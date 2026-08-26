use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use anyhow::Result;
use app_test_support::DEFAULT_CLIENT_NAME;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_fake_parented_rollout_with_source;
use app_test_support::create_fake_rollout;
use app_test_support::create_final_assistant_message_sse_response;
use app_test_support::create_mock_responses_server_sequence_unchecked;
use codex_app_server::in_process;
use codex_app_server::in_process::InProcessServerEvent;
use codex_app_server::in_process::InProcessStartArgs;
use codex_app_server_protocol::ClientInfo;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::DurableSessionControlEffect;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlOutcome;
use codex_app_server_protocol::DurableSessionControlParams;
use codex_app_server_protocol::DurableSessionControlRejectionReason;
use codex_app_server_protocol::DurableSessionControlResponse;
use codex_app_server_protocol::DurableSessionDomainLifecycle;
use codex_app_server_protocol::DurableSessionFactProvenance;
use codex_app_server_protocol::DurableSessionListParams;
use codex_app_server_protocol::DurableSessionListResponse;
use codex_app_server_protocol::DurableSessionOperationAvailability;
use codex_app_server_protocol::DurableSessionReadIssue;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use codex_app_server_protocol::DurableSessionReadStatus;
use codex_app_server_protocol::DurableSessionResidency;
use codex_app_server_protocol::DurableSessionStorageStatus;
use codex_app_server_protocol::DurableSessionTeamProducerState;
use codex_app_server_protocol::DurableSessionTeamRootState;
use codex_app_server_protocol::ExperimentalSessionReadParams;
use codex_app_server_protocol::InitializeCapabilities;
use codex_app_server_protocol::InitializeParams;
use codex_app_server_protocol::JSONRPCError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadArchiveParams;
use codex_app_server_protocol::ThreadArchiveResponse;
use codex_app_server_protocol::ThreadLoadedListParams;
use codex_app_server_protocol::ThreadLoadedListResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::TurnStartResponse;
use codex_app_server_protocol::UserInput;
use codex_arg0::Arg0DispatchPaths;
use codex_config::CloudConfigBundleLoader;
use codex_config::LoaderOverrides;
use codex_core::config::ConfigBuilder;
use codex_core::init_state_db;
use codex_exec_server::EnvironmentManager;
use codex_features::Feature;
use codex_feedback::CodexFeedback;
use codex_protocol::SessionId;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use codex_thread_store::InMemoryThreadStore;
use core_test_support::responses;
use core_test_support::streaming_sse::StreamingSseChunk;
use core_test_support::streaming_sse::start_streaming_sse_server;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::sync::Arc;
use tempfile::TempDir;
use tokio::sync::Mutex;
use tokio::sync::oneshot;
use tokio::time::timeout;
use uuid::Uuid;

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(20);

#[tokio::test]
async fn durable_session_query_is_default_off() -> Result<()> {
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new("http://127.0.0.1:1").write(codex_home.path())?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let id = ThreadId::new().to_string();

    let request_id = mcp
        .send_durable_session_read_request(DurableSessionReadParams {
            session_id: id.clone(),
            root_thread_id: id,
        })
        .await?;
    let error = read_error(&mut mcp, request_id).await?;
    assert_eq!(error.error.code, -32600);
    assert!(
        error
            .error
            .message
            .contains("Durable Session query is disabled"),
        "{}",
        error.error.message
    );
    let request_id = mcp
        .send_durable_session_list_request(DurableSessionListParams::default())
        .await?;
    let error = read_error(&mut mcp, request_id).await?;
    assert_eq!(error.error.code, -32600);
    assert!(
        error
            .error
            .message
            .contains("Durable Session query is disabled")
    );
    let control_id = ThreadId::new().to_string();
    let control = session_control(
        &mut mcp,
        &control_id,
        dummy_committed_precondition(),
        DurableSessionControlOperation::Delete,
    )
    .await?;
    assert!(matches!(
        control.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::Unsupported,
            ..
        }
    ));
    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());
    Ok(())
}

#[tokio::test]
async fn durable_session_query_is_stable_and_independent_of_experimental_api() -> Result<()> {
    let codex_home = TempDir::new()?;
    write_query_config(codex_home.path(), "http://127.0.0.1:1", false)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build()
        .await?;
    mcp.initialize_with_capabilities(
        default_client_info(),
        Some(InitializeCapabilities {
            experimental_api: false,
            ..Default::default()
        }),
    )
    .await?;
    let id = ThreadId::new().to_string();

    let DurableSessionReadResponse { session } = session_read(&mut mcp, &id).await?;
    assert_eq!(session.identity.session_id, id);
    assert_eq!(session.identity.root_thread_id, None);
    assert_eq!(session.storage_status, DurableSessionStorageStatus::Unknown);
    assert_eq!(session.residency, DurableSessionResidency::Unknown);
    assert_eq!(
        session.provenance.identity,
        DurableSessionFactProvenance::Unavailable
    );
    assert_eq!(
        session.read_status,
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SessionNotFound,
        }
    );
    let listed = session_list(
        &mut mcp,
        DurableSessionListParams {
            cursor: None,
            limit: Some(1),
            archived: false,
        },
    )
    .await?;
    assert!(listed.complete);
    assert!(listed.data.is_empty());

    let request_id = mcp
        .send_durable_session_list_request(DurableSessionListParams {
            cursor: None,
            limit: Some(0),
            archived: false,
        })
        .await?;
    let error = read_error(&mut mcp, request_id).await?;
    assert_eq!(error.error.code, -32600);
    let control = session_control(
        &mut mcp,
        &id,
        dummy_committed_precondition(),
        DurableSessionControlOperation::Delete,
    )
    .await?;
    assert!(matches!(
        control.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::Unsupported,
            ..
        }
    ));
    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());
    Ok(())
}

