use super::*;
use crate::ids::TeamRevision;
use crate::model::ProducerState;
use crate::model::RootState;
use crate::mutation::LifecycleChange;
use crate::mutation::LifecycleRequest;
use crate::mutation::LifecycleTarget;
use crate::mutation::PublishTarget;
use crate::store::MAX_HISTORY_LIMIT;
use crate::view::HistoryQuery;
use pretty_assertions::assert_eq;
use std::time::Duration;

fn team() -> (Arc<TeamStateHandle>, ThreadId, ThreadId) {
    let handle = Arc::new(TeamStateHandle::default());
    let root = ThreadId::new();
    let worker = ThreadId::new();
    handle.register_participant(root, ParticipantRole::Root, "/root".to_string());
    handle.register_participant(worker, ParticipantRole::Member, "/root/worker".to_string());
    (handle, root, worker)
}

fn publish(handle: &TeamStateHandle, actor: ThreadId, request_id: &str) -> PublishOutcome {
    handle
        .publish(
            actor,
            &Submission {
                based_on: handle.revision(),
                request_id: request_id.to_string(),
            },
            PublishRequest {
                target: PublishTarget::NewEvent {
                    title: "finding".to_string(),
                },
                summary: "worker found something".to_string(),
                handoff: None,
            },
        )
        .expect("publish succeeds")
}

#[tokio::test]
async fn a_change_published_before_the_wait_starts_is_not_lost() {
    let (handle, root, worker) = team();
    publish(&handle, worker, "w1");

    let waiter = handle.wake_waiter(root);
    tokio::time::timeout(Duration::from_secs(5), waiter.wait())
        .await
        .expect("a change published before the wait must still resolve it");
}

#[tokio::test]
async fn a_change_published_during_the_wait_resolves_it() {
    let (handle, root, worker) = team();
    let waiter = handle.wake_waiter(root);

    let publisher = {
        let handle = Arc::clone(&handle);
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_millis(50)).await;
            publish(&handle, worker, "w1");
        })
    };

    tokio::time::timeout(Duration::from_secs(5), waiter.wait())
        .await
        .expect("a change published during the wait must resolve it");
    publisher.await.expect("publisher finishes");
}

#[tokio::test]
async fn an_already_consumed_change_does_not_resolve_the_next_wait() {
    let (handle, root, worker) = team();
    publish(&handle, worker, "w1");

    tokio::time::timeout(Duration::from_secs(5), handle.wake_waiter(root).wait())
        .await
        .expect("the first wait consumes the change");

    let second =
        tokio::time::timeout(Duration::from_millis(200), handle.wake_waiter(root).wait()).await;
    assert!(
        second.is_err(),
        "a change the root already consumed must not wake it again"
    );
}

#[tokio::test]
async fn the_root_is_not_woken_by_its_own_publication() {
    let (handle, root, _worker) = team();
    publish(&handle, root, "r1");

    let outcome =
        tokio::time::timeout(Duration::from_millis(200), handle.wake_waiter(root).wait()).await;
    assert!(outcome.is_err(), "the root must not wake itself");
}

#[test]
fn a_stable_retry_does_not_bump_wake_generation() {
    let (handle, _root, worker) = team();
    publish(&handle, worker, "w1");
    let generation = handle.wake_generation();
    let retry = publish(&handle, worker, "w1");
    assert!(retry.deduplicated);
    assert_eq!(handle.wake_generation(), generation);
    assert_eq!(handle.revision(), TeamRevision::from_raw(1));
}

