#![allow(clippy::expect_used, clippy::unwrap_used)]

//! Offline lifecycle and failure matrix for the cloud reference scorer backend.
//!
//! Every case drives the real cloud service launcher and the real typed client against a
//! deterministic loopback provider, so the assertions cover the product selection path rather
//! than an in-process stub. No case reaches a real provider.

use codex_publication_critic::ActorRole;
use codex_publication_critic::CLOUD_BACKEND_PROTOCOL;
use codex_publication_critic::ClientConfig;
use codex_publication_critic::ComponentIdentity;
use codex_publication_critic::ContinuityContext;
use codex_publication_critic::CriticFailure;
use codex_publication_critic::InfrastructureFailure;
use codex_publication_critic::LocalScope;
use codex_publication_critic::PublicationCandidate;
use codex_publication_critic::PublicationCriticClient;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::QualificationIdentity;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::ServiceDescriptor;
use codex_publication_critic::ServiceIdentity;
use codex_publication_critic::StartupAnnouncement;
use codex_publication_critic::TargetKind;
use codex_publication_critic::Verdict;
use codex_publication_critic::cloud_reference_scoring_identity;
use codex_publication_critic::controlled_test_descriptor;
use codex_publication_critic::provider_managed_model_identity;
use codex_utils_cargo_bin::cargo_bin;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::error::Error;
use std::net::SocketAddr;
use std::path::Path;
use std::path::PathBuf;
use std::process::ExitStatus;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStderr;
use tokio::process::ChildStdout;
use tokio::process::Command;
use tokio::time::Instant;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;

const API_KEY_ENV: &str = "RONDO_PLAN095_TEST_CLOUD_API_KEY";
const API_KEY: &str = "sk-plan095-loopback-only-not-a-real-credential";
const BODY_SENTINEL: &str = "PLAN095_SYNTHETIC_CANDIDATE_BODY";
const REASONING_SENTINEL: &str = "PLAN096_PRIVATE_REASONING_MUST_NOT_LEAK";
const PROVIDER_MODEL: &str = "rondo-plan095-fake-model";
const PROVIDER_PATH: &str = "/v1/chat/completions";
const PROCESS_TIMEOUT: Duration = Duration::from_secs(10);
const IO_TIMEOUT: Duration = Duration::from_millis(800);

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

static NEXT_TEMP_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy)]
struct DescriptorOptions {
    job_timeout: Duration,
    request_timeout: Duration,
    max_attempts: u8,
    retry_backoff: Duration,
    max_concurrency: u16,
    queue_capacity: u16,
    served_model: &'static str,
    threshold: f64,
}

impl Default for DescriptorOptions {
    fn default() -> Self {
        Self {
            job_timeout: Duration::from_millis(2_000),
            request_timeout: Duration::from_millis(900),
            max_attempts: 2,
            retry_backoff: Duration::from_millis(100),
            max_concurrency: 1,
            queue_capacity: 4,
            served_model: "echoed",
            threshold: 0.5,
        }
    }
}

fn service_descriptor(options: DescriptorOptions) -> TestResult<ServiceDescriptor> {
    let identity = ServiceIdentity::new(
        ComponentIdentity::new("rondo-publication-critic-cloud-service", "v1")?,
        QualificationIdentity::new(
            ComponentIdentity::new("rondo-publication-packet", "v1")?,
            ComponentIdentity::new("rondo-publication-qualification", "v1")?,
        ),
        provider_managed_model_identity(PROVIDER_MODEL)?,
        cloud_reference_scoring_identity(PROVIDER_MODEL, "v1", options.threshold)?,
    )?;
    Ok(ServiceDescriptor::new(
        identity,
        RuntimeLimits::new(
            32 * 1024,
            16 * 1024,
            options.max_concurrency,
            options.queue_capacity,
            options.job_timeout,
            IO_TIMEOUT,
        )?,
    )?)
}

fn cloud_descriptor(base_url: &str, options: DescriptorOptions) -> TestResult<Value> {
    Ok(json!({
        "backend_protocol": CLOUD_BACKEND_PROTOCOL,
        "provider": {
            "api": "chat_completions",
            "base_url": base_url,
            "api_key_env": API_KEY_ENV,
            "model": PROVIDER_MODEL,
            "served_model": options.served_model,
            "response_format": "json_object",
            "max_output_tokens": 64,
            "temperature": 0.0,
            "request_timeout_ms": u64::try_from(options.request_timeout.as_millis())?,
            "max_attempts": options.max_attempts,
            "retry_backoff_ms": u64::try_from(options.retry_backoff.as_millis())?,
        },
        "service_descriptor": service_descriptor(options)?,
    }))
}

fn test_packet(descriptor: &ServiceDescriptor) -> TestResult<PublicationPacket> {
    Ok(PublicationPacket::new(
        descriptor.identity.qualification.clone(),
        ActorRole::Root,
        TargetKind::NewEvent,
        LocalScope::new("Plan 095 synthetic cloud smoke")?,
        PublicationCandidate::new(format!(
            "Synthetic candidate {BODY_SENTINEL}: the loopback provider scores this packet."
        ))?,
        ContinuityContext::NotApplicable,
    )?)
}

/// Deterministic loopback stand-in for a hosted chat-completions provider.
struct FakeProvider {
    server: MockServer,
}

impl FakeProvider {
    async fn start() -> Self {
        Self {
            server: MockServer::start().await,
        }
    }

    fn base_url(&self) -> String {
        format!("{}/v1", self.server.uri())
    }

    async fn mount(&self, response: ResponseTemplate) {
        Mock::given(method("POST"))
            .and(path(PROVIDER_PATH))
            .respond_with(response)
            .mount(&self.server)
            .await;
    }

