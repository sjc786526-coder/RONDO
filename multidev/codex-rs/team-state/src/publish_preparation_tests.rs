use super::*;
use codex_protocol::ThreadId;
use pretty_assertions::assert_eq;

fn team() -> (TeamStateHandle, ThreadId, ThreadId) {
    let handle = TeamStateHandle::default();
    let root = ThreadId::new();
    let worker = ThreadId::new();
    handle.register_participant(root, ParticipantRole::Root, "/root".to_string());
    handle.register_participant(worker, ParticipantRole::Member, "/root/worker".to_string());
    (handle, root, worker)
}

fn submission(request_id: &str) -> Submission {
    Submission {
        based_on: TeamRevision::INITIAL,
        request_id: request_id.to_string(),
    }
}

fn new_event(title: &str, summary: &str, handoff: Option<&str>) -> PublishRequest {
    PublishRequest {
        target: PublishTarget::NewEvent {
            title: title.to_string(),
        },
        summary: summary.to_string(),
        handoff: handoff.map(str::to_string),
    }
}

fn ready(preparation: PublishPreparation) -> PreparedPublish {
    match preparation {
        PublishPreparation::Ready(prepared) => prepared,
        PublishPreparation::Committed(_) => panic!("request should not already be committed"),
    }
}

fn state_fingerprint(handle: &TeamStateHandle, root: ThreadId) -> (TeamRevision, u64, HistoryPage) {
    (
        handle.revision(),
        handle.wake_generation(),
        handle
            .history(root, &HistoryQuery::default())
            .expect("root may read team history"),
    )
}

#[test]
fn prepared_authored_fields_are_exactly_what_publish_commits() {
    let (handle, root, worker) = team();
    let request = new_event(
        &"题".repeat(/*n*/ 230),
        &"结".repeat(/*n*/ 2_030),
        Some(&"续".repeat(/*n*/ 1_030)),
    );
    let initial_submission = submission("canonical");
    let before = state_fingerprint(&handle, root);

    let prepared = ready(
        handle
            .prepare_publish(worker, &initial_submission, &request)
            .expect("valid request is prepared"),
    );

    assert_eq!(state_fingerprint(&handle, root), before);
    assert_eq!(prepared.actor_role, ParticipantRole::Member);
    let PreparedPublishTarget::NewEvent { title } = &prepared.target else {
        panic!("new-event request keeps its target kind");
    };
    let outcome = handle
        .publish(worker, &initial_submission, request)
        .expect("the raw request still performs the only commit");
    let page = handle
        .history(
            root,
            &HistoryQuery {
                event_id: Some(outcome.event_id),
                limit: Some(1),
                before: None,
            },
        )
        .expect("root may read the committed event");
    let event = &page.events[0].event;
    let version = &event.versions[0];

    assert_eq!(&event.title, title);
    assert_eq!(version.summary, prepared.summary);
    assert_eq!(version.handoff, prepared.handoff);

    let append_request = PublishRequest {
        target: PublishTarget::ExistingEvent {
            event_id: outcome.event_id,
        },
        summary: "补".repeat(/*n*/ 2_030),
        handoff: Some("接".repeat(/*n*/ 1_030)),
    };
    let append_submission = submission("canonical-append");
    let before_append = state_fingerprint(&handle, root);
    let prepared_append = ready(
        handle
            .prepare_publish(root, &append_submission, &append_request)
            .expect("visible existing event is prepared"),
    );
    assert_eq!(state_fingerprint(&handle, root), before_append);
    assert_eq!(prepared_append.actor_role, ParticipantRole::Root);
    assert_eq!(
        prepared_append.target,
        PreparedPublishTarget::ExistingEvent {
            event_id: outcome.event_id,
            title: event.title.clone(),
            authored_on_stale_view: true,
        }
    );
    handle
        .publish(root, &append_submission, append_request)
        .expect("the raw append performs the only second commit");
    let appended = handle
        .history(
            root,
            &HistoryQuery {
                event_id: Some(outcome.event_id),
                limit: Some(1),
                before: None,
            },
        )
        .expect("root may read the appended event");
    assert_eq!(
        appended.events[0].event.versions[0].summary,
        prepared_append.summary
    );
    assert_eq!(
        appended.events[0].event.versions[0].handoff,
        prepared_append.handoff
    );
}

