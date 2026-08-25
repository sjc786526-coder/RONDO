use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionMeta;
use codex_protocol::protocol::ThreadHistoryMode;
use std::any::Any;
use std::future::Future;
use std::pin::Pin;

use crate::AppendThreadItemsParams;
use crate::ArchiveThreadParams;
use crate::ArchiveThreadsParams;
use crate::CreateThreadParams;
use crate::CreateThreadSectionParams;
use crate::DeleteThreadParams;
use crate::DeleteThreadSectionParams;
use crate::DeleteThreadsParams;
use crate::ItemPage;
use crate::ListItemsParams;
use crate::ListSessionLocatorsError;
use crate::ListSessionLocatorsParams;
use crate::ListThreadSectionsParams;
use crate::ListThreadsParams;
use crate::ListTurnsParams;
use crate::LoadThreadHistoryParams;
use crate::MoveThreadToSectionParams;
use crate::PrepareForkParams;
use crate::PreparedFork;
use crate::ReadSessionMetaError;
use crate::ReadSessionMetaParams;
use crate::ReadThreadByRolloutPathParams;
use crate::ReadThreadParams;
use crate::RenameThreadSectionParams;
use crate::ResumeThreadParams;
use crate::RootWriterAuthority;
use crate::SearchThreadOccurrencesParams;
use crate::SearchThreadsParams;
use crate::SessionLocatorPage;
use crate::StoredModelContext;
use crate::StoredThread;
use crate::StoredThreadHistory;
use crate::StoredThreadSection;
use crate::StoredThreadSectionsPage;
use crate::ThreadOccurrenceSearchPage;
use crate::ThreadPage;
use crate::ThreadSearchPage;
use crate::ThreadStoreError;
use crate::ThreadStoreResult;
use crate::TurnPage;
use crate::UpdateThreadMetadataParams;

/// Future returned by [`ThreadStore`] operations.
pub type ThreadStoreFuture<'a, T> = Pin<Box<dyn Future<Output = ThreadStoreResult<T>> + Send + 'a>>;

/// Future returned by the canonical SessionMeta read seam.
pub type ReadSessionMetaFuture<'a> =
    Pin<Box<dyn Future<Output = Result<SessionMeta, ReadSessionMetaError>> + Send + 'a>>;

/// Future returned by fail-closed durable-session locator discovery.
pub type ListSessionLocatorsFuture<'a> =
    Pin<Box<dyn Future<Output = Result<SessionLocatorPage, ListSessionLocatorsError>> + Send + 'a>>;

pub(crate) async fn archive_thread_ids_in_order<F, Fut>(
    thread_ids: Vec<ThreadId>,
    mut archive_thread: F,
) -> ThreadStoreResult<Vec<ThreadId>>
where
    F: FnMut(ThreadId) -> Fut,
    Fut: Future<Output = ThreadStoreResult<()>>,
{
    let mut archived_thread_ids = Vec::new();
    for thread_id in thread_ids {
        match archive_thread(thread_id).await {
            Ok(()) => archived_thread_ids.push(thread_id),
            Err(err) if archived_thread_ids.is_empty() => return Err(err),
            Err(err) => {
                return Err(ThreadStoreError::Internal {
                    message: format!(
                        "archive partially completed; archived thread ids: {}; failed thread {thread_id}: {err}",
                        archived_thread_ids
                            .iter()
                            .map(ToString::to_string)
                            .collect::<Vec<_>>()
                            .join(", ")
                    ),
                });
            }
        }
    }
    Ok(archived_thread_ids)
}

/// Storage-neutral thread persistence boundary.
pub trait ThreadStore: Any + Send + Sync {
    /// Return this store as [`Any`] for implementation-owned escape hatches.
    fn as_any(&self) -> &dyn Any;

    /// Returns the history mode to use when history does not carry a persisted mode.
    ///
    /// The default is legacy so existing stores stay compatible. Stores whose durable contract is
    /// already paginated should override this instead of relying on core to infer storage behavior.
    fn default_history_mode(&self) -> ThreadHistoryMode {
        ThreadHistoryMode::Legacy
    }

    /// Creates a new live thread.
    fn create_thread(&self, params: CreateThreadParams) -> ThreadStoreFuture<'_, ()>;

    /// Reopens an existing thread for live appends.
    fn resume_thread(&self, params: ResumeThreadParams) -> ThreadStoreFuture<'_, ()>;

    /// Appends raw rollout items to a live thread.
    ///
    /// Implementations should apply the shared rollout persistence policy before writing durable
    /// replay history and before updating any implementation-owned projections.
    fn append_items(&self, params: AppendThreadItemsParams) -> ThreadStoreFuture<'_, ()>;

