use std::sync::Arc;
use std::time::Duration;

use anyhow::Result;
use app_test_support::DEFAULT_CLIENT_NAME;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::create_fake_parented_rollout_with_source;
use app_test_support::create_fake_rollout;
use app_test_support::create_final_assistant_message_sse_response;
use app_test_support::create_mock_responses_server_repeating_assistant;
use app_test_support::create_mock_responses_server_sequence_unchecked;
use codex_app_server::in_process;
use codex_app_server::in_process::InProcessStartArgs;
use codex_app_server_protocol::ClientInfo;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::ExperimentalSessionDomainLifecycle;
use codex_app_server_protocol::ExperimentalSessionFactProvenance;
use codex_app_server_protocol::ExperimentalSessionListParams;
use codex_app_server_protocol::ExperimentalSessionListResponse;
use codex_app_server_protocol::ExperimentalSessionOperationAvailability;
use codex_app_server_protocol::ExperimentalSessionOperationUnavailableReason;
use codex_app_server_protocol::ExperimentalSessionPrototypeFacts;
use codex_app_server_protocol::ExperimentalSessionReadParams;
use codex_app_server_protocol::ExperimentalSessionReadResponse;
use codex_app_server_protocol::ExperimentalSessionResidency;
use codex_app_server_protocol::ExperimentalSessionTeamProducerState;
use codex_app_server_protocol::ExperimentalSessionTeamRootState;
use codex_app_server_protocol::ExperimentalSessionUpdateTeamLifecycleParams;
use codex_app_server_protocol::ExperimentalSessionUpdateTeamLifecycleResponse;
use codex_app_server_protocol::InitializeCapabilities;
use codex_app_server_protocol::JSONRPCError;
use codex_app_server_protocol::JSONRPCMessage;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadArchiveParams;
use codex_app_server_protocol::ThreadArchiveResponse;
use codex_app_server_protocol::ThreadLoadedListParams;
use codex_app_server_protocol::ThreadLoadedListResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::ThreadStatus;
use codex_app_server_protocol::ThreadUnarchiveParams;
use codex_app_server_protocol::ThreadUnarchiveResponse;
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
use core_test_support::responses;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;
use tokio::time::timeout;

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(20);

#[tokio::test]
async fn experimental_session_requests_require_experimental_api_capability() -> Result<()> {
    let codex_home = TempDir::new()?;
    write_session_config(codex_home.path(), "http://127.0.0.1:1", false)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build()
        .await?;

    let initialized = mcp
        .initialize_with_capabilities(
            default_client_info(),
            Some(InitializeCapabilities {
                experimental_api: false,
                ..Default::default()
            }),
        )
        .await?;
    assert!(matches!(initialized, JSONRPCMessage::Response(_)));

    let request_id = mcp
        .send_experimental_session_list_request(ExperimentalSessionListParams::default())
        .await?;
    let error = read_error(&mut mcp, request_id).await?;
    assert_eq!(error.error.code, -32600);
    assert_eq!(
        error.error.message,
        "experimentalSession/list requires experimentalApi capability"
    );

    Ok(())
}

#[tokio::test]
async fn experimental_api_capability_does_not_enable_the_session_product() -> Result<()> {
    let codex_home = TempDir::new()?;
    MockResponsesConfig::new("http://127.0.0.1:1").write(codex_home.path())?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;

    let request_id = mcp
        .send_experimental_session_read_request(ExperimentalSessionReadParams {
            session_id: ThreadId::new().to_string(),
            prototype_facts: None,
        })
        .await?;
    let error = read_error(&mut mcp, request_id).await?;
    assert_eq!(error.error.code, -32600);
    assert!(
        error
            .error
            .message
            .contains("experimental Session control is disabled"),
        "{}",
        error.error.message
    );

    Ok(())
}