#[test]
fn prepared_freshness_uses_the_target_event_not_global_revision() {
    let (handle, root, worker) = team();
    let target = handle
        .publish(
            worker,
            &submission("target"),
            new_event("target", "initial target state", /*handoff*/ None),
        )
        .expect("worker opens the target event");
    let based_on_target = target.revision;
    handle
        .publish(
            root,
            &Submission {
                based_on: based_on_target,
                request_id: "unrelated".to_string(),
            },
            new_event(
                "unrelated",
                "moves only global revision",
                /*handoff*/ None,
            ),
        )
        .expect("root opens an unrelated event");
    let append_submission = Submission {
        based_on: based_on_target,
        request_id: "candidate".to_string(),
    };
    let append_request = PublishRequest {
        target: PublishTarget::ExistingEvent {
            event_id: target.event_id,
        },
        summary: "candidate".to_string(),
        handoff: None,
    };

    let (fresh, history) = handle
        .prepare_publish_with_history(worker, &append_submission, &append_request, 1)
        .expect("target and bounded history are prepared from one store view");
    let fresh = ready(fresh);
    let history = history.expect("an existing target includes bounded public history");
    assert_eq!(history.revision, handle.revision());
    assert_eq!(history.event_id, target.event_id);
    assert_eq!(history.versions.len(), 1);
    let PreparedPublishTarget::ExistingEvent {
        authored_on_stale_view,
        ..
    } = fresh.target
    else {
        panic!("append keeps its target kind");
    };
    assert!(!authored_on_stale_view);

    handle
        .publish(
            root,
            &Submission {
                based_on: handle.revision(),
                request_id: "target-moved".to_string(),
            },
            PublishRequest {
                target: PublishTarget::ExistingEvent {
                    event_id: target.event_id,
                },
                summary: "target moved".to_string(),
                handoff: None,
            },
        )
        .expect("the target event advances");
    let stale = ready(
        handle
            .prepare_publish(worker, &append_submission, &append_request)
            .expect("the same based-on revision is now event-locally stale"),
    );
    let PreparedPublishTarget::ExistingEvent {
        authored_on_stale_view,
        ..
    } = stale.target
    else {
        panic!("append keeps its target kind");
    };
    assert!(authored_on_stale_view);

    let committed = handle
        .publish(worker, &append_submission, append_request)
        .expect("the final mutation rechecks and records the same event-local staleness");
    assert!(committed.authored_on_stale_view);
}

#[test]
fn prepared_existing_event_history_is_bounded_and_has_no_route_or_fact_identity_shape() {
    let (handle, root, worker) = team();
    let event = handle
        .publish(
            root,
            &submission("bounded-initial"),
            new_event("bounded", "version 1", /*handoff*/ None),
        )
        .expect("root opens the event");
    handle
        .route(
            root,
            &Submission {
                based_on: handle.revision(),
                request_id: "bounded-route".to_string(),
            },
            RouteRequest {
                event_id: event.event_id,
                target: worker,
                intent: RouteIntent::Assign,
                note: Some("route metadata must not be cloned".to_string()),
            },
        )
        .expect("the route makes the event visible to the worker");
    for ordinal in 2..=6 {
        handle
            .publish(
                root,
                &Submission {
                    based_on: handle.revision(),
                    request_id: format!("bounded-{ordinal}"),
                },
                PublishRequest {
                    target: PublishTarget::ExistingEvent {
                        event_id: event.event_id,
                    },
                    summary: format!("version {ordinal}"),
                    handoff: None,
                },
            )
            .expect("root appends another version");
    }

    let append = PublishRequest {
        target: PublishTarget::ExistingEvent {
            event_id: event.event_id,
        },
        summary: "worker candidate".to_string(),
        handoff: None,
    };
    let (_, history) = handle
        .prepare_publish_with_history(
            worker,
            &Submission {
                based_on: handle.revision(),
                request_id: "bounded-candidate".to_string(),
            },
            &append,
            2,
        )
        .expect("worker receives its bounded publication-only view");

    assert_eq!(
        history,
        Some(PreparedPublishHistory {
            event_id: event.event_id,
            revision: handle.revision(),
            versions: vec![
                PreparedPublishHistoryVersion {
                    summary: "version 5".to_string(),
                    handoff: None,
                    evidence_reference_count: 0,
                },
                PreparedPublishHistoryVersion {
                    summary: "version 6".to_string(),
                    handoff: None,
                    evidence_reference_count: 0,
                },
            ],
            omitted_versions: 4,
        })
    );
}

