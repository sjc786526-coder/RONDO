use super::*;
use crate::ids::EventId;
use crate::ids::TeamRevision;
use crate::mutation::PublishOutcome;
use crate::test_support::TeamFixture;
use crate::test_support::append;
use crate::test_support::new_event;
use crate::test_support::register_member;
use crate::test_support::route as route_request;
use crate::test_support::submission;
use crate::view::HistoryQuery;
use pretty_assertions::assert_eq;

/// A root-authored event the worker has never seen.
fn root_event(store: &mut TeamStore, root: ThreadId) -> PublishOutcome {
    store
        .publish(
            root,
            &submission(TeamRevision::INITIAL, "r-open"),
            new_event("migration review", "two columns were renamed"),
        )
        .expect("root may publish")
}

fn assign(
    store: &mut TeamStore,
    root: ThreadId,
    event_id: EventId,
    target: ThreadId,
    request_id: &str,
) -> RouteOutcome {
    let based_on = store.revision();
    store
        .route(
            root,
            &submission(based_on, request_id),
            route_request(event_id, target, RouteIntent::Assign),
        )
        .expect("the root may route")
}

fn active_event_ids(store: &TeamStore, viewer: ThreadId) -> Vec<EventId> {
    store
        .snapshot_for(viewer)
        .expect("viewer is registered")
        .events
        .iter()
        .map(|event| event.id)
        .collect()
}

// --- the grant --------------------------------------------------------------------------------

#[test]
fn a_route_makes_the_event_readable_and_contributable_for_its_target() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);

    // Before the route the worker cannot reach the event at all, even knowing its identifier.
    assert_eq!(
        store
            .history(
                worker,
                &HistoryQuery {
                    event_id: Some(event.event_id),
                    limit: None,
                    before: None,
                },
            )
            .expect_err("not routed yet"),
        TeamError::NotPermitted {
            reason: "this event is not visible to you"
        }
    );

    assign(&mut store, root, event.event_id, worker, "r1");

    let page = store
        .history(
            worker,
            &HistoryQuery {
                event_id: Some(event.event_id),
                limit: None,
                before: None,
            },
        )
        .expect("the route made the whole chain readable");
    assert_eq!(page.events[0].total_versions, 1);

    let appended = store
        .publish(
            worker,
            &submission(store.revision(), "w1"),
            append(event.event_id, "checked both columns against production"),
        )
        .expect("the route made the worker eligible to contribute");
    assert_eq!(appended.event_id, event.event_id);
    assert_eq!(store.events.len(), 1, "no second canonical event was made");
    assert_eq!(store.events[0].versions().len(), 2);
}

#[test]
fn a_multi_author_chain_stays_under_one_event_and_both_authors_see_all_of_it() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    assign(&mut store, root, event.event_id, worker, "r1");
    store
        .publish(
            worker,
            &submission(store.revision(), "w1"),
            append(event.event_id, "the rename is safe"),
        )
        .expect("worker appends");

    let authors_seen_by = |store: &TeamStore, viewer: ThreadId| -> Vec<String> {
        store
            .history(
                viewer,
                &HistoryQuery {
                    event_id: Some(event.event_id),
                    limit: None,
                    before: None,
                },
            )
            .expect("visible")
            .events[0]
            .event
            .versions
            .iter()
            .map(|version| version.author_label.clone())
            .collect()
    };
    let expected = vec!["/root".to_string(), "/root/worker".to_string()];
    assert_eq!(authors_seen_by(&store, root), expected);
    assert_eq!(authors_seen_by(&store, worker), expected);
}

#[test]
fn visibility_outlives_the_assignment_that_carried_it() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let routed = assign(&mut store, root, event.event_id, worker, "r1");

    store
        .end_assignment(root, routed.dispatch.route_id)
        .expect("the root may end what it assigned");

    assert!(
        !active_event_ids(&store, worker).contains(&event.event_id),
        "no remaining reason to be active"
    );
    let page = store
        .history(
            worker,
            &HistoryQuery {
                event_id: Some(event.event_id),
                limit: None,
                before: None,
            },
        )
        .expect("an ended assignment does not take back what was shown");
    assert_eq!(page.events[0].total_versions, 1);
}

