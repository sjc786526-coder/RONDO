#![allow(clippy::expect_used)]

use codex_publication_critic::ActorRole;
use codex_publication_critic::ClientConfig;
use codex_publication_critic::ContinuityContext;
use codex_publication_critic::ContractFailure;
use codex_publication_critic::CriticFailure;
use codex_publication_critic::IdentityField;
use codex_publication_critic::LocalScope;
use codex_publication_critic::PublicationCandidate;
use codex_publication_critic::PublicationCriticClient;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::ServiceDescriptor;
use codex_publication_critic::TargetKind;
use codex_publication_critic::controlled_test_descriptor;
use serde_json::Value;
use serde_json::json;
use std::future::Future;
use std::net::SocketAddr;
use std::time::Duration;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::net::TcpListener;
use tokio::net::TcpStream;
use tokio::sync::oneshot;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

const TEST_TIMEOUT: Duration = Duration::from_secs(2);

fn test_descriptor() -> ServiceDescriptor {
    let limits = RuntimeLimits::new(
        64 * 1024,
        16 * 1024,
        /*max_concurrency*/ 1,
        /*queue_capacity*/ 1,
        Duration::from_secs(1),
        Duration::from_secs(1),
    )
    .expect("test resource limits must be valid");
    controlled_test_descriptor(limits)
}

fn test_packet(expected: &ServiceDescriptor) -> PublicationPacket {
    PublicationPacket::new(
        expected.identity.qualification.clone(),
        ActorRole::Member,
        TargetKind::NewEvent,
        LocalScope::new("adversarial peer test").expect("test scope must be valid"),
        PublicationCandidate::new("private-candidate-sentinel")
            .expect("test candidate must be valid"),
        ContinuityContext::NotApplicable,
    )
    .expect("test packet must be valid")
}

fn test_client(endpoint: SocketAddr, expected: ServiceDescriptor) -> PublicationCriticClient {
    let config = ClientConfig::new(endpoint, expected, TEST_TIMEOUT, TEST_TIMEOUT)
        .expect("loopback test client configuration must be valid");
    PublicationCriticClient::new(config)
}

async fn bind_peer() -> (TcpListener, SocketAddr) {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("malicious peer must bind loopback");
    let endpoint = listener
        .local_addr()
        .expect("malicious peer must have a local address");
    (listener, endpoint)
}

async fn consume_request(stream: &mut TcpStream) {
    let mut prefix = [0_u8; 4];
    stream
        .read_exact(&mut prefix)
        .await
        .expect("client must send a frame prefix");
    let body_len =
        usize::try_from(u32::from_be_bytes(prefix)).expect("u32 request length must fit usize");
    assert!(
        body_len <= 64 * 1024,
        "test client request exceeded its cap"
    );
    let mut body = vec![0_u8; body_len];
    stream
        .read_exact(&mut body)
        .await
        .expect("client must send the complete request frame");
}

async fn write_frame(stream: &mut TcpStream, body: &[u8]) {
    let body_len = u32::try_from(body.len()).expect("test response must fit a u32 frame");
    stream
        .write_all(&body_len.to_be_bytes())
        .await
        .expect("malicious peer must write response prefix");
    stream
        .write_all(body)
        .await
        .expect("malicious peer must write response body");
}

async fn await_peer(task: JoinHandle<()>) {
    timeout(TEST_TIMEOUT, task)
        .await
        .expect("malicious peer task timed out")
        .expect("malicious peer task panicked");
}

async fn expect_review_failure<F>(peer: F) -> CriticFailure
where
    F: Future<Output = (SocketAddr, JoinHandle<()>)>,
{
    let (endpoint, peer_task) = peer.await;
    let expected = test_descriptor();
    let client = test_client(endpoint, expected.clone());
    let result = client.review(test_packet(&expected)).await;
    await_peer(peer_task).await;
    result.expect_err("an adversarial response must never produce a verdict")
}

async fn framed_peer(body: Vec<u8>) -> (SocketAddr, JoinHandle<()>) {
    let (listener, endpoint) = bind_peer().await;
    let task = tokio::spawn(async move {
        let (mut stream, _) = listener
            .accept()
            .await
            .expect("malicious peer must accept one client");
        consume_request(&mut stream).await;
        write_frame(&mut stream, &body).await;
    });
    (endpoint, task)
}