#[tokio::test]
async fn durable_session_control_rejects_a_non_durable_root_without_side_effects() -> Result<()> {
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new("http://127.0.0.1:1")
        .enable_feature(Feature::DurableSessionQuery)
        .enable_feature(Feature::DurableSessionControl)
        .disable_feature(Feature::MultiAgentV2)
        .write(codex_home.path())?;
    let legacy_id = create_fake_rollout(
        codex_home.path(),
        "2026-08-25T10-00-00",
        "2026-08-25T10:00:00Z",
        "legacy control rejection",
        Some("mock_provider"),
        /*git_info*/ None,
    )?;
    let legacy_thread_id = ThreadId::from_string(&legacy_id)?;
    let rollout = codex_core::find_thread_path_by_id_str(
        codex_home.path(),
        &legacy_id,
        /*state_db_ctx*/ None,
    )
    .await?
    .expect("legacy Root rollout");
    let rollout_before = std::fs::read(&rollout)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;

    let read = session_read(&mut mcp, &legacy_id).await?.session;
    assert_eq!(
        read.read_status,
        DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::LegacySession,
        }
    );
    let control = session_control(
        &mut mcp,
        &legacy_id,
        dummy_committed_precondition(),
        DurableSessionControlOperation::Delete,
    )
    .await?;
    assert!(matches!(
        control.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::InvalidState,
            ..
        }
    ));
    assert_eq!(std::fs::read(&rollout)?, rollout_before);
    assert!(
        codex_core::find_thread_path_by_id_str(
            codex_home.path(),
            &legacy_thread_id.to_string(),
            /*state_db_ctx*/ None,
        )
        .await?
        .is_some()
    );
    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());
    Ok(())
}

