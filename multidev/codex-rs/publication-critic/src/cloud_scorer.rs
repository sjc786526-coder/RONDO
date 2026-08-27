//! Cloud reference scorer backend.
//!
//! This is a sibling of the local worker backend: it satisfies the same [`PublicationScorer`]
//! contract, is driven by the same service, and returns either exactly one scalar or a body-free
//! typed failure. Provider request and response bodies, the credential, and provider error text
//! never leave this module.

use crate::ComponentIdentity;
use crate::ContractFailure;
use crate::ModelIdentity;
use crate::PublicationPacket;
use crate::PublicationScorer;
use crate::QualificationIdentity;
use crate::RawScorerOutput;
use crate::ScoreFailureKind;
use crate::ScorerError;
use crate::ScorerStatus;
use crate::ScoringIdentity;
use crate::cloud_config::CloudProviderConfig;
use crate::cloud_config::CloudResponseFormat;
use crate::cloud_config::CloudScorerConfig;
use crate::cloud_config::CloudScorerConfigError;
use crate::cloud_config::ServedModelCheck;
use crate::cloud_template;
use codex_http_client::ClientRouteClass;
use codex_http_client::HttpClient;
use codex_http_client::HttpClientBuilder;
use codex_http_client::HttpClientFactory;
use codex_http_client::HttpResponse;
use codex_http_client::OutboundProxyPolicy;
use serde::Deserialize;
use serde::Serialize;
use std::sync::Arc;
use std::time::Duration;
use thiserror::Error;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
const MAX_RESPONSE_BYTES: usize = 64 * 1024;
const RETRYABLE_STATUS: [u16; 6] = [408, 425, 429, 500, 502, 503];

/// Revision recorded on an observed served model that differs from the requested one.
const SERVED_MODEL_DRIFT_REVISION: &str = "provider-served";
/// Placeholder used when a drifting reply carries no usable served model id at all.
const SERVED_MODEL_ABSENT: &str = "provider-served-model-absent";

struct CloudScorerInner {
    client: HttpClient,
    request_url: String,
    api_key: String,
    provider: CloudProviderConfig,
    qualification: QualificationIdentity,
    model: ModelIdentity,
    scoring: ScoringIdentity,
}

/// Body-free token counts observed on one terminal provider response.
///
/// Cache counts remain optional because providers may omit them. The Plan 096 cost layer decides
/// how to conservatively price a missing or partial observation; this scorer only preserves the
/// provider fields without interpreting a price card.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CloudTokenUsage {
    pub prompt_tokens: Option<u64>,
    pub completion_tokens: Option<u64>,
    pub total_tokens: Option<u64>,
    pub prompt_cache_hit_tokens: Option<u64>,
    pub prompt_cache_miss_tokens: Option<u64>,
}

/// Body-free failure categories exposed only by the direct evaluation entry point.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CloudEvaluationFailureKind {
    ProviderTransport,
    ProviderHttpStatus,
    ProviderMalformedResponse,
    ModelIdentityMismatch,
    InvalidScoreShape,
    NonFiniteScore,
    ScoreOutOfDomain,
}

/// The typed result of one completed evaluation call.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "type", rename_all = "snake_case")]
pub enum CloudEvaluationOutcome {
    Success,
    Failure {
        kind: CloudEvaluationFailureKind,
        http_status: Option<u16>,
    },
}

/// Evaluation-only observation of a cloud scorer call.
///
/// This deliberately contains no packet, prompt, provider response body, credential, or reasoning
/// content. A score remains present for typed model-identity and score-domain failures because it
/// is a real provider observation, but it cannot become a successful row until the same checks the
/// product service applies have passed.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CloudEvaluationObservation {
    pub requested_model: String,
    pub served_model: Option<String>,
    pub score: Option<f64>,
    pub attempts: u8,
    pub elapsed_ms: u64,
    pub usage: Option<CloudTokenUsage>,
    pub outcome: CloudEvaluationOutcome,
}

/// A local evaluation input was rejected before any provider attempt was made.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum CloudEvaluationInputError {
    #[error("publication critic cloud evaluation packet is invalid")]
    InvalidPacket,
    #[error("publication critic cloud evaluation qualification is mismatched")]
    QualificationMismatch,
}

/// Scorer backed by one hosted chat-completions provider.
///
/// Construction has no outbound effect: it only builds an HTTP client. The first request is sent
/// when the service actually asks for a review.
#[derive(Clone)]
pub struct CloudPublicationScorer {
    inner: Arc<CloudScorerInner>,
}

