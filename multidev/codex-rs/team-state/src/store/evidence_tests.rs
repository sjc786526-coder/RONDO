use super::*;
use crate::evidence::RetainedOutputKind;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::model::ParticipantRole;
use crate::mutation::PublishOutcome;
use crate::mutation::RouteIntent;
use crate::test_support::TeamFixture;
use crate::test_support::append;
use crate::test_support::new_event;
use crate::test_support::register_member;
use crate::test_support::route as route_request;
use crate::test_support::submission;
use crate::view::HistoryQuery;
use pretty_assertions::assert_eq;

fn locator(call_id: &str, tool: &str) -> ObservationLocator {
    ObservationLocator {
        call_id: call_id.to_string(),
        output_kind: RetainedOutputKind::FunctionCallOutput,
        tool: tool.to_string(),
    }
}

/// Note an observation and immediately confirm its retention, as the capture layer does for a
/// supported tool result that reached history.
fn observe(store: &mut TeamStore, producer: ThreadId, call_id: &str) -> FactId {
    store.note_observation(
        producer,
        FactCategory::ToolResultSuccess,
        locator(call_id, "shell_command"),
    );
    store
        .confirm_observation(producer, call_id)
        .expect("a noted observation mints a fact once retention is confirmed")
}

// --- capture ----------------------------------------------------------------------------------

#[test]
fn an_observation_becomes_a_fact_only_once_its_retention_is_confirmed() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    store.note_observation(
        worker,
        FactCategory::ToolResultSuccess,
        locator("call-1", "shell_command"),
    );
    let published_before_confirmation = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w-0"),
            new_event(
                "checked the report",
                "the nightly report selects both columns",
            ),
        )
        .expect("worker may publish");
    assert_eq!(
        published_before_confirmation.evidence_refs,
        Vec::new(),
        "an unconfirmed observation is not evidence yet"
    );

    let fact_id = store
        .confirm_observation(worker, "call-1")
        .expect("confirming retention mints the fact");
    let published_after = store
        .publish(
            worker,
            &submission(store.revision(), "w-1"),
            append(published_before_confirmation.event_id, "and it breaks"),
        )
        .expect("worker may append");
    assert_eq!(published_after.evidence_refs, vec![fact_id]);
}

#[test]
fn facts_are_numbered_in_confirmed_retention_order_rather_than_completion_order() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    // Two tool calls complete in one order and are retained in the other, which is what a parallel
    // pair of calls can do. The numbering has to follow retention, since that is the order the same
    // trajectory reproduces.
    store.note_observation(
        worker,
        FactCategory::ToolResultSuccess,
        locator("second", "shell_command"),
    );
    store.note_observation(
        root,
        FactCategory::ToolResultFailure,
        locator("first", "shell_command"),
    );
    let first = store
        .confirm_observation(root, "first")
        .expect("the root's result was retained first");
    let second = store
        .confirm_observation(worker, "second")
        .expect("the worker's result was retained second");

    assert_eq!((first.ordinal(), second.ordinal()), (1, 2));
    assert_eq!(
        store
            .publish(
                worker,
                &submission(TeamRevision::INITIAL, "w-0"),
                new_event("finding", "the worker's own observation"),
            )
            .expect("worker may publish")
            .evidence_refs,
        vec![second],
        "another participant's evidence never enters this author's window"
    );
}

/// The single mechanism by which everything outside the support set is excluded.
///
/// An abandoned call, a streaming increment, a media result, a nested code-mode step and a team
/// tool's own output all reach retention without ever having been noted. Retention on its own never
/// mints anything, so each of those exclusions is settled by not noting it rather than by a second
/// filter that could disagree with the first.
#[test]
fn a_retained_result_that_was_never_noted_mints_nothing() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    assert_eq!(store.confirm_observation(worker, "call-never-noted"), None);
    assert!(store.facts.is_empty());
}

