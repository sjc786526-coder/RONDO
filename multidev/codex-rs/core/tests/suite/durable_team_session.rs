//! Product-level cold-resume coverage for durable Team Session activation.

use anyhow::Result;
use codex_features::Feature;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::user_input::UserInput;
use codex_team_state::TEAM_WORLD_STATE_OPEN_TAG;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call_with_namespace;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_sequence_without_request_count_expectation;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::TestCodexBuilder;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;

const NAMESPACE: &str = "collaboration";
const IMMEDIATE_CRASH_PROCESS_TEST: &str =
    "suite::durable_team_session::durable_team_immediate_crash_is_cold_resumable";
const IMMEDIATE_CRASH_MODE: &str = "CODEX_DURABLE_TEAM_IMMEDIATE_CRASH_MODE";
const IMMEDIATE_CRASH_HOME: &str = "CODEX_DURABLE_TEAM_IMMEDIATE_CRASH_HOME";
const IMMEDIATE_CRASH_THREAD_PREFIX: &str = "DURABLE_TEAM_THREAD=";

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_team_immediate_crash_is_cold_resumable() -> Result<()> {
    if std::env::var_os(IMMEDIATE_CRASH_MODE).is_some() {
        let home = PathBuf::from(
            std::env::var_os(IMMEDIATE_CRASH_HOME)
                .expect("immediate-crash child has a shared home"),
        );
        let server = start_mock_server().await;
        let mut builder = durable_team_codex_at(home);
        let created = builder.build(&server).await?;
        let rollout_path = created
            .session_configured
            .rollout_path
            .as_ref()
            .expect("durable Session exposes its canonical rollout");
        assert!(rollout_path.is_file());
        println!(
            "{IMMEDIATE_CRASH_THREAD_PREFIX}{}",
            created.session_configured.thread_id
        );
        std::io::stdout().flush()?;
        // Bypass every destructor and graceful shutdown path. The parent must locate and resume
        // only what Session activation made durable before returning success.
        std::process::exit(0);
    }

    let home = tempfile::TempDir::new()?;
    let output = Command::new(std::env::current_exe()?)
        .arg("--exact")
        .arg(IMMEDIATE_CRASH_PROCESS_TEST)
        .arg("--nocapture")
        .env(IMMEDIATE_CRASH_MODE, "1")
        .env(IMMEDIATE_CRASH_HOME, home.path())
        .output()?;
    assert!(
        output.status.success(),
        "immediate-crash child failed: status={:?}\nstdout={}\nstderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr),
    );
    let child_stdout = String::from_utf8(output.stdout)?;
    let thread_id = child_stdout
        .lines()
        .find_map(|line| line.strip_prefix(IMMEDIATE_CRASH_THREAD_PREFIX))
        .ok_or_else(|| anyhow::anyhow!("child did not report its durable Root: {child_stdout}"))?;
    let rollout_path = codex_rollout::find_thread_path_by_id_str(home.path(), thread_id, None)
        .await?
        .ok_or_else(|| anyhow::anyhow!("cannot locate immediately-crashed Root {thread_id}"))?;

    let server = start_mock_server().await;
    let responses = mount_sse_sequence_without_request_count_expectation(
        &server,
        vec![
            publish_call("publish-after-immediate-crash", "after immediate crash"),
            assistant_reply("after-immediate-crash-complete"),
        ],
    )
    .await;
    let mut builder = durable_team_codex_at(home.path().to_path_buf());
    let resumed = builder
        .resume(&server, Arc::new(tempfile::TempDir::new()?), rollout_path)
        .await?;
    submit_turn(&resumed, "continue after the immediate process exit").await?;
    let requests = responses.requests();
    assert_eq!(requests.len(), 2);
    assert!(projection(&requests[1].body_json()).contains("after immediate crash"));
    resumed.codex.shutdown_and_wait().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_team_cold_resume_preserves_identity_and_continues_mutation() -> Result<()> {
    let server = start_mock_server().await;
    let responses = mount_sse_sequence_without_request_count_expectation(
        &server,
        vec![
            publish_call("publish-before-resume", "before resume"),
            assistant_reply("first-complete"),
            publish_call("publish-after-resume", "after resume"),
            assistant_reply("second-complete"),
        ],
    )
    .await;
    let mut builder = durable_team_codex();
    let first = builder.build(&server).await?;
    let session_id = first.session_configured.session_id;
    let thread_id = first.session_configured.thread_id;
    let home = Arc::clone(&first.home);
    let rollout_path = first
        .session_configured
        .rollout_path
        .clone()
        .expect("durable Session materializes its canonical rollout before startup succeeds");
    assert!(rollout_path.is_file());
    let team_directory = home.path().join("team-sessions/v1");
    assert!(
        team_directory
            .join(format!("{thread_id}.team-lineage"))
            .is_file()
    );
    assert!(
        team_directory
            .join(format!("{thread_id}.team-state"))
            .is_file()
    );

    submit_turn(&first, "publish before the process-style restart").await?;
    let initial_requests = responses.requests();
    assert_eq!(initial_requests.len(), 2);
    let first_body = initial_requests[1].body_json();
    let first_projection = projection(&first_body);
    let team_instance = projection_field(first_projection, "team_instance")?;
    assert!(first_projection.contains("before resume"));

    first.codex.shutdown_and_wait().await?;
    let mut disabled_builder = test_codex()
        .with_model("gpt-5.6-sol")
        .with_config(enable_non_durable_team);
    let disabled_error = match disabled_builder
        .resume(&server, Arc::clone(&home), rollout_path.clone())
        .await
    {
        Ok(_) => anyhow::bail!("durable marker must not resume with durability disabled"),
        Err(error) => error,
    };
    assert!(
        format!("{disabled_error:#}").contains("writable resume requires durable_team_enabled")
    );

    builder = builder
        .with_model("gpt-5.6-sol")
        .with_config(enable_durable_team);
    let resumed = builder.resume(&server, home, rollout_path).await?;
    assert_eq!(resumed.session_configured.session_id, session_id);
    assert_eq!(resumed.session_configured.thread_id, thread_id);
    submit_turn(&resumed, "continue the same Team after restart").await?;

    let all_requests = responses.requests();
    assert_eq!(all_requests.len(), 4);
    let resumed_body = all_requests[2].body_json();
    let resumed_projection = projection(&resumed_body);
    assert_eq!(
        projection_field(resumed_projection, "team_instance")?,
        team_instance
    );
    assert!(resumed_projection.contains("before resume"));
    let continued_body = all_requests[3].body_json();
    let continued_projection = projection(&continued_body);
    assert_eq!(
        projection_field(continued_projection, "team_instance")?,
        team_instance
    );
    assert!(continued_projection.contains("before resume"));
    assert!(continued_projection.contains("after resume"));

    resumed.codex.shutdown_and_wait().await?;
    Ok(())
}

fn durable_team_codex() -> TestCodexBuilder {
    test_codex()
        .with_model("gpt-5.6-sol")
        .with_config(enable_durable_team)
}

fn durable_team_codex_at(home: PathBuf) -> TestCodexBuilder {
    durable_team_codex().with_config(move |config| {
        config.codex_home = home
            .try_into()
            .expect("shared durable Team test home is absolute");
    })
}

fn enable_durable_team(config: &mut codex_core::config::Config) {
    enable_non_durable_team(config);
    config.multi_agent_v2.durable_team_enabled = true;
}

fn enable_non_durable_team(config: &mut codex_core::config::Config) {
    config
        .features
        .enable(Feature::Collab)
        .expect("test config allows collaboration");
    config
        .features
        .enable(Feature::MultiAgentV2)
        .expect("test config allows Multi-Agent V2");
    config.multi_agent_v2.team_state_enabled = true;
}

async fn submit_turn(test: &TestCodex, prompt: &str) -> Result<()> {
    let submission_id = test
        .codex
        .submit(Op::UserInput {
            items: vec![UserInput::Text {
                text: prompt.to_string(),
                text_elements: Vec::new(),
            }],
            final_output_json_schema: None,
            responsesapi_client_metadata: None,
            additional_context: Default::default(),
            thread_settings: ThreadSettingsOverrides::default(),
        })
        .await?;
    let mut observed = Vec::new();
    let terminal = tokio::time::timeout(std::time::Duration::from_secs(10), async {
        loop {
            let event = test.codex.next_event().await?;
            let is_submission = event.id == submission_id;
            match event.msg {
                EventMsg::TurnComplete(_) if is_submission => return Ok(()),
                EventMsg::Error(error) if is_submission => {
                    anyhow::bail!("durable Team turn failed: {}", error.message)
                }
                message => observed.push(format!("{}: {message:?}", event.id)),
            }
        }
    })
    .await;
    terminal.map_err(|_| {
        anyhow::anyhow!(
            "durable Team turn {submission_id} timed out; prior events: {}",
            observed.join(" | ")
        )
    })?
}

fn publish_call(response_id: &str, title: &str) -> String {
    sse(vec![
        ev_response_created(response_id),
        ev_function_call_with_namespace(
            response_id,
            NAMESPACE,
            "team_publish",
            &serde_json::to_string(&json!({
                "title": title,
                "summary": format!("durably committed {title}"),
            }))
            .expect("serialize publish request"),
        ),
        ev_completed(response_id),
    ])
}

fn assistant_reply(response_id: &str) -> String {
    sse(vec![
        ev_response_created(response_id),
        ev_assistant_message(response_id, "done"),
        ev_completed(response_id),
    ])
}

fn projection(body: &Value) -> &str {
    body.get("input")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| item.get("content").and_then(Value::as_array))
        .flatten()
        .filter_map(|content| content.get("text").and_then(Value::as_str))
        .find(|text| text.contains(TEAM_WORLD_STATE_OPEN_TAG))
        .expect("request carries the durable Team projection")
}

fn projection_field<'a>(projection: &'a str, name: &str) -> Result<&'a str> {
    projection
        .split_whitespace()
        .find_map(|token| token.strip_prefix(&format!("{name}=")))
        .ok_or_else(|| anyhow::anyhow!("projection lacks {name}: {projection}"))
}
