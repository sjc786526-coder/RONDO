//! Team-state domain objects.
//!
//! The split enforced here is the one the design contract cares about: [`AuthoredVersion`] is
//! written once and never rewritten, while the two lifecycle fields attached to it are mutable
//! projections. Only [`crate::store`] can reach the mutable fields, and it can only reach the
//! lifecycle ones, so "authored content is immutable" is a property of the code rather than a
//! convention.

use crate::availability::AvailabilityEpoch;
use crate::availability::ProducerAvailability;
use crate::ids::EventId;
use crate::ids::FactId;
use crate::ids::RouteId;
use crate::ids::TeamRevision;
use crate::ids::VersionId;
use codex_protocol::ThreadId;
use serde::Serialize;
use std::fmt;

/// Per-field ceilings on authored content.
///
/// The store never holds an unbounded authored field, so everything downstream of it — the
/// projection, history queries, tool output — is bounded by construction rather than by each
/// consumer remembering to clamp. Over-long input is cut at write time with a visible marker, so
/// the author's own record shows that it was cut.
const MAX_TITLE_CHARS: usize = 200;
const MAX_SUMMARY_CHARS: usize = 2_000;
const MAX_HANDOFF_CHARS: usize = 1_000;
/// A route note travels inside a notification rather than the projection, and its whole purpose is
/// to stay small enough that the notice never becomes a second copy of the event.
const MAX_ROUTE_NOTE_CHARS: usize = 400;
/// Root retirement reasons are coordination metadata, bounded the same way as delivery failures.
const MAX_RETIRE_REASON_CHARS: usize = 400;
/// Delivery failures come from transport errors, which are not authored content but still end up in
/// the canonical record, so they are bounded the same way.
const MAX_DELIVERY_REASON_CHARS: usize = 300;
const TRUNCATION_MARKER: &str = " […truncated]";

/// Clamp `value` to `max_chars`, marking it when anything was removed.
pub(crate) fn clamp_authored(value: &str, max_chars: usize) -> String {
    if value.chars().count() <= max_chars {
        return value.to_string();
    }
    let kept: String = value.chars().take(max_chars).collect();
    format!("{kept}{TRUNCATION_MARKER}")
}

pub(crate) fn clamp_title(value: &str) -> String {
    clamp_authored(value, MAX_TITLE_CHARS)
}

pub(crate) fn clamp_summary(value: &str) -> String {
    clamp_authored(value, MAX_SUMMARY_CHARS)
}

pub(crate) fn clamp_handoff(value: &str) -> String {
    clamp_authored(value, MAX_HANDOFF_CHARS)
}

pub(crate) fn clamp_route_note(value: &str) -> String {
    clamp_authored(value, MAX_ROUTE_NOTE_CHARS)
}

pub(crate) fn clamp_delivery_reason(value: &str) -> String {
    clamp_authored(value, MAX_DELIVERY_REASON_CHARS)
}

pub(crate) fn clamp_retire_reason(value: &str) -> String {
    clamp_authored(value, MAX_RETIRE_REASON_CHARS)
}

/// What the author of a version currently believes about the matter it describes.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProducerState {
    /// The author still considers this worth attention.
    #[default]
    Open,
    /// The author is done with it. Terminal: a closed version is never reopened in place.
    Closed,
}

impl fmt::Display for ProducerState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Open => "open",
            Self::Closed => "closed",
        })
    }
}

/// Where the root's coordination attention stands on a version.
///
/// Independent of [`ProducerState`]: the root resolving something does not close the author's
/// item, and the author closing an item does not consume the root's attention.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RootState {
    /// Not yet explicitly handled by the root.
    #[default]
    Pending,
    /// The root judged it and wants it to keep occupying attention.
    Tracking,
    /// Coordination is done for now. Not a claim that the matter itself is solved.
    Resolved,
}

impl RootState {
    pub(crate) fn occupies_root_attention(self) -> bool {
        !matches!(self, Self::Resolved)
    }
}

impl fmt::Display for RootState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Pending => "pending",
            Self::Tracking => "tracking",
            Self::Resolved => "resolved",
        })
    }
}

/// Capability tier of a registered team participant.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ParticipantRole {
    /// The root of the agent tree. Coordinates, and is the only role that owns [`RootState`].
    Root,
    /// A spawned member of the same root tree.
    Member,
}

impl ParticipantRole {
    pub fn is_root(self) -> bool {
        matches!(self, Self::Root)
    }
}

/// A registered participant of the team instance.
///
/// Registration is derived from the authoritative session/agent registry, never from anything the
/// model reports about itself.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct Participant {
    pub thread_id: ThreadId,
    pub role: ParticipantRole,
    /// Human/model-visible label, taken from the agent path registered for this thread.
    pub label: String,
}

/// The immutable half of a version: what its author said, at the time they said it.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct AuthoredVersion {
    pub author: ThreadId,
    pub summary: String,
    pub handoff: Option<String>,
    /// References to the observations the harness recorded for this author since its last successful
    /// publish. Typed identities only: the observations themselves stay where Codex kept them.
    pub evidence_refs: Vec<FactId>,
}

