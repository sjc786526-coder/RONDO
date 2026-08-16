use super::*;
use crate::ids::TeamRevision;
use crate::test_support::TeamFixture;
use crate::test_support::append;
use crate::test_support::new_event;
use crate::test_support::submission;
use pretty_assertions::assert_eq;

/// Upper bound on the irreducible notice, which is the one thing allowed to exceed a tiny budget.
const MINIMUM_NOTICE_TOKENS: i64 = 64;

fn fixture_with_chain(entries: usize) -> (crate::store::TeamStore, codex_protocol::ThreadId) {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w0"),
            new_event(
                "integration drift",
                "entry 0 with enough text to cost tokens",
            ),
        )
        .expect("worker may publish");
    for index in 1..entries {
        store
            .publish(
                worker,
                &submission(store.revision(), &format!("w{index}")),
                append(
                    opened.event_id,
                    &format!(
                        "entry {index} with enough text to cost a measurable number of tokens"
                    ),
                ),
            )
            .expect("worker may append");
    }
    (store, root)
}

#[test]
fn an_idle_team_renders_nothing() {
    let TeamFixture { store, root, .. } = TeamFixture::new();
    let snapshot = store.snapshot_for(root).expect("root view");

    assert_eq!(
        render_active_world_index(&snapshot, ProjectionBudget::from_remaining_context(None)),
        None
    );
}

#[test]
fn a_generous_budget_renders_the_whole_chain() {
    let (store, root) = fixture_with_chain(4);
    let snapshot = store.snapshot_for(root).expect("root view");

    let rendered =
        render_active_world_index(&snapshot, ProjectionBudget::from_remaining_context(None))
            .expect("an active team renders");

    assert!(rendered.omissions.is_empty());
    for index in 0..4 {
        assert!(
            rendered.text.contains(&format!("entry {index} ")),
            "entry {index} should be present in {}",
            rendered.text
        );
    }
}

#[test]
fn a_tight_budget_drops_the_oldest_entries_and_says_so() {
    let (store, root) = fixture_with_chain(8);
    let snapshot = store.snapshot_for(root).expect("root view");

    let rendered = render_active_world_index(
        &snapshot,
        ProjectionBudget::from_remaining_context(Some(3_500)),
    )
    .expect("an active team renders");

    assert!(
        !rendered.omissions.is_empty(),
        "a projection that had to shed content must report it"
    );
    assert!(rendered.text.contains("team_history"));
    assert!(
        rendered.text.contains("entry 7"),
        "the newest entry is what coordination needs and must survive"
    );
    assert!(!rendered.text.contains("entry 0 "));
}

#[test]
fn the_projection_never_exceeds_the_budget_it_was_given() {
    let (store, root) = fixture_with_chain(12);
    let snapshot = store.snapshot_for(root).expect("root view");

    for remaining in [3_000, 6_000, 20_000, 200_000] {
        let budget = ProjectionBudget::from_remaining_context(Some(remaining));
        let Some(rendered) = render_active_world_index(&snapshot, budget) else {
            continue;
        };
        assert!(
            rendered.estimated_tokens <= budget.max_tokens(),
            "remaining={remaining} produced {} tokens against a budget of {}",
            rendered.estimated_tokens,
            budget.max_tokens()
        );
    }
}

#[test]
fn a_request_with_almost_no_room_left_still_says_the_team_has_active_items() {
    let (store, root) = fixture_with_chain(4);
    let snapshot = store.snapshot_for(root).expect("root view");
    let budget = ProjectionBudget::from_remaining_context(Some(2_100));

    let rendered = render_active_world_index(&snapshot, budget)
        .expect("an active view must never vanish just because the request is tight");

    assert!(
        rendered.estimated_tokens <= budget.max_tokens().max(MINIMUM_NOTICE_TOKENS),
        "the cap still holds: {} tokens against a budget of {}",
        rendered.estimated_tokens,
        budget.max_tokens()
    );
    assert!(
        !rendered.omissions.is_empty(),
        "and what was left out has to be stated: {rendered:?}"
    );
    assert!(
        rendered.text.contains("team_history"),
        "a squeezed view still has to point at where the content went: {rendered:?}"
    );
}

#[test]
fn one_oversized_entry_cannot_break_the_cap() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    // A single entry far larger than any budget. Shedding cannot help here: there is nothing else
    // to drop, so the renderer has to give way rather than overrun.
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w0"),
            new_event("runaway", &"lorem ipsum dolor sit amet ".repeat(4_000)),
        )
        .expect("worker may publish");
    let snapshot = store.snapshot_for(root).expect("root view");

    let stored_summary = snapshot.events[0].versions[0].summary.clone();
    for remaining in [2_500, 5_000, 40_000, 400_000] {
        let budget = ProjectionBudget::from_remaining_context(Some(remaining));
        let rendered =
            render_active_world_index(&snapshot, budget).expect("the active item is reported");
        // The floor notice is allowed to exceed a pathologically small budget; everything above
        // that floor must respect it.
        assert!(
            rendered.estimated_tokens <= budget.max_tokens().max(MINIMUM_NOTICE_TOKENS),
            "remaining={remaining} produced {} tokens against a budget of {}",
            rendered.estimated_tokens,
            budget.max_tokens()
        );
        assert!(
            rendered.text.contains("team_history") || rendered.text.contains(&stored_summary),
            "remaining={remaining} produced a view that neither shows the item nor points at it"
        );
        // Whenever the entry did not survive intact, the projection has to say so rather than
        // quietly present a partial view as the whole picture.
        if !rendered.text.contains(&stored_summary) {
            assert!(
                !rendered.omissions.is_empty(),
                "remaining={remaining} dropped content without saying so"
            );
        }
    }
}

#[test]
fn authored_content_is_bounded_when_it_is_written() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w0"),
            new_event("t", &"x".repeat(50_000)),
        )
        .expect("worker may publish");

    let stored = store
        .snapshot_for(worker)
        .expect("worker view")
        .events
        .into_iter()
        .flat_map(|event| event.versions)
        .find(|version| version.id == published.version_id)
        .expect("the version exists");
    assert!(
        stored.summary.chars().count() < 50_000,
        "the store must not hold an unbounded authored field"
    );
    assert!(
        stored.summary.contains("truncated"),
        "and the cut has to be visible in the record itself"
    );
}

#[test]
fn the_budget_is_capped_regardless_of_how_much_room_the_request_has() {
    assert_eq!(
        ProjectionBudget::from_remaining_context(Some(10_000_000)).max_tokens(),
        MAX_PROJECTION_TOKENS
    );
}