/// Replaying the same trajectory produces the same observation-to-publication association.
///
/// Compared as `(publication, position within its author's window)` rather than by identifier: a new
/// team instance mints new identities on purpose, and requiring the old ones back would break the
/// reset semantics the instance tag exists to enforce.
#[test]
fn replaying_a_trajectory_associates_the_same_observations_with_the_same_publications() {
    fn run() -> Vec<Vec<u32>> {
        let TeamFixture {
            mut store,
            root,
            worker,
        } = TeamFixture::new();
        let mut windows = Vec::new();
        // Two of the worker's observations, then a publish; then one each and a publish from both.
        observe(&mut store, worker, "w-call-1");
        observe(&mut store, worker, "w-call-2");
        let opened = store
            .publish(
                worker,
                &submission(TeamRevision::INITIAL, "w-0"),
                new_event("first finding", "what the first two checks showed"),
            )
            .expect("worker may publish");
        windows.push(
            opened
                .evidence_refs
                .iter()
                .map(FactId::ordinal)
                .collect::<Vec<_>>(),
        );
        observe(&mut store, root, "r-call-1");
        observe(&mut store, worker, "w-call-3");
        windows.push(
            store
                .publish(
                    root,
                    &submission(store.revision(), "r-0"),
                    append(opened.event_id, "what the root saw"),
                )
                .expect("root may append")
                .evidence_refs
                .iter()
                .map(FactId::ordinal)
                .collect(),
        );
        windows.push(
            store
                .publish(
                    worker,
                    &submission(store.revision(), "w-1"),
                    append(opened.event_id, "and what the third check showed"),
                )
                .expect("worker may append")
                .evidence_refs
                .iter()
                .map(FactId::ordinal)
                .collect(),
        );
        windows
    }

    assert_eq!(run(), run());
    assert_eq!(
        run(),
        vec![vec![1, 2], vec![3], vec![4]],
        "each publication carries exactly the observations recorded for its author since the last one"
    );
}

#[test]
fn a_result_from_an_unregistered_session_never_becomes_evidence() {
    let TeamFixture { mut store, .. } = TeamFixture::new();
    let stranger = ThreadId::new();

    store.note_observation(
        stranger,
        FactCategory::ToolResultSuccess,
        locator("call-1", "shell_command"),
    );

    assert_eq!(store.confirm_observation(stranger, "call-1"), None);
}

#[test]
fn confirming_the_same_call_twice_mints_one_fact() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let fact_id = observe(&mut store, worker, "call-1");

    assert_eq!(store.confirm_observation(worker, "call-1"), None);
    assert_eq!(
        store.facts.iter().map(TeamFact::id).collect::<Vec<_>>(),
        vec![fact_id]
    );
}

#[test]
fn unconfirmed_observations_stay_bounded() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    for index in 0..MAX_PENDING_OBSERVATIONS + 10 {
        store.note_observation(
            worker,
            FactCategory::ToolResultSuccess,
            locator(&format!("call-{index}"), "shell_command"),
        );
    }

    assert_eq!(store.pending_observations.len(), MAX_PENDING_OBSERVATIONS);
    assert_eq!(
        store.confirm_observation(worker, "call-0"),
        None,
        "the oldest unconfirmed observations are dropped rather than accumulating"
    );
    assert!(
        store
            .confirm_observation(worker, &format!("call-{}", MAX_PENDING_OBSERVATIONS + 9))
            .is_some(),
        "the newest is still there"
    );
}

// --- the publication window -------------------------------------------------------------------

#[test]
fn each_publish_carries_only_what_arrived_since_the_last_successful_one() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let first = observe(&mut store, worker, "call-1");
    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w-0"),
            new_event("first finding", "what the first check showed"),
        )
        .expect("worker may publish");
    assert_eq!(opened.evidence_refs, vec![first]);

    let second = observe(&mut store, worker, "call-2");
    let appended = store
        .publish(
            worker,
            &submission(store.revision(), "w-1"),
            append(opened.event_id, "what the second check showed"),
        )
        .expect("worker may append");

    assert_eq!(
        appended.evidence_refs,
        vec![second],
        "the first publish consumed the first observation"
    );
}