/// Root-declared independent terminal for a version whose author can no longer act.
///
/// This is not [`ProducerState::Closed`]: the author never closed the item. It only removes the
/// producer-open activity reason.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct RetirementRecord {
    pub retired_by: ThreadId,
    pub reason: String,
    pub retired_at: TeamRevision,
    pub availability: ProducerAvailability,
    pub availability_epoch: AvailabilityEpoch,
}

/// One immutable authored entry in an event's chain, plus its two mutable lifecycle states.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TeamVersion {
    id: VersionId,
    authored: AuthoredVersion,
    pub(crate) producer_state: ProducerState,
    pub(crate) root_state: RootState,
    pub(crate) retirement: Option<RetirementRecord>,
    created_at: TeamRevision,
    /// Set when the author submitted against a view older than the event's latest change. The
    /// append is still accepted; it is only labelled.
    authored_on_stale_view: Option<TeamRevision>,
}

impl TeamVersion {
    pub(crate) fn new(
        id: VersionId,
        authored: AuthoredVersion,
        root_state: RootState,
        created_at: TeamRevision,
        authored_on_stale_view: Option<TeamRevision>,
    ) -> Self {
        Self {
            id,
            authored,
            producer_state: ProducerState::Open,
            root_state,
            retirement: None,
            created_at,
            authored_on_stale_view,
        }
    }

    pub fn id(&self) -> VersionId {
        self.id
    }

    pub fn authored(&self) -> &AuthoredVersion {
        &self.authored
    }

    pub fn producer_state(&self) -> ProducerState {
        self.producer_state
    }

    pub fn root_state(&self) -> RootState {
        self.root_state
    }

    pub fn created_at(&self) -> TeamRevision {
        self.created_at
    }

    pub fn authored_on_stale_view(&self) -> Option<TeamRevision> {
        self.authored_on_stale_view
    }

    pub fn retirement(&self) -> Option<&RetirementRecord> {
        self.retirement.as_ref()
    }

    pub fn is_retired(&self) -> bool {
        self.retirement.is_some()
    }

    /// Whether this version still keeps the event in its own author's active view.
    ///
    /// Root retirement is an independent terminal: it does not pretend the author closed the
    /// item, but it does stop occupying the author's attention.
    pub(crate) fn occupies_author_attention(&self) -> bool {
        matches!(self.producer_state, ProducerState::Open) && self.retirement.is_none()
    }
}

/// Where a route's work assignment stands.
///
/// This is only the assignment half of a route. The visibility a route grants is irrevocable and
/// does not appear here at all, which is what keeps "may read" and "still has work to do" from
/// collapsing into one flag.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RouteDuty {
    /// Informational: the target may read and contribute, but nothing was asked of it. A notice
    /// never becomes work, so it never enters the target's active view on the route's account and
    /// there is nothing to end.
    Notice,
    /// Work the target has been asked to start or continue.
    Assigned,
    /// Work that has been ended. Terminal: a new route is how work is handed over again.
    Ended,
}

impl RouteDuty {
    /// Whether this route keeps its event in the target's active view.
    pub fn is_assigned(self) -> bool {
        matches!(self, Self::Assigned)
    }
}

impl fmt::Display for RouteDuty {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Notice => "notice",
            Self::Assigned => "assigned",
            Self::Ended => "ended",
        })
    }
}

/// How far the compact notice for a route has got.
///
/// The grant and the assignment are already committed whatever this says. Delivery is the side
/// effect that follows them, so a failure here is a retryable fact about the notice and never a
/// reason to undo the canonical change.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum DeliveryState {
    /// Committed, not yet reported either way.
    Pending,
    /// Handed to the target's own delivery path. Terminal: a later report cannot un-deliver it.
    Delivered,
    /// The last attempt failed. The grant and assignment stand and the notice can be retried.
    Failed { reason: String },
}

impl DeliveryState {
    pub fn is_delivered(&self) -> bool {
        matches!(self, Self::Delivered)
    }

    /// Short machine-readable state, without the failure text.
    pub fn label(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Delivered => "delivered",
            Self::Failed { .. } => "failed",
        }
    }

    pub fn failure_reason(&self) -> Option<&str> {
        match self {
            Self::Pending | Self::Delivered => None,
            Self::Failed { reason } => Some(reason),
        }
    }
}

impl fmt::Display for DeliveryState {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Pending | Self::Delivered => f.write_str(self.label()),
            Self::Failed { reason } => write!(f, "failed: {reason}"),
        }
    }
}

/// One root decision to hand an event to another participant.
///
/// The grant it carries is irrevocable: ending the assignment retires the work, not the target's
/// right to read what it was shown.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TeamRoute {
    id: RouteId,
    target: ThreadId,
    routed_by: ThreadId,
    /// Compact action hint for the target, carried by the notice. Never the event's own chain.
    note: Option<String>,
    created_at: TeamRevision,
    pub(crate) duty: RouteDuty,
    pub(crate) delivery: DeliveryState,
    pub(crate) ended_by: Option<ThreadId>,
    pub(crate) ended_at: Option<TeamRevision>,
}

