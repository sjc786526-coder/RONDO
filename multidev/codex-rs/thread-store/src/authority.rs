use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionMeta;
use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::Weak;
use tokio::sync::Notify;

use crate::ThreadStoreError;
use crate::ThreadStoreResult;
use crate::local::writer_lock::WriterLockGuard;

/// A weak capability derived from a live thread's canonical writer ownership.
///
/// Keeping this handle alive does not extend the underlying OS writer lock. A write permit can be
/// acquired only while the owning store still has the corresponding live recorder and its writer
/// authority remains open.
#[derive(Clone)]
pub struct RootWriterAuthority {
    thread_id: ThreadId,
    state: Weak<RootWriterAuthorityState>,
}

impl RootWriterAuthority {
    /// Returns the thread whose canonical writer owns this authority.
    pub fn thread_id(&self) -> ThreadId {
        self.thread_id
    }

    /// Starts one Team mutation under the live writer authority.
    ///
    /// The returned permit must be retained through the durable commit and successful return. A
    /// close that has started or completed rejects new writes.
    pub fn begin_write(&self) -> ThreadStoreResult<RootWritePermit> {
        let state = self.upgrade()?;
        state.begin_write()
    }

    /// Prevents new Team mutations and waits for all existing write permits to finish.
    ///
    /// Call [`RootClosePermit::abort`] if the durable Team close fails before thread shutdown. Call
    /// [`RootClosePermit::complete`] once the Team state is durably closed; the thread writer can
    /// then be shut down. Dropping an unfinished permit aborts the close.
    pub async fn begin_close(&self) -> ThreadStoreResult<RootClosePermit> {
        let state = self.upgrade()?;
        state.begin_close().await
    }

    fn upgrade(&self) -> ThreadStoreResult<Arc<RootWriterAuthorityState>> {
        self.state
            .upgrade()
            .ok_or_else(|| authority_inactive(self.thread_id))
    }
}

impl fmt::Debug for RootWriterAuthority {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RootWriterAuthority")
            .field("thread_id", &self.thread_id)
            .finish_non_exhaustive()
    }
}

/// Proof that one Team mutation is continuously covered by the root writer authority.
pub struct RootWritePermit {
    state: Arc<RootWriterAuthorityState>,
}

impl RootWritePermit {
    /// Returns the thread whose canonical writer covers this mutation.
    pub fn thread_id(&self) -> ThreadId {
        self.state.thread_id
    }

    /// Reads the canonical metadata owned by this live Root writer.
    ///
    /// Team durability uses this while the write permit is live so a snapshot read or commit
    /// cannot report success after the Root lineage marker has disappeared or changed.
    pub fn read_session_meta(&self) -> ThreadStoreResult<SessionMeta> {
        codex_rollout::read_session_meta_line_blocking(&self.state.rollout_path)
            .map(|line| line.meta)
            .map_err(|error| ThreadStoreError::Internal {
                message: format!(
                    "cannot read canonical SessionMeta for Root thread {}: {error}",
                    self.state.thread_id
                ),
            })
    }
}

impl fmt::Debug for RootWritePermit {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RootWritePermit")
            .field("thread_id", &self.state.thread_id)
            .finish_non_exhaustive()
    }
}

impl Drop for RootWritePermit {
    fn drop(&mut self) {
        self.state.finish_write();
    }
}

/// Exclusive authority to finish or roll back a Team close barrier.
pub struct RootClosePermit {
    state: Arc<RootWriterAuthorityState>,
    generation: u64,
    finished: bool,
}

impl RootClosePermit {
    /// Returns the thread whose canonical writer is being closed.
    pub fn thread_id(&self) -> ThreadId {
        self.state.thread_id
    }

    /// Reopens the authority after a durable Team close failed before thread shutdown.
    pub fn abort(mut self) -> ThreadStoreResult<()> {
        self.state.abort_close(self.generation)?;
        self.finished = true;
        Ok(())
    }