// --- who may route ----------------------------------------------------------------------------

#[test]
fn only_the_root_routes_events() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let other = register_member(&mut store, "/root/other");
    let event = root_event(&mut store, root);
    assign(&mut store, root, event.event_id, worker, "r1");
    let before = store.revision();

    let refused = store
        .route(
            worker,
            &submission(before, "w1"),
            route_request(event.event_id, other, RouteIntent::Assign),
        )
        .expect_err("a member cannot hand work around");
    assert_eq!(
        refused,
        TeamError::NotPermitted {
            reason: "only the root routes events; publish instead to make your work visible",
        }
    );
    assert_eq!(store.revision(), before, "a refusal leaves no trace");
    assert_eq!(store.events[0].routes().len(), 1);
}

#[test]
fn an_unknown_caller_and_an_unknown_target_both_fail_closed() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let stranger = ThreadId::new();
    let before = store.revision();

    assert_eq!(
        store
            .route(
                stranger,
                &submission(before, "x1"),
                route_request(event.event_id, worker, RouteIntent::Assign),
            )
            .expect_err("an unregistered caller has no team capability"),
        TeamError::UnknownParticipant
    );
    assert_eq!(
        store
            .route(
                root,
                &submission(before, "r1"),
                route_request(event.event_id, stranger, RouteIntent::Assign),
            )
            .expect_err("an unregistered target cannot be routed to"),
        TeamError::UnknownTarget
    );
    assert_eq!(store.revision(), before);
    assert!(store.events[0].routes().is_empty());
}

#[test]
fn a_reference_from_another_instance_and_an_unknown_event_are_both_refused() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    root_event(&mut store, root);
    let other_instance = TeamStore::new();
    let foreign = EventId::new(other_instance.instance().tag(), 1);
    let unknown = EventId::new(store.instance().tag(), 99);
    let before = store.revision();

    let reset = store
        .route(
            root,
            &submission(before, "r1"),
            route_request(foreign, worker, RouteIntent::Assign),
        )
        .expect_err("an old reference must not resolve here");
    assert_eq!(
        reset,
        TeamError::InstanceReset {
            referenced_instance: other_instance.instance().tag(),
            current_instance: store.instance().tag(),
        }
    );
    assert_eq!(
        store
            .route(
                root,
                &submission(before, "r2"),
                route_request(unknown, worker, RouteIntent::Assign),
            )
            .expect_err("nothing to route"),
        TeamError::UnknownReference {
            reference: unknown.to_string()
        }
    );
    assert_eq!(store.revision(), before);
}

#[test]
fn the_root_cannot_route_an_event_to_itself() {
    let TeamFixture {
        mut store, root, ..
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let before = store.revision();

    assert_eq!(
        store
            .route(
                root,
                &submission(before, "r1"),
                route_request(event.event_id, root, RouteIntent::Assign),
            )
            .expect_err("routing to yourself is not a hand-over"),
        TeamError::NotPermitted {
            reason: "an event cannot be routed to yourself"
        }
    );
    assert_eq!(store.revision(), before);
}

// --- idempotency ------------------------------------------------------------------------------

#[test]
fn a_repeated_route_submission_returns_the_original_grant() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let first = assign(&mut store, root, event.event_id, worker, "r1");
    let after_first = store.revision();

    let repeat = store
        .route(
            root,
            &submission(TeamRevision::INITIAL, "r1"),
            route_request(event.event_id, worker, RouteIntent::Assign),
        )
        .expect("a retry succeeds");

    assert_eq!(repeat.dispatch.route_id, first.dispatch.route_id);
    assert!(repeat.deduplicated);
    assert_eq!(store.revision(), after_first);
    assert_eq!(store.events[0].routes().len(), 1);
}

