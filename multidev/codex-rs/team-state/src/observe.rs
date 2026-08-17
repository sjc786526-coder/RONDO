//! Lightweight, deterministic explanation of canonical team state.
//!
//! Dump, change log and publication stats are read-only views of the same TeamState. They never
//! become a second writable copy, and they never carry tool output, transcripts or private context.

use crate::availability::AvailabilityEpoch;
use crate::availability::ProducerAvailability;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::model::ParticipantRole;
use crate::model::ProducerState;
use crate::model::RootState;
use crate::model::RouteDuty;
use crate::mutation::TeamError;
use serde::Serialize;

/// Hard ceiling on one dump or change-log page.
pub const MAX_OBSERVE_LIMIT: usize = 50;
pub(crate) const DEFAULT_OBSERVE_LIMIT: usize = 20;

/// One page of a frozen dump. Identity fields let a caller refuse to splice pages from different
/// snapshots.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TeamDumpPage {
    pub instance: TeamInstanceId,
    pub revision: TeamRevision,
    pub wake_generation: u64,
    pub availability_epoch: AvailabilityEpoch,
    pub observe_generation: u64,
    pub entries: Vec<DumpEntry>,
    pub total_entries: usize,
    pub next_offset: Option<u32>,
}

/// One bounded dump row. Ordered by a stable sort so HashMap iteration cannot change the page.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "entry", rename_all = "snake_case")]
pub enum DumpEntry {
    Participant {
        label: String,
        thread_id: String,
        role: ParticipantRole,
        availability: ProducerAvailability,
    },
    Event {
        event_id: String,
        created_by: String,
        created_by_thread_id: String,
        version_count: usize,
        route_count: usize,
    },
    Version {
        version_id: String,
        author: String,
        author_thread_id: String,
        producer_state: ProducerState,
        root_state: RootState,
        retired: bool,
        retired_by: Option<String>,
        retired_by_thread_id: Option<String>,
        retired_at: Option<TeamRevision>,
        retire_reason: Option<String>,
        retired_availability: Option<ProducerAvailability>,
        retired_availability_epoch: Option<AvailabilityEpoch>,
        fact_ref_count: usize,
    },
    VersionFact {
        version_id: String,
        fact_id: String,
    },
    Route {
        route_id: String,
        event_id: String,
        target: String,
        target_thread_id: String,
        duty: RouteDuty,
        delivery: String,
    },
    Fact {
        fact_id: String,
        producer: String,
        producer_thread_id: String,
        category: String,
        item_id: String,
        call_id: String,
        tool: String,
    },
    Visibility {
        participant: String,
        participant_thread_id: String,
        event_id: String,
        visible: bool,
        reasons: Vec<String>,
    },
    Activity {
        participant: String,
        participant_thread_id: String,
        event_id: String,
        active: bool,
        reasons: Vec<String>,
    },
    Publication {
        participant: String,
        thread_id: String,
        version_count: u64,
        authored_chars: u64,
        fact_ref_count: u64,
    },
}

/// A page of the revision-ordered change log.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ChangeLogPage {
    pub instance: TeamInstanceId,
    pub revision: TeamRevision,
    pub wake_generation: u64,
    pub entries: Vec<ChangeLogView>,
    pub total_entries: usize,
    pub next_offset: Option<u32>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ChangeLogView {
    pub revision: TeamRevision,
    pub actor: String,
    pub actor_thread_id: String,
    pub kind: ChangeKind,
    pub target: String,
    pub before: Option<String>,
    pub after: Option<String>,
    pub wake: WakeDecisionView,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ChangeKind {
    Publish,
    CloseProducer,
    SetRootState,
    Retire,
    Route,
    Delivery,
    EndAssignment,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "decision", rename_all = "snake_case")]
pub enum WakeDecisionView {
    Signalled {
        target: String,
        target_thread_id: String,
        rule: String,
    },
    None {
        rule: String,
    },
}

/// Publication volume for one participant, recomputed from canonical authored fields.
///
/// Rows are keyed by the participant's stable thread identity. `participant` is the current label
/// for humans and may repeat; it is not the aggregation key.
///
/// `authored_chars` is the number of Unicode scalar values (`chars().count()`) in:
/// - the Event title, attributed to the version that opened the event
/// - each Version's canonical `summary`
/// - each Version's canonical `handoff`, when present
///
/// Rejected publishes and stable retries are not stored, so they cannot appear here.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct PublicationStats {
    pub participant: String,
    pub thread_id: String,
    pub version_count: u64,
    pub authored_chars: u64,
    pub fact_ref_count: u64,
}

/// One bounded page of publication stats. The same hard ceiling as dump and the change log.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct PublicationStatsPage {
    pub instance: TeamInstanceId,
    pub revision: TeamRevision,
    pub wake_generation: u64,
    pub entries: Vec<PublicationStats>,
    pub total_entries: usize,
    pub next_offset: Option<u32>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ObserveQuery {
    pub limit: Option<usize>,
    pub offset: Option<u32>,
    pub after: Option<TeamRevision>,
}

impl ObserveQuery {
    pub(crate) fn limit(self) -> usize {
        self.limit
            .unwrap_or(DEFAULT_OBSERVE_LIMIT)
            .clamp(1, MAX_OBSERVE_LIMIT)
    }
}

/// Cursor carried by dump pages so a later page can refuse a different snapshot.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DumpCursor {
    pub revision: TeamRevision,
    pub availability_epoch: AvailabilityEpoch,
    pub observe_generation: u64,
    pub offset: u32,
}

impl DumpCursor {
    pub fn encode(self) -> String {
        format!(
            "{}:{}:{}:{}",
            self.revision.get(),
            self.availability_epoch.get(),
            self.observe_generation,
            self.offset
        )
    }

    pub fn decode(value: &str) -> Result<Self, TeamError> {
        let mut parts = value.split(':');
        let revision =
            parts
                .next()
                .and_then(|part| part.parse().ok())
                .ok_or(TeamError::InvalidRequest {
                    reason: "dump cursor is malformed",
                })?;
        let epoch =
            parts
                .next()
                .and_then(|part| part.parse().ok())
                .ok_or(TeamError::InvalidRequest {
                    reason: "dump cursor is malformed",
                })?;
        let observe_generation =
            parts
                .next()
                .and_then(|part| part.parse().ok())
                .ok_or(TeamError::InvalidRequest {
                    reason: "dump cursor is malformed",
                })?;
        let offset =
            parts
                .next()
                .and_then(|part| part.parse().ok())
                .ok_or(TeamError::InvalidRequest {
                    reason: "dump cursor is malformed",
                })?;
        if parts.next().is_some() {
            return Err(TeamError::InvalidRequest {
                reason: "dump cursor is malformed",
            });
        }
        Ok(Self {
            revision: TeamRevision::from_raw(revision),
            availability_epoch: AvailabilityEpoch::from_raw(epoch),
            observe_generation,
            offset,
        })
    }
}

/// Internal change-log row. Labels are resolved at read time so a rename cannot rewrite history.
#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ChangeRecord {
    pub revision: TeamRevision,
    pub actor: codex_protocol::ThreadId,
    pub kind: ChangeKind,
    pub target: String,
    pub before: Option<String>,
    pub after: Option<String>,
    pub wake: StoredWake,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) enum StoredWake {
    Signalled {
        participant: codex_protocol::ThreadId,
        rule: &'static str,
    },
    None {
        rule: &'static str,
    },
}