    /// Seals the authority after the durable Team close has succeeded.
    ///
    /// Completion prevents all later Team mutations while the store retains the strong authority
    /// and OS writer lock until thread shutdown itself succeeds.
    pub fn complete(mut self) -> ThreadStoreResult<()> {
        self.state.complete_close(self.generation)?;
        self.finished = true;
        Ok(())
    }
}

impl fmt::Debug for RootClosePermit {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RootClosePermit")
            .field("thread_id", &self.state.thread_id)
            .field("finished", &self.finished)
            .finish_non_exhaustive()
    }
}

impl Drop for RootClosePermit {
    fn drop(&mut self) {
        if !self.finished {
            let _ = self.state.abort_close(self.generation);
        }
    }
}

pub(crate) struct RootWriterAuthorityState {
    thread_id: ThreadId,
    rollout_path: PathBuf,
    inner: Mutex<AuthorityInner>,
    writes_drained: Notify,
    // A write permit clones this state, so the canonical OS writer lock remains held through the
    // mutation's durable commit and successful return even if its live recorder is torn down.
    _writer_lock: WriterLockGuard,
}

#[derive(Debug)]
struct AuthorityInner {
    owner_attached: bool,
    lifecycle: AuthorityLifecycle,
    active_writes: usize,
    close_permit_issued: bool,
    next_close_generation: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum AuthorityLifecycle {
    Active,
    Closing { generation: u64 },
    Closed,
}

pub(crate) enum OwnerCloseState {
    Permit(RootClosePermit),
    ExternallyClosing,
    AlreadyClosed,
}

impl RootWriterAuthorityState {
    pub(crate) fn new(
        thread_id: ThreadId,
        rollout_path: PathBuf,
        writer_lock: WriterLockGuard,
    ) -> Arc<Self> {
        Arc::new(Self {
            thread_id,
            rollout_path,
            inner: Mutex::new(AuthorityInner {
                owner_attached: true,
                lifecycle: AuthorityLifecycle::Active,
                active_writes: 0,
                close_permit_issued: false,
                next_close_generation: 1,
            }),
            writes_drained: Notify::new(),
            _writer_lock: writer_lock,
        })
    }

    pub(crate) fn downgrade(self: &Arc<Self>) -> RootWriterAuthority {
        RootWriterAuthority {
            thread_id: self.thread_id,
            state: Arc::downgrade(self),
        }
    }

    fn begin_write(self: &Arc<Self>) -> ThreadStoreResult<RootWritePermit> {
        let mut inner = self.lock_inner()?;
        match (inner.owner_attached, inner.lifecycle) {
            (true, AuthorityLifecycle::Active) => {
                inner.active_writes = inner.active_writes.checked_add(1).ok_or_else(|| {
                    ThreadStoreError::Internal {
                        message: format!(
                            "root writer authority permit count overflowed for thread {}",
                            self.thread_id
                        ),
                    }
                })?;
            }
            (false, _)
            | (true, AuthorityLifecycle::Closing { .. })
            | (true, AuthorityLifecycle::Closed) => {
                return Err(authority_inactive(self.thread_id));
            }
        }
        drop(inner);
        Ok(RootWritePermit {
            state: Arc::clone(self),
        })
    }

