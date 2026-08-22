#![allow(clippy::expect_used)]

use codex_publication_critic::ActorRole;
use codex_publication_critic::ClientConfig;
use codex_publication_critic::ContinuityContext;
use codex_publication_critic::ContractFailure;
use codex_publication_critic::CriticFailure;
use codex_publication_critic::LocalScope;
use codex_publication_critic::ProtocolVersion;
use codex_publication_critic::PublicationCandidate;
use codex_publication_critic::PublicationCriticClient;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::ServiceDescriptor;
use codex_publication_critic::StartupAnnouncement;
use codex_publication_critic::TargetKind;
use codex_publication_critic::Verdict;
use codex_publication_critic::controlled_test_descriptor;
use serde_json::Value;
use serde_json::json;
use std::error::Error;
use std::net::SocketAddr;
use std::process::Stdio;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::TcpStream;
use tokio::process::Child;
use tokio::process::Command;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

const PROCESS_TIMEOUT: Duration = Duration::from_secs(3);
const CALL_TIMEOUT: Duration = Duration::from_secs(1);
const STARTUP_TIMEOUT: Duration = Duration::from_secs(2);
const REQUEST_BYTES: u32 = 4 * 1024;
const RESPONSE_BYTES: u32 = 4 * 1024;

type TestResult<T = ()> = Result<T, Box<dyn Error + Send + Sync>>;

struct ServiceProcess {
    child: Child,
    endpoint: SocketAddr,
    expected: ServiceDescriptor,
}

impl ServiceProcess {
    async fn spawn() -> TestResult<Self> {
        let limits = RuntimeLimits::new(
            REQUEST_BYTES,
            RESPONSE_BYTES,
            /*max_concurrency*/ 1,
            /*queue_capacity*/ 2,
            Duration::from_millis(500),
            Duration::from_millis(500),
        )?;
        let expected = controlled_test_descriptor(limits.clone());
        let mut command = Command::new(codex_utils_cargo_bin::cargo_bin(
            "codex-publication-critic-service",
        )?);
        command
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
            .arg("500")
            .arg("--force-shutdown-ms")
            .arg("500")
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .kill_on_drop(true);

        let mut child = command.spawn()?;
        let stdout = child.stdout.take().ok_or("service stdout was not piped")?;
        let mut stdout = BufReader::new(stdout);
        let mut startup_line = String::new();
        let bytes_read = timeout(PROCESS_TIMEOUT, stdout.read_line(&mut startup_line))
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

        Ok(Self {
            child,
            endpoint: announcement.endpoint,
            expected,
        })
    }

    fn client(&self) -> PublicationCriticClient {
        PublicationCriticClient::new(
            ClientConfig::new(
                self.endpoint,
                self.expected.clone(),
                CALL_TIMEOUT,
                STARTUP_TIMEOUT,
            )
            .expect("controlled client configuration must be valid"),
        )
        .expect("validated client configuration must be accepted")
    }

    async fn finish(mut self) -> TestResult {
        let status = timeout(PROCESS_TIMEOUT, self.child.wait())
            .await
            .map_err(|_| "timed out waiting for service process exit")??;
        assert!(status.success(), "service exit: {status}");
        Ok(())
    }
}

fn packet(expected: &ServiceDescriptor) -> PublicationPacket {
    PublicationPacket::new(
        expected.identity.qualification.clone(),
        ActorRole::Root,
        TargetKind::NewEvent,
        LocalScope::new("ingress contract test").expect("test scope must be valid"),
        PublicationCandidate::new("controlled ingress candidate")
            .expect("test candidate must be valid"),
        ContinuityContext::NotApplicable,
    )
    .expect("test packet must be valid")
}

fn raw_review(expected: &ServiceDescriptor, packet: &PublicationPacket) -> Value {
    json!({
        "protocol": "rondo_publication_critic_v1",
        "request": {
            "type": "review",
            "data": {
                "expected": expected,
                "packet": packet,
            }
        }
    })
}

