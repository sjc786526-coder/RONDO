#![allow(clippy::expect_used)]

use codex_publication_critic::ActorRole;
use codex_publication_critic::ClientConfig;
use codex_publication_critic::ContinuityContext;
use codex_publication_critic::ContractFailure;
use codex_publication_critic::CriticFailure;
use codex_publication_critic::IdentityField;
use codex_publication_critic::InfrastructureFailure;
use codex_publication_critic::LocalScope;
use codex_publication_critic::ProtocolVersion;
use codex_publication_critic::PublicationCandidate;
use codex_publication_critic::PublicationCriticClient;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::ScoreFailureKind;
use codex_publication_critic::ServiceDescriptor;
use codex_publication_critic::ServicePhase;
use codex_publication_critic::StartupAnnouncement;
use codex_publication_critic::TargetKind;
use codex_publication_critic::Verdict;
use codex_publication_critic::controlled_test_descriptor;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::process::ExitStatus;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::TcpSocket;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::Command;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

const BODY_SENTINEL: &str = "RONDO_PUBLICATION_BODY_SENTINEL_055";
const PROCESS_DEADLINE: Duration = Duration::from_secs(3);
const IO_TIMEOUT: Duration = Duration::from_millis(800);
const CALL_TIMEOUT: Duration = Duration::from_millis(800);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(2);
const GRACEFUL_SHUTDOWN_TIMEOUT: Duration = Duration::from_millis(500);

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

#[derive(Clone, Copy)]
struct TestRuntime {
    job_timeout: Duration,
}

impl TestRuntime {
    fn normal() -> Self {
        Self {
            job_timeout: Duration::from_millis(600),
        }
    }

    fn short_job_timeout() -> Self {
        Self {
            job_timeout: Duration::from_millis(120),
        }
    }

