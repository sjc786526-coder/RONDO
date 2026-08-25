//! Experimental Session discovery and control request handling.
//!
//! Reads are deliberately side-effect free: list is forced through the state-DB-only path and
//! single reads never request history. Live Team state is reached only through the narrow core
//! façade on the currently loaded root; this module never receives a Team writer or handle.

use super::*;
use codex_app_server_protocol::ExperimentalSessionDomainLifecycle;
use codex_app_server_protocol::ExperimentalSessionFactProvenance;
use codex_app_server_protocol::ExperimentalSessionIdentity;
use codex_app_server_protocol::ExperimentalSessionListParams;
use codex_app_server_protocol::ExperimentalSessionListResponse;
use codex_app_server_protocol::ExperimentalSessionOperation;
use codex_app_server_protocol::ExperimentalSessionOperationAvailability;
use codex_app_server_protocol::ExperimentalSessionOperationUnavailableReason;
use codex_app_server_protocol::ExperimentalSessionOperations;
use codex_app_server_protocol::ExperimentalSessionProvenance;
use codex_app_server_protocol::ExperimentalSessionReadParams;
use codex_app_server_protocol::ExperimentalSessionReadResponse;
use codex_app_server_protocol::ExperimentalSessionResidency;
use codex_app_server_protocol::ExperimentalSessionTeamEventProjection;
use codex_app_server_protocol::ExperimentalSessionTeamProducerState;
use codex_app_server_protocol::ExperimentalSessionTeamProjection;
use codex_app_server_protocol::ExperimentalSessionTeamRootState;
use codex_app_server_protocol::ExperimentalSessionTeamVersionProjection;
use codex_app_server_protocol::ExperimentalSessionTeamViewerRole;
use codex_app_server_protocol::ExperimentalSessionUpdateTeamLifecycleParams;
use codex_app_server_protocol::ExperimentalSessionUpdateTeamLifecycleResponse;
use codex_app_server_protocol::ExperimentalSessionView;
use codex_core::CodexThread;
use codex_core::ExperimentalSessionControlError as CoreControlError;
use codex_core::ExperimentalSessionControlMutationOutcome as CoreMutationOutcome;
use codex_core::ExperimentalSessionControlProducerState as CoreProducerState;
use codex_core::ExperimentalSessionControlRootState as CoreRootState;
use codex_core::ExperimentalSessionControlSetRootStateParams as CoreSetRootStateParams;
use codex_core::ExperimentalSessionControlTeamProjection as CoreTeamProjection;
use codex_core::ExperimentalSessionControlVersion as CoreVersion;
use codex_thread_store::ReadThreadParams as StoreReadThreadParams;
use codex_thread_store::StoredThread;
use codex_thread_store::ThreadStoreError;

const SESSION_LIST_DEFAULT_LIMIT: usize = 25;
const SESSION_LIST_MAX_LIMIT: usize = 100;
const SESSION_LIST_MAX_SCANNED_THREADS: usize = 400;
const SESSION_LIST_MAX_SOURCE_PAGES: usize = 16;