impl CloudPublicationScorer {
    pub fn new(config: CloudScorerConfig) -> Result<Self, CloudScorerConfigError> {
        let builder = HttpClientBuilder::new()
            .without_redirects()
            .without_request_logging()
            .connect_timeout(CONNECT_TIMEOUT);
        let client = if config.loopback_provider {
            // The loopback provider is the offline test fixture. Bypassing proxy discovery is
            // required for it, and it never carries real outbound traffic.
            builder
                .build_direct()
                .map_err(|_| CloudScorerConfigError::ClientUnavailable)?
        } else {
            builder
                .build_respecting_outbound_proxy_policy(
                    &HttpClientFactory::new(OutboundProxyPolicy::RespectSystemProxy),
                    &config.request_url,
                    ClientRouteClass::Api,
                )
                .map_err(|_| CloudScorerConfigError::ClientUnavailable)?
        };
        let descriptor = config.descriptor.service_descriptor();
        Ok(Self {
            inner: Arc::new(CloudScorerInner {
                client,
                request_url: config.request_url.clone(),
                api_key: config.api_key.clone(),
                provider: config.descriptor.provider().clone(),
                qualification: descriptor.identity.qualification.clone(),
                model: descriptor.identity.model.clone(),
                scoring: descriptor.identity.scoring.clone(),
            }),
        })
    }

    /// Scores one packet directly for eval/reference use while preserving scalar and usage.
    ///
    /// The product service and typed client intentionally expose only a verdict. This method is a
    /// separate opt-in seam for Plan 096 and reuses the exact provider request, retry policy,
    /// parser, identity checks, and score domain of the product-backed cloud scorer.
    pub async fn score_for_evaluation(
        &self,
        packet: PublicationPacket,
    ) -> Result<CloudEvaluationObservation, CloudEvaluationInputError> {
        packet
            .validate()
            .map_err(|_| CloudEvaluationInputError::InvalidPacket)?;
        if packet.qualification != self.inner.qualification {
            return Err(CloudEvaluationInputError::QualificationMismatch);
        }
        let user = cloud_template::render_user_message(&packet)
            .ok_or(CloudEvaluationInputError::InvalidPacket)?;
        Ok(self
            .inner
            .evaluation_observation(self.inner.call(user).await))
    }
}

impl PublicationScorer for CloudPublicationScorer {
    /// A hosted provider has no local load phase, and readiness must not send a billable probe.
    /// A fully validated, identity-bound configuration is the readiness signal; real provider
    /// availability shows up as a typed result on the first review.
    fn status(&self) -> ScorerStatus {
        ScorerStatus::Ready {
            model: self.inner.model.clone(),
            scoring: Box::new(self.inner.scoring.clone()),
        }
    }

    async fn score(
        &self,
        packet: PublicationPacket,
        cancellation: CancellationToken,
    ) -> Result<RawScorerOutput, ScorerError> {
        if cancellation.is_cancelled() {
            return Err(ScorerError::BackendUnavailable);
        }
        tokio::select! {
            biased;
            _ = cancellation.cancelled() => Err(ScorerError::BackendUnavailable),
            result = self.inner.score(packet) => result,
        }
    }
}

impl CloudScorerInner {
    async fn score(&self, packet: PublicationPacket) -> Result<RawScorerOutput, ScorerError> {
        let user =
            cloud_template::render_user_message(&packet).ok_or(ScorerError::BackendUnavailable)?;
        match self.call(user).await.outcome {
            Ok(observed) => self.output(observed),
            Err(_) => Err(ScorerError::BackendUnavailable),
        }
    }

    async fn call(&self, user: String) -> CloudCallObservation {
        let request = self.build_request(user);
        let started = Instant::now();
        let mut attempt = 1_u8;
        loop {
            report_attempt(attempt);
            match self.attempt(&request).await {
                Ok(observed) => {
                    let elapsed_ms = elapsed_ms(started);
                    report_call(attempt, elapsed_ms, &observed);
                    return CloudCallObservation {
                        outcome: Ok(observed),
                        attempts: attempt,
                        elapsed_ms,
                    };
                }
                Err(observed_failure) => {
                    if attempt >= self.provider.max_attempts
                        || !observed_failure.failure.retryable()
                    {
                        let elapsed_ms = elapsed_ms(started);
                        report_failure(attempt, elapsed_ms, &observed_failure);
                        return CloudCallObservation {
                            outcome: Err(observed_failure),
                            attempts: attempt,
                            elapsed_ms,
                        };
                    }
                    let backoff = self
                        .provider
                        .retry_backoff_ms
                        .saturating_mul(u64::from(attempt));
                    tokio::time::sleep(Duration::from_millis(backoff)).await;
                    attempt += 1;
                }
            }
        }
    }

