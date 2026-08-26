use std::path::Path;
use std::time::Duration;

use anyhow::Result;
use app_test_support::MockResponsesConfig;
use app_test_support::TestAppServer;
use app_test_support::write_models_cache_with_models;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::DurableSessionControlEffect;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlOutcome;
use codex_app_server_protocol::DurableSessionControlParams;
use codex_app_server_protocol::DurableSessionControlRejectionReason;
use codex_app_server_protocol::DurableSessionControlResponse;
use codex_app_server_protocol::DurableSessionDomainLifecycle;
use codex_app_server_protocol::DurableSessionReadIssue;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use codex_app_server_protocol::DurableSessionReadStatus;
use codex_app_server_protocol::DurableSessionResidency;
use codex_app_server_protocol::DurableSessionStorageStatus;
use codex_app_server_protocol::DurableSessionTeamProducerState;
use codex_app_server_protocol::DurableSessionTeamRole;
use codex_app_server_protocol::DurableSessionTeamRootState;
use codex_app_server_protocol::ThreadLoadedListParams;
use codex_app_server_protocol::ThreadLoadedListResponse;
use codex_app_server_protocol::ThreadResumeParams;
use codex_app_server_protocol::ThreadResumeResponse;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_app_server_protocol::TurnStartParams;
use codex_app_server_protocol::UserInput;
use codex_features::Feature;
use codex_models_manager::model_info::model_info_from_slug;
use codex_protocol::protocol::MultiAgentVersion;
use core_test_support::responses;
use pretty_assertions::assert_eq;
use serde_json::json;
use tempfile::TempDir;
use tokio::time::timeout;

const DEFAULT_TIMEOUT: Duration = Duration::from_secs(20);
const NAMESPACE: &str = "collaboration";

