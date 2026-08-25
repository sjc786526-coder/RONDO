use crate::JsonSchema;
use crate::TS;
use serde::Deserialize;
use serde::Serialize;

/// Parameters for discovering canonical durable Sessions.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, Default, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionListParams {
    /// Opaque pagination cursor returned by a previous call for the same source.
    #[ts(optional = nullable)]
    pub cursor: Option<String>,
    /// Optional page size; the server applies a bounded default and maximum.
    #[ts(optional = nullable)]
    pub limit: Option<u32>,
    /// Selects the archived source when true and the active source when false.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub archived: bool,
}

/// One bounded page of canonical durable Sessions.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionListResponse {
    pub data: Vec<DurableSessionView>,
    pub next_cursor: Option<String>,
    /// Whether discovery completed against the selected source for this request.
    /// This is independent of whether `next_cursor` offers another complete page.
    pub complete: bool,
    pub incomplete_reason: Option<DurableSessionListIncompleteReason>,
}

/// Why a list page cannot claim a complete read of its selected source.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionListIncompleteReason {
    SourceUnavailable,
    SourceUnsupported,
    SourceChanged,
    BudgetExhausted,
    RecordUnreadable,
    RecordIncompatible,
    ClassificationFailed,
    Unknown,
}

/// Parameters for reading one canonical durable Session.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, Hash, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionReadParams {
    /// Canonical Session identity to cross-check against the durable marker.
    pub session_id: String,
    /// Canonical Root identity used only to locate the durable record. The
    /// server must still cross-check it against the marker and Session identity.
    pub root_thread_id: String,
}

/// Response for reading one canonical durable Session.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionReadResponse {
    pub session: DurableSessionView,
}

/// Read-only projection of one canonical durable Session.
///
/// Durable identity, storage placement, domain lifecycle, server-local runtime
/// residency, operation availability, and read completeness remain independent
/// axes. A caller must not infer one axis from another.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionView {
    pub identity: DurableSessionIdentity,
    pub storage_status: DurableSessionStorageStatus,
    pub domain_lifecycle: DurableSessionDomainLifecycle,
    pub residency: DurableSessionResidency,
    pub operation_availability: DurableSessionOperations,
    pub provenance: DurableSessionProvenance,
    pub read_status: DurableSessionReadStatus,
    /// Present only when one complete committed Team snapshot was projected.
    pub team: Option<DurableSessionTeamProjection>,
}

/// Canonical durable Session identity and its Root lineage identity.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionIdentity {
    pub session_id: String,
    /// `None` means that a canonical Root identity could not be established.
    pub root_thread_id: Option<String>,
}

/// Persistent source selected for this Session record.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionStorageStatus {
    Active,
    Archived,
    /// The selected durable source could not prove active or archived status.
    Unknown,
}

/// Domain lifecycle, independent of storage placement and runtime residency.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionDomainLifecycle {
    Open,
    Closing,
    Closed,
    Failed,
    Unknown,
}

/// Runtime residency observed only by the app-server answering this query.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionResidency {
    ObservedOwnerHere,
    OwnerUnavailableHere,
    NotObservedHere,
    Unknown,
}

/// Availability of the Session operations that a query may present.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionOperations {
    pub resume: DurableSessionOperation,
    pub close: DurableSessionOperation,
    pub archive: DurableSessionOperation,
    pub unarchive: DurableSessionOperation,
    pub delete: DurableSessionOperation,
}

/// One operation's availability and the fact source supporting it.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionOperation {
    pub availability: DurableSessionOperationAvailability,
    pub provenance: DurableSessionFactProvenance,
}

/// Whether an operation is available from the currently proven facts.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(tag = "status", rename_all = "camelCase")]
#[ts(tag = "status")]
#[ts(export_to = "v2/")]
pub enum DurableSessionOperationAvailability {
    Available,
    Unknown {
        reason: DurableSessionOperationAvailabilityReason,
    },
    Unavailable {
        reason: DurableSessionOperationAvailabilityReason,
    },
}

