//! Product-level cold-resume coverage for durable Team Session activation.

use anyhow::Result;
use codex_features::Feature;
use codex_protocol::SessionId;
use codex_protocol::ThreadId;
use codex_protocol::protocol::DurableTeamSessionMeta;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::SessionSource;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::user_input::UserInput;
use codex_team_state::DurableTeamIdentity;
use codex_team_state::TEAM_WORLD_STATE_OPEN_TAG;
use codex_team_state::committed_snapshot_generation;
use codex_thread_store::AppendThreadItemsParams;
use codex_thread_store::ArchiveThreadParams;
use codex_thread_store::CreateThreadParams;
use codex_thread_store::DeleteThreadParams;
use codex_thread_store::ListThreadsParams;
use codex_thread_store::LoadThreadHistoryParams;
use codex_thread_store::ReadThreadByRolloutPathParams;
use codex_thread_store::ReadThreadParams;
use codex_thread_store::ResumeThreadParams;
use codex_thread_store::RootWriterAuthority;
use codex_thread_store::StoredThread;
use codex_thread_store::StoredThreadHistory;
use codex_thread_store::ThreadPage;
use codex_thread_store::ThreadStore;
use codex_thread_store::ThreadStoreError;
use codex_thread_store::ThreadStoreFuture;
use codex_thread_store::UpdateThreadMetadataParams;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call_with_namespace;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once_match_with;
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
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use walkdir::WalkDir;

const NAMESPACE: &str = "collaboration";
const IMMEDIATE_CRASH_PROCESS_TEST: &str =
    "suite::durable_team_session::durable_team_immediate_crash_is_cold_resumable";
const IMMEDIATE_CRASH_MODE: &str = "CODEX_DURABLE_TEAM_IMMEDIATE_CRASH_MODE";
const IMMEDIATE_CRASH_HOME: &str = "CODEX_DURABLE_TEAM_IMMEDIATE_CRASH_HOME";
const IMMEDIATE_CRASH_THREAD_PREFIX: &str = "DURABLE_TEAM_THREAD=";

struct PersistAfterSuccessThreadStore {
    inner: Arc<dyn ThreadStore>,
    persist_failures_remaining: Arc<AtomicUsize>,
    history_read_failures_remaining: Arc<AtomicUsize>,
}

impl PersistAfterSuccessThreadStore {
    fn new(inner: Arc<dyn ThreadStore>) -> Self {
        Self::with_activation_failures(inner, 1, 0)
    }

    fn with_history_read_failure(
        inner: Arc<dyn ThreadStore>,
        fail_next_history_read: bool,
    ) -> Self {
        Self::with_activation_failures(inner, 1, usize::from(fail_next_history_read))
    }

    fn with_activation_failures(
        inner: Arc<dyn ThreadStore>,
        persist_failures: usize,
        history_read_failures: usize,
    ) -> Self {
        Self::with_failure_counters(
            inner,
            Arc::new(AtomicUsize::new(persist_failures)),
            Arc::new(AtomicUsize::new(history_read_failures)),
        )
    }

    fn with_failure_counters(
        inner: Arc<dyn ThreadStore>,
        persist_failures_remaining: Arc<AtomicUsize>,
        history_read_failures_remaining: Arc<AtomicUsize>,
    ) -> Self {
        Self {
            inner,
            persist_failures_remaining,
            history_read_failures_remaining,
        }
    }

    fn take_failure(counter: &AtomicUsize) -> bool {
        counter
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |remaining| {
                remaining.checked_sub(1)
            })
            .is_ok()
    }
}

impl ThreadStore for PersistAfterSuccessThreadStore {
    fn as_any(&self) -> &dyn std::any::Any {
        self
    }

    fn default_history_mode(&self) -> codex_protocol::protocol::ThreadHistoryMode {
        self.inner.default_history_mode()
    }

