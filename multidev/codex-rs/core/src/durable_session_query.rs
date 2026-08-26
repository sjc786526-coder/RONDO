//! Read-only projection of one canonical Durable Team Session.
//!
//! This facade deliberately accepts already-read canonical [`SessionMeta`] and returns only a
//! bounded domain projection. It neither acquires Root writer authority nor exposes the committed
//! medium or [`TeamStateHandle`] to callers.

use crate::team::durable::read_committed_snapshot_after_validated_intent;
use crate::team::durable::validate_session_intent;
use codex_protocol::SessionId;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionMeta;
use codex_team_state::DurableTeamIdentity;
use codex_team_state::ParticipantRole;
use codex_team_state::ProducerState;
use codex_team_state::RootState;
use codex_team_state::TeamDurabilityError;
use codex_team_state::TeamDurabilityStatus;
use codex_team_state::TeamError;
use codex_team_state::TeamSnapshot;
use codex_team_state::TeamStateHandle;
use codex_team_state::committed_snapshot_token;
use std::path::Path;

const MAX_PROJECTED_PARTICIPANTS: usize = 64;
const MAX_PROJECTED_EVENTS: usize = 32;
const MAX_PROJECTED_VERSIONS_PER_EVENT: usize = 8;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableSessionTeamRole {
    Root,
    Member,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableSessionProducerState {
    Open,
    Closed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurableSessionRootState {
    Pending,
    Tracking,
    Resolved,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableSessionParticipant {
    pub thread_id: ThreadId,
    pub role: DurableSessionTeamRole,
    pub label: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableSessionVersion {
    pub id: String,
    pub author: ThreadId,
    pub author_label: String,
    pub summary: String,
    pub producer_state: DurableSessionProducerState,
    pub root_state: DurableSessionRootState,
    pub retired: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableSessionEvent {
    pub id: String,
    pub title: String,
    pub versions: Vec<DurableSessionVersion>,
    pub omitted_versions: usize,
}

/// A bounded view derived from exactly one checksummed committed Team snapshot.
///
/// `commit_generation` and `commit_fingerprint` belong to the durable commit boundary. The
/// fingerprint covers the complete committed payload, including state omitted by this bounded
/// projection, so consumers can reject conflicting reads at one generation. `revision` belongs to
/// the Team domain; consumers must preserve all three and must not substitute one for another.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableSessionTeamProjection {
    pub session_id: SessionId,
    pub root_thread_id: ThreadId,
    pub team_instance: String,
    pub commit_generation: u64,
    pub commit_fingerprint: String,
    pub revision: u64,
    pub participants: Vec<DurableSessionParticipant>,
    pub omitted_participants: usize,
    pub events: Vec<DurableSessionEvent>,
    pub omitted_events: usize,
}

/// Typed failure at the canonical durable read boundary.
///
/// Variants intentionally carry no storage path or backend handle. App-server callers can expose
/// the stable category while keeping local storage diagnostics out of the wire response.
#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum DurableSessionReadError {
    #[error("the canonical Root SessionMeta has no durable Team marker")]
    NotDurable,
    #[error("the canonical durable Team marker conflicts with its SessionMeta")]
    MarkerConflict,
    #[error("durable Team marker version {found} is unsupported; this build supports {supported}")]
    MarkerUnsupportedVersion { found: u32, supported: u32 },
    #[error("the durable Team marker identity does not agree with its canonical Session and Root")]
    MarkerIdentityMismatch,
    #[error("the canonical durable Team state is unavailable")]
    Unavailable,
    #[error("the canonical durable Team snapshot is missing")]
    SnapshotMissing,
    #[error("the canonical durable Team state conflicts with the requested read")]
    Conflict,
    #[error("the canonical durable Team commit result is indeterminate")]
    Indeterminate,
    #[error("the canonical durable Team state is corrupt or exceeds its bound")]
    Corrupt,
    #[error("durable Team state version {found} is unsupported; this build supports {supported}")]
    UnsupportedVersion { found: u32, supported: u32 },
    #[error("the durable Session, Root, marker, and Team snapshot identities do not agree")]
    IdentityMismatch,
    #[error("the committed Team state cannot be projected as its canonical Root")]
    InvalidTeamState,
}

/// Read and project one Durable Team Session without loading or resuming its Root.
///
/// `session_meta` must come from the canonical ThreadStore read seam. The top-level Session/Root
/// identity is treated as authoritative and is cross-validated with both the durable marker and
/// the checksummed snapshot before any Team facts are returned.
pub fn project_committed_durable_session(
    codex_home: &Path,
    session_meta: &SessionMeta,
) -> Result<DurableSessionTeamProjection, DurableSessionReadError> {
    if session_meta.durable_team.is_none() {
        return Err(DurableSessionReadError::NotDurable);
    }
    let identity = DurableTeamIdentity::new(session_meta.session_id, session_meta.id);
    validate_session_intent(session_meta, identity).map_err(map_marker_error)?;
    let committed = read_committed_snapshot_after_validated_intent(codex_home, identity)
        .map_err(map_snapshot_error)?
        .ok_or(DurableSessionReadError::SnapshotMissing)?;
    let commit_token =
        committed_snapshot_token(identity, &committed).map_err(map_snapshot_error)?;
    let team = TeamStateHandle::from_committed_snapshot(identity, &committed)
        .map_err(map_snapshot_error)?;
    let TeamDurabilityStatus::ReadOnly { commit_generation } = team.durability_status() else {
        return Err(DurableSessionReadError::InvalidTeamState);
    };
    if commit_generation != commit_token.commit_generation() {
        return Err(DurableSessionReadError::InvalidTeamState);
    }
    let snapshot = team
        .snapshot_for(identity.root_thread_id())
        .map_err(map_team_error)?;
    if snapshot.viewer != identity.root_thread_id() || snapshot.viewer_role != ParticipantRole::Root
    {
        return Err(DurableSessionReadError::InvalidTeamState);
    }

    Ok(bounded_projection(
        &team,
        snapshot,
        identity,
        commit_generation,
        format_commit_fingerprint(commit_token.payload_checksum()),
    ))
}

fn bounded_projection(
    team: &TeamStateHandle,
    snapshot: TeamSnapshot,
    identity: DurableTeamIdentity,
    commit_generation: u64,
    commit_fingerprint: String,
) -> DurableSessionTeamProjection {
    let mut participants = team.participants();
    if let Some(root_index) = participants
        .iter()
        .position(|participant| participant.thread_id == identity.root_thread_id())
    {
        participants.swap(0, root_index);
    }
    let omitted_participants = participants
        .len()
        .saturating_sub(MAX_PROJECTED_PARTICIPANTS);
    let participants = participants
        .into_iter()
        .take(MAX_PROJECTED_PARTICIPANTS)
        .map(|participant| DurableSessionParticipant {
            thread_id: participant.thread_id,
            role: participant.role.into(),
            label: participant.label,
        })
        .collect();

    let omitted_events = snapshot.events.len().saturating_sub(MAX_PROJECTED_EVENTS);
    let events = snapshot
        .events
        .into_iter()
        .skip(omitted_events)
        .map(|event| {
            let omitted_versions = event
                .versions
                .len()
                .saturating_sub(MAX_PROJECTED_VERSIONS_PER_EVENT);
            let versions = event
                .versions
                .into_iter()
                .skip(omitted_versions)
                .map(|version| DurableSessionVersion {
                    id: version.id.to_string(),
                    author: version.author,
                    author_label: version.author_label,
                    summary: version.summary,
                    producer_state: version.producer_state.into(),
                    root_state: version.root_state.into(),
                    retired: version.retired,
                })
                .collect();
            DurableSessionEvent {
                id: event.id.to_string(),
                title: event.title,
                versions,
                omitted_versions,
            }
        })
        .collect();

    DurableSessionTeamProjection {
        session_id: identity.session_id(),
        root_thread_id: identity.root_thread_id(),
        team_instance: snapshot.instance.to_string(),
        commit_generation,
        commit_fingerprint,
        revision: snapshot.revision.get(),
        participants,
        omitted_participants,
        events,
        omitted_events,
    }
}

fn format_commit_fingerprint(checksum: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut fingerprint = String::with_capacity("sha256:".len() + checksum.len() * 2);
    fingerprint.push_str("sha256:");
    for byte in checksum {
        fingerprint.push(char::from(HEX[usize::from(byte >> 4)]));
        fingerprint.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    fingerprint
}

fn map_marker_error(error: TeamDurabilityError) -> DurableSessionReadError {
    match error {
        TeamDurabilityError::Conflict { .. } => DurableSessionReadError::MarkerConflict,
        TeamDurabilityError::UnsupportedVersion { found, supported } => {
            DurableSessionReadError::MarkerUnsupportedVersion { found, supported }
        }
        TeamDurabilityError::IdentityMismatch => DurableSessionReadError::MarkerIdentityMismatch,
        TeamDurabilityError::Unavailable { .. }
        | TeamDurabilityError::Unknown { .. }
        | TeamDurabilityError::ReadOnly
        | TeamDurabilityError::Corrupt { .. }
        | TeamDurabilityError::GenerationOverflow
        | TeamDurabilityError::Domain(_) => DurableSessionReadError::InvalidTeamState,
    }
}

fn map_snapshot_error(error: TeamDurabilityError) -> DurableSessionReadError {
    match error {
        TeamDurabilityError::Unavailable { .. } => DurableSessionReadError::Unavailable,
        TeamDurabilityError::Conflict { .. } => DurableSessionReadError::Conflict,
        TeamDurabilityError::Unknown { .. } => DurableSessionReadError::Indeterminate,
        TeamDurabilityError::ReadOnly | TeamDurabilityError::Domain(_) => {
            DurableSessionReadError::InvalidTeamState
        }
        TeamDurabilityError::Corrupt { .. } | TeamDurabilityError::GenerationOverflow => {
            DurableSessionReadError::Corrupt
        }
        TeamDurabilityError::UnsupportedVersion { found, supported } => {
            DurableSessionReadError::UnsupportedVersion { found, supported }
        }
        TeamDurabilityError::IdentityMismatch => DurableSessionReadError::IdentityMismatch,
    }
}

fn map_team_error(error: TeamError) -> DurableSessionReadError {
    match error {
        TeamError::Durability { .. }
        | TeamError::SnapshotConflict { .. }
        | TeamError::OwnerIncarnationConflict
        | TeamError::UnknownParticipant
        | TeamError::InstanceReset { .. }
        | TeamError::UnknownReference { .. }
        | TeamError::MalformedReference { .. }
        | TeamError::NotPermitted { .. }
        | TeamError::LifecycleConflict { .. }
        | TeamError::VersionClosed { .. }
        | TeamError::InvalidRequest { .. }
        | TeamError::RetryIdentityReused
        | TeamError::RootAttentionResolved { .. }
        | TeamError::ConflictingTargets { .. }
        | TeamError::UnknownTarget
        | TeamError::NotAnAssignment { .. }
        | TeamError::AssignmentEnded { .. }
        | TeamError::AssignmentInProgress { .. }
        | TeamError::VersionRetired { .. }
        | TeamError::ProducerNotUnavailable { .. }
        | TeamError::AvailabilityConflict { .. }
        | TeamError::DumpCursorStale { .. } => DurableSessionReadError::InvalidTeamState,
    }
}

impl From<ParticipantRole> for DurableSessionTeamRole {
    fn from(value: ParticipantRole) -> Self {
        match value {
            ParticipantRole::Root => Self::Root,
            ParticipantRole::Member => Self::Member,
        }
    }
}

impl From<ProducerState> for DurableSessionProducerState {
    fn from(value: ProducerState) -> Self {
        match value {
            ProducerState::Open => Self::Open,
            ProducerState::Closed => Self::Closed,
        }
    }
}

impl From<RootState> for DurableSessionRootState {
    fn from(value: RootState) -> Self {
        match value {
            RootState::Pending => Self::Pending,
            RootState::Tracking => Self::Tracking,
            RootState::Resolved => Self::Resolved,
        }
    }
}

#[cfg(test)]
#[path = "durable_session_query_tests.rs"]
mod tests;
