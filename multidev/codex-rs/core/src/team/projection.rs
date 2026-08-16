//! The request-only Active World Index.
//!
//! A projection is captured once per logical sampling and rendered into the request tail. It is
//! never handed to `record_conversation_items`, so it reaches neither the conversation history nor
//! the rollout, and after a compaction it is simply regenerated from the canonical state.

use crate::session::context_window::context_window_token_status;
use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseItem;
use codex_team_state::ProjectionBudget;
use codex_team_state::RenderedProjection;
use codex_team_state::render_active_world_index;

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
/// Returns `None` when the feature is off, the session is not a team participant, the participant
/// has nothing active, or the request has too little room left for the projection to be worth
/// anything. The last case is what keeps the projection from pushing a request over the window:
/// the budget is derived from what the whole request has left, not from the history alone.
pub(crate) async fn capture_team_projection(
    session: &Session,
    turn_context: &TurnContext,
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
    if snapshot.is_empty() {
        return None;
    }

    let token_status = context_window_token_status(session, turn_context).await;
    let budget =
        ProjectionBudget::from_remaining_context(token_status.base_window_tokens_remaining);
    let rendered = render_active_world_index(&snapshot, budget)?;
    tracing::trace!(
        revision = %snapshot.revision,
        estimated_tokens = rendered.estimated_tokens,
        budget_tokens = budget.max_tokens(),
        omissions = rendered.omissions.len(),
        "captured team projection for this sampling"
    );
    Some(TeamProjection { rendered })
}