    fn build_request(&self, user: String) -> ChatCompletionsRequest {
        ChatCompletionsRequest {
            model: self.provider.model.clone(),
            messages: vec![
                ChatRequestMessage {
                    role: "system",
                    content: cloud_template::CLOUD_SYSTEM_MESSAGE.to_string(),
                },
                ChatRequestMessage {
                    role: "user",
                    content: user,
                },
            ],
            temperature: self.provider.temperature,
            max_tokens: self.provider.max_output_tokens,
            stream: false,
            response_format: match self.provider.response_format {
                CloudResponseFormat::JsonObject => Some(ResponseFormat {
                    format: "json_object",
                }),
                CloudResponseFormat::Unconstrained => None,
            },
        }
    }

    async fn attempt(
        &self,
        request: &ChatCompletionsRequest,
    ) -> Result<ObservedCompletion, ObservedFailure> {
        let response = self
            .client
            .post(&self.request_url)
            .bearer_auth(&self.api_key)
            .timeout(Duration::from_millis(self.provider.request_timeout_ms))
            .json(request)
            .send()
            .await
            .map_err(|_| ObservedFailure::without_metadata(CloudFailure::Transport))?;
        let status = response.status();
        if !status.is_success() {
            // The provider error body is deliberately dropped unread: only the status code is
            // safe to surface.
            return Err(ObservedFailure::without_metadata(CloudFailure::Status {
                code: status.as_u16(),
            }));
        }
        let body = read_bounded(response)
            .await
            .map_err(ObservedFailure::without_metadata)?;
        let parsed: ChatCompletionsResponse = serde_json::from_slice(&body)
            .map_err(|_| ObservedFailure::without_metadata(CloudFailure::Malformed))?;
        parsed.into_observed()
    }

    fn output(&self, observed: ObservedCompletion) -> Result<RawScorerOutput, ScorerError> {
        let model = self.observed_model(observed.served_model.as_deref())?;
        Ok(RawScorerOutput {
            model,
            scoring: self.scoring.clone(),
            scores: vec![observed.score],
        })
    }

    fn evaluation_observation(&self, call: CloudCallObservation) -> CloudEvaluationObservation {
        let requested_model = self.provider.model.clone();
        let attempts = call.attempts;
        let elapsed_ms = call.elapsed_ms;
        match call.outcome {
            Err(failure) => CloudEvaluationObservation {
                requested_model,
                served_model: self.safe_served_model(failure.served_model),
                score: None,
                attempts,
                elapsed_ms,
                usage: failure.usage,
                outcome: evaluation_failure(failure.failure),
            },
            Ok(observed) => {
                let served_model = self.safe_served_model(observed.served_model.clone());
                let score = observed.score;
                let usage = observed.usage;
                let outcome = match self.observed_model(observed.served_model.as_deref()) {
                    Err(ScorerError::BackendUnavailable) => CloudEvaluationOutcome::Failure {
                        kind: CloudEvaluationFailureKind::ProviderMalformedResponse,
                        http_status: None,
                    },
                    Ok(model) if model != self.model => CloudEvaluationOutcome::Failure {
                        kind: CloudEvaluationFailureKind::ModelIdentityMismatch,
                        http_status: None,
                    },
                    Ok(_) => match self.scoring.verdict_for_scores(&[score]) {
                        Ok(_) => CloudEvaluationOutcome::Success,
                        Err(ContractFailure::InvalidScore(ScoreFailureKind::Shape)) => {
                            CloudEvaluationOutcome::Failure {
                                kind: CloudEvaluationFailureKind::InvalidScoreShape,
                                http_status: None,
                            }
                        }
                        Err(ContractFailure::InvalidScore(ScoreFailureKind::NonFinite)) => {
                            CloudEvaluationOutcome::Failure {
                                kind: CloudEvaluationFailureKind::NonFiniteScore,
                                http_status: None,
                            }
                        }
                        Err(ContractFailure::InvalidScore(ScoreFailureKind::OutOfDomain)) => {
                            CloudEvaluationOutcome::Failure {
                                kind: CloudEvaluationFailureKind::ScoreOutOfDomain,
                                http_status: None,
                            }
                        }
                        Err(_) => CloudEvaluationOutcome::Failure {
                            kind: CloudEvaluationFailureKind::ProviderMalformedResponse,
                            http_status: None,
                        },
                    },
                };
                CloudEvaluationObservation {
                    requested_model,
                    served_model,
                    score: Some(score),
                    attempts,
                    elapsed_ms,
                    usage,
                    outcome,
                }
            }
        }
    }

