//! Five-dimension output contracts shared by the Plan 100/101 diagnostic and the
//! Plan 102 product five-dimension cloud path.
//!
//! All three diagnostic arms receive the same serialized [`PublicationPacket`] and the same
//! common rubric. The only model-visible difference is the final output contract selected here.
//! The product service consumes [`CloudFiveDimensionDecisions`] and [`local_verdict`] when the
//! cloud descriptor selects the five-dimension scoring contract; scalar and direct-gate arms
//! remain diagnostic-only. Output-contract examples are illegal templates so a model cannot
//! obtain a valid reply by copying them.

use serde::Deserialize;
use serde::Serialize;
use std::str::FromStr;
use thiserror::Error;

use crate::PublicationPacket;

const MAX_CONTENT_BYTES: usize = 4 * 1024;

const COMMON_SYSTEM_MESSAGE: &str = r#"You are the RONDO Publication Critic structured diagnostic. Judge only the submitted candidate and bounded public packet. The following frozen rubric is the model-input projection of `rondo-publication-critic-task@v2`.

# Publication Critic qualification rubric v2

Assess the candidate under these exact hard-requirement semantics:

- `useful_state_transfer`: `PASS` when the local scope contains a concrete result, state, decision, artifact, blocker, or starting point that another worker can rely on; `FAIL` for vague activity or progress with no reusable state.
- `honest_uncertainty`: `PASS` when visible observations, inference, suspicion, unknowns, stale context, and missing context keep their stated certainty; `FAIL` when a visible limit, guess, or unverified mechanism is presented as established fact.
- `conditional_continuity`: `N/A` only when the model-visible candidate clearly and consistently says the work is complete. Otherwise it is applicable: `PASS` when unfinished work gives usable progress, blockage, or the next starting point, and `FAIL` when it cannot be continued. Conflicting completion claims are never `N/A`.
- `scope_and_signal`: `PASS` when the core public state is easy to identify inside the local scope; `FAIL` when process dumps, repetition, or off-scope material overwhelms that state.
- `internal_consistency`: `PASS` when title, summary, handoff, and supplied continuity agree on key completion, verification, and next-action state; `FAIL` when those visible claims conflict.

The first, second, fourth, and fifth decisions are always `PASS` or `FAIL`. Completed work may omit a handoff. A candidate qualifies only when every applicable decision is `PASS`; one applicable `FAIL` requires `REWRITE`. Style, brevity, formality, preferred wording, or any other soft quality cannot compensate for a hard failure and cannot create a PASS-internal qualification ranking.

Use only public packet facts. Do not infer completion or quality from hidden `completion_state`, scenario state, candidate briefs, labels, defects, split, source, generator, reviewer, rationale, or pair direction. Do not verify external truth or claim-to-Fact entailment. A completion claim contradicted by visible packet content remains subject to `internal_consistency` and, when it overstates visible support, `honest_uncertainty`; hidden private truth never changes applicability. Treat stale, partial, unavailable, and omitted context as visible limits, not proof for or against the candidate.

Apply those rules to the specific packet in the user message. Every legal value named by the output contract is available when that packet's visible facts warrant it.

# Output contract

"#;

const SCALAR_OUTPUT_CONTRACT: &str = r#"Reply with exactly one JSON object and nothing else. The angle-bracket template is not valid JSON and must not be copied:

{"quality":<number in [0,1]>}

`quality` must be one finite JSON number in the closed interval [0,1]. Higher means the candidate is more likely to satisfy every applicable hard requirement. Choose a boundary only when every applicable hard requirement clearly fails or clearly holds; otherwise choose an interior value. Emit no other key, prose, explanation, verdict, dimension, confidence, or code fence."#;

const DIRECT_GATE_OUTPUT_CONTRACT: &str = r#"Reply with exactly one JSON object and nothing else. The angle-bracket template is not valid JSON and must not be copied:

{"verdict":<PASS or REWRITE>}

`verdict` must be exactly `PASS` or `REWRITE`. Check this packet against every applicable hard requirement. If any applicable requirement fails, emit REWRITE; if none fail, emit PASS. Emit no other key, scalar, dimension, prose, explanation, confidence, or code fence."#;

const FIVE_DIMENSION_OUTPUT_CONTRACT: &str = r#"Reply with exactly one JSON object and nothing else, containing exactly these five keys. The angle-bracket template is not valid JSON and must not be copied:

