//! Frozen configuration and identity honesty rules for the cloud reference scorer backend.
//!
//! A cloud descriptor is the explicit, opt-in selection of this backend. Nothing here is read
//! unless a caller already decided to run the cloud service, so the absent, controlled, and local
//! worker backends never require a cloud credential and never resolve a provider endpoint.

use crate::ComponentIdentity;
use crate::ContractFailure;
use crate::ModelIdentity;
use crate::ScoreDomain;
use crate::ScoringIdentity;
use crate::ServiceDescriptor;
use crate::cloud_template::CLOUD_PROJECTION_NAME;
use crate::cloud_template::CLOUD_PROJECTION_REVISION;
use crate::cloud_template::CLOUD_SCORE_DOMAIN_MAX;
use crate::cloud_template::CLOUD_SCORE_DOMAIN_MIN;
use crate::cloud_template::CLOUD_TEMPLATE_NAME;
use crate::cloud_template::CLOUD_TEMPLATE_REVISION;
use serde::Deserialize;
use serde::Serialize;
use std::net::IpAddr;
use thiserror::Error;
use url::Url;

/// Frozen backend protocol shared by the cloud descriptor and the cloud service launcher.
pub const CLOUD_BACKEND_PROTOCOL: &str = "rondo-publication-critic-cloud-v1";

/// The only tokenizer component a cloud descriptor may declare.
///
/// A hosted provider cannot prove which tokenizer revision served a request, so the identity says
/// so instead of borrowing an exact-looking revision from a local artifact. The service equality
/// check therefore only confirms that the configured identity is consistent end to end; it is not
/// evidence about the provider.
pub(crate) const PROVIDER_MANAGED_TOKENIZER_NAME: &str = "provider-managed-tokenizer";
pub(crate) const PROVIDER_MANAGED_TOKENIZER_REVISION: &str = "unverifiable";

/// Every cloud scalar definition declares itself a non-final reference scorer.
pub(crate) const CLOUD_DEFINITION_PREFIX: &str = "rondo-cloud-reference-";

const MAX_BASE_URL_BYTES: usize = 512;
const MAX_MODEL_BYTES: usize = 128;
const MAX_ENV_NAME_BYTES: usize = 64;
const MAX_API_KEY_BYTES: usize = 1024;
const MAX_ATTEMPTS: u8 = 4;
const MAX_RETRY_BACKOFF_MS: u64 = 5_000;
const MAX_OUTPUT_TOKENS: u32 = 4_096;
const MAX_TEMPERATURE: f64 = 2.0;

#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum CloudScorerConfigError {
    #[error("publication critic cloud descriptor is invalid")]
    InvalidDescriptor,
    #[error("publication critic cloud identity misrepresents provider-managed components")]
    DishonestIdentity,
    #[error("publication critic cloud endpoint is unsafe")]
    UnsafeEndpoint,
    #[error("publication critic cloud credential is missing or malformed")]
    InvalidCredential,
    #[error("publication critic cloud client could not be constructed")]
    ClientUnavailable,
}

/// Wire shape of the provider request.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CloudApiShape {
    /// OpenAI-compatible `POST {base_url}/chat/completions`.
    ChatCompletions,
}

/// Whether the request asks the provider to constrain its reply to a JSON object.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum CloudResponseFormat {
    JsonObject,
    /// Send no `response_format`. The strict projection still requires a bare JSON object.
    Unconstrained,
}

/// Whether the provider reply carries a served model id that can be compared.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ServedModelCheck {
    /// The provider echoes the served model id, so an observed change is real drift.
    Echoed,
    /// The provider does not expose a verifiable served model id.
    ProviderManaged,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CloudProviderConfig {
    pub(crate) api: CloudApiShape,
    pub(crate) base_url: String,
    pub(crate) api_key_env: String,
    pub(crate) model: String,
    pub(crate) served_model: ServedModelCheck,
    pub(crate) response_format: CloudResponseFormat,
    pub(crate) max_output_tokens: u32,
    pub(crate) temperature: f64,
    pub(crate) request_timeout_ms: u64,
    pub(crate) max_attempts: u8,
    pub(crate) retry_backoff_ms: u64,
}

