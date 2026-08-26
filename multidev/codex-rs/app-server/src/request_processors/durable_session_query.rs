//! Formal, read-only Durable Session discovery and projection.
//!
//! The dedicated thread-store locator is only a bounded index query. Every returned Session is
//! authenticated by the canonical Root `SessionMeta` and projected from one complete committed
//! Team snapshot. This module never resumes a thread, acquires writer authority, or reads live
//! Team state.

use super::*;
use base64::Engine;
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use codex_app_server_protocol::DurableSessionListIncompleteReason;
use codex_app_server_protocol::DurableSessionListParams;
use codex_app_server_protocol::DurableSessionListResponse;
use codex_app_server_protocol::DurableSessionReadIssue;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use codex_app_server_protocol::DurableSessionReadStatus;
use codex_app_server_protocol::DurableSessionResidency;
use codex_app_server_protocol::DurableSessionStorageStatus;
use codex_app_server_protocol::DurableSessionView;
use codex_core::DurableSessionReadError as CoreReadError;
use codex_core::project_committed_durable_session;
use codex_protocol::SessionId;
use codex_protocol::protocol::SessionMeta;
use codex_thread_store::ListSessionLocatorsError;
use codex_thread_store::ListSessionLocatorsParams;
use codex_thread_store::ReadSessionMetaError;
use codex_thread_store::ReadSessionMetaParams as StoreReadSessionMetaParams;
use codex_thread_store::SessionLocatorCursor;
use codex_thread_store::SessionLocatorStorage;
use serde::Deserialize;
use serde::Serialize;

#[path = "durable_session_query_projection.rs"]
mod projection;
use projection::authenticated_delete_retry_view;
use projection::authenticated_view;
use projection::core_read_status;
use projection::team_projection;
use projection::unavailable_view;

const SESSION_LIST_DEFAULT_LIMIT: usize = 25;
const SESSION_LIST_MAX_LIMIT: usize = 100;
const SESSION_LIST_MAX_SCANNED_THREADS: usize = 400;
const SESSION_LIST_MAX_SOURCE_PAGES: usize = 16;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum StorageScope {
    Active,
    Archived,
}

impl StorageScope {
    fn from_archived(archived: bool) -> Self {
        if archived {
            Self::Archived
        } else {
            Self::Active
        }
    }

    pub(super) fn status(self) -> DurableSessionStorageStatus {
        match self {
            Self::Active => DurableSessionStorageStatus::Active,
            Self::Archived => DurableSessionStorageStatus::Archived,
        }
    }

    fn archived(self) -> bool {
        matches!(self, Self::Archived)
    }

    fn locator_storage(self) -> SessionLocatorStorage {
        match self {
            Self::Active => SessionLocatorStorage::Active,
            Self::Archived => SessionLocatorStorage::Archived,
        }
    }
}

