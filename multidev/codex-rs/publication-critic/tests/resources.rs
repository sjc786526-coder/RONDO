#![allow(clippy::expect_used)]

use codex_publication_critic::ActorRole;
use codex_publication_critic::ClientConfig;
use codex_publication_critic::ContinuityContext;
use codex_publication_critic::CriticFailure;
use codex_publication_critic::InfrastructureFailure;
use codex_publication_critic::LocalScope;
use codex_publication_critic::ProtocolVersion;
use codex_publication_critic::PublicationCandidate;
use codex_publication_critic::PublicationCriticClient;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::ServiceDescriptor;
use codex_publication_critic::ServicePhase;
use codex_publication_critic::StartupAnnouncement;
use codex_publication_critic::TargetKind;
use codex_publication_critic::Verdict;
use codex_publication_critic::controlled_test_descriptor;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::io;
use std::process::Stdio;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::process::Child;
use tokio::process::ChildStdin;
use tokio::process::Command;
use tokio::sync::mpsc;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

const TEST_DEADLINE: Duration = Duration::from_secs(8);
const PROCESS_DEADLINE: Duration = Duration::from_secs(3);
const OBSERVATION_DEADLINE: Duration = Duration::from_secs(2);
const IMMEDIATE_RESPONSE_DEADLINE: Duration = Duration::from_secs(1);
const CALL_TIMEOUT: Duration = Duration::from_secs(6);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(2);

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

struct ServiceProcess {
    child: Child,
    stdin: Option<ChildStdin>,
    endpoint: std::net::SocketAddr,
    expected: ServiceDescriptor,
    stderr_lines: mpsc::UnboundedReceiver<String>,
    stdout_task: JoinHandle<()>,
    stderr_task: JoinHandle<()>,
}

impl ServiceProcess {
    async fn spawn() -> TestResult<Self> {
        let limits = RuntimeLimits::new(
            32 * 1024,
            16 * 1024,
            /*max_concurrency*/ 1,
            /*queue_capacity*/ 4,
            Duration::from_secs(10),
            Duration::from_secs(1),
        )?;
        let expected = controlled_test_descriptor(limits.clone());
        let mut command = Command::new(codex_utils_cargo_bin::cargo_bin(
            "codex-publication-critic-service",
        )?);
        command
            .arg("--behavior")
            .arg("block-first")
            .arg("--affected-calls")
            .arg("1")
            .arg("--score")
            .arg("0.75")
            .arg("--request-bytes")
            .arg(limits.request_bytes.to_string())
            .arg("--response-bytes")
            .arg(limits.response_bytes.to_string())
            .arg("--max-concurrency")
            .arg(limits.max_concurrency.to_string())
            .arg("--queue-capacity")
            .arg(limits.queue_capacity.to_string())
            .arg("--job-timeout-ms")
            .arg(limits.job_timeout_ms.to_string())
            .arg("--io-timeout-ms")
            .arg(limits.io_timeout_ms.to_string())
            .arg("--graceful-shutdown-ms")
            .arg("500")
            .arg("--force-shutdown-ms")
            .arg("500")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);

        let mut child = command.spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| test_error("missing stdin"))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| test_error("missing stdout"))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| test_error("missing stderr"))?;

        let mut stdout_reader = BufReader::new(stdout);
        let mut startup_line = String::new();
        let bytes_read = timeout(PROCESS_DEADLINE, stdout_reader.read_line(&mut startup_line))
            .await
            .map_err(|_| test_error("timed out waiting for startup announcement"))??;
        if bytes_read == 0 {
            return Err(test_error("service exited before startup announcement").into());
        }
        let announcement: StartupAnnouncement = serde_json::from_str(startup_line.trim_end())?;
        assert_eq!(
            announcement.protocol,
            ProtocolVersion::RondoPublicationCriticV1
        );
        assert!(announcement.endpoint.ip().is_loopback());
        assert_ne!(announcement.endpoint.port(), 0);
        assert_eq!(announcement.descriptor, expected);

        let stdout_task = tokio::spawn(async move {
            let mut remainder = Vec::new();
            let _ = stdout_reader.read_to_end(&mut remainder).await;
        });
        let (stderr_tx, stderr_lines) = mpsc::unbounded_channel();
        let stderr_task = tokio::spawn(async move {
            let mut lines = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = lines.next_line().await {
                let _ = stderr_tx.send(line);
            }
        });

        let mut service = Self {
            child,
            stdin: Some(stdin),
            endpoint: announcement.endpoint,
            expected,
            stderr_lines,
            stdout_task,
            stderr_task,
        };
        service
            .wait_for_stderr("publication_critic_service_listening")
            .await?;
        Ok(service)
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
    }

    fn packet(&self) -> PublicationPacket {
        PublicationPacket::new(
            self.expected.identity.qualification.clone(),
            ActorRole::Root,
            TargetKind::NewEvent,
            LocalScope::new("resource gate scope").expect("scope is valid"),
            PublicationCandidate::new("resource gate candidate").expect("candidate is valid"),
            ContinuityContext::NotApplicable,
        )
        .expect("controlled packet is valid")
    }

    async fn send_command(&mut self, command: &str) -> TestResult {
        let stdin = self
            .stdin
            .as_mut()
            .ok_or_else(|| test_error("service stdin is closed"))?;
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
            Err(test_error("stderr closed before expected barrier").into())
        })
        .await
        .map_err(|_| test_error("timed out waiting for stderr barrier"))?
    }

    async fn finish(mut self) -> TestResult {
        drop(self.stdin.take());
        let status = timeout(PROCESS_DEADLINE, self.child.wait())
            .await
            .map_err(|_| test_error("timed out waiting for service exit"))??;
        if !status.success() {
            return Err(test_error(format!("service exited with {status}")).into());
        }
        timeout(PROCESS_DEADLINE, self.stdout_task)
            .await
            .map_err(|_| test_error("timed out draining stdout"))??;
        timeout(PROCESS_DEADLINE, self.stderr_task)
            .await
            .map_err(|_| test_error("timed out draining stderr"))??;
        Ok(())
    }
}

