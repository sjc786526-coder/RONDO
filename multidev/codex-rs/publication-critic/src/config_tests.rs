use crate::ActorRole;
use crate::ClientConfig;
use crate::CloudContinuityDecision;
use crate::CloudFiveDimensionDecisions;
use crate::CloudHardDecision;
use crate::ComponentIdentity;
use crate::ContinuityContext;
use crate::ContractFailure;
use crate::FiveDimensionScoringIdentity;
use crate::LocalScope;
use crate::MIN_PROTOCOL_FRAME_BYTES;
use crate::ModelIdentity;
use crate::ProtocolVersion;
use crate::PublicationCandidate;
use crate::PublicationCriticClient;
use crate::PublicationPacket;
use crate::PublicationScorer;
use crate::QualificationIdentity;
use crate::RawScorerOutput;
use crate::RuntimeLimits;
use crate::ScoreDomain;
use crate::ScorerError;
use crate::ScorerProjection;
use crate::ScorerStatus;
use crate::ScoringContract;
use crate::ScoringIdentity;
use crate::ServiceConfig;
use crate::ServiceDescriptor;
use crate::ServiceIdentity;
use crate::ServicePhase;
use crate::ServiceRunError;
use crate::ServiceStatus;
use crate::TargetKind;
use crate::Verdict;
use crate::controlled_test_descriptor;
use crate::controlled_test_identity;
use crate::serve;
use crate::wire::RequestEnvelope;
use crate::wire::RequestPayload;
use crate::wire::ResponseEnvelope;
use crate::wire::ResponsePayload;
use crate::wire::ServiceFailureCode;
use std::net::SocketAddr;
use std::sync::Mutex;
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

fn hard(pass: bool) -> CloudHardDecision {
    if pass {
        CloudHardDecision::Pass
    } else {
        CloudHardDecision::Fail
    }
}

fn legal_five_dimension_combinations() -> Vec<CloudFiveDimensionDecisions> {
    let mut combinations = Vec::with_capacity(48);
    for useful in [true, false] {
        for honest in [true, false] {
            for scope in [true, false] {
                for consistency in [true, false] {
                    for continuity in [
                        CloudContinuityDecision::Pass,
                        CloudContinuityDecision::Fail,
                        CloudContinuityDecision::NotApplicable,
                    ] {
                        combinations.push(CloudFiveDimensionDecisions {
                            useful_state_transfer: hard(useful),
                            honest_uncertainty: hard(honest),
                            conditional_continuity: continuity,
                            scope_and_signal: hard(scope),
                            internal_consistency: hard(consistency),
                        });
                    }
                }
            }
        }
    }
    combinations
}

/// Independent task-v2 §3 oracle. N/A only excludes continuity; it does not add a pass.
fn section3_verdict(decisions: &CloudFiveDimensionDecisions) -> Verdict {
    let applicable_fail = decisions.useful_state_transfer == CloudHardDecision::Fail
        || decisions.honest_uncertainty == CloudHardDecision::Fail
        || decisions.scope_and_signal == CloudHardDecision::Fail
        || decisions.internal_consistency == CloudHardDecision::Fail
        || decisions.conditional_continuity == CloudContinuityDecision::Fail;
    if applicable_fail {
        Verdict::Rewrite
    } else {
        Verdict::Pass
    }
}

fn five_dimension_test_descriptor() -> ServiceDescriptor {
    let scoring = FiveDimensionScoringIdentity::new(
        ComponentIdentity::new("controlled-test-five-dimension", "v1").expect("component is valid"),
        ComponentIdentity::new("controlled-test-five-dimension-template", "v1")
            .expect("component is valid"),
        ComponentIdentity::new("controlled-test-five-dimension-projection", "v1")
            .expect("component is valid"),
    );
    let mut identity = controlled_test_identity();
    identity.scoring = ScoringContract::FiveDimension(scoring);
    ServiceDescriptor::new(identity, RuntimeLimits::production()).expect("descriptor is valid")
}

fn review_packet(descriptor: &ServiceDescriptor) -> PublicationPacket {
    PublicationPacket::new(
        descriptor.identity.qualification.clone(),
        ActorRole::Root,
        TargetKind::NewEvent,
        LocalScope::new("Plan 102 five-dimension service gate").expect("title is valid"),
        PublicationCandidate::new(
            "Synthetic candidate used only to drive the in-process five-dimension gate.",
        )
        .expect("summary is valid"),
        ContinuityContext::NotApplicable,
    )
    .expect("packet is valid")
}

#[derive(Clone)]
struct QueuedFiveDimensionScorer {
    descriptor: ServiceDescriptor,
    remaining: std::sync::Arc<Mutex<Vec<CloudFiveDimensionDecisions>>>,
}

impl PublicationScorer for QueuedFiveDimensionScorer {
    fn status(&self) -> ScorerStatus {
        ScorerStatus::Ready {
            model: self.descriptor.identity.model.clone(),
            scoring: Box::new(self.descriptor.identity.scoring.clone()),
        }
    }

    async fn score(
        &self,
        _packet: PublicationPacket,
        _cancellation: CancellationToken,
    ) -> Result<RawScorerOutput, ScorerError> {
        let decisions = self
            .remaining
            .lock()
            .expect("five-dimension queue lock")
            .pop()
            .ok_or(ScorerError::BackendUnavailable)?;
        Ok(RawScorerOutput {
            model: self.descriptor.identity.model.clone(),
            scoring: self.descriptor.identity.scoring.clone(),
            projection: ScorerProjection::FiveDimension { decisions },
        })
    }
}

