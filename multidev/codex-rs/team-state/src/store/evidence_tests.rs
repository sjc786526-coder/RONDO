use super::*;
use crate::evidence::FactCategory;
use crate::evidence::MAX_REPORTED_EVIDENCE_REFS;
use crate::evidence::NotedObservation;
use crate::evidence::reported_evidence_refs;
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

fn noted(call_id: &str, tool: &str) -> NotedObservation {
    NotedObservation {
        item_id: item_of(call_id),
        call_id: call_id.to_string(),
        category: FactCategory::ToolResultSuccess,
        tool: tool.to_string(),
    }
}

/// The identity Codex would assign the item that carries this call's output.
fn item_of(call_id: &str) -> String {
    format!("fco_{call_id}")
}

/// Note an observation and immediately confirm its retention, as the capture layer does for a
/// supported tool result that reached history.
fn observe(store: &mut TeamStore, producer: ThreadId, call_id: &str) -> FactId {
    store.note_observation(producer, noted(call_id, "shell_command"));
    store
        .confirm_observation(producer, &item_of(call_id))
        .expect("a noted observation mints a fact once retention is confirmed")
}

// --- capture ----------------------------------------------------------------------------------

#[test]
fn an_observation_becomes_a_fact_only_once_its_retention_is_confirmed() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    store.note_observation(worker, noted("call-1", "shell_command"));
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
        .confirm_observation(worker, &item_of("call-1"))
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
    store.note_observation(worker, noted("second", "shell_command"));
    store.note_observation(
        root,
        NotedObservation {
            category: FactCategory::ToolResultFailure,
            ..noted("first", "shell_command")
        },
    );
    let first = store
        .confirm_observation(root, &item_of("first"))
        .expect("the root's result was retained first");
    let second = store
        .confirm_observation(worker, &item_of("second"))
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

/// Retention on its own never mints anything.
///
/// This is the shape of the exclusion, not proof of any particular exclusion: which results get
/// noted is decided in the capture layer, and the cases it turns away are covered there.
#[test]
fn a_retained_result_that_was_never_noted_mints_nothing() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    assert_eq!(
        store.confirm_observation(worker, &item_of("call-never-noted")),
        None
    );
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

    store.note_observation(stranger, noted("call-1", "shell_command"));

    assert_eq!(
        store.confirm_observation(stranger, &item_of("call-1")),
        None
    );
}

#[test]
fn confirming_the_same_call_twice_mints_one_fact() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let fact_id = observe(&mut store, worker, "call-1");

    assert_eq!(store.confirm_observation(worker, &item_of("call-1")), None);
    assert_eq!(
        store.facts.iter().map(TeamFact::id).collect::<Vec<_>>(),
        vec![fact_id]
    );
}

/// Pending observations are short-lived staging records, but a burst cannot be truncated: every
/// supported result that is subsequently retained still has to become a fact.
#[test]
fn more_than_256_pending_observations_are_all_confirmable() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    const OBSERVATION_COUNT: usize = 266;
    store.note_observation(root, noted("root-call", "shell_command"));
    for index in 0..OBSERVATION_COUNT {
        store.note_observation(worker, noted(&format!("call-{index}"), "shell_command"));
    }

    assert_eq!(
        store
            .pending_observations
            .iter()
            .filter(|pending| pending.producer == worker)
            .count(),
        OBSERVATION_COUNT,
        "staging must not silently drop a supported result before retention"
    );
    let confirmed = (0..OBSERVATION_COUNT)
        .filter_map(|index| store.confirm_observation(worker, &item_of(&format!("call-{index}"))))
        .count();
    assert_eq!(confirmed, OBSERVATION_COUNT);
    assert!(
        store
            .confirm_observation(root, &item_of("root-call"))
            .is_some(),
        "another producer's pending note is independent too"
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

/// A participant publishes from its own first observation, not from the team's.
///
/// The guarantee comes from the window filtering on producer, plus the rule that an unregistered
/// session cannot leave a note at all — so a participant provably has no evidence from before it
/// joined, and the first thing it observes afterwards is the first thing it can publish.
#[test]
fn a_participant_that_joins_later_publishes_from_its_own_first_observation() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    observe(&mut store, worker, "call-1");
    observe(&mut store, root, "call-2");
    let latecomer = register_member(&mut store, "/root/latecomer");

    let first = store
        .publish(
            latecomer,
            &submission(TeamRevision::INITIAL, "l-0"),
            new_event("late finding", "nothing observed yet"),
        )
        .expect("the latecomer may publish");
    assert_eq!(
        first.evidence_refs,
        Vec::new(),
        "the team's existing evidence is not the latecomer's to publish"
    );

    let own = observe(&mut store, latecomer, "call-3");
    assert_eq!(
        store
            .publish(
                latecomer,
                &submission(store.revision(), "l-1"),
                append(first.event_id, "and now I have looked"),
            )
            .expect("the latecomer may append")
            .evidence_refs,
        vec![own],
        "and its own first observation is the first thing it carries"
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

// --- discarded results and bounded windows ----------------------------------------------------

/// An interrupted call can still finish teardown and return an outcome the host then throws away in
/// favour of its own filler answer. The filler reaches history under the same call id, so the note
/// has to be revoked or the interrupted call becomes evidence.
#[test]
fn a_discarded_result_does_not_become_evidence_when_its_filler_is_retained() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    store.note_observation(
        worker,
        NotedObservation {
            category: FactCategory::ToolResultFailure,
            ..noted("call-1", "shell_command")
        },
    );
    store.discard_observation(worker, &item_of("call-1"));

    assert_eq!(store.confirm_observation(worker, &item_of("call-1")), None);
    assert!(store.facts.is_empty());
}

#[test]
fn discarding_one_call_leaves_the_others_alone() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    store.note_observation(worker, noted("call-1", "shell_command"));
    store.note_observation(worker, noted("call-2", "shell_command"));
    store.discard_observation(worker, &item_of("call-1"));

    assert_eq!(store.confirm_observation(worker, &item_of("call-1")), None);
    assert!(
        store
            .confirm_observation(worker, &item_of("call-2"))
            .is_some()
    );
}