#[test]
fn raw_requests_that_canonicalize_the_same_still_conflict() {
    let (handle, _root, worker) = team();
    let shared_prefix = "x".repeat(/*n*/ 2_000);
    let first_request = new_event(
        "finding",
        &format!("{shared_prefix}a"),
        /*handoff*/ None,
    );
    let second_request = new_event(
        "finding",
        &format!("{shared_prefix}b"),
        /*handoff*/ None,
    );
    let first_prepared = ready(
        handle
            .prepare_publish(worker, &submission("preview-a"), &first_request)
            .expect("first request is prepared"),
    );
    let second_prepared = ready(
        handle
            .prepare_publish(worker, &submission("preview-b"), &second_request)
            .expect("second request is prepared"),
    );
    assert_eq!(first_prepared.summary, second_prepared.summary);

    let shared_submission = submission("same-raw-identity");
    handle
        .publish(worker, &shared_submission, first_request)
        .expect("first raw request commits");
    let revision = handle.revision();
    let generation = handle.wake_generation();

    let conflict = handle
        .prepare_publish(worker, &shared_submission, &second_request)
        .expect_err("canonical equality must not turn different raw content into a retry");

    assert_eq!(conflict, TeamError::RetryIdentityReused);
    assert_eq!(handle.revision(), revision);
    assert_eq!(handle.wake_generation(), generation);
}

#[test]
fn committed_preflight_is_exact_and_does_not_consume_later_evidence() {
    let (handle, root, worker) = team();
    let request = new_event("finding", "the first conclusion", /*handoff*/ None);
    let committed_submission = submission("committed");
    let first = handle
        .publish(worker, &committed_submission, request.clone())
        .expect("first request commits");
    handle.note_observation(
        worker,
        NotedObservation {
            item_id: "retained-item".to_string(),
            call_id: "call-after-publish".to_string(),
            category: FactCategory::ToolResultSuccess,
            tool: "shell".to_string(),
        },
    );
    let later_fact = handle
        .confirm_observation(worker, "retained-item")
        .expect("the observation is retained");
    let before = state_fingerprint(&handle, root);

    let exact = handle
        .prepare_publish(worker, &committed_submission, &request)
        .expect("an exact retry is answered from the ledger");
    assert_eq!(
        exact,
        PublishPreparation::Committed(PublishOutcome {
            deduplicated: true,
            ..first.clone()
        })
    );
    assert_eq!(state_fingerprint(&handle, root), before);

    let different = new_event("finding", "a different conclusion", /*handoff*/ None);
    assert_eq!(
        handle
            .prepare_publish(worker, &committed_submission, &different)
            .expect_err("different raw content is not a retry"),
        TeamError::RetryIdentityReused
    );
    assert_eq!(state_fingerprint(&handle, root), before);

    let invalid = new_event("finding", "   ", /*handoff*/ None);
    assert_eq!(
        handle
            .prepare_publish(worker, &committed_submission, &invalid)
            .expect_err("summary validation still precedes retry lookup"),
        TeamError::InvalidRequest {
            reason: "summary must not be empty"
        }
    );
    assert_eq!(state_fingerprint(&handle, root), before);

    let appended = handle
        .publish(
            worker,
            &Submission {
                based_on: handle.revision(),
                request_id: "after-preflight".to_string(),
            },
            PublishRequest {
                target: PublishTarget::ExistingEvent {
                    event_id: first.event_id,
                },
                summary: "the follow-up".to_string(),
                handoff: None,
            },
        )
        .expect("a later publish still receives the untouched evidence window");
    assert_eq!(appended.evidence_refs, vec![later_fact]);
}

