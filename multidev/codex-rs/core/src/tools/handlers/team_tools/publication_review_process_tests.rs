use super::TurnPublicationReviews;
use crate::StartThreadOptions;
use crate::ThreadManager;
use crate::config::PublicationCriticConfig;
use crate::session::step_context::StepContext;
use crate::session::tests::make_session_and_context;
use crate::session::turn_context::TurnContext;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolOutput;
use crate::tools::context::ToolPayload;
use crate::tools::handlers::team_tools::TeamPublishHandler;
use crate::tools::registry::ToolExecutor;
use crate::turn_diff_tracker::TurnDiffTracker;
use codex_features::Feature;
use codex_login::CodexAuth;
use codex_model_provider_info::built_in_model_providers;
use codex_protocol::ThreadId;
use codex_protocol::models::FunctionCallOutputBody;
use codex_protocol::models::ResponseInputItem;
use codex_publication_critic::ClientConfig;
use codex_publication_critic::PublicationCriticClient;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::ServiceDescriptor;
use codex_publication_critic::StartupAnnouncement;
use codex_publication_critic::controlled_test_descriptor;
use codex_team_state::HistoryQuery;
use codex_team_state::TeamRevision;
use codex_team_state::TeamStateHandle;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::path::PathBuf;
use std::process::ExitStatus;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex as StdMutex;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::Command;
use tokio::sync::Mutex;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

type TestResult<T = ()> = Result<T, Box<dyn std::error::Error + Send + Sync>>;

const PROCESS_DEADLINE: Duration = Duration::from_secs(10);
const CALL_TIMEOUT: Duration = Duration::from_secs(3);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(3);
const CANDIDATE_SENTINEL: &str = "candidate-body-sentinel-057";
const SERVICE_BIN_ENV: &str = "RONDO_PUBLICATION_CRITIC_SERVICE_BIN";

fn thread_manager() -> ThreadManager {
    ThreadManager::with_models_provider_for_tests(
        CodexAuth::from_api_key("dummy"),
        built_in_model_providers(/*openai_base_url*/ None)["openai"].clone(),
    )
}

fn invocation(
    session: Arc<crate::session::session::Session>,
    turn: Arc<TurnContext>,
    call_id: &str,
    args: Value,
    cancellation_token: CancellationToken,
) -> ToolInvocation {
    ToolInvocation {
        session,
        step_context: StepContext::for_test(Arc::clone(&turn)),
        turn,
        cancellation_token,
        tracker: Arc::new(Mutex::new(TurnDiffTracker::default())),
        call_id: call_id.to_string(),
        output_item_id: None,
        tool_name: codex_tools::ToolName::plain("team_publish"),
        source: ToolCallSource::Direct,
        payload: ToolPayload::Function {
            arguments: args.to_string(),
        },
    }
}

fn output_json(output: &dyn ToolOutput) -> Value {
    let response = output.to_response_item(
        "output",
        &ToolPayload::Function {
            arguments: "{}".to_string(),
        },
    );
    let ResponseInputItem::FunctionCallOutput { output, .. } = response else {
        panic!("expected function output");
    };
    let FunctionCallOutputBody::Text(text) = output.body else {
        panic!("expected text output");
    };
    serde_json::from_str(&text).expect("team_publish output is JSON")
}

fn assert_body_free_observation(output: &dyn ToolOutput) {
    assert!(!output.log_preview().contains(CANDIDATE_SENTINEL));
    let response = output
        .post_tool_use_response(
            "output",
            &ToolPayload::Function {
                arguments: "{}".to_string(),
            },
        )
        .expect("reviewed output has an explicit body-free hook response");
    assert!(!response.to_string().contains(CANDIDATE_SENTINEL));
}

struct TeamHarness {
    _manager: ThreadManager,
    session: Arc<crate::session::session::Session>,
    turn: Arc<TurnContext>,
    team: Arc<TeamStateHandle>,
    root: ThreadId,
}