#[tokio::test]
async fn durable_team_survives_process_replacement_and_completes_public_lifecycle() -> Result<()> {
    const ROOT_PROMPT: &str = "run the durable Team full-chain collaboration";
    const CHILD_PROMPT: &str = "publish the durable child checkpoint";
    const CLOSE_CHILD_PROMPT: &str = "close the recovered durable worker";
    const SPAWN_CALL_ID: &str = "full-chain-spawn-worker";
    const PUBLISH_CALL_ID: &str = "full-chain-child-publish";
    const WAIT_CALL_ID: &str = "full-chain-wait-worker";
    const CLOSE_CALL_ID: &str = "full-chain-close-worker";
    const EVENT_TITLE: &str = "durable child checkpoint";
    const EVENT_SUMMARY: &str = "the child committed through the canonical Team writer";

    let model_server = responses::start_mock_server().await;
    let spawn_args = serde_json::to_string(&json!({
        "message": CHILD_PROMPT,
        "task_name": "durable_worker",
        "fork_turns": "none",
    }))?;
    let publish_args = serde_json::to_string(&json!({
        "title": EVENT_TITLE,
        "summary": EVENT_SUMMARY,
        "handoff": "resume the same Team after process replacement",
    }))?;

    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| String::from_utf8_lossy(&request.body).contains(ROOT_PROMPT),
        responses::sse(vec![
            responses::ev_response_created("full-chain-root-spawn"),
            responses::ev_function_call_with_namespace(
                SPAWN_CALL_ID,
                NAMESPACE,
                "spawn_agent",
                &spawn_args,
            ),
            responses::ev_completed("full-chain-root-spawn"),
        ]),
    )
    .await;
    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| {
            let body = String::from_utf8_lossy(&request.body);
            body.contains(CHILD_PROMPT)
                && !body.contains(SPAWN_CALL_ID)
                && !body.contains(PUBLISH_CALL_ID)
        },
        responses::sse(vec![
            responses::ev_response_created("full-chain-child-publish"),
            responses::ev_function_call_with_namespace(
                PUBLISH_CALL_ID,
                NAMESPACE,
                "team_publish",
                &publish_args,
            ),
            responses::ev_completed("full-chain-child-publish"),
        ]),
    )
    .await;
    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| {
            String::from_utf8_lossy(&request.body).contains(PUBLISH_CALL_ID)
        },
        responses::sse(vec![
            responses::ev_response_created("full-chain-child-complete"),
            responses::ev_assistant_message(
                "full-chain-child-message",
                "durable child checkpoint committed",
            ),
            responses::ev_completed("full-chain-child-complete"),
        ]),
    )
    .await;
    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| {
            let body = String::from_utf8_lossy(&request.body);
            body.contains(SPAWN_CALL_ID) && !body.contains(WAIT_CALL_ID)
        },
        responses::sse(vec![
            responses::ev_response_created("full-chain-root-wait"),
            responses::ev_function_call_with_namespace(WAIT_CALL_ID, NAMESPACE, "wait_agent", "{}"),
            responses::ev_completed("full-chain-root-wait"),
        ]),
    )
    .await;
    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| String::from_utf8_lossy(&request.body).contains(WAIT_CALL_ID),
        responses::sse(vec![
            responses::ev_response_created("full-chain-root-complete"),
            responses::ev_assistant_message(
                "full-chain-root-message",
                "durable Team collaboration complete",
            ),
            responses::ev_completed("full-chain-root-complete"),
        ]),
    )
    .await;

    let codex_home = TempDir::new()?;
    write_config(codex_home.path(), &model_server.uri())?;
    let mut model_info = model_info_from_slug("gpt-5.4");
    model_info.multi_agent_version = Some(MultiAgentVersion::V2);
    write_models_cache_with_models(codex_home.path(), vec![model_info])?;
    let mut primary = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let ThreadStartResponse { thread, .. } = primary
        .start_thread(ThreadStartParams {
            model: Some("gpt-5.4".to_string()),
            ..Default::default()
        })
        .await?;
    let root_thread_id = thread.id;
    timeout(
        DEFAULT_TIMEOUT,
        primary.start_turn_and_wait_for_completion(TurnStartParams {
            thread_id: root_thread_id.clone(),
            input: vec![UserInput::Text {
                text: ROOT_PROMPT.to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        }),
    )
    .await??;

    let initial = session_read(&mut primary, &root_thread_id, &root_thread_id)
        .await?
        .session;
    assert_eq!(initial.identity.session_id, root_thread_id);
    assert_eq!(
        initial.identity.root_thread_id.as_deref(),
        Some(root_thread_id.as_str())
    );
    assert_eq!(initial.storage_status, DurableSessionStorageStatus::Active);
    assert_eq!(
        initial.residency,
        DurableSessionResidency::ObservedOwnerHere
    );
    assert_eq!(initial.read_status, DurableSessionReadStatus::Available);
    let initial_team = initial.team.expect("complete initial Team projection");
    assert_eq!(initial_team.viewer.thread_id, root_thread_id);
    assert_eq!(initial_team.viewer.role, DurableSessionTeamRole::Root);
    assert_eq!(initial_team.events.len(), 1);
    assert_eq!(initial_team.events[0].title, EVENT_TITLE);
    assert_eq!(initial_team.events[0].versions.len(), 1);
    let initial_version = &initial_team.events[0].versions[0];
    assert_eq!(initial_version.summary, EVENT_SUMMARY);
    assert_ne!(initial_version.author_thread_id, root_thread_id);
    let child_thread_id = initial_version.author_thread_id.clone();
    assert!(initial_team.participants.iter().any(|participant| {
        participant.thread_id == root_thread_id && participant.role == DurableSessionTeamRole::Root
    }));
    assert!(initial_team.participants.iter().any(|participant| {
        participant.thread_id == child_thread_id
            && participant.role == DurableSessionTeamRole::Member
    }));
    let team_instance_id = initial_team.team_instance_id.clone();
    let initial_generation = initial_team.commit_generation;
    let initial_fingerprint = initial_team.commit_fingerprint.clone();
    let version_id = initial_version.version_id.clone();
    let initial_root_state = initial_version.root_state;
    let requests_before_restart = response_request_count(&model_server).await;
    assert_eq!(requests_before_restart, 5);

    // Dropping the client closes stdio and the harness waits for the real OS child to exit,
    // force-terminating it after a bounded grace period when the open child blocks Root close.
    drop(primary);

    let mut replacement = TestAppServer::builder()
        .with_codex_home(codex_home.path())
        .without_auto_env()
        .build_initialized_with_timeout(DEFAULT_TIMEOUT)
        .await?;
    let cold = session_read(&mut replacement, &root_thread_id, &root_thread_id)
        .await?
        .session;
    assert_eq!(cold.identity.session_id, root_thread_id);
    assert_eq!(
        cold.identity.root_thread_id.as_deref(),
        Some(root_thread_id.as_str())
    );
    assert_eq!(cold.residency, DurableSessionResidency::NotObservedHere);
    assert_eq!(cold.read_status, DurableSessionReadStatus::Available);
    let cold_team = cold.team.expect("cold committed Team projection");
    assert_eq!(cold_team.team_instance_id, team_instance_id);
    assert_eq!(cold_team.commit_generation, initial_generation);
    assert_eq!(cold_team.commit_fingerprint, initial_fingerprint);
    assert_eq!(
        cold_team.events[0].versions[0].author_thread_id,
        child_thread_id
    );
    assert!(loaded_thread_ids(&mut replacement).await?.is_empty());
    assert_eq!(
        response_request_count(&model_server).await,
        requests_before_restart
    );

    let child_locator = session_read(&mut replacement, &root_thread_id, &child_thread_id)
        .await?
        .session;
    assert_eq!(
        child_locator.read_status,
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::NotCanonicalRoot,
        }
    );
    assert_eq!(child_locator.team, None);

    let resume_id = replacement
        .send_thread_resume_request(ThreadResumeParams {
            thread_id: root_thread_id.clone(),
            ..Default::default()
        })
        .await?;
    let ThreadResumeResponse {
        thread: resumed, ..
    } = timeout(DEFAULT_TIMEOUT, replacement.read_response(resume_id)).await??;
    assert_eq!(resumed.id, root_thread_id);
    assert_eq!(
        loaded_thread_ids(&mut replacement).await?,
        vec![root_thread_id.clone()]
    );
    assert_eq!(
        response_request_count(&model_server).await,
        requests_before_restart
    );

    let resumed_view = session_read(&mut replacement, &root_thread_id, &root_thread_id)
        .await?
        .session;
    let resumed_proof = resumed_view
        .control_precondition
        .expect("resumed canonical owner proof");
    let updated = session_control(
        &mut replacement,
        &root_thread_id,
        resumed_proof,
        DurableSessionControlOperation::SetRootState {
            version_id: version_id.clone(),
            expected_producer_state: DurableSessionTeamProducerState::Open,
            expected_root_state: initial_root_state,
            next_root_state: DurableSessionTeamRootState::Resolved,
        },
    )
    .await?;
    assert!(matches!(
        updated.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::RootStateUpdated { changed: true, .. }
        }
    ));
    let after_mutation = session_read(&mut replacement, &root_thread_id, &root_thread_id)
        .await?
        .session;
    let after_mutation_team = after_mutation
        .team
        .as_ref()
        .expect("updated Team projection");
    assert_eq!(after_mutation_team.team_instance_id, team_instance_id);
    assert!(after_mutation_team.commit_generation > initial_generation);
    assert_ne!(after_mutation_team.commit_fingerprint, initial_fingerprint);
    // `session/read` projects the active Team view. Resolving the restored version is terminal
    // root attention, so the successfully mutated event leaves this view while remaining in the
    // Team history. The fresh commit identity above proves that the restored version was accepted
    // by the canonical writer rather than replayed through the model.
    assert!(after_mutation_team.events.is_empty());
    assert_eq!(
        response_request_count(&model_server).await,
        requests_before_restart
    );

    let blocked_close = session_control(
        &mut replacement,
        &root_thread_id,
        after_mutation
            .control_precondition
            .expect("post-mutation owner proof"),
        DurableSessionControlOperation::Close,
    )
    .await?;
    assert!(matches!(
        blocked_close.outcome,
        DurableSessionControlOutcome::Rejected {
            reason: DurableSessionControlRejectionReason::ActiveWriter,
            ..
        }
    ));

    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| {
            String::from_utf8_lossy(&request.body).contains(CLOSE_CHILD_PROMPT)
        },
        responses::sse(vec![
            responses::ev_response_created("full-chain-close-child"),
            responses::ev_function_call_with_namespace(
                CLOSE_CALL_ID,
                NAMESPACE,
                "close_agent",
                &serde_json::to_string(&json!({"target": "durable_worker"}))
                    .expect("static close args"),
            ),
            responses::ev_completed("full-chain-close-child"),
        ]),
    )
    .await;
    responses::mount_sse_once_match(
        &model_server,
        |request: &wiremock::Request| {
            String::from_utf8_lossy(&request.body).contains(CLOSE_CALL_ID)
        },
        responses::sse(vec![
            responses::ev_response_created("full-chain-root-after-close"),
            responses::ev_assistant_message(
                "full-chain-root-after-close-message",
                "recovered durable worker closed",
            ),
            responses::ev_completed("full-chain-root-after-close"),
        ]),
    )
    .await;
    timeout(
        DEFAULT_TIMEOUT,
        replacement.start_turn_and_wait_for_completion(TurnStartParams {
            thread_id: root_thread_id.clone(),
            input: vec![UserInput::Text {
                text: CLOSE_CHILD_PROMPT.to_string(),
                text_elements: Vec::new(),
            }],
            ..Default::default()
        }),
    )
    .await??;
    let requests_after_explicit_close = response_request_count(&model_server).await;
    assert_eq!(requests_after_explicit_close, requests_before_restart + 2);

    let close_view = session_read(&mut replacement, &root_thread_id, &root_thread_id)
        .await?
        .session;
    let closed = session_control(
        &mut replacement,
        &root_thread_id,
        close_view.control_precondition.expect("close proof"),
        DurableSessionControlOperation::Close,
    )
    .await?;
    assert!(matches!(
        closed.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::OwnerClosed,
        }
    ));
    assert!(loaded_thread_ids(&mut replacement).await?.is_empty());

    let closed_view = session_read(&mut replacement, &root_thread_id, &root_thread_id)
        .await?
        .session;
    // OwnerClosed proves the canonical writer crossed its close barrier and was removed; the
    // public effect deliberately does not invent a whole-Session Closed fact.
    assert_eq!(
        closed_view.domain_lifecycle,
        DurableSessionDomainLifecycle::Unknown
    );
    let archived = session_control(
        &mut replacement,
        &root_thread_id,
        closed_view.control_precondition.expect("archive proof"),
        DurableSessionControlOperation::Archive,
    )
    .await?;
    assert!(matches!(
        archived.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::Archived { .. }
        }
    ));

    let archived_view = session_read(&mut replacement, &root_thread_id, &root_thread_id)
        .await?
        .session;
    assert_eq!(
        archived_view.storage_status,
        DurableSessionStorageStatus::Archived
    );
    let unarchived = session_control(
        &mut replacement,
        &root_thread_id,
        archived_view.control_precondition.expect("unarchive proof"),
        DurableSessionControlOperation::Unarchive,
    )
    .await?;
    assert!(matches!(
        unarchived.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::Unarchived,
        }
    ));

    let active_again = session_read(&mut replacement, &root_thread_id, &root_thread_id)
        .await?
        .session;
    assert_eq!(
        active_again.storage_status,
        DurableSessionStorageStatus::Active
    );
    let deleted = session_control(
        &mut replacement,
        &root_thread_id,
        active_again.control_precondition.expect("delete proof"),
        DurableSessionControlOperation::Delete,
    )
    .await?;
    assert!(matches!(
        deleted.outcome,
        DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::Deleted { .. }
        }
    ));
    let missing = session_read(&mut replacement, &root_thread_id, &root_thread_id)
        .await?
        .session;
    assert_eq!(
        missing.read_status,
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SessionNotFound,
        }
    );
    assert_eq!(
        response_request_count(&model_server).await,
        requests_after_explicit_close
    );

    let shutdown = timeout(DEFAULT_TIMEOUT, replacement.shutdown_gracefully()).await??;
    assert!(
        shutdown.success(),
        "replacement app-server shutdown failed: {shutdown}"
    );
    Ok(())
}

