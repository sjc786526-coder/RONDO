//! Producer availability derived from the live control plane.
//!
//! The four classes are product contract. This module is the only place that turns AgentControl
//! facts into them; `codex-team-state` stores and compares the result, it does not invent it.
//!
//! Loaded threads are available. A missing live thread that still has a stored rollout in this
//! root tree is recoverable. A confirmed ThreadNotFound from the store is unavailable. Anything
//! else — a dropped manager, a read error, a contradiction — is unknown and refuses retirement.

use super::AgentControl;
use crate::thread_manager::ThreadManagerState;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErrorDetails;
use codex_team_state::AvailabilitySnapshot;
use codex_team_state::ProducerAvailability;
use codex_thread_store::ReadThreadParams;
use std::sync::Arc;

impl AgentControl {
    /// Classify every registered team participant from current control-plane facts.
    pub(crate) async fn producer_availability_snapshot(&self) -> AvailabilitySnapshot {
        let mut entries = Vec::new();
        for participant in self.team.participants() {
            let class = self.classify_producer(participant.thread_id).await;
            entries.push((participant.thread_id, class));
        }
        AvailabilitySnapshot::from_entries(entries)
    }

    pub(crate) async fn classify_producer(&self, thread_id: ThreadId) -> ProducerAvailability {
        let Some(state) = self.manager.upgrade() else {
            return ProducerAvailability::Unknown;
        };
        classify_with_manager(&state, thread_id).await
    }
}

async fn classify_with_manager(
    state: &Arc<ThreadManagerState>,
    thread_id: ThreadId,
) -> ProducerAvailability {
    if state.get_thread(thread_id).await.is_ok() {
        return ProducerAvailability::Available;
    }
    match state
        .read_stored_thread(ReadThreadParams {
            thread_id,
            include_archived: true,
            include_history: false,
        })
        .await
    {
        Ok(stored)
            if stored
                .rollout_path
                .as_ref()
                .is_some_and(|path| !path.exists()) =>
        {
            // SQLite can keep a summary after the rollout is gone. That row is not a restore path.
            ProducerAvailability::Unavailable
        }
        Ok(_) => ProducerAvailability::RecoverableUnloaded,
        Err(err) if matches!(err.details(), CodexErrorDetails::ThreadNotFound(_)) => {
            ProducerAvailability::Unavailable
        }
        Err(_) => ProducerAvailability::Unknown,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_protocol::ThreadId;
    use codex_team_state::ParticipantRole;

    #[tokio::test]
    async fn a_control_handle_without_a_manager_is_unknown() {
        let control = AgentControl::default();
        let thread = ThreadId::new();
        control.team().register_participant(
            thread,
            ParticipantRole::Member,
            "/root/worker".to_string(),
        );
        let snapshot = control.producer_availability_snapshot().await;
        assert_eq!(
            snapshot.class_of(thread),
            Some(ProducerAvailability::Unknown)
        );
    }
}
