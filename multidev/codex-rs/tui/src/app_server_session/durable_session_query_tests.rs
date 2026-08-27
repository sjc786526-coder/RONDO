use super::*;
use crate::app_server_session::ThreadParamsMode;
use crate::legacy_core::config::ConfigBuilder;
use crate::tests::start_test_embedded_app_server;
use codex_app_server_client::AppServerClient;
use codex_app_server_client::InvalidSessionListProjection;
use codex_app_server_protocol::DurableSessionFactProvenance;
use codex_app_server_protocol::DurableSessionOperation;
use codex_app_server_protocol::DurableSessionOperationAvailability;
use codex_app_server_protocol::DurableSessionOperationAvailabilityReason;
use codex_app_server_protocol::DurableSessionOperations;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;

#[tokio::test]
async fn next_replaces_the_page_and_transport_loss_retires_late_completion()
-> color_eyre::Result<()> {
    let temp_dir = TempDir::new()?;
    let config = ConfigBuilder::default()
        .codex_home(temp_dir.path().to_path_buf())
        .build()
        .await?;
    let session = AppServerSession::new(
        AppServerClient::InProcess(start_test_embedded_app_server(config).await?),
        ThreadParamsMode::Embedded,
    );
    let first = session
        .durable_session_begin_list(DurableSessionListParams {
            cursor: None,
            limit: Some(2),
            archived: false,
        })
        .expect("connected list read should start");
    let DurableSessionQueryRequest::List {
        ticket: first_ticket,
        ..
    } = first
    else {
        panic!("list request must retain its response kind");
    };
    let first_page = DurableSessionListResponse {
        data: Vec::new(),
        next_cursor: Some("opaque-cursor".to_string()),
        complete: true,
        incomplete_reason: None,
    };
    assert_eq!(
        session.durable_session_apply_list(first_ticket, first_page.clone()),
        QueryReadApplyResult::Applied
    );

    let next = session
        .durable_session_begin_next()
        .expect("fresh page should expose its next cursor");
    let DurableSessionQueryRequest::List {
        ticket: next_ticket,
        params,
    } = next
    else {
        panic!("next must remain a list request");
    };
    assert_eq!(params.cursor.as_deref(), Some("opaque-cursor"));
    assert_eq!(session.durable_session_projection(), None);

    let second_page = DurableSessionListResponse {
        data: Vec::new(),
        next_cursor: None,
        complete: true,
        incomplete_reason: None,
    };
    assert_eq!(
        session.durable_session_apply_list(next_ticket, second_page.clone()),
        QueryReadApplyResult::Applied
    );
    let invalid_refresh = session
        .durable_session_begin_refresh()
        .expect("attached list should refresh");
    let DurableSessionQueryRequest::List {
        ticket: invalid_ticket,
        ..
    } = invalid_refresh
    else {
        panic!("list refresh must remain a list request");
    };
    assert_eq!(
        session.durable_session_apply_list(invalid_ticket, duplicate_protocol_list_response()),
        QueryReadApplyResult::RejectedInvalidListProjection(
            InvalidSessionListProjection::DuplicateSessionIdentity
        )
    );
    assert_eq!(
        session.durable_session_projection(),
        Some(DurableSessionQueryProjection::List(second_page.clone()))
    );
    assert_eq!(
        session.durable_session_view_freshness(),
        QueryViewFreshness::Stale
    );
    let refresh = session
        .durable_session_begin_refresh()
        .expect("attached list should refresh");
    let DurableSessionQueryRequest::List {
        ticket: refresh_ticket,
        ..
    } = refresh
    else {
        panic!("list refresh must remain a list request");
    };
    session.durable_session_on_lagged();
    assert_eq!(
        session.durable_session_view_freshness(),
        QueryViewFreshness::Stale
    );
    assert_eq!(
        session.durable_session_apply_list(refresh_ticket, first_page),
        QueryReadApplyResult::Retired
    );
    assert_eq!(
        session.durable_session_projection(),
        Some(DurableSessionQueryProjection::List(second_page))
    );
    assert_eq!(
        session.durable_session_view_freshness(),
        QueryViewFreshness::Stale
    );

    session.shutdown().await?;
    Ok(())
}

fn duplicate_protocol_list_response() -> DurableSessionListResponse {
    let operation = DurableSessionOperation {
        availability: DurableSessionOperationAvailability::Unknown {
            reason: DurableSessionOperationAvailabilityReason::Unsupported,
        },
        provenance: DurableSessionFactProvenance::DerivedPolicy,
    };
    let operation_availability = DurableSessionOperations {
        resume: operation.clone(),
        set_root_state: operation.clone(),
        close: operation.clone(),
        archive: operation.clone(),
        unarchive: operation.clone(),
        delete: operation,
    };
    let view = json!({
        "identity": {
            "sessionId": "session-a",
            "rootThreadId": null
        },
        "storageStatus": "unknown",
        "domainLifecycle": "unknown",
        "residency": "unknown",
        "operationAvailability": operation_availability,
        "provenance": {
            "identity": "unavailable",
            "storageStatus": "unavailable",
            "domainLifecycle": "unavailable",
            "residency": "unavailable",
            "team": "unavailable"
        },
        "readStatus": {
            "status": "unavailable",
            "issue": "identityUnavailable"
        },
        "team": null
    });
    serde_json::from_value(json!({
        "data": [view.clone(), view],
        "nextCursor": null,
        "complete": false,
        "incompleteReason": "classificationFailed"
    }))
    .expect("valid duplicate protocol list fixture")
}
