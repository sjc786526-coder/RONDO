use super::*;
use codex_protocol::error::CodexErrorDetails;
use std::time::Duration;

const AGENT_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);

impl AgentControl {
    async fn shutdown_live_agent_runtime(&self, agent_id: ThreadId) -> CodexResult<String> {
        let state = self.upgrade()?;
        if let Ok(thread) = state.get_thread(agent_id).await {
            if !matches!(thread.agent_status().await, AgentStatus::Shutdown) {
                thread.session.ensure_rollout_materialized().await;
                thread.session.flush_rollout().await?;
            }
            #[cfg(test)]
            state.capture_direct_thread_op_for_tests(agent_id, &Op::Shutdown {});
            match tokio::time::timeout(AGENT_SHUTDOWN_TIMEOUT, thread.shutdown_and_wait()).await {
                Ok(result) => result.map(|()| String::new()),
                Err(_) => Err(CodexErr::Fatal(format!(
                    "timed out shutting down agent {agent_id}; the tracked owner remains available for retry"
                ))),
            }
        } else {
            state
                .send_op(agent_id, Op::Shutdown {}, /*parent_turn_id*/ None)
                .await
        }
    }

    async fn finalize_shutdown_live_agent(&self, agent_id: ThreadId) -> CodexResult<()> {
        let state = self.upgrade()?;
        let _ = state.remove_thread(&agent_id).await;
        self.forget_v2_residency(agent_id);
        let _gate = state.lock_availability_transition();
        self.state.release_spawned_thread(agent_id);
        state.bump_availability_generation();
        Ok(())
    }

    /// Submit a shutdown request for a live agent without marking it explicitly closed in
    /// persisted spawn-edge state.
    #[cfg(test)]
    pub(crate) async fn shutdown_live_agent(&self, agent_id: ThreadId) -> CodexResult<String> {
        let result = self.shutdown_live_agent_runtime(agent_id).await?;
        self.finalize_shutdown_live_agent(agent_id).await?;
        Ok(result)
    }

    /// Shut down `agent_id` and its live descendants, persist the target edge as explicitly
    /// closed, then release their tracked residency.
    pub(crate) async fn close_agent(&self, agent_id: ThreadId) -> CodexResult<String> {
        let state = self.upgrade()?;
        let known_agent = self.state.agent_metadata_for_thread(agent_id).is_some();
        let persist_closed_edge = match state.get_thread(agent_id).await {
            Ok(thread) => !thread.config_snapshot().await.ephemeral,
            Err(err)
                if known_agent && matches!(err.details(), CodexErrorDetails::ThreadNotFound(_)) =>
            {
                true
            }
            Err(err) if matches!(err.details(), CodexErrorDetails::ThreadNotFound(_)) => false,
            Err(err) => return Err(err),
        };

        let (shutdown_order, result) =
            match Box::pin(self.shutdown_agent_tree_runtimes(agent_id, known_agent)).await {
                Ok(outcome) => outcome,
                Err(err)
                    if known_agent
                        && matches!(
                            err.details(),
                            CodexErrorDetails::ThreadNotFound(_)
                                | CodexErrorDetails::InternalAgentDied
                        ) =>
                {
                    (Vec::new(), String::new())
                }
                Err(err) => return Err(err),
            };

        // A persisted Closed edge is the durable terminal boundary. Do not release registry or
        // residency entries if it fails: the same terminated-but-tracked tree remains retryable.
        if persist_closed_edge && let Some(agent_graph_store) = state.agent_graph_store() {
            agent_graph_store
                .set_thread_spawn_edge_status(
                    agent_id,
                    codex_agent_graph_store::ThreadSpawnEdgeStatus::Closed,
                )
                .await
                .map_err(|err| {
                    CodexErr::Fatal(format!(
                        "failed to persist thread-spawn edge status for {agent_id}: {err}"
                    ))
                })?;
        }
        for thread_id in shutdown_order {
            self.finalize_shutdown_live_agent(thread_id).await?;
        }
        Ok(result)
    }

    /// Shut down `agent_id` and any live descendants reachable from the in-memory spawn tree.
    #[cfg(test)]
    pub(crate) async fn shutdown_agent_tree(&self, agent_id: ThreadId) -> CodexResult<String> {
        let known_agent = self.state.agent_metadata_for_thread(agent_id).is_some();
        let (shutdown_order, result) = self
            .shutdown_agent_tree_runtimes(agent_id, known_agent)
            .await?;
        for thread_id in shutdown_order {
            self.finalize_shutdown_live_agent(thread_id).await?;
        }
        Ok(result)
    }

    async fn shutdown_agent_tree_runtimes(
        &self,
        agent_id: ThreadId,
        known_agent: bool,
    ) -> CodexResult<(Vec<ThreadId>, String)> {
        let mut shutdown_order = self.live_thread_spawn_descendants(agent_id).await?;
        shutdown_order.reverse();
        shutdown_order.push(agent_id);
        let mut root_result = String::new();
        for &thread_id in &shutdown_order {
            match self.shutdown_live_agent_runtime(thread_id).await {
                Ok(result) => {
                    if thread_id == agent_id {
                        root_result = result;
                    }
                }
                Err(err)
                    if (known_agent || thread_id != agent_id)
                        && matches!(
                            err.details(),
                            CodexErrorDetails::ThreadNotFound(_)
                                | CodexErrorDetails::InternalAgentDied
                        ) => {}
                Err(err) => return Err(err),
            }
        }
        Ok((shutdown_order, root_result))
    }
}