#[test]
fn a_second_hand_over_of_the_same_work_reuses_the_assignment_in_progress() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let first = assign(&mut store, root, event.event_id, worker, "r1");
    let after_first = store.revision();

    // A different retry identity, so this is not a replay — it is the root asking twice.
    let again = assign(&mut store, root, event.event_id, worker, "r2");

    assert_eq!(again.dispatch.route_id, first.dispatch.route_id);
    assert!(again.deduplicated);
    assert_eq!(store.revision(), after_first);
    assert_eq!(store.events[0].routes().len(), 1);
}

#[test]
fn a_retry_identity_reused_for_different_content_is_refused() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let other = register_member(&mut store, "/root/other");
    let event = root_event(&mut store, root);
    assign(&mut store, root, event.event_id, worker, "r1");
    let before = store.revision();

    let refused = store
        .route(
            root,
            &submission(before, "r1"),
            route_request(event.event_id, other, RouteIntent::Assign),
        )
        .expect_err("the same identity cannot stand for two different routes");
    assert_eq!(refused, TeamError::RetryIdentityReused);
    assert_eq!(store.revision(), before);
}

#[test]
fn one_retry_identity_cannot_stand_for_a_publish_and_a_route() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);

    let refused = store
        .route(
            root,
            &submission(store.revision(), "r-open"),
            route_request(event.event_id, worker, RouteIntent::Assign),
        )
        .expect_err("the publish already owns this identity");
    assert_eq!(refused, TeamError::RetryIdentityReused);
    assert!(store.events[0].routes().is_empty());
}

#[test]
fn a_new_assignment_can_be_made_once_the_previous_one_ended() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let first = assign(&mut store, root, event.event_id, worker, "r1");
    store
        .end_assignment(worker, first.dispatch.route_id)
        .expect("the target finishes it");

    let second = assign(&mut store, root, event.event_id, worker, "r2");

    assert_ne!(second.dispatch.route_id, first.dispatch.route_id);
    assert!(!second.deduplicated);
    assert_eq!(store.events[0].routes().len(), 2);
    assert!(active_event_ids(&store, worker).contains(&event.event_id));
}

// --- assignment versus notice ------------------------------------------------------------------

#[test]
fn an_informational_route_grants_visibility_without_manufacturing_work() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);

    let outcome = store
        .route(
            root,
            &submission(store.revision(), "r1"),
            route_request(event.event_id, worker, RouteIntent::Notify),
        )
        .expect("the root may tell a member about an event");

    assert_eq!(outcome.dispatch.duty, RouteDuty::Notice);
    assert!(
        store
            .history(
                worker,
                &HistoryQuery {
                    event_id: Some(event.event_id),
                    limit: None,
                    before: None,
                },
            )
            .is_ok(),
        "a notice still grants visibility"
    );
    assert!(
        !active_event_ids(&store, worker).contains(&event.event_id),
        "being told about something is not being given work"
    );
    assert!(!store.has_pending_wake(worker));
}

#[test]
fn an_assignment_enters_the_targets_active_view_and_signals_it() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);

    let outcome = assign(&mut store, root, event.event_id, worker, "r1");

    assert_eq!(outcome.dispatch.duty, RouteDuty::Assigned);
    assert_eq!(active_event_ids(&store, worker), vec![event.event_id]);
    assert!(store.has_pending_wake(worker));
}

#[test]
fn a_member_sees_only_the_routes_addressed_to_it() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let other = register_member(&mut store, "/root/other");
    let event = root_event(&mut store, root);
    assign(&mut store, root, event.event_id, worker, "r1");
    assign(&mut store, root, event.event_id, other, "r2");

    let targets_in = |viewer: ThreadId| -> Vec<String> {
        store
            .snapshot_for(viewer)
            .expect("registered")
            .events
            .iter()
            .flat_map(|event| event.routes.iter())
            .map(|route| route.target_label.clone())
            .collect()
    };
    assert_eq!(targets_in(worker), vec!["/root/worker".to_string()]);
    assert_eq!(
        targets_in(root),
        vec!["/root/worker".to_string(), "/root/other".to_string()]
    );
}

// --- ending an assignment ----------------------------------------------------------------------