impl ThreadRequestProcessor {
    pub(crate) async fn experimental_session_list(
        &self,
        params: ExperimentalSessionListParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_experimental_session_control_enabled()?;

        let Some(state_db) = self.state_db.as_ref() else {
            return Ok(Some(
                ExperimentalSessionListResponse {
                    data: Vec::new(),
                    next_cursor: None,
                    provenance: ExperimentalSessionFactProvenance::Unavailable,
                    complete: false,
                }
                .into(),
            ));
        };
        let page_size = params
            .limit
            .map(|limit| limit as usize)
            .unwrap_or(SESSION_LIST_DEFAULT_LIMIT)
            .clamp(1, SESSION_LIST_MAX_LIMIT);
        let mut anchor = params
            .cursor
            .as_deref()
            .map(parse_session_list_cursor)
            .transpose()?;
        let mut roots = Vec::with_capacity(page_size);
        let mut scanned = 0usize;
        let mut source_pages = 0usize;
        let mut classification_incomplete = false;
        let mut next_anchor = None;

        while roots.len() < page_size
            && scanned < SESSION_LIST_MAX_SCANNED_THREADS
            && source_pages < SESSION_LIST_MAX_SOURCE_PAGES
        {
            source_pages = source_pages.saturating_add(1);
            let query_size = (page_size - roots.len())
                .min(SESSION_LIST_MAX_SCANNED_THREADS - scanned)
                .max(1);
            let page = match state_db
                .list_threads(
                    query_size,
                    codex_state::ThreadFilterOptions {
                        archived_only: false,
                        allowed_sources: &[],
                        model_providers: None,
                        cwd_filters: None,
                        section: None,
                        anchor: anchor.as_ref(),
                        // RecencyAt is the existing global-list key with a thread-id
                        // tie-breaker, so equal-millisecond rows remain reachable by cursor.
                        sort_key: codex_state::SortKey::RecencyAt,
                        sort_direction: codex_state::SortDirection::Desc,
                        search_term: None,
                    },
                )
                .await
            {
                Ok(page) => page,
                Err(error) => {
                    tracing::warn!(%error, "experimental Session discovery state DB query failed");
                    return Ok(Some(
                        ExperimentalSessionListResponse {
                            data: Vec::new(),
                            next_cursor: None,
                            provenance: ExperimentalSessionFactProvenance::Unavailable,
                            complete: false,
                        }
                        .into(),
                    ));
                }
            };
            scanned = scanned.saturating_add(page.num_scanned_rows.max(page.items.len()));
            next_anchor = page.next_anchor;

            for metadata in page.items {
                match state_metadata_parent_thread_id(&metadata) {
                    Ok(None) => roots.push((
                        metadata.id,
                        SessionStoredFacts {
                            parent_thread_id: None,
                            archived: metadata.archived_at.is_some(),
                        },
                    )),
                    Ok(Some(_)) => {}
                    Err(error) => {
                        classification_incomplete = true;
                        tracing::warn!(
                            thread_id = %metadata.id,
                            %error,
                            "experimental Session discovery could not classify persisted thread identity"
                        );
                    }
                }
            }

            if roots.len() >= page_size || next_anchor.is_none() {
                break;
            }
            anchor = next_anchor.clone();
        }

        let source_exhausted = next_anchor.is_none();
        let scan_budget_exhausted = scanned >= SESSION_LIST_MAX_SCANNED_THREADS
            && roots.len() < page_size
            && !source_exhausted;
        let page_budget_exhausted = source_pages >= SESSION_LIST_MAX_SOURCE_PAGES
            && roots.len() < page_size
            && !source_exhausted;
        let complete =
            !classification_incomplete && !scan_budget_exhausted && !page_budget_exhausted;
        let next_cursor = next_anchor.as_ref().map(session_list_cursor);

        let mut data = Vec::with_capacity(roots.len());
        for (thread_id, stored_facts) in roots {
            data.push(
                self.experimental_session_view(
                    thread_id,
                    Some(stored_facts),
                    /*prototype_lifecycle*/ None,
                    ExperimentalSessionFactProvenance::StateDbPrototype,
                )
                .await,
            );
        }

        Ok(Some(
            ExperimentalSessionListResponse {
                data,
                next_cursor,
                provenance: ExperimentalSessionFactProvenance::StateDbPrototype,
                complete,
            }
            .into(),
        ))
    }

    pub(crate) async fn experimental_session_read(
        &self,
        params: ExperimentalSessionReadParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_experimental_session_control_enabled()?;
        let session_id = parse_thread_id(&params.session_id)?;
        let stored = match self
            .thread_store
            .read_thread(StoreReadThreadParams {
                thread_id: session_id,
                include_archived: true,
                include_history: false,
            })
            .await
        {
            Ok(stored) => Some(stored),
            Err(ThreadStoreError::ThreadNotFound { .. }) => None,
            Err(error) => {
                tracing::warn!(%session_id, %error, "experimental Session metadata read unavailable");
                None
            }
        };
        let prototype_lifecycle = params.prototype_facts.map(|facts| facts.domain_lifecycle);
        let stored_facts = stored.as_ref().map(SessionStoredFacts::from);
        let session = self
            .experimental_session_view(
                session_id,
                stored_facts,
                prototype_lifecycle,
                ExperimentalSessionFactProvenance::ThreadStore,
            )
            .await;
        Ok(Some(ExperimentalSessionReadResponse { session }.into()))
    }

