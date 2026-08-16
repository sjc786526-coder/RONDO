//! Submission and outcome types for team-state mutations.
//!
//! Every submission carries the revision the author's view was built from and a stable retry
//! identity, which together give the four behaviours the design contract requires: retries never
//! duplicate objects, appends on a stale view are labelled rather than rejected, lifecycle changes
//! whose precondition already moved are rejected with the current state, and a batch only ever
//! touches the targets it names.

use crate::ids::EventId;
use crate::ids::InstanceTag;
use crate::ids::TeamRevision;
use crate::ids::VersionId;
use crate::model::ProducerState;
use crate::model::RootState;
use serde::Serialize;
use std::fmt;

/// Context every mutation is submitted with. The actor is supplied by the harness from the
/// authoritative session identity, never by the caller's payload.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Submission {
    /// The view revision the author believes it acted on.
    pub based_on: TeamRevision,
    /// Stable identity for this logical submission; a repeat of the same value is a retry.
    pub request_id: String,
}

/// What to publish: a new team-level matter, or another entry under an existing one.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PublishTarget {
    NewEvent { title: String },
    ExistingEvent { event_id: EventId },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PublishRequest {
    pub target: PublishTarget,
    pub summary: String,
    pub handoff: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct PublishOutcome {
    pub event_id: EventId,
    pub version_id: VersionId,
    pub revision: TeamRevision,
    /// True when this submission's `based_on` was older than the event's last change. The entry
    /// is committed either way; the label travels with it.
    pub authored_on_stale_view: bool,
    /// True when this was a retry of an already-committed submission and no new object was made.
    pub deduplicated: bool,
}

/// The lifecycle change requested for one version.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LifecycleChange {
    /// Author-side close. Only the version's own author may do this.
    CloseProducer,
    /// Root-side attention update. Only the root may do this.
    SetRootState(RootState),
}

/// One target of a lifecycle batch, with the precondition the caller believes holds.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LifecycleTarget {
    pub version_id: VersionId,
    pub expected_producer_state: ProducerState,
    pub expected_root_state: RootState,
    pub change: LifecycleChange,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LifecycleRequest {
    /// Only these versions are touched. Concurrently added versions are never swept up.
    pub targets: Vec<LifecycleTarget>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct LifecycleSnapshot {
    pub version_id: VersionId,
    pub producer_state: ProducerState,
    pub root_state: RootState,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct LifecycleOutcome {
    pub revision: TeamRevision,
    pub updated: Vec<LifecycleSnapshot>,
}

/// Why a team operation was refused.
///
/// Every variant is a refusal, never a silent partial success: the store commits a mutation whole
/// or not at all.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "error", rename_all = "snake_case")]
pub enum TeamError {
    /// The caller's session is not a registered participant of this team instance. Team
    /// capabilities are refused rather than defaulted.
    UnknownParticipant,
    /// The reference belongs to a different team instance, so the team has been reset from the
    /// caller's point of view and the old reference must not resolve here.
    InstanceReset {
        referenced_instance: InstanceTag,
        current_instance: InstanceTag,
    },
    /// The reference is well-formed for this instance but names nothing.
    UnknownReference { reference: String },
    /// The reference is not a team reference at all.
    MalformedReference { reference: String },
    /// The caller may not make this change to this object.
    NotPermitted { reason: &'static str },
    /// A lifecycle precondition no longer holds. The caller gets the current state back instead of
    /// silently overwriting someone else's change.
    LifecycleConflict { current: LifecycleSnapshot },
    /// A closed version cannot be reopened in place; publish a new version instead.
    VersionClosed { version_id: VersionId },
    /// A required field was empty.
    InvalidRequest { reason: &'static str },
}

impl fmt::Display for TeamError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::UnknownParticipant => f.write_str(
                "this session is not a registered participant of the team; team tools are unavailable",
            ),
            Self::InstanceReset {
                referenced_instance,
                current_instance,
            } => write!(
                f,
                "team state was reset: reference belongs to instance {referenced_instance} but the current instance is {current_instance}; re-read the active team state instead of reusing old references"
            ),
            Self::UnknownReference { reference } => {
                write!(f, "no team object named {reference}")
            }
            Self::MalformedReference { reference } => {
                write!(f, "{reference} is not a valid team reference")
            }
            Self::NotPermitted { reason } => write!(f, "not permitted: {reason}"),
            Self::LifecycleConflict { current } => {
                let LifecycleSnapshot {
                    version_id,
                    producer_state,
                    root_state,
                } = current;
                write!(
                    f,
                    "lifecycle precondition for {version_id} no longer holds; it is now producer={producer_state} root={root_state}"
                )
            }
            Self::VersionClosed { version_id } => write!(
                f,
                "{version_id} is closed and cannot be reopened; append a new version instead"
            ),
            Self::InvalidRequest { reason } => write!(f, "invalid request: {reason}"),
        }
    }
}

impl std::error::Error for TeamError {}
