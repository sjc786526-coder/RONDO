//! Producer availability derived from the live control plane.
//!
//! The four classes are product contract. This module is the only place that turns AgentControl
//! facts into them; `codex-team-state` stores and compares the result, it does not invent it.
//!
//! Classification follows explicit `resume_agent` recoverability: a loaded thread that can still
//! accept tasks is available, a stored rollout that resume can rebuild is recoverable even if
//! registry metadata is gone, a missing store/history is unavailable, and any other read failure
//! is unknown. A map-resident thread whose submit channel is closed is not available. While a
//! store transition is in progress, every producer is unknown so a mid-delete epoch cannot mean
//! both recoverable and unavailable.

use super::AgentControl;
use super::spawn::ProducerRecoverability;
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
                .team()
                .participants()
                .into_iter()
                .map(|participant| (participant.thread_id, ProducerAvailability::Unknown))
                .collect();
            return AvailabilitySnapshot::from_entries_at(AvailabilityEpoch::INITIAL, entries);
        };
        loop {
            let (generation, store_transition_active) = state.availability_marker();
            if store_transition_active {
                let entries = self
                    .team()
                    .participants()
                    .into_iter()
                    .map(|participant| (participant.thread_id, ProducerAvailability::Unknown))
                    .collect();
                let (live_generation, live_store_transition_active) = state.availability_marker();
                if generation != live_generation || !live_store_transition_active {
                    continue;
                }
                return AvailabilitySnapshot::from_entries_at(
                    AvailabilityEpoch::from_raw(generation),
                    entries,
                );
            }
            let mut entries = Vec::new();
            for participant in self.team().participants() {
                let class = self
                    .classify_with_state(&state, participant.thread_id)
                    .await;
                entries.push((participant.thread_id, class));
            }
            let (live_generation, live_store_transition_active) = state.availability_marker();
            if generation == live_generation && !live_store_transition_active {
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
        if state.store_transition_in_progress() {
            return ProducerAvailability::Unknown;
        }
        match self.probe_producer_recoverability(state, thread_id).await {
            ProducerRecoverability::Loaded => ProducerAvailability::Available,
            ProducerRecoverability::Restorable => ProducerAvailability::RecoverableUnloaded,
            ProducerRecoverability::Unrecoverable => ProducerAvailability::Unavailable,
            ProducerRecoverability::Failed => ProducerAvailability::Unknown,
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
            ProducerAvailability::RecoverableUnloaded,
            "automatic V2 load may fail, but a leftover rollout is still resume_agent recoverable"
        );
    }

    #[tokio::test]
    async fn shutdown_without_registry_is_resume_recoverable_and_must_not_retire() {
        let mut config = test_config().await;
        let _ = config.features.enable(Feature::MultiAgentV2);
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
        let worker =
            spawn_v2_subagent(&control, &state, config.clone(), root.thread_id, "worker-1").await;
        control.team().register_participant(
            worker.thread_id,
            ParticipantRole::Member,
            "/root/worker".to_string(),
        );
        let epoch_before = control.availability_epoch();

        control
            .shutdown_live_agent(worker.thread_id)
            .await
            .expect("shutdown");
        assert_eq!(
            control.get_status(worker.thread_id).await,
            crate::agent::AgentStatus::NotFound
        );
        assert!(control.availability_epoch() != epoch_before);
        assert_eq!(
            control.classify_producer(worker.thread_id).await,
            ProducerAvailability::RecoverableUnloaded,
            "registry miss must not count as truly unavailable while resume_agent can restore"
        );

        control
            .resume_agent_from_rollout(
                config,
                worker.thread_id,
                SessionSource::SubAgent(SubAgentSource::Other("worker-1".to_string())),
            )
            .await
            .expect("explicit resume_agent restores the shutdown worker");
        assert_eq!(
            control.classify_producer(worker.thread_id).await,
            ProducerAvailability::Available
        );
    }

    #[tokio::test]
    async fn a_dead_resident_thread_is_not_available() {
        let mut config = test_config().await;
        let _ = config.features.enable(Feature::MultiAgentV2);
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
        let worker = spawn_v2_subagent(&control, &state, config, root.thread_id, "worker-1").await;
        control.team().register_participant(
            worker.thread_id,
            ParticipantRole::Member,
            "/root/worker".to_string(),
        );
        assert_eq!(
            control.classify_producer(worker.thread_id).await,
            ProducerAvailability::Available
        );
        assert!(worker.thread.is_running());

        worker.thread.session.ensure_rollout_materialized().await;
        worker
            .thread
            .session
            .flush_rollout()
            .await
            .expect("flush leftover rollout before the runtime dies");
        worker.thread.io.tx_sub.close();
        assert!(!worker.thread.is_running());
        assert!(
            state.get_thread(worker.thread_id).await.is_ok(),
            "the dead runtime is still mapped before classification"
        );
        let epoch_before = control.availability_epoch();
        assert_eq!(
            control.classify_producer(worker.thread_id).await,
            ProducerAvailability::RecoverableUnloaded,
            "a closed submit channel is not currently available"
        );
        assert!(control.availability_epoch() != epoch_before);
        assert!(
            state.get_thread(worker.thread_id).await.is_err(),
            "dead residents are dropped so the availability change is versioned once"
        );
    }

    #[tokio::test]
    async fn a_store_transition_midpoint_is_unknown_until_finish() {
        let mut config = test_config().await;
        let _ = config.features.enable(Feature::MultiAgentV2);
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
        let worker = spawn_v2_subagent(&control, &state, config, root.thread_id, "worker-1").await;
        control.team().register_participant(
            worker.thread_id,
            ParticipantRole::Member,
            "/root/worker".to_string(),
        );
        control
            .shutdown_live_agent(worker.thread_id)
            .await
            .expect("shutdown");
        assert_eq!(
            control.classify_producer(worker.thread_id).await,
            ProducerAvailability::RecoverableUnloaded
        );
        let before_transition = control.producer_availability_snapshot().await;
        assert_eq!(
            before_transition.class_of(worker.thread_id),
            Some(ProducerAvailability::RecoverableUnloaded)
        );

        let transition = manager.begin_thread_store_transition();
        let midpoint_epoch = control.availability_epoch();
        assert_ne!(midpoint_epoch, before_transition.epoch);
        assert_eq!(
            control.classify_producer(worker.thread_id).await,
            ProducerAvailability::Unknown,
            "an open store transition must not publish recoverable or unavailable"
        );
        manager
            .read_stored_thread(codex_thread_store::ReadThreadParams {
                thread_id: worker.thread_id,
                include_archived: true,
                include_history: false,
            })
            .await
            .expect("store row is still present after begin");

        manager
            .delete_store_row_for_tests(worker.thread_id)
            .await
            .expect("delete the store row while the transition is still open");
        assert_eq!(
            control.availability_epoch(),
            midpoint_epoch,
            "deleting the row must not by itself close the mid-delete epoch"
        );

        let barrier = Arc::new(tokio::sync::Barrier::new(2));
        let observer = control.clone();
        let worker_id = worker.thread_id;
        let observer_barrier = Arc::clone(&barrier);
        let observed = tokio::spawn(async move {
            observer_barrier.wait().await;
            let class = observer.classify_producer(worker_id).await;
            let snapshot = observer.producer_availability_snapshot().await;
            (class, snapshot.class_of(worker_id), snapshot.epoch)
        });
        barrier.wait().await;
        let (class, snapshot_class, snapshot_epoch) = observed.await.expect("observer");
        assert_eq!(class, ProducerAvailability::Unknown);
        assert_eq!(snapshot_class, Some(ProducerAvailability::Unknown));
        assert_eq!(snapshot_epoch, midpoint_epoch);

        transition.finish();
        assert!(control.availability_epoch() != midpoint_epoch);
        let after_transition = control.producer_availability_snapshot().await;
        assert_ne!(after_transition.epoch, midpoint_epoch);
        assert_eq!(
            after_transition.class_of(worker.thread_id),
            Some(ProducerAvailability::Unavailable)
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
                /*writer_workspace_binding*/ None,
                /*defer_durable_team_participant_registration*/ false,
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
