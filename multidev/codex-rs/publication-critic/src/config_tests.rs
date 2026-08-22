use crate::ClientConfig;
use crate::ContractFailure;
use crate::PublicationCriticClient;
use crate::PublicationPacket;
use crate::PublicationScorer;
use crate::RawScorerOutput;
use crate::RuntimeLimits;
use crate::ScorerError;
use crate::ScorerStatus;
use crate::ServiceConfig;
use crate::ServiceRunError;
use crate::controlled_test_descriptor;
use crate::serve;
use std::net::SocketAddr;
use std::time::Duration;
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;

#[derive(Clone)]
struct UnusedScorer;

impl PublicationScorer for UnusedScorer {
    fn status(&self) -> ScorerStatus {
        ScorerStatus::Loading
    }

    async fn score(
        &self,
        _packet: PublicationPacket,
        _cancellation: CancellationToken,
    ) -> Result<RawScorerOutput, ScorerError> {
        unreachable!("invalid service configuration must fail before scoring")
    }
}

#[test]
fn client_consumption_boundary_revalidates_loopback_and_bounded_timeouts() {
    let expected = controlled_test_descriptor(RuntimeLimits::production());
    let bypassed = ClientConfig {
        endpoint: SocketAddr::from(([192, 0, 2, 1], 1)),
        expected: expected.clone(),
        call_timeout: Duration::from_secs(1),
        startup_timeout: Duration::from_secs(1),
    };
    assert!(matches!(
        PublicationCriticClient::new(bypassed),
        Err(ContractFailure::InvalidResourceConfiguration)
    ));
    assert_eq!(
        ClientConfig::new(
            SocketAddr::from(([127, 0, 0, 1], 1)),
            expected,
            Duration::MAX,
            Duration::from_secs(1),
        )
        .expect_err("unbounded client timeout must be rejected"),
        ContractFailure::InvalidResourceConfiguration
    );
}

#[tokio::test]
async fn service_consumption_boundary_revalidates_frame_caps_and_shutdown_timeouts() {
    let mut descriptor = controlled_test_descriptor(RuntimeLimits::production());
    descriptor.limits.request_bytes = u32::MAX;
    let bypassed = ServiceConfig {
        descriptor,
        graceful_shutdown_timeout: Duration::from_secs(1),
        force_shutdown_timeout: Duration::from_secs(1),
    };
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("test listener must bind");
    assert_eq!(
        serve(listener, bypassed, UnusedScorer).await,
        Err(ServiceRunError::InvalidConfiguration)
    );

    let descriptor = controlled_test_descriptor(RuntimeLimits::production());
    assert_eq!(
        ServiceConfig::new(descriptor, Duration::MAX, Duration::from_secs(1))
            .expect_err("unbounded shutdown timeout must be rejected"),
        ContractFailure::InvalidResourceConfiguration
    );
}
