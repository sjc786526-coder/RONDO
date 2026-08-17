//! Producer availability derived from the live control plane.
//!
//! The four classes are product contract. This module is the only place that turns AgentControl
//! facts into them; `codex-team-state` stores and compares the result, it does not invent it.
//!
//! Classification reuses the same V2 restore probe as `ensure_v2_agent_loaded`: loaded threads are
//! available, a probe that would succeed is recoverable, a probe that would return ThreadNotFound
//! is unavailable, and any other read failure is unknown.

use super::AgentControl;
use super::spawn::V2RestoreProbe;
use crate::thread_manager::ThreadManagerState;
use codex_protocol::ThreadId;
use codex_team_state::AvailabilityEpoch;
use codex_team_state::AvailabilitySnapshot;
use codex_team_state::ProducerAvailability;
use std::sync::Arc;

impl AgentControl {
    /// Classify every registered team participant from current control-plane facts.
    pub(crate) async fn producer_availability_snapshot(&self) -> AvailabilitySnapshot {
        let Some(state) = self.manager.upgrade() else {
            let entries = self
                .team
                .participants()
                .into_iter()
                .map(|participant| (participant.thread_id, ProducerAvailability::Unknown))
                .collect();
            return AvailabilitySnapshot::from_entries_at(AvailabilityEpoch::INITIAL, entries);
        };
        loop {
            let generation = state.availability_generation();
            let mut entries = Vec::new();
            for participant in self.team.participants() {
                let class = self
                    .classify_with_state(&state, participant.thread_id)
                    .await;
                entries.push((participant.thread_id, class));
            }
            if generation == state.availability_generation() {
                return AvailabilitySnapshot::from_entries_at(
                    AvailabilityEpoch::from_raw(generation),
                    entries,
                );
            }
        }
    }

    pub(crate) fn availability_epoch(&self) -> AvailabilityEpoch {
        self.manager
            .upgrade()
            .map(|state| AvailabilityEpoch::from_raw(state.availability_generation()))
            .unwrap_or(AvailabilityEpoch::INITIAL)
    }

    #[cfg(test)]
    pub(crate) async fn classify_producer(&self, thread_id: ThreadId) -> ProducerAvailability {
        let Some(state) = self.manager.upgrade() else {
            return ProducerAvailability::Unknown;
        };
        self.classify_with_state(&state, thread_id).await
    }