impl TeamHarness {
    async fn new(publication_critic: Option<PublicationCriticConfig>) -> Self {
        let (mut session, mut turn) = make_session_and_context().await;
        let manager = thread_manager();
        let mut config = turn.config.as_ref().clone();
        config
            .features
            .enable(Feature::Collab)
            .expect("test config allows feature updates");
        config
            .features
            .enable(Feature::MultiAgentV2)
            .expect("test config allows feature updates");
        config.multi_agent_v2.team_state_enabled = true;
        config.multi_agent_v2.publication_critic = publication_critic;
        turn.multi_agent_version = config.multi_agent_version_from_features();
        turn.config = Arc::new(config);
        let root_thread = manager
            .start_thread(StartThreadOptions::new((*turn.config).clone()))
            .await
            .expect("root thread should start");
        root_thread.thread.session.new_default_turn().await;
        session.services.agent_control = manager.agent_control();
        session.thread_id = root_thread.thread_id;
        session
            .services
            .agent_control
            .register_team_participant(session.thread_id, &turn.session_source);

        let team = Arc::clone(session.services.agent_control.team());
        let root = session.thread_id;
        Self {
            _manager: manager,
            session: Arc::new(session),
            turn: Arc::new(turn),
            team,
            root,
        }
    }

    async fn publish(
        &self,
        call_id: &str,
        args: Value,
    ) -> Result<Box<dyn ToolOutput>, crate::function_tool::FunctionCallError> {
        TeamPublishHandler::new(self.turn.config.multi_agent_v2.publication_critic.clone())
            .handle(invocation(
                Arc::clone(&self.session),
                Arc::clone(&self.turn),
                call_id,
                args,
                CancellationToken::new(),
            ))
            .await
    }
}

struct CapturedProcess {
    status: ExitStatus,
    stdout: String,
    stderr: String,
}

struct ServiceProcess {
    child: Child,
    stdin: Option<ChildStdin>,
    endpoint: std::net::SocketAddr,
    expected: ServiceDescriptor,
    stdout: Arc<StdMutex<Vec<String>>>,
    stderr: Arc<StdMutex<Vec<String>>>,
    stderr_lines: mpsc::UnboundedReceiver<String>,
    stdout_task: JoinHandle<()>,
    stderr_task: JoinHandle<()>,
}