    /// Answers `first` once, then every later request with `rest`.
    async fn mount_sequence(&self, first: ResponseTemplate, rest: ResponseTemplate) {
        Mock::given(method("POST"))
            .and(path(PROVIDER_PATH))
            .respond_with(first)
            .up_to_n_times(1)
            .with_priority(/*p*/ 1)
            .mount(&self.server)
            .await;
        Mock::given(method("POST"))
            .and(path(PROVIDER_PATH))
            .respond_with(rest)
            .with_priority(/*p*/ 2)
            .mount(&self.server)
            .await;
    }

    async fn mount_quality(&self, quality: f64) {
        self.mount(ResponseTemplate::new(200).set_body_json(completion(
            PROVIDER_MODEL,
            &format!(r#"{{"quality":{quality}}}"#),
        )))
        .await;
    }

    async fn requests(&self) -> Vec<wiremock::Request> {
        self.server.received_requests().await.unwrap_or_default()
    }

    /// Waits until the provider has actually received `count` requests. wiremock records an
    /// incoming request before it applies any response delay, so this returns while a delayed
    /// call is still in flight.
    async fn wait_for_requests(&self, count: usize) -> TestResult {
        timeout(PROCESS_TIMEOUT, async {
            while self.requests().await.len() < count {
                tokio::time::sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .map_err(|_| format!("provider did not receive {count} requests"))?;
        Ok(())
    }
}

fn completion(model: &str, content: &str) -> Value {
    json!({
        "id": "chatcmpl-plan095",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 512, "completion_tokens": 8, "total_tokens": 520},
    })
}

fn detailed_completion(model: &str, content: Option<&str>, finish_reason: Option<&str>) -> Value {
    let mut choice = json!({
        "index": 0,
        "message": {
            "role": "assistant",
            "content": content,
            "reasoning_content": REASONING_SENTINEL,
        },
    });
    if let Some(finish_reason) = finish_reason {
        choice["finish_reason"] = json!(finish_reason);
    }
    json!({
        "id": "chatcmpl-plan096",
        "object": "chat.completion",
        "created": 1_700_000_000,
        "model": model,
        "choices": [choice],
        "usage": {
            "prompt_tokens": 512,
            "completion_tokens": 8,
            "total_tokens": 520,
            "prompt_cache_hit_tokens": 128,
            "prompt_cache_miss_tokens": 384,
        },
    })
}

struct Fixture {
    root: PathBuf,
    descriptor_path: PathBuf,
    packet_path: PathBuf,
    expected: ServiceDescriptor,
}

impl Fixture {
    fn new(base_url: &str, options: DescriptorOptions) -> TestResult<Self> {
        let unique = NEXT_TEMP_ID.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "rondo-plan095-cloud-{}-{unique}",
            std::process::id()
        ));
        std::fs::create_dir(&root)?;
        let descriptor_path = root.join("cloud-descriptor.json");
        let packet_path = root.join("packet.json");
        let expected = service_descriptor(options)?;
        std::fs::write(
            &descriptor_path,
            serde_json::to_vec(&cloud_descriptor(base_url, options)?)?,
        )?;
        std::fs::write(&packet_path, serde_json::to_vec(&test_packet(&expected)?)?)?;
        Ok(Self {
            root,
            descriptor_path,
            packet_path,
            expected,
        })
    }

    fn packet(&self) -> TestResult<PublicationPacket> {
        test_packet(&self.expected)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.root);
    }
}

struct CapturedProbe {
    status: ExitStatus,
    stdout: String,
    stderr: String,
}

#[derive(Clone, Copy)]
enum DiagnosticMode {
    Evaluate,
    RenderMessages,
}

struct CloudService {
    child: Child,
    stdout: BufReader<ChildStdout>,
    stderr: ChildStderr,
    endpoint: SocketAddr,
    descriptor_path: PathBuf,
    expected: ServiceDescriptor,
}

impl CloudService {
    async fn spawn(fixture: &Fixture, shutdown: Duration) -> TestResult<Self> {
        let mut command = Command::new(cargo_bin("codex-publication-critic-cloud-service")?);
        command
            .arg("--descriptor")
            .arg(&fixture.descriptor_path)
            .arg("--graceful-shutdown-ms")
            .arg(shutdown.as_millis().to_string())
            .arg("--force-shutdown-ms")
            .arg(shutdown.as_millis().to_string())
            .env(API_KEY_ENV, API_KEY)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let mut child = command.spawn()?;
        let stdout = child.stdout.take().ok_or("service stdout was not piped")?;
        let stderr = child.stderr.take().ok_or("service stderr was not piped")?;
        let mut stdout = BufReader::new(stdout);
        let mut line = String::new();
        let read = timeout(PROCESS_TIMEOUT, stdout.read_line(&mut line))
            .await
            .map_err(|_| "cloud service startup announcement timed out")??;
        if read == 0 {
            return Err("cloud service exited before its startup announcement".into());
        }
        let announcement: StartupAnnouncement = serde_json::from_str(line.trim_end())?;
        assert_eq!(announcement.descriptor, fixture.expected);
        assert!(announcement.endpoint.ip().is_loopback());
        Ok(Self {
            child,
            stdout,
            stderr,
            endpoint: announcement.endpoint,
            descriptor_path: fixture.descriptor_path.clone(),
            expected: fixture.expected.clone(),
        })
    }

    fn client(&self, call_timeout: Duration) -> TestResult<PublicationCriticClient> {
        Ok(PublicationCriticClient::new(ClientConfig::new(
            self.endpoint,
            self.expected.clone(),
            call_timeout,
            Duration::from_secs(5),
        )?)?)
    }