#[test]
fn a_same_state_lifecycle_update_does_not_bump_wake_generation() {
    let (handle, root, worker) = team();
    let published = publish(&handle, worker, "w1");
    let generation = handle.wake_generation();
    let outcome = handle
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![LifecycleTarget {
                    version_id: published.version_id,
                    expected_producer_state: ProducerState::Open,
                    expected_root_state: RootState::Pending,
                    change: LifecycleChange::SetRootState(RootState::Pending),
                }],
            },
        )
        .expect("same-state update");
    assert!(!outcome.changed);
    assert_eq!(handle.wake_generation(), generation);
    assert_eq!(handle.revision(), TeamRevision::from_raw(1));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_appends_to_one_event_all_land_exactly_once() {
    let (handle, root, worker) = team();
    let opened = publish(&handle, worker, "seed");

    // Both actors are entitled to this event: the worker opened it, and the root can write
    // anywhere in its own team. Each submits eight distinct appends, and every submission is sent
    // twice with the same retry identity.
    let mut tasks = Vec::new();
    for (actor, name) in [(root, "root"), (worker, "worker")] {
        for index in 0..8 {
            let handle = Arc::clone(&handle);
            let request_id = format!("append-{name}-{index}");
            tasks.push(tokio::spawn(async move {
                for _ in 0..2 {
                    handle
                        .publish(
                            actor,
                            &Submission {
                                based_on: handle.revision(),
                                request_id: request_id.clone(),
                            },
                            PublishRequest {
                                target: PublishTarget::ExistingEvent {
                                    event_id: opened.event_id,
                                },
                                summary: format!("append {name}/{index}"),
                                handoff: None,
                            },
                        )
                        .expect("concurrent appends by entitled actors are accepted");
                }
            }));
        }
    }
    for task in tasks {
        task.await.expect("append task finishes");
    }

    let page = handle
        .history(
            root,
            &HistoryQuery {
                event_id: Some(opened.event_id),
                limit: Some(MAX_HISTORY_LIMIT),
                before: None,
            },
        )
        .expect("root may read history");
    let entry = page.events.first().expect("one event");
    // 1 seed + 16 distinct submissions; the 16 retries must not create anything.
    assert_eq!(entry.total_versions, 17);
    assert_eq!(entry.event.versions.len(), 17);
}