fn write_config(codex_home: &Path, model_server_uri: &str) -> std::io::Result<()> {
    MockResponsesConfig::new(model_server_uri)
        .with_model("gpt-5.4")
        .enable_feature(Feature::DurableSessionQuery)
        .enable_feature(Feature::DurableSessionControl)
        .with_extra_config(
            "[features.multi_agent_v2]\nenabled = true\nteam_state_enabled = true\ndurable_team_enabled = true",
        )
        .write(codex_home)
}

async fn session_read(
    app_server: &mut TestAppServer,
    session_id: &str,
    root_thread_id: &str,
) -> Result<DurableSessionReadResponse> {
    let request_id = app_server
        .send_durable_session_read_request(DurableSessionReadParams {
            session_id: session_id.to_string(),
            root_thread_id: root_thread_id.to_string(),
        })
        .await?;
    timeout(DEFAULT_TIMEOUT, app_server.read_response(request_id)).await?
}

async fn session_control(
    app_server: &mut TestAppServer,
    id: &str,
    precondition: codex_app_server_protocol::DurableSessionControlPrecondition,
    operation: DurableSessionControlOperation,
) -> Result<DurableSessionControlResponse> {
    app_server
        .request(|request_id| ClientRequest::DurableSessionControl {
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

async fn loaded_thread_ids(app_server: &mut TestAppServer) -> Result<Vec<String>> {
    let request_id = app_server
        .send_thread_loaded_list_request(ThreadLoadedListParams::default())
        .await?;
    let ThreadLoadedListResponse { data, .. } =
        timeout(DEFAULT_TIMEOUT, app_server.read_response(request_id)).await??;
    Ok(data)
}

async fn response_request_count(model_server: &wiremock::MockServer) -> usize {
    model_server
        .received_requests()
        .await
        .unwrap_or_default()
        .into_iter()
        .filter(|request| request.url.path().ends_with("/responses"))
        .count()
}