#[tokio::test]
async fn session_list_reports_an_unavailable_state_db_as_incomplete() -> Result<()> {
    let codex_home = TempDir::new()?;
    write_session_config(codex_home.path(), "http://127.0.0.1:1", false)?;
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
        session_source: codex_protocol::protocol::SessionSource::Cli,
        enable_codex_api_key_env: false,
        initialize: codex_app_server_protocol::InitializeParams {
            client_info: default_client_info(),
            capabilities: Some(InitializeCapabilities {
                experimental_api: true,
                ..Default::default()
            }),
        },
        channel_capacity: in_process::DEFAULT_IN_PROCESS_CHANNEL_CAPACITY,
    })
    .await?;

    let result = client
        .request(ClientRequest::ExperimentalSessionList {
            request_id: RequestId::Integer(1),
            params: ExperimentalSessionListParams::default(),
        })
        .await?
        .expect("Session list should return an explicit incomplete response");
    let response: ExperimentalSessionListResponse = serde_json::from_value(result)?;
    assert!(response.data.is_empty());
    assert_eq!(response.next_cursor, None);
    assert_eq!(
        response.provenance,
        ExperimentalSessionFactProvenance::Unavailable
    );
    assert!(!response.complete);

    client.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn session_list_reports_a_failed_state_db_query_as_incomplete() -> Result<()> {
    let codex_home = TempDir::new()?;
    write_session_config(codex_home.path(), "http://127.0.0.1:1", false)?;
    let loader_overrides = LoaderOverrides::without_managed_config_for_tests();
    let config = ConfigBuilder::default()
        .codex_home(codex_home.path().to_path_buf())
        .fallback_cwd(Some(codex_home.path().to_path_buf()))
        .loader_overrides(loader_overrides.clone())
        .build()
        .await?;
    let state_db = init_state_db(&config)
        .await
        .expect("state DB should initialize before fault injection");
    let state_db_fault_handle = Arc::clone(&state_db);
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
        state_db: Some(state_db),
        environment_manager: Arc::new(EnvironmentManager::default_for_tests()),
        config_warnings: Vec::new(),
        session_source: SessionSource::Cli,
        enable_codex_api_key_env: false,
        initialize: codex_app_server_protocol::InitializeParams {
            client_info: default_client_info(),
            capabilities: Some(InitializeCapabilities {
                experimental_api: true,
                ..Default::default()
            }),
        },
        channel_capacity: in_process::DEFAULT_IN_PROCESS_CHANNEL_CAPACITY,
    })
    .await?;

    state_db_fault_handle.close().await;
    let result = client
        .request(ClientRequest::ExperimentalSessionList {
            request_id: RequestId::Integer(2),
            params: ExperimentalSessionListParams::default(),
        })
        .await?
        .expect("query failure should produce an explicit incomplete response");
    let response: ExperimentalSessionListResponse = serde_json::from_value(result)?;
    assert!(response.data.is_empty());
    assert_eq!(response.next_cursor, None);
    assert_eq!(
        response.provenance,
        ExperimentalSessionFactProvenance::Unavailable
    );
    assert!(!response.complete);

    client.shutdown().await?;
    Ok(())
}

#[tokio::test]
async fn session_list_scans_past_a_full_child_page_to_find_the_root() -> Result<()> {
    let codex_home = TempDir::new()?;
    let root_id = create_fake_rollout(
        codex_home.path(),
        "2026-08-24T12-00-00",
        "2026-08-24T12:00:00Z",
        "older Root Session",
        Some("mock_provider"),
        /*git_info*/ None,
    )?;
    let root_thread_id = ThreadId::from_string(&root_id)?;
    let root_session_id = SessionId::from(root_thread_id);
    let mut child_ids = Vec::new();
    for minute in 1..=25 {
        let timestamp = format!("2026-08-24T12-{minute:02}-00");
        let metadata_timestamp = format!("2026-08-24T12:{minute:02}:00Z");
        child_ids.push(create_fake_parented_rollout_with_source(
            codex_home.path(),
            &timestamp,
            &metadata_timestamp,
            "newer child",
            Some("mock_provider"),
            /*git_info*/ None,
            spawned_child_source(root_thread_id),
            root_session_id,
            root_thread_id,
        )?);
    }
    write_session_config(codex_home.path(), "http://127.0.0.1:1", false)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;

    let request_id = mcp
        .send_experimental_session_list_request(ExperimentalSessionListParams::default())
        .await?;
    let response: ExperimentalSessionListResponse =
        timeout(DEFAULT_TIMEOUT, mcp.read_response(request_id)).await??;
    assert!(response.complete);
    assert_eq!(response.next_cursor, None);
    assert_eq!(response.data.len(), 1);
    assert_eq!(response.data[0].identity.session_id, root_id);
    assert!(
        response
            .data
            .iter()
            .all(|session| !child_ids.contains(&session.identity.session_id))
    );

    Ok(())
}