/// The harness item identity pairs each completion note with its retained result, even when two
/// calls reuse one model-provided id and retention observes them in the opposite order.
#[test]
fn concurrent_reused_call_ids_pair_metadata_with_their_own_retained_items() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    store.note_observation(
        worker,
        NotedObservation {
            item_id: "fco_first-item".to_string(),
            tool: "first_tool".to_string(),
            ..noted("call-1", "first_tool")
        },
    );
    store.note_observation(
        worker,
        NotedObservation {
            item_id: "fco_second-item".to_string(),
            category: FactCategory::ToolResultFailure,
            ..noted("call-1", "second_tool")
        },
    );
    let second = store
        .confirm_observation(worker, "fco_second-item")
        .expect("the second retained item finds its own pending metadata");
    let first = store
        .confirm_observation(worker, "fco_first-item")
        .expect("the first retained item remains independently confirmable");

    assert_ne!(first, second);
    let locators = [second, first].map(|id| {
        let view = store
            .read_fact(worker, id)
            .expect("its producer may read it");
        (view.category, view.locator.item_id, view.locator.tool)
    });
    assert_eq!(
        locators,
        [
            (
                FactCategory::ToolResultFailure,
                "fco_second-item".to_string(),
                "second_tool".to_string()
            ),
            (
                FactCategory::ToolResultSuccess,
                "fco_first-item".to_string(),
                "first_tool".to_string()
            ),
        ],
        "each fact describes and points at its own item, so neither can answer with the other's text"
    );
}

/// A publication window is never truncated.
///
/// Consuming an observation without anchoring it would lose it for good: the cursor has moved past it,
/// so no later publish can pick it up. Bounding what an answer prints is a separate job, done by
/// [`crate::evidence::reported_evidence_refs`] at the surfaces that print it.
#[test]
fn a_version_anchors_every_observation_its_window_consumed() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let mut all = Vec::new();
    for index in 0..MAX_REPORTED_EVIDENCE_REFS + 5 {
        all.push(observe(&mut store, worker, &format!("call-{index}")));
    }

    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w-0"),
            new_event("checked everything", "here is what all of that showed"),
        )
        .expect("worker may publish");

    assert_eq!(
        opened.evidence_refs, all,
        "every observation the window consumed is anchored to the version that consumed it"
    );
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
        all,
        "and the canonical record hands all of them back"
    );

    // What a context budget bounds is the printing, and it says how much it left out.
    let (reported, omitted) = reported_evidence_refs(&opened.evidence_refs);
    assert_eq!(reported.len(), MAX_REPORTED_EVIDENCE_REFS);
    assert_eq!(omitted, 5);
    assert_eq!(reported, &all[..MAX_REPORTED_EVIDENCE_REFS]);

    let next = observe(&mut store, worker, "call-later");
    assert_eq!(
        store
            .publish(
                worker,
                &submission(store.revision(), "w-1"),
                append(opened.event_id, "and then this"),
            )
            .expect("worker may append")
            .evidence_refs,
        vec![next]
    );
}