#[tokio::test]
async fn service_emits_section3_verdict_for_every_legal_five_dimension_combination() {
    let combinations = legal_five_dimension_combinations();
    assert_eq!(combinations.len(), 48, "four binary heads × continuity 3");

    let mut remaining = combinations.clone();
    remaining.reverse();
    let descriptor = five_dimension_test_descriptor();
    let packet = review_packet(&descriptor);
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("test listener must bind");
    let endpoint = listener.local_addr().expect("listener address");
    let scorer = QueuedFiveDimensionScorer {
        descriptor: descriptor.clone(),
        remaining: std::sync::Arc::new(Mutex::new(remaining)),
    };
    let server = tokio::spawn(serve(
        listener,
        ServiceConfig::new(
            descriptor.clone(),
            Duration::from_secs(1),
            Duration::from_secs(1),
        )
        .expect("service config is valid"),
        scorer,
    ));
    let client = PublicationCriticClient::new(
        ClientConfig::new(
            endpoint,
            descriptor,
            Duration::from_secs(2),
            Duration::from_secs(2),
        )
        .expect("client config is valid"),
    )
    .expect("client is valid");
    client
        .wait_until_ready(CancellationToken::new())
        .await
        .expect("five-dimension service must become ready");

    let mut pass_count = 0;
    let mut rewrite_count = 0;
    for decisions in &combinations {
        let expected = section3_verdict(decisions);
        let verdict = client
            .review(packet.clone())
            .await
            .expect("five-dimension review must succeed");
        assert_eq!(
            verdict, expected,
            "service verdict must equal task-v2 §3 for {decisions:?}"
        );
        match expected {
            Verdict::Pass => pass_count += 1,
            Verdict::Rewrite => rewrite_count += 1,
        }
    }

    let all_pass = CloudFiveDimensionDecisions {
        useful_state_transfer: CloudHardDecision::Pass,
        honest_uncertainty: CloudHardDecision::Pass,
        conditional_continuity: CloudContinuityDecision::Pass,
        scope_and_signal: CloudHardDecision::Pass,
        internal_consistency: CloudHardDecision::Pass,
    };
    let na_and_all_pass = CloudFiveDimensionDecisions {
        useful_state_transfer: CloudHardDecision::Pass,
        honest_uncertainty: CloudHardDecision::Pass,
        conditional_continuity: CloudContinuityDecision::NotApplicable,
        scope_and_signal: CloudHardDecision::Pass,
        internal_consistency: CloudHardDecision::Pass,
    };
    assert_eq!(section3_verdict(&all_pass), Verdict::Pass);
    assert_eq!(section3_verdict(&na_and_all_pass), Verdict::Pass);
    for head in [
        "useful_state_transfer",
        "honest_uncertainty",
        "scope_and_signal",
        "internal_consistency",
    ] {
        let mut single_fail = all_pass.clone();
        match head {
            "useful_state_transfer" => single_fail.useful_state_transfer = CloudHardDecision::Fail,
            "honest_uncertainty" => single_fail.honest_uncertainty = CloudHardDecision::Fail,
            "scope_and_signal" => single_fail.scope_and_signal = CloudHardDecision::Fail,
            "internal_consistency" => single_fail.internal_consistency = CloudHardDecision::Fail,
            _ => unreachable!(),
        }
        assert_eq!(
            section3_verdict(&single_fail),
            Verdict::Rewrite,
            "{head} FAIL must be non-compensating"
        );
        let mut na_and_fail = single_fail.clone();
        na_and_fail.conditional_continuity = CloudContinuityDecision::NotApplicable;
        assert_eq!(
            section3_verdict(&na_and_fail),
            Verdict::Rewrite,
            "N/A must not rescue a {head} FAIL"
        );
    }
    assert_eq!(pass_count, 2);
    assert_eq!(rewrite_count, 46);

    drop(client);
    server.abort();
}

#[test]
fn five_dimension_scoring_contract_has_no_threshold_and_scalar_json_is_unchanged() {
    let scalar = ScoringIdentity::new(
        ComponentIdentity::new("controlled-test-scalar", "v1").expect("component is valid"),
        ComponentIdentity::new("rondo-publication-packet-render", "v1")
            .expect("component is valid"),
        ComponentIdentity::new("single-scalar", "v1").expect("component is valid"),
        ScoreDomain::new(0.0, 1.0).expect("domain is valid"),
        0.5,
    )
    .expect("scalar identity is valid");
    let wrapped = ScoringContract::from(scalar.clone());
    assert_eq!(
        serde_json::to_value(&wrapped).expect("contract must serialize"),
        serde_json::to_value(&scalar).expect("scalar must serialize")
    );

    let five = FiveDimensionScoringIdentity::new(
        ComponentIdentity::new("rondo-cloud-reference-example", "v1").expect("component is valid"),
        ComponentIdentity::new("rondo-publication-cloud-five-dimension-template", "v1")
            .expect("component is valid"),
        ComponentIdentity::new("rondo-cloud-json-five-dimension-decisions", "v1")
            .expect("component is valid"),
    );
    let encoded = serde_json::to_value(ScoringContract::FiveDimension(five))
        .expect("five-dimension contract must serialize");
    let object = encoded.as_object().expect("object");
    assert!(!object.contains_key("threshold"));
    assert!(!object.contains_key("domain"));
    assert!(!object.contains_key("scalar_projection"));
    assert_eq!(object["pass_rule"], "discrete_non_compensating_conjunction");
    assert_eq!(
        object["decision_projection"]["name"],
        "rondo-cloud-json-five-dimension-decisions"
    );
}