#[derive(Debug)]
pub(super) enum CanonicalMetaFailure {
    NotFound,
    Unavailable,
    Unsupported,
    Corrupt,
    IdentityMismatch,
    SourceChanged,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct SessionListCursor {
    version: u8,
    archived: bool,
    source_cursor: SessionLocatorCursor,
}

impl ThreadRequestProcessor {
    pub(crate) async fn durable_session_list(
        &self,
        params: DurableSessionListParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_durable_session_query_enabled()?;
        let scope = StorageScope::from_archived(params.archived);
        if params.limit == Some(0) {
            return Err(invalid_request(
                "Session list limit must be greater than zero",
            ));
        }
        let page_size = params
            .limit
            .map(|limit| limit as usize)
            .unwrap_or(SESSION_LIST_DEFAULT_LIMIT)
            .min(SESSION_LIST_MAX_LIMIT);
        let continued_request = params.cursor.is_some();
        let mut source_cursor = params
            .cursor
            .as_deref()
            .map(|cursor| decode_session_list_cursor(cursor, scope))
            .transpose()?;
        let mut last_source_cursor = source_cursor.clone();
        let mut data = Vec::with_capacity(page_size);
        let mut scanned = 0usize;
        let mut source_pages = 0usize;
        let mut next_source_cursor = None;
        let mut incomplete_reason = None;

        while data.len() < page_size
            && scanned < SESSION_LIST_MAX_SCANNED_THREADS
            && source_pages < SESSION_LIST_MAX_SOURCE_PAGES
        {
            source_pages = source_pages.saturating_add(1);
            let source_page_size = (page_size - data.len())
                .min(SESSION_LIST_MAX_LIMIT)
                .min(SESSION_LIST_MAX_SCANNED_THREADS - scanned)
                .max(1);
            let page = match self
                .thread_store
                .list_session_locators(ListSessionLocatorsParams {
                    page_size: source_page_size,
                    cursor: source_cursor.clone(),
                    storage: scope.locator_storage(),
                })
                .await
            {
                Ok(page) => page,
                Err(error) => {
                    tracing::warn!(%error, "Durable Session locator query failed");
                    let reason = locator_failure_reason(error)?;
                    incomplete_reason = Some(reason);
                    break;
                }
            };
            scanned = scanned.saturating_add(page.items.len());
            next_source_cursor = page.next_cursor;

            for candidate in page.items {
                let root_thread_id = candidate.thread_id;
                let meta = match self.read_canonical_meta(root_thread_id, scope).await {
                    Ok(meta) => meta,
                    Err(CanonicalMetaFailure::NotFound) => {
                        incomplete_reason
                            .get_or_insert(DurableSessionListIncompleteReason::SourceChanged);
                        continue;
                    }
                    Err(CanonicalMetaFailure::Unavailable) => {
                        incomplete_reason
                            .get_or_insert(DurableSessionListIncompleteReason::SourceUnavailable);
                        continue;
                    }
                    Err(CanonicalMetaFailure::Unsupported) => {
                        incomplete_reason
                            .get_or_insert(DurableSessionListIncompleteReason::SourceUnsupported);
                        continue;
                    }
                    Err(CanonicalMetaFailure::Corrupt) => {
                        incomplete_reason
                            .get_or_insert(DurableSessionListIncompleteReason::RecordUnreadable);
                        continue;
                    }
                    Err(CanonicalMetaFailure::IdentityMismatch) => {
                        incomplete_reason.get_or_insert(
                            DurableSessionListIncompleteReason::ClassificationFailed,
                        );
                        continue;
                    }
                    Err(CanonicalMetaFailure::SourceChanged) => {
                        incomplete_reason
                            .get_or_insert(DurableSessionListIncompleteReason::SourceChanged);
                        continue;
                    }
                };
                // Legacy records and child rollouts are intentionally filtered from the formal
                // Durable Session namespace; neither is upgraded or repaired by this query.
                if meta.parent_thread_id.is_some() || meta.durable_team.is_none() {
                    continue;
                }
                let view = self
                    .project_authenticated_session(meta, scope, root_thread_id)
                    .await;
                if matches!(
                    &view.read_status,
                    DurableSessionReadStatus::Incomplete {
                        issue: DurableSessionReadIssue::SourceChanged
                    }
                ) {
                    incomplete_reason
                        .get_or_insert(DurableSessionListIncompleteReason::SourceChanged);
                }
                data.push(view);
            }

            if data.len() >= page_size || next_source_cursor.is_none() {
                break;
            }
            let Some(next) = next_source_cursor.clone() else {
                break;
            };
            if last_source_cursor.as_ref() == Some(&next) {
                incomplete_reason.get_or_insert(DurableSessionListIncompleteReason::SourceChanged);
                break;
            }
            last_source_cursor = Some(next.clone());
            source_cursor = Some(next);
        }

        let source_exhausted = next_source_cursor.is_none();
        if data.len() < page_size
            && !source_exhausted
            && (scanned >= SESSION_LIST_MAX_SCANNED_THREADS
                || source_pages >= SESSION_LIST_MAX_SOURCE_PAGES)
        {
            incomplete_reason.get_or_insert(DurableSessionListIncompleteReason::BudgetExhausted);
        }
        // The state locator has no collection generation. A cursor continuation crosses request
        // boundaries, and filtering across multiple locator pages crosses source reads within one
        // request. In either case membership continuity cannot be proven, so retain the useful
        // bounded data but do not claim a complete source view. More specific typed failures win.
        if continued_request || source_pages > 1 {
            incomplete_reason.get_or_insert(DurableSessionListIncompleteReason::SourceChanged);
        }
        let next_cursor = next_source_cursor
            .as_ref()
            .map(|cursor| encode_session_list_cursor(cursor, scope))
            .transpose()?;
        Ok(Some(
            DurableSessionListResponse {
                data,
                next_cursor,
                complete: incomplete_reason.is_none(),
                incomplete_reason,
            }
            .into(),
        ))
    }