#[test]
fn a_publish_with_no_new_observations_is_still_accepted() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w-0"),
            new_event("a judgement", "no tool was needed for this"),
        )
        .expect("an empty window is not a reason to refuse a legitimate version");

    assert_eq!(opened.evidence_refs, Vec::new());
}

#[test]
fn a_refused_publish_leaves_the_window_intact() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let fact_id = observe(&mut store, worker, "call-1");
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w-bad"),
            new_event("", "a title is required to open an event"),
        )
        .expect_err("the publish is refused before it commits");

    assert_eq!(
        store
            .publish(
                worker,
                &submission(TeamRevision::INITIAL, "w-0"),
                new_event("second attempt", "same finding, valid this time"),
            )
            .expect("worker may publish")
            .evidence_refs,
        vec![fact_id],
        "a failure that never committed cannot have consumed the evidence"
    );
}

#[test]
fn a_retry_reports_the_references_it_committed_with() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let fact_id = observe(&mut store, worker, "call-1");
    let request = new_event("finding", "what the check showed");
    let first = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w-0"),
            request.clone(),
        )
        .expect("worker may publish");
    // Another observation lands while the caller is retrying, which must not join the version that
    // was already committed.
    let later = observe(&mut store, worker, "call-2");
    let retry = store
        .publish(worker, &submission(TeamRevision::INITIAL, "w-0"), request)
        .expect("a repeated submission is answered from the committed one");

    assert_eq!(
        retry,
        PublishOutcome {
            deduplicated: true,
            ..first
        }
    );
    assert_eq!(retry.evidence_refs, vec![fact_id]);
    assert_eq!(
        store
            .publish(
                worker,
                &submission(store.revision(), "w-1"),
                append(first.event_id, "and here is the follow-up"),
            )
            .expect("worker may append")
            .evidence_refs,
        vec![later],
        "the observation that arrived during the retry is left for the next publish"
    );
}

#[test]
fn a_reloaded_member_keeps_the_window_it_already_advanced() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let first = observe(&mut store, worker, "call-1");
    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w-0"),
            new_event("finding", "what the check showed"),
        )
        .expect("worker may publish");
    assert_eq!(opened.evidence_refs, vec![first]);

    // Unloaded and reloaded inside the same live root tree: the same registration call comes back.
    assert!(!store.register_participant(
        worker,
        ParticipantRole::Member,
        "/root/worker".to_string()
    ));
    let after_reload = observe(&mut store, worker, "call-2");

    assert_eq!(
        store
            .publish(
                worker,
                &submission(store.revision(), "w-1"),
                append(opened.event_id, "more of the same"),
            )
            .expect("worker may append")
            .evidence_refs,
        vec![after_reload],
        "a reload must not replay evidence the participant already published"
    );
}

#[test]
fn a_participant_that_joins_later_does_not_inherit_earlier_evidence() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    observe(&mut store, worker, "call-1");
    observe(&mut store, root, "call-2");
    let latecomer = register_member(&mut store, "/root/latecomer");

    assert_eq!(
        store
            .publish(
                latecomer,
                &submission(TeamRevision::INITIAL, "l-0"),
                new_event("late finding", "nothing observed yet"),
            )
            .expect("the latecomer may publish")
            .evidence_refs,
        Vec::new()
    );
}

// --- read permission --------------------------------------------------------------------------

#[test]
fn a_producer_and_the_root_may_read_a_fact_the_producer_recorded() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let fact_id = observe(&mut store, worker, "call-1");

    assert_eq!(
        store
            .read_fact(worker, fact_id)
            .expect("its own producer")
            .id,
        fact_id
    );
    let root_view = store
        .read_fact(root, fact_id)
        .expect("the root reads its team's evidence");
    assert_eq!(
        (root_view.producer, root_view.producer_label.as_str()),
        (worker, "/root/worker")
    );
}

