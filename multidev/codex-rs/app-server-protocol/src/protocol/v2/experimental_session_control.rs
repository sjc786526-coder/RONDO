use crate::JsonSchema;
use crate::TS;
use serde::Deserialize;
use serde::Serialize;

/// Experimental Session discovery parameters.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, Default, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionListParams {
    /// Opaque pagination cursor returned by a previous call.
    #[ts(optional = nullable)]
    pub cursor: Option<String>,
    /// Optional page size; the server selects a bounded default when omitted.
    #[ts(optional = nullable)]
    pub limit: Option<u32>,
}

/// Experimental Session discovery response.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionListResponse {
    pub data: Vec<ExperimentalSessionView>,
    /// Opaque cursor to continue after the last returned Session.
    pub next_cursor: Option<String>,
    /// Source used for discovery. `unavailable` must accompany an incomplete
    /// result rather than presenting an empty page as an authoritative empty set.
    pub provenance: ExperimentalSessionFactProvenance,
    /// Whether discovery completed against the stated source for this request.
    /// This is independent of pagination; `nextCursor` still indicates whether
    /// another complete page exists.
    pub complete: bool,
}

/// Experimental Session read parameters.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionReadParams {
    /// Session identity used as the lookup key. The response separately reports
    /// whether a canonical Root identity could be established.
    pub session_id: String,
    /// Explicit prototype-only facts used to exercise lifecycle states that do
    /// not yet have an S1 durable read model.
    ///
    /// A server that uses any of these facts must report `prototypeInput` for
    /// the corresponding response provenance. These values are never durable
    /// authority and must not be persisted or used to activate a Session.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[ts(optional = nullable)]
    pub prototype_facts: Option<ExperimentalSessionPrototypeFacts>,
}

/// Prototype-only inputs for states not yet readable from a durable authority.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionPrototypeFacts {
    pub domain_lifecycle: ExperimentalSessionDomainLifecycle,
}

/// Experimental Session read response.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionReadResponse {
    pub session: ExperimentalSessionView,
}

/// One read-only Session projection.
///
/// Domain lifecycle, runtime residency, operation availability, and source
/// provenance are deliberately independent. Client freshness and mutation
/// result certainty belong to the client synchronization layer and are not
/// asserted by this server DTO.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionView {
    pub identity: ExperimentalSessionIdentity,
    pub domain_lifecycle: ExperimentalSessionDomainLifecycle,
    pub residency: ExperimentalSessionResidency,
    pub operation_availability: ExperimentalSessionOperations,
    pub provenance: ExperimentalSessionProvenance,
    /// Present only when a bounded Team projection is available.
    pub team: Option<ExperimentalSessionTeamProjection>,
}

/// Session identity and the canonical Root identity when it can be proven.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionIdentity {
    pub session_id: String,
    /// Canonical loaded Root thread when known. `None` means unavailable, not
    /// that the queried Session is itself the Root.
    pub root_thread_id: Option<String>,
}

/// Domain lifecycle projected for the selected Session.
///
/// This does not describe whether an owner runtime is loaded or whether the
/// client view is synchronized.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ExperimentalSessionDomainLifecycle {
    Open,
    Closing,
    Closed,
    Archived,
    Failed,
    Partial,
    Unknown,
}

/// Current owner/runtime residency, independent of domain lifecycle.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ExperimentalSessionResidency {
    LoadedOwner,
    LoadedNonOwner,
    UnloadedResumable,
    UnloadedNotResumable,
    OwnerUnavailable,
    Unknown,
}

/// Availability of the representative C0 operations.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionOperations {
    pub update_team_lifecycle: ExperimentalSessionOperation,
    pub archive: ExperimentalSessionOperation,
    pub unarchive: ExperimentalSessionOperation,
}

/// One operation's current availability and the source that supports that claim.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionOperation {
    pub availability: ExperimentalSessionOperationAvailability,
    pub provenance: ExperimentalSessionFactProvenance,
}