    fn create_thread(&self, params: CreateThreadParams) -> ThreadStoreFuture<'_, ()> {
        self.inner.create_thread(params)
    }

    fn resume_thread(&self, params: ResumeThreadParams) -> ThreadStoreFuture<'_, ()> {
        self.inner.resume_thread(params)
    }

    fn append_items(&self, params: AppendThreadItemsParams) -> ThreadStoreFuture<'_, ()> {
        self.inner.append_items(params)
    }

    fn persist_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()> {
        let inner = Arc::clone(&self.inner);
        let fail = Self::take_failure(&self.persist_failures_remaining);
        Box::pin(async move {
            inner.persist_thread(thread_id).await?;
            if fail {
                Err(ThreadStoreError::Internal {
                    message: "injected error after canonical intent became readable".to_string(),
                })
            } else {
                Ok(())
            }
        })
    }

    fn flush_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()> {
        self.inner.flush_thread(thread_id)
    }

    fn writer_authority(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, RootWriterAuthority> {
        self.inner.writer_authority(thread_id)
    }

    fn shutdown_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()> {
        self.inner.shutdown_thread(thread_id)
    }

    fn discard_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()> {
        self.inner.discard_thread(thread_id)
    }

    fn load_history(
        &self,
        params: LoadThreadHistoryParams,
    ) -> ThreadStoreFuture<'_, StoredThreadHistory> {
        if Self::take_failure(&self.history_read_failures_remaining) {
            Box::pin(async {
                Err(ThreadStoreError::Internal {
                    message: "injected canonical intent read-back failure".to_string(),
                })
            })
        } else {
            self.inner.load_history(params)
        }
    }

    fn read_thread(&self, params: ReadThreadParams) -> ThreadStoreFuture<'_, StoredThread> {
        self.inner.read_thread(params)
    }

    fn read_thread_by_rollout_path(
        &self,
        params: ReadThreadByRolloutPathParams,
    ) -> ThreadStoreFuture<'_, StoredThread> {
        self.inner.read_thread_by_rollout_path(params)
    }

    fn list_threads(&self, params: ListThreadsParams) -> ThreadStoreFuture<'_, ThreadPage> {
        self.inner.list_threads(params)
    }

    fn update_thread_metadata(
        &self,
        params: UpdateThreadMetadataParams,
    ) -> ThreadStoreFuture<'_, StoredThread> {
        self.inner.update_thread_metadata(params)
    }

    fn archive_thread(&self, params: ArchiveThreadParams) -> ThreadStoreFuture<'_, ()> {
        self.inner.archive_thread(params)
    }

    fn unarchive_thread(&self, params: ArchiveThreadParams) -> ThreadStoreFuture<'_, StoredThread> {
        self.inner.unarchive_thread(params)
    }

    fn delete_thread(&self, params: DeleteThreadParams) -> ThreadStoreFuture<'_, ()> {
        self.inner.delete_thread(params)
    }
}

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
    let session_meta = codex_rollout::read_session_meta_line(&rollout_path).await?;
    assert_eq!(
        session_meta.meta.durable_team,
        Some(DurableTeamSessionMeta::current(session_id, thread_id))
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
    let moved_team_backend = home.path().join("team-sessions-v1-moved-for-test");
    std::fs::rename(&team_directory, &moved_team_backend)?;
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
    assert!(
        !team_directory.exists(),
        "durable-off rejection must not recreate an empty Team backend"
    );
    std::fs::rename(&moved_team_backend, &team_directory)?;

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

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_team_rejects_unknown_root_before_persistence() -> Result<()> {
    let server = start_mock_server().await;
    let home = Arc::new(tempfile::TempDir::new()?);
    let mut builder = durable_team_codex()
        .with_home(Arc::clone(&home))
        .with_session_source(SessionSource::Unknown);
    let error = match builder.build(&server).await {
        Ok(_) => anyhow::bail!("Unknown source must not activate a durable Root Session"),
        Err(error) => error,
    };
    assert!(
        format!("{error:#}").contains("verifiable Root participant identity"),
        "unexpected activation error: {error:#}"
    );
    assert!(
        !home.path().join("team-sessions").exists(),
        "rejected Unknown Root must not leave a Team artifact"
    );
    assert!(
        WalkDir::new(home.path())
            .into_iter()
            .filter_map(|entry| entry.ok())
            .all(|entry| entry.path().extension().and_then(|ext| ext.to_str()) != Some("jsonl")),
        "rejected Unknown Root must not materialize a canonical rollout"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_team_reconciles_visible_intent_after_persist_error() -> Result<()> {
    let server = start_mock_server().await;
    let home = Arc::new(tempfile::TempDir::new()?);
    let mut builder = durable_team_codex()
        .with_home(Arc::clone(&home))
        .with_thread_store_wrapper(|inner| Arc::new(PersistAfterSuccessThreadStore::new(inner)));

    let created = builder.build(&server).await?;
    let thread_id = created.session_configured.thread_id;
    let session_id = SessionId::from(thread_id);
    let rollout_path =
        codex_rollout::find_thread_path_by_id_str(home.path(), &thread_id.to_string(), None)
            .await?
            .expect("persist error happened after the canonical rollout became readable");
    let session_meta = codex_rollout::read_session_meta_line(&rollout_path).await?;
    assert_eq!(
        session_meta.meta.durable_team,
        Some(DurableTeamSessionMeta::current(session_id, thread_id))
    );

    let snapshot = std::fs::read(
        home.path()
            .join("team-sessions/v1")
            .join(format!("{thread_id}.team-state")),
    )?;
    assert_eq!(
        committed_snapshot_generation(DurableTeamIdentity::new(session_id, thread_id), &snapshot,)?,
        1,
        "the same Root owner must continue through generation-1 after read-back"
    );
    created.codex.shutdown_and_wait().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_team_retains_owner_when_intent_read_back_is_unavailable() -> Result<()> {
    let server = start_mock_server().await;
    let home = Arc::new(tempfile::TempDir::new()?);
    let mut builder = durable_team_codex()
        .with_home(Arc::clone(&home))
        .with_thread_store_wrapper(|inner| {
            Arc::new(PersistAfterSuccessThreadStore::with_history_read_failure(
                inner, true,
            ))
        });

    let created = builder.build(&server).await?;
    let thread_id = created.session_configured.thread_id;
    let session_id = SessionId::from(thread_id);
    let snapshot_path = home
        .path()
        .join("team-sessions/v1")
        .join(format!("{thread_id}.team-state"));
    assert!(
        !snapshot_path.exists(),
        "generation 1 must wait until canonical intent is proven"
    );
    let rollout_path =
        codex_rollout::find_thread_path_by_id_str(home.path(), &thread_id.to_string(), None)
            .await?
            .expect("persist-after-success made canonical intent visible");
    assert_eq!(
        codex_rollout::read_session_meta_line(&rollout_path)
            .await?
            .meta
            .durable_team,
        Some(DurableTeamSessionMeta::current(session_id, thread_id))
    );

    let responses = mount_sse_sequence_without_request_count_expectation(
        &server,
        vec![assistant_reply("activation-retried")],
    )
    .await;
    submit_turn(&created, "retry pending durable activation").await?;
    assert_eq!(responses.requests().len(), 1);
    let snapshot = std::fs::read(&snapshot_path)?;
    assert_eq!(
        committed_snapshot_generation(DurableTeamIdentity::new(session_id, thread_id), &snapshot,)?,
        1,
        "a later product access must retry under the retained Root owner"
    );
    created.codex.shutdown_and_wait().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_team_projection_fails_before_sampling_when_activation_stays_unavailable()
-> Result<()> {
    let server = start_mock_server().await;
    let home = Arc::new(tempfile::TempDir::new()?);
    let persist_failures = Arc::new(AtomicUsize::new(usize::MAX));
    let history_read_failures = Arc::new(AtomicUsize::new(usize::MAX));
    let persist_failures_for_store = Arc::clone(&persist_failures);
    let history_read_failures_for_store = Arc::clone(&history_read_failures);
    let mut builder = durable_team_codex()
        .with_home(Arc::clone(&home))
        .with_thread_store_wrapper(move |inner| {
            Arc::new(PersistAfterSuccessThreadStore::with_failure_counters(
                inner,
                Arc::clone(&persist_failures_for_store),
                Arc::clone(&history_read_failures_for_store),
            ))
        });
    let created = builder.build(&server).await?;
    let responses = mount_sse_sequence_without_request_count_expectation(
        &server,
        vec![assistant_reply("must-not-sample")],
    )
    .await;

    let error = submit_turn_expect_error(&created, "durability remains unavailable").await?;
    assert!(
        error.contains("Team world state is unavailable"),
        "unexpected projection failure: {error}"
    );
    assert_eq!(
        responses.requests().len(),
        0,
        "persistent durable activation failure must stop sampling"
    );

    persist_failures.store(0, Ordering::SeqCst);
    history_read_failures.store(0, Ordering::SeqCst);
    created.codex.shutdown_and_wait().await?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_team_wait_fails_when_root_marker_disappears_after_sampling() -> Result<()> {
    let server = start_mock_server().await;
    let home = Arc::new(tempfile::TempDir::new()?);
    let mut builder = durable_team_codex()
        .with_home(Arc::clone(&home))
        .with_config(|config| {
            config.multi_agent_v2.min_wait_timeout_ms = 50;
            config.multi_agent_v2.default_wait_timeout_ms = 50;
        });
    let created = builder.build(&server).await?;
    let rollout_path = created
        .session_configured
        .rollout_path
        .clone()
        .expect("live Root rollout path");
    assert!(
        rollout_path.is_file(),
        "canonical Root rollout must exist before sampling: {}",
        rollout_path.display()
    );
    let hidden_path = rollout_path.with_extension("jsonl.hidden-marker");
    let rollout_path_for_mock = rollout_path.clone();
    let hidden_path_for_mock = hidden_path.clone();
    let responses =
        mount_sse_once_match_with(&server, wiremock::matchers::method("POST"), move |_| {
            std::fs::rename(&rollout_path_for_mock, &hidden_path_for_mock)
                .expect("hide canonical Root marker after sampling begins");
            wait_call("wait-after-marker-loss")
        })
        .await;

    let submission_id = created
        .codex
        .submit(Op::UserInput {
            items: vec![UserInput::Text {
                text: "wait after sampling".to_string(),
                text_elements: Vec::new(),
            }],
            final_output_json_schema: None,
            responsesapi_client_metadata: None,
            additional_context: Default::default(),
            thread_settings: ThreadSettingsOverrides::default(),
        })
        .await?;
    let terminal = wait_for_turn_error(&created, &submission_id).await;
    let marker_was_hidden = hidden_path.is_file();
    if marker_was_hidden {
        std::fs::rename(&hidden_path, &rollout_path)?;
    }
    let error = terminal?;
    assert!(
        marker_was_hidden,
        "the initial sampling request must hide the canonical Root marker"
    );
    assert!(
        error.contains("Team world state is unavailable"),
        "unexpected wait failure: {error}"
    );
    assert_eq!(
        responses.requests().len(),
        1,
        "wait must not complete normally or trigger another sampling while Team durability is unavailable"
    );

    created.codex.shutdown_and_wait().await?;
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

async fn submit_turn_expect_error(test: &TestCodex, prompt: &str) -> Result<String> {
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
    wait_for_turn_error(test, &submission_id).await
}

async fn wait_for_turn_error(test: &TestCodex, submission_id: &str) -> Result<String> {
    let mut observed = Vec::new();
    tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            let event = test.codex.next_event().await?;
            let is_submission = event.id == submission_id;
            match event.msg {
                EventMsg::Error(error) if is_submission => return Ok(error.message),
                EventMsg::TurnComplete(_) if is_submission => {
                    anyhow::bail!("durable Team turn unexpectedly completed")
                }
                message => observed.push(format!("{}: {message:?}", event.id)),
            }
        }
    })
    .await
    .map_err(|_| {
        anyhow::anyhow!(
            "durable Team turn {submission_id} did not report an error; prior events: {}",
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

fn wait_call(response_id: &str) -> String {
    sse(vec![
        ev_response_created(response_id),
        ev_function_call_with_namespace(
            response_id,
            NAMESPACE,
            "wait_agent",
            r#"{"timeout_ms":50}"#,
        ),
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
