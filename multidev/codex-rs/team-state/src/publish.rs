//! Read-only preparation for the canonical publish mutation.

use crate::ids::EventId;
use crate::ids::TeamRevision;
use crate::model::ParticipantRole;
use crate::mutation::PublishOutcome;
use std::fmt;

/// The result of checking a publish request before any external preparation work.
///
/// A committed retry is answered from the canonical ledger. A ready request carries a bounded copy
/// of the authored fields exactly as the store would write them, while the original request remains
/// the only request accepted by the final publish mutation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PublishPreparation {
    Committed(PublishOutcome),
    Ready(PreparedPublish),
}

/// Canonical authored fields for a publish request that has not committed yet.
#[derive(Clone, Eq, PartialEq)]
pub struct PreparedPublish {
    pub actor_role: ParticipantRole,
    pub target: PreparedPublishTarget,
    pub summary: String,
    pub handoff: Option<String>,
}

/// Canonical local scope of a publish request.
#[derive(Clone, Eq, PartialEq)]
pub enum PreparedPublishTarget {
    NewEvent {
        title: String,
    },
    ExistingEvent {
        event_id: EventId,
        title: String,
        /// Event-local stale status at preparation time. The final publish mutation rechecks it.
        authored_on_stale_view: bool,
    },
}

/// The bounded, event-local public history needed by Publication Critic preparation.
///
/// This deliberately cannot carry routes, Fact identities, lifecycle state, or participant
/// metadata. Only the authored continuity fields and a body-free evidence count leave the store.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPublishHistory {
    pub event_id: EventId,
    pub revision: TeamRevision,
    pub versions: Vec<PreparedPublishHistoryVersion>,
    pub omitted_versions: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPublishHistoryVersion {
    pub summary: String,
    pub handoff: Option<String>,
    pub evidence_reference_count: usize,
}

impl fmt::Debug for PreparedPublish {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("PreparedPublish")
            .field("actor_role", &self.actor_role)
            .field("target", &self.target)
            .field("summary_scalars", &self.summary.chars().count())
            .field("handoff_present", &self.handoff.is_some())
            .finish()
    }
}

impl fmt::Debug for PreparedPublishTarget {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NewEvent { title } => f
                .debug_struct("NewEvent")
                .field("title_scalars", &title.chars().count())
                .finish(),
            Self::ExistingEvent {
                event_id,
                title,
                authored_on_stale_view,
            } => f
                .debug_struct("ExistingEvent")
                .field("event_id", event_id)
                .field("title_scalars", &title.chars().count())
                .field("authored_on_stale_view", authored_on_stale_view)
                .finish(),
        }
    }
}
