use super::*;
use crate::ids::TeamRevision;
use crate::test_support::TeamFixture;
use crate::test_support::append;
use crate::test_support::new_event;
use crate::test_support::submission;
use crate::view::TeamSnapshot;
use pretty_assertions::assert_eq;

fn rendered(snapshot: &TeamSnapshot, budget: ProjectionBudget) -> RenderedProjection {
    match render_active_world_index(snapshot, budget) {
        ProjectionOutcome::Rendered(rendered) => rendered,
        other => panic!("expected a rendered projection, got {other:?}"),
    }
}

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
        ProjectionOutcome::Idle
    );
}

#[test]
fn a_generous_budget_renders_the_whole_chain() {
    let (store, root) = fixture_with_chain(4);
    let snapshot = store.snapshot_for(root).expect("root view");

    let projection = rendered(&snapshot, ProjectionBudget::from_remaining_context(None));

    assert!(projection.omissions.is_empty());
    for index in 0..4 {
        assert!(
            projection.text.contains(&format!("entry {index} ")),
            "entry {index} should be present in {}",
            projection.text
        );
    }
}

/// A participant has to be able to see that an entry has evidence before it can ask for any, so the
/// references travel in the view. A publication window has no fixed size, so the list they form does.
#[test]
fn a_versions_evidence_is_named_in_the_view_and_stays_bounded() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let mut expected = Vec::new();
    for index in 0..MAX_PROJECTED_EVIDENCE_REFS + 3 {
        store.note_observation(
            worker,
            crate::evidence::FactCategory::ToolResultSuccess,
            crate::evidence::ObservationLocator {
                call_id: format!("call-{index}"),
                output_kind: crate::evidence::RetainedOutputKind::FunctionCallOutput,
                tool: "shell_command".to_string(),
            },
        );
        expected.push(
            store
                .confirm_observation(worker, &format!("call-{index}"))
                .expect("retention was confirmed"),
        );
    }
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w0"),
            new_event("checked everything", "here is what all of that showed"),
        )
        .expect("worker may publish");
    let snapshot = store.snapshot_for(root).expect("root view");

    let projection = rendered(&snapshot, ProjectionBudget::from_remaining_context(None));

    for reference in expected.iter().take(MAX_PROJECTED_EVIDENCE_REFS) {
        assert!(
            projection.text.contains(&reference.to_string()),
            "{reference} should be named in:\n{}",
            projection.text
        );
    }
    assert!(
        projection
            .text
            .contains("(+3 more, read with team_history)"),
        "the rest is counted rather than dropped in silence:\n{}",
        projection.text
    );
    for reference in expected.iter().skip(MAX_PROJECTED_EVIDENCE_REFS) {
        assert!(
            !projection.text.contains(&reference.to_string()),
            "{reference} is past the cap and must not be named:\n{}",
            projection.text
        );
    }
}

#[test]
fn a_tight_budget_drops_the_oldest_entries_and_says_so() {
    let (store, root) = fixture_with_chain(8);
    let snapshot = store.snapshot_for(root).expect("root view");

    let projection = rendered(
        &snapshot,
        ProjectionBudget::from_remaining_context(Some(3_500)),
    );

    assert!(
        !projection.omissions.is_empty(),
        "a projection that had to shed content must report it"
    );
    assert!(projection.text.contains("team_history"));
    assert!(
        projection.text.contains("entry 7"),
        "the newest entry is what coordination needs and must survive"
    );
    assert!(!projection.text.contains("entry 0 "));
}

/// The budget is a boundary, not a suggestion: nothing that comes back may exceed it, at any size
/// of content and at any amount of remaining room.
#[test]
fn whatever_comes_back_always_fits_the_budget() {
    let (many, many_root) = fixture_with_chain(12);
    // One entry far larger than any budget, so shedding cannot rescue it.
    let TeamFixture {
        mut store,
        root: long_root,
        worker,
    } = TeamFixture::new();
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w0"),
            new_event("runaway", &"lorem ipsum dolor sit amet ".repeat(4_000)),
        )
        .expect("worker may publish");
    let snapshots = [
        many.snapshot_for(many_root).expect("root view"),
        store.snapshot_for(long_root).expect("root view"),
    ];

    for snapshot in &snapshots {
        for remaining in [0, 1_000, 2_050, 2_100, 2_500, 5_000, 40_000, 400_000] {
            let budget = ProjectionBudget::from_remaining_context(Some(remaining));
            if let ProjectionOutcome::Rendered(projection) =
                render_active_world_index(snapshot, budget)
            {
                assert!(
                    projection.estimated_tokens <= budget.max_tokens(),
                    "remaining={remaining} produced {} tokens against a budget of {}",
                    projection.estimated_tokens,
                    budget.max_tokens()
                );
            }
        }
    }
}

/// Squeezed, but still honest: whatever survives has to point at what did not.
#[test]
fn a_squeezed_view_names_what_it_dropped() {
    let (store, root) = fixture_with_chain(8);
    let snapshot = store.snapshot_for(root).expect("root view");

    let projection = rendered(
        &snapshot,
        ProjectionBudget::from_remaining_context(Some(3_000)),
    );

    assert!(!projection.omissions.is_empty());
    assert!(
        projection.text.contains("team_history"),
        "a squeezed view has to say where the rest went: {projection:?}"
    );
}

/// When there is no room at all the renderer says so rather than overrunning or pretending the
/// team is idle; making room is the caller's job.
#[test]
fn no_room_is_reported_rather_than_overrunning_or_faking_an_idle_team() {
    let (store, root) = fixture_with_chain(4);
    let snapshot = store.snapshot_for(root).expect("root view");

    let outcome = render_active_world_index(
        &snapshot,
        ProjectionBudget::from_remaining_context(Some(2_050)),
    );

    assert_eq!(outcome, ProjectionOutcome::NoRoom { active_events: 1 });
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