impl ServiceProcess {
    async fn spawn(behavior: &str, score: f64, affected_calls: usize) -> TestResult<Self> {
        let expected = controlled_test_descriptor(RuntimeLimits::production());
        let mut command = Command::new(service_binary()?);
        command
            .arg("--behavior")
            .arg(behavior)
            .arg("--score")
            .arg(score.to_string())
            .arg("--affected-calls")
            .arg(affected_calls.to_string())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let mut child = command.spawn()?;
        let stdin = child.stdin.take().ok_or("service stdin was not piped")?;
        let stdout = child.stdout.take().ok_or("service stdout was not piped")?;
        let stderr = child.stderr.take().ok_or("service stderr was not piped")?;

        let mut stdout_reader = BufReader::new(stdout);
        let mut startup_line = String::new();
        let bytes_read = timeout(PROCESS_DEADLINE, stdout_reader.read_line(&mut startup_line))
            .await
            .map_err(|_| "timed out waiting for service startup announcement")??;
        if bytes_read == 0 {
            return Err("service exited before startup announcement".into());
        }
        let announcement: StartupAnnouncement = serde_json::from_str(startup_line.trim_end())?;
        assert!(announcement.endpoint.ip().is_loopback());
        assert_ne!(announcement.endpoint.port(), 0);
        assert_eq!(announcement.descriptor, expected);

        let stdout_capture = Arc::new(StdMutex::new(vec![startup_line.trim_end().to_string()]));
        let stdout_for_task = Arc::clone(&stdout_capture);
        let stdout_task = tokio::spawn(async move {
            let mut remainder = String::new();
            let _ = stdout_reader.read_to_string(&mut remainder).await;
            if !remainder.is_empty() {
                stdout_for_task.lock().unwrap().push(remainder);
            }
        });

        let stderr_capture = Arc::new(StdMutex::new(Vec::new()));
        let stderr_for_task = Arc::clone(&stderr_capture);
        let (stderr_tx, stderr_lines) = mpsc::unbounded_channel();
        let stderr_task = tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                stderr_for_task.lock().unwrap().push(line.clone());
                let _ = stderr_tx.send(line);
            }
        });

        let mut process = Self {
            child,
            stdin: Some(stdin),
            endpoint: announcement.endpoint,
            expected,
            stdout: stdout_capture,
            stderr: stderr_capture,
            stderr_lines,
            stdout_task,
            stderr_task,
        };
        process
            .wait_for_stderr("publication_critic_service_listening")
            .await?;
        Ok(process)
    }

    fn config(&self) -> PublicationCriticConfig {
        PublicationCriticConfig::new(
            self.endpoint,
            self.expected.clone(),
            CALL_TIMEOUT,
            STARTUP_TIMEOUT,
        )
        .expect("controlled service configuration is valid")
    }

    fn client(&self) -> PublicationCriticClient {
        PublicationCriticClient::new(
            ClientConfig::new(
                self.endpoint,
                self.expected.clone(),
                CALL_TIMEOUT,
                STARTUP_TIMEOUT,
            )
            .expect("controlled client configuration is valid"),
        )
        .expect("controlled client should initialize")
    }

    async fn send_command(&mut self, command: &str) -> TestResult {
        let stdin = self.stdin.as_mut().ok_or("service stdin is closed")?;
        stdin.write_all(command.as_bytes()).await?;
        stdin.write_all(b"\n").await?;
        stdin.flush().await?;
        Ok(())
    }

    async fn wait_for_stderr(&mut self, expected: &str) -> TestResult {
        timeout(PROCESS_DEADLINE, async {
            while let Some(line) = self.stderr_lines.recv().await {
                if line.contains(expected) {
                    return Ok(());
                }
            }
            Err("service stderr closed before expected barrier".into())
        })
        .await
        .map_err(|_| "timed out waiting for service stderr barrier")?
    }

    async fn shutdown_and_finish(mut self) -> TestResult<CapturedProcess> {
        self.client().shutdown().await?;
        drop(self.stdin.take());
        let status = timeout(PROCESS_DEADLINE, self.child.wait())
            .await
            .map_err(|_| "timed out waiting for service process exit")??;
        timeout(PROCESS_DEADLINE, self.stdout_task)
            .await
            .map_err(|_| "timed out draining service stdout")??;
        timeout(PROCESS_DEADLINE, self.stderr_task)
            .await
            .map_err(|_| "timed out draining service stderr")??;
        let stdout = self.stdout.lock().unwrap().join("\n");
        let stderr = self.stderr.lock().unwrap().join("\n");
        Ok(CapturedProcess {
            status,
            stdout,
            stderr,
        })
    }
}

fn service_binary() -> TestResult<PathBuf> {
    if let Some(configured) = std::env::var_os(SERVICE_BIN_ENV) {
        let path = PathBuf::from(configured);
        if !path.is_absolute() || !path.is_file() {
            return Err(
                format!("{SERVICE_BIN_ENV} must be an absolute service binary path").into(),
            );
        }
        return Ok(path);
    }

    // Cargo callers must opt into the exact binary they just built so a stale target artifact
    // cannot masquerade as product-process evidence. Bazel explicitly supplies this sibling
    // binary through runfiles, where the shared resolver is the authoritative location.
    if codex_utils_cargo_bin::runfiles_available() {
        return codex_utils_cargo_bin::cargo_bin("codex-publication-critic-service")
            .map_err(Into::into);
    }
    Err(format!("{SERVICE_BIN_ENV} must name the freshly built service binary").into())
}