/// Why an operation is unknown or unavailable in this projection.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionOperationAvailabilityReason {
    ReadIncomplete,
    IdentityUnavailable,
    StorageUnavailable,
    LifecycleUnknown,
    ResidencyUnknown,
    OwnerUnavailableHere,
    NotObservedHere,
    AlreadyArchived,
    NotArchived,
    Closing,
    Closed,
    Failed,
    ChildSession,
    Unsupported,
}

/// Provenance for each independent Session fact axis.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionProvenance {
    pub identity: DurableSessionFactProvenance,
    pub storage_status: DurableSessionFactProvenance,
    pub domain_lifecycle: DurableSessionFactProvenance,
    pub residency: DurableSessionFactProvenance,
    pub team: DurableSessionFactProvenance,
}

/// Canonical or observation source for one projected fact axis.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionFactProvenance {
    SessionMeta,
    ThreadStore,
    CommittedTeamSnapshot,
    ServerRuntimeObservation,
    DerivedPolicy,
    Unavailable,
}

/// Completeness of the durable read used to build this projection.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(tag = "status", rename_all = "camelCase")]
#[ts(tag = "status")]
#[ts(export_to = "v2/")]
pub enum DurableSessionReadStatus {
    Available,
    Incomplete { issue: DurableSessionReadIssue },
    Unavailable { issue: DurableSessionReadIssue },
    Unsupported { issue: DurableSessionReadIssue },
}

/// Typed issue that limits or prevents a durable Session read.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionReadIssue {
    SessionNotFound,
    SourceUnavailable,
    SourceUnsupported,
    SourceChanged,
    BudgetExhausted,
    IdentityUnavailable,
    /// The supplied Root locator resolves to a child rather than a canonical Root.
    NotCanonicalRoot,
    /// The supplied Session and Root identities do not describe the same lineage.
    SessionRootIdentityMismatch,
    SessionMetaUnreadable,
    SessionMetaIncompatible,
    DurableMarkerMissing,
    DurableMarkerIncompatible,
    DurableMarkerIdentityMismatch,
    TeamSnapshotMissing,
    TeamSnapshotCorrupt,
    TeamSnapshotIncompatible,
    TeamSnapshotValidationFailed,
    LegacySession,
    DurableSessionsDisabled,
    Unknown,
}

/// Bounded projection of one complete committed Team snapshot.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionTeamProjection {
    pub team_instance_id: String,
    /// Canonical durable commit generation for this exact snapshot.
    #[ts(type = "number")]
    pub commit_generation: u64,
    /// SHA-256 of the complete validated snapshot payload, encoded as
    /// `sha256:` followed by 64 lowercase hexadecimal digits. This includes
    /// state omitted from the bounded projection.
    pub commit_fingerprint: String,
    /// Team domain revision stored in this exact snapshot.
    #[ts(type = "number")]
    pub revision: u64,
    pub viewer: DurableSessionTeamViewer,
    pub participants: Vec<DurableSessionTeamParticipantProjection>,
    pub omitted_participants: u32,
    pub events: Vec<DurableSessionTeamEventProjection>,
    pub omitted_events: u32,
}

/// Session member through whose lineage the Team projection is viewed.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionTeamViewer {
    pub thread_id: String,
    pub role: DurableSessionTeamRole,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionTeamRole {
    Root,
    Member,
}

/// One participant included in the bounded committed Team projection.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionTeamParticipantProjection {
    pub thread_id: String,
    pub role: DurableSessionTeamRole,
    pub label: String,
}

/// One bounded event from the committed Team snapshot.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionTeamEventProjection {
    pub event_id: String,
    pub title: String,
    pub versions: Vec<DurableSessionTeamVersionProjection>,
    pub omitted_versions: u32,
}

/// One committed Team version within an event projection.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionTeamVersionProjection {
    pub version_id: String,
    pub author_thread_id: String,
    pub author_label: String,
    pub summary: String,
    pub producer_state: DurableSessionTeamProducerState,
    pub root_state: DurableSessionTeamRootState,
    pub retired: bool,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionTeamProducerState {
    Open,
    Closed,
}

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionTeamRootState {
    Pending,
    Tracking,
    Resolved,
}

#[cfg(test)]
#[path = "durable_session_query_tests.rs"]
mod tests;