#[tokio::test]
async fn session_list_and_read_do_not_activate_an_unloaded_session() -> Result<()> {
    let model_server = create_mock_responses_server_repeating_assistant("Done").await;
    let codex_home = TempDir::new()?;
    let unloaded_id = create_fake_rollout(
        codex_home.path(),
        "2026-08-24T12-00-00",
        "2026-08-24T12:00:00Z",
        "unloaded Session",
        Some("mock_provider"),
        /*git_info*/ None,
    )?;
    write_session_config(codex_home.path(), &model_server.uri(), true)?;

    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let ThreadStartResponse {
        thread: loaded_thread,
        ..
    } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;

    let loaded_before = loaded_thread_ids(&mut mcp).await?;
    assert_eq!(loaded_before, vec![loaded_thread.id.clone()]);

    let list = session_list(&mut mcp).await?;
    assert!(list.complete);
    assert_eq!(
        list.provenance,
        ExperimentalSessionFactProvenance::StateDbPrototype
    );
    assert!(
        list.data
            .iter()
            .any(|session| session.identity.session_id == unloaded_id)
    );

    let unloaded = session_read(&mut mcp, &unloaded_id, None).await?;
    assert_eq!(
        unloaded.residency,
        ExperimentalSessionResidency::UnloadedResumable
    );
    assert_eq!(
        unloaded.domain_lifecycle,
        ExperimentalSessionDomainLifecycle::Unknown
    );
    assert_eq!(
        unloaded.identity.root_thread_id.as_deref(),
        Some(unloaded_id.as_str())
    );
    assert_eq!(unloaded.team, None);
    assert_eq!(
        unloaded
            .operation_availability
            .update_team_lifecycle
            .availability,
        unavailable(ExperimentalSessionOperationUnavailableReason::OwnerUnavailable)
    );

    let loaded = session_read(&mut mcp, &loaded_thread.id, None).await?;
    assert_eq!(loaded.residency, ExperimentalSessionResidency::LoadedOwner);
    assert_eq!(
        loaded.domain_lifecycle,
        ExperimentalSessionDomainLifecycle::Unknown
    );
    assert_eq!(
        loaded.provenance.domain_lifecycle,
        ExperimentalSessionFactProvenance::Unavailable
    );
    assert_eq!(
        loaded.provenance.team,
        ExperimentalSessionFactProvenance::LiveOwner
    );
    assert!(loaded.team.is_some());
    assert_eq!(
        loaded
            .operation_availability
            .update_team_lifecycle
            .availability,
        ExperimentalSessionOperationAvailability::Available
    );

    let loaded_after = loaded_thread_ids(&mut mcp).await?;
    assert_eq!(loaded_after, loaded_before);

    Ok(())
}

#[tokio::test]
async fn prototype_only_lifecycles_are_never_reported_as_durable_authority() -> Result<()> {
    let codex_home = TempDir::new()?;
    write_session_config(codex_home.path(), "http://127.0.0.1:1", false)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;

    for lifecycle in [
        ExperimentalSessionDomainLifecycle::Closed,
        ExperimentalSessionDomainLifecycle::Failed,
        ExperimentalSessionDomainLifecycle::Partial,
        ExperimentalSessionDomainLifecycle::Unknown,
    ] {
        let view = session_read(
            &mut mcp,
            &ThreadId::new().to_string(),
            Some(ExperimentalSessionPrototypeFacts {
                domain_lifecycle: lifecycle,
            }),
        )
        .await?;
        assert_eq!(view.domain_lifecycle, lifecycle);
        assert_eq!(
            view.provenance.domain_lifecycle,
            ExperimentalSessionFactProvenance::PrototypeInput
        );
        assert_eq!(
            view.provenance.identity,
            ExperimentalSessionFactProvenance::Unavailable
        );
        assert_eq!(view.residency, ExperimentalSessionResidency::Unknown);
        assert_eq!(view.team, None);
    }

    Ok(())
}