impl TeamRoute {
    pub(crate) fn new(
        id: RouteId,
        target: ThreadId,
        routed_by: ThreadId,
        note: Option<String>,
        duty: RouteDuty,
        created_at: TeamRevision,
    ) -> Self {
        Self {
            id,
            target,
            routed_by,
            note: note.as_deref().map(clamp_route_note),
            created_at,
            duty,
            delivery: DeliveryState::Pending,
            ended_by: None,
            ended_at: None,
        }
    }

    pub fn id(&self) -> RouteId {
        self.id
    }

    pub fn target(&self) -> ThreadId {
        self.target
    }

    pub fn routed_by(&self) -> ThreadId {
        self.routed_by
    }

    pub fn note(&self) -> Option<&str> {
        self.note.as_deref()
    }

    pub fn duty(&self) -> RouteDuty {
        self.duty
    }

    pub fn delivery(&self) -> &DeliveryState {
        &self.delivery
    }

    pub fn created_at(&self) -> TeamRevision {
        self.created_at
    }

    pub fn ended_by(&self) -> Option<ThreadId> {
        self.ended_by
    }

    pub fn ended_at(&self) -> Option<TeamRevision> {
        self.ended_at
    }
}

/// A team-level matter. Versions accumulate under it in registration order; the order carries no
/// causal or superseding meaning of its own.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TeamEvent {
    id: EventId,
    title: String,
    created_by: ThreadId,
    created_at: TeamRevision,
    pub(crate) last_changed_at: TeamRevision,
    pub(crate) versions: Vec<TeamVersion>,
    /// Routes of this event, oldest first. Every one of them is a standing visibility grant.
    pub(crate) routes: Vec<TeamRoute>,
}

impl TeamEvent {
    pub(crate) fn new(
        id: EventId,
        title: String,
        created_by: ThreadId,
        created_at: TeamRevision,
    ) -> Self {
        Self {
            id,
            title,
            created_by,
            created_at,
            last_changed_at: created_at,
            versions: Vec::new(),
            routes: Vec::new(),
        }
    }

    pub fn id(&self) -> EventId {
        self.id
    }

    pub fn title(&self) -> &str {
        &self.title
    }

    pub fn created_by(&self) -> ThreadId {
        self.created_by
    }

    pub fn created_at(&self) -> TeamRevision {
        self.created_at
    }

    pub fn last_changed_at(&self) -> TeamRevision {
        self.last_changed_at
    }

    pub fn versions(&self) -> &[TeamVersion] {
        &self.versions
    }

    #[cfg(test)]
    pub(crate) fn version(&self, id: VersionId) -> Option<&TeamVersion> {
        self.versions.iter().find(|version| version.id == id)
    }

    pub(crate) fn version_position(&self, id: VersionId) -> Option<usize> {
        self.versions.iter().position(|version| version.id == id)
    }

    pub fn routes(&self) -> &[TeamRoute] {
        &self.routes
    }

    pub(crate) fn route_position(&self, id: RouteId) -> Option<usize> {
        self.routes.iter().position(|route| route.id == id)
    }

    /// The assignment this target is still working on, if any.
    ///
    /// At most one can exist at a time, which is what keeps a repeated hand-over from stacking up
    /// duplicate work on the same participant.
    pub(crate) fn assignment_in_progress_for(&self, target: ThreadId) -> Option<&TeamRoute> {
        self.routes
            .iter()
            .find(|route| route.target == target && route.duty.is_assigned())
    }

    /// Whether the event is in `viewer`'s active view.
    ///
    /// The three inclusion reasons of the design contract, and only those: the viewer still has a
    /// version of its own that it has not closed, a route assignment addressed to it is still in
    /// progress, or the viewer is the root and some version still occupies root attention. Each is
    /// an independent reason, so retiring one of them leaves the others alone — ending an
    /// assignment must not take away a participant's view of its own unfinished work, and having
    /// merely been shown an event must not keep it in view forever.
    pub(crate) fn is_active_for(&self, viewer: ThreadId, role: ParticipantRole) -> bool {
        let has_own_open_version = self.versions.iter().any(|version| {
            version.authored.author == viewer && version.occupies_author_attention()
        });
        if has_own_open_version {
            return true;
        }
        if self.assignment_in_progress_for(viewer).is_some() {
            return true;
        }
        role.is_root()
            && self
                .versions
                .iter()
                .any(|version| version.root_state.occupies_root_attention())
    }

    /// Whether this event is visible to `participant`.
    ///
    /// Visibility governs both reading and contributing: in the first version, being able to see an
    /// event is exactly what makes someone eligible to add to it. That means the root (whole team),
    /// whoever opened the event or already authored under it, and anyone the root has routed it to.
    /// A route grant is permanent — it survives the end of its assignment — so what a participant
    /// was once shown stays readable through bounded history even after it leaves the active view.
    pub(crate) fn is_visible_to(&self, participant: ThreadId, role: ParticipantRole) -> bool {
        role.is_root()
            || self.created_by == participant
            || self
                .versions
                .iter()
                .any(|version| version.authored.author == participant)
            || self.routes.iter().any(|route| route.target == participant)
    }
}