#[test]
fn ending_an_assignment_leaves_the_targets_own_unfinished_work_in_view() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let routed = assign(&mut store, root, event.event_id, worker, "r1");
    store
        .publish(
            worker,
            &submission(store.revision(), "w1"),
            append(event.event_id, "still verifying the second column"),
        )
        .expect("worker appends its own version");

    store
        .end_assignment(worker, routed.dispatch.route_id)
        .expect("the target ends its assignment");

    assert_eq!(
        active_event_ids(&store, worker),
        vec![event.event_id],
        "its own open version is a separate reason to stay active"
    );
}

#[test]
fn ending_one_assignment_leaves_another_in_progress() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let other = register_member(&mut store, "/root/other");
    let first = root_event(&mut store, root);
    let second = store
        .publish(
            root,
            &submission(store.revision(), "r-open-2"),
            new_event("rollback plan", "we need one before Friday"),
        )
        .expect("root may publish");
    let to_worker_first = assign(&mut store, root, first.event_id, worker, "r1");
    assign(&mut store, root, second.event_id, worker, "r2");
    assign(&mut store, root, first.event_id, other, "r3");

    store
        .end_assignment(worker, to_worker_first.dispatch.route_id)
        .expect("worker ends only the first");

    assert_eq!(
        active_event_ids(&store, worker),
        vec![second.event_id],
        "only the named assignment was retired"
    );
    assert_eq!(
        active_event_ids(&store, other),
        vec![first.event_id],
        "another participant's assignment on the same event is untouched"
    );
}

#[test]
fn an_assignment_ends_once_and_a_second_attempt_is_refused() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let routed = assign(&mut store, root, event.event_id, worker, "r1");

    let ended = store
        .end_assignment(worker, routed.dispatch.route_id)
        .expect("first end wins");
    assert_eq!(ended.duty, RouteDuty::Ended);
    let after_end = store.revision();

    let again = store
        .end_assignment(root, routed.dispatch.route_id)
        .expect_err("a terminal assignment does not end twice");
    assert_eq!(
        again,
        TeamError::AssignmentEnded {
            route_id: routed.dispatch.route_id
        }
    );
    assert_eq!(store.revision(), after_end);
}

#[test]
fn an_informational_route_has_no_assignment_to_end() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let notice = store
        .route(
            root,
            &submission(store.revision(), "r1"),
            route_request(event.event_id, worker, RouteIntent::Notify),
        )
        .expect("notice committed");

    assert_eq!(
        store
            .end_assignment(worker, notice.dispatch.route_id)
            .expect_err("a notice never carried work"),
        TeamError::NotAnAssignment {
            route_id: notice.dispatch.route_id
        }
    );
}

#[test]
fn a_bystander_cannot_end_someone_elses_assignment() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let other = register_member(&mut store, "/root/other");
    let event = root_event(&mut store, root);
    let routed = assign(&mut store, root, event.event_id, worker, "r1");
    let before = store.revision();

    assert_eq!(
        store
            .end_assignment(other, routed.dispatch.route_id)
            .expect_err("not this member's assignment"),
        TeamError::NotPermitted {
            reason: "only the assignment's target or the root may end it"
        }
    );
    assert_eq!(store.revision(), before);
    assert_eq!(store.events[0].routes()[0].duty(), RouteDuty::Assigned);
}

#[test]
fn a_target_ending_its_assignment_gives_the_root_a_coordination_opportunity() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let routed = assign(&mut store, root, event.event_id, worker, "r1");
    store.consume_wake(root);

    store
        .end_assignment(worker, routed.dispatch.route_id)
        .expect("target ends it");

    assert!(store.has_pending_wake(root));
}

// --- delivery ---------------------------------------------------------------------------------