    async fn probe(&self, command: &[&str]) -> TestResult<CapturedProbe> {
        let mut process = Command::new(cargo_bin("codex-publication-critic-probe")?);
        process
            .arg("--endpoint")
            .arg(self.endpoint.to_string())
            .arg("--expected-cloud-descriptor")
            .arg(&self.descriptor_path)
            .arg("--call-timeout-ms")
            .arg("5000")
            .arg("--startup-timeout-ms")
            .arg("5000")
            .args(command)
            .env_remove(API_KEY_ENV)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let output = timeout(PROCESS_TIMEOUT, process.output())
            .await
            .map_err(|_| "probe process timed out")??;
        Ok(CapturedProbe {
            status: output.status,
            stdout: String::from_utf8(output.stdout)?,
            stderr: String::from_utf8(output.stderr)?,
        })
    }

    async fn finish(mut self) -> TestResult<(ExitStatus, String, String)> {
        let status = timeout(PROCESS_TIMEOUT, self.child.wait())
            .await
            .map_err(|_| "cloud service shutdown timed out")??;
        let mut stdout = String::new();
        self.stdout.read_to_string(&mut stdout).await?;
        let mut stderr = String::new();
        self.stderr.read_to_string(&mut stderr).await?;
        assert_body_free(&stdout, &stderr);
        Ok((status, stdout, stderr))
    }
}

fn assert_body_free(stdout: &str, stderr: &str) {
    for stream in [stdout, stderr] {
        assert!(!stream.contains(API_KEY), "output exposed the credential");
        assert!(
            !stream.contains(BODY_SENTINEL),
            "output exposed the candidate body"
        );
    }
}

fn assert_probe_success(probe: &CapturedProbe, expected: &str) {
    assert!(
        probe.status.success(),
        "probe failed: status={} stderr={}",
        probe.status,
        probe.stderr
    );
    assert!(
        probe.stdout.contains(expected),
        "probe output: {}",
        probe.stdout
    );
    assert_body_free(&probe.stdout, &probe.stderr);
}

fn assert_probe_failure(probe: &CapturedProbe, expected_code: &str) {
    assert!(
        !probe.status.success(),
        "probe unexpectedly succeeded: {}",
        probe.stdout
    );
    assert!(
        probe.stderr.contains(expected_code),
        "probe stderr: {}",
        probe.stderr
    );
    assert_body_free(&probe.stdout, &probe.stderr);
}

fn path_text(path: &Path) -> TestResult<&str> {
    path.to_str().ok_or_else(|| "test path is not UTF-8".into())
}

async fn run_cloud_eval(fixture: &Fixture, input: &[u8]) -> TestResult<CapturedProbe> {
    let mut command = Command::new(cargo_bin("codex-publication-critic-cloud-eval")?);
    command
        .arg("--descriptor")
        .arg(&fixture.descriptor_path)
        .env(API_KEY_ENV, API_KEY)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let mut child = command.spawn()?;
    let mut stdin = child.stdin.take().ok_or("cloud eval stdin was not piped")?;
    stdin.write_all(input).await?;
    stdin.shutdown().await?;
    drop(stdin);
    let output = timeout(PROCESS_TIMEOUT, child.wait_with_output())
        .await
        .map_err(|_| "cloud eval process timed out")??;
    Ok(CapturedProbe {
        status: output.status,
        stdout: String::from_utf8(output.stdout)?,
        stderr: String::from_utf8(output.stderr)?,
    })
}

async fn run_cloud_diagnostic(
    fixture: &Fixture,
    task: &str,
    input: &[u8],
    mode: DiagnosticMode,
) -> TestResult<CapturedProbe> {
    let mut command = Command::new(cargo_bin("codex-publication-critic-cloud-diagnostic")?);
    command
        .arg("--descriptor")
        .arg(&fixture.descriptor_path)
        .arg("--task")
        .arg(task)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    match mode {
        DiagnosticMode::Evaluate => {
            command.env(API_KEY_ENV, API_KEY);
        }
        DiagnosticMode::RenderMessages => {
            command.arg("--render-messages");
        }
    }
    let mut child = command.spawn()?;
    let mut stdin = child
        .stdin
        .take()
        .ok_or("cloud diagnostic stdin was not piped")?;
    stdin.write_all(input).await?;
    stdin.shutdown().await?;
    drop(stdin);
    let output = timeout(PROCESS_TIMEOUT, child.wait_with_output())
        .await
        .map_err(|_| "cloud diagnostic process timed out")??;
    Ok(CapturedProbe {
        status: output.status,
        stdout: String::from_utf8(output.stdout)?,
        stderr: String::from_utf8(output.stderr)?,
    })
}