    async fn begin_close(self: &Arc<Self>) -> ThreadStoreResult<RootClosePermit> {
        let generation = {
            let mut inner = self.lock_inner()?;
            if !inner.owner_attached {
                return Err(authority_inactive(self.thread_id));
            }
            match inner.lifecycle {
                AuthorityLifecycle::Active => {
                    let generation = inner.next_close_generation;
                    inner.next_close_generation = generation.checked_add(1).ok_or_else(|| {
                        ThreadStoreError::Internal {
                            message: format!(
                                "root writer authority close generation overflowed for thread {}",
                                self.thread_id
                            ),
                        }
                    })?;
                    inner.lifecycle = AuthorityLifecycle::Closing { generation };
                    inner.close_permit_issued = false;
                    generation
                }
                AuthorityLifecycle::Closing { .. } => {
                    return Err(ThreadStoreError::Conflict {
                        message: format!(
                            "root writer authority for thread {} is already closing",
                            self.thread_id
                        ),
                    });
                }
                AuthorityLifecycle::Closed => return Err(authority_inactive(self.thread_id)),
            }
        };
        // Construct the RAII permit before waiting so cancellation of this future aborts the close
        // instead of leaving the authority permanently stuck in `Closing`.
        let permit = RootClosePermit {
            state: Arc::clone(self),
            generation,
            finished: false,
        };

        loop {
            let notified = self.writes_drained.notified();
            {
                let mut inner = self.lock_inner()?;
                match inner.lifecycle {
                    AuthorityLifecycle::Closing {
                        generation: current,
                    } if current == generation && inner.active_writes == 0 => {
                        inner.close_permit_issued = true;
                        break;
                    }
                    AuthorityLifecycle::Closing {
                        generation: current,
                    } if current == generation => {}
                    _ => return Err(close_permit_stale(self.thread_id)),
                }
            }
            notified.await;
        }

        Ok(permit)
    }

    pub(crate) async fn begin_owner_close(self: &Arc<Self>) -> ThreadStoreResult<OwnerCloseState> {
        {
            let inner = self.lock_inner()?;
            match inner.lifecycle {
                AuthorityLifecycle::Active => {}
                AuthorityLifecycle::Closing { .. }
                    if inner.active_writes == 0 && inner.close_permit_issued =>
                {
                    return Ok(OwnerCloseState::ExternallyClosing);
                }
                AuthorityLifecycle::Closing { .. } => {
                    return Err(ThreadStoreError::Conflict {
                        message: format!(
                            "root writer authority for thread {} still has active writes",
                            self.thread_id
                        ),
                    });
                }
                AuthorityLifecycle::Closed => return Ok(OwnerCloseState::AlreadyClosed),
            }
        }
        self.begin_close().await.map(OwnerCloseState::Permit)
    }

    pub(crate) fn detach_owner(&self) {
        let Ok(mut inner) = self.inner.lock() else {
            return;
        };
        inner.owner_attached = false;
        // Preserve an external close generation so its permit can complete after successful
        // recorder shutdown. Active authority is closed immediately because there is no owner to
        // admit another write.
        if matches!(inner.lifecycle, AuthorityLifecycle::Active) {
            inner.lifecycle = AuthorityLifecycle::Closed;
        }
        self.writes_drained.notify_one();
    }

    fn finish_write(&self) {
        let Ok(mut inner) = self.inner.lock() else {
            return;
        };
        debug_assert!(inner.active_writes > 0);
        inner.active_writes = inner.active_writes.saturating_sub(1);
        if inner.active_writes == 0 && matches!(inner.lifecycle, AuthorityLifecycle::Closing { .. })
        {
            self.writes_drained.notify_one();
        }
    }

    fn abort_close(&self, generation: u64) -> ThreadStoreResult<()> {
        let mut inner = self.lock_inner()?;
        match inner.lifecycle {
            AuthorityLifecycle::Closing {
                generation: current,
            } if current == generation => {
                inner.lifecycle = if inner.owner_attached {
                    AuthorityLifecycle::Active
                } else {
                    AuthorityLifecycle::Closed
                };
                inner.close_permit_issued = false;
                Ok(())
            }
            _ => Err(close_permit_stale(self.thread_id)),
        }
    }

    fn complete_close(&self, generation: u64) -> ThreadStoreResult<()> {
        let mut inner = self.lock_inner()?;
        match inner.lifecycle {
            AuthorityLifecycle::Closing {
                generation: current,
            } if current == generation && inner.active_writes == 0 => {
                inner.lifecycle = AuthorityLifecycle::Closed;
                inner.close_permit_issued = false;
                Ok(())
            }
            _ => Err(close_permit_stale(self.thread_id)),
        }
    }