#[tokio::test]
async fn durable_session_query_reports_an_unsupported_in_memory_source() -> Result<()> {
    let codex_home = TempDir::new()?;
    let store_id = Uuid::new_v4().to_string();
    MockResponsesConfig::new("http://127.0.0.1:1")
        .enable_feature(Feature::DurableSessionQuery)
        .with_root_config(&format!(
            r#"experimental_thread_store = {{ type = "in_memory", id = "{store_id}" }}"#
        ))
        .write(codex_home.path())?;
    let _store = InMemoryThreadStore::for_id(store_id.clone());
    let _store_registration = InMemoryThreadStoreId { store_id };

    let loader_overrides = LoaderOverrides::without_managed_config_for_tests();
    let config = ConfigBuilder::default()
        .codex_home(codex_home.path().to_path_buf())
        .fallback_cwd(Some(codex_home.path().to_path_buf()))
        .loader_overrides(loader_overrides.clone())
        .build()
        .await?;
    let client = in_process::start(InProcessStartArgs {
        arg0_paths: Arg0DispatchPaths::default(),
        config: Arc::new(config),
        cli_overrides: Vec::new(),
        loader_overrides,
        strict_config: false,
        cloud_config_bundle: CloudConfigBundleLoader::default(),
        thread_config_loader: Arc::new(codex_config::NoopThreadConfigLoader),
        feedback: CodexFeedback::new(),
        log_db: None,
        state_db: None,
        environment_manager: Arc::new(EnvironmentManager::default_for_tests()),
        config_warnings: Vec::new(),
        session_source: SessionSource::Cli,
        enable_codex_api_key_env: false,
        initialize: InitializeParams {
            client_info: default_client_info(),
            capabilities: Some(InitializeCapabilities {
                experimental_api: false,
                ..Default::default()
            }),
        },
        channel_capacity: in_process::DEFAULT_IN_PROCESS_CHANNEL_CAPACITY,
    })
    .await?;

    let result = client
        .request(ClientRequest::DurableSessionList {
            request_id: RequestId::Integer(1),
            params: DurableSessionListParams::default(),
        })
        .await?
        .expect("unsupported locator must return an explicit incomplete list");
    let response: DurableSessionListResponse = serde_json::from_value(result)?;
    assert!(response.data.is_empty());
    assert_eq!(response.next_cursor, None);
    assert!(!response.complete);
    assert_eq!(
        response.incomplete_reason,
        Some(codex_app_server_protocol::DurableSessionListIncompleteReason::SourceUnsupported)
    );

    let root_thread_id = ThreadId::new().to_string();
    let result = client
        .request(ClientRequest::DurableSessionRead {
            request_id: RequestId::Integer(2),
            params: DurableSessionReadParams {
                session_id: root_thread_id.clone(),
                root_thread_id,
            },
        })
        .await?
        .expect("unsupported metadata source must return an explicit unavailable view");
    let response: DurableSessionReadResponse = serde_json::from_value(result)?;
    assert_eq!(
        response.session.read_status,
        DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::SourceUnsupported,
        }
    );
    assert_eq!(response.session.identity.root_thread_id, None);
    assert_eq!(response.session.team, None);

    client.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn durable_session_query_reads_cold_commits_without_activation_or_writes() -> Result<()> {
    let model_server = responses::start_mock_server().await;
    let codex_home = TempDir::new()?;
    write_query_config(codex_home.path(), &model_server.uri(), true)?;
    let mut primary = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;

    let first = start_durable_session(&mut primary).await?;
    let second = start_durable_session(&mut primary).await?;
    let third = start_durable_session(&mut primary).await?;
    let hot = session_read(&mut primary, &first).await?.session;
    assert_eq!(hot.storage_status, DurableSessionStorageStatus::Active);
    assert_eq!(hot.residency, DurableSessionResidency::ObservedOwnerHere);
    assert_eq!(hot.domain_lifecycle, DurableSessionDomainLifecycle::Unknown);
    assert_eq!(hot.read_status, DurableSessionReadStatus::Available);
    assert!(hot.team.is_some());

    timeout(DEFAULT_TIMEOUT, primary.shutdown_gracefully()).await??;
    let common_created_at = "2026-08-25T11:59:59.123Z";
    for id in [&first, &second, &third] {
        let rollout = codex_core::find_thread_path_by_id_str(
            codex_home.path(),
            id,
            /*state_db_ctx*/ None,
        )
        .await?
        .expect("durable Root rollout");
        rewrite_session_meta_timestamp(&rollout, common_created_at)?;
    }
    // Force this test's private state DB to rebuild from the equal-createdAt, empty-preview Root
    // rollouts. The formal locator must not depend on the generic thread-list preview contract.
    remove_fixture_state_db(codex_home.path())?;
    let legacy = create_fake_rollout(
        codex_home.path(),
        "2026-08-25T12-00-00",
        "2026-08-25T12:00:00Z",
        "legacy Root",
        Some("mock_provider"),
        /*git_info*/ None,
    )?;
    let first_thread_id = ThreadId::from_string(&first)?;
    let child = create_fake_parented_rollout_with_source(
        codex_home.path(),
        "2026-08-25T12-01-00",
        "2026-08-25T12:01:00Z",
        "durable child locator",
        Some("mock_provider"),
        /*git_info*/ None,
        spawned_child_source(first_thread_id),
        SessionId::from(first_thread_id),
        first_thread_id,
    )?;
    // Server B intentionally has only the query product enabled. Existing durable data must stay
    // readable without re-enabling Team creation/runtime or the C0 control prototype.
    write_query_config(codex_home.path(), &model_server.uri(), false)?;

    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build()
        .await?;
    timeout(
        DEFAULT_TIMEOUT,
        restarted.initialize_with_capabilities(
            default_client_info(),
            Some(InitializeCapabilities {
                experimental_api: true,
                ..Default::default()
            }),
        ),
    )
    .await??;
    assert!(loaded_thread_ids(&mut restarted).await?.is_empty());

    let c0_request = restarted
        .send_experimental_session_read_request(ExperimentalSessionReadParams {
            session_id: first.clone(),
            prototype_facts: None,
        })
        .await?;
    let c0_error = read_error(&mut restarted, c0_request).await?;
    assert_eq!(c0_error.error.code, -32600);
    assert!(
        c0_error
            .error
            .message
            .contains("experimental Session control is disabled")
    );

    let child_view = session_read(&mut restarted, &child).await?.session;
    assert_eq!(
        child_view.read_status,
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::NotCanonicalRoot,
        }
    );
    assert_eq!(
        child_view.provenance.identity,
        DurableSessionFactProvenance::Unavailable
    );
    let mismatch_id = restarted
        .send_durable_session_read_request(DurableSessionReadParams {
            session_id: third.clone(),
            root_thread_id: first.clone(),
        })
        .await?;
    let mismatch: DurableSessionReadResponse =
        timeout(DEFAULT_TIMEOUT, restarted.read_response(mismatch_id)).await??;
    assert_eq!(
        mismatch.session.read_status,
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SessionRootIdentityMismatch,
        }
    );
    assert_eq!(
        mismatch.session.provenance.identity,
        DurableSessionFactProvenance::Unavailable
    );
    let legacy_view = session_read(&mut restarted, &legacy).await?.session;
    assert_eq!(
        legacy_view.read_status,
        DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::LegacySession,
        }
    );

    let second_rollout = codex_core::find_thread_path_by_id_str(
        codex_home.path(),
        &second,
        /*state_db_ctx*/ None,
    )
    .await?
    .expect("second durable Root rollout");
    let second_rollout_original =
        rewrite_durable_marker(&second_rollout, MarkerMutation::Version(u32::MAX))?;
    let incompatible_marker = session_read(&mut restarted, &second).await?.session;
    assert_eq!(
        incompatible_marker.read_status,
        DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::DurableMarkerIncompatible,
        }
    );
    assert_eq!(incompatible_marker.team, None);
    std::fs::write(&second_rollout, second_rollout_original)?;

    let third_rollout = codex_core::find_thread_path_by_id_str(
        codex_home.path(),
        &third,
        /*state_db_ctx*/ None,
    )
    .await?
    .expect("third durable Root rollout");
    let third_rollout_original = rewrite_durable_marker(
        &third_rollout,
        MarkerMutation::Root(ThreadId::new().to_string()),
    )?;
    let mismatched_marker = session_read(&mut restarted, &third).await?.session;
    assert_eq!(
        mismatched_marker.read_status,
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::DurableMarkerIdentityMismatch,
        }
    );
    assert_eq!(mismatched_marker.team, None);
    std::fs::write(&third_rollout, third_rollout_original)?;

    let snapshot_path = team_snapshot_path(codex_home.path(), &first);
    let snapshot_before = std::fs::read(&snapshot_path)?;
    let cold = session_read(&mut restarted, &first).await?.session;
    let snapshot_after = std::fs::read(&snapshot_path)?;
    assert_eq!(snapshot_after, snapshot_before);
    assert_eq!(cold.storage_status, DurableSessionStorageStatus::Active);
    assert_eq!(cold.residency, DurableSessionResidency::NotObservedHere);
    assert_eq!(
        cold.domain_lifecycle,
        DurableSessionDomainLifecycle::Unknown
    );
    assert_eq!(cold.read_status, DurableSessionReadStatus::Available);
    let cold_team = cold.team.expect("cold committed Team should project");
    assert!(cold_team.commit_generation > 0);
    assert!(cold_team.commit_fingerprint.starts_with("sha256:"));
    assert_eq!(cold_team.viewer.thread_id, first);
    assert!(loaded_thread_ids(&mut restarted).await?.is_empty());

    let first_page = session_list(
        &mut restarted,
        DurableSessionListParams {
            cursor: None,
            limit: Some(1),
            archived: false,
        },
    )
    .await?;
    assert!(!first_page.complete);
    assert_eq!(
        first_page.incomplete_reason,
        Some(codex_app_server_protocol::DurableSessionListIncompleteReason::SourceChanged)
    );
    assert_eq!(first_page.data.len(), 1);
    let first_page_session = first_page.data[0].identity.session_id.clone();
    // Keep the first-page Root active for the unreadable-record regression below; one of these
    // other two Roots is necessarily still unseen after a one-row first page.
    let archived_between_pages = [&second, &third]
        .into_iter()
        .find(|session_id| session_id.as_str() != first_page_session.as_str())
        .expect("at least one unseen durable Root")
        .clone();
    let active_cursor = first_page.next_cursor.expect("active page should continue");
    let _: ThreadArchiveResponse = restarted
        .request(|request_id| ClientRequest::ThreadArchive {
            request_id,
            params: ThreadArchiveParams {
                thread_id: archived_between_pages.clone(),
            },
        })
        .await?;
    let second_page = session_list(
        &mut restarted,
        DurableSessionListParams {
            cursor: Some(active_cursor.clone()),
            limit: Some(10),
            archived: false,
        },
    )
    .await?;
    assert!(!second_page.complete);
    assert_eq!(
        second_page.incomplete_reason,
        Some(codex_app_server_protocol::DurableSessionListIncompleteReason::SourceChanged)
    );
    assert_eq!(second_page.next_cursor, None);
    let discovered = first_page
        .data
        .into_iter()
        .chain(second_page.data)
        .map(|view| view.identity.session_id)
        .collect::<std::collections::BTreeSet<_>>();
    let mut expected_active =
        std::collections::BTreeSet::from([first.clone(), second.clone(), third.clone()]);
    expected_active.remove(&archived_between_pages);
    assert_eq!(discovered, expected_active);
    assert!(!discovered.contains(&archived_between_pages));
    assert!(!discovered.contains(&legacy));
    assert!(!discovered.contains(&child));

    let unreadable_rollout = codex_core::find_thread_path_by_id_str(
        codex_home.path(),
        &first_page_session,
        /*state_db_ctx*/ None,
    )
    .await?
    .expect("first-page durable Root rollout");
    let unreadable_rollout_original = std::fs::read(&unreadable_rollout)?;
    std::fs::write(&unreadable_rollout, b"{")?;
    let unreadable = session_list(
        &mut restarted,
        DurableSessionListParams {
            cursor: None,
            limit: Some(10),
            archived: false,
        },
    )
    .await?;
    assert!(!unreadable.complete);
    assert_eq!(
        unreadable.incomplete_reason,
        Some(codex_app_server_protocol::DurableSessionListIncompleteReason::RecordUnreadable)
    );
    assert!(
        unreadable
            .data
            .iter()
            .all(|view| view.identity.session_id != first_page_session)
    );
    std::fs::write(&unreadable_rollout, unreadable_rollout_original)?;

    let archived = session_list(
        &mut restarted,
        DurableSessionListParams {
            cursor: None,
            limit: Some(10),
            archived: true,
        },
    )
    .await?;
    assert!(archived.complete);
    assert_eq!(archived.data.len(), 1);
    assert_eq!(archived.next_cursor, None);
    assert_eq!(archived.data[0].identity.session_id, archived_between_pages);
    assert_eq!(
        archived.data[0].storage_status,
        DurableSessionStorageStatus::Archived
    );
    let cursor_request = restarted
        .send_durable_session_list_request(DurableSessionListParams {
            cursor: Some(active_cursor),
            limit: Some(1),
            archived: true,
        })
        .await?;
    let cursor_error = read_error(&mut restarted, cursor_request).await?;
    assert_eq!(cursor_error.error.code, -32600);

    let corrupt_path = team_snapshot_path(codex_home.path(), &second);
    std::fs::write(&corrupt_path, b"not a committed Team snapshot")?;
    let corrupt = session_read(&mut restarted, &second).await?.session;
    assert_eq!(
        corrupt.read_status,
        DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotCorrupt,
        }
    );
    assert_eq!(corrupt.team, None);

    let missing_path = team_snapshot_path(codex_home.path(), &third);
    std::fs::rename(
        &missing_path,
        missing_path.with_extension("team-state.missing"),
    )?;
    let missing = session_read(&mut restarted, &third).await?.session;
    assert_eq!(
        missing.read_status,
        DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotMissing,
        }
    );
    assert_eq!(missing.team, None);
    assert!(loaded_thread_ids(&mut restarted).await?.is_empty());

    let requests = model_server.received_requests().await.unwrap_or_default();
    assert!(
        requests
            .iter()
            .all(|request| !request.url.path().contains("responses")),
        "Durable Session queries must not call the model"
    );
    Ok(())
}