    /// Only provider model identifiers that satisfy the same bounded component contract may enter
    /// an eval archive. Invalid arbitrary response text remains body-free by becoming `None`.
    fn safe_served_model(&self, served: Option<String>) -> Option<String> {
        served.filter(|model| {
            model == &self.provider.model
                || ComponentIdentity::new(model.as_str(), SERVED_MODEL_DRIFT_REVISION).is_ok()
        })
    }

    /// Reports the configured identity when the served model still matches, and the observed one
    /// when it does not, so the service emits its typed model-identity mismatch instead of a
    /// generic backend failure.
    ///
    /// Descriptor validation already pinned the configured identity to the requested model, so a
    /// reply that names any other model is real drift regardless of the configured mode. The mode
    /// only decides whether a reply that names no model at all is acceptable.
    fn observed_model(&self, served: Option<&str>) -> Result<ModelIdentity, ScorerError> {
        match served {
            Some(model) if model == self.provider.model => return Ok(self.model.clone()),
            None if matches!(
                self.provider.served_model,
                ServedModelCheck::ProviderManaged
            ) =>
            {
                return Ok(self.model.clone());
            }
            _ => {}
        }
        let observed = ComponentIdentity::new(
            served.unwrap_or(SERVED_MODEL_ABSENT),
            SERVED_MODEL_DRIFT_REVISION,
        )
        .map_err(|_| ScorerError::BackendUnavailable)?;
        let drifted = ModelIdentity::new(observed, self.model.tokenizer.clone());
        if drifted == self.model {
            return Err(ScorerError::BackendUnavailable);
        }
        Ok(drifted)
    }
}

/// Reads at most [`MAX_RESPONSE_BYTES`] so a hostile or broken provider cannot stream unbounded
/// data into the service.
async fn read_bounded(mut response: HttpResponse) -> Result<Vec<u8>, CloudFailure> {
    let mut body = Vec::new();
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| CloudFailure::Transport)?
    {
        if body.len().saturating_add(chunk.len()) > MAX_RESPONSE_BYTES {
            return Err(CloudFailure::Malformed);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body)
}

fn report_attempt(attempt: u8) {
    // Emitted before building/sending each HTTP attempt so an outer process timeout can count its
    // maximum possible billable exposure even when no terminal JSON observation is produced.
    eprintln!("publication_critic_cloud_attempt attempt={attempt}");
}

fn report_call(attempts: u8, elapsed_ms: u64, observed: &ObservedCompletion) {
    let usage = observed.usage.as_ref();
    eprintln!(
        "publication_critic_cloud_call attempts={attempts} elapsed_ms={elapsed_ms} prompt_tokens={} completion_tokens={} total_tokens={} prompt_cache_hit_tokens={} prompt_cache_miss_tokens={}",
        usage_field(usage.and_then(|value| value.prompt_tokens)),
        usage_field(usage.and_then(|value| value.completion_tokens)),
        usage_field(usage.and_then(|value| value.total_tokens)),
        usage_field(usage.and_then(|value| value.prompt_cache_hit_tokens)),
        usage_field(usage.and_then(|value| value.prompt_cache_miss_tokens)),
    );
}

fn report_failure(attempts: u8, elapsed_ms: u64, observed: &ObservedFailure) {
    let failure = observed.failure;
    let usage = observed.usage.as_ref();
    eprintln!(
        "publication_critic_cloud_failed attempts={attempts} elapsed_ms={elapsed_ms} kind={} status={} prompt_tokens={} completion_tokens={} total_tokens={} prompt_cache_hit_tokens={} prompt_cache_miss_tokens={}",
        failure.log_code(),
        match failure {
            CloudFailure::Status { code } => code.to_string(),
            CloudFailure::Transport | CloudFailure::Malformed => "none".to_string(),
        },
        usage_field(usage.and_then(|value| value.prompt_tokens)),
        usage_field(usage.and_then(|value| value.completion_tokens)),
        usage_field(usage.and_then(|value| value.total_tokens)),
        usage_field(usage.and_then(|value| value.prompt_cache_hit_tokens)),
        usage_field(usage.and_then(|value| value.prompt_cache_miss_tokens)),
    );
}

fn elapsed_ms(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX)
}

