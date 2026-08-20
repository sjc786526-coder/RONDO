//! Anchoring team versions to observations Codex actually kept.
//!
//! Capture is split across the places that know different facts. The harness first reserves a unique
//! output item identity. When a handler produces an outcome, it knows which tool ran and what shape
//! its result has — that is where an observation is *noted* against the reserved identity, and where
//! a call the host ends up answering for itself is revoked again. Code mode adds one join: a terminal
//! outer result qualifies only when the same runtime cell completed a supported non-team nested
//! tool. When that exact outer or direct result reaches conversation history, the harness knows it
//! was really retained — that is where a fact is *minted* and numbered. Splitting these boundaries is
//! what keeps a reference from claiming to exist before anything has been kept.
//!
//! Resolution goes the other way: a locator names one retained item in one participant's history, and
//! reading it returns that item's bounded text and nothing that happens to sit next to it. Whether it
//! can be read at all is answered per read, because both ways of failing — a history that no longer
//! carries it, a producer that is not loaded — are about now rather than forever.

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolPayload;
use crate::tools::registry::AnyToolResult;
use codex_protocol::ResponseItemId;
use codex_protocol::models::FunctionCallOutputBody;
use codex_protocol::models::FunctionCallOutputContentItem;
use codex_protocol::models::ResponseItem;
use codex_team_state::FactCategory;
use codex_team_state::FactView;
use codex_team_state::NotedObservation;
use std::borrow::Cow;
use std::collections::HashMap;
use std::sync::Mutex;

/// Hard ceiling on the text one evidence read returns.
///
/// A drill-down answers "what did you see" for one observation, so it is bounded on its own terms
/// rather than by whatever the producer's tool happened to print. Anything cut is reported.
pub(crate) const MAX_OBSERVATION_CHARS: usize = 4_000;
const MAX_PENDING_CODE_MODE_OUTPUTS: usize = 256;

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

/// Session-local provenance for evidence carried by an outer code-mode result.
///
/// The outer `exec`/`wait` result is the item Codex retains, but only the nested dispatch path knows
/// whether the cell actually ran an evidence-producing tool. Keeping that one bit keyed by the
/// runtime cell and binding each model-visible output item to the cell lets the retention path join
/// the two facts without parsing model-authored JavaScript or printed text. Only a terminal response
/// can carry the bit; yielded snapshots are deliberately ineligible because their producer runs in
/// another process and can race ahead of the receiving handler.
#[derive(Default)]
pub(crate) struct CodeModeEvidenceRecorder {
    state: Mutex<CodeModeEvidenceState>,
}

#[derive(Default)]
struct CodeModeEvidenceState {
    cells: HashMap<String, CodeModeCellEvidence>,
    item_cells: HashMap<String, String>,
    sealed_items: HashMap<String, bool>,
    terminal_cells: std::collections::HashSet<String>,
}

#[derive(Default)]
struct CodeModeCellEvidence {
    pending_eligible: bool,
}

/// The lifecycle boundary represented by one outer code-mode response.
pub(crate) enum CodeModeOutputBoundary {
    /// A remote snapshot which may race with nested completions while being delivered.
    Yielded,
    /// A response produced after the runtime drained or cancelled nested callbacks.
    Terminal,
    /// No trustworthy cell response exists (for example, a missing cell or failed first observe).
    Unavailable,
}

impl CodeModeEvidenceRecorder {
    /// Bind a unique harness output item to a cell.
    ///
    /// Returns whether the cell was already known. Wait errors use that distinction to retain a
    /// genuinely live cell across a retry without allowing arbitrary unknown cell ids to accumulate
    /// recorder state.
    pub(crate) fn register_output(&self, cell_id: &str, output_item_id: &str) -> bool {
        if cell_id.is_empty() || output_item_id.is_empty() {
            return false;
        }
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let cell_was_known = state.cells.contains_key(cell_id);
        if state.item_cells.len() >= MAX_PENDING_CODE_MODE_OUTPUTS
            && !state.item_cells.contains_key(output_item_id)
        {
            return false;
        }
        if state.cells.len() >= MAX_PENDING_CODE_MODE_OUTPUTS && !cell_was_known {
            return false;
        }
        state.cells.entry(cell_id.to_string()).or_default();
        state
            .item_cells
            .insert(output_item_id.to_string(), cell_id.to_string());
        cell_was_known
    }