fn verdict_response(protocol: &str, descriptor: Value) -> Vec<u8> {
    serde_json::to_vec(&json!({
        "protocol": protocol,
        "descriptor": descriptor,
        "response": {
            "type": "verdict",
            "data": { "verdict": "pass" }
        }
    }))
    .expect("test response JSON must serialize")
}

#[tokio::test]
async fn malformed_json_response_is_a_typed_contract_failure() {
    let failure = expect_review_failure(framed_peer(b"not-json".to_vec())).await;

    assert_eq!(
        failure,
        CriticFailure::Contract(ContractFailure::MalformedResponse)
    );
}

#[tokio::test]
async fn oversized_response_prefix_is_rejected_before_body_allocation() {
    let (listener, endpoint) = bind_peer().await;
    let expected = test_descriptor();
    let oversized = expected
        .limits
        .response_bytes
        .checked_add(1)
        .expect("test response cap must be incrementable");
    let peer_task = tokio::spawn(async move {
        let (mut stream, _) = listener
            .accept()
            .await
            .expect("malicious peer must accept one client");
        consume_request(&mut stream).await;
        stream
            .write_all(&oversized.to_be_bytes())
            .await
            .expect("malicious peer must write oversized prefix");
    });
    let client = test_client(endpoint, expected.clone());

    let result = client.review(test_packet(&expected)).await;
    await_peer(peer_task).await;

    assert_eq!(
        result.expect_err("an oversized response must never produce a verdict"),
        CriticFailure::Contract(ContractFailure::ResponseTooLarge)
    );
}

#[tokio::test]
async fn unknown_protocol_response_is_a_typed_contract_failure() {
    let expected = test_descriptor();
    let body = verdict_response(
        "rondo_publication_critic_v2",
        serde_json::to_value(expected).expect("test descriptor must serialize"),
    );

    let failure = expect_review_failure(framed_peer(body)).await;

    assert_eq!(
        failure,
        CriticFailure::Contract(ContractFailure::MalformedResponse)
    );
}

#[tokio::test]
async fn descriptor_identity_drift_cannot_smuggle_a_verdict() {
    let expected = test_descriptor();
    let mut drifted =
        serde_json::to_value(expected).expect("test descriptor must serialize to JSON");
    drifted["identity"]["implementation"]["revision"] = json!("drift-v2");
    let body = verdict_response("rondo_publication_critic_v1", drifted);

    let failure = expect_review_failure(framed_peer(body)).await;

    assert_eq!(
        failure,
        CriticFailure::Contract(ContractFailure::IdentityMismatch(IdentityField::Service))
    );
}

#[tokio::test]
async fn stalled_response_observes_cancellation_as_a_typed_failure() {
    let (listener, endpoint) = bind_peer().await;
    let (request_seen_tx, request_seen_rx) = oneshot::channel();
    let peer_task = tokio::spawn(async move {
        let (mut stream, _) = listener
            .accept()
            .await
            .expect("malicious peer must accept one client");
        consume_request(&mut stream).await;
        request_seen_tx
            .send(())
            .expect("test must wait for the peer barrier");

        let mut unexpected = [0_u8; 1];
        let bytes_read = stream
            .read(&mut unexpected)
            .await
            .expect("peer must observe client disconnect after cancellation");
        assert_eq!(
            bytes_read, 0,
            "cancelled client sent unexpected trailing data"
        );
    });
    let expected = test_descriptor();
    let client = test_client(endpoint, expected.clone());
    let cancellation = CancellationToken::new();
    let review_task = tokio::spawn({
        let cancellation = cancellation.clone();
        async move {
            client
                .review_with_cancellation(test_packet(&expected), cancellation)
                .await
        }
    });

    timeout(TEST_TIMEOUT, request_seen_rx)
        .await
        .expect("malicious peer did not consume the request")
        .expect("malicious peer dropped its request barrier");
    cancellation.cancel();
    let result = timeout(TEST_TIMEOUT, review_task)
        .await
        .expect("cancelled review task timed out")
        .expect("cancelled review task panicked");
    await_peer(peer_task).await;

    assert_eq!(
        result.expect_err("a cancelled stalled response must never produce a verdict"),
        CriticFailure::Cancelled
    );
}