    pub(crate) async fn durable_session_read(
        &self,
        params: DurableSessionReadParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_durable_session_query_enabled()?;
        let session_id = SessionId::from_string(&params.session_id)
            .map_err(|error| invalid_request(format!("invalid Session id: {error}")))?;
        let root_thread_id = ThreadId::from_string(&params.root_thread_id)
            .map_err(|error| invalid_request(format!("invalid Root thread id: {error}")))?;

        let (meta, scope) = match self.read_canonical_meta_anywhere(root_thread_id).await {
            Ok(value) => value,
            Err(error) => {
                return Ok(Some(
                    DurableSessionReadResponse {
                        session: unavailable_view(session_id, meta_failure_status(error)),
                    }
                    .into(),
                ));
            }
        };
        if meta.parent_thread_id.is_some() {
            return Ok(Some(
                DurableSessionReadResponse {
                    session: unavailable_view(
                        session_id,
                        DurableSessionReadStatus::Unavailable {
                            issue: DurableSessionReadIssue::NotCanonicalRoot,
                        },
                    ),
                }
                .into(),
            ));
        }
        if meta.session_id != session_id {
            return Ok(Some(
                DurableSessionReadResponse {
                    session: unavailable_view(
                        session_id,
                        DurableSessionReadStatus::Unavailable {
                            issue: DurableSessionReadIssue::SessionRootIdentityMismatch,
                        },
                    ),
                }
                .into(),
            ));
        }
        if meta.durable_team.is_none() {
            return Ok(Some(
                DurableSessionReadResponse {
                    session: authenticated_view(
                        &meta,
                        scope,
                        DurableSessionReadStatus::Unsupported {
                            issue: DurableSessionReadIssue::LegacySession,
                        },
                        self.observed_runtime(meta.session_id, root_thread_id)
                            .await
                            .0,
                        None,
                        self.config.features.enabled(Feature::DurableSessionControl),
                        None,
                    ),
                }
                .into(),
            ));
        }

        let session = self
            .project_authenticated_session(meta, scope, root_thread_id)
            .await;
        Ok(Some(DurableSessionReadResponse { session }.into()))
    }

    fn ensure_durable_session_query_enabled(&self) -> Result<(), JSONRPCErrorError> {
        if self.config.features.enabled(Feature::DurableSessionQuery) {
            Ok(())
        } else {
            Err(invalid_request(
                "Durable Session query is disabled; enable features.durable_session_query and restart Codex",
            ))
        }
    }

    pub(super) async fn read_canonical_meta_anywhere(
        &self,
        root_thread_id: ThreadId,
    ) -> Result<(SessionMeta, StorageScope), CanonicalMetaFailure> {
        match self
            .read_canonical_meta(root_thread_id, StorageScope::Active)
            .await
        {
            Ok(meta) => Ok((meta, StorageScope::Active)),
            Err(CanonicalMetaFailure::NotFound) => self
                .read_canonical_meta(root_thread_id, StorageScope::Archived)
                .await
                .map(|meta| (meta, StorageScope::Archived)),
            Err(error) => Err(error),
        }
    }