#[tokio::test]
async fn reusing_a_retry_identity_for_different_content_is_refused() {
    let (handle, _root, worker) = team();
    let submission = Submission {
        based_on: TeamRevision::INITIAL,
        request_id: "same-id".to_string(),
    };
    let request = |summary: &str| PublishRequest {
        target: PublishTarget::NewEvent {
            title: "finding".to_string(),
        },
        summary: summary.to_string(),
        handoff: None,
    };

    handle
        .publish(worker, &submission, request("the first conclusion"))
        .expect("first submission lands");
    let reused = handle
        .publish(worker, &submission, request("a different conclusion"))
        .expect_err("different content under the same identity is not a retry");

    assert_eq!(reused, TeamError::RetryIdentityReused);

    // The refusal must not have thrown away the first submission either.
    let snapshot = handle.snapshot_for(worker).expect("worker view");
    assert_eq!(snapshot.events.len(), 1);
    assert_eq!(
        snapshot.events[0].versions[0].summary,
        "the first conclusion"
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_stale_lifecycle_change_racing_a_concurrent_one_loses_cleanly() {
    let (handle, root, worker) = team();
    let published = publish(&handle, worker, "w1");
    let target = move |expected: RootState, next: RootState| LifecycleRequest {
        targets: vec![LifecycleTarget {
            version_id: published.version_id,
            expected_producer_state: ProducerState::Open,
            expected_root_state: expected,
            change: LifecycleChange::SetRootState(next),
        }],
    };

    let first = {
        let handle = Arc::clone(&handle);
        tokio::spawn(async move {
            handle.update_lifecycle(root, target(RootState::Pending, RootState::Tracking))
        })
    };
    let second = {
        let handle = Arc::clone(&handle);
        tokio::spawn(async move {
            handle.update_lifecycle(root, target(RootState::Pending, RootState::Resolved))
        })
    };
    let results = [
        first.await.expect("task finishes"),
        second.await.expect("task finishes"),
    ];

    let winners = results.iter().filter(|result| result.is_ok()).count();
    assert_eq!(winners, 1, "exactly one of two racing changes may commit");
    let loser = results
        .iter()
        .find_map(|result| result.as_ref().err())
        .expect("the other must be refused with the current state");
    assert!(matches!(loser, TeamError::LifecycleConflict { .. }));

    // The refusal did not corrupt anything: the winner's value is what is stored. Read through
    // the author's view because a root-resolved version correctly leaves the root's active view,
    // while the still-open producer item remains active for its author.
    let snapshot = handle.snapshot_for(worker).expect("worker view");
    let stored = snapshot.events[0].versions[0].root_state;
    assert!(matches!(stored, RootState::Tracking | RootState::Resolved));
}

#[test]
fn every_clone_of_the_handle_sees_the_same_canonical_state() {
    let (handle, root, worker) = team();
    let clone = Arc::clone(&handle);
    let published = publish(&clone, worker, "w1");

    assert_eq!(handle.revision(), TeamRevision::from_raw(1));
    assert_eq!(
        handle
            .snapshot_for(root)
            .expect("root view")
            .events
            .iter()
            .map(|event| event.id)
            .collect::<Vec<_>>(),
        vec![published.event_id]
    );
}

/// An empty handoff and the absence of one are different submissions. A retry check that flattens
/// the request into text has to decide how to encode that difference, and any encoding of
/// model-controlled text can be made to collide; comparing the request itself cannot.
#[tokio::test]
async fn an_empty_field_is_not_the_same_submission_as_a_missing_one() {
    let (handle, _root, worker) = team();
    let submission = Submission {
        based_on: TeamRevision::INITIAL,
        request_id: "ambiguity".to_string(),
    };
    let request = |handoff: Option<&str>| PublishRequest {
        target: PublishTarget::NewEvent {
            title: "finding".to_string(),
        },
        summary: "same summary".to_string(),
        handoff: handoff.map(str::to_string),
    };

    handle
        .publish(worker, &submission, request(None))
        .expect("first submission lands");
    let ambiguous = handle
        .publish(worker, &submission, request(Some("")))
        .expect_err("an empty handoff is not the absence of one");

    assert_eq!(ambiguous, TeamError::RetryIdentityReused);
}

fn route_submission(request_id: &str) -> Submission {
    Submission {
        based_on: TeamRevision::INITIAL,
        request_id: request_id.to_string(),
    }
}

fn assignment(event_id: crate::ids::EventId, target: ThreadId) -> RouteRequest {
    RouteRequest {
        event_id,
        target,
        intent: crate::mutation::RouteIntent::Assign,
        note: None,
    }
}

fn routes_of(handle: &TeamStateHandle, viewer: ThreadId) -> Vec<crate::view::RouteView> {
    handle
        .snapshot_for(viewer)
        .expect("viewer is registered")
        .events
        .iter()
        .flat_map(|event| event.routes.clone())
        .collect()
}

/// Racing copies of one logical route must settle on a single grant. Two assignments for the same
/// work would each need ending separately, and ending only one of them would leave the event in the
/// target's view with nothing to explain why.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_copies_of_one_route_produce_exactly_one_assignment() {
    let (handle, root, worker) = team();
    let event_id = publish(&handle, root, "r-open").event_id;

    let tasks: Vec<_> = (0..8)
        .map(|_| {
            let handle = Arc::clone(&handle);
            tokio::spawn(async move {
                handle.route(root, &route_submission("r1"), assignment(event_id, worker))
            })
        })
        .collect();
    let mut outcomes = Vec::new();
    for task in tasks {
        outcomes.push(task.await.expect("task finishes").expect("route succeeds"));
    }

    let fresh = outcomes
        .iter()
        .filter(|outcome| !outcome.deduplicated)
        .count();
    assert_eq!(fresh, 1, "only one caller may mint the grant");
    let route_id = outcomes[0].dispatch.route_id;
    assert!(
        outcomes
            .iter()
            .all(|outcome| outcome.dispatch.route_id == route_id),
        "every caller must be told about the same grant"
    );
    assert_eq!(routes_of(&handle, worker).len(), 1);
}

/// Ending is terminal, so a race has one winner and the losers learn the assignment is already
/// over rather than silently re-ending it or walking the state backwards.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn concurrent_ends_of_one_assignment_leave_exactly_one_winner() {
    let (handle, root, worker) = team();
    let event_id = publish(&handle, root, "r-open").event_id;
    let route_id = handle
        .route(root, &route_submission("r1"), assignment(event_id, worker))
        .expect("routed")
        .dispatch
        .route_id;

    let tasks: Vec<_> = [root, worker, root, worker]
        .into_iter()
        .map(|actor| {
            let handle = Arc::clone(&handle);
            tokio::spawn(async move { handle.end_assignment(actor, route_id) })
        })
        .collect();
    let mut results = Vec::new();
    for task in tasks {
        results.push(task.await.expect("task finishes"));
    }

    assert_eq!(
        results.iter().filter(|result| result.is_ok()).count(),
        1,
        "an assignment ends exactly once"
    );
    assert!(
        results
            .iter()
            .filter_map(|result| result.as_ref().err())
            .all(|err| matches!(err, TeamError::AssignmentEnded { .. })),
        "every loser is told it was already ended"
    );
    assert_eq!(
        routes_of(&handle, root)[0].duty,
        crate::model::RouteDuty::Ended
    );
}
