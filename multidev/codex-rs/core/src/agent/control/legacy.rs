use super::*;
use crate::codex_thread::CodexThread;
use crate::thread_manager::ExactThreadRetirement;
use codex_protocol::error::CodexErrorDetails;
use std::time::Duration;

const AGENT_SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(10);

struct ShutdownAgentRuntime {
    thread_id: ThreadId,
    owner: Option<Arc<CodexThread>>,
}

impl AgentControl {
    fn shutdown_runtime_owners(
        shutdown_order: &[ShutdownAgentRuntime],
    ) -> Vec<(ThreadId, Option<Arc<CodexThread>>)> {
        shutdown_order
            .iter()
            .map(|runtime| (runtime.thread_id, runtime.owner.clone()))
            .collect()
    }

    async fn lock_shutdown_agent_runtimes(
        &self,
        shutdown_order: &[ShutdownAgentRuntime],
    ) -> CodexResult<ExactThreadRetirement> {
        self.upgrade()?
            .lock_threads_if_not_replaced(Self::shutdown_runtime_owners(shutdown_order))
            .await
            .map_err(|thread_id| {
                CodexErr::UnsupportedOperation(format!(
                    "agent {thread_id} no longer has the shutdown owner while close was completing; retry close"
                ))
            })
    }

    async fn shutdown_live_agent_runtime(
        &self,
        agent_id: ThreadId,
    ) -> CodexResult<(String, Arc<CodexThread>)> {
        let state = self.upgrade()?;
        let thread = state.get_thread(agent_id).await?;
        if !matches!(thread.agent_status().await, AgentStatus::Shutdown) {
            thread.session.ensure_rollout_materialized().await;
            thread.session.flush_rollout().await?;
        }
        #[cfg(test)]
        state.capture_direct_thread_op_for_tests(agent_id, &Op::Shutdown {});
        match tokio::time::timeout(AGENT_SHUTDOWN_TIMEOUT, thread.shutdown_and_wait()).await {
            Ok(result) => result.map(|()| (String::new(), thread)),
            Err(_) => Err(CodexErr::Fatal(format!(
                "timed out shutting down agent {agent_id}; the tracked owner remains available for retry"
            ))),
        }
    }

    #[cfg(test)]
    async fn retire_shutdown_agent_runtimes(
        &self,
        shutdown_order: &[ShutdownAgentRuntime],
    ) -> CodexResult<()> {
        let retirement = self.lock_shutdown_agent_runtimes(shutdown_order).await?;
        self.retire_shutdown_agents(retirement);
        Ok(())
    }

    fn retire_shutdown_agents(&self, retirement: crate::thread_manager::ExactThreadRetirement) {
        // Registry and residency release are part of the same map/availability transition as the
        // exact-owner removal. A same-ID replacement therefore cannot inherit stale cleanup.
        retirement.retire_with(|thread_id, _| {
            self.forget_v2_residency(thread_id);
            self.state.release_spawned_thread(thread_id);
        });
    }

    /// Submit a shutdown request for a live agent without marking it explicitly closed in
    /// persisted spawn-edge state.
    #[cfg(test)]
    pub(crate) async fn shutdown_live_agent(&self, agent_id: ThreadId) -> CodexResult<String> {
        let (result, owner) = self.shutdown_live_agent_runtime(agent_id).await?;
        let shutdown_order = [ShutdownAgentRuntime {
            thread_id: agent_id,
            owner: Some(owner),
        }];
        self.retire_shutdown_agent_runtimes(&shutdown_order).await?;
        Ok(result)
    }

    /// Shut down `agent_id` and its live descendants, persist the target edge as explicitly
    /// closed, then release their tracked residency.
    pub(crate) async fn close_agent(&self, agent_id: ThreadId) -> CodexResult<String> {
        if self
            .team()
            .durable_identity()
            .is_some_and(|identity| identity.root_thread_id() == agent_id)
        {
            return Err(CodexErr::UnsupportedOperation(
                "durable team root must be closed through its root shutdown lifecycle".to_string(),
            ));
        }
        let _subtree_close = self.begin_agent_subtree_close()?;
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

        // Keep the exact captured owners mapped until their Closed edge is durable. The exclusive
        // map lease prevents replacement during the write; a failed write drops the lease without
        // retiring anything, preserving the terminated owners for inspection and retry.
        let retirement = self.lock_shutdown_agent_runtimes(&shutdown_order).await?;
        if persist_closed_edge {
            let agent_graph_store = match state.agent_graph_store() {
                Some(agent_graph_store) => Some(agent_graph_store),
                None if self.team().durable_identity().is_some() => {
                    return Err(CodexErr::Fatal(
                        "durable Team child close requires an available agent graph store"
                            .to_string(),
                    ));
                }
                None => None,
            };
            if let Some(agent_graph_store) = agent_graph_store {
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
        }
        self.retire_shutdown_agents(retirement);
        Ok(result)
    }

    /// Shut down `agent_id` and any live descendants reachable from the in-memory spawn tree.
    #[cfg(test)]
    pub(crate) async fn shutdown_agent_tree(&self, agent_id: ThreadId) -> CodexResult<String> {
        let _subtree_close = self.begin_agent_subtree_close()?;
        let known_agent = self.state.agent_metadata_for_thread(agent_id).is_some();
        let (shutdown_order, result) = self
            .shutdown_agent_tree_runtimes(agent_id, known_agent)
            .await?;
        self.retire_shutdown_agent_runtimes(&shutdown_order).await?;
        Ok(result)
    }

    async fn shutdown_agent_tree_runtimes(
        &self,
        agent_id: ThreadId,
        known_agent: bool,
    ) -> CodexResult<(Vec<ShutdownAgentRuntime>, String)> {
        let mut shutdown_order = self.live_thread_spawn_descendants(agent_id).await?;
        shutdown_order.reverse();
        shutdown_order.push(agent_id);
        let mut root_result = String::new();
        let mut shutdown_runtimes = Vec::with_capacity(shutdown_order.len());
        for thread_id in shutdown_order {
            match self.shutdown_live_agent_runtime(thread_id).await {
                Ok((result, owner)) => {
                    if thread_id == agent_id {
                        root_result = result;
                    }
                    shutdown_runtimes.push(ShutdownAgentRuntime {
                        thread_id,
                        owner: Some(owner),
                    });
                }
                Err(err)
                    if (known_agent || thread_id != agent_id)
                        && matches!(
                            err.details(),
                            CodexErrorDetails::ThreadNotFound(_)
                                | CodexErrorDetails::InternalAgentDied
                        ) =>
                {
                    shutdown_runtimes.push(ShutdownAgentRuntime {
                        thread_id,
                        owner: None,
                    })
                }
                Err(err) => return Err(err),
            }
        }
        Ok((shutdown_runtimes, root_result))
    }
}
