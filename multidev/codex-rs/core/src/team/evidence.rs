//! Anchoring team versions to observations Codex actually kept.
//!
//! Capture happens in two steps because those two steps know different things. When a tool call
//! completes, the harness knows which tool ran, that it ran to completion rather than being
//! abandoned, and what shape its result has — that is where an observation is *noted*. When the
//! result reaches conversation history, the harness knows the observation was really retained — that
//! is where a fact is *minted*, and where its ordinal comes from. Splitting them is what keeps a
//! reference from claiming to be available before anything has been kept.
//!
//! Resolution goes the other way: a locator names one retained item in one participant's history, and
//! reading it returns that item's bounded text and nothing that happens to sit next to it.

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::registry::AnyToolResult;
use codex_protocol::models::FunctionCallOutputBody;
use codex_protocol::models::ResponseItem;
use codex_team_state::FactCategory;
use codex_team_state::FactView;
use codex_team_state::ObservationLocator;
use codex_team_state::RetainedOutputKind;

/// Hard ceiling on the text one evidence read returns.
///
/// A drill-down answers "what did you see" for one observation, so it is bounded on its own terms
/// rather than by whatever the producer's tool happened to print. Anything cut is reported.
pub(crate) const MAX_OBSERVATION_CHARS: usize = 4_000;

/// The terminal outcome a tool handler produced for the model.
///
/// A handler that fails is as much an observation as one that succeeds — a command exiting non-zero
/// is exactly the kind of thing a team version needs to be able to point at — but the two arrive
/// differently: one carries its own output and decides for itself whether it succeeded, the other is
/// turned into a failed text result by the host.
pub(crate) enum CompletedToolResult<'a> {
    Output(&'a AnyToolResult),
    Failure,
}

/// Note a completed tool result so it can become evidence once Codex has retained it.
///
/// Called only where a tool handler has really produced a terminal outcome, which is what keeps an
/// abandoned call — whose response is written by the host after the dispatch is given up on — from
/// leaving evidence behind. Three further exclusions are decided here, at the only point where all
/// three are knowable: nested code-mode calls (their retained observation is the cell's own result,
/// not each step inside it), the team tools and the evidence read itself (a drill-down that produced
/// more evidence would make every read generate another thing to read), and every result shape
/// outside the supported set.
pub(crate) fn note_completed_tool_result(
    invocation: &ToolInvocation,
    result: CompletedToolResult<'_>,
) {
    if !super::team_state_enabled(&invocation.turn) {
        return;
    }
    if !matches!(
        invocation.source,
        ToolCallSource::Direct | ToolCallSource::DirectPlaintextMessage
    ) {
        return;
    }
    if crate::tools::handlers::team_tools::is_team_tool(&invocation.tool_name) {
        return;
    }
    let Ok(access) = super::TeamAccess::resolve(&invocation.session) else {
        return;
    };

    let (call_id, output_kind, category) = match result {
        CompletedToolResult::Output(result) => {
            let item = ResponseItem::from(
                result
                    .result
                    .to_response_item(&result.call_id, &result.payload),
            );
            let Some(observation) = supported_observation(&item) else {
                return;
            };
            (
                observation.call_id.to_string(),
                observation.output_kind,
                observation.category,
            )
        }
        // The host answers a failing handler with the error text in the same shape the payload
        // implies, always as text and always marked unsuccessful, so the classification is settled
        // without waiting to see the message.
        CompletedToolResult::Failure => {
            let output_kind = match invocation.payload {
                ToolPayload::Function { .. } => RetainedOutputKind::FunctionCallOutput,
                ToolPayload::Custom { .. } => RetainedOutputKind::CustomToolCallOutput,
                ToolPayload::ToolSearch { .. } => return,
            };
            if invocation.call_id.is_empty() {
                return;
            }
            (
                invocation.call_id.clone(),
                output_kind,
                FactCategory::ToolResultFailure,
            )
        }
    };
    access.handle().note_observation(
        access.actor(),
        category,
        ObservationLocator {
            call_id,
            output_kind,
            tool: invocation.tool_name.name.clone(),
        },
    );
}

/// Mint facts for the supported tool results in `items` that this session really retained.
///
/// Called from the retention boundary itself, so the ordinals facts receive follow Codex's retention
/// order. The history that was just written is consulted rather than assumed: a reference is only
/// worth having if the thing it points at was kept.
pub(crate) async fn record_retained_tool_facts(
    session: &Session,
    turn_context: &TurnContext,
    items: &[ResponseItem],
) {
    if !super::team_state_enabled(turn_context) {
        return;
    }
    let candidates: Vec<(String, RetainedOutputKind)> = items
        .iter()
        .filter_map(supported_observation)
        .map(|observation| (observation.call_id.to_string(), observation.output_kind))
        .collect();
    if candidates.is_empty() {
        return;
    }
    let Ok(access) = super::TeamAccess::resolve(session) else {
        return;
    };
    for (call_id, output_kind) in candidates {
        if !session.retains_tool_output(&call_id, output_kind).await {
            continue;
        }
        if let Some(fact_id) = access
            .handle()
            .confirm_observation(access.actor(), &call_id)
        {
            tracing::debug!(
                %fact_id,
                call_id,
                "recorded team evidence for a retained tool result"
            );
        }
    }
}