#[tokio::test]
async fn durable_session_control_revalidates_proof_and_reuses_cold_lifecycle() -> Result<()> {
    let model_server = responses::start_mock_server().await;
    let codex_home = TempDir::new()?;
    write_control_config(codex_home.path(), &model_server.uri())?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let root_thread_id = start_durable_session(&mut mcp).await?;

    let active = session_read(&mut mcp, &root_thread_id).await?.session;
    assert_eq!(active.storage_status, DurableSessionStorageStatus::Active);
    assert_eq!(active.residency, DurableSessionResidency::ObservedOwnerHere);
    let proof = active
        .control_precondition
        .expect("control-enabled complete query should return a proof");

    let mut stale = proof.clone();
    let codex_app_server_protocol::DurableSessionControlPrecondition::CommittedTeam {
        team_revision,
        ..
    } = &mut stale
    else {
        panic!("complete Team query should return a committed Team proof");
    };
    *team_revision = team_revision.saturating_add(1);
    let rejected = session_control(
        &mut mcp,
        &root_thread_id,
        stale,
        DurableSessionControlOperation::Archive,
    )
    .await?;
    assert!(matches!(
        rejected.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::NotCurrentOwner,
            ..
        }
    ));
    assert_eq!(
        session_read(&mut mcp, &root_thread_id)
            .await?
            .session
            .storage_status,
        DurableSessionStorageStatus::Active
    );

    let archived = session_control(
        &mut mcp,
        &root_thread_id,
        proof,
        DurableSessionControlOperation::Archive,
    )
    .await?;
    assert!(matches!(
        archived.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::Archived { .. }
        }
    ));
    let archived_view = session_read(&mut mcp, &root_thread_id).await?.session;
    assert_eq!(
        archived_view.storage_status,
        DurableSessionStorageStatus::Archived
    );
    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());

    let unarchived = session_control(
        &mut mcp,
        &root_thread_id,
        archived_view
            .control_precondition
            .expect("archived query should return a fresh proof"),
        DurableSessionControlOperation::Unarchive,
    )
    .await?;
    assert!(matches!(
        unarchived.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::Unarchived
        }
    ));
    let cold_active = session_read(&mut mcp, &root_thread_id).await?.session;
    assert_eq!(
        cold_active.storage_status,
        DurableSessionStorageStatus::Active
    );
    assert_eq!(
        cold_active.residency,
        DurableSessionResidency::NotObservedHere
    );

    let deleted = session_control(
        &mut mcp,
        &root_thread_id,
        cold_active
            .control_precondition
            .expect("cold active query should return a fresh proof"),
        DurableSessionControlOperation::Delete,
    )
    .await?;
    assert!(matches!(
        deleted.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::Deleted { .. }
        }
    ));
    let missing = session_read(&mut mcp, &root_thread_id).await?.session;
    assert_eq!(
        missing.read_status,
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SessionNotFound,
        }
    );
    assert!(
        model_server
            .received_requests()
            .await
            .unwrap_or_default()
            .iter()
            .all(|request| !request.url.path().ends_with("/responses"))
    );
    Ok(())
}