    async fn read_canonical_meta(
        &self,
        root_thread_id: ThreadId,
        scope: StorageScope,
    ) -> Result<SessionMeta, CanonicalMetaFailure> {
        if matches!(scope, StorageScope::Archived) {
            match self
                .thread_store
                .read_session_meta(StoreReadSessionMetaParams {
                    thread_id: root_thread_id,
                    include_archived: false,
                })
                .await
            {
                Ok(_) => return Err(CanonicalMetaFailure::SourceChanged),
                Err(ReadSessionMetaError::NotFound { .. }) => {}
                Err(error) => return Err(map_meta_error(error)),
            }
        }
        self.thread_store
            .read_session_meta(StoreReadSessionMetaParams {
                thread_id: root_thread_id,
                include_archived: scope.archived(),
            })
            .await
            .map_err(map_meta_error)
    }

    pub(super) async fn project_authenticated_session(
        &self,
        meta: SessionMeta,
        scope: StorageScope,
        root_thread_id: ThreadId,
    ) -> DurableSessionView {
        let control_enabled = self.config.features.enabled(Feature::DurableSessionControl);
        let codex_home = self.config.codex_home.to_path_buf();
        let projection_meta = meta.clone();
        let projected = tokio::task::spawn_blocking(move || {
            project_committed_durable_session(codex_home.as_path(), &projection_meta)
        })
        .await;
        let reread = self.read_canonical_meta(root_thread_id, scope).await;
        let (residency, owner_incarnation) =
            self.observed_runtime(meta.session_id, root_thread_id).await;
        if !matches!(reread, Ok(ref after) if same_durable_lineage(&meta, after)) {
            return authenticated_view(
                &meta,
                scope,
                DurableSessionReadStatus::Incomplete {
                    issue: DurableSessionReadIssue::SourceChanged,
                },
                residency,
                None,
                control_enabled,
                owner_incarnation,
            );
        }
        match projected {
            Ok(Ok(team)) => authenticated_view(
                &meta,
                scope,
                DurableSessionReadStatus::Available,
                residency,
                Some(team_projection(team)),
                control_enabled,
                owner_incarnation,
            ),
            Ok(Err(CoreReadError::SnapshotMissing)) => {
                authenticated_delete_retry_view(&meta, scope, residency, control_enabled)
            }
            Ok(Err(error)) => authenticated_view(
                &meta,
                scope,
                core_read_status(error),
                residency,
                None,
                control_enabled,
                owner_incarnation,
            ),
            Err(error) => {
                tracing::warn!(%root_thread_id, %error, "Durable Session snapshot task failed");
                authenticated_view(
                    &meta,
                    scope,
                    DurableSessionReadStatus::Unavailable {
                        issue: DurableSessionReadIssue::SourceUnavailable,
                    },
                    residency,
                    None,
                    control_enabled,
                    owner_incarnation,
                )
            }
        }
    }