/// What resolving one fact's locator produced.
pub(crate) enum ObservationRead {
    /// The retained text, clamped to [`MAX_OBSERVATION_CHARS`].
    Retained { text: String, total_chars: usize },
    /// The producer still holds a history, and the item this locator names is no longer in it.
    /// Compaction and rollback do not put items back, so this is final.
    Gone,
    /// The producer is not loaded right now, so nothing can be read for it this turn. The reference
    /// is not written off: the same member reloaded into this live root tree can answer again.
    ProducerNotLoaded,
}

/// Resolve one fact to the observation it points at.
///
/// Permission has already been decided by the team state; this only fetches. It reads the single
/// retained item the locator names, from the history of the participant that produced it, and returns
/// nothing else — not the call's arguments, not the items around it, not the producer's transcript.
pub(crate) async fn read_observation(session: &Session, fact: &FactView) -> ObservationRead {
    let producer = if fact.producer == session.thread_id {
        None
    } else {
        match session
            .services
            .agent_control
            .loaded_session(fact.producer)
            .await
        {
            Some(loaded) => Some(loaded),
            None => return ObservationRead::ProducerNotLoaded,
        }
    };
    let producer = producer.as_deref().unwrap_or(session);
    let Some(text) = producer
        .retained_tool_output(&fact.locator.call_id, fact.locator.output_kind)
        .await
    else {
        return ObservationRead::Gone;
    };

    let total_chars = text.chars().count();
    let text = if total_chars > MAX_OBSERVATION_CHARS {
        text.chars().take(MAX_OBSERVATION_CHARS).collect()
    } else {
        text
    };
    ObservationRead::Retained { text, total_chars }
}

/// The retained text of the one item this call id and shape name, if `items` still holds it.
///
/// The first match wins, which keeps resolution deterministic if a history somehow carries the same
/// call id twice.
pub(crate) fn retained_output_text(
    items: &[ResponseItem],
    call_id: &str,
    output_kind: RetainedOutputKind,
) -> Option<String> {
    items.iter().find_map(|item| {
        let observation = supported_observation(item)?;
        (observation.call_id == call_id && observation.output_kind == output_kind)
            .then(|| observation.text.to_string())
    })
}

/// One supported observation, borrowed from the retained item that carries it.
struct Observation<'a> {
    call_id: &'a str,
    output_kind: RetainedOutputKind,
    category: FactCategory,
    text: &'a str,
}

/// Classify a retained item as a supported observation, or not one at all.
///
/// The support set is deliberately narrow: a completed tool call whose retained body is plain text.
/// The content-item shape is what carries images and other media, so it is excluded whole rather
/// than salvaged for its text parts — a fact has to describe what the model actually saw.
fn supported_observation(item: &ResponseItem) -> Option<Observation<'_>> {
    let (call_id, output_kind, output) = match item {
        ResponseItem::FunctionCallOutput {
            call_id, output, ..
        } => (call_id, RetainedOutputKind::FunctionCallOutput, output),
        ResponseItem::CustomToolCallOutput {
            call_id, output, ..
        } => (call_id, RetainedOutputKind::CustomToolCallOutput, output),
        ResponseItem::AdditionalTools { .. }
        | ResponseItem::Message { .. }
        | ResponseItem::AgentMessage { .. }
        | ResponseItem::Reasoning { .. }
        | ResponseItem::LocalShellCall { .. }
        | ResponseItem::FunctionCall { .. }
        | ResponseItem::ToolSearchCall { .. }
        | ResponseItem::ToolSearchOutput { .. }
        | ResponseItem::CustomToolCall { .. }
        | ResponseItem::WebSearchCall { .. }
        | ResponseItem::ImageGenerationCall { .. }
        | ResponseItem::Compaction { .. }
        | ResponseItem::CompactionTrigger { .. }
        | ResponseItem::ContextCompaction { .. }
        | ResponseItem::Other => return None,
    };
    if call_id.is_empty() {
        return None;
    }
    let FunctionCallOutputBody::Text(text) = &output.body else {
        return None;
    };
    // `success: None` means the tool did not classify itself, which every other surface reads as a
    // success; evidence follows the same convention rather than inventing a third state.
    let category = if output.success.unwrap_or(true) {
        FactCategory::ToolResultSuccess
    } else {
        FactCategory::ToolResultFailure
    };
    Some(Observation {
        call_id,
        output_kind,
        category,
        text,
    })
}

#[cfg(test)]
#[path = "evidence_tests.rs"]
mod tests;
