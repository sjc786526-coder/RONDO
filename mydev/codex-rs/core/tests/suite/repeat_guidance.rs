#![allow(clippy::unwrap_used)]

use anyhow::Result;
use codex_core::StartThreadOptions;
use codex_features::Feature;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::SubAgentSource;
use core_test_support::responses;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_sequence;
use core_test_support::responses::sse;
use core_test_support::skip_if_no_network;
use core_test_support::test_codex::local;
use core_test_support::test_codex::test_codex;
use serde_json::Value;

const REPEAT_GUIDANCE_MARKER: &str = "Before repeating this tool from the same requester/tool path";

fn tool_description<'a>(body: &'a Value, name: &str) -> &'a str {
    body["tools"]
        .as_array()
        .expect("request should contain tools")
        .iter()
        .find(|tool| tool["name"].as_str() == Some(name))
        .and_then(|tool| tool["description"].as_str())
        .unwrap_or_else(|| panic!("request should contain a description for {name}"))
}

async fn request_body(
    repeat_guidance_enabled: bool,
    code_mode_only: bool,
    non_root_agent: bool,
) -> Result<Value> {
    let server = responses::start_mock_server().await;
    let completed_response = |response_id: &str, message_id: &str| {
        sse(vec![
            ev_response_created(response_id),
            ev_assistant_message(message_id, "done"),
            ev_completed(response_id),
        ])
    };
    let response = if non_root_agent {
        mount_sse_sequence(
            &server,
            vec![
                completed_response("resp-parent", "msg-parent"),
                completed_response("resp-child", "msg-child"),
            ],
        )
        .await
    } else {
        responses::mount_sse_once(&server, completed_response("resp-root", "msg-root")).await
    };
    let mut builder = test_codex()
        .with_model("test-gpt-5.1-codex")
        .with_config(move |config| {
            config
                .features
                .enable(Feature::UnifiedExec)
                .expect("unified exec feature should be available");
            if repeat_guidance_enabled {
                config
                    .features
                    .enable(Feature::ExecCommandRepeatGuidance)
                    .expect("repeat guidance feature should be available");
            } else {
                config
                    .features
                    .disable(Feature::ExecCommandRepeatGuidance)
                    .expect("repeat guidance feature should be available");
            }
            if code_mode_only {
                config
                    .features
                    .enable(Feature::CodeModeOnly)
                    .expect("code mode only feature should be available");
            }
        });
    let base_test = builder.build(&server).await?;
    let mut test = base_test;
    if non_root_agent {
        test.submit_turn_with_environments(
            "initialize the parent thread",
            Some(vec![local(test.config.cwd.clone())]),
        )
        .await?;
        let session_source = SessionSource::SubAgent(SubAgentSource::ThreadSpawn {
            parent_thread_id: test.session_configured.thread_id,
            depth: 1,
            agent_path: None,
            agent_nickname: None,
            agent_role: None,
        });
        let new_thread = test
            .thread_manager
            .start_thread(StartThreadOptions {
                session_source: Some(session_source),
                ..StartThreadOptions::new(test.config.clone())
            })
            .await?;
        test.codex = new_thread.thread;
        test.session_configured = new_thread.session_configured;
    }

    test.submit_turn_with_environments(
        "report the available command tools",
        Some(vec![local(test.config.cwd.clone())]),
    )
    .await?;
    let requests = response.requests();
    let expected_count = if non_root_agent { 2 } else { 1 };
    assert_eq!(requests.len(), expected_count);
    Ok(requests
        .last()
        .expect("request sequence should not be empty")
        .body_json())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn repeat_guidance_is_model_visible_only_to_enabled_root_agents() -> Result<()> {
    skip_if_no_network!(Ok(()));

    let root_disabled = request_body(
        /*repeat_guidance_enabled*/ false, /*code_mode_only*/ false,
        /*non_root_agent*/ false,
    )
    .await?;
    assert!(!tool_description(&root_disabled, "exec_command").contains(REPEAT_GUIDANCE_MARKER));

    let root_enabled = request_body(
        /*repeat_guidance_enabled*/ true, /*code_mode_only*/ false,
        /*non_root_agent*/ false,
    )
    .await?;
    assert!(tool_description(&root_enabled, "exec_command").contains(REPEAT_GUIDANCE_MARKER));

    let spawned_enabled = request_body(
        /*repeat_guidance_enabled*/ true, /*code_mode_only*/ false,
        /*non_root_agent*/ true,
    )
    .await?;
    assert!(!tool_description(&spawned_enabled, "exec_command").contains(REPEAT_GUIDANCE_MARKER));

    let code_mode_root = request_body(
        /*repeat_guidance_enabled*/ true, /*code_mode_only*/ true,
        /*non_root_agent*/ false,
    )
    .await?;
    assert!(tool_description(&code_mode_root, "exec").contains(REPEAT_GUIDANCE_MARKER));

    let code_mode_spawned = request_body(
        /*repeat_guidance_enabled*/ true, /*code_mode_only*/ true,
        /*non_root_agent*/ true,
    )
    .await?;
    assert!(!tool_description(&code_mode_spawned, "exec").contains(REPEAT_GUIDANCE_MARKER));

    Ok(())
}