async fn wait_for_counts(
    client: &PublicationCriticClient,
    expected_in_flight: u16,
    expected_queued: u16,
) -> TestResult {
    timeout(OBSERVATION_DEADLINE, async {
        loop {
            let status = client.liveness().await?;
            if status.phase == ServicePhase::Ready
                && status.in_flight == expected_in_flight
                && status.queued == expected_queued
            {
                return Ok::<(), CriticFailure>(());
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .map_err(|_| {
        test_error(format!(
            "timed out waiting for resource counts in_flight={expected_in_flight} queued={expected_queued}"
        ))
    })??;
    Ok(())
}

fn test_error(message: impl Into<String>) -> io::Error {
    io::Error::other(message.into())
}

#[tokio::test(flavor = "current_thread")]
async fn one_active_four_queued_reserves_control_lane_and_rejects_overflow() -> TestResult {
    timeout(TEST_DEADLINE, resource_capacity_scenario())
        .await
        .map_err(|_| test_error("resource capacity scenario exceeded its hard deadline"))?
}

async fn resource_capacity_scenario() -> TestResult {
    let mut service = ServiceProcess::spawn().await?;
    let client = service.client();
    client.wait_until_ready(CancellationToken::new()).await?;

    let active_client = client.clone();
    let active_packet = service.packet();
    let active = tokio::spawn(async move { active_client.review(active_packet).await });
    service
        .wait_for_stderr("controlled_scorer_entered call=1")
        .await?;

    let mut queued = Vec::new();
    for _ in 0..4 {
        let queued_client = client.clone();
        let queued_packet = service.packet();
        queued.push(tokio::spawn(async move {
            queued_client.review(queued_packet).await
        }));
    }

    wait_for_counts(
        &client, /*expected_in_flight*/ 1, /*expected_queued*/ 4,
    )
    .await?;
    let overflow = timeout(IMMEDIATE_RESPONSE_DEADLINE, client.review(service.packet()))
        .await
        .map_err(|_| test_error("queue overflow did not fail immediately"))?
        .expect_err("the sixth concurrent review must be rejected");
    assert_eq!(
        overflow,
        CriticFailure::Infrastructure(InfrastructureFailure::QueueFull)
    );

    service.send_command("release").await?;
    assert_eq!(active.await??, Verdict::Pass);
    for queued_review in queued {
        assert_eq!(queued_review.await??, Verdict::Pass);
    }
    wait_for_counts(
        &client, /*expected_in_flight*/ 0, /*expected_queued*/ 0,
    )
    .await?;
    assert_eq!(client.review(service.packet()).await?, Verdict::Pass);

    client.shutdown().await?;
    service.finish().await
}

#[tokio::test(flavor = "current_thread")]
async fn cancelling_a_queued_review_releases_its_queue_slot() -> TestResult {
    timeout(TEST_DEADLINE, queued_cancellation_scenario())
        .await
        .map_err(|_| test_error("queued cancellation scenario exceeded its hard deadline"))?
}

async fn queued_cancellation_scenario() -> TestResult {
    let mut service = ServiceProcess::spawn().await?;
    let client = service.client();
    client.wait_until_ready(CancellationToken::new()).await?;

    let active_client = client.clone();
    let active_packet = service.packet();
    let active = tokio::spawn(async move { active_client.review(active_packet).await });
    service
        .wait_for_stderr("controlled_scorer_entered call=1")
        .await?;

    let cancellation = CancellationToken::new();
    let queued_cancellation = cancellation.clone();
    let queued_client = client.clone();
    let queued_packet = service.packet();
    let queued = tokio::spawn(async move {
        queued_client
            .review_with_cancellation(queued_packet, queued_cancellation)
            .await
    });
    wait_for_counts(
        &client, /*expected_in_flight*/ 1, /*expected_queued*/ 1,
    )
    .await?;

    cancellation.cancel();
    let cancelled = timeout(IMMEDIATE_RESPONSE_DEADLINE, queued)
        .await
        .map_err(|_| test_error("queued cancellation was not observed immediately"))??
        .expect_err("cancelled queued review must fail");
    assert_eq!(cancelled, CriticFailure::Cancelled);
    wait_for_counts(
        &client, /*expected_in_flight*/ 1, /*expected_queued*/ 0,
    )
    .await?;

    service.send_command("release").await?;
    assert_eq!(active.await??, Verdict::Pass);
    assert_eq!(client.review(service.packet()).await?, Verdict::Pass);

    client.shutdown().await?;
    service.finish().await
}