#[tokio::test]
async fn archive_and_unarchive_use_thread_authority_without_loading_the_session() -> Result<()> {
    let model_server = create_mock_responses_server_repeating_assistant("Done").await;
    let codex_home = TempDir::new()?;
    let session_id = create_fake_rollout(
        codex_home.path(),
        "2026-08-24T13-00-00",
        "2026-08-24T13:00:00Z",
        "cold Session",
        Some("mock_provider"),
        /*git_info*/ None,
    )?;
    write_session_config(codex_home.path(), &model_server.uri(), false)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;

    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());
    let _: ThreadArchiveResponse = mcp
        .request(|request_id| ClientRequest::ThreadArchive {
            request_id,
            params: ThreadArchiveParams {
                thread_id: session_id.clone(),
            },
        })
        .await?;

    let archived = session_read(&mut mcp, &session_id, None).await?;
    assert_eq!(
        archived.domain_lifecycle,
        ExperimentalSessionDomainLifecycle::Archived
    );
    assert_eq!(
        archived.residency,
        ExperimentalSessionResidency::UnloadedNotResumable
    );
    assert_eq!(
        archived.operation_availability.unarchive.availability,
        ExperimentalSessionOperationAvailability::Available
    );
    assert_eq!(
        archived
            .operation_availability
            .update_team_lifecycle
            .availability,
        unavailable(ExperimentalSessionOperationUnavailableReason::Archived)
    );
    assert_eq!(
        archived.operation_availability.archive.availability,
        unavailable(ExperimentalSessionOperationUnavailableReason::Unsupported)
    );
    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());

    let ThreadUnarchiveResponse { thread } = mcp
        .request(|request_id| ClientRequest::ThreadUnarchive {
            request_id,
            params: ThreadUnarchiveParams {
                thread_id: session_id.clone(),
            },
        })
        .await?;
    assert_eq!(thread.status, ThreadStatus::NotLoaded);

    let unarchived = session_read(&mut mcp, &session_id, None).await?;
    assert_eq!(
        unarchived.residency,
        ExperimentalSessionResidency::UnloadedResumable
    );
    assert_ne!(
        unarchived.domain_lifecycle,
        ExperimentalSessionDomainLifecycle::Archived
    );
    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());

    let mutation_id = mcp
        .send_experimental_session_update_team_lifecycle_request(
            ExperimentalSessionUpdateTeamLifecycleParams {
                root_thread_id: session_id.clone(),
                version_id: "team-absent:ver-1".to_string(),
                expected_producer_state: ExperimentalSessionTeamProducerState::Open,
                expected_root_state: ExperimentalSessionTeamRootState::Pending,
                next_root_state: ExperimentalSessionTeamRootState::Resolved,
            },
        )
        .await?;
    let error = read_error(&mut mcp, mutation_id).await?;
    assert_eq!(error.error.code, -32600);
    assert!(
        error
            .error
            .message
            .contains("loaded Session owner is unavailable"),
        "{}",
        error.error.message
    );

    Ok(())
}

#[tokio::test]
async fn archived_child_is_not_a_cold_session_unarchive_target() -> Result<()> {
    let codex_home = TempDir::new()?;
    let root_id = create_fake_rollout(
        codex_home.path(),
        "2026-08-24T13-10-00",
        "2026-08-24T13:10:00Z",
        "archived Root",
        Some("mock_provider"),
        /*git_info*/ None,
    )?;
    let root_thread_id = ThreadId::from_string(&root_id)?;
    let child_id = create_fake_parented_rollout_with_source(
        codex_home.path(),
        "2026-08-24T13-11-00",
        "2026-08-24T13:11:00Z",
        "archived child",
        Some("mock_provider"),
        /*git_info*/ None,
        spawned_child_source(root_thread_id),
        SessionId::from(root_thread_id),
        root_thread_id,
    )?;
    write_session_config(codex_home.path(), "http://127.0.0.1:1", false)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;

    for thread_id in [&child_id, &root_id] {
        let _: ThreadArchiveResponse = mcp
            .request(|request_id| ClientRequest::ThreadArchive {
                request_id,
                params: ThreadArchiveParams {
                    thread_id: thread_id.clone(),
                },
            })
            .await?;
    }

    let child = session_read(&mut mcp, &child_id, None).await?;
    assert_eq!(
        child.operation_availability.unarchive.availability,
        unavailable(ExperimentalSessionOperationUnavailableReason::IdentityUnavailable)
    );
    let root = session_read(&mut mcp, &root_id, None).await?;
    assert_eq!(
        root.operation_availability.unarchive.availability,
        ExperimentalSessionOperationAvailability::Available
    );

    let _: ThreadUnarchiveResponse = mcp
        .request(|request_id| ClientRequest::ThreadUnarchive {
            request_id,
            params: ThreadUnarchiveParams {
                thread_id: root_id.clone(),
            },
        })
        .await?;
    let child_after = session_read(&mut mcp, &child_id, None).await?;
    assert_eq!(
        child_after.domain_lifecycle,
        ExperimentalSessionDomainLifecycle::Archived
    );
    assert_eq!(
        child_after.operation_availability.unarchive.availability,
        unavailable(ExperimentalSessionOperationUnavailableReason::IdentityUnavailable)
    );
    assert!(loaded_thread_ids(&mut mcp).await?.is_empty());

    Ok(())
}

