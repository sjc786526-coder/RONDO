//! Read-side projections of the canonical state.
//!
//! A [`TeamSnapshot`] is captured once per logical sampling and then treated as immutable, so all
//! provider retries of that sampling see exactly the same team state.

use crate::ids::EventId;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::ids::VersionId;
use crate::model::ParticipantRole;
use crate::model::ProducerState;
use crate::model::RootState;
use codex_protocol::ThreadId;
use serde::Serialize;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct VersionView {
    pub id: VersionId,
    pub author_label: String,
    pub summary: String,
    pub handoff: Option<String>,
    pub producer_state: ProducerState,
    pub root_state: RootState,
    pub authored_on_stale_view: bool,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EventView {
    pub id: EventId,
    pub title: String,
    pub versions: Vec<VersionView>,
}

/// One participant's active view, frozen at a revision.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TeamSnapshot {
    pub instance: TeamInstanceId,
    pub revision: TeamRevision,
    pub viewer: ThreadId,
    pub viewer_label: String,
    pub viewer_role: ParticipantRole,
    pub events: Vec<EventView>,
}

impl TeamSnapshot {
    pub fn is_empty(&self) -> bool {
        self.events.is_empty()
    }
}

/// A bounded history request. `limit` is clamped by the store.
///
/// `before` is the cursor: pass the `next_before` of the previous page to keep walking backwards.
/// Without it a capped query could only ever show the newest slice, and everything the projection
/// reported as omitted would be permanently out of reach.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct HistoryQuery {
    pub event_id: Option<EventId>,
    pub limit: Option<usize>,
    pub before: Option<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct EventHistory {
    pub event: EventView,
    pub total_versions: usize,
    pub omitted_versions: usize,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct HistoryPage {
    pub instance: TeamInstanceId,
    pub revision: TeamRevision,
    pub events: Vec<EventHistory>,
    pub total_events: usize,
    pub omitted_events: usize,
    /// Cursor for the next page, or `None` when this page reached the oldest entry.
    pub next_before: Option<u32>,
}
