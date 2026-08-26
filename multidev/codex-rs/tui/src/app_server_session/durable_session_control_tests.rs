use super::*;
use codex_app_server_client::QueryReadApplyResult;
use codex_app_server_client::QueryViewFreshness;
use codex_app_server_protocol::DurableSessionControlEffect;
use codex_app_server_protocol::DurableSessionControlOperationKind;
use codex_app_server_protocol::DurableSessionControlOutcome;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn bridge_uses_one_query_projection_and_retires_late_results_after_loss() {
    let query = Mutex::new(fresh_query());
    let bridge = DurableSessionControlBridge::new();
    let preview = bridge
        .preview(&query, DurableSessionControlOperation::Close)
        .expect("fresh query should expose an available operation");
    let attempt = bridge
        .begin(&query, preview)
        .expect("fresh formal proof should produce one attempt");

    let retired = {
        let mut query = query
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        bridge.retire_pending_as_unknown(&mut query, EVENT_STREAM_CLOSED_RESULT_MESSAGE)
    };
    assert!(retired);
    assert_eq!(
        bridge.certainty(),
        DurableSessionControlCertainty::Unknown {
            operation: DurableSessionControlOperationKind::Close,
            message: EVENT_STREAM_CLOSED_RESULT_MESSAGE.to_string(),
        }
    );
    assert_eq!(
        query
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .view_freshness(),
        QueryViewFreshness::Stale
    );
    assert!(!bridge.apply_response(
        &query,
        attempt.ticket,
        DurableSessionControlResponse {
            outcome: DurableSessionControlOutcome::Applied {
                effect: DurableSessionControlEffect::OwnerClosed,
            },
        },
    ));
}

#[test]
fn control_disable_retires_a_preview_without_detaching_the_query() {
    let query = Mutex::new(fresh_query());
    let bridge = DurableSessionControlBridge::new();
    let preview = bridge
        .preview(&query, DurableSessionControlOperation::Delete)
        .expect("fresh query should expose an available operation");

    {
        let mut query = query
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        assert!(!bridge.retire_pending_as_unknown(&mut query, DISABLED_RESULT_MESSAGE));
        query.on_lagged();
        assert!(matches!(
            query.attachment(),
            Some(codex_app_server_client::DurableSessionQueryAttachment::Session(_))
        ));
        assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
    }

    assert!(matches!(
        bridge.begin(&query, preview),
        Err(DurableSessionControlCaptureError::QueryViewNotFresh)
    ));
}

fn fresh_query() -> DurableSessionQueryClientState {
    let mut query = DurableSessionQueryClientState::new();
    query.bind_connection();
    query.attach_session(DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-a".to_string(),
    });
    let ticket = query.begin_read().expect("connected read should start");
    assert_eq!(
        query.apply_protocol_session_read_success(ticket, formal_session_response()),
        QueryReadApplyResult::Applied
    );
    query
}

fn formal_session_response() -> DurableSessionReadResponse {
    let available = json!({
        "availability": { "status": "available" },
        "provenance": "derivedPolicy"
    });
    serde_json::from_value(json!({
        "session": {
            "identity": {
                "sessionId": "session-a",
                "rootThreadId": "root-a"
            },
            "storageStatus": "active",
            "domainLifecycle": "open",
            "residency": "observedOwnerHere",
            "operationAvailability": {
                "resume": available,
                "setRootState": available,
                "close": available,
                "archive": available,
                "unarchive": available,
                "delete": available
            },
            "controlPrecondition": {
                "type": "committedTeam",
                "expectedStorageStatus": "active",
                "expectedResidency": "observedOwnerHere",
                "ownerIncarnation": "owner-a",
                "teamInstanceId": "team-a",
                "teamRevision": 7,
                "commitGeneration": 4,
                "commitFingerprint": "fingerprint-4"
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
                "teamInstanceId": "team-a",
                "commitGeneration": 4,
                "commitFingerprint": "fingerprint-4",
                "revision": 7,
                "viewer": { "threadId": "root-a", "role": "root" },
                "participants": [],
                "omittedParticipants": 0,
                "events": [],
                "omittedEvents": 0
            }
        }
    }))
    .expect("valid formal Session response")
}
