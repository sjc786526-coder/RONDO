use super::*;
use crate::QualificationIdentity;
use crate::RuntimeLimits;
use crate::ServiceIdentity;
use pretty_assertions::assert_eq;

fn reference_provider() -> CloudProviderConfig {
    CloudProviderConfig {
        api: CloudApiShape::ChatCompletions,
        base_url: "https://provider.example.com/v1".to_string(),
        api_key_env: "EXAMPLE_CLOUD_API_KEY".to_string(),
        model: "example-cloud-model".to_string(),
        served_model: ServedModelCheck::Echoed,
        response_format: CloudResponseFormat::JsonObject,
        max_output_tokens: 64,
        temperature: 0.0,
        request_timeout_ms: 8_000,
        max_attempts: 3,
        // 3 attempts sleep (1+2)×300 ms, so the worst case is 24,900 ms of the 25,000 ms
        // production job deadline.
        retry_backoff_ms: 300,
    }
}

fn reference_service_descriptor() -> ServiceDescriptor {
    ServiceDescriptor::new(
        ServiceIdentity::new(
            ComponentIdentity::new("rondo-publication-critic-service", "v1")
                .expect("component is valid"),
            QualificationIdentity::new(
                ComponentIdentity::new("rondo-publication-packet", "v1")
                    .expect("component is valid"),
                ComponentIdentity::new("rondo-publication-qualification", "v1")
                    .expect("component is valid"),
            ),
            provider_managed_model_identity("example-cloud-model")
                .expect("provider-managed model identity is valid"),
            cloud_reference_scoring_identity("example-cloud-model", "v1", /*threshold*/ 0.5)
                .expect("cloud reference scoring identity is valid"),
        )
        .expect("service identity is valid"),
        RuntimeLimits::production(),
    )
    .expect("service descriptor is valid")
}

fn reference_descriptor() -> CloudScorerDescriptor {
    CloudScorerDescriptor {
        backend_protocol: CLOUD_BACKEND_PROTOCOL.to_string(),
        provider: reference_provider(),
        service_descriptor: reference_service_descriptor(),
    }
}

#[test]
fn reference_cloud_descriptor_is_valid_and_names_its_api_path() {
    let descriptor = reference_descriptor();
    assert_eq!(descriptor.validate(), Ok(()));
    assert_eq!(
        descriptor.provider().request_url().map(String::from),
        Ok("https://provider.example.com/v1/chat/completions".to_string())
    );
    assert_eq!(descriptor.api_key_env(), "EXAMPLE_CLOUD_API_KEY");
}

#[test]
fn foreign_backend_protocol_is_rejected() {
    let mut descriptor = reference_descriptor();
    descriptor.backend_protocol = "rondo-publication-critic-worker-v1".to_string();
    assert_eq!(
        descriptor.validate(),
        Err(CloudScorerConfigError::InvalidDescriptor)
    );
}

#[test]
fn cloud_identity_cannot_claim_a_verified_tokenizer_or_local_template() {
    let exact_looking_tokenizer =
        ComponentIdentity::new("qwen3-tokenizer", "9f2c1a").expect("component is valid");
    let local_render = ComponentIdentity::new("rondo-publication-packet-render", "v1")
        .expect("component is valid");

    let mut tokenizer_claim = reference_descriptor();
    tokenizer_claim.service_descriptor.identity.model.tokenizer = exact_looking_tokenizer;

    // Requesting model A while declaring model B would let the service accept A's score under B.
    let mut substituted_model = reference_descriptor();
    substituted_model.provider.model = "example-cheaper-model".to_string();

    // A pinned-looking serving revision would imply the provider proved which deployment served
    // the request, which a chat-completions reply never does.
    let mut pinned_serving_revision = reference_descriptor();
    pinned_serving_revision
        .service_descriptor
        .identity
        .model
        .model =
        ComponentIdentity::new("example-cloud-model", "2026-08-01").expect("component is valid");

    let mut template_claim = reference_descriptor();
    template_claim
        .service_descriptor
        .identity
        .scoring
        .input_template = local_render;

    let mut projection_claim = reference_descriptor();
    projection_claim
        .service_descriptor
        .identity
        .scoring
        .scalar_projection =
        ComponentIdentity::new("single-scalar", "v1").expect("component is valid");

    let mut final_definition_claim = reference_descriptor();
    final_definition_claim
        .service_descriptor
        .identity
        .scoring
        .definition = ComponentIdentity::new("skywork-publication-critic-final", "v1")
        .expect("component is valid");

    let mut widened_domain = reference_descriptor();
    widened_domain.service_descriptor.identity.scoring = ScoringIdentity::new(
        widened_domain
            .service_descriptor
            .identity
            .scoring
            .definition
            .clone(),
        widened_domain
            .service_descriptor
            .identity
            .scoring
            .input_template
            .clone(),
        widened_domain
            .service_descriptor
            .identity
            .scoring
            .scalar_projection
            .clone(),
        ScoreDomain::new(/*min*/ 0.0, /*max*/ 10.0).expect("domain is valid"),
        /*threshold*/ 5.0,
    )
    .expect("scoring identity is valid");

    for descriptor in [
        tokenizer_claim,
        substituted_model,
        pinned_serving_revision,
        template_claim,
        projection_claim,
        final_definition_claim,
        widened_domain,
    ] {
        assert_eq!(
            descriptor.validate(),
            Err(CloudScorerConfigError::DishonestIdentity)
        );
    }
}