    pub(crate) async fn experimental_session_update_team_lifecycle(
        &self,
        params: ExperimentalSessionUpdateTeamLifecycleParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        self.ensure_experimental_session_control_enabled()?;
        let root_thread_id = parse_thread_id(&params.root_thread_id)?;
        let thread = self
            .thread_manager
            .get_thread(root_thread_id)
            .await
            .map_err(|_| {
                invalid_request(format!(
                    "loaded Session owner is unavailable: {root_thread_id}"
                ))
            })?;
        let configured = thread.session_configured();
        if configured.parent_thread_id.is_some()
            || configured.thread_id != root_thread_id
            || ThreadId::from(configured.session_id) != root_thread_id
        {
            return Err(invalid_request(format!(
                "thread {root_thread_id} is not the loaded Session owner"
            )));
        }

        let outcome = thread
            .experimental_session_control_set_root_state(CoreSetRootStateParams {
                version_id: params.version_id,
                expected_producer_state: core_producer_state(params.expected_producer_state),
                expected_root_state: core_root_state(params.expected_root_state),
                next_root_state: core_root_state(params.next_root_state),
            })
            .await
            .map_err(core_control_error)?;
        Ok(Some(update_response(outcome).into()))
    }

    fn ensure_experimental_session_control_enabled(&self) -> Result<(), JSONRPCErrorError> {
        if self
            .config
            .features
            .enabled(Feature::ExperimentalSessionControl)
        {
            Ok(())
        } else {
            Err(invalid_request(
                "experimental Session control is disabled; enable features.experimental_session_control and restart Codex",
            ))
        }
    }

