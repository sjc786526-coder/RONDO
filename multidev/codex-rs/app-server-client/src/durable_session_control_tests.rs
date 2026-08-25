use super::*;
use crate::QueryReadApplyResult;
use codex_app_server_protocol::DurableSessionControlEffect;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlOperationKind;
use codex_app_server_protocol::DurableSessionControlOutcome;
use codex_app_server_protocol::DurableSessionControlRejectionReason;
use codex_app_server_protocol::DurableSessionControlResponse;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use pretty_assertions::assert_eq;
use serde_json::json;

fn protocol_operation(available: bool) -> serde_json::Value {
    if available {
        json!({
            "availability": { "status": "available" },
            "provenance": "derivedPolicy"
        })
    } else {
        json!({
            "availability": {
                "status": "unavailable",
                "reason": "controlDisabled"
            },
            "provenance": "derivedPolicy"
        })
    }
}

fn response(
    session_id: &str,
    root_thread_id: &str,
    commit_generation: u64,
    control_available: bool,
) -> DurableSessionReadResponse {
    serde_json::from_value(json!({
        "session": {
            "identity": {
                "sessionId": session_id,
                "rootThreadId": root_thread_id
            },
            "storageStatus": "active",
            "domainLifecycle": "open",
            "residency": "observedOwnerHere",
            "operationAvailability": {
                "resume": protocol_operation(false),
                "setRootState": protocol_operation(control_available),
                "close": protocol_operation(control_available),
                "archive": protocol_operation(control_available),
                "unarchive": protocol_operation(control_available),
                "delete": protocol_operation(control_available)
            },
            "controlPrecondition": if control_available {
                json!({
                    "expectedStorageStatus": "active",
                    "expectedResidency": "observedOwnerHere",
                    "teamInstanceId": format!("team-{session_id}"),
                    "teamRevision": 7,
                    "commitGeneration": commit_generation,
                    "commitFingerprint": format!("fingerprint-{commit_generation}")
                })
            } else {
                serde_json::Value::Null
            },
            "provenance": {
                "identity": "sessionMeta",
                "storageStatus": "threadStore",
                "domainLifecycle": "committedTeamSnapshot",
                "residency": "serverRuntimeObservation",
                "team": "committedTeamSnapshot"
            },
            "readStatus": { "status": "available" },
            "team": {
                "teamInstanceId": format!("team-{session_id}"),
                "commitGeneration": commit_generation,
                "commitFingerprint": format!("fingerprint-{commit_generation}"),
                "revision": 7,
                "viewer": {
                    "threadId": root_thread_id,
                    "role": "root"
                },
                "participants": [],
                "omittedParticipants": 0,
                "events": [],
                "omittedEvents": 0
            }
        }
    }))
    .expect("valid formal Session response")
}

fn attach_fresh(
    query: &mut DurableSessionQueryClientState,
    session_id: &str,
    root_thread_id: &str,
    commit_generation: u64,
    control_available: bool,
) -> QueryReadTicket {
    query.attach_session(DurableSessionReadParams {
        session_id: session_id.to_string(),
        root_thread_id: root_thread_id.to_string(),
    });
    let ticket = query.begin_read().expect("read should start");
    assert_eq!(
        query.apply_protocol_session_read_success(
            ticket,
            response(
                session_id,
                root_thread_id,
                commit_generation,
                control_available,
            ),
        ),
        QueryReadApplyResult::Applied
    );
    ticket
}

fn fresh_query() -> (DurableSessionQueryClientState, QueryReadTicket) {
    let mut query = DurableSessionQueryClientState::new();
    query.bind_connection();
    let ticket = attach_fresh(&mut query, "session-a", "root-a", 4, true);
    (query, ticket)
}

#[test]
fn begin_attempt_captures_only_the_accepted_fresh_query_proof() {
    let (query, accepted) = fresh_query();
    let mut control = DurableSessionControlAttemptState::new();
    let attempt = control
        .begin_attempt(&query, accepted, DurableSessionControlOperation::Archive)
        .expect("fresh available operation should capture");

    assert_eq!(attempt.params.session_id, "session-a");
    assert_eq!(attempt.params.root_thread_id, "root-a");
    assert_eq!(attempt.params.precondition.commit_generation, 4);
    assert_eq!(
        attempt.params.precondition.commit_fingerprint,
        "fingerprint-4"
    );
    assert_eq!(
        control.certainty(),
        &DurableSessionControlCertainty::Pending {
            operation: DurableSessionControlOperationKind::Archive
        }
    );
    assert_eq!(
        control.begin_attempt(&query, accepted, DurableSessionControlOperation::Archive),
        Err(DurableSessionControlCaptureError::AttemptPending)
    );
}

#[test]
fn refresh_and_unavailable_policy_retire_or_refuse_confirmation_tokens() {
    let (mut query, accepted) = fresh_query();
    let refresh = query.begin_read().expect("refresh should start");
    assert_eq!(
        query.apply_protocol_session_read_success(
            refresh,
            response("session-a", "root-a", 5, true),
        ),
        QueryReadApplyResult::Applied
    );
    let mut control = DurableSessionControlAttemptState::new();
    assert_eq!(
        control.begin_attempt(&query, accepted, DurableSessionControlOperation::Close),
        Err(DurableSessionControlCaptureError::ReadTicketRetired)
    );

    let mut unavailable = DurableSessionQueryClientState::new();
    unavailable.bind_connection();
    let ticket = attach_fresh(&mut unavailable, "session-b", "root-b", 1, false);
    assert_eq!(
        control.begin_attempt(&unavailable, ticket, DurableSessionControlOperation::Delete,),
        Err(DurableSessionControlCaptureError::OperationUnavailable)
    );
}

