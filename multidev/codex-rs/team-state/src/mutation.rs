//! Submission and outcome types for team-state mutations.
//!
//! Every submission carries the revision the author's view was built from and a stable retry
//! identity, which together give the four behaviours the design contract requires: retries never
//! duplicate objects, appends on a stale view are labelled rather than rejected, lifecycle changes
//! whose precondition already moved are rejected with the current state, and a batch only ever
//! touches the targets it names.

use crate::availability::AvailabilityEpoch;
use crate::availability::ProducerAvailability;
use crate::ids::EventId;
use crate::ids::FactId;
use crate::ids::InstanceTag;
use crate::ids::RouteId;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::ids::VersionId;
use crate::model::DeliveryState;
use crate::model::ProducerState;
use crate::model::RootState;
use crate::model::RouteDuty;
use codex_protocol::ThreadId;
use serde::Deserialize;
use serde::Serialize;
use std::fmt;

/// Context every mutation is submitted with. The actor is supplied by the harness from the
/// authoritative session identity, never by the caller's payload.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Submission {
    /// The view revision the author believes it acted on.
    pub based_on: TeamRevision,
    /// Stable identity for this logical submission; a repeat of the same value is a retry.
    pub request_id: String,
}

/// What to publish: a new team-level matter, or another entry under an existing one.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub enum PublishTarget {
    NewEvent { title: String },
    ExistingEvent { event_id: EventId },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublishRequest {
    pub target: PublishTarget,
    pub summary: String,
    pub handoff: Option<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PublishOutcome {
    pub event_id: EventId,
    pub version_id: VersionId,
    pub revision: TeamRevision,
    /// The evidence this publish attached, chosen by the harness rather than by the author. Because
    /// it is part of the committed outcome, a retry answered from that outcome reports the same
    /// references, whatever has been observed since.
    pub evidence_refs: Vec<FactId>,
    /// True when this submission's `based_on` was older than the event's last change. The entry
    /// is committed either way; the label travels with it.
    pub authored_on_stale_view: bool,
    /// True when this was a retry of an already-committed submission and no new object was made.
    pub deduplicated: bool,
}

/// The lifecycle change requested for one version.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub enum LifecycleChange {
    /// Author-side close. Only the version's own author may do this.
    CloseProducer,
    /// Root-side attention update. Only the root may do this.
    SetRootState(RootState),
}