#[test]
fn unsafe_endpoints_are_rejected_before_any_request_is_built() {
    for base_url in [
        "http://provider.example.com/v1",
        "https://user:secret@provider.example.com/v1",
        "https://token@provider.example.com/v1",
        "https://provider.example.com/v1?api_key=secret",
        "https://provider.example.com/v1#secret",
        "ftp://provider.example.com/v1",
        "provider.example.com/v1",
        "",
    ] {
        let mut descriptor = reference_descriptor();
        descriptor.provider.base_url = base_url.to_string();
        assert_eq!(
            descriptor.validate(),
            Err(CloudScorerConfigError::UnsafeEndpoint),
            "endpoint must be rejected: {base_url}"
        );
    }
}

#[test]
fn a_loopback_provider_may_use_plain_http_for_offline_injection() {
    let mut descriptor = reference_descriptor();
    descriptor.provider.base_url = "http://127.0.0.1:8123/v1".to_string();
    assert_eq!(descriptor.validate(), Ok(()));
    assert_eq!(
        descriptor.provider().request_url().map(String::from),
        Ok("http://127.0.0.1:8123/v1/chat/completions".to_string())
    );
    assert!(
        CloudScorerConfig::new(descriptor, "sk-example-key".to_string())
            .expect("loopback config is valid")
            .loopback_provider
    );
}

#[test]
fn the_worst_case_retry_budget_must_fit_the_service_job_deadline() {
    let mut descriptor = reference_descriptor();
    descriptor.provider.request_timeout_ms = 20_000;
    descriptor.provider.max_attempts = 2;
    assert_eq!(
        descriptor.validate(),
        Err(CloudScorerConfigError::InvalidDescriptor)
    );

    let mut backoff_overrun = reference_descriptor();
    backoff_overrun.provider.request_timeout_ms = 8_000;
    backoff_overrun.provider.max_attempts = 3;
    backoff_overrun.provider.retry_backoff_ms = 1_000;
    assert_eq!(
        backoff_overrun.validate(),
        Err(CloudScorerConfigError::InvalidDescriptor)
    );
}

/// The runtime sleeps `backoff × attempt` after each failure, so the accepted budget must be the
/// triangular sum rather than one flat backoff per retry.
#[test]
fn the_retry_budget_accounts_for_every_increasing_backoff() {
    // `RuntimeLimits::production()` advertises a 25,000 ms job deadline.
    for (max_attempts, request_timeout_ms, retry_backoff_ms, expected) in [
        // 2 attempts sleep 1×backoff: 24,000 + 1,000 = 25,000.
        (2_u8, 12_000_u64, 1_000_u64, Ok(())),
        (
            2,
            12_000,
            1_001,
            Err(CloudScorerConfigError::InvalidDescriptor),
        ),
        // 3 attempts sleep (1+2)×backoff: 21,000 + 3,000 = 24,000.
        (3, 7_000, 1_000, Ok(())),
        (
            3,
            7_000,
            1_400,
            Err(CloudScorerConfigError::InvalidDescriptor),
        ),
        // 4 attempts sleep (1+2+3)×backoff: 22,000 + 3,000 = 25,000.
        (4, 5_500, 500, Ok(())),
        (
            4,
            5_500,
            600,
            Err(CloudScorerConfigError::InvalidDescriptor),
        ),
    ] {
        let mut descriptor = reference_descriptor();
        descriptor.provider.max_attempts = max_attempts;
        descriptor.provider.request_timeout_ms = request_timeout_ms;
        descriptor.provider.retry_backoff_ms = retry_backoff_ms;
        assert_eq!(
            descriptor.validate(),
            expected,
            "attempts={max_attempts} timeout={request_timeout_ms} backoff={retry_backoff_ms}"
        );
    }
}

#[test]
fn provider_request_bounds_are_enforced() {
    let mut unbounded_attempts = reference_descriptor();
    unbounded_attempts.provider.max_attempts = MAX_ATTEMPTS + 1;

    let mut unbounded_output = reference_descriptor();
    unbounded_output.provider.max_output_tokens = MAX_OUTPUT_TOKENS + 1;

    let mut non_finite_temperature = reference_descriptor();
    non_finite_temperature.provider.temperature = f64::NAN;

    let mut shell_style_env = reference_descriptor();
    shell_style_env.provider.api_key_env = "example-cloud-key".to_string();

    for descriptor in [
        unbounded_attempts,
        unbounded_output,
        non_finite_temperature,
        shell_style_env,
    ] {
        assert_eq!(
            descriptor.validate(),
            Err(CloudScorerConfigError::InvalidDescriptor)
        );
    }
}

#[test]
fn credentials_must_be_present_and_header_safe() {
    for api_key in ["", "key with space", "key\nInjected: header", "\u{e9}key"] {
        assert!(matches!(
            CloudScorerConfig::new(reference_descriptor(), api_key.to_string()),
            Err(CloudScorerConfigError::InvalidCredential)
        ));
    }
    assert!(CloudScorerConfig::new(reference_descriptor(), "sk-example-key".to_string()).is_ok());
}