    fn lock_inner(&self) -> ThreadStoreResult<MutexGuard<'_, AuthorityInner>> {
        self.inner.lock().map_err(|_| ThreadStoreError::Internal {
            message: format!(
                "root writer authority state is poisoned for thread {}",
                self.thread_id
            ),
        })
    }
}

fn authority_inactive(thread_id: ThreadId) -> ThreadStoreError {
    ThreadStoreError::Conflict {
        message: format!("root writer authority for thread {thread_id} is not active"),
    }
}

fn close_permit_stale(thread_id: ThreadId) -> ThreadStoreError {
    ThreadStoreError::Conflict {
        message: format!("root close permit for thread {thread_id} is no longer current"),
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use tempfile::TempDir;

    use super::RootWriterAuthorityState;
    use crate::ThreadStoreError;
    use crate::local::writer_lock::WriterLockCoordinator;

    fn authority_state() -> (TempDir, Arc<RootWriterAuthorityState>) {
        let home = TempDir::new().expect("temp dir");
        let coordinator = Arc::new(WriterLockCoordinator::new(home.path()));
        let thread_id = codex_protocol::ThreadId::default();
        let writer_lock = coordinator.acquire(thread_id).expect("writer lock");
        let state = RootWriterAuthorityState::new(
            thread_id,
            home.path().join("rollout.jsonl"),
            writer_lock,
        );
        (home, state)
    }

    #[test]
    fn weak_handle_does_not_keep_owner_alive() {
        let (_home, state) = authority_state();
        let authority = state.downgrade();
        assert!(authority.begin_write().is_ok());

        drop(state);
        assert!(authority.begin_write().is_err());
    }

    #[test]
    fn in_flight_permit_keeps_os_lock_but_cannot_mint_more_writes_after_owner_detaches() {
        let (home, state) = authority_state();
        let authority = state.downgrade();
        let thread_id = authority.thread_id();
        let write = authority.begin_write().expect("begin write");

        state.detach_owner();
        drop(state);
        assert!(authority.begin_write().is_err());
        let competitor = Arc::new(WriterLockCoordinator::new(home.path()));
        let error = match competitor.acquire(thread_id) {
            Ok(_) => panic!("write permit must retain the OS writer lock"),
            Err(error) => error,
        };
        assert!(matches!(error, ThreadStoreError::Conflict { .. }));

        drop(write);
        let _next_owner = competitor
            .acquire(thread_id)
            .expect("OS writer lock should release after the final permit");
    }

    #[tokio::test]
    async fn close_waits_for_writes_and_abort_reopens_authority() {
        let (_home, state) = authority_state();
        let authority = state.downgrade();
        let write = authority.begin_write().expect("begin write");

        let closing = tokio::spawn({
            let authority = authority.clone();
            async move { authority.begin_close().await }
        });
        while let Ok(permit) = authority.begin_write() {
            drop(permit);
            tokio::task::yield_now().await;
        }
        assert!(!closing.is_finished());

        drop(write);
        let close = closing
            .await
            .expect("close task")
            .expect("begin close after write drains");
        close.abort().expect("abort close");
        assert!(authority.begin_write().is_ok());
    }

    #[tokio::test]
    async fn completed_close_permanently_rejects_writes() {
        let (_home, state) = authority_state();
        let authority = state.downgrade();
        authority
            .begin_close()
            .await
            .expect("begin close")
            .complete()
            .expect("complete close");

        assert!(authority.begin_write().is_err());
        assert!(authority.begin_close().await.is_err());
    }

    #[tokio::test]
    async fn cancelling_close_wait_reopens_authority() {
        let (_home, state) = authority_state();
        let authority = state.downgrade();
        let write = authority.begin_write().expect("begin write");
        let closing = tokio::spawn({
            let authority = authority.clone();
            async move { authority.begin_close().await }
        });
        while let Ok(permit) = authority.begin_write() {
            drop(permit);
            tokio::task::yield_now().await;
        }

        closing.abort();
        assert!(closing.await.expect_err("cancel close").is_cancelled());
        assert!(authority.begin_write().is_ok());
        drop(write);
    }
}