    /// Seal the provenance snapshot carried by this particular runtime response.
    ///
    /// Yielded content is produced in the remote cell actor before its oneshot wakes this handler.
    /// A nested tool can finish in that delivery gap, so handler-side code cannot prove that any
    /// pending credit was part of the yielded snapshot. Yielded outputs therefore discard the
    /// current credit and never qualify as evidence. Terminal responses are safe: the runtime drains
    /// or cancels nested callbacks before producing them, so no later completion can race across the
    /// terminal boundary.
    pub(crate) fn seal_output(&self, output_item_id: &str, boundary: CodeModeOutputBoundary) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Some(cell_id) = state.item_cells.get(output_item_id).cloned() else {
            return;
        };
        let pending_eligible = state
            .cells
            .get_mut(&cell_id)
            .is_some_and(|cell| std::mem::take(&mut cell.pending_eligible));
        let (eligible, terminal) = match boundary {
            CodeModeOutputBoundary::Yielded => (false, false),
            CodeModeOutputBoundary::Terminal => (pending_eligible, true),
            CodeModeOutputBoundary::Unavailable => (false, true),
        };
        state
            .sealed_items
            .insert(output_item_id.to_string(), eligible);
        if terminal {
            state.terminal_cells.insert(cell_id);
        }
    }

    fn mark_eligible(&self, cell_id: &str) {
        if cell_id.is_empty() {
            return;
        }
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if !state.terminal_cells.contains(cell_id)
            && let Some(cell) = state.cells.get_mut(cell_id)
        {
            cell.pending_eligible = true;
        }
    }

    fn take_output_eligibility(&self, output_item_id: &str) -> bool {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Some(cell_id) = state.item_cells.remove(output_item_id) else {
            return false;
        };
        let eligible = state.sealed_items.remove(output_item_id).unwrap_or(false);
        if state.terminal_cells.contains(&cell_id)
            && !state.item_cells.values().any(|value| value == &cell_id)
        {
            state.terminal_cells.remove(&cell_id);
            state.cells.remove(&cell_id);
        }
        eligible
    }

    fn discard_output(&self, output_item_id: &str) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let cell_id = state.item_cells.remove(output_item_id);
        state.sealed_items.remove(output_item_id);
        if let Some(cell_id) = cell_id
            && !state.item_cells.values().any(|value| value == &cell_id)
        {
            // `discard` means the host replaced this output (normally cancellation), so no future
            // retained response is promised for the registration being removed. Unlike `take` on a
            // Yielded result, this is not the normal gap before a follow-up wait; keeping the last
            // cell here would let cancelled, never-terminal invocations accumulate to the recorder
            // ceiling and permanently suppress later evidence.
            state.terminal_cells.remove(&cell_id);
            state.cells.remove(&cell_id);
        }
    }
}

/// Remember that a nested code-mode call completed with a result which would be evidence if Codex
/// retained it directly. Nested results have no conversation item of their own, so the marker is
/// consumed by the outer cell result instead. Team-state tools remain excluded: a publish, inspect
/// or evidence read must never create another observation merely because code mode wrapped it.
pub(crate) fn note_completed_code_mode_nested_result(
    invocation: &ToolInvocation,
    result: CompletedToolResult<'_>,
) {
    if !super::team_state_enabled(&invocation.turn) {
        return;
    }
    let ToolCallSource::CodeMode { cell_id, .. } = &invocation.source else {
        return;
    };
    if crate::tools::handlers::team_tools::is_team_tool(&invocation.tool_name) {
        return;
    }
    let supported = match result {
        CompletedToolResult::Output(result) => {
            let item = ResponseItem::from(
                result
                    .result
                    .to_response_item(&result.call_id, &result.payload),
            );
            supported_observation(&item).is_some()
        }
        CompletedToolResult::Failure => {
            !matches!(invocation.payload, ToolPayload::ToolSearch { .. })
                && !invocation.call_id.is_empty()
        }
    };
    if supported {
        invocation
            .session
            .services
            .code_mode_evidence
            .mark_eligible(cell_id);
    }
}