    fn limits(self) -> RuntimeLimits {
        RuntimeLimits::new(
            32 * 1024,
            16 * 1024,
            /*max_concurrency*/ 1,
            /*queue_capacity*/ 4,
            self.job_timeout,
            IO_TIMEOUT,
        )
        .expect("controlled test runtime is valid")
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
    stdout: Arc<Mutex<Vec<String>>>,
    stderr: Arc<Mutex<Vec<String>>>,
    stderr_lines: mpsc::UnboundedReceiver<String>,
    stdout_task: JoinHandle<()>,
    stderr_task: JoinHandle<()>,
}

impl ServiceProcess {
    async fn spawn(
        behavior: &str,
        score: f64,
        initially_unready: bool,
        runtime: TestRuntime,
    ) -> TestResult<Self> {
        let limits = runtime.limits();
        let expected = controlled_test_descriptor(limits.clone());
        let mut command = Command::new(codex_utils_cargo_bin::cargo_bin(
            "codex-publication-critic-service",
        )?);
        command
            .arg("--behavior")
            .arg(behavior)
            .arg("--score")
            .arg(score.to_string())
            .arg("--request-bytes")
            .arg(limits.request_bytes().to_string())
            .arg("--response-bytes")
            .arg(limits.response_bytes().to_string())
            .arg("--max-concurrency")
            .arg(limits.max_concurrency().to_string())
            .arg("--queue-capacity")
            .arg(limits.queue_capacity().to_string())
            .arg("--job-timeout-ms")
            .arg(limits.job_timeout_ms().to_string())
            .arg("--io-timeout-ms")
            .arg(limits.io_timeout_ms().to_string())
            .arg("--graceful-shutdown-ms")
            .arg(
                u64::try_from(GRACEFUL_SHUTDOWN_TIMEOUT.as_millis())
                    .expect("test timeout fits in u64")
                    .to_string(),
            )
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        if initially_unready {
            command.arg("--initially-unready");
        }

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
        assert_eq!(
            announcement.protocol,
            ProtocolVersion::RondoPublicationCriticV1
        );
        assert!(announcement.endpoint.ip().is_loopback());
        assert_ne!(announcement.endpoint.port(), 0);
        assert_eq!(announcement.descriptor, expected);

        let stdout_capture = Arc::new(Mutex::new(vec![startup_line.trim_end().to_string()]));
        let stdout_for_task = Arc::clone(&stdout_capture);
        let stdout_task = tokio::spawn(async move {
            let mut remainder = String::new();
            let _ = stdout_reader.read_to_string(&mut remainder).await;
            if !remainder.is_empty() {
                stdout_for_task
                    .lock()
                    .expect("stdout capture lock is not poisoned")
                    .push(remainder);
            }
        });

        let stderr_capture = Arc::new(Mutex::new(Vec::new()));
        let stderr_for_task = Arc::clone(&stderr_capture);
        let (stderr_tx, stderr_lines) = mpsc::unbounded_channel();
        let stderr_task = tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                stderr_for_task
                    .lock()
                    .expect("stderr capture lock is not poisoned")
                    .push(line.clone());
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

    fn client(&self) -> PublicationCriticClient {
        self.client_with_timeouts(CALL_TIMEOUT, STARTUP_TIMEOUT)
    }

    fn client_with_timeouts(
        &self,
        call_timeout: Duration,
        startup_timeout: Duration,
    ) -> PublicationCriticClient {
        PublicationCriticClient::new(
            ClientConfig::new(
                self.endpoint,
                self.expected.clone(),
                call_timeout,
                startup_timeout,
            )
            .expect("controlled client configuration is valid"),
        )
        .expect("validated client configuration must be accepted")
    }

    fn packet(&self) -> PublicationPacket {
        packet_for(&self.expected)
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

    async fn finish(mut self) -> TestResult<CapturedProcess> {
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
        let stdout = self
            .stdout
            .lock()
            .expect("stdout capture lock is not poisoned")
            .join("\n");
        let stderr = self
            .stderr
            .lock()
            .expect("stderr capture lock is not poisoned")
            .join("\n");
        Ok(CapturedProcess {
            status,
            stdout,
            stderr,
        })
    }
}

#[tokio::test(flavor = "current_thread")]
async fn real_process_transport_returns_pass_and_rewrite_and_reaps_cleanly() -> TestResult {
    for (score, expected_verdict) in [(0.75, Verdict::Pass), (0.25, Verdict::Rewrite)] {
        let service = ServiceProcess::spawn(
            "fixed",
            score,
            /*initially_unready*/ false,
            TestRuntime::normal(),
        )
        .await?;
        let client = service.client();
        client.wait_until_ready(CancellationToken::new()).await?;
        assert_eq!(client.review(service.packet()).await?, expected_verdict);
        client.shutdown().await?;

        let captured = service.finish().await?;
        assert!(
            captured.status.success(),
            "service exit: {}",
            captured.status
        );
        assert_body_is_redacted(&captured.stdout, &captured.stderr, &[]);
        assert!(
            captured
                .stderr
                .contains("publication_critic_service_stopped")
        );
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn initially_unready_process_becomes_ready_via_stdin_control() -> TestResult {
    let mut service = ServiceProcess::spawn(
        "fixed",
        /*score*/ 0.75,
        /*initially_unready*/ true,
        TestRuntime::normal(),
    )
    .await?;
    let client = service.client();
    assert_eq!(client.readiness().await?.phase, ServicePhase::Starting);
    assert_eq!(
        client.review(service.packet()).await,
        Err(CriticFailure::Infrastructure(
            InfrastructureFailure::NotReady
        ))
    );

    let wait_client = client.clone();
    let ready =
        tokio::spawn(async move { wait_client.wait_until_ready(CancellationToken::new()).await });
    service.send_command("ready").await?;
    ready.await??;
    assert_eq!(client.review(service.packet()).await?, Verdict::Pass);
    client.shutdown().await?;

    let captured = service.finish().await?;
    assert!(
        captured.status.success(),
        "service exit: {}",
        captured.status
    );
    assert_body_is_redacted(&captured.stdout, &captured.stderr, &[]);
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn server_job_timeout_cancels_blocked_backend_and_next_call_recovers() -> TestResult {
    let mut service = ServiceProcess::spawn(
        "block-first",
        /*score*/ 0.75,
        /*initially_unready*/ false,
        TestRuntime::short_job_timeout(),
    )
    .await?;
    let client = service.client();
    let packet = service.packet();
    let review_client = client.clone();
    let review = tokio::spawn(async move { review_client.review(packet).await });

    service
        .wait_for_stderr("controlled_scorer_entered call=1")
        .await?;
    let failure = review.await?.expect_err("blocked review must time out");
    assert_eq!(
        failure,
        CriticFailure::Infrastructure(InfrastructureFailure::CallTimeout)
    );
    service
        .wait_for_stderr("controlled_scorer_cancelled call=1")
        .await?;
    service.send_command("release").await?;
    assert_eq!(client.review(service.packet()).await?, Verdict::Pass);
    client.shutdown().await?;

    let captured = service.finish().await?;
    assert!(
        captured.status.success(),
        "service exit: {}",
        captured.status
    );
    assert_body_is_redacted(
        &captured.stdout,
        &captured.stderr,
        &[format!("{failure:?}"), failure.to_string()],
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn explicit_cancellation_disconnects_blocked_call_and_next_call_recovers() -> TestResult {
    let mut service = ServiceProcess::spawn(
        "block-first",
        /*score*/ 0.75,
        /*initially_unready*/ false,
        TestRuntime::normal(),
    )
    .await?;
    let client = service.client();
    let packet = service.packet();
    let cancellation = CancellationToken::new();
    let request_cancellation = cancellation.clone();
    let review_client = client.clone();
    let review = tokio::spawn(async move {
        review_client
            .review_with_cancellation(packet, request_cancellation)
            .await
    });

    service
        .wait_for_stderr("controlled_scorer_entered call=1")
        .await?;
    cancellation.cancel();
    let failure = review
        .await?
        .expect_err("explicitly cancelled review must fail");
    assert_eq!(failure, CriticFailure::Cancelled);
    service
        .wait_for_stderr("controlled_scorer_cancelled call=1")
        .await?;
    service.send_command("release").await?;
    assert_eq!(client.review(service.packet()).await?, Verdict::Pass);
    client.shutdown().await?;

    let packet_debug = format!("{:?}", service.packet());
    let captured = service.finish().await?;
    assert!(
        captured.status.success(),
        "service exit: {}",
        captured.status
    );
    assert_body_is_redacted(
        &captured.stdout,
        &captured.stderr,
        &[packet_debug, format!("{failure:?}"), failure.to_string()],
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn shutdown_forces_a_blocked_backend_and_reaps_the_process() -> TestResult {
    let mut service = ServiceProcess::spawn(
        "block-first",
        /*score*/ 0.75,
        /*initially_unready*/ false,
        TestRuntime::normal(),
    )
    .await?;
    let client = service.client();
    let other_client = service.client();
    let review_client = client.clone();
    let packet = service.packet();
    let review = tokio::spawn(async move { review_client.review(packet).await });

    service
        .wait_for_stderr("controlled_scorer_entered call=1")
        .await?;
    client.shutdown().await?;
    let rejected = other_client
        .review(service.packet())
        .await
        .expect_err("draining service must not accept new work");
    assert!(matches!(
        rejected,
        CriticFailure::Infrastructure(
            InfrastructureFailure::ShuttingDown | InfrastructureFailure::Connect
        )
    ));

    let interrupted = timeout(PROCESS_DEADLINE, review)
        .await
        .map_err(|_| "blocked review outlived the force-shutdown deadline")??
        .expect_err("force shutdown must not produce a verdict");
    assert!(matches!(
        interrupted,
        CriticFailure::Infrastructure(
            InfrastructureFailure::ShuttingDown | InfrastructureFailure::Disconnected
        )
    ));
    service
        .wait_for_stderr("controlled_scorer_cancelled call=1")
        .await?;

    let captured = service.finish().await?;
    assert!(
        captured.status.success(),
        "service exit: {}",
        captured.status
    );
    assert_body_is_redacted(
        &captured.stdout,
        &captured.stderr,
        &[
            format!("{rejected:?}"),
            rejected.to_string(),
            format!("{interrupted:?}"),
            interrupted.to_string(),
        ],
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn controlled_backend_faults_are_typed_and_the_next_call_recovers() -> TestResult {
    let cases = [
        (
            "backend-failure-first",
            CriticFailure::Infrastructure(InfrastructureFailure::Backend),
        ),
        (
            "nan-first",
            CriticFailure::Contract(ContractFailure::InvalidScore(ScoreFailureKind::NonFinite)),
        ),
        (
            "positive-infinity-first",
            CriticFailure::Contract(ContractFailure::InvalidScore(ScoreFailureKind::NonFinite)),
        ),
        (
            "negative-infinity-first",
            CriticFailure::Contract(ContractFailure::InvalidScore(ScoreFailureKind::NonFinite)),
        ),
        (
            "multi-score-first",
            CriticFailure::Contract(ContractFailure::InvalidScore(ScoreFailureKind::Shape)),
        ),
        (
            "model-drift-first",
            CriticFailure::Contract(ContractFailure::IdentityMismatch(IdentityField::Model)),
        ),
        (
            "scoring-drift-first",
            CriticFailure::Contract(ContractFailure::IdentityMismatch(IdentityField::Scoring)),
        ),
    ];

    for (behavior, expected_failure) in cases {
        let service = ServiceProcess::spawn(
            behavior,
            /*score*/ 0.75,
            /*initially_unready*/ false,
            TestRuntime::normal(),
        )
        .await?;
        let client = service.client();
        let failure = client
            .review(service.packet())
            .await
            .expect_err("the first controlled call must fail");
        assert_eq!(failure, expected_failure, "behavior: {behavior}");
        assert_eq!(client.review(service.packet()).await?, Verdict::Pass);
        client.shutdown().await?;

        let captured = service.finish().await?;
        assert!(
            captured.status.success(),
            "service exit for {behavior}: {}",
            captured.status
        );
        assert_body_is_redacted(
            &captured.stdout,
            &captured.stderr,
            &[format!("{failure:?}"), failure.to_string()],
        );
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn out_of_domain_score_is_a_typed_contract_failure() -> TestResult {
    let service = ServiceProcess::spawn(
        "fixed",
        /*score*/ 1.25,
        /*initially_unready*/ false,
        TestRuntime::normal(),
    )
    .await?;
    let client = service.client();
    let failure = client
        .review(service.packet())
        .await
        .expect_err("out-of-domain score must not become a verdict");
    assert_eq!(
        failure,
        CriticFailure::Contract(ContractFailure::InvalidScore(ScoreFailureKind::OutOfDomain))
    );
    client.shutdown().await?;

    let captured = service.finish().await?;
    assert!(
        captured.status.success(),
        "service exit: {}",
        captured.status
    );
    assert_body_is_redacted(
        &captured.stdout,
        &captured.stderr,
        &[format!("{failure:?}"), failure.to_string()],
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn connection_refusal_is_a_typed_infrastructure_failure() -> TestResult {
    let unavailable_socket = TcpSocket::new_v4()?;
    unavailable_socket.bind("127.0.0.1:0".parse()?)?;
    let endpoint = unavailable_socket.local_addr()?;
    let expected = controlled_test_descriptor(TestRuntime::normal().limits());
    let client = PublicationCriticClient::new(ClientConfig::new(
        endpoint,
        expected.clone(),
        CALL_TIMEOUT,
        STARTUP_TIMEOUT,
    )?)?;
    let packet = packet_for(&expected);

    let failure = client
        .review(packet.clone())
        .await
        .expect_err("bound non-listening socket must refuse the connection");
    assert_eq!(
        failure,
        CriticFailure::Infrastructure(InfrastructureFailure::Connect)
    );
    assert_body_is_redacted(
        "",
        "",
        &[
            format!("{packet:?}"),
            format!("{failure:?}"),
            failure.to_string(),
        ],
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn initially_unready_process_reports_typed_startup_timeout_then_recovers() -> TestResult {
    let mut service = ServiceProcess::spawn(
        "fixed",
        /*score*/ 0.75,
        /*initially_unready*/ true,
        TestRuntime::normal(),
    )
    .await?;
    let client = service.client_with_timeouts(CALL_TIMEOUT, Duration::from_millis(120));
    let failure = client
        .wait_until_ready(CancellationToken::new())
        .await
        .expect_err("persistently unready service must reach the startup deadline");
    assert_eq!(
        failure,
        CriticFailure::Infrastructure(InfrastructureFailure::StartupTimeout)
    );

    service.send_command("ready").await?;
    client.wait_until_ready(CancellationToken::new()).await?;
    assert_eq!(client.review(service.packet()).await?, Verdict::Pass);
    client.shutdown().await?;

    let captured = service.finish().await?;
    assert!(
        captured.status.success(),
        "service exit: {}",
        captured.status
    );
    assert_body_is_redacted(
        &captured.stdout,
        &captured.stderr,
        &[format!("{failure:?}"), failure.to_string()],
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn abnormal_process_exit_is_reaped_then_client_reports_connection_failure() -> TestResult {
    let mut service = ServiceProcess::spawn(
        "fixed",
        /*score*/ 0.75,
        /*initially_unready*/ false,
        TestRuntime::normal(),
    )
    .await?;
    let client = service.client();
    let packet = service.packet();
    assert_eq!(client.review(packet.clone()).await?, Verdict::Pass);

    service.send_command("exit").await?;
    let captured = service.finish().await?;
    assert_eq!(captured.status.code(), Some(86));
    let failure = client
        .review(packet.clone())
        .await
        .expect_err("a reaped service cannot accept another review");
    assert_eq!(
        failure,
        CriticFailure::Infrastructure(InfrastructureFailure::Connect)
    );
    assert_body_is_redacted(
        &captured.stdout,
        &captured.stderr,
        &[
            format!("{packet:?}"),
            format!("{failure:?}"),
            failure.to_string(),
        ],
    );
    Ok(())
}

fn packet_for(expected: &ServiceDescriptor) -> PublicationPacket {
    PublicationPacket::new(
        expected.identity.qualification.clone(),
        ActorRole::Root,
        TargetKind::NewEvent,
        LocalScope::new(format!("private scope {BODY_SENTINEL}")).expect("test title is valid"),
        PublicationCandidate::new(format!("private candidate {BODY_SENTINEL}"))
            .expect("test candidate is valid")
            .with_handoff(format!("private handoff {BODY_SENTINEL}"))
            .expect("test handoff is valid"),
        ContinuityContext::NotApplicable,
    )
    .expect("test packet is valid")
}

fn assert_body_is_redacted(stdout: &str, stderr: &str, rendered_values: &[String]) {
    for (label, value) in [("stdout", stdout), ("stderr", stderr)] {
        assert!(
            !value.contains(BODY_SENTINEL),
            "{label} exposed the publication body sentinel: {value}"
        );
    }
    for value in rendered_values {
        assert!(
            !value.contains(BODY_SENTINEL),
            "Debug/Display exposed the publication body sentinel: {value}"
        );
    }
}