#[test]
fn invalid_and_unpermitted_preparation_has_no_side_effects() {
    let (handle, root, worker) = team();
    let outsider = ThreadId::new();
    handle.register_participant(
        outsider,
        ParticipantRole::Member,
        "/root/outsider".to_string(),
    );
    let private = handle
        .publish(
            root,
            &submission("root-private"),
            new_event("root only", "private coordination", /*handoff*/ None),
        )
        .expect("root opens a private event");
    let before = state_fingerprint(&handle, root);

    let unknown = ThreadId::new();
    assert_eq!(
        handle
            .prepare_publish(
                unknown,
                &submission("unknown"),
                &new_event("finding", "summary", /*handoff*/ None),
            )
            .expect_err("an unknown session has no capability"),
        TeamError::UnknownParticipant
    );
    assert_eq!(state_fingerprint(&handle, root), before);

    assert_eq!(
        handle
            .prepare_publish(
                worker,
                &submission("empty-summary"),
                &new_event("finding", "  ", /*handoff*/ None),
            )
            .expect_err("empty summary is invalid"),
        TeamError::InvalidRequest {
            reason: "summary must not be empty"
        }
    );
    assert_eq!(state_fingerprint(&handle, root), before);

    assert_eq!(
        handle
            .prepare_publish(
                worker,
                &submission("empty-title"),
                &new_event("  ", "summary", /*handoff*/ None),
            )
            .expect_err("empty new-event title is invalid"),
        TeamError::InvalidRequest {
            reason: "title must not be empty when opening a new event"
        }
    );
    assert_eq!(state_fingerprint(&handle, root), before);

    let invisible_append = PublishRequest {
        target: PublishTarget::ExistingEvent {
            event_id: private.event_id,
        },
        summary: "not mine".to_string(),
        handoff: None,
    };
    assert_eq!(
        handle
            .prepare_publish(outsider, &submission("invisible"), &invisible_append)
            .expect_err("an invisible event cannot be prepared for append"),
        TeamError::NotPermitted {
            reason: "this event is not visible to you, so you cannot add to it"
        }
    );
    assert_eq!(state_fingerprint(&handle, root), before);

    let (other, _other_root, other_worker) = team();
    let foreign = other
        .publish(
            other_worker,
            &submission("foreign"),
            new_event("foreign", "other instance", /*handoff*/ None),
        )
        .expect("other instance has an event");
    let foreign_append = PublishRequest {
        target: PublishTarget::ExistingEvent {
            event_id: foreign.event_id,
        },
        summary: "cross-instance".to_string(),
        handoff: None,
    };
    assert_eq!(
        handle
            .prepare_publish(worker, &submission("cross-instance"), &foreign_append)
            .expect_err("a previous-instance reference is refused"),
        TeamError::InstanceReset {
            referenced_instance: foreign.event_id.instance(),
            current_instance: handle.instance().tag(),
        }
    );
    assert_eq!(state_fingerprint(&handle, root), before);

    handle
        .publish(
            worker,
            &submission("empty-title"),
            new_event(
                "valid now",
                "the failed preparation reserved nothing",
                /*handoff*/ None,
            ),
        )
        .expect("an invalid preparation did not reserve its retry identity");
}
