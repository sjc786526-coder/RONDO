use crate::agent::registry::AgentRegistry;
use crate::thread_manager::ThreadManagerState;
use codex_protocol::AgentPath;
use codex_protocol::ThreadId;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::Weak;

const TEAM_CLOSING_MESSAGE: &str =
    "durable team root is closing; new child admission is unavailable";
const TEAM_CLOSED_MESSAGE: &str = "durable team root is closed; new child admission is unavailable";

#[derive(Default)]
pub(super) struct DurableTeamLifecycleGate {
    state: Mutex<LifecycleState>,
}

#[derive(Default)]
enum LifecycleState {
    #[default]
    Open,
    Admitting {
        count: usize,
    },
    Closing,
    Closed,
}

impl DurableTeamLifecycleGate {
    pub(super) fn begin_admission(self: &Arc<Self>) -> CodexResult<DurableTeamChildAdmissionGuard> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match &mut *state {
            LifecycleState::Open => {
                *state = LifecycleState::Admitting { count: 1 };
            }
            LifecycleState::Admitting { count } => {
                let Some(next_count) = count.checked_add(1) else {
                    return Err(CodexErr::UnsupportedOperation(
                        "durable team child admission capacity is exhausted".to_string(),
                    ));
                };
                *count = next_count;
            }
            LifecycleState::Closing => {
                return Err(CodexErr::UnsupportedOperation(
                    TEAM_CLOSING_MESSAGE.to_string(),
                ));
            }
            LifecycleState::Closed => {
                return Err(CodexErr::UnsupportedOperation(
                    TEAM_CLOSED_MESSAGE.to_string(),
                ));
            }
        }
        drop(state);
        Ok(DurableTeamChildAdmissionGuard {
            gate: Arc::clone(self),
        })
    }

    pub(super) fn begin_root_close(
        self: &Arc<Self>,
        root_thread_id: ThreadId,
        manager: Weak<ThreadManagerState>,
        registry: Arc<AgentRegistry>,
    ) -> CodexResult<DurableTeamRootCloseGuard> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match &*state {
            LifecycleState::Open => {
                *state = LifecycleState::Closing;
            }
            LifecycleState::Admitting { .. } => {
                return Err(CodexErr::UnsupportedOperation(
                    "durable team root cannot close while a child admission is in progress"
                        .to_string(),
                ));
            }
            LifecycleState::Closing => {
                return Err(CodexErr::UnsupportedOperation(
                    "durable team root is already closing".to_string(),
                ));
            }
            LifecycleState::Closed => {
                return Err(CodexErr::UnsupportedOperation(
                    "durable team root is already closed".to_string(),
                ));
            }
        }
        drop(state);
        Ok(DurableTeamRootCloseGuard {
            gate: Arc::clone(self),
            root_thread_id,
            manager,
            registry,
            settled: false,
        })
    }

    fn finish_admission(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match &mut *state {
            LifecycleState::Admitting { count } if *count == 1 => {
                *state = LifecycleState::Open;
            }
            LifecycleState::Admitting { count } => {
                debug_assert!(*count > 1, "team child admission state became unbalanced");
                *count = count.saturating_sub(1);
            }
            LifecycleState::Open | LifecycleState::Closing | LifecycleState::Closed => {
                debug_assert!(false, "team child admission state became unbalanced");
            }
        }
    }

    fn abort_root_close(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if matches!(&*state, LifecycleState::Closing) {
            *state = LifecycleState::Open;
        } else {
            debug_assert!(false, "team root close state became unbalanced");
        }
    }

    fn complete_root_close(&self) {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if matches!(&*state, LifecycleState::Closing) {
            *state = LifecycleState::Closed;
        } else {
            debug_assert!(false, "team root close state became unbalanced");
        }
    }
}

pub(super) struct DurableTeamChildAdmissionGuard {
    gate: Arc<DurableTeamLifecycleGate>,
}

impl Drop for DurableTeamChildAdmissionGuard {
    fn drop(&mut self) {
        self.gate.finish_admission();
    }
}

/// A root-close barrier for one durable Team tree.
///
/// Creating the guard atomically stops new child admission. The caller must then prove that no
/// loaded descendant can still mutate the Team before completing persistence shutdown. Dropping
/// the guard, including on an error path, reopens admission so the current owner remains retryable.
pub(crate) struct DurableTeamRootCloseGuard {
    gate: Arc<DurableTeamLifecycleGate>,
    root_thread_id: ThreadId,
    manager: Weak<ThreadManagerState>,
    registry: Arc<AgentRegistry>,
    settled: bool,
}

impl DurableTeamRootCloseGuard {
    /// Fail closed if a loaded, running descendant can still mutate this Team.
    pub(crate) async fn ensure_no_live_descendants(&self) -> CodexResult<()> {
        if self
            .registry
            .agent_id_for_path(&AgentPath::root())
            .is_some_and(|registered_root| registered_root != self.root_thread_id)
        {
            return Err(CodexErr::UnsupportedOperation(format!(
                "durable team root identity does not match closing thread {}",
                self.root_thread_id
            )));
        }

        let manager = self.manager.upgrade().ok_or_else(|| {
            CodexErr::UnsupportedOperation(
                "thread manager dropped while checking durable team descendants".to_string(),
            )
        })?;
        let mut live_descendants = Vec::new();
        for metadata in self.registry.live_agents() {
            let Some(thread_id) = metadata.agent_id else {
                continue;
            };
            if let Ok(thread) = manager.get_thread(thread_id).await
                && thread.is_running()
            {
                live_descendants.push(thread_id);
            }
        }
        if live_descendants.is_empty() {
            return Ok(());
        }
        live_descendants.sort_by_key(ToString::to_string);
        let thread_ids = live_descendants
            .iter()
            .map(ToString::to_string)
            .collect::<Vec<_>>()
            .join(", ");
        Err(CodexErr::UnsupportedOperation(format!(
            "durable team root {} cannot close while live descendants remain: {thread_ids}",
            self.root_thread_id
        )))
    }

    /// Abort this close attempt and allow a later child admission or close retry.
    pub(crate) fn abort(mut self) {
        self.gate.abort_root_close();
        self.settled = true;
    }

    /// Mark the durable Team tree closed; future child admission remains rejected.
    pub(crate) fn complete(mut self) {
        self.gate.complete_root_close();
        self.settled = true;
    }
}

impl Drop for DurableTeamRootCloseGuard {
    fn drop(&mut self) {
        if !self.settled {
            self.gate.abort_root_close();
        }
    }
}
