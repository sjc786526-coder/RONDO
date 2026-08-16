//! The request-only Active World Index.
//!
//! A projection is captured once per logical sampling and rendered into the request tail. It is
//! never handed to `record_conversation_items`, so it reaches neither the conversation history nor
//! the rollout, and after a compaction it is simply regenerated from the canonical state.

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
use codex_utils_output_truncation::approx_token_count;

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

/// Capture and render this participant's active view for one logical sampling.
///
/// The budget is derived from the request that is actually about to be sent — the assembled input
/// plus the instructions that travel with it — rather than from the token usage the provider
/// reported for an earlier request. Items written during this turn are already in `prompt_input`,
/// so they are counted; measuring anything else would leave the projection free to overrun exactly
/// when the request is fullest.
///
/// Returns `None` when the feature is off, the session is not a participant, nothing is active, or
/// the request genuinely has no room. In that last case a new context window is requested, so the
/// turn compacts and the next sampling has space, instead of the projection taking room it was not
/// given or the participant being told its team is idle.
pub(crate) async fn capture_team_projection(
    session: &Session,
    turn_context: &TurnContext,
    prompt_input: &[ResponseItem],
    base_instructions: &BaseInstructions,
) -> Option<TeamProjection> {
    if !super::team_state_enabled(turn_context) {
        return None;
    }
    let access = super::TeamAccess::resolve(session).ok()?;
    let snapshot = access
        .handle()
        .snapshot_for(access.actor())
        .inspect_err(|err| tracing::debug!(%err, "team projection unavailable"))
        .ok()?;

    let budget = ProjectionBudget::from_remaining_context(remaining_request_context(
        turn_context,
        prompt_input,
        base_instructions,
    ));
    match render_active_world_index(&snapshot, budget) {
        ProjectionOutcome::Idle => None,
        ProjectionOutcome::Rendered(rendered) => {
            tracing::trace!(
                revision = %snapshot.revision,
                estimated_tokens = rendered.estimated_tokens,
                budget_tokens = budget.max_tokens(),
                omissions = rendered.omissions.len(),
                "captured team projection for this sampling"
            );
            Some(TeamProjection { rendered })
        }
        ProjectionOutcome::NoRoom { active_events } => {
            tracing::info!(
                active_events,
                budget_tokens = budget.max_tokens(),
                "no room for the team projection in this request; requesting a new context window"
            );
            session.request_new_context_window().await;
            None
        }
    }
}

/// What the model's window has left once this request's own contents are accounted for.
///
/// `None` when the window is unknown, in which case only the projection's absolute cap applies.
fn remaining_request_context(
    turn_context: &TurnContext,
    prompt_input: &[ResponseItem],
    base_instructions: &BaseInstructions,
) -> Option<i64> {
    let window = turn_context.model_context_window()?;
    let instructions =
        i64::try_from(approx_token_count(&base_instructions.text)).unwrap_or(i64::MAX);
    let input = prompt_input
        .iter()
        .map(estimate_item_token_count)
        .fold(0i64, i64::saturating_add);
    Some(window.saturating_sub(instructions).saturating_sub(input))
}
