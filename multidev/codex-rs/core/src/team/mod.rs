//! Session-facing access to the canonical team world state.
//!
//! Everything a model can reach goes through here, and every capability is derived from the
//! session's own authoritative identity. A session that is not a registered participant of the
//! root tree's team gets no team capability at all rather than a default one.

mod projection;

pub(crate) use projection::capture_team_projection;

use crate::session::session::Session;
use crate::session::turn_context::TurnContext;
use codex_protocol::ThreadId;
use codex_team_state::TeamError;
use codex_team_state::TeamStateHandle;
use std::sync::Arc;

/// Whether the team world state is switched on for this turn.
pub(crate) fn team_state_enabled(turn_context: &TurnContext) -> bool {
    turn_context.config.multi_agent_v2.team_state_enabled
}

/// A resolved team capability for one session.
pub(crate) struct TeamAccess {
    handle: Arc<TeamStateHandle>,
    actor: ThreadId,
}

impl TeamAccess {
    /// Resolve the calling session's team capability, or refuse.
    ///
    /// The actor is the session's own thread id. Nothing in the caller's payload can influence who
    /// the harness thinks is acting.
    pub(crate) fn resolve(session: &Session) -> Result<Self, TeamError> {
        let handle = Arc::clone(session.services.agent_control.team());
        let actor = session.thread_id;
        if handle.participant(actor).is_none() {
            return Err(TeamError::UnknownParticipant);
        }
        Ok(Self { handle, actor })
    }

    pub(crate) fn handle(&self) -> &Arc<TeamStateHandle> {
        &self.handle
    }

    pub(crate) fn actor(&self) -> ThreadId {
        self.actor
    }
}