async fn read_raw_frame(stream: &mut TcpStream) -> TestResult<Vec<u8>> {
    let mut prefix = [0_u8; 4];
    timeout(CALL_TIMEOUT, stream.read_exact(&mut prefix))
        .await
        .map_err(|_| "timed out waiting for raw response prefix")??;
    let body_len = usize::try_from(u32::from_be_bytes(prefix))?;
    assert!(body_len <= usize::try_from(RESPONSE_BYTES)?);
    let mut body = vec![0_u8; body_len];
    timeout(CALL_TIMEOUT, stream.read_exact(&mut body))
        .await
        .map_err(|_| "timed out waiting for raw response body")??;
    Ok(body)
}

async fn assert_raw_failure(
    endpoint: SocketAddr,
    expected: &ServiceDescriptor,
    body: Option<&[u8]>,
    announced_len: u32,
    expected_code: &str,
) -> TestResult {
    let mut stream = TcpStream::connect(endpoint).await?;
    stream.write_all(&announced_len.to_be_bytes()).await?;
    if let Some(body) = body {
        assert_eq!(u32::try_from(body.len())?, announced_len);
        stream.write_all(body).await?;
        stream.flush().await?;
    }

    let response: Value = serde_json::from_slice(&read_raw_frame(&mut stream).await?)?;
    assert_eq!(response["protocol"], json!("rondo_publication_critic_v1"));
    assert_eq!(response["descriptor"], serde_json::to_value(expected)?);
    assert_eq!(response["response"]["type"], json!("failure"));
    assert_eq!(response["response"]["data"]["code"], json!(expected_code));
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn ingress_rejects_oversize_and_unknown_fields_without_poisoning_typed_calls() -> TestResult {
    let service = ServiceProcess::spawn().await?;
    let client = service.client();
    let review_packet = packet(&service.expected);
    client.wait_until_ready(CancellationToken::new()).await?;

    let oversized = service
        .expected
        .limits
        .request_bytes()
        .checked_add(1)
        .ok_or("request byte cap cannot be incremented")?;
    assert_raw_failure(
        service.endpoint,
        &service.expected,
        /*body*/ None,
        oversized,
        "request_too_large",
    )
    .await?;
    assert_eq!(client.review(review_packet.clone()).await?, Verdict::Pass);

    let mut unknown_envelope_field = raw_review(&service.expected, &review_packet);
    unknown_envelope_field
        .as_object_mut()
        .ok_or("raw request envelope must be an object")?
        .insert("unknown_envelope_field".to_string(), json!(true));
    let unknown_envelope_body = serde_json::to_vec(&unknown_envelope_field)?;
    assert!(u32::try_from(unknown_envelope_body.len())? <= REQUEST_BYTES);
    assert_raw_failure(
        service.endpoint,
        &service.expected,
        Some(&unknown_envelope_body),
        u32::try_from(unknown_envelope_body.len())?,
        "invalid_request",
    )
    .await?;
    assert_eq!(client.review(review_packet.clone()).await?, Verdict::Pass);

    let mut unknown_packet_field = raw_review(&service.expected, &review_packet);
    unknown_packet_field["request"]["data"]["packet"]
        .as_object_mut()
        .ok_or("raw nested packet must be an object")?
        .insert("unknown_packet_field".to_string(), json!(true));
    let unknown_packet_body = serde_json::to_vec(&unknown_packet_field)?;
    assert!(u32::try_from(unknown_packet_body.len())? <= REQUEST_BYTES);
    assert_raw_failure(
        service.endpoint,
        &service.expected,
        Some(&unknown_packet_body),
        u32::try_from(unknown_packet_body.len())?,
        "invalid_request",
    )
    .await?;
    assert_eq!(client.review(review_packet.clone()).await?, Verdict::Pass);

    let local_cap = RuntimeLimits::new(
        /*request_bytes*/ 1,
        RESPONSE_BYTES,
        /*max_concurrency*/ 1,
        /*queue_capacity*/ 2,
        Duration::from_millis(500),
        Duration::from_millis(500),
    )?;
    let local_expected = controlled_test_descriptor(local_cap);
    let local_cap_client = PublicationCriticClient::new(ClientConfig::new(
        service.endpoint,
        local_expected.clone(),
        CALL_TIMEOUT,
        STARTUP_TIMEOUT,
    )?)?;
    assert_eq!(
        local_cap_client.review(packet(&local_expected)).await,
        Err(CriticFailure::Contract(ContractFailure::RequestTooLarge))
    );
    assert_eq!(client.review(review_packet).await?, Verdict::Pass);

    client.shutdown().await?;
    service.finish().await
}
