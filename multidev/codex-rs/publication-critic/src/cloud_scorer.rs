//! Cloud reference scorer backend.
//!
//! This is a sibling of the local worker backend: it satisfies the same [`PublicationScorer`]
//! contract, is driven by the same service, and returns either exactly one scalar or a body-free
//! typed failure. Provider request and response bodies, the credential, and provider error text
//! never leave this module.

use crate::ComponentIdentity;
use crate::ModelIdentity;
use crate::PublicationPacket;
use crate::PublicationScorer;
use crate::RawScorerOutput;
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
    model: ModelIdentity,
    scoring: ScoringIdentity,
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
                model: descriptor.identity.model.clone(),
                scoring: descriptor.identity.scoring.clone(),
            }),
        })
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
        let request = self.build_request(user);
        let started = Instant::now();
        let mut attempt = 1_u8;
        loop {
            match self.attempt(&request).await {
                Ok(observed) => {
                    report_call(attempt, started, &observed);
                    return self.output(observed);
                }
                Err(failure) => {
                    if attempt >= self.provider.max_attempts || !failure.retryable() {
                        report_failure(attempt, started, failure);
                        return Err(ScorerError::BackendUnavailable);
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
    ) -> Result<ObservedCompletion, CloudFailure> {
        let response = self
            .client
            .post(&self.request_url)
            .bearer_auth(&self.api_key)
            .timeout(Duration::from_millis(self.provider.request_timeout_ms))
            .json(request)
            .send()
            .await
            .map_err(|_| CloudFailure::Transport)?;
        let status = response.status();
        if !status.is_success() {
            // The provider error body is deliberately dropped unread: only the status code is
            // safe to surface.
            return Err(CloudFailure::Status {
                code: status.as_u16(),
            });
        }
        let body = read_bounded(response).await?;
        let parsed: ChatCompletionsResponse =
            serde_json::from_slice(&body).map_err(|_| CloudFailure::Malformed)?;
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

fn report_call(attempts: u8, started: Instant, observed: &ObservedCompletion) {
    eprintln!(
        "publication_critic_cloud_call attempts={attempts} elapsed_ms={} prompt_tokens={} completion_tokens={}",
        started.elapsed().as_millis(),
        usage_field(observed.prompt_tokens),
        usage_field(observed.completion_tokens),
    );
}

fn report_failure(attempts: u8, started: Instant, failure: CloudFailure) {
    eprintln!(
        "publication_critic_cloud_failed attempts={attempts} elapsed_ms={} kind={} status={}",
        started.elapsed().as_millis(),
        failure.log_code(),
        match failure {
            CloudFailure::Status { code } => code.to_string(),
            CloudFailure::Transport | CloudFailure::Malformed => "none".to_string(),
        },
    );
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
    prompt_tokens: Option<u64>,
    completion_tokens: Option<u64>,
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
    fn into_observed(self) -> Result<ObservedCompletion, CloudFailure> {
        let [choice] =
            <[ChatChoice; 1]>::try_from(self.choices).map_err(|_| CloudFailure::Malformed)?;
        if choice
            .finish_reason
            .as_deref()
            .is_some_and(|reason| reason != "stop")
        {
            return Err(CloudFailure::Malformed);
        }
        let content = choice.message.content.ok_or(CloudFailure::Malformed)?;
        let score =
            cloud_template::parse_quality_scalar(&content).ok_or(CloudFailure::Malformed)?;
        let (prompt_tokens, completion_tokens) = self.usage.map_or((None, None), |usage| {
            (usage.prompt_tokens, usage.completion_tokens)
        });
        Ok(ObservedCompletion {
            served_model: self.model,
            score,
            prompt_tokens,
            completion_tokens,
        })
    }
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
}