/// Whether one operation can be submitted through the current authority.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(tag = "type", rename_all = "camelCase")]
#[ts(tag = "type")]
#[ts(export_to = "v2/")]
pub enum ExperimentalSessionOperationAvailability {
    Available,
    Unavailable {
        reason: ExperimentalSessionOperationUnavailableReason,
    },
}

/// Why an operation is unavailable in the current projection.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ExperimentalSessionOperationUnavailableReason {
    Archived,
    NotArchived,
    NotLoaded,
    NotOwner,
    ChildOnly,
    OwnerUnavailable,
    IdentityUnavailable,
    TeamUnavailable,
    Unsupported,
    Unknown,
}

/// Per-axis sources used to build a Session projection.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionProvenance {
    pub identity: ExperimentalSessionFactProvenance,
    pub domain_lifecycle: ExperimentalSessionFactProvenance,
    pub residency: ExperimentalSessionFactProvenance,
    pub team: ExperimentalSessionFactProvenance,
}

/// Source and authority boundary for one projected fact axis.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ExperimentalSessionFactProvenance {
    /// Current canonical Team state delegated by the loaded owner runtime.
    LiveOwner,
    /// Loaded Session runtime facts that do not themselves prove Root ownership.
    LiveRuntime,
    /// Existing authoritative ThreadStore lifecycle or identity metadata.
    ThreadStore,
    /// Query-only metadata from the state DB; not the S1 Team read model.
    StateDbPrototype,
    /// Query-only metadata reconstructed from rollout storage.
    RolloutPrototype,
    /// Caller-supplied prototype input; never durable or canonical authority.
    PrototypeInput,
    Unavailable,
}

/// Bounded projection of the canonical in-process Team owned by a loaded Root.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionTeamProjection {
    /// Opaque Team instance identity, using the domain's normal display form.
    pub team_instance_id: String,
    /// Canonical Team revision observed by this read.
    #[ts(type = "number")]
    pub revision: u64,
    pub viewer_thread_id: String,
    pub viewer_role: ExperimentalSessionTeamViewerRole,
    /// Registered participants not included in this bounded projection. C0 does
    /// not expose participant records, so this reports their omitted count.
    pub omitted_participants: u32,
    pub events: Vec<ExperimentalSessionTeamEventProjection>,
    /// Events excluded by the projection bound.
    pub omitted_events: u32,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ExperimentalSessionTeamViewerRole {
    Root,
    Member,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionTeamEventProjection {
    pub event_id: String,
    pub title: String,
    pub versions: Vec<ExperimentalSessionTeamVersionProjection>,
    /// Versions of this event excluded by the projection bound.
    pub omitted_versions: u32,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionTeamVersionProjection {
    pub version_id: String,
    pub author_thread_id: String,
    pub producer_state: ExperimentalSessionTeamProducerState,
    pub root_state: ExperimentalSessionTeamRootState,
    pub retired: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ExperimentalSessionTeamProducerState {
    Open,
    Closed,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum ExperimentalSessionTeamRootState {
    Pending,
    Tracking,
    Resolved,
}

/// Root-owner command for one canonical Team lifecycle transition.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionUpdateTeamLifecycleParams {
    /// Loaded Root thread that must own the Team instance being mutated.
    pub root_thread_id: String,
    /// Opaque canonical Team version identity.
    pub version_id: String,
    pub expected_producer_state: ExperimentalSessionTeamProducerState,
    pub expected_root_state: ExperimentalSessionTeamRootState,
    pub next_root_state: ExperimentalSessionTeamRootState,
}

#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct ExperimentalSessionUpdateTeamLifecycleResponse {
    pub team_instance_id: String,
    #[ts(type = "number")]
    pub revision: u64,
    pub changed: bool,
    pub version: ExperimentalSessionTeamVersionProjection,
}

#[cfg(test)]
#[path = "experimental_session_control_tests.rs"]
mod tests;