fn assert_clean_process(captured: &CapturedProcess) {
    assert!(
        captured.status.success(),
        "service stderr: {}",
        captured.stderr
    );
    assert!(!captured.stdout.contains(CANDIDATE_SENTINEL));
    assert!(!captured.stderr.contains(CANDIDATE_SENTINEL));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn off_path_keeps_original_contract_and_makes_zero_service_calls() -> TestResult {
    let service = ServiceProcess::spawn("block-first", 0.75, 8).await?;
    let harness = TeamHarness::new(None).await;
    let handler = TeamPublishHandler::off();
    assert!(!crate::tools::registry::CoreToolRuntime::waits_for_runtime_cancellation(&handler));
    assert!(!crate::tools::registry::CoreToolRuntime::redacts_tool_bodies(&handler));
    let output = harness
        .publish(
            "off-call",
            json!({
                "title": "off title",
                "summary": CANDIDATE_SENTINEL,
                "request_id": "off-request"
            }),
        )
        .await?;
    let value = output_json(output.as_ref());
    assert_eq!(value.as_object().unwrap().len(), 7);
    assert_eq!(harness.team.revision(), TeamRevision::from_raw(1));
    assert!(
        harness
            .turn
            .extension_data
            .get::<TurnPublicationReviews>()
            .is_none()
    );

    let captured = service.shutdown_and_finish().await?;
    assert_clean_process(&captured);
    assert!(!captured.stderr.contains("controlled_scorer_entered"));
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn pass_commits_canonical_candidate_and_committed_replay_skips_review() -> TestResult {
    let mut service = ServiceProcess::spawn("block-first", 0.75, 8).await?;
    service.send_command("release").await?;
    let harness = TeamHarness::new(Some(service.config())).await;
    let args = json!({
        "title": "pass title",
        "summary": CANDIDATE_SENTINEL,
        "handoff": "next owner",
        "request_id": "pass-request"
    });
    let output = harness.publish("pass-call", args.clone()).await?;
    assert_body_free_observation(output.as_ref());
    let value = output_json(output.as_ref());
    assert_eq!(value["publication_review"]["status"], "pass");
    assert_eq!(value["deduplicated"], false);
    let event_id = value["event_id"].as_str().unwrap().parse()?;
    let history = harness
        .team
        .history(
            harness.root,
            &HistoryQuery {
                event_id: Some(event_id),
                limit: Some(1),
                before: None,
            },
        )
        .map_err(|error| error.to_string())?;
    assert_eq!(
        history.events[0].event.versions[0].summary,
        CANDIDATE_SENTINEL
    );

    let replay = harness.publish("pass-replay-call", args).await?;
    let replay = output_json(replay.as_ref());
    assert_eq!(replay["publication_review"]["status"], "committed_replay");
    assert_eq!(replay["deduplicated"], true);
    assert_eq!(harness.team.revision(), TeamRevision::from_raw(1));

    let captured = service.shutdown_and_finish().await?;
    assert_clean_process(&captured);
    assert_eq!(
        captured.stderr.matches("controlled_scorer_entered").count(),
        1
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_exact_publish_reviews_and_commits_only_once() -> TestResult {
    let mut service = ServiceProcess::spawn("block-first", 0.75, 8).await?;
    let config = service.config();
    let harness = TeamHarness::new(Some(config.clone())).await;
    let args = json!({
        "title": "concurrent title",
        "summary": CANDIDATE_SENTINEL,
        "request_id": "concurrent-request"
    });
    let first_invocation = invocation(
        Arc::clone(&harness.session),
        Arc::clone(&harness.turn),
        "concurrent-call-1",
        args.clone(),
        CancellationToken::new(),
    );
    let first_config = config.clone();
    let first = tokio::spawn(async move {
        TeamPublishHandler::new(Some(first_config))
            .handle(first_invocation)
            .await
    });
    service
        .wait_for_stderr("controlled_scorer_entered call=1")
        .await?;

    let second_invocation = invocation(
        Arc::clone(&harness.session),
        Arc::clone(&harness.turn),
        "concurrent-call-2",
        args,
        CancellationToken::new(),
    );
    let second = tokio::spawn(async move {
        TeamPublishHandler::new(Some(config))
            .handle(second_invocation)
            .await
    });
    service.send_command("release").await?;

    let first = timeout(PROCESS_DEADLINE, first)
        .await
        .map_err(|_| "timed out waiting for first concurrent publish")???;
    let second = timeout(PROCESS_DEADLINE, second)
        .await
        .map_err(|_| "timed out waiting for second concurrent publish")???;
    let mut statuses = [
        output_json(first.as_ref())["publication_review"]["status"]
            .as_str()
            .unwrap()
            .to_string(),
        output_json(second.as_ref())["publication_review"]["status"]
            .as_str()
            .unwrap()
            .to_string(),
    ];
    statuses.sort();
    assert_eq!(statuses, ["committed_replay", "pass"]);
    assert_eq!(harness.team.revision(), TeamRevision::from_raw(1));
    let history = harness
        .team
        .history(harness.root, &HistoryQuery::default())
        .map_err(|error| error.to_string())?;
    assert_eq!(history.events.len(), 1);
    assert_eq!(history.events[0].event.versions.len(), 1);

    let captured = service.shutdown_and_finish().await?;
    assert_clean_process(&captured);
    assert_eq!(
        captured.stderr.matches("controlled_scorer_entered").count(),
        1
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn full_rewrite_cycle_replays_exact_attempt_and_commits_third_candidate() -> TestResult {
    let mut service = ServiceProcess::spawn("block-first", 0.25, 8).await?;
    service.send_command("release").await?;
    let harness = TeamHarness::new(Some(service.config())).await;
    let first_args = json!({
        "title": "rewrite title",
        "summary": CANDIDATE_SENTINEL,
        "request_id": "rewrite-attempt-1"
    });
    let first = harness
        .publish("rewrite-call-1", first_args.clone())
        .await?;
    assert_body_free_observation(first.as_ref());
    let first = output_json(first.as_ref());
    assert_eq!(first["status"], "rewrite_required");
    assert_eq!(first["feedback_version"], "v1");
    assert_eq!(first["candidate"]["summary"], CANDIDATE_SENTINEL);
    assert_eq!(harness.team.revision(), TeamRevision::INITIAL);
    let cycle = first["review_cycle_id"].as_str().unwrap().to_string();

    let replay = harness.publish("rewrite-replay", first_args).await?;
    assert_eq!(output_json(replay.as_ref()), first);
    let conflict_result = harness
        .publish(
            "rewrite-conflict",
            json!({
                "title": "rewrite title",
                "summary": "different raw content",
                "request_id": "rewrite-attempt-1"
            }),
        )
        .await;
    let conflict = match conflict_result {
        Ok(_) => return Err("same attempt identity with different raw content must fail".into()),
        Err(error) => error,
    };
    assert!(conflict.to_string().contains("retry identity"));

    let second = harness
        .publish(
            "rewrite-call-2",
            json!({
                "title": "rewritten title",
                "summary": "focused revision one",
                "request_id": "rewrite-attempt-2",
                "review_cycle_id": cycle
            }),
        )
        .await?;
    let second = output_json(second.as_ref());
    assert_eq!(second["feedback_version"], "v2");
    assert_eq!(second["blocking_rewrite_count"], 2);
    assert_eq!(harness.team.revision(), TeamRevision::INITIAL);
    let cycle = second["review_cycle_id"].as_str().unwrap().to_string();

    let third = harness
        .publish(
            "rewrite-call-3",
            json!({
                "title": "final rewritten title",
                "summary": "focused revision two",
                "request_id": "rewrite-attempt-3",
                "review_cycle_id": cycle
            }),
        )
        .await?;
    let third = output_json(third.as_ref());
    assert_eq!(third["publication_review"]["status"], "rewrite_exhausted");
    assert_eq!(third["publication_review"]["review_attempt"], 3);
    assert_eq!(third["publication_review"]["blocking_rewrite_count"], 2);
    assert_eq!(harness.team.revision(), TeamRevision::from_raw(1));

    let captured = service.shutdown_and_finish().await?;
    assert_clean_process(&captured);
    assert_eq!(
        captured.stderr.matches("controlled_scorer_entered").count(),
        3
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn typed_backend_failure_falls_back_to_one_store_commit() -> TestResult {
    let service = ServiceProcess::spawn("backend-failure-first", 0.75, 1).await?;
    let harness = TeamHarness::new(Some(service.config())).await;
    let output = harness
        .publish(
            "fallback-call",
            json!({
                "title": "fallback title",
                "summary": CANDIDATE_SENTINEL,
                "request_id": "fallback-request"
            }),
        )
        .await?;
    assert_body_free_observation(output.as_ref());
    let value = output_json(output.as_ref());
    assert_eq!(value["publication_review"]["status"], "failure_fallback");
    assert_eq!(value["publication_review"]["failure_kind"], "backend");
    assert_eq!(value["publication_review"]["blocking_rewrite_count"], 0);
    assert_eq!(harness.team.revision(), TeamRevision::from_raw(1));

    let captured = service.shutdown_and_finish().await?;
    assert_clean_process(&captured);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn failure_after_rewrite_preserves_blocking_count_and_ends_cycle() -> TestResult {
    let service = ServiceProcess::spawn("fixed", 0.25, 8).await?;
    let harness = TeamHarness::new(Some(service.config())).await;
    let first = harness
        .publish(
            "rewrite-before-failure",
            json!({
                "title": "rewrite then failure",
                "summary": CANDIDATE_SENTINEL,
                "request_id": "rewrite-before-failure-1"
            }),
        )
        .await?;
    let first = output_json(first.as_ref());
    assert_eq!(first["status"], "rewrite_required");
    assert_eq!(first["blocking_rewrite_count"], 1);
    assert_eq!(harness.team.revision(), TeamRevision::INITIAL);
    let cycle = first["review_cycle_id"].as_str().unwrap().to_string();

    let captured = service.shutdown_and_finish().await?;
    assert_clean_process(&captured);

    let fallback = harness
        .publish(
            "failure-after-rewrite",
            json!({
                "title": "rewrite then failure",
                "summary": "focused correction",
                "request_id": "rewrite-before-failure-2",
                "review_cycle_id": cycle
            }),
        )
        .await?;
    let fallback = output_json(fallback.as_ref());
    assert_eq!(fallback["publication_review"]["status"], "failure_fallback");
    assert_eq!(
        fallback["publication_review"]["failure_kind"],
        "startup_timeout"
    );
    assert_eq!(fallback["publication_review"]["blocking_rewrite_count"], 1);
    assert_eq!(harness.team.revision(), TeamRevision::from_raw(1));
    let reviews = harness
        .turn
        .extension_data
        .get::<TurnPublicationReviews>()
        .expect("enabled path creates turn-scoped review state");
    assert!(reviews.state.lock().await.active.is_none());
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn cancellation_while_scorer_blocks_never_falls_back_or_commits() -> TestResult {
    let mut service = ServiceProcess::spawn("block-first", 0.75, 1).await?;
    let config = service.config();
    let harness = TeamHarness::new(Some(config.clone())).await;
    let cancellation = CancellationToken::new();
    let invocation = invocation(
        Arc::clone(&harness.session),
        Arc::clone(&harness.turn),
        "cancel-call",
        json!({
            "title": "cancel title",
            "summary": CANDIDATE_SENTINEL,
            "request_id": "cancel-request"
        }),
        cancellation.clone(),
    );
    let task = tokio::spawn(async move {
        TeamPublishHandler::new(Some(config))
            .handle(invocation)
            .await
    });
    service
        .wait_for_stderr("controlled_scorer_entered call=1")
        .await?;
    cancellation.cancel();
    let result = timeout(PROCESS_DEADLINE, task)
        .await
        .map_err(|_| "timed out waiting for cancelled team_publish")??;
    let error = match result {
        Ok(_) => return Err("cancelled review must not produce a publish output".into()),
        Err(error) => error,
    };
    assert!(error.to_string().contains("cancelled before commit"));
    service
        .wait_for_stderr("controlled_scorer_cancelled call=1")
        .await?;
    assert_eq!(harness.team.revision(), TeamRevision::INITIAL);
    let reviews = harness
        .turn
        .extension_data
        .get::<TurnPublicationReviews>()
        .expect("enabled path creates turn-scoped review state");
    assert!(reviews.state.lock().await.active.is_none());

    let captured = service.shutdown_and_finish().await?;
    assert_clean_process(&captured);
    Ok(())
}