fn usage_field(value: Option<u64>) -> String {
    value.map_or_else(|| "none".to_string(), |value| value.to_string())
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum CloudFailure {
    /// Connection, TLS, timeout, or stream failure with no provider status.
    Transport,
    /// Complete non-2xx response.
    Status { code: u16 },
    /// A 2xx response whose body cannot be projected to exactly one finite scalar.
    Malformed,
}

impl CloudFailure {
    /// Only transient transport and throttling faults are worth another attempt. Authentication,
    /// schema, and deterministic projection faults are never retried.
    fn retryable(self) -> bool {
        match self {
            Self::Transport => true,
            Self::Status { code } => RETRYABLE_STATUS.contains(&code),
            Self::Malformed => false,
        }
    }

    fn log_code(self) -> &'static str {
        match self {
            Self::Transport => "transport",
            Self::Status { .. } => "status",
            Self::Malformed => "malformed",
        }
    }
}

struct ObservedCompletion {
    served_model: Option<String>,
    score: f64,
    usage: Option<CloudTokenUsage>,
}

struct ObservedFailure {
    failure: CloudFailure,
    served_model: Option<String>,
    usage: Option<CloudTokenUsage>,
}

impl ObservedFailure {
    fn without_metadata(failure: CloudFailure) -> Self {
        Self {
            failure,
            served_model: None,
            usage: None,
        }
    }
}

struct CloudCallObservation {
    outcome: Result<ObservedCompletion, ObservedFailure>,
    attempts: u8,
    elapsed_ms: u64,
}

#[derive(Serialize)]
struct ChatCompletionsRequest {
    model: String,
    messages: Vec<ChatRequestMessage>,
    temperature: f64,
    max_tokens: u32,
    stream: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    response_format: Option<ResponseFormat>,
}

#[derive(Serialize)]
struct ChatRequestMessage {
    role: &'static str,
    content: String,
}

#[derive(Serialize)]
struct ResponseFormat {
    #[serde(rename = "type")]
    format: &'static str,
}

#[derive(Deserialize)]
struct ChatCompletionsResponse {
    model: Option<String>,
    choices: Vec<ChatChoice>,
    usage: Option<ChatUsage>,
}

impl ChatCompletionsResponse {
    fn into_observed(self) -> Result<ObservedCompletion, ObservedFailure> {
        let served_model = self.model;
        let usage = self.usage.map(CloudTokenUsage::from);
        match parse_quality_choice(self.choices) {
            Ok(score) => Ok(ObservedCompletion {
                served_model,
                score,
                usage,
            }),
            Err(failure) => Err(ObservedFailure {
                failure,
                served_model,
                usage,
            }),
        }
    }
}

fn parse_quality_choice(choices: Vec<ChatChoice>) -> Result<f64, CloudFailure> {
    let [choice] = <[ChatChoice; 1]>::try_from(choices).map_err(|_| CloudFailure::Malformed)?;
    if choice.finish_reason.as_deref() != Some("stop") {
        return Err(CloudFailure::Malformed);
    }
    let content = choice.message.content.ok_or(CloudFailure::Malformed)?;
    cloud_template::parse_quality_scalar(&content).ok_or(CloudFailure::Malformed)
}

#[derive(Deserialize)]
struct ChatChoice {
    message: ChatChoiceMessage,
    finish_reason: Option<String>,
}

#[derive(Deserialize)]
struct ChatChoiceMessage {
    content: Option<String>,
}

#[derive(Deserialize)]
struct ChatUsage {
    prompt_tokens: Option<u64>,
    completion_tokens: Option<u64>,
    total_tokens: Option<u64>,
    prompt_cache_hit_tokens: Option<u64>,
    prompt_cache_miss_tokens: Option<u64>,
}

impl From<ChatUsage> for CloudTokenUsage {
    fn from(value: ChatUsage) -> Self {
        Self {
            prompt_tokens: value.prompt_tokens,
            completion_tokens: value.completion_tokens,
            total_tokens: value.total_tokens,
            prompt_cache_hit_tokens: value.prompt_cache_hit_tokens,
            prompt_cache_miss_tokens: value.prompt_cache_miss_tokens,
        }
    }
}

fn evaluation_failure(failure: CloudFailure) -> CloudEvaluationOutcome {
    match failure {
        CloudFailure::Transport => CloudEvaluationOutcome::Failure {
            kind: CloudEvaluationFailureKind::ProviderTransport,
            http_status: None,
        },
        CloudFailure::Status { code } => CloudEvaluationOutcome::Failure {
            kind: CloudEvaluationFailureKind::ProviderHttpStatus,
            http_status: Some(code),
        },
        CloudFailure::Malformed => CloudEvaluationOutcome::Failure {
            kind: CloudEvaluationFailureKind::ProviderMalformedResponse,
            http_status: None,
        },
    }
}
