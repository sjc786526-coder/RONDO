use super::DurableSessionResidency;
use super::DurableSessionStorageStatus;
use super::DurableSessionTeamProducerState;
use super::DurableSessionTeamRootState;
use crate::JsonSchema;
use crate::TS;
use serde::Deserialize;
use serde::Serialize;

/// Parameters for one authoritative Durable Session control attempt.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionControlParams {
    pub session_id: String,
    pub root_thread_id: String,
    pub precondition: DurableSessionControlPrecondition,
    pub operation: DurableSessionControlOperation,
}

/// Query proof that the server must revalidate before applying a control operation.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionControlPrecondition {
    pub expected_storage_status: DurableSessionStorageStatus,
    pub expected_residency: DurableSessionResidency,
    pub team_instance_id: String,
    #[ts(type = "number")]
    pub team_revision: u64,
    #[ts(type = "number")]
    pub commit_generation: u64,
    pub commit_fingerprint: String,
}

/// Mutation requested from the current canonical Durable Session authority.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
#[ts(tag = "type")]
#[ts(export_to = "v2/")]
pub enum DurableSessionControlOperation {
    SetRootState {
        version_id: String,
        expected_producer_state: DurableSessionTeamProducerState,
        expected_root_state: DurableSessionTeamRootState,
        next_root_state: DurableSessionTeamRootState,
    },
    Close,
    Archive,
    Unarchive,
    Delete,
}

impl DurableSessionControlOperation {
    /// Returns the field-free operation identity used in an outcome.
    pub fn kind(&self) -> DurableSessionControlOperationKind {
        match self {
            Self::SetRootState { .. } => DurableSessionControlOperationKind::SetRootState,
            Self::Close => DurableSessionControlOperationKind::Close,
            Self::Archive => DurableSessionControlOperationKind::Archive,
            Self::Unarchive => DurableSessionControlOperationKind::Unarchive,
            Self::Delete => DurableSessionControlOperationKind::Delete,
        }
    }
}

/// Field-free operation identity used in outcomes after the request payload is consumed.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionControlOperationKind {
    SetRootState,
    Close,
    Archive,
    Unarchive,
    Delete,
}

/// Result of one Durable Session control attempt.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub struct DurableSessionControlResponse {
    pub outcome: DurableSessionControlOutcome,
}

/// Certainty-preserving outcome returned by the control boundary.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
#[ts(tag = "type")]
#[ts(export_to = "v2/")]
pub enum DurableSessionControlOutcome {
    Applied {
        effect: DurableSessionControlEffect,
    },
    Rejected {
        operation: DurableSessionControlOperationKind,
        reason: DurableSessionControlRejectionReason,
        message: String,
    },
    Partial {
        operation: DurableSessionControlOperationKind,
        completed_thread_ids: Vec<String>,
        message: String,
    },
    Unknown {
        operation: DurableSessionControlOperationKind,
        message: String,
    },
}

/// Confirmed domain effect of an applied control operation.
#[derive(Serialize, Deserialize, Debug, Clone, PartialEq, Eq, JsonSchema, TS)]
#[serde(
    tag = "type",
    rename_all = "camelCase",
    rename_all_fields = "camelCase"
)]
#[ts(tag = "type")]
#[ts(export_to = "v2/")]
pub enum DurableSessionControlEffect {
    RootStateUpdated {
        changed: bool,
        #[ts(type = "number")]
        mutation_revision: u64,
    },
    /// The loaded canonical Root owner completed the close barrier and was removed.
    /// This does not invent a whole-Session lifecycle fact.
    OwnerClosed,
    Archived {
        affected_thread_ids: Vec<String>,
    },
    Unarchived,
    Deleted {
        affected_thread_ids: Vec<String>,
    },
}

/// Typed, side-effect-free reason why a control attempt was rejected.
#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, JsonSchema, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export_to = "v2/")]
pub enum DurableSessionControlRejectionReason {
    StalePrecondition,
    WrongStorage,
    OwnerUnavailable,
    NotCurrentOwner,
    ActiveWriter,
    Conflict,
    NotFound,
    Unsupported,
    InvalidState,
}

#[cfg(test)]
#[path = "durable_session_control_tests.rs"]
mod tests;