    async fn experimental_session_view(
        &self,
        query_id: ThreadId,
        stored: Option<SessionStoredFacts>,
        prototype_lifecycle: Option<ExperimentalSessionDomainLifecycle>,
        stored_provenance: ExperimentalSessionFactProvenance,
    ) -> ExperimentalSessionView {
        let loaded = self.loaded_session_context(query_id).await;
        let is_archived = stored.as_ref().is_some_and(|thread| thread.archived);
        let stored_is_root = stored
            .as_ref()
            .is_some_and(|thread| thread.parent_thread_id.is_none());

        let mut identity = ExperimentalSessionIdentity {
            session_id: query_id.to_string(),
            root_thread_id: stored_is_root.then(|| query_id.to_string()),
        };
        let mut identity_provenance = if stored_is_root {
            stored_provenance
        } else {
            ExperimentalSessionFactProvenance::Unavailable
        };
        let mut team = None;
        let mut team_provenance = ExperimentalSessionFactProvenance::Unavailable;

        let mut residency = if is_archived {
            ExperimentalSessionResidency::UnloadedNotResumable
        } else if stored.is_some() {
            ExperimentalSessionResidency::UnloadedResumable
        } else {
            ExperimentalSessionResidency::Unknown
        };
        let mut residency_provenance = if stored.is_some() {
            stored_provenance
        } else {
            ExperimentalSessionFactProvenance::Unavailable
        };

        let mut update_unavailable = if is_archived {
            ExperimentalSessionOperationUnavailableReason::Archived
        } else if stored_is_root {
            ExperimentalSessionOperationUnavailableReason::OwnerUnavailable
        } else {
            ExperimentalSessionOperationUnavailableReason::IdentityUnavailable
        };

        match loaded {
            LoadedSessionContext::Owner(thread) => {
                identity.root_thread_id = Some(query_id.to_string());
                identity_provenance = ExperimentalSessionFactProvenance::LiveRuntime;
                residency = ExperimentalSessionResidency::LoadedOwner;
                residency_provenance = ExperimentalSessionFactProvenance::LiveRuntime;
                match thread.experimental_session_control_team_projection().await {
                    Ok(projection) => {
                        team = Some(team_projection(projection));
                        team_provenance = ExperimentalSessionFactProvenance::LiveOwner;
                    }
                    Err(error) => {
                        update_unavailable = control_unavailable_reason(&error);
                        if matches!(error, CoreControlError::OwnerUnavailable { .. }) {
                            residency = ExperimentalSessionResidency::OwnerUnavailable;
                        }
                    }
                }
            }
            LoadedSessionContext::NonOwner { root_thread_id } => {
                identity.session_id = root_thread_id.to_string();
                identity.root_thread_id = Some(root_thread_id.to_string());
                identity_provenance = ExperimentalSessionFactProvenance::LiveRuntime;
                residency = ExperimentalSessionResidency::LoadedNonOwner;
                residency_provenance = ExperimentalSessionFactProvenance::LiveRuntime;
                update_unavailable = ExperimentalSessionOperationUnavailableReason::NotOwner;
            }
            LoadedSessionContext::ChildOnly { root_thread_id } => {
                identity.session_id = root_thread_id.to_string();
                identity.root_thread_id = Some(root_thread_id.to_string());
                identity_provenance = ExperimentalSessionFactProvenance::LiveRuntime;
                residency = ExperimentalSessionResidency::OwnerUnavailable;
                residency_provenance = ExperimentalSessionFactProvenance::LiveRuntime;
                update_unavailable = ExperimentalSessionOperationUnavailableReason::ChildOnly;
            }
            LoadedSessionContext::None => {}
        }

        let (domain_lifecycle, lifecycle_provenance) = if is_archived {
            (
                ExperimentalSessionDomainLifecycle::Archived,
                stored_provenance,
            )
        } else if let Some(prototype) = prototype_lifecycle {
            (prototype, ExperimentalSessionFactProvenance::PrototypeInput)
        } else {
            (
                ExperimentalSessionDomainLifecycle::Unknown,
                ExperimentalSessionFactProvenance::Unavailable,
            )
        };

        let update_team_lifecycle = if is_archived {
            operation(
                unavailable(ExperimentalSessionOperationUnavailableReason::Archived),
                stored_provenance,
            )
        } else if team.is_some() && matches!(residency, ExperimentalSessionResidency::LoadedOwner) {
            operation(
                ExperimentalSessionOperationAvailability::Available,
                ExperimentalSessionFactProvenance::LiveOwner,
            )
        } else {
            let provenance = if matches!(
                residency,
                ExperimentalSessionResidency::LoadedOwner
                    | ExperimentalSessionResidency::LoadedNonOwner
                    | ExperimentalSessionResidency::OwnerUnavailable
            ) {
                ExperimentalSessionFactProvenance::LiveRuntime
            } else if stored.is_some() {
                stored_provenance
            } else {
                ExperimentalSessionFactProvenance::Unavailable
            };
            operation(unavailable(update_unavailable), provenance)
        };
        let unarchive = if is_archived && stored_is_root {
            operation(
                ExperimentalSessionOperationAvailability::Available,
                stored_provenance,
            )
        } else if is_archived {
            let reason = match residency {
                ExperimentalSessionResidency::LoadedNonOwner => {
                    ExperimentalSessionOperationUnavailableReason::NotOwner
                }
                ExperimentalSessionResidency::OwnerUnavailable => {
                    ExperimentalSessionOperationUnavailableReason::ChildOnly
                }
                _ => ExperimentalSessionOperationUnavailableReason::IdentityUnavailable,
            };
            operation(unavailable(reason), stored_provenance)
        } else if stored.is_some() {
            operation(
                unavailable(ExperimentalSessionOperationUnavailableReason::NotArchived),
                stored_provenance,
            )
        } else {
            operation(
                unavailable(ExperimentalSessionOperationUnavailableReason::Unknown),
                ExperimentalSessionFactProvenance::Unavailable,
            )
        };

        ExperimentalSessionView {
            identity,
            domain_lifecycle,
            residency,
            operation_availability: ExperimentalSessionOperations {
                update_team_lifecycle,
                archive: operation(
                    unavailable(ExperimentalSessionOperationUnavailableReason::Unsupported),
                    ExperimentalSessionFactProvenance::Unavailable,
                ),
                unarchive,
            },
            provenance: ExperimentalSessionProvenance {
                identity: identity_provenance,
                domain_lifecycle: lifecycle_provenance,
                residency: residency_provenance,
                team: team_provenance,
            },
            team,
        }
    }