{"useful_state_transfer":<PASS or FAIL>,"honest_uncertainty":<PASS or FAIL>,"conditional_continuity":<PASS, FAIL, or N/A>,"scope_and_signal":<PASS or FAIL>,"internal_consistency":<PASS or FAIL>}

Each value except `conditional_continuity` must be exactly `PASS` or `FAIL`. `conditional_continuity` must be exactly `PASS`, `FAIL`, or `N/A`; use `N/A` only when continuity is not applicable. Assign every key from this packet's visible facts. Emit no overall gate, scalar, score, confidence, explanation, prose, or code fence."#;

/// The three output-expression arms of the Plan 100/101 diagnostic.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CloudDiagnosticTask {
    Scalar,
    DirectGate,
    FiveDimension,
}

/// Thinking switch for the Plan 101 diagnostic path and the product five-dimension path.
///
/// Diagnostic requests always send an explicit `thinking.type`. The product five-dimension
/// path always sends `disabled`. The unselected scalar product path still omits this field.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CloudDiagnosticThinking {
    #[default]
    Disabled,
    Enabled,
}

impl CloudDiagnosticThinking {
    pub fn as_request_type(self) -> &'static str {
        match self {
            Self::Disabled => "disabled",
            Self::Enabled => "enabled",
        }
    }
}

/// Exact provider-visible messages for one Plan 100 diagnostic request.
///
/// The offline token recounter obtains these bytes from the same Rust implementation that owns
/// the paid request so prompt reconstruction cannot drift into a second template.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CloudDiagnosticMessages {
    pub system: String,
    pub user: String,
}

/// Renders the two provider-visible messages without constructing a provider client.
pub fn diagnostic_messages(
    packet: &PublicationPacket,
    task: CloudDiagnosticTask,
) -> Option<CloudDiagnosticMessages> {
    Some(CloudDiagnosticMessages {
        system: system_message(task),
        user: serde_json::to_string(packet).ok()?,
    })
}

impl FromStr for CloudDiagnosticTask {
    type Err = CloudDiagnosticTaskParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "a" | "scalar" => Ok(Self::Scalar),
            "b" | "direct-gate" | "direct_gate" => Ok(Self::DirectGate),
            "c" | "five-dimension" | "five_dimension" => Ok(Self::FiveDimension),
            _ => Err(CloudDiagnosticTaskParseError),
        }
    }
}

impl FromStr for CloudDiagnosticThinking {
    type Err = CloudDiagnosticThinkingParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "disabled" | "off" | "thinking_off" => Ok(Self::Disabled),
            "enabled" | "on" | "thinking_on" => Ok(Self::Enabled),
            _ => Err(CloudDiagnosticThinkingParseError),
        }
    }
}

/// A command-line task selector was not one of the three diagnostic arms.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
#[error("publication critic cloud diagnostic task is invalid")]
pub struct CloudDiagnosticTaskParseError;

/// A command-line thinking selector was not `enabled` or `disabled`.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
#[error("publication critic cloud diagnostic thinking is invalid")]
pub struct CloudDiagnosticThinkingParseError;

/// A direct publication gate, also used for the locally derived five-dimension gate.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum CloudDiagnosticVerdict {
    #[serde(rename = "PASS")]
    Pass,
    #[serde(rename = "REWRITE")]
    Rewrite,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum CloudHardDecision {
    #[serde(rename = "PASS")]
    Pass,
    #[serde(rename = "FAIL")]
    Fail,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum CloudContinuityDecision {
    #[serde(rename = "PASS")]
    Pass,
    #[serde(rename = "FAIL")]
    Fail,
    #[serde(rename = "N/A")]
    NotApplicable,
}

/// The exact five decisions accepted from the structured arm.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CloudFiveDimensionDecisions {
    pub useful_state_transfer: CloudHardDecision,
    pub honest_uncertainty: CloudHardDecision,
    pub conditional_continuity: CloudContinuityDecision,
    pub scope_and_signal: CloudHardDecision,
    pub internal_consistency: CloudHardDecision,
}

