use codex_protocol::ThreadId;
use codex_protocol::protocol::ThreadHistoryMode;

/// Result type returned by thread-store operations.
pub type ThreadStoreResult<T> = Result<T, ThreadStoreError>;

/// Failure returned by fail-closed durable-session locator discovery.
#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error)]
pub enum ListSessionLocatorsError {
    /// The caller supplied an invalid bounded-list request.
    #[error("invalid durable-session locator request: {message}")]
    InvalidRequest {
        /// Explanation of the invalid request.
        message: String,
    },

    /// The store implementation cannot provide read-only locator discovery.
    #[error("thread-store unsupported operation: {operation}")]
    Unsupported {
        /// Stable operation name for callers that map unsupported reads.
        operation: &'static str,
    },

    /// The locator backend exists but could not serve this query.
    #[error("durable-session locator source is unavailable: {message}")]
    Unavailable {
        /// Backend failure detail.
        message: String,
    },

    /// The locator backend returned a row that could not be classified safely.
    #[error("durable-session locator row is corrupt: {message}")]
    Corrupt {
        /// Row decoding or classification failure detail.
        message: String,
    },
}

/// Failure returned by the canonical [`SessionMeta`](codex_protocol::protocol::SessionMeta)
/// read seam.
///
/// This is separate from [`ThreadStoreError`] so query callers can distinguish missing,
/// unsupported, unavailable, corrupt, and identity-mismatched durable metadata without changing
/// the error contract of existing thread operations.
#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error)]
pub enum ReadSessionMetaError {
    /// The requested thread has no eligible persisted rollout.
    #[error("canonical SessionMeta for thread {thread_id} was not found")]
    NotFound {
        /// Thread id requested by the caller.
        thread_id: ThreadId,
    },

    /// The store implementation does not expose canonical session metadata.
    #[error("thread-store unsupported operation: {operation}")]
    Unsupported {
        /// Stable operation name for callers that map unsupported reads.
        operation: &'static str,
    },

    /// The canonical metadata locator backend could not serve the read.
    #[error("canonical SessionMeta source for thread {thread_id} is unavailable: {message}")]
    Unavailable {
        /// Thread id requested by the caller.
        thread_id: ThreadId,
        /// Backend failure detail.
        message: String,
    },

    /// The eligible persisted rollout could not yield canonical session metadata.
    #[error("canonical SessionMeta for thread {thread_id} is corrupt: {message}")]
    Corrupt {
        /// Thread id requested by the caller.
        thread_id: ThreadId,
        /// Storage or decoding failure detail.
        message: String,
    },

    /// The located rollout's canonical metadata belongs to another thread.
    #[error(
        "canonical SessionMeta identity mismatch: requested thread {requested_thread_id}, found {actual_thread_id}"
    )]
    IdentityMismatch {
        /// Thread id requested by the caller.
        requested_thread_id: ThreadId,
        /// Thread id encoded in the canonical SessionMeta.
        actual_thread_id: ThreadId,
    },
}

pub(crate) fn reject_paginated_history_mode(
    history_mode: ThreadHistoryMode,
) -> ThreadStoreResult<()> {
    if matches!(history_mode, ThreadHistoryMode::Paginated) {
        return Err(ThreadStoreError::Unsupported {
            operation: "paginated_threads",
        });
    }
    Ok(())
}

/// Error type shared by thread-store implementations.
#[derive(Debug, thiserror::Error)]
pub enum ThreadStoreError {
    /// The requested thread does not exist in this store.
    #[error("thread {thread_id} not found")]
    ThreadNotFound {
        /// Thread id requested by the caller.
        thread_id: ThreadId,
    },

    /// The caller supplied invalid request data.
    #[error("invalid thread-store request: {message}")]
    InvalidRequest {
        /// User-facing explanation of the invalid request.
        message: String,
    },

    /// The operation conflicted with current store state.
    #[error("thread-store conflict: {message}")]
    Conflict {
        /// User-facing explanation of the conflict.
        message: String,
    },

    /// An ordered batch crossed its mutation boundary before a later member failed.
    #[error(
        "thread-store operation partially completed; completed thread ids: {completed_thread_ids:?}; failed thread {failed_thread_id}: {message}"
    )]
    Partial {
        completed_thread_ids: Vec<ThreadId>,
        failed_thread_id: ThreadId,
        message: String,
    },

    /// The store implementation does not support this operation yet.
    #[error("thread-store unsupported operation: {operation}")]
    Unsupported {
        /// Stable operation name for callers that need to map unsupported operations.
        operation: &'static str,
    },

    /// Catch-all for implementation failures that do not fit a more specific category.
    #[error("thread-store internal error: {message}")]
    Internal {
        /// User-facing explanation of the implementation failure.
        message: String,
    },
}