    /// Materializes the thread if persistence is lazy, then persists all queued items.
    fn persist_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()>;

    /// Flushes all queued items and returns once they are durable/readable.
    fn flush_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()>;

    /// Returns a weak Team mutation capability backed by this live thread's writer ownership.
    ///
    /// Stores without a cross-process canonical writer retain this fail-closed default.
    fn writer_authority(&self, _thread_id: ThreadId) -> ThreadStoreFuture<'_, RootWriterAuthority> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "writer_authority",
            })
        })
    }

    /// Flushes pending items and closes the live thread writer.
    fn shutdown_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()>;

    /// Discards the live thread writer without forcing pending in-memory items to become durable.
    ///
    /// Core calls this when session initialization fails after a live writer has been created.
    /// Implementations should release any live writer resources for the thread while preserving
    /// already-durable thread data.
    fn discard_thread(&self, thread_id: ThreadId) -> ThreadStoreFuture<'_, ()>;

    /// Loads persisted history for resume, fork, rollback, and memory jobs.
    fn load_history(
        &self,
        params: LoadThreadHistoryParams,
    ) -> ThreadStoreFuture<'_, StoredThreadHistory>;

    /// Loads the persisted rollout items needed to reconstruct the latest model-visible context.
    ///
    /// Implementations that cannot perform a targeted read may return the full persisted history.
    fn load_latest_model_context(
        &self,
        _params: LoadThreadHistoryParams,
    ) -> ThreadStoreFuture<'_, StoredModelContext> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "load_latest_model_context",
            })
        })
    }

    /// Freezes source history and model context used to initialize a referenced fork.
    ///
    /// Stores without reference-backed fork support can retain this default implementation.
    fn prepare_fork(&self, _params: PrepareForkParams) -> ThreadStoreFuture<'_, PreparedFork> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "prepare_fork",
            })
        })
    }

    /// Reads the canonical persisted SessionMeta without activating or mutating the thread.
    ///
    /// Implementations must not open a writer, repair metadata, update an index, or resume the
    /// thread while serving this query. Stores that cannot prove those semantics should retain the
    /// fail-closed default.
    fn read_session_meta(&self, _params: ReadSessionMetaParams) -> ReadSessionMetaFuture<'_> {
        Box::pin(async {
            Err(ReadSessionMetaError::Unsupported {
                operation: "read_session_meta",
            })
        })
    }

    /// Lists state-backed thread locators for canonical durable-session classification.
    ///
    /// Implementations must use a bounded, stable keyset and must not scan rollouts, repair an
    /// index, activate a thread, or treat locator rows as canonical Session identity. Stores that
    /// cannot prove those semantics should retain the fail-closed default.
    fn list_session_locators(
        &self,
        _params: ListSessionLocatorsParams,
    ) -> ListSessionLocatorsFuture<'_> {
        Box::pin(async {
            Err(ListSessionLocatorsError::Unsupported {
                operation: "list_session_locators",
            })
        })
    }

    /// Reads a thread summary and optionally its persisted history.
    fn read_thread(&self, params: ReadThreadParams) -> ThreadStoreFuture<'_, StoredThread>;

    /// Reads a rollout-backed thread by path when the store supports path-addressed lookups.
    ///
    /// Deprecated: new callers should use [`ThreadStore::read_thread`] instead.
    fn read_thread_by_rollout_path(
        &self,
        params: ReadThreadByRolloutPathParams,
    ) -> ThreadStoreFuture<'_, StoredThread>;

    /// Lists stored threads matching the supplied filters.
    fn list_threads(&self, params: ListThreadsParams) -> ThreadStoreFuture<'_, ThreadPage>;

    /// Whether this store can discover and manage independently persisted thread sections.
    fn supports_thread_sections(&self) -> bool {
        false
    }

    /// Lists independently persisted thread sections.
    fn list_thread_sections(
        &self,
        _params: ListThreadSectionsParams,
    ) -> ThreadStoreFuture<'_, StoredThreadSectionsPage> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "threadSection/list",
            })
        })
    }

    /// Creates a custom thread section with a stable, server-assigned identity.
    fn create_thread_section(
        &self,
        _params: CreateThreadSectionParams,
    ) -> ThreadStoreFuture<'_, StoredThreadSection> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "threadSection/create",
            })
        })
    }

    /// Renames a custom thread section, returning `None` when it does not exist.
    fn rename_thread_section(
        &self,
        _params: RenameThreadSectionParams,
    ) -> ThreadStoreFuture<'_, Option<StoredThreadSection>> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "threadSection/update",
            })
        })
    }

    /// Deletes a custom thread section and reports whether it existed.
    fn delete_thread_section(
        &self,
        _params: DeleteThreadSectionParams,
    ) -> ThreadStoreFuture<'_, bool> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "threadSection/delete",
            })
        })
    }

    /// Whether paginated threads can hydrate durable history through turn and item lists.
    fn supports_paginated_history_lists(&self) -> bool {
        false
    }

    /// Searches stored threads and returns search-only preview metadata.
    fn search_threads(
        &self,
        _params: SearchThreadsParams,
    ) -> ThreadStoreFuture<'_, ThreadSearchPage> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "thread/search",
            })
        })
    }

    /// Searches visible message occurrences within one paginated thread.
    fn search_thread_occurrences(
        &self,
        _params: SearchThreadOccurrencesParams,
    ) -> ThreadStoreFuture<'_, ThreadOccurrenceSearchPage> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "thread/searchOccurrences",
            })
        })
    }

    /// Lists turns within a stored thread.
    fn list_turns(&self, _params: ListTurnsParams) -> ThreadStoreFuture<'_, TurnPage> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "list_turns",
            })
        })
    }

    /// Lists persisted items within a stored thread, optionally filtered to a turn.
    fn list_items(&self, _params: ListItemsParams) -> ThreadStoreFuture<'_, ItemPage> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "list_items",
            })
        })
    }

    /// Applies a literal metadata patch and returns the updated thread.
    ///
    /// Implementations should apply the supplied fields directly. Policy such as deciding whether
    /// an append-derived preview should be emitted belongs above the store.
    fn update_thread_metadata(
        &self,
        params: UpdateThreadMetadataParams,
    ) -> ThreadStoreFuture<'_, StoredThread>;

    /// Moves a thread to, within, or out of a server-ordered section.
    fn move_thread_to_section(
        &self,
        _params: MoveThreadToSectionParams,
    ) -> ThreadStoreFuture<'_, ()> {
        Box::pin(async {
            Err(ThreadStoreError::Unsupported {
                operation: "thread/section/move",
            })
        })
    }

    /// Archives a thread.
    fn archive_thread(&self, params: ArchiveThreadParams) -> ThreadStoreFuture<'_, ()>;

    /// Archives threads in order, returning the successfully archived thread ids.
    ///
    /// Any failure is returned to the caller. If an implementation cannot make the operation
    /// atomic, its error must identify already-completed members rather than reporting success for
    /// a partially archived subtree.
    fn archive_threads(
        &self,
        params: ArchiveThreadsParams,
    ) -> ThreadStoreFuture<'_, Vec<ThreadId>> {
        Box::pin(async move {
            archive_thread_ids_in_order(params.thread_ids, |thread_id| {
                self.archive_thread(ArchiveThreadParams { thread_id })
            })
            .await
        })
    }

    /// Unarchives a thread and returns its updated metadata.
    fn unarchive_thread(&self, params: ArchiveThreadParams) -> ThreadStoreFuture<'_, StoredThread>;

    /// Deletes a thread's persisted rollout data and associated metadata.
    fn delete_thread(&self, params: DeleteThreadParams) -> ThreadStoreFuture<'_, ()>;

    /// Deletes threads in order, treating already-missing members as deleted.
    ///
    /// Stores with request-scoped delete preflight should override this instead of repeating
    /// that work through [`ThreadStore::delete_thread`].
    fn delete_threads(&self, params: DeleteThreadsParams) -> ThreadStoreFuture<'_, ()> {
        Box::pin(async move {
            for thread_id in params.thread_ids {
                match self.delete_thread(DeleteThreadParams { thread_id }).await {
                    Ok(()) | Err(ThreadStoreError::ThreadNotFound { .. }) => {}
                    Err(err) => return Err(err),
                }
            }
            Ok(())
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicUsize;
    use std::sync::atomic::Ordering;

    #[tokio::test]
    async fn archive_batch_reports_runtime_partial_failure() {
        let thread_ids = vec![ThreadId::new(), ThreadId::new(), ThreadId::new()];
        let attempts = AtomicUsize::new(0);

        let error = archive_thread_ids_in_order(thread_ids.clone(), |thread_id| {
            let attempt = attempts.fetch_add(1, Ordering::AcqRel);
            async move {
                if attempt == 1 {
                    Err(ThreadStoreError::Conflict {
                        message: format!("simulated runtime failure for {thread_id}"),
                    })
                } else {
                    Ok(())
                }
            }
        })
        .await
        .expect_err("the batch must not report success after a runtime partial failure");

        let message = error.to_string();
        assert!(message.contains(&thread_ids[0].to_string()));
        assert!(message.contains(&thread_ids[1].to_string()));
        assert_eq!(attempts.load(Ordering::Acquire), 2);
    }
}