#[test]
fn a_failed_notice_leaves_the_grant_and_the_assignment_standing() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let routed = assign(&mut store, root, event.event_id, worker, "r1");

    let failed = store
        .record_delivery(
            root,
            routed.dispatch.route_id,
            DeliveryResult::Failed {
                reason: "agent with id 1 not found".to_string(),
            },
        )
        .expect("a failure is recorded, not raised");

    assert_eq!(
        failed.delivery,
        DeliveryState::Failed {
            reason: "agent with id 1 not found".to_string()
        }
    );
    assert!(failed.changed);
    assert_eq!(store.events[0].routes()[0].duty(), RouteDuty::Assigned);
    assert_eq!(active_event_ids(&store, worker), vec![event.event_id]);
    assert!(
        store
            .history(
                worker,
                &HistoryQuery {
                    event_id: Some(event.event_id),
                    limit: None,
                    before: None,
                },
            )
            .is_ok(),
        "the grant does not depend on the notice arriving"
    );

    // And the retry settles it without minting anything.
    let retried = store
        .record_delivery(root, routed.dispatch.route_id, DeliveryResult::Delivered)
        .expect("retry recorded");
    assert_eq!(retried.delivery, DeliveryState::Delivered);
    assert_eq!(store.events[0].routes().len(), 1);
}

#[test]
fn a_delivered_notice_is_terminal_and_repeated_reports_change_nothing() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let routed = assign(&mut store, root, event.event_id, worker, "r1");
    store
        .record_delivery(root, routed.dispatch.route_id, DeliveryResult::Delivered)
        .expect("delivered");
    let after_delivery = store.revision();

    let repeated = store
        .record_delivery(root, routed.dispatch.route_id, DeliveryResult::Delivered)
        .expect("an at-least-once path may report twice");
    assert_eq!(repeated.delivery, DeliveryState::Delivered);
    assert!(!repeated.changed);

    let late_failure = store
        .record_delivery(
            root,
            routed.dispatch.route_id,
            DeliveryResult::Failed {
                reason: "late".to_string(),
            },
        )
        .expect("a late failure is absorbed");
    assert_eq!(late_failure.delivery, DeliveryState::Delivered);
    assert!(!late_failure.changed);
    assert_eq!(store.revision(), after_delivery);
}

#[test]
fn only_the_participant_that_routed_may_report_on_the_notice() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let routed = assign(&mut store, root, event.event_id, worker, "r1");
    let before = store.revision();

    assert_eq!(
        store
            .record_delivery(worker, routed.dispatch.route_id, DeliveryResult::Delivered)
            .expect_err("the target does not get to declare its own notice delivered"),
        TeamError::NotPermitted {
            reason: "only the participant that routed this event may report on its notice"
        }
    );
    assert_eq!(store.revision(), before);
    assert_eq!(
        *store.events[0].routes()[0].delivery(),
        DeliveryState::Pending
    );
}

/// Resending is an action on the target's attention, so the target itself must not be able to take
/// a dispatch. The store is where that has to be refused: by the time a handler has a dispatch in
/// hand it is one step away from sending, and a send that the canonical state then refuses to
/// account for has already happened.
#[test]
fn only_the_router_may_take_a_dispatch_to_resend() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let other = register_member(&mut store, "/root/other");
    let event = root_event(&mut store, root);
    let routed = store
        .route(
            root,
            &submission(store.revision(), "r1"),
            RouteRequest {
                event_id: event.event_id,
                target: worker,
                intent: RouteIntent::Assign,
                note: Some("confirm the column types".to_string()),
            },
        )
        .expect("routed");

    let by_root = store
        .route_dispatch(root, routed.dispatch.route_id)
        .expect("the router may rebuild its own notice");
    assert_eq!(by_root, routed.dispatch);
    let refused = TeamError::NotPermitted {
        reason: "only the participant that routed this event may resend its notice",
    };
    assert_eq!(
        store
            .route_dispatch(worker, routed.dispatch.route_id)
            .expect_err("the target does not get to resend its own notice"),
        refused
    );
    assert_eq!(
        store
            .route_dispatch(other, routed.dispatch.route_id)
            .expect_err("nor does a bystander"),
        refused
    );

    // The target keeps everything the route was for: it can still read the event and end the work.
    assert!(
        store
            .history(
                worker,
                &HistoryQuery {
                    event_id: Some(event.event_id),
                    limit: None,
                    before: None,
                },
            )
            .is_ok()
    );
    assert!(
        store
            .end_assignment(worker, routed.dispatch.route_id)
            .is_ok()
    );
}