    async fn loaded_session_context(&self, query_id: ThreadId) -> LoadedSessionContext {
        if let Ok(thread) = self.thread_manager.get_thread(query_id).await
            && thread.is_running()
        {
            let configured = thread.session_configured();
            let root_thread_id = ThreadId::from(configured.session_id);
            if configured.parent_thread_id.is_none()
                && configured.thread_id == query_id
                && root_thread_id == query_id
            {
                return LoadedSessionContext::Owner(thread);
            }
            if self.loaded_root_is_current(root_thread_id).await {
                return LoadedSessionContext::NonOwner { root_thread_id };
            }
            return LoadedSessionContext::ChildOnly { root_thread_id };
        }

        for loaded_id in self.thread_manager.list_thread_ids().await {
            let Ok(thread) = self.thread_manager.get_thread(loaded_id).await else {
                continue;
            };
            if !thread.is_running() {
                continue;
            }
            let configured = thread.session_configured();
            let root_thread_id = ThreadId::from(configured.session_id);
            if root_thread_id == query_id && configured.thread_id != root_thread_id {
                return LoadedSessionContext::ChildOnly { root_thread_id };
            }
        }
        LoadedSessionContext::None
    }

    async fn loaded_root_is_current(&self, root_thread_id: ThreadId) -> bool {
        let Ok(root) = self.thread_manager.get_thread(root_thread_id).await else {
            return false;
        };
        if !root.is_running() {
            return false;
        }
        let configured = root.session_configured();
        configured.parent_thread_id.is_none()
            && configured.thread_id == root_thread_id
            && ThreadId::from(configured.session_id) == root_thread_id
    }
}

#[derive(Clone, Copy)]
struct SessionStoredFacts {
    parent_thread_id: Option<ThreadId>,
    archived: bool,
}

impl From<&StoredThread> for SessionStoredFacts {
    fn from(stored: &StoredThread) -> Self {
        Self {
            parent_thread_id: stored.parent_thread_id,
            archived: stored.archived_at.is_some(),
        }
    }
}

enum LoadedSessionContext {
    Owner(Arc<CodexThread>),
    NonOwner { root_thread_id: ThreadId },
    ChildOnly { root_thread_id: ThreadId },
    None,
}

fn parse_thread_id(value: &str) -> Result<ThreadId, JSONRPCErrorError> {
    ThreadId::from_string(value)
        .map_err(|error| invalid_request(format!("invalid Session id: {error}")))
}

fn unavailable(
    reason: ExperimentalSessionOperationUnavailableReason,
) -> ExperimentalSessionOperationAvailability {
    ExperimentalSessionOperationAvailability::Unavailable { reason }
}

fn operation(
    availability: ExperimentalSessionOperationAvailability,
    provenance: ExperimentalSessionFactProvenance,
) -> ExperimentalSessionOperation {
    ExperimentalSessionOperation {
        availability,
        provenance,
    }
}

fn parse_session_list_cursor(value: &str) -> Result<codex_state::Anchor, JSONRPCErrorError> {
    let (timestamp, thread_id) = match value.rsplit_once('|') {
        Some((timestamp, thread_id)) => (
            timestamp,
            Some(
                ThreadId::from_string(thread_id)
                    .map_err(|error| invalid_request(format!("invalid Session cursor: {error}")))?,
            ),
        ),
        None => (value, None),
    };
    let ts = chrono::DateTime::parse_from_rfc3339(timestamp)
        .map_err(|error| invalid_request(format!("invalid Session cursor: {error}")))?
        .with_timezone(&chrono::Utc);
    Ok(codex_state::Anchor { ts, id: thread_id })
}

fn session_list_cursor(anchor: &codex_state::Anchor) -> String {
    let timestamp = anchor
        .ts
        .to_rfc3339_opts(chrono::SecondsFormat::Nanos, true);
    match anchor.id {
        Some(thread_id) => format!("{timestamp}|{thread_id}"),
        None => timestamp,
    }
}

