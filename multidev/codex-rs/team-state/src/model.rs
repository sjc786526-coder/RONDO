//! Team-state domain objects.
//!
//! The split enforced here is the one the design contract cares about: [`AuthoredVersion`] is
//! written once and never rewritten, while the two lifecycle fields attached to it are mutable
//! projections. Only [`crate::store`] can reach the mutable fields, and it can only reach the
//! lifecycle ones, so "authored content is immutable" is a property of the code rather than a
//! convention.

use crate::ids::EventId;
use crate::ids::TeamRevision;
use crate::ids::VersionId;
use codex_protocol::ThreadId;
use serde::Serialize;
use std::fmt;

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
    /// Evidence locators. Always empty in M-1; evidence anchoring is a later stage.
    pub evidence_refs: Vec<String>,
}

/// One immutable authored entry in an event's chain, plus its two mutable lifecycle states.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TeamVersion {
    id: VersionId,
    authored: AuthoredVersion,
    pub(crate) producer_state: ProducerState,
    pub(crate) root_state: RootState,
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

    /// Whether this version still keeps the event in its own author's active view.
    pub(crate) fn occupies_author_attention(&self) -> bool {
        matches!(self.producer_state, ProducerState::Open)
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

    /// Whether the event is in `viewer`'s active view.
    ///
    /// M-1 implements the two inclusion reasons that exist before routing: the viewer still has a
    /// version of its own that it has not closed, or the viewer is the root and some version still
    /// occupies root attention. Route-based inclusion arrives with M-2.
    pub(crate) fn is_active_for(&self, viewer: ThreadId, role: ParticipantRole) -> bool {
        let has_own_open_version = self.versions.iter().any(|version| {
            version.authored.author == viewer && version.occupies_author_attention()
        });
        if has_own_open_version {
            return true;
        }
        role.is_root()
            && self
                .versions
                .iter()
                .any(|version| version.root_state.occupies_root_attention())
    }

    /// Whether `viewer` may read this event's history.
    ///
    /// Before routing exists the only readers are the root (whole team) and participants who
    /// authored something under the event.
    pub(crate) fn is_readable_by(&self, viewer: ThreadId, role: ParticipantRole) -> bool {
        role.is_root()
            || self.created_by == viewer
            || self
                .versions
                .iter()
                .any(|version| version.authored.author == viewer)
    }
}