#[tokio::test(flavor = "current_thread")]
async fn cloud_backend_reaches_ready_and_produces_both_verdicts() -> TestResult {
    let provider = FakeProvider::start().await;
    provider
        .mount_sequence(
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#)),
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.12}"#)),
        )
        .await;
    let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
    let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;

    assert_probe_success(&service.probe(&["ready"]).await?, "\"result\":\"ready\"");
    assert_probe_success(
        &service
            .probe(&["review", "--packet", path_text(&fixture.packet_path)?])
            .await?,
        "\"result\":\"pass\"",
    );
    assert_probe_success(
        &service
            .probe(&["review", "--packet", path_text(&fixture.packet_path)?])
            .await?,
        "\"result\":\"rewrite\"",
    );
    assert_probe_success(
        &service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );

    let requests = provider.requests().await;
    assert_eq!(
        requests.len(),
        2,
        "readiness must not send a provider probe"
    );
    let body: Value = serde_json::from_slice(&requests[0].body)?;
    assert_eq!(body["model"], json!(PROVIDER_MODEL));
    assert_eq!(body["temperature"], json!(0.0));
    assert_eq!(body["max_tokens"], json!(64));
    assert_eq!(body["stream"], json!(false));
    assert_eq!(body["response_format"]["type"], json!("json_object"));
    assert!(body.get("thinking").is_none());
    assert!(body.get("reasoning_effort").is_none());
    let user = body["messages"][1]["content"]
        .as_str()
        .ok_or("user message must be a string")?;
    assert_eq!(
        serde_json::from_str::<PublicationPacket>(user)?,
        fixture.packet()?,
        "the cloud template must send the stable packet projection"
    );
    let authorization = format!("Bearer {API_KEY}");
    assert_eq!(
        requests[0]
            .headers
            .get("authorization")
            .and_then(|value| value.to_str().ok()),
        Some(authorization.as_str()),
    );

    let (status, stdout, stderr) = service.finish().await?;
    assert!(status.success(), "cloud service failed: {status}");
    assert!(
        stdout.is_empty(),
        "service emitted stdout after announcement"
    );
    assert!(stderr.contains("publication_critic_cloud_service_listening"));
    assert!(stderr.contains("publication_critic_cloud_service_stopped"));
    assert!(stderr.contains("publication_critic_cloud_call attempts=1"));
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn eval_entry_point_preserves_scalar_model_and_cache_usage_without_reasoning() -> TestResult {
    let provider = FakeProvider::start().await;
    provider
        .mount(
            ResponseTemplate::new(200).set_body_json(detailed_completion(
                PROVIDER_MODEL,
                Some(r#"{"quality":0.83}"#),
                Some("stop"),
            )),
        )
        .await;
    let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
    let input = std::fs::read(&fixture.packet_path)?;
    let output = run_cloud_eval(&fixture, &input).await?;
    assert!(
        output.status.success(),
        "cloud eval failed: {}",
        output.stderr
    );
    assert_body_free(&output.stdout, &output.stderr);
    assert!(!output.stdout.contains(REASONING_SENTINEL));
    assert!(!output.stderr.contains(REASONING_SENTINEL));
    assert_eq!(
        output
            .stderr
            .matches("publication_critic_cloud_attempt attempt=1")
            .count(),
        1
    );

    let mut observation: Value = serde_json::from_str(output.stdout.trim())?;
    assert!(observation["elapsed_ms"].as_u64().is_some());
    observation["elapsed_ms"] = json!(0);
    assert_eq!(
        observation,
        json!({
            "requested_model": PROVIDER_MODEL,
            "served_model": PROVIDER_MODEL,
            "score": 0.83,
            "attempts": 1,
            "elapsed_ms": 0,
            "usage": {
                "prompt_tokens": 512,
                "completion_tokens": 8,
                "total_tokens": 520,
                "prompt_cache_hit_tokens": 128,
                "prompt_cache_miss_tokens": 384,
            },
            "outcome": {"type": "success"},
        })
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn diagnostic_entry_point_keeps_only_output_contract_variable_and_never_retries_parse_failure()
-> TestResult {
    let cases = [
        ("scalar", r#"{"quality":0.83}"#, 2, false),
        ("direct-gate", r#"{"verdict":"PASS"}"#, 1, false),
        (
            "five-dimension",
            r#"{"useful_state_transfer":"PASS","honest_uncertainty":"PASS","conditional_continuity":"N/A","scope_and_signal":"PASS","internal_consistency":"PASS"}"#,
            1,
            true,
        ),
    ];
    let mut normalized_request = None;
    for (task, content, expected_attempts, has_local_verdict) in cases {
        let provider = FakeProvider::start().await;
        let terminal = ResponseTemplate::new(200).set_body_json(detailed_completion(
            PROVIDER_MODEL,
            Some(content),
            Some("stop"),
        ));
        if expected_attempts == 2 {
            provider
                .mount_sequence(ResponseTemplate::new(429), terminal)
                .await;
        } else {
            provider.mount(terminal).await;
        }
        let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
        let input = std::fs::read(&fixture.packet_path)?;
        let output = run_cloud_diagnostic(&fixture, task, &input, DiagnosticMode::Evaluate).await?;
        assert!(
            output.status.success(),
            "diagnostic failed: {}",
            output.stderr
        );
        assert_body_free(&output.stdout, &output.stderr);
        assert!(!output.stdout.contains(REASONING_SENTINEL));
        assert!(!output.stderr.contains(REASONING_SENTINEL));

        let observation: Value = serde_json::from_str(output.stdout.trim())?;
        assert_eq!(observation["response_text"], json!(content));
        assert!(!observation["output"].is_null());
        assert_eq!(observation["local_verdict"].is_string(), has_local_verdict);
        assert_eq!(observation["outcome"], json!({"type": "success"}));
        assert_eq!(observation["attempts"], json!(expected_attempts));
        assert_eq!(observation["usage"]["prompt_tokens"], json!(512));
        let requested_at = observation["attempt_requested_at_unix_ms"]
            .as_array()
            .ok_or("attempt timestamps must be an array")?;
        assert_eq!(requested_at.len(), expected_attempts);
        assert!(requested_at[0].as_u64().is_some_and(|value| value > 0));

        let requests = provider.requests().await;
        assert_eq!(requests.len(), expected_attempts);
        let mut body = serde_json::from_slice::<Value>(&requests[0].body)?;
        assert_eq!(body["thinking"]["type"], json!("disabled"));
        let system = body["messages"][0]["content"]
            .as_str()
            .ok_or("system message must be a string")?;
        let (common, contract) = system
            .split_once("# Output contract\n\n")
            .ok_or("diagnostic prompt lacks output contract boundary")?;
        assert!(!common.is_empty() && !contract.is_empty());
        body["messages"][0]["content"] = json!(common);
        if let Some(expected) = &normalized_request {
            assert_eq!(&body, expected);
        } else {
            normalized_request = Some(body);
        }
    }

    let provider = FakeProvider::start().await;
    let invalid = r#"{"useful_state_transfer":"PASS","honest_uncertainty":"PASS","conditional_continuity":"N/A","scope_and_signal":"PASS","internal_consistency":"PASS","gate":"PASS"}"#;
    provider
        .mount(
            ResponseTemplate::new(200).set_body_json(detailed_completion(
                PROVIDER_MODEL,
                Some(invalid),
                Some("stop"),
            )),
        )
        .await;
    let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
    let input = std::fs::read(&fixture.packet_path)?;
    let output =
        run_cloud_diagnostic(&fixture, "five-dimension", &input, DiagnosticMode::Evaluate).await?;
    assert!(
        output.status.success(),
        "diagnostic failed: {}",
        output.stderr
    );
    assert_body_free(&output.stdout, &output.stderr);
    let observation: Value = serde_json::from_str(output.stdout.trim())?;
    assert_eq!(observation["attempts"], json!(1));
    assert_eq!(observation["response_text"], json!(invalid));
    assert_eq!(observation["outcome"]["kind"], "output_contract_violation");
    assert_eq!(provider.requests().await.len(), 1);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn diagnostic_message_renderer_is_offline_and_matches_the_paid_request() -> TestResult {
    let provider = FakeProvider::start().await;
    provider
        .mount(
            ResponseTemplate::new(200).set_body_json(detailed_completion(
                PROVIDER_MODEL,
                Some(r#"{"verdict":"PASS"}"#),
                Some("stop"),
            )),
        )
        .await;
    let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
    let input = std::fs::read(&fixture.packet_path)?;
    let rendered = run_cloud_diagnostic(
        &fixture,
        "direct-gate",
        &input,
        DiagnosticMode::RenderMessages,
    )
    .await?;
    assert!(
        rendered.status.success(),
        "renderer failed: {}",
        rendered.stderr
    );
    assert!(rendered.stderr.is_empty());
    assert_eq!(provider.requests().await.len(), 0);
    let rendered: Value = serde_json::from_str(rendered.stdout.trim())?;

    let evaluated =
        run_cloud_diagnostic(&fixture, "direct-gate", &input, DiagnosticMode::Evaluate).await?;
    assert!(
        evaluated.status.success(),
        "diagnostic failed: {}",
        evaluated.stderr
    );
    let requests = provider.requests().await;
    assert_eq!(requests.len(), 1);
    let body: Value = serde_json::from_slice(&requests[0].body)?;
    assert_eq!(rendered["system"], body["messages"][0]["content"]);
    assert_eq!(rendered["user"], body["messages"][1]["content"]);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn eval_malformed_finish_retains_usage_and_never_exposes_reasoning() -> TestResult {
    for finish_reason in [Some("length"), None] {
        let provider = FakeProvider::start().await;
        provider
            .mount(
                ResponseTemplate::new(200).set_body_json(detailed_completion(
                    PROVIDER_MODEL,
                    None,
                    finish_reason,
                )),
            )
            .await;
        let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
        let input = std::fs::read(&fixture.packet_path)?;
        let output = run_cloud_eval(&fixture, &input).await?;
        assert!(
            output.status.success(),
            "cloud eval failed: {}",
            output.stderr
        );
        assert_body_free(&output.stdout, &output.stderr);
        assert!(!output.stdout.contains(REASONING_SENTINEL));
        assert!(!output.stderr.contains(REASONING_SENTINEL));

        let observation: Value = serde_json::from_str(output.stdout.trim())?;
        assert_eq!(observation["attempts"], json!(1));
        assert_eq!(observation["score"], Value::Null);
        assert_eq!(observation["usage"]["prompt_tokens"], json!(512));
        assert_eq!(observation["usage"]["completion_tokens"], json!(8));
        assert_eq!(
            observation["outcome"],
            json!({
                "type": "failure",
                "kind": "provider_malformed_response",
                "http_status": null,
            })
        );
        assert_eq!(provider.requests().await.len(), 1);
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn eval_model_drift_and_out_of_domain_scores_are_typed_observations() -> TestResult {
    for (model, quality, expected_kind) in [
        (
            "rondo-plan096-substituted-model",
            0.83,
            "model_identity_mismatch",
        ),
        (PROVIDER_MODEL, 1.7, "score_out_of_domain"),
    ] {
        let provider = FakeProvider::start().await;
        provider
            .mount(
                ResponseTemplate::new(200).set_body_json(detailed_completion(
                    model,
                    Some(&format!(r#"{{"quality":{quality}}}"#)),
                    Some("stop"),
                )),
            )
            .await;
        let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
        let input = std::fs::read(&fixture.packet_path)?;
        let output = run_cloud_eval(&fixture, &input).await?;
        assert!(
            output.status.success(),
            "cloud eval failed: {}",
            output.stderr
        );
        assert_body_free(&output.stdout, &output.stderr);
        let observation: Value = serde_json::from_str(output.stdout.trim())?;
        assert_eq!(observation["served_model"], json!(model));
        assert_eq!(observation["score"], json!(quality));
        assert_eq!(observation["usage"]["total_tokens"], json!(520));
        assert_eq!(observation["outcome"]["type"], json!("failure"));
        assert_eq!(observation["outcome"]["kind"], json!(expected_kind));
        assert_eq!(observation["outcome"]["http_status"], Value::Null);
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn eval_retry_and_terminal_status_keep_attempts_and_body_free_failure() -> TestResult {
    let throttled = FakeProvider::start().await;
    throttled
        .mount_sequence(
            ResponseTemplate::new(429).set_body_string("rate limited"),
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#)),
        )
        .await;
    let fixture = Fixture::new(&throttled.base_url(), DescriptorOptions::default())?;
    let input = std::fs::read(&fixture.packet_path)?;
    let output = run_cloud_eval(&fixture, &input).await?;
    assert!(
        output.status.success(),
        "cloud eval failed: {}",
        output.stderr
    );
    let observation: Value = serde_json::from_str(output.stdout.trim())?;
    assert_eq!(observation["attempts"], json!(2));
    assert_eq!(observation["outcome"], json!({"type": "success"}));
    assert_eq!(throttled.requests().await.len(), 2);
    assert_eq!(
        output
            .stderr
            .matches("publication_critic_cloud_attempt attempt=")
            .count(),
        2
    );

    let unauthorized = FakeProvider::start().await;
    unauthorized
        .mount(ResponseTemplate::new(401).set_body_string(REASONING_SENTINEL))
        .await;
    let fixture = Fixture::new(&unauthorized.base_url(), DescriptorOptions::default())?;
    let input = std::fs::read(&fixture.packet_path)?;
    let output = run_cloud_eval(&fixture, &input).await?;
    assert!(
        output.status.success(),
        "cloud eval failed: {}",
        output.stderr
    );
    assert_body_free(&output.stdout, &output.stderr);
    assert!(!output.stdout.contains(REASONING_SENTINEL));
    assert!(!output.stderr.contains(REASONING_SENTINEL));
    let observation: Value = serde_json::from_str(output.stdout.trim())?;
    assert_eq!(observation["attempts"], json!(1));
    assert_eq!(observation["score"], Value::Null);
    assert_eq!(observation["usage"], Value::Null);
    assert_eq!(
        observation["outcome"],
        json!({
            "type": "failure",
            "kind": "provider_http_status",
            "http_status": 401,
        })
    );
    assert_eq!(unauthorized.requests().await.len(), 1);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn eval_invalid_local_input_exits_before_credential_or_provider_use() -> TestResult {
    let provider = FakeProvider::start().await;
    provider.mount_quality(/*quality*/ 0.83).await;
    let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
    let output = run_cloud_eval(&fixture, b"{}").await?;
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    assert!(output.stderr.contains("code=invalid_packet"));
    assert!(!output.stderr.contains("publication_critic_cloud_attempt"));
    assert!(provider.requests().await.is_empty());
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn replies_that_are_not_one_in_domain_scalar_stay_typed_failures() -> TestResult {
    for (content, expected_code) in [
        (r#"{"quality":0.83,"reason":"looks fine"}"#, "code=backend"),
        ("The candidate passes.", "code=backend"),
        (r#"{"quality":1.7}"#, "code=invalid_score"),
    ] {
        let provider = FakeProvider::start().await;
        provider
            .mount(ResponseTemplate::new(200).set_body_json(completion(PROVIDER_MODEL, content)))
            .await;
        let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;
        let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;
        assert_probe_failure(
            &service
                .probe(&["review", "--packet", path_text(&fixture.packet_path)?])
                .await?,
            expected_code,
        );
        assert_eq!(
            provider.requests().await.len(),
            1,
            "a deterministic projection failure must not be retried"
        );
        assert_probe_success(
            &service.probe(&["shutdown"]).await?,
            "\"result\":\"accepted\"",
        );
        let (status, _, _) = service.finish().await?;
        assert!(status.success(), "cloud service failed: {status}");
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn served_model_drift_becomes_a_typed_model_identity_mismatch() -> TestResult {
    // A reply naming a different model is real drift in both modes: `provider_managed` only
    // tolerates a reply that names no model at all.
    for served_model in ["echoed", "provider_managed"] {
        let provider = FakeProvider::start().await;
        provider
            .mount(ResponseTemplate::new(200).set_body_json(completion(
                "rondo-plan095-substituted-model",
                r#"{"quality":0.83}"#,
            )))
            .await;
        let options = DescriptorOptions {
            served_model,
            ..DescriptorOptions::default()
        };
        let fixture = Fixture::new(&provider.base_url(), options)?;
        let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;
        assert_probe_failure(
            &service
                .probe(&["review", "--packet", path_text(&fixture.packet_path)?])
                .await?,
            "code=identity_mismatch",
        );
        assert_probe_success(
            &service.probe(&["shutdown"]).await?,
            "\"result\":\"accepted\"",
        );
        let (status, _, _) = service.finish().await?;
        assert!(status.success(), "cloud service failed: {status}");
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn a_provider_managed_descriptor_accepts_an_unverifiable_served_model() -> TestResult {
    let provider = FakeProvider::start().await;
    provider
        .mount(ResponseTemplate::new(200).set_body_json(json!({
            "choices": [{
                "message": {"role": "assistant", "content": r#"{"quality":0.9}"#},
                "finish_reason": "stop",
            }],
        })))
        .await;
    let options = DescriptorOptions {
        served_model: "provider_managed",
        ..DescriptorOptions::default()
    };
    let fixture = Fixture::new(&provider.base_url(), options)?;
    let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;
    assert_probe_success(
        &service
            .probe(&["review", "--packet", path_text(&fixture.packet_path)?])
            .await?,
        "\"result\":\"pass\"",
    );
    assert_probe_success(
        &service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );
    let (status, _, stderr) = service.finish().await?;
    assert!(status.success(), "cloud service failed: {status}");
    assert!(stderr.contains("prompt_tokens=none"));
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn transient_status_is_retried_once_and_terminal_status_is_not() -> TestResult {
    let throttled = FakeProvider::start().await;
    throttled
        .mount_sequence(
            ResponseTemplate::new(429).set_body_string("rate limited: quota exhausted"),
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#)),
        )
        .await;
    let fixture = Fixture::new(&throttled.base_url(), DescriptorOptions::default())?;
    let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;
    assert_probe_success(
        &service
            .probe(&["review", "--packet", path_text(&fixture.packet_path)?])
            .await?,
        "\"result\":\"pass\"",
    );
    assert_eq!(throttled.requests().await.len(), 2);
    assert_probe_success(
        &service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );
    let (status, _, stderr) = service.finish().await?;
    assert!(status.success(), "cloud service failed: {status}");
    assert!(stderr.contains("publication_critic_cloud_call attempts=2"));

    let unauthorized = FakeProvider::start().await;
    unauthorized
        .mount(ResponseTemplate::new(401).set_body_string("invalid api key sk-secret-leak"))
        .await;
    let fixture = Fixture::new(&unauthorized.base_url(), DescriptorOptions::default())?;
    let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;
    let probe = service
        .probe(&["review", "--packet", path_text(&fixture.packet_path)?])
        .await?;
    assert_probe_failure(&probe, "code=backend");
    assert_eq!(
        unauthorized.requests().await.len(),
        1,
        "authentication failures must not be retried"
    );
    assert_probe_success(
        &service.probe(&["shutdown"]).await?,
        "\"result\":\"accepted\"",
    );
    let (status, _, stderr) = service.finish().await?;
    assert!(status.success(), "cloud service failed: {status}");
    assert!(stderr.contains("kind=status status=401"));
    assert!(
        !stderr.contains("sk-secret-leak"),
        "provider error body leaked into service output"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn a_slow_provider_stays_inside_the_service_deadline_and_can_be_cancelled() -> TestResult {
    let provider = FakeProvider::start().await;
    let options = DescriptorOptions {
        job_timeout: Duration::from_millis(1_500),
        request_timeout: Duration::from_millis(300),
        max_attempts: 1,
        retry_backoff: Duration::ZERO,
        ..DescriptorOptions::default()
    };
    provider
        .mount_sequence(
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#))
                .set_delay(Duration::from_secs(30)),
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#)),
        )
        .await;
    let fixture = Fixture::new(&provider.base_url(), options)?;
    let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;
    let client = service.client(Duration::from_secs(5))?;

    // Descriptor validation keeps the backend's own worst-case attempt budget inside the service
    // job deadline, so a request that starts executing immediately normally converges to a typed
    // backend failure first. The service deadline stays the outer bound and can still fire first
    // when a call waits in the queue, so this asserts the bound, not which failure wins.
    let started = Instant::now();
    assert_eq!(
        client.review(fixture.packet()?).await,
        Err(CriticFailure::Infrastructure(
            InfrastructureFailure::Backend
        ))
    );
    assert!(
        started.elapsed() < options.job_timeout,
        "slow provider was not bounded by the backend attempt deadline"
    );

    // A cancelled review wins immediately and leaves nothing behind: the next call is healthy.
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    assert_eq!(
        client
            .review_with_cancellation(fixture.packet()?, cancellation)
            .await,
        Err(CriticFailure::Cancelled)
    );
    assert_eq!(client.review(fixture.packet()?).await, Ok(Verdict::Pass));

    client.shutdown().await?;
    let (status, _, _) = service.finish().await?;
    assert!(status.success(), "cloud service failed: {status}");
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrency_and_queue_capacity_bound_the_cloud_backend() -> TestResult {
    let provider = FakeProvider::start().await;
    provider
        .mount(
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#))
                .set_delay(Duration::from_millis(400)),
        )
        .await;
    let options = DescriptorOptions {
        job_timeout: Duration::from_millis(4_000),
        request_timeout: Duration::from_millis(1_900),
        max_attempts: 2,
        retry_backoff: Duration::from_millis(100),
        max_concurrency: 1,
        queue_capacity: 1,
        ..DescriptorOptions::default()
    };
    let fixture = Fixture::new(&provider.base_url(), options)?;
    let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;
    let client = service.client(Duration::from_secs(8))?;

    let mut calls = Vec::new();
    for _ in 0..3 {
        let client = client.clone();
        let packet = fixture.packet()?;
        calls.push(tokio::spawn(async move { client.review(packet).await }));
    }
    let mut verdicts = 0;
    let mut queue_full = 0;
    for call in calls {
        match timeout(PROCESS_TIMEOUT, call).await?? {
            Ok(Verdict::Pass) => verdicts += 1,
            Err(CriticFailure::Infrastructure(InfrastructureFailure::QueueFull)) => queue_full += 1,
            other => return Err(format!("unexpected concurrent result: {other:?}").into()),
        }
    }
    assert_eq!(
        (verdicts, queue_full),
        (2, 1),
        "one admitted call, one queued call, and one rejection are expected"
    );

    client.shutdown().await?;
    let (status, _, _) = service.finish().await?;
    assert!(status.success(), "cloud service failed: {status}");
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn cancelling_an_in_flight_provider_call_drops_its_retry_and_frees_the_backend() -> TestResult
{
    let provider = FakeProvider::start().await;
    let options = DescriptorOptions {
        job_timeout: Duration::from_millis(1_500),
        request_timeout: Duration::from_millis(300),
        max_attempts: 2,
        retry_backoff: Duration::from_millis(100),
        ..DescriptorOptions::default()
    };
    // Without cancellation the first attempt would time out after 300 ms and a second provider
    // request would follow ~100 ms later, so a stable count of one proves the retry was dropped.
    provider
        .mount_sequence(
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#))
                .set_delay(Duration::from_secs(30)),
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#)),
        )
        .await;
    let fixture = Fixture::new(&provider.base_url(), options)?;
    let service = CloudService::spawn(&fixture, Duration::from_millis(500)).await?;
    let client = service.client(Duration::from_secs(5))?;

    let cancellation = CancellationToken::new();
    let review = tokio::spawn({
        let client = client.clone();
        let packet = fixture.packet()?;
        let cancellation = cancellation.clone();
        async move { client.review_with_cancellation(packet, cancellation).await }
    });
    provider.wait_for_requests(1).await?;
    cancellation.cancel();
    assert_eq!(
        timeout(PROCESS_TIMEOUT, review).await??,
        Err(CriticFailure::Cancelled)
    );

    tokio::time::sleep(Duration::from_millis(800)).await;
    assert_eq!(
        provider.requests().await.len(),
        1,
        "a cancelled review must not leave a detached provider retry running"
    );
    assert_eq!(client.review(fixture.packet()?).await, Ok(Verdict::Pass));

    client.shutdown().await?;
    let (status, _, _) = service.finish().await?;
    assert!(status.success(), "cloud service failed: {status}");
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn shutdown_during_an_in_flight_provider_call_exits_within_its_bounded_budget() -> TestResult
{
    let provider = FakeProvider::start().await;
    let options = DescriptorOptions {
        job_timeout: Duration::from_millis(4_000),
        request_timeout: Duration::from_millis(3_000),
        max_attempts: 1,
        retry_backoff: Duration::ZERO,
        ..DescriptorOptions::default()
    };
    provider
        .mount(
            ResponseTemplate::new(200)
                .set_body_json(completion(PROVIDER_MODEL, r#"{"quality":0.83}"#))
                .set_delay(Duration::from_secs(30)),
        )
        .await;
    let fixture = Fixture::new(&provider.base_url(), options)?;
    let service = CloudService::spawn(&fixture, Duration::from_millis(300)).await?;
    let client = service.client(Duration::from_secs(8))?;

    let review = tokio::spawn({
        let client = client.clone();
        let packet = fixture.packet()?;
        async move { client.review(packet).await }
    });
    provider.wait_for_requests(1).await?;

    // A second client issues the shutdown so the in-flight review is not short-circuited by the
    // caller's own shutting-down flag.
    let started = Instant::now();
    service.client(Duration::from_secs(5))?.shutdown().await?;
    assert_eq!(
        timeout(PROCESS_TIMEOUT, review).await??,
        Err(CriticFailure::Infrastructure(
            InfrastructureFailure::ShuttingDown
        ))
    );
    let (status, _, _) = service.finish().await?;
    assert!(status.success(), "cloud service failed: {status}");
    assert!(
        started.elapsed() < options.request_timeout,
        "forced shutdown did not preempt the in-flight provider call"
    );
    assert_eq!(
        provider.requests().await.len(),
        1,
        "no provider work continued after shutdown"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn the_launcher_fails_closed_before_it_can_reach_a_provider() -> TestResult {
    let provider = FakeProvider::start().await;
    provider.mount_quality(/*quality*/ 0.83).await;
    let fixture = Fixture::new(&provider.base_url(), DescriptorOptions::default())?;

    // No credential: the launcher must exit instead of serving an unusable backend.
    let mut command = Command::new(cargo_bin("codex-publication-critic-cloud-service")?);
    command
        .arg("--descriptor")
        .arg(&fixture.descriptor_path)
        .env_remove(API_KEY_ENV)
        .stdin(Stdio::null());
    let missing_credential = timeout(PROCESS_TIMEOUT, command.output()).await??;
    assert!(!missing_credential.status.success());
    assert!(missing_credential.stdout.is_empty());

    // A descriptor that claims an exact tokenizer revision is rejected as dishonest.
    let mut dishonest: Value = serde_json::from_slice(&std::fs::read(&fixture.descriptor_path)?)?;
    dishonest["service_descriptor"]["identity"]["model"]["tokenizer"] =
        json!({"name": "qwen3-tokenizer", "revision": "9f2c1a"});
    let dishonest_path = fixture.root.join("dishonest-descriptor.json");
    std::fs::write(&dishonest_path, serde_json::to_vec(&dishonest)?)?;
    let mut command = Command::new(cargo_bin("codex-publication-critic-cloud-service")?);
    command
        .arg("--descriptor")
        .arg(&dishonest_path)
        .env(API_KEY_ENV, API_KEY)
        .stdin(Stdio::null());
    let rejected = timeout(PROCESS_TIMEOUT, command.output()).await??;
    assert!(!rejected.status.success());
    assert!(rejected.stdout.is_empty());

    assert!(
        provider.requests().await.is_empty(),
        "a failed launch must not reach the provider"
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn a_non_cloud_backend_needs_no_cloud_credential_and_stays_offline() -> TestResult {
    let provider = FakeProvider::start().await;
    provider.mount_quality(/*quality*/ 0.83).await;

    let expected = controlled_test_descriptor(RuntimeLimits::new(
        32 * 1024,
        16 * 1024,
        /*max_concurrency*/ 1,
        /*queue_capacity*/ 4,
        Duration::from_millis(2_000),
        IO_TIMEOUT,
    )?);
    let mut command = Command::new(cargo_bin("codex-publication-critic-service")?);
    command
        .arg("--job-timeout-ms")
        .arg("2000")
        .arg("--io-timeout-ms")
        .arg(IO_TIMEOUT.as_millis().to_string())
        .arg("--request-bytes")
        .arg((32 * 1024).to_string())
        .arg("--response-bytes")
        .arg((16 * 1024).to_string())
        .env_remove(API_KEY_ENV)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    let mut child = command.spawn()?;
    let mut stdout = BufReader::new(child.stdout.take().ok_or("stdout was not piped")?);
    let mut line = String::new();
    timeout(PROCESS_TIMEOUT, stdout.read_line(&mut line))
        .await
        .map_err(|_| "controlled service announcement timed out")??;
    let announcement: StartupAnnouncement = serde_json::from_str(line.trim_end())?;
    assert_eq!(announcement.descriptor, expected);

    let client = PublicationCriticClient::new(ClientConfig::new(
        announcement.endpoint,
        expected.clone(),
        Duration::from_secs(5),
        Duration::from_secs(5),
    )?)?;
    client.wait_until_ready(CancellationToken::new()).await?;
    assert_eq!(
        client.review(test_packet(&expected)?).await,
        Ok(Verdict::Pass)
    );
    client.shutdown().await?;
    let status = timeout(PROCESS_TIMEOUT, child.wait()).await??;
    assert!(status.success(), "controlled service failed: {status}");

    assert!(
        provider.requests().await.is_empty(),
        "a non-cloud backend must not send provider traffic"
    );
    Ok(())
}