    async fn observed_runtime(
        &self,
        session_id: SessionId,
        root_thread_id: ThreadId,
    ) -> (DurableSessionResidency, Option<String>) {
        if let Ok(root) = self.thread_manager.get_thread(root_thread_id).await
            && root.is_running()
        {
            let configured = root.session_configured();
            if configured.parent_thread_id.is_none()
                && configured.thread_id == root_thread_id
                && configured.session_id == session_id
            {
                return match root.durable_session_control_owner_incarnation_id().await {
                    Ok(owner_incarnation) => (
                        DurableSessionResidency::ObservedOwnerHere,
                        Some(owner_incarnation),
                    ),
                    Err(error) => {
                        tracing::debug!(%root_thread_id, %error, "loaded Root owner incarnation is unavailable");
                        (DurableSessionResidency::OwnerUnavailableHere, None)
                    }
                };
            }
        }
        for loaded_id in self.thread_manager.list_thread_ids().await {
            let Ok(thread) = self.thread_manager.get_thread(loaded_id).await else {
                continue;
            };
            if !thread.is_running() {
                continue;
            }
            let configured = thread.session_configured();
            if configured.parent_thread_id.is_some() && configured.session_id == session_id {
                return (DurableSessionResidency::OwnerUnavailableHere, None);
            }
        }
        (DurableSessionResidency::NotObservedHere, None)
    }
}

fn same_durable_lineage(before: &SessionMeta, after: &SessionMeta) -> bool {
    before.id == after.id
        && before.session_id == after.session_id
        && before.parent_thread_id == after.parent_thread_id
        && before.durable_team == after.durable_team
}

fn map_meta_error(error: ReadSessionMetaError) -> CanonicalMetaFailure {
    match error {
        ReadSessionMetaError::NotFound { .. } => CanonicalMetaFailure::NotFound,
        ReadSessionMetaError::Unavailable { .. } => CanonicalMetaFailure::Unavailable,
        ReadSessionMetaError::Unsupported { .. } => CanonicalMetaFailure::Unsupported,
        ReadSessionMetaError::Corrupt { .. } => CanonicalMetaFailure::Corrupt,
        ReadSessionMetaError::IdentityMismatch { .. } => CanonicalMetaFailure::IdentityMismatch,
    }
}

fn meta_failure_status(failure: CanonicalMetaFailure) -> DurableSessionReadStatus {
    match failure {
        CanonicalMetaFailure::NotFound => DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SessionNotFound,
        },
        CanonicalMetaFailure::Unavailable => DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SourceUnavailable,
        },
        CanonicalMetaFailure::Unsupported => DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::SourceUnsupported,
        },
        CanonicalMetaFailure::Corrupt => DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::SessionMetaUnreadable,
        },
        CanonicalMetaFailure::IdentityMismatch => DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::IdentityUnavailable,
        },
        CanonicalMetaFailure::SourceChanged => DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::SourceChanged,
        },
    }
}

fn encode_session_list_cursor(
    source_cursor: &SessionLocatorCursor,
    scope: StorageScope,
) -> Result<String, JSONRPCErrorError> {
    let payload = serde_json::to_vec(&SessionListCursor {
        version: 1,
        archived: scope.archived(),
        source_cursor: source_cursor.clone(),
    })
    .map_err(|error| internal_error(format!("failed to encode Session cursor: {error}")))?;
    Ok(URL_SAFE_NO_PAD.encode(payload))
}

fn decode_session_list_cursor(
    cursor: &str,
    scope: StorageScope,
) -> Result<SessionLocatorCursor, JSONRPCErrorError> {
    let payload = URL_SAFE_NO_PAD
        .decode(cursor)
        .map_err(|error| invalid_request(format!("invalid Session cursor: {error}")))?;
    let decoded: SessionListCursor = serde_json::from_slice(&payload)
        .map_err(|error| invalid_request(format!("invalid Session cursor: {error}")))?;
    if decoded.version != 1
        || decoded.archived != scope.archived()
        || decoded.source_cursor.storage != scope.locator_storage()
    {
        return Err(invalid_request(
            "Session cursor does not belong to the selected active/archived source",
        ));
    }
    Ok(decoded.source_cursor)
}

fn locator_failure_reason(
    error: ListSessionLocatorsError,
) -> Result<DurableSessionListIncompleteReason, JSONRPCErrorError> {
    match error {
        ListSessionLocatorsError::InvalidRequest { message } => Err(invalid_request(format!(
            "invalid Session locator cursor: {message}"
        ))),
        ListSessionLocatorsError::Unsupported { .. } => {
            Ok(DurableSessionListIncompleteReason::SourceUnsupported)
        }
        ListSessionLocatorsError::Unavailable { .. } => {
            Ok(DurableSessionListIncompleteReason::SourceUnavailable)
        }
        ListSessionLocatorsError::Corrupt { .. } => {
            Ok(DurableSessionListIncompleteReason::ClassificationFailed)
        }
    }
}

#[cfg(test)]
#[path = "durable_session_query_tests.rs"]
mod tests;
