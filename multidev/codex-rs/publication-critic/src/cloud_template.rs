//! Frozen cloud prompt template and its strict single-scalar projection.
//!
//! This template is deliberately not the local reward-model render. It owns its own
//! version-bound identity, it feeds a general chat model the stable JSON projection of the same
//! typed [`PublicationPacket`], and it asks for exactly one `[0, 1]` quality scalar. It makes no
//! claim of token-level equivalence with `rondo-publication-packet-render`, and it never decides
//! the product verdict: the service still applies the configured threshold and pass rule.

use crate::PublicationPacket;
use serde::Deserialize;

/// Identity of the cloud prompt. Changing any frozen byte below requires a new revision.
pub(crate) const CLOUD_TEMPLATE_NAME: &str = "rondo-publication-cloud-template";
pub(crate) const CLOUD_TEMPLATE_REVISION: &str = "v1";

/// Identity of the projection from one provider reply to one scalar.
pub(crate) const CLOUD_PROJECTION_NAME: &str = "rondo-cloud-json-quality-scalar";
pub(crate) const CLOUD_PROJECTION_REVISION: &str = "v1";

/// The declared domain of the projection. A descriptor cannot widen it.
pub(crate) const CLOUD_SCORE_DOMAIN_MIN: f64 = 0.0;
pub(crate) const CLOUD_SCORE_DOMAIN_MAX: f64 = 1.0;

/// Upper bound on the assistant text the strict parser will consider.
const MAX_CONTENT_BYTES: usize = 4 * 1024;

/// Fixed system message: qualification rubric v1 plus the packet and output contracts.
pub(crate) const CLOUD_SYSTEM_MESSAGE: &str = r#"You are the RONDO Publication Critic cloud reference scorer. You receive one JSON publication packet and return one quality scalar for the submitted publication candidate. You are a reference scorer only; you never decide whether the candidate is published.

# Publication Critic qualification rubric v1

Judge only the submitted publication candidate against the public packet. A candidate qualifies only when all five hard requirements hold:

1. Useful state transfer: the summary preserves the concrete state another teammate needs to continue or rely on the work.
2. Honest uncertainty: unknown, suspected, partial, stale, or unavailable facts are described without invented certainty.
3. Conditional continuity: unfinished work has an actionable handoff; completed work may omit the handoff.
4. Scope and signal: the publication stays relevant to its local scope and does not bury the useful state in a process dump.
5. Internal consistency: title, summary, handoff, and any provided continuity agree with one another.

Style preferences are not qualification requirements. Do not reward or reject a candidate merely for tone, formatting, brevity, or wording when the five requirements are otherwise satisfied.

# Evidence boundary

Use only the public packet. The evidence envelope may say that prior publications have no Fact references or that references are present, and may expose a visible count plus whether more were omitted. It does not expose Fact identifiers, producer, locator, tool, category, observation text, private traces, transcripts, reasoning, or supervision metadata.

Do not claim to verify factual truth, freshness, applicability, or claim-to-Fact entailment. Semantic entailment is not evaluated in evidence v1, observation availability remains unknown, and the candidate window was not frozen before commit. Treat absent, partial, stale, unavailable, and omitted context as explicit limits rather than evidence of truth or falsehood.

# Packet fields

- `local_scope.title` is the canonical title of the work; `candidate.summary` and the optional `candidate.handoff` are the submitted candidate.
- `actor_role` is `root` or `member`; `target_kind` is `new_event` or `existing_event`.
- `continuity` is `not_applicable` for a new event, otherwise the typed `available` or `unavailable` envelope with coverage, freshness, revision, and at most four oldest-to-newest prior publications.
- `evidence_v1` and `qualification` are fixed policy markers, not content to judge.

# Output contract

Reply with exactly one JSON object and nothing else:

{"quality": 0.42}

`quality` is a single number in the closed interval [0, 1]; higher means the candidate is more likely to satisfy all five hard requirements. Emit no other key, no prose, no explanation, and no code fence. Do not emit a verdict, a label, or a threshold decision."#;

/// The stable JSON projection of one packet, used as the single user message.
pub(crate) fn render_user_message(packet: &PublicationPacket) -> Option<String> {
    serde_json::to_string(packet).ok()
}

/// The only accepted reply shape: exactly one finite `quality` number and no other field.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct CloudQualityScalar {
    quality: f64,
}

/// Strictly projects assistant text to one finite scalar.
///
/// Domain membership is deliberately not checked here. A finite but out-of-domain number is a
/// real provider observation, and the service owns the typed out-of-domain failure.
pub(crate) fn parse_quality_scalar(content: &str) -> Option<f64> {
    let content = content.trim();
    if content.is_empty() || content.len() > MAX_CONTENT_BYTES {
        return None;
    }
    let parsed: CloudQualityScalar = serde_json::from_str(content).ok()?;
    parsed.quality.is_finite().then_some(parsed.quality)
}

#[cfg(test)]
#[path = "cloud_template_tests.rs"]
mod tests;