impl CloudProviderConfig {
    /// Validates the provider contract against the service job deadline that will bound it.
    fn validate(&self, job_timeout_ms: u64) -> Result<(), CloudScorerConfigError> {
        validate_endpoint(&self.base_url)?;
        if self.api_key_env.is_empty()
            || self.api_key_env.len() > MAX_ENV_NAME_BYTES
            || !is_env_name(&self.api_key_env)
            || self.model.is_empty()
            || self.model.len() > MAX_MODEL_BYTES
            || !self.model.bytes().all(|byte| byte.is_ascii_graphic())
            || self.max_output_tokens == 0
            || self.max_output_tokens > MAX_OUTPUT_TOKENS
            || !self.temperature.is_finite()
            || !(0.0..=MAX_TEMPERATURE).contains(&self.temperature)
            || self.max_attempts == 0
            || self.max_attempts > MAX_ATTEMPTS
            || self.retry_backoff_ms > MAX_RETRY_BACKOFF_MS
            || self.request_timeout_ms == 0
        {
            return Err(CloudScorerConfigError::InvalidDescriptor);
        }
        if self
            .worst_case_budget_ms()
            .is_none_or(|budget| budget > job_timeout_ms)
        {
            return Err(CloudScorerConfigError::InvalidDescriptor);
        }
        Ok(())
    }

    /// Every attempt plus every backoff must still fit inside one service job deadline, so a
    /// retrying call can never outlive the deadline the service already advertises.
    fn worst_case_budget_ms(&self) -> Option<u64> {
        let attempts = u64::from(self.max_attempts);
        self.request_timeout_ms
            .checked_mul(attempts)?
            .checked_add(self.retry_backoff_ms.checked_mul(attempts - 1)?)
    }

    /// The exact URL this backend posts to.
    pub(crate) fn request_url(&self) -> Result<Url, CloudScorerConfigError> {
        let path = match self.api {
            CloudApiShape::ChatCompletions => "chat/completions",
        };
        validate_endpoint(&format!("{}/{path}", self.base_url.trim_end_matches('/')))
    }
}

/// Frozen cloud backend identity: provider contract plus the service descriptor it serves.
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CloudScorerDescriptor {
    backend_protocol: String,
    provider: CloudProviderConfig,
    service_descriptor: ServiceDescriptor,
}

impl CloudScorerDescriptor {
    pub fn validate(&self) -> Result<(), CloudScorerConfigError> {
        if self.backend_protocol != CLOUD_BACKEND_PROTOCOL {
            return Err(CloudScorerConfigError::InvalidDescriptor);
        }
        self.service_descriptor
            .validate()
            .map_err(|_| CloudScorerConfigError::InvalidDescriptor)?;
        validate_cloud_identity(&self.service_descriptor)?;
        self.provider
            .validate(self.service_descriptor.limits.job_timeout_ms())
    }

    pub fn service_descriptor(&self) -> &ServiceDescriptor {
        &self.service_descriptor
    }

    /// Name of the single allowlisted environment variable this backend needs.
    pub fn api_key_env(&self) -> &str {
        &self.provider.api_key_env
    }

    pub(crate) fn provider(&self) -> &CloudProviderConfig {
        &self.provider
    }
}

/// A validated descriptor bound to one credential value.
///
/// This type intentionally has no `Debug` implementation because it holds the credential.
pub struct CloudScorerConfig {
    pub(crate) descriptor: CloudScorerDescriptor,
    pub(crate) request_url: String,
    /// A loopback provider is a hermetic fixture, so it must bypass proxy discovery.
    pub(crate) loopback_provider: bool,
    pub(crate) api_key: String,
}

impl CloudScorerConfig {
    /// Binds the descriptor to the credential the parent process injected for it.
    ///
    /// This reads exactly one named process environment variable. It never opens, searches, or
    /// parses a repository secret file: injecting only the required variable is the launching
    /// context's responsibility.
    pub fn from_process_env(
        descriptor: CloudScorerDescriptor,
    ) -> Result<Self, CloudScorerConfigError> {
        descriptor.validate()?;
        let api_key = std::env::var(&descriptor.provider.api_key_env)
            .map_err(|_| CloudScorerConfigError::InvalidCredential)?;
        Self::new(descriptor, api_key)
    }

    pub fn new(
        descriptor: CloudScorerDescriptor,
        api_key: String,
    ) -> Result<Self, CloudScorerConfigError> {
        descriptor.validate()?;
        if api_key.is_empty()
            || api_key.len() > MAX_API_KEY_BYTES
            || !api_key.bytes().all(|byte| byte.is_ascii_graphic())
        {
            return Err(CloudScorerConfigError::InvalidCredential);
        }
        let request_url = descriptor.provider.request_url()?;
        let loopback_provider = request_url.host_str().is_some_and(is_loopback_host);
        Ok(Self {
            descriptor,
            request_url: request_url.into(),
            loopback_provider,
            api_key,
        })
    }
}

