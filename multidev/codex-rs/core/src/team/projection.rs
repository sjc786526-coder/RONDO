//! The request-only Active World Index.
//!
//! A projection is rendered once per logical sampling and appended to the request tail. It is never
//! handed to `record_conversation_items`, so it reaches neither the conversation history nor the
//! rollout, and after a compaction it is simply regenerated from the canonical state.

use crate::context_manager::estimate_item_token_count;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use codex_protocol::models::BaseInstructions;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_team_state::ProjectionBudget;
use codex_team_state::ProjectionOutcome;
use codex_team_state::RenderedProjection;
use codex_team_state::render_active_world_index;
use codex_tools::ToolSpec;
use codex_utils_output_truncation::approx_token_count;

/// Roughly what the JSON around the projection text costs: the item type, the developer role and
/// the content wrapper. The renderer measures its own text, so this is the part it cannot see.
const PROJECTION_ITEM_FRAMING_TOKENS: i64 = 24;

/// A rendered team projection for one logical sampling.
///
/// The same value is reused by every provider retry of that sampling, so a retry can never see a
/// different team state than the attempt it is retrying.
pub(crate) struct TeamProjection {
    rendered: RenderedProjection,
}

impl TeamProjection {
    /// The request-only item to append at the tail of the request.
    pub(crate) fn as_response_item(&self) -> ResponseItem {
        ResponseItem::Message {
            id: None,
            role: "developer".to_string(),
            content: vec![ContentItem::InputText {
                text: self.rendered.text.clone(),
            }],
            phase: None,
            internal_chat_message_metadata_passthrough: None,
        }
    }
}

/// What the team world state contributes to this request.
pub(crate) enum TeamProjectionOutcome {
    /// Nothing to attach: the feature is off, this session is not a participant, or the
    /// participant's active view is empty.
    Nothing,
    /// A view that fits the request.
    Ready(TeamProjection),
    /// The participant has active items but this request has no room for them.
    ///
    /// The caller has to free space before sampling. Sending the request as it stands would show
    /// the model an empty team while it decides what to do, which is exactly what the active view
    /// exists to prevent.
    NeedsRoom,
}

/// Everything the provider will receive besides the projection itself.
pub(crate) struct PromptCost<'a> {
    pub(crate) input: &'a [ResponseItem],
    pub(crate) base_instructions: &'a BaseInstructions,
    pub(crate) tools: &'a [ToolSpec],
}

/// Render this participant's active view for one logical sampling.
///
/// The budget is measured against the prompt the provider is actually about to receive — the input
/// items, the instructions, the tool specifications and the output schema — rather than against the
/// usage the provider reported for some earlier request. Tool schemas in particular can be large
/// and vary per turn, so leaving them out would quietly hand the projection room that does not
/// exist.
pub(crate) async fn capture_team_projection(
    session: &Session,
    turn_context: &TurnContext,
    prompt: &PromptCost<'_>,
) -> TeamProjectionOutcome {
    if !super::team_state_enabled(turn_context) {
        return TeamProjectionOutcome::Nothing;
    }
    if let Err(error) = session.ensure_durable_root_activation().await {
        tracing::debug!(%error, "fresh durable Root activation is not yet readable");
        return TeamProjectionOutcome::Nothing;
    }
    let Ok(access) = super::TeamAccess::resolve(session) else {
        return TeamProjectionOutcome::Nothing;
    };
    let Ok(mut snapshot) = access
        .handle()
        .snapshot_for(access.actor())
        .inspect_err(|err| tracing::debug!(%err, "team projection unavailable"))
    else {
        return TeamProjectionOutcome::Nothing;
    };
    if snapshot.viewer_role.is_root() {
        let availability = session
            .services
            .agent_control
            .producer_availability_snapshot()
            .await;
        snapshot = snapshot.with_producer_availability(&availability);
    }

    let budget =
        ProjectionBudget::from_remaining_context(remaining_request_context(turn_context, prompt));
    match render_active_world_index(&snapshot, budget) {
        ProjectionOutcome::Idle => TeamProjectionOutcome::Nothing,
        ProjectionOutcome::Rendered(rendered) => {
            tracing::trace!(
                revision = %snapshot.revision,
                estimated_tokens = rendered.estimated_tokens,
                budget_tokens = budget.max_tokens(),
                omissions = rendered.omissions.len(),
                "rendered team projection for this sampling"
            );
            TeamProjectionOutcome::Ready(TeamProjection { rendered })
        }
        ProjectionOutcome::NoRoom { active_events } => {
            tracing::info!(
                active_events,
                budget_tokens = budget.max_tokens(),
                "no room for the team projection in this request"
            );
            TeamProjectionOutcome::NeedsRoom
        }
    }
}

/// What the model's window has left once everything else in this request is accounted for.
///
/// `None` when the window is unknown, in which case only the projection's absolute cap applies.
fn remaining_request_context(turn_context: &TurnContext, prompt: &PromptCost<'_>) -> Option<i64> {
    let window = turn_context.model_context_window()?;
    let instructions = approx_tokens_of(&prompt.base_instructions.text);
    let input = prompt_input_tokens(prompt.input);
    let tools = serde_json::to_string(prompt.tools)
        .map(|json| approx_tokens_of(&json))
        .unwrap_or_default();
    let output_schema = turn_context
        .final_output_json_schema
        .as_ref()
        .and_then(|schema| serde_json::to_string(schema).ok())
        .map(|json| approx_tokens_of(&json))
        .unwrap_or_default();

    Some(
        window
            .saturating_sub(instructions)
            .saturating_sub(input)
            .saturating_sub(tools)
            .saturating_sub(output_schema)
            .saturating_sub(PROJECTION_ITEM_FRAMING_TOKENS),
    )
}

/// What the input items cost, counting everything the provider will see on them.
///
/// The caller hands this the items it has already finished assembling, attached metadata included,
/// so the measurement is of the request itself rather than of the history it grew from.
fn prompt_input_tokens(input: &[ResponseItem]) -> i64 {
    input
        .iter()
        .map(estimate_item_token_count)
        .fold(0i64, i64::saturating_add)
}

fn approx_tokens_of(text: &str) -> i64 {
    i64::try_from(approx_token_count(text)).unwrap_or(i64::MAX)
}

#[cfg(test)]
#[path = "projection_tests.rs"]
mod tests;