#[test]
fn a_member_cannot_read_a_siblings_fact_by_naming_it() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let sibling = register_member(&mut store, "/root/sibling");

    let worker_fact = observe(&mut store, worker, "call-1");
    let root_fact = observe(&mut store, root, "call-2");

    assert_eq!(
        store.read_fact(sibling, worker_fact),
        Err(TeamError::NotPermitted {
            reason: "this evidence was not produced by you and is not referenced by any team event you can see",
        })
    );
    assert_eq!(
        store.read_fact(sibling, root_fact),
        Err(TeamError::NotPermitted {
            reason: "this evidence was not produced by you and is not referenced by any team event you can see",
        })
    );
}

#[test]
fn a_routed_member_reads_the_evidence_that_event_references_and_nothing_else() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let referenced = observe(&mut store, root, "call-1");
    let opened = store
        .publish(
            root,
            &submission(TeamRevision::INITIAL, "r-0"),
            new_event("migration review", "two columns were renamed"),
        )
        .expect("root may publish");
    assert_eq!(opened.evidence_refs, vec![referenced]);
    // A second observation the root never published: seeing one of the root's facts must not open
    // the rest of them.
    let unreferenced = observe(&mut store, root, "call-2");

    let based_on = store.revision();
    store
        .route(
            root,
            &submission(based_on, "r-route"),
            route_request(opened.event_id, worker, RouteIntent::Assign),
        )
        .expect("root may route");

    assert_eq!(
        store
            .read_fact(worker, referenced)
            .expect("the routed event explicitly references this")
            .id,
        referenced
    );
    assert_eq!(
        store.read_fact(worker, unreferenced),
        Err(TeamError::NotPermitted {
            reason: "this evidence was not produced by you and is not referenced by any team event you can see",
        })
    );
}

#[test]
fn a_fact_reference_from_another_instance_is_refused_rather_than_resolved() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();
    let fact_id = observe(&mut store, worker, "call-1");
    let stale = FactId::new(TeamInstanceId::new().tag(), fact_id.ordinal());

    let Err(TeamError::InstanceReset {
        referenced_instance,
        current_instance,
    }) = store.read_fact(worker, stale)
    else {
        panic!("a reference from another instance must report the reset");
    };
    assert_ne!(referenced_instance, current_instance);
}

#[test]
fn a_well_formed_reference_to_nothing_is_reported_as_unknown() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();
    observe(&mut store, worker, "call-1");
    let never_minted = FactId::new(store.tag, 99);

    assert_eq!(
        store.read_fact(worker, never_minted),
        Err(TeamError::UnknownReference {
            reference: never_minted.to_string(),
        })
    );
}

// --- honest degradation -----------------------------------------------------------------------

#[test]
fn a_lost_observation_keeps_its_reference_and_is_labelled_unavailable() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let fact_id = observe(&mut store, worker, "call-1");
    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w-0"),
            new_event("finding", "what the check showed"),
        )
        .expect("worker may publish");
    store
        .mark_fact_unavailable(root, fact_id)
        .expect("the root may write off evidence it can read");

    let view = store.read_fact(root, fact_id).expect("the reference stays");
    assert_eq!(view.availability, FactAvailability::Unavailable);
    assert_eq!(
        store
            .history(
                root,
                &HistoryQuery {
                    event_id: Some(opened.event_id),
                    ..Default::default()
                },
            )
            .expect("root may read history")
            .events[0]
            .event
            .versions[0]
            .evidence_refs,
        vec![fact_id],
        "authored content never changes, so the reference is still there to explain"
    );
}

#[test]
fn writing_off_a_fact_needs_the_same_permission_as_reading_it() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();
    let sibling = register_member(&mut store, "/root/sibling");
    let fact_id = observe(&mut store, worker, "call-1");

    assert_eq!(
        store.mark_fact_unavailable(sibling, fact_id),
        Err(TeamError::NotPermitted {
            reason: "this evidence was not produced by you and is not referenced by any team event you can see",
        })
    );
    assert_eq!(
        store
            .read_fact(worker, fact_id)
            .expect("still readable by its producer")
            .availability,
        FactAvailability::Available
    );
}