/// Note a completed tool result so it can become evidence once Codex has retained it.
///
/// Called where a tool handler has produced a terminal outcome for the model. A call the host ends up
/// answering for itself is revoked again by [`discard_noted_tool_result`], so an interrupted call
/// leaves nothing behind even when its runtime finishes teardown afterwards.
///
/// Team tools and the evidence read itself remain excluded (a drill-down that produced more evidence
/// would make every read generate another thing to read), as does every result shape outside the
/// supported set. A nested code-mode result is never noted under its own call id because it is not
/// retained there; [`note_completed_code_mode_nested_result`] instead records trusted provenance so
/// the retained outer cell can qualify without parsing model-controlled text.
pub(crate) fn note_completed_tool_result(
    invocation: &ToolInvocation,
    item_id: &str,
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
    if invocation.tool_name.is_default_namespace()
        && matches!(
            invocation.tool_name.name.as_str(),
            crate::tools::code_mode::PUBLIC_TOOL_NAME | crate::tools::code_mode::WAIT_TOOL_NAME
        )
        && !invocation
            .session
            .services
            .code_mode_evidence
            .take_output_eligibility(item_id)
    {
        return;
    }
    let Ok(access) = super::TeamAccess::resolve(&invocation.session) else {
        return;
    };

    let (call_id, category) = match result {
        CompletedToolResult::Output(result) => {
            let item = ResponseItem::from(
                result
                    .result
                    .to_response_item(&result.call_id, &result.payload),
            );
            let Some(observation) = supported_observation(&item) else {
                return;
            };
            (observation.call_id.to_string(), observation.category)
        }
        // The host answers a failing handler with the error text in the shape the payload implies,
        // always as text and always marked unsuccessful, so the classification is settled without
        // waiting to see the message. A tool search answers in a shape that is not a supported
        // observation at all.
        CompletedToolResult::Failure => {
            if matches!(invocation.payload, ToolPayload::ToolSearch { .. })
                || invocation.call_id.is_empty()
            {
                return;
            }
            (invocation.call_id.clone(), FactCategory::ToolResultFailure)
        }
    };
    access.handle().note_observation(
        access.actor(),
        NotedObservation {
            item_id: item_id.to_string(),
            call_id,
            category,
            tool: invocation.tool_name.name.clone(),
        },
    );
}

/// Revoke the note for a tool call whose result the host is about to answer for itself.
///
/// An interrupted call can still finish its teardown and hand back an outcome, which the host then
/// discards in favour of its own "aborted" filler. That filler is retained under the same call id, so
/// without this the interrupted call would be confirmed as though the tool had reported it.
pub(crate) fn discard_noted_tool_result(
    session: &Session,
    turn_context: &TurnContext,
    item_id: &str,
) {
    session.services.code_mode_evidence.discard_output(item_id);
    if !super::team_state_enabled(turn_context) {
        return;
    }
    let Ok(access) = super::TeamAccess::resolve(session) else {
        return;
    };
    access.handle().discard_observation(access.actor(), item_id);
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
    // The items handed here are the ones being recorded, so each already carries the identity Codex
    // assigned it. That identity is what the fact will resolve by; an item without one cannot be
    // located again and is therefore not evidence.
    let candidates: Vec<String> = items
        .iter()
        .filter_map(|item| {
            supported_observation(item)?;
            let item_id = item
                .id()
                .map(ResponseItemId::as_str)
                .filter(|id| !id.is_empty())?;
            Some(item_id.to_string())
        })
        .collect();
    if candidates.is_empty() {
        return;
    }
    let Ok(access) = super::TeamAccess::resolve(session) else {
        return;
    };
    for item_id in candidates {
        if session.retained_tool_output(&item_id).await.is_none() {
            continue;
        }
        if let Some(fact_id) = access
            .handle()
            .confirm_observation(access.actor(), &item_id)
        {
            tracing::debug!(
                %fact_id,
                item_id,
                "recorded team evidence for a retained tool result"
            );
        }
    }
}

/// What resolving one fact's locator produced.
///
/// Both unreadable cases are about right now, not forever. A producer's model-visible history is
/// rewritten by compaction and trimmed under context pressure, so an observation missing from it may
/// still be in that thread's rollout; and a member that is not loaded can be loaded again into the
/// same live root tree. Neither is grounds for writing a reference off, which is why availability is
/// answered per read instead of being cached on the fact.
pub(crate) enum ObservationRead {
    /// The retained text, clamped to [`MAX_OBSERVATION_CHARS`].
    Retained { text: String, total_chars: usize },
    /// The producer is loaded and the item this locator names is not in its current history.
    NotInProducerHistory,
    /// The producer is not loaded right now, so nothing can be read for it this turn.
    ProducerNotLoaded,
}