#[test]
fn every_typed_terminal_outcome_is_preserved_and_stales_the_query_view() {
    let cases = [
        (
            DurableSessionControlOutcome::Applied {
                effect: DurableSessionControlEffect::Archived {
                    affected_thread_ids: vec!["root-a".to_string()],
                },
            },
            DurableSessionControlCertainty::Applied {
                effect: DurableSessionControlEffect::Archived {
                    affected_thread_ids: vec!["root-a".to_string()],
                },
            },
        ),
        (
            DurableSessionControlOutcome::Rejected {
                operation: DurableSessionControlOperationKind::Archive,
                reason: DurableSessionControlRejectionReason::StalePrecondition,
                message: "stale".to_string(),
            },
            DurableSessionControlCertainty::Rejected {
                operation: DurableSessionControlOperationKind::Archive,
                reason: DurableSessionControlRejectionReason::StalePrecondition,
                message: "stale".to_string(),
            },
        ),
        (
            DurableSessionControlOutcome::Partial {
                operation: DurableSessionControlOperationKind::Archive,
                completed_thread_ids: vec!["child-a".to_string()],
                message: "root not moved".to_string(),
            },
            DurableSessionControlCertainty::Partial {
                operation: DurableSessionControlOperationKind::Archive,
                completed_thread_ids: vec!["child-a".to_string()],
                message: "root not moved".to_string(),
            },
        ),
        (
            DurableSessionControlOutcome::Unknown {
                operation: DurableSessionControlOperationKind::Archive,
                message: "completion lost".to_string(),
            },
            DurableSessionControlCertainty::Unknown {
                operation: DurableSessionControlOperationKind::Archive,
                message: "completion lost".to_string(),
            },
        ),
    ];

    for (outcome, expected) in cases {
        let (mut query, accepted) = fresh_query();
        let mut control = DurableSessionControlAttemptState::new();
        let attempt = control
            .begin_attempt(&query, accepted, DurableSessionControlOperation::Archive)
            .expect("attempt should start");
        assert!(control.apply_response(
            &mut query,
            attempt.ticket,
            DurableSessionControlResponse { outcome },
        ));
        assert_eq!(control.certainty(), &expected);
        assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
        assert_eq!(query.accepted_read_ticket(), None);
    }
}

#[test]
fn response_loss_is_unknown_and_late_completion_cannot_overwrite_a_new_attempt() {
    let (mut query, accepted) = fresh_query();
    let mut control = DurableSessionControlAttemptState::new();
    let first = control
        .begin_attempt(&query, accepted, DurableSessionControlOperation::Delete)
        .expect("first attempt should start");
    assert!(control.apply_unknown(&mut query, first.ticket, "transport closed after submit"));
    assert_eq!(
        control.certainty(),
        &DurableSessionControlCertainty::Unknown {
            operation: DurableSessionControlOperationKind::Delete,
            message: "transport closed after submit".to_string(),
        }
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);

    let reread = query
        .begin_read()
        .expect("explicit reconciliation should start");
    assert_eq!(
        query
            .apply_protocol_session_read_success(reread, response("session-a", "root-a", 5, true),),
        QueryReadApplyResult::Applied
    );
    let second = control
        .begin_attempt(&query, reread, DurableSessionControlOperation::Close)
        .expect("second attempt should start after explicit reread");

    assert!(!control.apply_response(
        &mut query,
        first.ticket,
        DurableSessionControlResponse {
            outcome: DurableSessionControlOutcome::Applied {
                effect: DurableSessionControlEffect::Deleted {
                    affected_thread_ids: vec!["root-a".to_string()],
                },
            },
        },
    ));
    assert_eq!(control.pending_ticket(), Some(second.ticket));
    assert_eq!(
        control.certainty(),
        &DurableSessionControlCertainty::Pending {
            operation: DurableSessionControlOperationKind::Close
        }
    );
}

#[test]
fn connection_loss_retires_pending_as_unknown_without_replay() {
    let (mut query, accepted) = fresh_query();
    let mut control = DurableSessionControlAttemptState::new();
    let attempt = control
        .begin_attempt(&query, accepted, DurableSessionControlOperation::Close)
        .expect("attempt should start");
    assert!(control.retire_pending_as_unknown(&mut query, "event stream EOF"));
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
    assert_eq!(control.pending_ticket(), None);
    assert_eq!(
        control.certainty(),
        &DurableSessionControlCertainty::Unknown {
            operation: DurableSessionControlOperationKind::Close,
            message: "event stream EOF".to_string(),
        }
    );
    assert!(!control.apply_response(
        &mut query,
        attempt.ticket,
        DurableSessionControlResponse {
            outcome: DurableSessionControlOutcome::Applied {
                effect: DurableSessionControlEffect::OwnerClosed,
            },
        },
    ));
}