fn state_metadata_parent_thread_id(
    metadata: &codex_state::ThreadMetadata,
) -> Result<Option<ThreadId>, serde_json::Error> {
    serde_json::from_str::<codex_protocol::protocol::SessionSource>(&metadata.source)
        .or_else(|_| serde_json::from_value(serde_json::Value::String(metadata.source.clone())))
        .map(|source| source.parent_thread_id())
}

fn control_unavailable_reason(
    error: &CoreControlError,
) -> ExperimentalSessionOperationUnavailableReason {
    match error {
        CoreControlError::NotRootOwner { .. } | CoreControlError::NotRootParticipant { .. } => {
            ExperimentalSessionOperationUnavailableReason::NotOwner
        }
        CoreControlError::OwnerUnavailable { .. } => {
            ExperimentalSessionOperationUnavailableReason::OwnerUnavailable
        }
        CoreControlError::OwnerIdentityUnavailable { .. } => {
            ExperimentalSessionOperationUnavailableReason::IdentityUnavailable
        }
        _ => ExperimentalSessionOperationUnavailableReason::TeamUnavailable,
    }
}

fn core_control_error(error: CoreControlError) -> JSONRPCErrorError {
    match error {
        CoreControlError::UnexpectedTeamError { message } => {
            internal_error(format!("canonical Team operation failed: {message}"))
        }
        error => invalid_request(error.to_string()),
    }
}

fn team_projection(value: CoreTeamProjection) -> ExperimentalSessionTeamProjection {
    let omitted_participants = value
        .omitted_participants
        .saturating_add(value.participants.len());
    ExperimentalSessionTeamProjection {
        team_instance_id: value.team_instance,
        revision: value.revision,
        viewer_thread_id: value.root_thread_id.to_string(),
        viewer_role: ExperimentalSessionTeamViewerRole::Root,
        events: value
            .events
            .into_iter()
            .map(|event| ExperimentalSessionTeamEventProjection {
                event_id: event.id,
                title: event.title,
                versions: event.versions.into_iter().map(team_version).collect(),
                omitted_versions: usize_to_u32(event.omitted_versions),
            })
            .collect(),
        omitted_participants: usize_to_u32(omitted_participants),
        omitted_events: usize_to_u32(value.omitted_events),
    }
}

fn team_version(value: CoreVersion) -> ExperimentalSessionTeamVersionProjection {
    ExperimentalSessionTeamVersionProjection {
        version_id: value.id,
        author_thread_id: value.author.to_string(),
        producer_state: api_producer_state(value.producer_state),
        root_state: api_root_state(value.root_state),
        retired: value.retired,
    }
}

fn update_response(outcome: CoreMutationOutcome) -> ExperimentalSessionUpdateTeamLifecycleResponse {
    ExperimentalSessionUpdateTeamLifecycleResponse {
        team_instance_id: outcome.projection.team_instance,
        revision: outcome.mutation_revision,
        changed: outcome.changed,
        version: team_version(outcome.updated),
    }
}

fn core_producer_state(value: ExperimentalSessionTeamProducerState) -> CoreProducerState {
    match value {
        ExperimentalSessionTeamProducerState::Open => CoreProducerState::Open,
        ExperimentalSessionTeamProducerState::Closed => CoreProducerState::Closed,
    }
}

fn core_root_state(value: ExperimentalSessionTeamRootState) -> CoreRootState {
    match value {
        ExperimentalSessionTeamRootState::Pending => CoreRootState::Pending,
        ExperimentalSessionTeamRootState::Tracking => CoreRootState::Tracking,
        ExperimentalSessionTeamRootState::Resolved => CoreRootState::Resolved,
    }
}

fn api_producer_state(value: CoreProducerState) -> ExperimentalSessionTeamProducerState {
    match value {
        CoreProducerState::Open => ExperimentalSessionTeamProducerState::Open,
        CoreProducerState::Closed => ExperimentalSessionTeamProducerState::Closed,
    }
}

fn api_root_state(value: CoreRootState) -> ExperimentalSessionTeamRootState {
    match value {
        CoreRootState::Pending => ExperimentalSessionTeamRootState::Pending,
        CoreRootState::Tracking => ExperimentalSessionTeamRootState::Tracking,
        CoreRootState::Resolved => ExperimentalSessionTeamRootState::Resolved,
    }
}

fn usize_to_u32(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}