impl CloudFiveDimensionDecisions {
    /// Applies the task-v2 non-compensating AND locally; the model never supplies this gate.
    pub fn local_verdict(&self) -> CloudDiagnosticVerdict {
        let hard_pass = self.useful_state_transfer == CloudHardDecision::Pass
            && self.honest_uncertainty == CloudHardDecision::Pass
            && self.scope_and_signal == CloudHardDecision::Pass
            && self.internal_consistency == CloudHardDecision::Pass;
        let continuity_pass = matches!(
            self.conditional_continuity,
            CloudContinuityDecision::Pass | CloudContinuityDecision::NotApplicable
        );
        if hard_pass && continuity_pass {
            CloudDiagnosticVerdict::Pass
        } else {
            CloudDiagnosticVerdict::Rewrite
        }
    }

    /// Product typed verdict. Same discrete rule as [`Self::local_verdict`]; no threshold.
    pub fn product_verdict(&self) -> crate::Verdict {
        match self.local_verdict() {
            CloudDiagnosticVerdict::Pass => crate::Verdict::Pass,
            CloudDiagnosticVerdict::Rewrite => crate::Verdict::Rewrite,
        }
    }
}

/// Parsed model output. The tag is local archive metadata, not part of the provider contract.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "type", rename_all = "snake_case")]
pub enum CloudDiagnosticOutput {
    Scalar {
        quality: f64,
    },
    DirectGate {
        verdict: CloudDiagnosticVerdict,
    },
    FiveDimension {
        decisions: CloudFiveDimensionDecisions,
    },
}

/// Body-free failure categories for one diagnostic call.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CloudDiagnosticFailureKind {
    ProviderTransport,
    ProviderHttpStatus,
    ProviderMalformedResponse,
    ModelIdentityMismatch,
    OutputContractViolation,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "type", rename_all = "snake_case")]
pub enum CloudDiagnosticOutcome {
    Success,
    Failure {
        kind: CloudDiagnosticFailureKind,
        http_status: Option<u16>,
    },
}

/// One body-free diagnostic observation. Parsed task output is retained for local metrics.
#[derive(Clone, Debug, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CloudDiagnosticObservation {
    pub task: CloudDiagnosticTask,
    pub requested_model: String,
    pub served_model: Option<String>,
    /// Exact bounded assistant content. It is emitted only to the task-owned ignored receipt;
    /// callers must not forward it to tracked results, ordinary logs, or review messages.
    pub response_text: Option<String>,
    pub output: Option<CloudDiagnosticOutput>,
    pub local_verdict: Option<CloudDiagnosticVerdict>,
    pub attempts: u8,
    pub attempt_requested_at_unix_ms: Vec<u64>,
    pub elapsed_ms: u64,
    pub usage: Option<crate::CloudTokenUsage>,
    pub outcome: CloudDiagnosticOutcome,
}

pub(crate) fn system_message(task: CloudDiagnosticTask) -> String {
    let contract = match task {
        CloudDiagnosticTask::Scalar => SCALAR_OUTPUT_CONTRACT,
        CloudDiagnosticTask::DirectGate => DIRECT_GATE_OUTPUT_CONTRACT,
        CloudDiagnosticTask::FiveDimension => FIVE_DIMENSION_OUTPUT_CONTRACT,
    };
    format!("{COMMON_SYSTEM_MESSAGE}{contract}")
}

pub(crate) fn parse_output(
    task: CloudDiagnosticTask,
    content: &str,
) -> Option<CloudDiagnosticOutput> {
    let content = content.trim();
    if content.is_empty() || content.len() > MAX_CONTENT_BYTES {
        return None;
    }
    match task {
        CloudDiagnosticTask::Scalar => {
            let output: ScalarOutput = serde_json::from_str(content).ok()?;
            (output.quality.is_finite() && (0.0..=1.0).contains(&output.quality)).then_some(
                CloudDiagnosticOutput::Scalar {
                    quality: output.quality,
                },
            )
        }
        CloudDiagnosticTask::DirectGate => {
            let output: DirectGateOutput = serde_json::from_str(content).ok()?;
            Some(CloudDiagnosticOutput::DirectGate {
                verdict: output.verdict,
            })
        }
        CloudDiagnosticTask::FiveDimension => {
            let decisions = serde_json::from_str(content).ok()?;
            Some(CloudDiagnosticOutput::FiveDimension { decisions })
        }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ScalarOutput {
    quality: f64,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DirectGateOutput {
    verdict: CloudDiagnosticVerdict,
}

#[cfg(test)]
#[path = "cloud_diagnostic_tests.rs"]
mod tests;