    async fn classify_with_state(
        &self,
        state: &Arc<ThreadManagerState>,
        thread_id: ThreadId,
    ) -> ProducerAvailability {
        match self.probe_v2_restore(state, thread_id).await {
            V2RestoreProbe::Loaded => ProducerAvailability::Available,
            V2RestoreProbe::Restorable(_) => ProducerAvailability::RecoverableUnloaded,
            V2RestoreProbe::Unrecoverable => ProducerAvailability::Unavailable,
            V2RestoreProbe::Failed(_) => ProducerAvailability::Unknown,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::StartThreadOptions;
    use crate::ThreadManager;
    use crate::codex_thread::CodexThread;
    use crate::config::test_config;
    use crate::thread_manager::ThreadManagerState;
    use codex_features::Feature;
    use codex_login::CodexAuth;
    use codex_protocol::error::CodexErrorDetails;
    use codex_protocol::protocol::EventMsg;
    use codex_protocol::protocol::SessionSource;
    use codex_protocol::protocol::SubAgentSource;
    use codex_protocol::protocol::ThreadSource;
    use codex_protocol::protocol::TurnAbortReason;
    use codex_protocol::protocol::TurnAbortedEvent;
    use codex_protocol::protocol::TurnCompleteEvent;
    use codex_team_state::ParticipantRole;
    use std::sync::Arc;

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
        assert_eq!(snapshot.epoch, AvailabilityEpoch::INITIAL);
    }

    #[tokio::test]
    async fn interrupted_eviction_matches_the_restore_gate() {
        let mut config = test_config().await;
        let _ = config.features.enable(Feature::MultiAgentV2);
        config.multi_agent_v2.max_concurrent_threads_per_session = 2;
        let temp_home = tempfile::tempdir().expect("create temp home");
        config.codex_home = temp_home.path().to_path_buf().try_into().unwrap();
        config.cwd = temp_home.path().to_path_buf().try_into().unwrap();
        let manager = ThreadManager::with_models_provider_and_home_for_tests(
            CodexAuth::from_api_key("dummy"),
            config.model_provider.clone(),
            config.codex_home.to_path_buf(),
            Arc::new(codex_exec_server::EnvironmentManager::default_for_tests()),
        );
        let root = manager
            .start_thread(StartThreadOptions::new(config.clone()))
            .await
            .expect("start root thread");
        let control = manager.agent_control();
        let state = control.upgrade().expect("thread manager should be live");

        let first_slot = control
            .reserve_v2_residency_slot(&state, &config, /*protected_thread_id*/ None)
            .await
            .expect("first resident slot");
        let first =
            spawn_v2_subagent(&control, &state, config.clone(), root.thread_id, "worker-1").await;
        first_slot.commit(first.thread_id);
        control.team().register_participant(
            first.thread_id,
            ParticipantRole::Member,
            "/root/worker".to_string(),
        );
        mark_thread_interrupted(first.thread.as_ref()).await;

        let second_slot = control
            .reserve_v2_residency_slot(&state, &config, /*protected_thread_id*/ None)
            .await
            .expect("second resident slot should evict the first interrupted idle agent");
        let second =
            spawn_v2_subagent(&control, &state, config.clone(), root.thread_id, "worker-2").await;
        second_slot.commit(second.thread_id);
        mark_thread_completed(second.thread.as_ref()).await;

        let err = control
            .ensure_v2_agent_loaded(config.clone(), first.thread_id)
            .await
            .expect_err("evicted interrupted agent should stay lost");
        match err.details() {
            CodexErrorDetails::ThreadNotFound(thread_id) => assert_eq!(*thread_id, first.thread_id),
            _ => panic!("expected ThreadNotFound, got {err:?}"),
        }
        assert_eq!(
            control.classify_producer(first.thread_id).await,
            ProducerAvailability::Unavailable,
            "classification must follow the restore gate, not a leftover stored summary"
        );
    }

    async fn spawn_v2_subagent(
        control: &AgentControl,
        state: &Arc<ThreadManagerState>,
        config: crate::config::Config,
        parent_thread_id: ThreadId,
        label: &str,
    ) -> crate::thread_manager::NewThread {
        state
            .spawn_new_thread_with_source(
                config,
                control.clone(),
                SessionSource::SubAgent(SubAgentSource::Other(label.to_string())),
                /*history_mode*/ None,
                Some(parent_thread_id),
                /*forked_from_thread_id*/ None,
                Some(ThreadSource::Subagent),
                /*metrics_service_name*/ None,
                /*inherited_environments*/ None,
                /*inherited_exec_policy*/ None,
                /*environments*/ None,
            )
            .await
            .expect("spawn v2 subagent")
    }

    async fn mark_thread_completed(thread: &CodexThread) {
        let turn = thread.session.new_default_turn().await;
        thread
            .session
            .send_event(
                turn.as_ref(),
                EventMsg::TurnComplete(TurnCompleteEvent {
                    turn_id: turn.sub_id.clone(),
                    started_at: None,
                    last_agent_message: Some("done".to_string()),
                    error: None,
                    completed_at: None,
                    duration_ms: None,
                    time_to_first_token_ms: None,
                }),
            )
            .await;
        *thread.session.active_turn.lock().await = None;
    }

    async fn mark_thread_interrupted(thread: &CodexThread) {
        let turn = thread.session.new_default_turn().await;
        thread
            .session
            .send_event(
                turn.as_ref(),
                EventMsg::TurnAborted(TurnAbortedEvent {
                    turn_id: Some(turn.sub_id.clone()),
                    started_at: None,
                    reason: TurnAbortReason::Interrupted,
                    completed_at: None,
                    duration_ms: None,
                }),
            )
            .await;
        *thread.session.active_turn.lock().await = None;
    }
}
