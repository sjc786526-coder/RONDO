use crate::ClientConfig;
use crate::ComponentIdentity;
use crate::ContractFailure;
use crate::MIN_PROTOCOL_FRAME_BYTES;
use crate::ModelIdentity;
use crate::ProtocolVersion;
use crate::PublicationCriticClient;
use crate::PublicationPacket;
use crate::PublicationScorer;
use crate::QualificationIdentity;
use crate::RawScorerOutput;
use crate::RuntimeLimits;
use crate::ScoreDomain;
use crate::ScorerError;
use crate::ScorerStatus;
use crate::ScoringIdentity;
use crate::ServiceConfig;
use crate::ServiceDescriptor;
use crate::ServiceIdentity;
use crate::ServicePhase;
use crate::ServiceRunError;
use crate::ServiceStatus;
use crate::Verdict;
use crate::controlled_test_descriptor;
use crate::serve;
use crate::wire::RequestEnvelope;
use crate::wire::RequestPayload;
use crate::wire::ResponseEnvelope;
use crate::wire::ResponsePayload;
use crate::wire::ServiceFailureCode;
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

    let mut too_small = controlled_test_descriptor(RuntimeLimits::production());
    too_small.limits.response_bytes = MIN_PROTOCOL_FRAME_BYTES - 1;
    let bypassed = ClientConfig {
        endpoint: SocketAddr::from(([127, 0, 0, 1], 1)),
        expected: too_small,
        call_timeout: Duration::from_secs(1),
        startup_timeout: Duration::from_secs(1),
    };
    assert!(matches!(
        PublicationCriticClient::new(bypassed),
        Err(ContractFailure::InvalidResourceConfiguration)
    ));
}

#[tokio::test]
async fn service_consumption_boundary_revalidates_frame_caps_and_shutdown_timeouts() {
    for invalid_request_bytes in [MIN_PROTOCOL_FRAME_BYTES - 1, u32::MAX] {
        let mut descriptor = controlled_test_descriptor(RuntimeLimits::production());
        descriptor.limits.request_bytes = invalid_request_bytes;
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
    }

    let descriptor = controlled_test_descriptor(RuntimeLimits::production());
    assert_eq!(
        ServiceConfig::new(descriptor, Duration::MAX, Duration::from_secs(1))
            .expect_err("unbounded shutdown timeout must be rejected"),
        ContractFailure::InvalidResourceConfiguration
    );
}

#[test]
fn protocol_frame_minimum_accepts_control_envelopes_for_maximum_valid_identity() {
    assert_eq!(
        RuntimeLimits::new(
            MIN_PROTOCOL_FRAME_BYTES - 1,
            MIN_PROTOCOL_FRAME_BYTES,
            /*max_concurrency*/ 1,
            /*queue_capacity*/ 0,
            Duration::from_secs(1),
            Duration::from_secs(1),
        )
        .expect_err("request cap below the protocol floor must be rejected"),
        ContractFailure::InvalidResourceConfiguration
    );

    let escaped = ComponentIdentity::new("\"".repeat(128), "\\".repeat(128))
        .expect("maximum escaped component is valid");
    let scoring = ScoringIdentity::new(
        escaped.clone(),
        escaped.clone(),
        escaped.clone(),
        ScoreDomain::new(-f64::MAX, f64::MAX).expect("finite score domain is valid"),
        /*threshold*/ 0.0,
    )
    .expect("maximum scoring identity is valid");
    let identity = ServiceIdentity::new(
        escaped.clone(),
        QualificationIdentity::new(escaped.clone(), escaped.clone()),
        ModelIdentity::new(escaped.clone(), escaped),
        scoring,
    )
    .expect("maximum service identity is valid");
    let limits = RuntimeLimits::new(
        MIN_PROTOCOL_FRAME_BYTES,
        MIN_PROTOCOL_FRAME_BYTES,
        /*max_concurrency*/ 8,
        /*queue_capacity*/ 64,
        Duration::from_secs(300),
        Duration::from_secs(300),
    )
    .expect("protocol floor is a valid frame cap");
    let descriptor = ServiceDescriptor::new(identity, limits)
        .expect("maximum descriptor with protocol floor is valid");
    let status = ServiceStatus {
        phase: ServicePhase::Failed,
        in_flight: u16::MAX,
        queued: u16::MAX,
    };

    let requests = [
        RequestEnvelope {
            protocol: ProtocolVersion::RondoPublicationCriticV1,
            request: RequestPayload::Liveness,
        },
        RequestEnvelope {
            protocol: ProtocolVersion::RondoPublicationCriticV1,
            request: RequestPayload::Readiness,
        },
        RequestEnvelope {
            protocol: ProtocolVersion::RondoPublicationCriticV1,
            request: RequestPayload::Shutdown {
                expected: Box::new(descriptor.clone()),
            },
        },
    ];
    for request in requests {
        assert_frame_fits(&request);
    }

    let responses = [
        ResponsePayload::Liveness { status },
        ResponsePayload::Readiness { status },
        ResponsePayload::Verdict {
            verdict: Verdict::Rewrite,
        },
        ResponsePayload::ShutdownAccepted,
        ResponsePayload::Failure {
            code: ServiceFailureCode::BackendScoringIdentityMismatch,
        },
    ];
    for response in responses {
        assert_frame_fits(&ResponseEnvelope {
            protocol: ProtocolVersion::RondoPublicationCriticV1,
            descriptor: descriptor.clone(),
            response,
        });
    }
}

fn assert_frame_fits(value: &impl serde::Serialize) {
    let encoded = serde_json::to_vec(value).expect("wire value must serialize");
    assert!(
        encoded.len() <= MIN_PROTOCOL_FRAME_BYTES as usize,
        "control envelope is {} bytes, above the {} byte protocol floor",
        encoded.len(),
        MIN_PROTOCOL_FRAME_BYTES
    );
}
