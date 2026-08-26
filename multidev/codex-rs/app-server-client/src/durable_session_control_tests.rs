use super::*;
use crate::QueryReadApplyResult;
use codex_app_server_protocol::DurableSessionControlEffect;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlOperationKind;
use codex_app_server_protocol::DurableSessionControlOutcome;
use codex_app_server_protocol::DurableSessionControlPrecondition;
use codex_app_server_protocol::DurableSessionControlRejectionReason;
use codex_app_server_protocol::DurableSessionControlResponse;
use codex_app_server_protocol::DurableSessionListParams;
use codex_app_server_protocol::DurableSessionListResponse;
use codex_app_server_protocol::DurableSessionReadIssue;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use codex_app_server_protocol::DurableSessionReadStatus;
use codex_app_server_protocol::DurableSessionResidency;
use codex_app_server_protocol::DurableSessionStorageStatus;
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
                    "type": "committedTeam",
                    "expectedStorageStatus": "active",
                    "expectedResidency": "observedOwnerHere",
                    "ownerIncarnation": "owner-a",
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

fn preview(
    control: &DurableSessionControlAttemptState,
    query: &DurableSessionQueryClientState,
    operation: DurableSessionControlOperation,
) -> DurableSessionControlPreview {
    control
        .preview_attempt(query, operation)
        .expect("preview should capture")
}

fn fresh_query() -> DurableSessionQueryClientState {
    let mut query = DurableSessionQueryClientState::new();
    query.bind_connection();
    attach_fresh(&mut query, "session-a", "root-a", 4, true);
    query
}

#[test]
fn preview_captures_target_without_entering_pending_then_begin_revalidates_it() {
    let query = fresh_query();
    let mut control = DurableSessionControlAttemptState::new();
    let preview = preview(&control, &query, DurableSessionControlOperation::Archive);
    assert_eq!(preview.session_id(), "session-a");
    assert_eq!(preview.root_thread_id(), "root-a");
    assert_eq!(
        preview.operation(),
        &DurableSessionControlOperation::Archive
    );
    assert_eq!(control.certainty(), &DurableSessionControlCertainty::None);
    assert_eq!(control.pending_ticket(), None);

    let attempt = control
        .begin_attempt(&query, preview)
        .expect("fresh available operation should capture");

    assert_eq!(attempt.params.session_id, "session-a");
    assert_eq!(attempt.params.root_thread_id, "root-a");
    assert!(matches!(
        attempt.params.precondition,
        DurableSessionControlPrecondition::CommittedTeam {
            commit_generation: 4,
            ref commit_fingerprint,
            ..
        } if commit_fingerprint == "fingerprint-4"
    ));
    assert_eq!(
        control.certainty(),
        &DurableSessionControlCertainty::Pending {
            operation: DurableSessionControlOperationKind::Archive
        }
    );
    let second_preview = control.preview_attempt(&query, DurableSessionControlOperation::Archive);
    assert_eq!(
        second_preview,
        Err(DurableSessionControlCaptureError::AttemptPending)
    );
}

#[test]
fn refresh_and_lag_retire_a_preview_before_pending_is_installed() {
    let mut query = fresh_query();
    let mut control = DurableSessionControlAttemptState::new();
    let retired_by_refresh = preview(&control, &query, DurableSessionControlOperation::Close);
    let refresh = query.begin_read().expect("refresh should start");
    assert_eq!(
        query.apply_protocol_session_read_success(
            refresh,
            response("session-a", "root-a", 5, true),
        ),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        control.begin_attempt(&query, retired_by_refresh),
        Err(DurableSessionControlCaptureError::ReadTicketRetired)
    );

    let retired_by_lag = preview(&control, &query, DurableSessionControlOperation::Close);
    query.on_lagged();
    assert_eq!(
        control.begin_attempt(&query, retired_by_lag),
        Err(DurableSessionControlCaptureError::QueryViewNotFresh)
    );
    assert_eq!(control.pending_ticket(), None);
}