/// Builds the frozen cloud scoring identity of one reference scorer.
///
/// The template, projection, and `[0, 1]` domain are fixed by the cloud template revision, and
/// the `rondo-cloud-reference-` prefix is added here, so a cloud descriptor cannot claim the local
/// reward-model render or a final calibrated definition. `threshold` is an explicitly non-final
/// reference operating point: it selects `PASS` versus `REWRITE` for this backend only.
pub fn cloud_reference_scoring_identity(
    definition_suffix: &str,
    definition_revision: &str,
    threshold: f64,
) -> Result<ScoringIdentity, ContractFailure> {
    ScoringIdentity::new(
        ComponentIdentity::new(
            format!("{CLOUD_DEFINITION_PREFIX}{definition_suffix}"),
            definition_revision,
        )?,
        ComponentIdentity::new(CLOUD_TEMPLATE_NAME, CLOUD_TEMPLATE_REVISION)?,
        ComponentIdentity::new(CLOUD_PROJECTION_NAME, CLOUD_PROJECTION_REVISION)?,
        ScoreDomain::new(CLOUD_SCORE_DOMAIN_MIN, CLOUD_SCORE_DOMAIN_MAX)?,
        threshold,
    )
}

/// Builds the model identity of a hosted model whose tokenizer cannot be verified.
///
/// The tokenizer component is a fixed `provider-managed-tokenizer@unverifiable` marker, not a
/// checked tokenizer revision. `model` and `revision` describe what this backend requests from the
/// provider; they are not proof of what the provider served.
pub fn provider_managed_model_identity(
    model: &str,
    revision: &str,
) -> Result<ModelIdentity, ContractFailure> {
    Ok(ModelIdentity::new(
        ComponentIdentity::new(model, revision)?,
        ComponentIdentity::new(
            PROVIDER_MANAGED_TOKENIZER_NAME,
            PROVIDER_MANAGED_TOKENIZER_REVISION,
        )?,
    ))
}

/// Rejects any endpoint that could carry a credential, downgrade transport, or move the request.
fn validate_endpoint(endpoint: &str) -> Result<Url, CloudScorerConfigError> {
    if endpoint.is_empty()
        || endpoint.len() > MAX_BASE_URL_BYTES
        || !endpoint.bytes().all(|byte| byte.is_ascii_graphic())
    {
        return Err(CloudScorerConfigError::UnsafeEndpoint);
    }
    let url = Url::parse(endpoint).map_err(|_| CloudScorerConfigError::UnsafeEndpoint)?;
    if !url.username().is_empty()
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return Err(CloudScorerConfigError::UnsafeEndpoint);
    }
    let loopback = url.host_str().is_some_and(is_loopback_host);
    match url.scheme() {
        "https" => {}
        // Plain HTTP is accepted only for a loopback provider, which is how the offline suite
        // injects a deterministic fake provider without weakening real outbound traffic.
        "http" if loopback => {}
        _ => return Err(CloudScorerConfigError::UnsafeEndpoint),
    }
    Ok(url)
}

fn is_loopback_host(host: &str) -> bool {
    host.eq_ignore_ascii_case("localhost")
        || host
            .parse::<IpAddr>()
            .is_ok_and(|address| address.is_loopback())
}

fn is_env_name(value: &str) -> bool {
    let mut bytes = value.bytes();
    bytes.next().is_some_and(|byte| byte.is_ascii_uppercase())
        && bytes.all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
}

/// Keeps a cloud descriptor from claiming local-artifact identity or a final calibration.
fn validate_cloud_identity(descriptor: &ServiceDescriptor) -> Result<(), CloudScorerConfigError> {
    let tokenizer = &descriptor.identity.model.tokenizer;
    if tokenizer.name() != PROVIDER_MANAGED_TOKENIZER_NAME
        || tokenizer.revision() != PROVIDER_MANAGED_TOKENIZER_REVISION
    {
        return Err(CloudScorerConfigError::DishonestIdentity);
    }
    let scoring = &descriptor.identity.scoring;
    if scoring.input_template.name() != CLOUD_TEMPLATE_NAME
        || scoring.input_template.revision() != CLOUD_TEMPLATE_REVISION
        || scoring.scalar_projection.name() != CLOUD_PROJECTION_NAME
        || scoring.scalar_projection.revision() != CLOUD_PROJECTION_REVISION
        || !scoring
            .definition
            .name()
            .starts_with(CLOUD_DEFINITION_PREFIX)
        || scoring.domain.min() != CLOUD_SCORE_DOMAIN_MIN
        || scoring.domain.max() != CLOUD_SCORE_DOMAIN_MAX
    {
        return Err(CloudScorerConfigError::DishonestIdentity);
    }
    Ok(())
}

#[cfg(test)]
#[path = "cloud_config_tests.rs"]
mod tests;