/// One target of a lifecycle batch, with the precondition the caller believes holds.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LifecycleTarget {
    pub version_id: VersionId,
    pub expected_producer_state: ProducerState,
    pub expected_root_state: RootState,
    pub change: LifecycleChange,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LifecycleRequest {
    /// Only these versions are touched. Concurrently added versions are never swept up.
    pub targets: Vec<LifecycleTarget>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LifecycleSnapshot {
    pub version_id: VersionId,
    pub producer_state: ProducerState,
    pub root_state: RootState,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LifecycleOutcome {
    pub revision: TeamRevision,
    pub updated: Vec<LifecycleSnapshot>,
    /// False when every named target was already in the requested state. A stable no-op must not
    /// look like a canonical mutation.
    pub changed: bool,
}

/// What a route asks of its target.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub enum RouteIntent {
    /// Hand over work: create an assignment and ask the target to start or continue.
    Assign,
    /// Tell the target about the event without asking for anything. No assignment is created, so
    /// an informational notice can never be mistaken for work in progress, and the target is never
    /// pulled into a turn just to be told something.
    Notify,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RouteRequest {
    pub event_id: EventId,
    pub target: ThreadId,
    pub intent: RouteIntent,
    /// Compact hint for the target, clamped on write. The event's own content is never copied here.
    pub note: Option<String>,
}

/// Everything the harness needs to build and send this route's compact notice.
///
/// It deliberately carries locators and the root's hint only: the target reads the event itself
/// from the canonical state, so nothing here has to duplicate a chain that could then drift.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RouteDispatch {
    pub instance: TeamInstanceId,
    pub route_id: RouteId,
    pub event_id: EventId,
    pub target: ThreadId,
    pub duty: RouteDuty,
    pub note: Option<String>,
    pub delivery: DeliveryState,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RouteOutcome {
    pub dispatch: RouteDispatch,
    pub revision: TeamRevision,
    /// True when this call matched a grant that already existed and minted nothing new.
    pub deduplicated: bool,
}

/// The result of one attempt to deliver a route's notice.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub enum DeliveryResult {
    Delivered,
    Failed { reason: String },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DeliveryOutcome {
    pub route_id: RouteId,
    pub delivery: DeliveryState,
    pub revision: TeamRevision,
    /// False when the recorded state already said this, so a repeated report changes nothing.
    pub changed: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EndAssignmentOutcome {
    pub route_id: RouteId,
    pub event_id: EventId,
    pub duty: RouteDuty,
    pub delivery: DeliveryState,
    pub revision: TeamRevision,
}

/// Root retirement of one version whose author is confirmed truly unavailable.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RetireRequest {
    pub version_id: VersionId,
    pub expected_producer_state: ProducerState,
    pub expected_root_state: RootState,
    pub expected_availability: ProducerAvailability,
    pub expected_availability_epoch: AvailabilityEpoch,
    pub reason: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RetireOutcome {
    pub revision: TeamRevision,
    pub version_id: VersionId,
    pub retired_by: ThreadId,
    pub reason: String,
    pub availability: ProducerAvailability,
    pub availability_epoch: AvailabilityEpoch,
    pub deduplicated: bool,
}

/// Why a team operation was refused.
///
/// Every variant is a refusal, never a silent partial success: the store commits a mutation whole
/// or not at all.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "error", rename_all = "snake_case")]
pub enum TeamError {
    /// The domain mutation was valid but its durable commit did not establish success. The reason
    /// preserves conflict, unavailable and indeterminate distinctions from the storage boundary.
    Durability { reason: String },
    /// The whole-Team snapshot used by a control caller is no longer current. Unlike a
    /// target-local lifecycle conflict, this rejects when any committed Team mutation won after
    /// the caller's read.
    SnapshotConflict {
        current_instance: TeamInstanceId,
        current_revision: TeamRevision,
        current_commit_generation: u64,
    },
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
    /// The same retry identity was reused for different content. Treating it as a retry would
    /// silently drop the second piece of content, so it is refused instead.
    RetryIdentityReused,
    /// Root attention on this version is already finished and does not reopen in place.
    RootAttentionResolved { version_id: VersionId },
    /// One batch named the same version twice on the same lifecycle axis, which would make the
    /// outcome depend on ordering and could step around a terminal state.
    ConflictingTargets { version_id: VersionId },
    /// The route target is not a registered participant of this team instance. Distinct from
    /// [`TeamError::UnknownParticipant`], which is about the caller.
    UnknownTarget,
    /// The route is informational, so it never carried an assignment there could be an end to.
    NotAnAssignment { route_id: RouteId },
    /// The assignment has already reached its terminal state and does not end twice.
    AssignmentEnded { route_id: RouteId },
    /// The target is already working on this event under a different instruction. Answering with
    /// the existing assignment would drop the new instruction silently, and opening a second one
    /// would leave the target holding the same event for two reasons.
    AssignmentInProgress { route_id: RouteId },
    /// Root retirement of a version that has already been retired. The original operator and
    /// reason stand.
    VersionRetired { version_id: VersionId },
    /// The producer is not confirmed truly unavailable, so Root retirement is refused.
    ProducerNotUnavailable {
        availability: ProducerAvailability,
        availability_epoch: AvailabilityEpoch,
    },
    /// The availability snapshot the caller acted on is no longer current.
    AvailabilityConflict {
        availability: ProducerAvailability,
        availability_epoch: AvailabilityEpoch,
    },
    /// A dump page cursor belongs to a different revision, availability snapshot or observe layout.
    DumpCursorStale {
        current_revision: TeamRevision,
        current_epoch: AvailabilityEpoch,
        current_observe_generation: u64,
    },
}

impl fmt::Display for TeamError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Durability { reason } => write!(f, "Team durability refused the mutation: {reason}"),
            Self::SnapshotConflict {
                current_instance,
                current_revision,
                current_commit_generation,
            } => write!(
                f,
                "Team snapshot changed: current instance={current_instance} revision={current_revision} commit_generation={current_commit_generation}"
            ),
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
            Self::RetryIdentityReused => f.write_str(
                "this retry identity was already used for different content; use a new one, or resend the original content unchanged",
            ),
            Self::ConflictingTargets { version_id } => write!(
                f,
                "this batch changes {version_id} twice on the same lifecycle axis; name it once"
            ),
            Self::RootAttentionResolved { version_id } => write!(
                f,
                "root attention on {version_id} is already resolved and does not reopen; publish a new version if the matter is current again"
            ),
            Self::UnknownTarget => f.write_str(
                "the target is not a registered participant of this team instance; only agents of this team can be routed to",
            ),
            Self::NotAnAssignment { route_id } => write!(
                f,
                "{route_id} is an informational route and carries no assignment to end"
            ),
            Self::AssignmentEnded { route_id } => write!(
                f,
                "the assignment on {route_id} has already ended; route the event again if there is new work"
            ),
            Self::AssignmentInProgress { route_id } => write!(
                f,
                "the target is already assigned this event under {route_id}; publish a version to add to it, or end {route_id} first if you want to hand it over again"
            ),
            Self::VersionRetired { version_id } => write!(
                f,
                "{version_id} has already been retired by the root and cannot be rewritten; publish a new version if the matter is current again"
            ),
            Self::ProducerNotUnavailable {
                availability,
                availability_epoch,
            } => write!(
                f,
                "the producer is {availability} (availability_epoch={availability_epoch}); root retirement requires a producer confirmed truly unavailable"
            ),
            Self::AvailabilityConflict {
                availability,
                availability_epoch,
            } => write!(
                f,
                "producer availability has moved; it is now {availability} at availability_epoch={availability_epoch}"
            ),
            Self::DumpCursorStale {
                current_revision,
                current_epoch,
                current_observe_generation,
            } => write!(
                f,
                "this dump cursor belongs to a different snapshot; current revision={current_revision} availability_epoch={current_epoch} observe_generation={current_observe_generation}"
            ),
        }
    }
}

impl std::error::Error for TeamError {}
