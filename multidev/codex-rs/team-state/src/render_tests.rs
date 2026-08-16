use super::*;
use crate::ids::TeamRevision;
use crate::test_support::TeamFixture;
use crate::test_support::append;
use crate::test_support::new_event;
use crate::test_support::submission;
use pretty_assertions::assert_eq;

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
fn a_request_with_almost_no_room_left_skips_the_projection_entirely() {
    let (store, root) = fixture_with_chain(4);
    let snapshot = store.snapshot_for(root).expect("root view");
    let budget = ProjectionBudget::from_remaining_context(Some(2_100));

    assert!(budget.is_exhausted());
    assert_eq!(render_active_world_index(&snapshot, budget), None);
}

#[test]
fn the_budget_is_capped_regardless_of_how_much_room_the_request_has() {
    assert_eq!(
        ProjectionBudget::from_remaining_context(Some(10_000_000)).max_tokens(),
        MAX_PROJECTION_TOKENS
    );
}