#[tokio::test]
async fn loaded_child_is_projected_as_non_owner_and_cannot_mutate_the_team() -> Result<()> {
    const CHILD_PROMPT: &str = "hold a loaded child Session for the control prototype";
    const PARENT_PROMPT: &str = "spawn one child for the control prototype";
    const SPAWN_CALL_ID: &str = "spawn-session-control-child";

    let model_server = responses::start_mock_server().await;
    let spawn_args = serde_json::to_string(&json!({
        "message": CHILD_PROMPT,
        "task_name": "session_control_child",
        "fork_turns": "none",
    }))?;
    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| {
            String::from_utf8_lossy(&request.body).contains(PARENT_PROMPT)
        },
        responses::sse(vec![
            responses::ev_response_created("parent-spawn"),
            responses::ev_function_call_with_namespace(
                SPAWN_CALL_ID,
                "collaboration",
                "spawn_agent",
                &spawn_args,
            ),
            responses::ev_completed("parent-spawn"),
        ]),
    )
    .await;
    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| {
            let body = String::from_utf8_lossy(&request.body);
            body.contains(CHILD_PROMPT) && !body.contains(SPAWN_CALL_ID)
        },
        responses::sse(vec![
            responses::ev_response_created("child-work"),
            responses::ev_assistant_message("child-message", "child complete"),
            responses::ev_completed("child-work"),
        ]),
    )
    .await;
    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| {
            String::from_utf8_lossy(&request.body).contains(SPAWN_CALL_ID)
        },
        create_final_assistant_message_sse_response("parent complete")?,
    )
    .await;

    let codex_home = TempDir::new()?;
    write_session_config(codex_home.path(), &model_server.uri(), true)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;
    let root_thread_id = thread.id;

    let _: TurnStartResponse = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: root_thread_id.clone(),
                input: vec![UserInput::Text {
                    text: PARENT_PROMPT.to_string(),
                    text_elements: Vec::new(),
                }],
                ..Default::default()
            },
        })
        .await?;

    let child_thread_id = timeout(DEFAULT_TIMEOUT, async {
        loop {
            if let Some(child_thread_id) = loaded_thread_ids(&mut mcp)
                .await?
                .into_iter()
                .find(|thread_id| thread_id != &root_thread_id)
            {
                return Ok::<String, anyhow::Error>(child_thread_id);
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await??;

    let child_view = session_read(&mut mcp, &child_thread_id, None).await?;
    assert_eq!(
        child_view.identity.root_thread_id.as_deref(),
        Some(root_thread_id.as_str())
    );
    assert_eq!(
        child_view.residency,
        ExperimentalSessionResidency::LoadedNonOwner
    );
    assert_eq!(
        child_view
            .operation_availability
            .update_team_lifecycle
            .availability,
        unavailable(ExperimentalSessionOperationUnavailableReason::NotOwner)
    );
    assert_eq!(
        child_view
            .operation_availability
            .update_team_lifecycle
            .provenance,
        ExperimentalSessionFactProvenance::LiveRuntime
    );

    let mutation_id = mcp
        .send_experimental_session_update_team_lifecycle_request(
            ExperimentalSessionUpdateTeamLifecycleParams {
                root_thread_id: child_thread_id,
                version_id: "not-reached".to_string(),
                expected_producer_state: ExperimentalSessionTeamProducerState::Open,
                expected_root_state: ExperimentalSessionTeamRootState::Pending,
                next_root_state: ExperimentalSessionTeamRootState::Resolved,
            },
        )
        .await?;
    let error = read_error(&mut mcp, mutation_id).await?;
    assert_eq!(error.error.code, -32600);
    assert!(
        error.error.message.contains("not the loaded Session owner"),
        "{}",
        error.error.message
    );

    Ok(())
}

#[tokio::test]
async fn child_only_projection_is_query_id_invariant_and_fails_closed() -> Result<()> {
    let codex_home = TempDir::new()?;
    let root_id = create_fake_rollout(
        codex_home.path(),
        "2026-08-24T14-00-00",
        "2026-08-24T14:00:00Z",
        "unloaded Root",
        Some("mock_provider"),
        /*git_info*/ None,
    )?;
    let root_thread_id = ThreadId::from_string(&root_id)?;
    let child_id = create_fake_parented_rollout_with_source(
        codex_home.path(),
        "2026-08-24T14-01-00",
        "2026-08-24T14:01:00Z",
        "loaded child only",
        Some("mock_provider"),
        /*git_info*/ None,
        spawned_child_source(root_thread_id),
        SessionId::from(root_thread_id),
        root_thread_id,
    )?;
    write_session_config(codex_home.path(), "http://127.0.0.1:1", false)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;

    let _: ThreadResumeResponse = mcp
        .request(|request_id| ClientRequest::ThreadResume {
            request_id,
            params: ThreadResumeParams {
                thread_id: child_id.clone(),
                exclude_turns: true,
                ..Default::default()
            },
        })
        .await?;
    assert_eq!(loaded_thread_ids(&mut mcp).await?, vec![child_id.clone()]);

    let root_query = session_read(&mut mcp, &root_id, None).await?;
    let child_query = session_read(&mut mcp, &child_id, None).await?;
    assert_eq!(root_query, child_query);
    assert_eq!(
        child_query.residency,
        ExperimentalSessionResidency::OwnerUnavailable
    );
    assert_eq!(
        child_query
            .operation_availability
            .update_team_lifecycle
            .availability,
        unavailable(ExperimentalSessionOperationUnavailableReason::ChildOnly)
    );

    for root_thread_id in [&root_id, &child_id] {
        let request_id = mcp
            .send_experimental_session_update_team_lifecycle_request(
                ExperimentalSessionUpdateTeamLifecycleParams {
                    root_thread_id: root_thread_id.clone(),
                    version_id: "not-reached".to_string(),
                    expected_producer_state: ExperimentalSessionTeamProducerState::Open,
                    expected_root_state: ExperimentalSessionTeamRootState::Pending,
                    next_root_state: ExperimentalSessionTeamRootState::Resolved,
                },
            )
            .await?;
        let error = read_error(&mut mcp, request_id).await?;
        assert_eq!(error.error.code, -32600);
    }

    Ok(())
}

#[tokio::test]
async fn loaded_owner_updates_team_lifecycle_and_conflicts_fail_closed() -> Result<()> {
    let publish_args = serde_json::to_string(&json!({
        "title": "prototype event",
        "summary": "the owner published a deterministic Team checkpoint",
        "handoff": "exercise the root lifecycle seam"
    }))?;
    let model_server = create_mock_responses_server_sequence_unchecked(vec![
        responses::sse(vec![
            responses::ev_response_created("publish-response"),
            responses::ev_function_call_with_namespace(
                "publish-call",
                "collaboration",
                "team_publish",
                &publish_args,
            ),
            responses::ev_completed("publish-response"),
        ]),
        create_final_assistant_message_sse_response("published")?,
    ])
    .await;
    let codex_home = TempDir::new()?;
    write_session_config(codex_home.path(), &model_server.uri(), true)?;
    let mut mcp = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let ThreadStartResponse { thread, .. } = mcp
        .start_thread(ThreadStartParams {
            model: Some("mock-model".to_string()),
            ..Default::default()
        })
        .await?;

    let _: TurnStartResponse = mcp
        .request(|request_id| ClientRequest::TurnStart {
            request_id,
            params: TurnStartParams {
                thread_id: thread.id.clone(),
                input: vec![UserInput::Text {
                    text: "publish one Team event".to_string(),
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

    let before = session_read(&mut mcp, &thread.id, None).await?;
    let team = before.team.expect("loaded owner should expose a Team view");
    assert_eq!(team.events.len(), 1);
    assert_eq!(team.events[0].versions.len(), 1);
    let version = &team.events[0].versions[0];
    assert_eq!(
        version.producer_state,
        ExperimentalSessionTeamProducerState::Open
    );
    assert_eq!(
        version.root_state,
        ExperimentalSessionTeamRootState::Tracking
    );

    let params = ExperimentalSessionUpdateTeamLifecycleParams {
        root_thread_id: thread.id.clone(),
        version_id: version.version_id.clone(),
        expected_producer_state: ExperimentalSessionTeamProducerState::Open,
        expected_root_state: ExperimentalSessionTeamRootState::Tracking,
        next_root_state: ExperimentalSessionTeamRootState::Resolved,
    };
    let update_id = mcp
        .send_experimental_session_update_team_lifecycle_request(params.clone())
        .await?;
    let update: ExperimentalSessionUpdateTeamLifecycleResponse =
        timeout(DEFAULT_TIMEOUT, mcp.read_response(update_id)).await??;
    assert!(update.changed);
    assert!(update.revision > team.revision);
    assert_eq!(
        update.version.root_state,
        ExperimentalSessionTeamRootState::Resolved
    );

    let after = session_read(&mut mcp, &thread.id, None).await?;
    let after_team = after.team.expect("post-mutation Team read should succeed");
    assert!(after_team.revision >= update.revision);
    assert_eq!(
        after_team.events[0].versions[0].root_state,
        ExperimentalSessionTeamRootState::Resolved
    );

    let conflict_id = mcp
        .send_experimental_session_update_team_lifecycle_request(params)
        .await?;
    let conflict = read_error(&mut mcp, conflict_id).await?;
    assert_eq!(conflict.error.code, -32600);
    assert!(
        conflict
            .error
            .message
            .contains("lifecycle precondition no longer holds"),
        "{}",
        conflict.error.message
    );

    Ok(())
}

fn write_session_config(
    codex_home: &std::path::Path,
    model_server_uri: &str,
    enable_team_state: bool,
) -> std::io::Result<()> {
    let mut config = MockResponsesConfig::new(model_server_uri)
        .enable_feature(Feature::ExperimentalSessionControl);
    if enable_team_state {
        config = config.with_extra_config(
            "[features.multi_agent_v2]\nenabled = true\nteam_state_enabled = true",
        );
    }
    config.write(codex_home)
}

async fn session_list(mcp: &mut TestAppServer) -> Result<ExperimentalSessionListResponse> {
    let request_id = mcp
        .send_experimental_session_list_request(ExperimentalSessionListParams {
            cursor: None,
            limit: Some(50),
        })
        .await?;
    timeout(DEFAULT_TIMEOUT, mcp.read_response(request_id)).await?
}

async fn session_read(
    mcp: &mut TestAppServer,
    session_id: &str,
    prototype_facts: Option<ExperimentalSessionPrototypeFacts>,
) -> Result<codex_app_server_protocol::ExperimentalSessionView> {
    let request_id = mcp
        .send_experimental_session_read_request(ExperimentalSessionReadParams {
            session_id: session_id.to_string(),
            prototype_facts,
        })
        .await?;
    let ExperimentalSessionReadResponse { session } =
        timeout(DEFAULT_TIMEOUT, mcp.read_response(request_id)).await??;
    Ok(session)
}

async fn loaded_thread_ids(mcp: &mut TestAppServer) -> Result<Vec<String>> {
    let request_id = mcp
        .send_thread_loaded_list_request(ThreadLoadedListParams::default())
        .await?;
    let ThreadLoadedListResponse { mut data, .. } =
        timeout(DEFAULT_TIMEOUT, mcp.read_response(request_id)).await??;
    data.sort();
    Ok(data)
}

async fn read_error(mcp: &mut TestAppServer, request_id: i64) -> Result<JSONRPCError> {
    timeout(
        DEFAULT_TIMEOUT,
        mcp.read_stream_until_error_message(RequestId::Integer(request_id)),
    )
    .await?
}

fn unavailable(
    reason: ExperimentalSessionOperationUnavailableReason,
) -> ExperimentalSessionOperationAvailability {
    ExperimentalSessionOperationAvailability::Unavailable { reason }
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