#[tokio::test]
async fn durable_session_control_rejects_a_replaced_owner_incarnation() -> Result<()> {
    let model_server = responses::start_mock_server().await;
    let codex_home = TempDir::new()?;
    write_control_config(codex_home.path(), &model_server.uri())?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let root_thread_id = start_durable_session(&mut mcp).await?;

    let owner_a = session_read(&mut mcp, &root_thread_id).await?.session;
    let owner_a_proof = owner_a
        .control_precondition
        .expect("loaded owner A should project a formal proof");
    let closed = session_control(
        &mut mcp,
        &root_thread_id,
        owner_a_proof.clone(),
        DurableSessionControlOperation::Close,
    )
    .await?;
    assert!(matches!(
        closed.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::OwnerClosed,
        }
    ));
    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());

    let resume_id = mcp
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: root_thread_id.clone(),
            ..Default::default()
        })
        .await?;
    let ThreadResumeResponse { thread, .. } =
        timeout(DEFAULT_TIMEOUT, mcp.read_response(resume_id)).await??;
    assert_eq!(thread.id, root_thread_id);

    let owner_b = session_read(&mut mcp, &root_thread_id).await?.session;
    let owner_b_proof = owner_b
        .control_precondition
        .clone()
        .expect("replacement owner B should project a formal proof");
    let (
        codex_app_server_protocol::DurableSessionControlPrecondition::CommittedTeam {
            owner_incarnation: Some(owner_a_incarnation),
            team_instance_id: owner_a_team,
            team_revision: owner_a_revision,
            commit_generation: owner_a_generation,
            commit_fingerprint: owner_a_fingerprint,
            ..
        },
        codex_app_server_protocol::DurableSessionControlPrecondition::CommittedTeam {
            owner_incarnation: Some(owner_b_incarnation),
            team_instance_id: owner_b_team,
            team_revision: owner_b_revision,
            commit_generation: owner_b_generation,
            commit_fingerprint: owner_b_fingerprint,
            ..
        },
    ) = (&owner_a_proof, &owner_b_proof)
    else {
        panic!("both loaded owners should carry committed Team proofs and authority incarnations");
    };
    assert_ne!(owner_a_incarnation, owner_b_incarnation);
    assert_eq!(owner_a_team, owner_b_team);
    assert_eq!(owner_a_revision, owner_b_revision);
    assert_eq!(owner_a_generation, owner_b_generation);
    assert_eq!(owner_a_fingerprint, owner_b_fingerprint);

    let rejected = session_control(
        &mut mcp,
        &root_thread_id,
        owner_a_proof,
        DurableSessionControlOperation::Close,
    )
    .await?;
    assert!(matches!(
        rejected.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::NotCurrentOwner,
            ..
        }
    ));
    assert_eq!(loaded_thread_ids(&mut mcp).await?, vec![root_thread_id]);
    assert_eq!(
        session_read(&mut mcp, &thread.id)
            .await?
            .session
            .control_precondition,
        Some(owner_b_proof)
    );
    Ok(())
}

#[tokio::test]
async fn durable_session_control_rejects_a_parented_self_consistent_root_before_delete()
-> Result<()> {
    let model_server = responses::start_mock_server().await;
    let codex_home = TempDir::new()?;
    write_control_config(codex_home.path(), &model_server.uri())?;
    let mut primary = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let root_thread_id = start_durable_session(&mut primary).await?;
    let rollout = codex_core::find_thread_path_by_id_str(
        codex_home.path(),
        &root_thread_id,
        /*state_db_ctx*/ None,
    )
    .await?
    .expect("durable Root rollout");
    let snapshot = team_snapshot_path(codex_home.path(), &root_thread_id);
    drop(primary);

    let mut cold_reader = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let cold_proof = session_read(&mut cold_reader, &root_thread_id)
        .await?
        .session
        .control_precondition
        .expect("cold self-consistent durable Root proof");
    assert!(matches!(
        &cold_proof,
        codex_app_server_protocol::DurableSessionControlPrecondition::CommittedTeam {
            expected_residency: DurableSessionResidency::NotObservedHere,
            owner_incarnation: None,
            ..
        }
    ));
    drop(cold_reader);

    rewrite_parent_thread_id(&rollout, ThreadId::new())?;
    let rollout_before = std::fs::read(&rollout)?;
    let snapshot_before = std::fs::read(&snapshot)?;
    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let rejected = session_control(
        &mut restarted,
        &root_thread_id,
        cold_proof,
        DurableSessionControlOperation::Delete,
    )
    .await?;
    assert!(matches!(
        rejected.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::NotCurrentOwner,
            ..
        }
    ));
    assert_eq!(std::fs::read(&rollout)?, rollout_before);
    assert_eq!(std::fs::read(&snapshot)?, snapshot_before);
    assert!(loaded_thread_ids(&mut restarted).await?.is_empty());
    Ok(())
}

#[tokio::test]
async fn durable_session_control_explicitly_retries_delete_from_the_root_marker() -> Result<()> {
    let model_server = responses::start_mock_server().await;
    let codex_home = TempDir::new()?;
    write_control_config(codex_home.path(), &model_server.uri())?;
    let mut primary = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let root_thread_id = start_durable_session(&mut primary).await?;
    let rollout = codex_core::find_thread_path_by_id_str(
        codex_home.path(),
        &root_thread_id,
        /*state_db_ctx*/ None,
    )
    .await?
    .expect("durable Root rollout");
    let snapshot = team_snapshot_path(codex_home.path(), &root_thread_id);
    drop(primary);
    std::fs::remove_file(&snapshot)?;
    assert!(rollout.is_file());

    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let recovery = session_read(&mut restarted, &root_thread_id).await?.session;
    assert_eq!(
        recovery.read_status,
        DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotMissing,
        }
    );
    assert_eq!(
        recovery.operation_availability.delete.availability,
        DurableSessionOperationAvailability::Available
    );
    let recovery_proof = recovery
        .control_precondition
        .expect("explicit delete retry proof");
    assert!(matches!(
        &recovery_proof,
        codex_app_server_protocol::DurableSessionControlPrecondition::DeleteRetryAnchor {
            expected_storage_status: DurableSessionStorageStatus::Active,
            expected_residency: DurableSessionResidency::NotObservedHere,
            ..
        }
    ));
    assert!(loaded_thread_ids(&mut restarted).await?.is_empty());

    let deleted = session_control(
        &mut restarted,
        &root_thread_id,
        recovery_proof,
        DurableSessionControlOperation::Delete,
    )
    .await?;
    assert!(matches!(
        deleted.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::Deleted { .. }
        }
    ));
    assert!(!rollout.exists());
    assert!(!snapshot.exists());
    assert_eq!(
        session_read(&mut restarted, &root_thread_id)
            .await?
            .session
            .read_status,
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SessionNotFound,
        }
    );
    assert!(
        model_server
            .received_requests()
            .await
            .unwrap_or_default()
            .iter()
            .all(|request| !request.url.path().ends_with("/responses"))
    );
    Ok(())
}