/// A replay has to report the delivery the route has now. Answering from a copy made at commit
/// time would always say `pending`, which is precisely the state a failed notice is not in.
#[test]
fn a_replayed_route_reports_the_delivery_state_the_route_has_now() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let first = assign(&mut store, root, event.event_id, worker, "r1");
    assert_eq!(first.dispatch.delivery, DeliveryState::Pending);

    store
        .record_delivery(
            root,
            first.dispatch.route_id,
            DeliveryResult::Failed {
                reason: "agent with id 1 not found".to_string(),
            },
        )
        .expect("the notice failed");

    let replay = store
        .route(
            root,
            &submission(TeamRevision::INITIAL, "r1"),
            route_request(event.event_id, worker, RouteIntent::Assign),
        )
        .expect("a replay succeeds");

    assert!(replay.deduplicated);
    assert_eq!(replay.dispatch.route_id, first.dispatch.route_id);
    assert_eq!(
        replay.dispatch.delivery,
        DeliveryState::Failed {
            reason: "agent with id 1 not found".to_string()
        },
        "a replay must not hide a failure the caller still has to retry"
    );
    assert_eq!(
        replay.revision,
        store.revision(),
        "the reported revision belongs to the same snapshot as the reported delivery"
    );
}

/// The alias identity has to be bound to the assignment it was answered with. Left unclaimed it
/// would mint a second assignment once the first ended, and would still be free for another kind
/// of submission to take.
#[test]
fn an_alias_identity_is_bound_to_the_assignment_it_was_answered_with() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let first = assign(&mut store, root, event.event_id, worker, "r1");
    let alias = assign(&mut store, root, event.event_id, worker, "r2");
    assert_eq!(alias.dispatch.route_id, first.dispatch.route_id);

    store
        .end_assignment(root, first.dispatch.route_id)
        .expect("the assignment ends");

    // Replaying the alias verbatim repeats its answer instead of handing the work over again.
    let replay = assign(&mut store, root, event.event_id, worker, "r2");
    assert_eq!(replay.dispatch.route_id, first.dispatch.route_id);
    assert_eq!(replay.dispatch.duty, RouteDuty::Ended);
    assert!(replay.deduplicated);
    assert_eq!(store.events[0].routes().len(), 1);

    // And the alias is genuinely claimed, so the shared namespace still holds.
    assert_eq!(
        store
            .publish(
                root,
                &submission(store.revision(), "r2"),
                new_event("something else", "reusing the identity"),
            )
            .expect_err("the identity already stands for a route"),
        TeamError::RetryIdentityReused
    );
}

/// Two different instructions are two different hand-overs. Answering the second with the first
/// would drop what the root just said, so it is refused rather than silently merged.
#[test]
fn a_hand_over_with_a_different_instruction_is_refused_rather_than_dropped() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    let with_note = |note: &str| RouteRequest {
        event_id: event.event_id,
        target: worker,
        intent: RouteIntent::Assign,
        note: Some(note.to_string()),
    };
    let first = store
        .route(
            root,
            &submission(store.revision(), "r1"),
            with_note("check the report"),
        )
        .expect("routed");
    let before = store.revision();

    let refused = store
        .route(
            root,
            &submission(before, "r2"),
            with_note("check the report and the backfill"),
        )
        .expect_err("a changed instruction is not the same hand-over");

    assert_eq!(
        refused,
        TeamError::AssignmentInProgress {
            route_id: first.dispatch.route_id
        }
    );
    assert_eq!(store.revision(), before);
    assert_eq!(store.events[0].routes().len(), 1);
    assert_eq!(
        store.events[0].routes()[0].note(),
        Some("check the report"),
        "the original instruction is untouched"
    );
}

#[test]
fn an_unknown_route_reference_is_refused_rather_than_guessed() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let event = root_event(&mut store, root);
    assign(&mut store, root, event.event_id, worker, "r1");
    let missing = RouteId::new(store.instance().tag(), event.event_id.ordinal(), 9);

    assert_eq!(
        store
            .end_assignment(root, missing)
            .expect_err("nothing named that"),
        TeamError::UnknownReference {
            reference: missing.to_string()
        }
    );
}