impl ObservationRead {
    /// The model-facing text, absent when nothing could be read.
    pub(crate) fn observation(&self) -> Option<&str> {
        match self {
            Self::Retained { text, .. } => Some(text),
            Self::NotInProducerHistory | Self::ProducerNotLoaded => None,
        }
    }

    pub(crate) fn availability(&self) -> &'static str {
        match self {
            Self::Retained { .. } => "available",
            Self::NotInProducerHistory | Self::ProducerNotLoaded => "unavailable",
        }
    }

    /// Why nothing could be read, said in terms of what the harness actually established.
    pub(crate) fn unavailable_reason(&self) -> Option<&'static str> {
        match self {
            Self::Retained { .. } => None,
            Self::NotInProducerHistory => Some(
                "the producer's current context no longer carries this observation; it was recorded, but the harness cannot read it back now",
            ),
            Self::ProducerNotLoaded => {
                Some("the participant that produced this observation is not loaded right now")
            }
        }
    }

    /// Length of the retained observation, so a truncated read says how much was left out.
    pub(crate) fn total_chars(&self) -> Option<usize> {
        match self {
            Self::Retained { total_chars, .. } => Some(*total_chars),
            Self::NotInProducerHistory | Self::ProducerNotLoaded => None,
        }
    }

    pub(crate) fn truncated(&self) -> bool {
        match self {
            Self::Retained { total_chars, .. } => *total_chars > MAX_OBSERVATION_CHARS,
            Self::NotInProducerHistory | Self::ProducerNotLoaded => false,
        }
    }
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
    let Some(text) = producer.retained_tool_output(&fact.locator.item_id).await else {
        return ObservationRead::NotInProducerHistory;
    };

    let total_chars = text.chars().count();
    let text = if total_chars > MAX_OBSERVATION_CHARS {
        text.chars().take(MAX_OBSERVATION_CHARS).collect()
    } else {
        text
    };
    ObservationRead::Retained { text, total_chars }
}

/// The retained text of the item Codex assigned `item_id`, if `items` still holds it.
///
/// Identities are minted per item, so this matches at most one — which is the whole point: a
/// reference can never be answered with a different call's output, and it cannot be redirected onto a
/// later result that happens to reuse a call id.
pub(crate) fn retained_output_text(items: &[ResponseItem], item_id: &str) -> Option<String> {
    items.iter().find_map(|item| {
        if item.id().map(ResponseItemId::as_str) != Some(item_id) {
            return None;
        }
        Some(supported_observation(item)?.text.to_string())
    })
}

/// One supported observation, borrowed from the retained item that carries it.
struct Observation<'a> {
    call_id: &'a str,
    category: FactCategory,
    text: Cow<'a, str>,
}

/// Classify a retained item as a supported observation, or not one at all.
///
/// The support set is deliberately narrow: a completed tool call whose retained body contains only
/// plain text. Code-mode results use several `input_text` content items for the script status and
/// output even when no media is present, so those items are joined in the same order the model saw
/// them. A mixed or encrypted body is still excluded whole rather than partially salvaged — a fact
/// has to describe the complete observation the model actually received.
fn supported_observation(item: &ResponseItem) -> Option<Observation<'_>> {
    let (call_id, output) = match item {
        ResponseItem::FunctionCallOutput {
            call_id, output, ..
        } => (call_id, output),
        ResponseItem::CustomToolCallOutput {
            call_id, output, ..
        } => (call_id, output),
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
    let text = match &output.body {
        FunctionCallOutputBody::Text(text) => Cow::Borrowed(text.as_str()),
        FunctionCallOutputBody::ContentItems(items)
            if !items.is_empty()
                && items.iter().all(|item| {
                    matches!(item, FunctionCallOutputContentItem::InputText { .. })
                }) =>
        {
            Cow::Owned(
                items
                    .iter()
                    .map(|item| match item {
                        FunctionCallOutputContentItem::InputText { text } => text.as_str(),
                        FunctionCallOutputContentItem::InputImage { .. }
                        | FunctionCallOutputContentItem::InputAudio { .. }
                        | FunctionCallOutputContentItem::EncryptedContent { .. } => {
                            unreachable!("the all-input-text guard excludes non-text content items")
                        }
                    })
                    .collect::<Vec<_>>()
                    .join("\n"),
            )
        }
        FunctionCallOutputBody::ContentItems(_) => return None,
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
        category,
        text,
    })
}

#[cfg(test)]
#[path = "evidence_tests.rs"]
mod tests;