#[tokio::test]
async fn durable_session_control_updates_only_the_current_loaded_root_snapshot() -> Result<()> {
    let publish_args = serde_json::to_string(&json!({
        "title": "formal control event",
        "summary": "bind one root-state change to a committed query proof",
        "handoff": null
    }))?;
    let model_server = create_mock_responses_server_sequence_unchecked(vec![
        responses::sse(vec![
            responses::ev_response_created("formal-publish"),
            responses::ev_function_call_with_namespace(
                "formal-publish-call",
                "collaboration",
                "team_publish",
                &publish_args,
            ),
            responses::ev_completed("formal-publish"),
        ]),
        create_final_assistant_message_sse_response("published")?,
    ])
    .await;
    let codex_home = TempDir::new()?;
    write_control_config(codex_home.path(), &model_server.uri())?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let root_thread_id = start_durable_session(&mut mcp).await?;
    let _: TurnStartResponse = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: root_thread_id.clone(),
                input: vec![UserInput::Text {
                    text: "publish one durable Team event".to_string(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;
    timeout(
        DEFAULT_TIMEOUT,
        mcp.read_stream_until_notification_message("turn/completed"),
    )
    .await??;

    let before = session_read(&mut mcp, &root_thread_id).await?.session;
    let proof = before
        .control_precondition
        .clone()
        .expect("complete loaded query proof");
    let version = &before.team.as_ref().expect("Team projection").events[0].versions[0];
    assert_eq!(version.root_state, DurableSessionTeamRootState::Tracking);
    let operation = DurableSessionControlOperation::SetRootState {
        version_id: version.version_id.clone(),
        expected_producer_state: DurableSessionTeamProducerState::Open,
        expected_root_state: DurableSessionTeamRootState::Tracking,
        next_root_state: DurableSessionTeamRootState::Resolved,
    };
    let updated =
        session_control(&mut mcp, &root_thread_id, proof.clone(), operation.clone()).await?;
    assert!(matches!(
        updated.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::RootStateUpdated { changed: true, .. }
        }
    ));

    let stale = session_control(&mut mcp, &root_thread_id, proof, operation).await?;
    assert!(matches!(
        stale.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::StalePrecondition,
            ..
        }
    ));
    let after = session_read(&mut mcp, &root_thread_id).await?.session;
    assert_eq!(
        after.team.expect("Team projection").events[0].versions[0].root_state,
        DurableSessionTeamRootState::Resolved
    );
    Ok(())
}

#[tokio::test]
async fn durable_session_control_close_rejects_team_commit_after_preflight() -> Result<()> {
    assert_team_commit_after_control_preflight_is_rejected(DurableSessionControlOperation::Close)
        .await
}

#[tokio::test]
async fn durable_session_control_active_archive_rejects_team_commit_after_preflight() -> Result<()>
{
    assert_team_commit_after_control_preflight_is_rejected(DurableSessionControlOperation::Archive)
        .await
}

async fn assert_team_commit_after_control_preflight_is_rejected(
    operation: DurableSessionControlOperation,
) -> Result<()> {
    let publish_args = serde_json::to_string(&json!({
        "title": "commit after formal control preflight",
        "summary": "the Team commit must win before lifecycle linearization",
        "handoff": null
    }))?;
    let (model_release_tx, model_release_rx) = oneshot::channel();
    let (model_server, _completions) = start_streaming_sse_server(vec![
        vec![StreamingSseChunk {
            gate: Some(model_release_rx),
            body: responses::sse(vec![
                responses::ev_response_created("preflight-race-publish"),
                responses::ev_function_call_with_namespace(
                    "preflight-race-call",
                    "collaboration",
                    "team_publish",
                    &publish_args,
                ),
                responses::ev_completed("preflight-race-publish"),
            ]),
        }],
        vec![StreamingSseChunk {
            gate: None,
            body: create_final_assistant_message_sse_response("published after preflight")?,
        }],
    ])
    .await;
    let codex_home = TempDir::new()?;
    write_control_config(codex_home.path(), model_server.uri())?;
    let loader_overrides = LoaderOverrides::without_managed_config_for_tests();
    let cli_overrides = vec![
        (
            "features.multi_agent_v2.enabled".to_string(),
            toml::Value::Boolean(true),
        ),
        (
            "features.multi_agent_v2.team_state_enabled".to_string(),
            toml::Value::Boolean(true),
        ),
        (
            "features.multi_agent_v2.durable_team_enabled".to_string(),
            toml::Value::Boolean(true),
        ),
    ];
    let config = ConfigBuilder::default()
        .codex_home(codex_home.path().to_path_buf())
        .fallback_cwd(Some(codex_home.path().to_path_buf()))
        .cli_overrides(cli_overrides.clone())
        .loader_overrides(loader_overrides.clone())
        .build()
        .await?;
    let state_db = init_state_db(&config)
        .await
        .expect("formal query requires the supported local ThreadStore");
    let (preflight_entered_tx, preflight_entered_rx) = oneshot::channel();
    let preflight_entered_tx = Arc::new(Mutex::new(Some(preflight_entered_tx)));
    let (control_release_tx, control_release_rx) = oneshot::channel();
    let control_release_rx = Arc::new(Mutex::new(Some(control_release_rx)));
    let hook_entered = Arc::clone(&preflight_entered_tx);
    let hook_release = Arc::clone(&control_release_rx);
    let mut client = in_process::start_with_durable_session_control_preflight_hook(
        InProcessStartArgs {
            arg0_paths: Arg0DispatchPaths::default(),
            config: Arc::new(config),
            // Thread start reloads its Config through ConfigManager. Reuse the same explicit
            // overrides so the injected in-process runtime and its Root agree on Team mode.
            cli_overrides,
            loader_overrides,
            strict_config: false,
            cloud_config_bundle: CloudConfigBundleLoader::default(),
            thread_config_loader: Arc::new(codex_config::NoopThreadConfigLoader),
            feedback: CodexFeedback::new(),
            log_db: None,
            state_db: Some(state_db),
            environment_manager: Arc::new(EnvironmentManager::default_for_tests()),
            config_warnings: Vec::new(),
            session_source: SessionSource::Cli,
            enable_codex_api_key_env: false,
            initialize: InitializeParams {
                client_info: default_client_info(),
                capabilities: Some(InitializeCapabilities {
                    experimental_api: false,
                    ..Default::default()
                }),
            },
            channel_capacity: in_process::DEFAULT_IN_PROCESS_CHANNEL_CAPACITY,
        },
        move |thread_id, operation| {
            let hook_entered = Arc::clone(&hook_entered);
            let hook_release = Arc::clone(&hook_release);
            async move {
                if let Some(entered) = hook_entered.lock().await.take() {
                    let _ = entered.send((thread_id, operation));
                }
                let release = hook_release.lock().await.take();
                if let Some(release) = release {
                    let _ = release.await;
                }
            }
        },
    )
    .await?;
    let sender = client.sender();
    let start: ThreadStartResponse = serde_json::from_value(
        sender
            .request(ClientRequest::ThreadStart {
                request_id: RequestId::Integer(100),
                params: ThreadStartParams {
                    model: Some("mock-model".to_string()),
                    ..Default::default()
                },
            })
            .await?
            .expect("thread/start must succeed"),
    )?;
    let root_thread_id = start.thread.id;
    let before = timeout(DEFAULT_TIMEOUT, async {
        let mut request_id = 101;
        loop {
            let response: DurableSessionReadResponse = serde_json::from_value(
                sender
                    .request(ClientRequest::DurableSessionRead {
                        request_id: RequestId::Integer(request_id),
                        params: DurableSessionReadParams {
                            session_id: root_thread_id.clone(),
                            root_thread_id: root_thread_id.clone(),
                        },
                    })
                    .await?
                    .expect("formal query must succeed"),
            )?;
            if response.session.team.is_some() && response.session.control_precondition.is_some() {
                break Ok::<DurableSessionReadResponse, anyhow::Error>(response);
            }
            request_id += 1;
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await??;
    let before_revision = before
        .session
        .team
        .as_ref()
        .expect("Team projection")
        .revision;
    let proof = before
        .session
        .control_precondition
        .expect("loaded Root proof");
    let _: TurnStartResponse = serde_json::from_value(
        sender
            .request(ClientRequest::TurnStart {
                request_id: RequestId::Integer(10_002),
                params: TurnStartParams {
                    thread_id: root_thread_id.clone(),
                    input: vec![UserInput::Text {
                        text: "publish only after lifecycle preflight".to_string(),
                        text_elements: Vec::new(),
                    }],
                    ..Default::default()
                },
            })
            .await?
            .expect("turn/start must succeed"),
    )?;
    timeout(DEFAULT_TIMEOUT, model_server.wait_for_request_count(1)).await?;

    let control_sender = sender.clone();
    let control_root = root_thread_id.clone();
    let control_operation = operation.clone();
    let control = tokio::spawn(async move {
        control_sender
            .request(ClientRequest::DurableSessionControl {
                request_id: RequestId::Integer(10_003),
                params: DurableSessionControlParams {
                    session_id: control_root.clone(),
                    root_thread_id: control_root,
                    precondition: proof,
                    operation: control_operation,
                },
            })
            .await
    });
    let (hook_thread_id, hook_operation) = timeout(DEFAULT_TIMEOUT, preflight_entered_rx).await??;
    assert_eq!(hook_thread_id.to_string(), root_thread_id);
    assert_eq!(hook_operation, operation.kind());

    model_release_tx
        .send(())
        .expect("model response gate must still be held");
    timeout(DEFAULT_TIMEOUT, async {
        loop {
            match client.next_event().await {
                Some(InProcessServerEvent::ServerNotification(notification))
                    if matches!(
                        notification.as_ref(),
                        ServerNotification::TurnCompleted(completed)
                            if completed.thread_id == root_thread_id
                    ) =>
                {
                    break;
                }
                Some(_) => {}
                None => panic!("in-process runtime ended before turn/completed"),
            }
        }
    })
    .await?;
    control_release_tx
        .send(())
        .expect("formal control hook must still be held");
    let control_response: DurableSessionControlResponse = serde_json::from_value(
        timeout(DEFAULT_TIMEOUT, control)
            .await???
            .expect("formal control must return a typed response"),
    )?;
    assert!(matches!(
        control_response.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::StalePrecondition,
            ..
        }
    ));

    let after: DurableSessionReadResponse = serde_json::from_value(
        sender
            .request(ClientRequest::DurableSessionRead {
                request_id: RequestId::Integer(104),
                params: DurableSessionReadParams {
                    session_id: root_thread_id.clone(),
                    root_thread_id: root_thread_id.clone(),
                },
            })
            .await?
            .expect("post-race formal query must succeed"),
    )?;
    assert_eq!(
        after.session.storage_status,
        DurableSessionStorageStatus::Active
    );
    assert_eq!(
        after.session.residency,
        DurableSessionResidency::ObservedOwnerHere
    );
    let after_team = after.session.team.expect("post-race Team projection");
    assert!(after_team.revision > before_revision);
    assert!(
        after_team
            .events
            .iter()
            .any(|event| event.title == "commit after formal control preflight")
    );
    let loaded: ThreadLoadedListResponse = serde_json::from_value(
        sender
            .request(ClientRequest::ThreadLoadedList {
                request_id: RequestId::Integer(105),
                params: ThreadLoadedListParams::default(),
            })
            .await?
            .expect("thread/loaded/list must succeed"),
    )?;
    assert_eq!(loaded.data, vec![root_thread_id]);
    client.shutdown().await?;
    model_server.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn durable_session_query_reads_an_immediately_dropped_owner_as_cold() -> Result<()> {
    let model_server = responses::start_mock_server().await;
    let codex_home = TempDir::new()?;
    write_query_config(codex_home.path(), &model_server.uri(), true)?;
    let mut primary = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let session_id = start_durable_session(&mut primary).await?;
    assert_eq!(
        session_read(&mut primary, &session_id)
            .await?
            .session
            .read_status,
        DurableSessionReadStatus::Available
    );

    // TestAppServer owns a kill-on-drop child. Do not close stdio or run the graceful Session
    // shutdown path: the next process must consume only the commit made during activation.
    drop(primary);
    write_query_config(codex_home.path(), &model_server.uri(), false)?;
    let mut restarted = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let cold = session_read(&mut restarted, &session_id).await?.session;
    assert_eq!(cold.read_status, DurableSessionReadStatus::Available);
    assert_eq!(
        cold.domain_lifecycle,
        DurableSessionDomainLifecycle::Unknown
    );
    assert_eq!(cold.residency, DurableSessionResidency::NotObservedHere);
    assert!(cold.team.is_some());
    assert!(loaded_thread_ids(&mut restarted).await?.is_empty());
    let requests = model_server.received_requests().await.unwrap_or_default();
    assert!(
        requests
            .iter()
            .all(|request| !request.url.path().contains("responses"))
    );
    Ok(())
}

fn write_query_config(
    codex_home: &Path,
    model_server_uri: &str,
    enable_durable_team: bool,
) -> std::io::Result<()> {
    let mut config =
        MockResponsesConfig::new(model_server_uri).enable_feature(Feature::DurableSessionQuery);
    if enable_durable_team {
        config = config.with_extra_config(
            "[features.multi_agent_v2]\nenabled = true\nteam_state_enabled = true\ndurable_team_enabled = true",
        );
    } else {
        config = config
            .disable_feature(Feature::MultiAgentV2)
            .disable_feature(Feature::ExperimentalSessionControl);
    }
    config.write(codex_home)
}

fn write_control_config(codex_home: &Path, model_server_uri: &str) -> std::io::Result<()> {
    MockResponsesConfig::new(model_server_uri)
        .enable_feature(Feature::DurableSessionQuery)
        .enable_feature(Feature::DurableSessionControl)
        .with_extra_config(
            "[features.multi_agent_v2]\nenabled = true\nteam_state_enabled = true\ndurable_team_enabled = true",
        )
        .write(codex_home)
}

async fn start_durable_session(mcp: &mut TestAppServer) -> Result<String> {
    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;
    Ok(thread.id)
}

async fn session_read(mcp: &mut TestAppServer, id: &str) -> Result<DurableSessionReadResponse> {
    let request_id = mcp
        .send_durable_session_read_request(DurableSessionReadParams {
            session_id: id.to_string(),
            root_thread_id: id.to_string(),
        })
        .await?;
    timeout(DEFAULT_TIMEOUT, mcp.read_response(request_id)).await?
}

async fn session_control(
    mcp: &mut TestAppServer,
    id: &str,
    precondition: codex_app_server_protocol::DurableSessionControlPrecondition,
    operation: DurableSessionControlOperation,
) -> Result<DurableSessionControlResponse> {
    mcp.request(|request_id| ClientRequest::DurableSessionControl {
        request_id,
        params: DurableSessionControlParams {
            session_id: id.to_string(),
            root_thread_id: id.to_string(),
            precondition,
            operation,
        },
    })
    .await
}

fn dummy_committed_precondition() -> codex_app_server_protocol::DurableSessionControlPrecondition {
    codex_app_server_protocol::DurableSessionControlPrecondition::CommittedTeam {
        expected_storage_status: DurableSessionStorageStatus::Active,
        expected_residency: DurableSessionResidency::NotObservedHere,
        owner_incarnation: None,
        team_instance_id: "000000000000".to_string(),
        team_revision: 0,
        commit_generation: 0,
        commit_fingerprint: format!("sha256:{}", "00".repeat(32)),
    }
}

async fn session_list(
    mcp: &mut TestAppServer,
    params: DurableSessionListParams,
) -> Result<DurableSessionListResponse> {
    let request_id = mcp.send_durable_session_list_request(params).await?;
    timeout(DEFAULT_TIMEOUT, mcp.read_response(request_id)).await?
}

async fn loaded_thread_ids(mcp: &mut TestAppServer) -> Result<Vec<String>> {
    let request_id = mcp
        .send_thread_loaded_list_request(ThreadLoadedListParams::default())
        .await?;
    let ThreadLoadedListResponse { data, .. } =
        timeout(DEFAULT_TIMEOUT, mcp.read_response(request_id)).await??;
    Ok(data)
}

async fn read_error(mcp: &mut TestAppServer, request_id: i64) -> Result<JSONRPCError> {
    timeout(
        DEFAULT_TIMEOUT,
        mcp.read_stream_until_error_message(RequestId::Integer(request_id)),
    )
    .await?
}

fn team_snapshot_path(codex_home: &Path, thread_id: &str) -> PathBuf {
    codex_home
        .join("team-sessions/v1")
        .join(format!("{thread_id}.team-state"))
}

enum MarkerMutation {
    Version(u32),
    Root(String),
}

fn rewrite_durable_marker(path: &Path, mutation: MarkerMutation) -> Result<Vec<u8>> {
    let original = std::fs::read(path)?;
    let first_line_end = original
        .iter()
        .position(|byte| *byte == b'\n')
        .unwrap_or(original.len());
    let mut item: serde_json::Value = serde_json::from_slice(&original[..first_line_end])?;
    let marker = item
        .pointer_mut("/payload/durable_team")
        .ok_or_else(|| anyhow::anyhow!("canonical SessionMeta has no durable marker"))?;
    match mutation {
        MarkerMutation::Version(version) => marker["version"] = json!(version),
        MarkerMutation::Root(root_thread_id) => {
            marker["root_thread_id"] = json!(root_thread_id);
        }
    }
    let mut rewritten = serde_json::to_vec(&item)?;
    rewritten.extend_from_slice(&original[first_line_end..]);
    std::fs::write(path, rewritten)?;
    Ok(original)
}

fn rewrite_session_meta_timestamp(path: &Path, timestamp: &str) -> Result<()> {
    let original = std::fs::read(path)?;
    let first_line_end = original
        .iter()
        .position(|byte| *byte == b'\n')
        .unwrap_or(original.len());
    let mut item: serde_json::Value = serde_json::from_slice(&original[..first_line_end])?;
    item["timestamp"] = json!(timestamp);
    item["payload"]["timestamp"] = json!(timestamp);
    let mut rewritten = serde_json::to_vec(&item)?;
    rewritten.extend_from_slice(&original[first_line_end..]);
    std::fs::write(path, rewritten)?;
    Ok(())
}

fn rewrite_parent_thread_id(path: &Path, parent_thread_id: ThreadId) -> Result<()> {
    let original = std::fs::read(path)?;
    let first_line_end = original
        .iter()
        .position(|byte| *byte == b'\n')
        .unwrap_or(original.len());
    let mut item: serde_json::Value = serde_json::from_slice(&original[..first_line_end])?;
    item["payload"]["parent_thread_id"] = json!(parent_thread_id.to_string());
    let mut rewritten = serde_json::to_vec(&item)?;
    rewritten.extend_from_slice(&original[first_line_end..]);
    std::fs::write(path, rewritten)?;
    Ok(())
}

fn remove_fixture_state_db(codex_home: &Path) -> std::io::Result<()> {
    for name in ["state_5.sqlite", "state_5.sqlite-shm", "state_5.sqlite-wal"] {
        let path = codex_home.join(name);
        match std::fs::remove_file(path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error),
        }
    }
    Ok(())
}

struct InMemoryThreadStoreId {
    store_id: String,
}

impl Drop for InMemoryThreadStoreId {
    fn drop(&mut self) {
        InMemoryThreadStore::remove_id(&self.store_id);
    }
}

fn default_client_info() -> ClientInfo {
    ClientInfo {
        name: DEFAULT_CLIENT_NAME.to_string(),
        title: None,
        version: "0.1.0".to_string(),
    }
}

fn spawned_child_source(parent_thread_id: ThreadId) -> SessionSource {
    SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
        parent_thread_id,
        depth: 1,
        agent_path: None,
        agent_nickname: None,
        agent_role: None,
    })
}