#[test]
fn preview_rejects_list_attachment_unavailable_operation_and_missing_proof() {
    let control = DurableSessionControlAttemptState::new();
    let mut list = DurableSessionQueryClientState::new();
    list.bind_connection();
    list.attach_list(DurableSessionListParams::default());
    let list_ticket = list.begin_read().expect("list read should start");
    assert_eq!(
        list.apply_protocol_list_read_success(
            list_ticket,
            DurableSessionListResponse {
                data: Vec::new(),
                next_cursor: None,
                complete: true,
                incomplete_reason: None,
            },
        ),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        control.preview_attempt(&list, DurableSessionControlOperation::Archive),
        Err(DurableSessionControlCaptureError::NotSessionAttachment)
    );

    let mut unavailable = DurableSessionQueryClientState::new();
    unavailable.bind_connection();
    attach_fresh(&mut unavailable, "session-b", "root-b", 1, false);
    assert_eq!(
        control.preview_attempt(&unavailable, DurableSessionControlOperation::Delete),
        Err(DurableSessionControlCaptureError::OperationUnavailable)
    );

    let mut missing_proof = DurableSessionQueryClientState::new();
    missing_proof.bind_connection();
    missing_proof.attach_session(DurableSessionReadParams {
        session_id: "session-c".to_string(),
        root_thread_id: "root-c".to_string(),
    });
    let read = missing_proof.begin_read().expect("read should start");
    let mut without_proof = response("session-c", "root-c", 1, true);
    without_proof.session.control_precondition = None;
    assert_eq!(
        missing_proof.apply_protocol_session_read_success(read, without_proof),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        control.preview_attempt(&missing_proof, DurableSessionControlOperation::Close),
        Err(DurableSessionControlCaptureError::ControlProofUnavailable)
    );
}

#[test]
fn tagged_delete_retry_proof_can_preview_only_delete() {
    let control = DurableSessionControlAttemptState::new();
    let mut query = DurableSessionQueryClientState::new();
    query.bind_connection();
    query.attach_session(DurableSessionReadParams {
        session_id: "session-retry".to_string(),
        root_thread_id: "root-retry".to_string(),
    });
    let read = query.begin_read().expect("retry-anchor read should start");
    let mut retry = response("session-retry", "root-retry", 1, true);
    retry.session.read_status = DurableSessionReadStatus::Incomplete {
        issue: DurableSessionReadIssue::TeamSnapshotMissing,
    };
    retry.session.residency = DurableSessionResidency::NotObservedHere;
    retry.session.team = None;
    retry.session.control_precondition =
        Some(DurableSessionControlPrecondition::DeleteRetryAnchor {
            expected_storage_status: DurableSessionStorageStatus::Active,
            expected_residency: DurableSessionResidency::NotObservedHere,
            root_marker_fingerprint: "sha256:root-marker".to_string(),
        });
    assert_eq!(
        query.apply_protocol_session_read_success(read, retry),
        QueryReadApplyResult::Applied
    );

    assert_eq!(
        control.preview_attempt(&query, DurableSessionControlOperation::Close),
        Err(DurableSessionControlCaptureError::ControlProofUnavailable)
    );
    let delete = control
        .preview_attempt(&query, DurableSessionControlOperation::Delete)
        .expect("delete retry proof should preview Delete");
    assert_eq!(delete.operation(), &DurableSessionControlOperation::Delete);
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
        let mut query = fresh_query();
        let mut control = DurableSessionControlAttemptState::new();
        let preview = preview(&control, &query, DurableSessionControlOperation::Archive);
        let attempt = control
            .begin_attempt(&query, preview)
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
    let mut query = fresh_query();
    let mut control = DurableSessionControlAttemptState::new();
    let first_preview = preview(&control, &query, DurableSessionControlOperation::Delete);
    let first = control
        .begin_attempt(&query, first_preview)
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
    let second_preview = preview(&control, &query, DurableSessionControlOperation::Close);
    let second = control
        .begin_attempt(&query, second_preview)
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
    let mut query = fresh_query();
    let mut control = DurableSessionControlAttemptState::new();
    let preview = preview(&control, &query, DurableSessionControlOperation::Close);
    let attempt = control
        .begin_attempt(&query, preview)
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
