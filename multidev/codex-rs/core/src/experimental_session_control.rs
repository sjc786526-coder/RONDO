//! Narrow domain façade for the experimental Session control prototype.
//!
//! This module deliberately exposes neither `AgentControl` nor `TeamStateHandle`. Every operation
//! starts from a concrete loaded `Session`, proves that it is the currently registered root owner,
//! and only then reads or mutates that root tree's canonical in-process Team state.

use crate::agent::AgentControl;
use crate::agent::control::DurableTeamRootCloseGuard;
use crate::session::session::Session;
use codex_protocol::SessionId;
use codex_protocol::ThreadId;
use codex_protocol::protocol::MultiAgentVersion;
use codex_team_state::LifecycleChange;
use codex_team_state::LifecycleRequest;
use codex_team_state::LifecycleSnapshot;
use codex_team_state::LifecycleTarget;
use codex_team_state::ParticipantRole;
use codex_team_state::ProducerState;
use codex_team_state::RootState;
use codex_team_state::TeamClosePermit;
use codex_team_state::TeamError;
use codex_team_state::TeamInstanceId;
use codex_team_state::TeamMutationPrecondition;
use codex_team_state::TeamRevision;
use codex_team_state::TeamSnapshot;
use codex_team_state::TeamStateHandle;
use codex_team_state::VersionId;
use std::str::FromStr;
use std::sync::Arc;
use uuid::Uuid;

const MAX_PROJECTED_PARTICIPANTS: usize = 64;
const MAX_PROJECTED_EVENTS: usize = 32;
const MAX_PROJECTED_VERSIONS_PER_EVENT: usize = 8;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExperimentalSessionControlTeamRole {
    Root,
    Member,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExperimentalSessionControlProducerState {
    Open,
    Closed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExperimentalSessionControlRootState {
    Pending,
    Tracking,
    Resolved,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExperimentalSessionControlTeamUnavailableReason {
    MultiAgentV2Inactive,
    TeamStateDisabled,
}

impl std::fmt::Display for ExperimentalSessionControlTeamUnavailableReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Self::MultiAgentV2Inactive => "multi-agent V2 is not active for this Session",
            Self::TeamStateDisabled => "canonical Team state is disabled for this Session",
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExperimentalSessionControlParticipant {
    pub thread_id: ThreadId,
    pub role: ExperimentalSessionControlTeamRole,
    pub label: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExperimentalSessionControlVersion {
    pub id: String,
    pub author: ThreadId,
    pub author_label: String,
    pub summary: String,
    pub producer_state: ExperimentalSessionControlProducerState,
    pub root_state: ExperimentalSessionControlRootState,
    pub retired: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExperimentalSessionControlEvent {
    pub id: String,
    pub title: String,
    pub versions: Vec<ExperimentalSessionControlVersion>,
    pub omitted_versions: usize,
}

/// Bounded read projection of one live root's canonical Team state.
///
/// This is intentionally narrower than `TeamSnapshot`: it contains only the identity and lifecycle
/// facts needed by the prototype, and explicitly counts anything omitted by the fixed bounds.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExperimentalSessionControlTeamProjection {
    pub team_instance: String,
    pub revision: u64,
    pub root_thread_id: ThreadId,
    pub participants: Vec<ExperimentalSessionControlParticipant>,
    pub omitted_participants: usize,
    pub events: Vec<ExperimentalSessionControlEvent>,
    pub omitted_events: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExperimentalSessionControlSetRootStateParams {
    pub version_id: String,
    pub expected_producer_state: ExperimentalSessionControlProducerState,
    pub expected_root_state: ExperimentalSessionControlRootState,
    pub next_root_state: ExperimentalSessionControlRootState,
}

/// Formal control parameters that bind a lifecycle update to one committed Team snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableSessionControlSetRootStateParams {
    pub owner_incarnation_id: String,
    pub team_instance_id: String,
    pub team_revision: u64,
    pub commit_generation: u64,
    pub version_id: String,
    pub expected_producer_state: ExperimentalSessionControlProducerState,
    pub expected_root_state: ExperimentalSessionControlRootState,
    pub next_root_state: ExperimentalSessionControlRootState,
}

/// Formal shutdown parameters bound to one loaded Root writer and committed Team snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurableSessionControlShutdownParams {
    pub owner_incarnation_id: String,
    pub team_instance_id: String,
    pub team_revision: u64,
    pub commit_generation: u64,
}

pub(crate) struct PreparedDurableSessionShutdown {
    pub(crate) lifecycle_close: DurableTeamRootCloseGuard,
    pub(crate) team_close: Box<dyn TeamClosePermit>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExperimentalSessionControlLifecycle {
    pub version_id: String,
    pub producer_state: ExperimentalSessionControlProducerState,
    pub root_state: ExperimentalSessionControlRootState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExperimentalSessionControlMutationOutcome {
    /// Revision at which the requested lifecycle operation linearized.
    pub mutation_revision: u64,
    pub changed: bool,
    pub updated: ExperimentalSessionControlVersion,
    /// A canonical re-read performed after the mutation. It may be newer than `mutation_revision`
    /// when another Team mutation wins the lock between the operation and this read.
    pub projection: ExperimentalSessionControlTeamProjection,
}

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum ExperimentalSessionControlError {
    #[error(
        "thread {thread_id} is not the root owner of Session {session_id}; child and non-owner access is refused"
    )]
    NotRootOwner {
        thread_id: ThreadId,
        session_id: SessionId,
    },
    #[error("root owner {thread_id} is not currently loaded")]
    OwnerUnavailable { thread_id: ThreadId },
    #[error("loaded root {thread_id} has no canonical Team root identity")]
    OwnerIdentityUnavailable { thread_id: ThreadId },
    #[error("loaded participant {thread_id} is not the canonical Team root")]
    NotRootParticipant { thread_id: ThreadId },
    #[error("canonical Team is unavailable: {reason}")]
    TeamUnavailable {
        reason: ExperimentalSessionControlTeamUnavailableReason,
    },
    #[error("invalid Team version id `{version_id}`")]
    InvalidVersionId { version_id: String },
    #[error(
        "Team instance reset: reference belongs to {referenced_instance}, current instance is {current_instance}"
    )]
    TeamInstanceReset {
        referenced_instance: String,
        current_instance: String,
    },
    #[error("unknown Team reference `{reference}`")]
    UnknownReference { reference: String },
    #[error("malformed Team reference `{reference}`")]
    MalformedReference { reference: String },
    #[error("Team lifecycle mutation is not permitted: {reason}")]
    NotPermitted { reason: String },
    #[error("Team lifecycle precondition no longer holds")]
    LifecycleConflict {
        current: ExperimentalSessionControlLifecycle,
    },
    #[error("Team version `{version_id}` is closed")]
    VersionClosed { version_id: String },
    #[error("invalid Team lifecycle request: {reason}")]
    InvalidRequest { reason: String },
    #[error("root attention for Team version `{version_id}` is already resolved")]
    RootAttentionResolved { version_id: String },
    #[error("conflicting lifecycle targets for Team version `{version_id}`")]
    ConflictingTargets { version_id: String },
    #[error("Team version `{version_id}` is retired")]
    VersionRetired { version_id: String },
    #[error("canonical Team rejected the operation: {message}")]
    UnexpectedTeamError { message: String },
    #[error("the committed Team snapshot changed after it was read")]
    SnapshotConflict,
    #[error("the loaded Root writer incarnation changed after it was read")]
    OwnerIncarnationConflict,
    #[error("formal Session shutdown handoff failed: {message}")]
    ShutdownHandoff { message: String },
    #[error("formal Session shutdown terminated the owner with an unknown close result: {message}")]
    ShutdownTerminatedWithError { message: String },
}

pub(crate) async fn project_loaded_root(
    session: &Session,
) -> Result<ExperimentalSessionControlTeamProjection, ExperimentalSessionControlError> {
    with_canonical_loaded_root(session, false, project_team).await
}

pub(crate) async fn loaded_root_owner_incarnation_id(
    session: &Session,
) -> Result<String, ExperimentalSessionControlError> {
    with_canonical_loaded_root(session, false, |team, thread_id| {
        team.owner_incarnation_id()
            .map(|incarnation_id| incarnation_id.to_string())
            .ok_or(ExperimentalSessionControlError::OwnerIdentityUnavailable { thread_id })
    })
    .await
}

pub(crate) async fn prepare_loaded_root_shutdown_at_snapshot(
    session: &Session,
    params: DurableSessionControlShutdownParams,
) -> Result<PreparedDurableSessionShutdown, ExperimentalSessionControlError> {
    let expected_owner_incarnation_id = Uuid::parse_str(&params.owner_incarnation_id)
        .map_err(|_| ExperimentalSessionControlError::OwnerIncarnationConflict)?;
    let instance = TeamInstanceId::from_str(&params.team_instance_id)
        .map_err(|_| ExperimentalSessionControlError::SnapshotConflict)?;
    let precondition = TeamMutationPrecondition {
        instance,
        revision: TeamRevision::from_raw(params.team_revision),
        commit_generation: params.commit_generation,
    };

    with_canonical_loaded_root(session, true, |team, thread_id| {
        if team.owner_incarnation_id() != Some(expected_owner_incarnation_id) {
            return Err(ExperimentalSessionControlError::OwnerIncarnationConflict);
        }
        Ok(thread_id)
    })
    .await?;
    session
        .ensure_durable_root_activation()
        .await
        .map_err(
            |error| ExperimentalSessionControlError::UnexpectedTeamError {
                message: error.to_string(),
            },
        )?;
    let agent_control = &session.services.agent_control;
    let lifecycle_close = agent_control
        .begin_durable_team_root_close(session.thread_id())
        .map_err(
            |error| ExperimentalSessionControlError::UnexpectedTeamError {
                message: error.to_string(),
            },
        )?;
    lifecycle_close
        .ensure_no_live_descendants()
        .await
        .map_err(
            |error| ExperimentalSessionControlError::UnexpectedTeamError {
                message: error.to_string(),
            },
        )?;
    let team_close = agent_control
        .team()
        .begin_close_at_snapshot(expected_owner_incarnation_id, precondition)
        .await
        .map_err(|error| match error {
            codex_team_state::TeamDurabilityError::Domain(error) => {
                map_team_error(session.thread_id(), error)
            }
            error => ExperimentalSessionControlError::UnexpectedTeamError {
                message: error.to_string(),
            },
        })?;

    let current = agent_control
        .with_current_running_session_for_formal_shutdown(session.thread_id(), session, || ())
        .await;
    if current.is_none() {
        team_close.abort().await.map_err(|error| {
            ExperimentalSessionControlError::UnexpectedTeamError {
                message: error.to_string(),
            }
        })?;
        lifecycle_close.abort();
        return Err(ExperimentalSessionControlError::OwnerUnavailable {
            thread_id: session.thread_id(),
        });
    }

    Ok(PreparedDurableSessionShutdown {
        lifecycle_close,
        team_close,
    })
}

pub(crate) async fn set_loaded_root_state(
    session: &Session,
    params: ExperimentalSessionControlSetRootStateParams,
) -> Result<ExperimentalSessionControlMutationOutcome, ExperimentalSessionControlError> {
    with_canonical_loaded_root(session, false, move |team, root_thread_id| {
        set_root_state_on_team(team, root_thread_id, params, None)
    })
    .await
}

pub(crate) async fn set_loaded_root_state_at_snapshot(
    session: &Session,
    params: DurableSessionControlSetRootStateParams,
) -> Result<ExperimentalSessionControlMutationOutcome, ExperimentalSessionControlError> {
    let expected_owner_incarnation_id = Uuid::parse_str(&params.owner_incarnation_id)
        .map_err(|_| ExperimentalSessionControlError::OwnerIncarnationConflict)?;
    let instance = TeamInstanceId::from_str(&params.team_instance_id)
        .map_err(|_| ExperimentalSessionControlError::SnapshotConflict)?;
    let precondition = TeamMutationPrecondition {
        instance,
        revision: TeamRevision::from_raw(params.team_revision),
        commit_generation: params.commit_generation,
    };
    let lifecycle = ExperimentalSessionControlSetRootStateParams {
        version_id: params.version_id,
        expected_producer_state: params.expected_producer_state,
        expected_root_state: params.expected_root_state,
        next_root_state: params.next_root_state,
    };
    with_canonical_loaded_root(session, false, move |team, root_thread_id| {
        set_root_state_on_team(
            team,
            root_thread_id,
            lifecycle,
            Some((expected_owner_incarnation_id, precondition)),
        )
    })
    .await
}

fn set_root_state_on_team(
    team: &TeamStateHandle,
    root_thread_id: ThreadId,
    params: ExperimentalSessionControlSetRootStateParams,
    formal_precondition: Option<(Uuid, TeamMutationPrecondition)>,
) -> Result<ExperimentalSessionControlMutationOutcome, ExperimentalSessionControlError> {
    let version_id = VersionId::from_str(&params.version_id).map_err(|_| {
        ExperimentalSessionControlError::InvalidVersionId {
            version_id: params.version_id.clone(),
        }
    })?;
    let before = team
        .snapshot_for(root_thread_id)
        .map_err(|error| map_team_error(root_thread_id, error))?
        .events
        .into_iter()
        .flat_map(|event| event.versions)
        .find(|version| version.id == version_id);
    let request = LifecycleRequest {
        targets: vec![LifecycleTarget {
            version_id,
            expected_producer_state: params.expected_producer_state.into(),
            expected_root_state: params.expected_root_state.into(),
            change: LifecycleChange::SetRootState(params.next_root_state.into()),
        }],
    };
    let outcome = match formal_precondition {
        Some((expected_owner_incarnation_id, precondition)) => team
            .update_lifecycle_at_snapshot_for_owner(
                root_thread_id,
                expected_owner_incarnation_id,
                precondition,
                request,
            ),
        None => team.update_lifecycle(root_thread_id, request),
    }
    .map_err(|error| map_team_error(root_thread_id, error))?;
    let Some(updated_lifecycle) = outcome.updated.first().copied() else {
        return Err(ExperimentalSessionControlError::UnexpectedTeamError {
            message: "single-target lifecycle response omitted its updated snapshot".to_string(),
        });
    };
    let Some(before) = before else {
        return Err(ExperimentalSessionControlError::UnexpectedTeamError {
            message: "successful lifecycle target was absent from the root's pre-mutation view"
                .to_string(),
        });
    };
    let updated_lifecycle: ExperimentalSessionControlLifecycle = updated_lifecycle.into();
    let updated = ExperimentalSessionControlVersion {
        id: updated_lifecycle.version_id,
        author: before.author,
        author_label: before.author_label,
        summary: before.summary,
        producer_state: updated_lifecycle.producer_state,
        root_state: updated_lifecycle.root_state,
        retired: before.retired,
    };
    let projection = project_team(team, root_thread_id)?;

    Ok(ExperimentalSessionControlMutationOutcome {
        mutation_revision: outcome.revision.get(),
        changed: outcome.changed,
        updated,
        projection,
    })
}

async fn with_canonical_loaded_root<T>(
    session: &Session,
    formal_shutdown: bool,
    operation: impl FnOnce(&TeamStateHandle, ThreadId) -> Result<T, ExperimentalSessionControlError>,
) -> Result<T, ExperimentalSessionControlError> {
    let thread_id = session.thread_id();
    let session_id = session.session_id();
    if ThreadId::from(session_id) != thread_id {
        return Err(ExperimentalSessionControlError::NotRootOwner {
            thread_id,
            session_id,
        });
    }

    if session.multi_agent_version() != Some(MultiAgentVersion::V2) {
        return Err(ExperimentalSessionControlError::TeamUnavailable {
            reason: ExperimentalSessionControlTeamUnavailableReason::MultiAgentV2Inactive,
        });
    }
    if !session.get_config().await.multi_agent_v2.team_state_enabled {
        return Err(ExperimentalSessionControlError::TeamUnavailable {
            reason: ExperimentalSessionControlTeamUnavailableReason::TeamStateDisabled,
        });
    }

    // Keep the live-registry proof as the final await and hold its map read lease through the
    // synchronous Team operation. CodexThread holds the matching runtime residency read lease, so
    // explicit shutdown cannot begin between this proof and the operation.
    let agent_control: &AgentControl = &session.services.agent_control;
    let team = Arc::clone(agent_control.team());
    let operation = move || {
        let participant = team
            .participant(thread_id)
            .ok_or(ExperimentalSessionControlError::OwnerIdentityUnavailable { thread_id })?;
        if participant.role != ParticipantRole::Root {
            return Err(ExperimentalSessionControlError::NotRootParticipant { thread_id });
        }
        operation(team.as_ref(), thread_id)
    };
    let result = if formal_shutdown {
        agent_control
            .with_current_running_session_for_formal_shutdown(thread_id, session, operation)
            .await
    } else {
        agent_control
            .with_current_running_session(thread_id, session, operation)
            .await
    };
    result.unwrap_or(Err(ExperimentalSessionControlError::OwnerUnavailable {
        thread_id,
    }))
}

fn project_team(
    team: &TeamStateHandle,
    root_thread_id: ThreadId,
) -> Result<ExperimentalSessionControlTeamProjection, ExperimentalSessionControlError> {
    let snapshot = team
        .snapshot_for(root_thread_id)
        .map_err(|error| map_team_error(root_thread_id, error))?;
    if snapshot.viewer != root_thread_id || snapshot.viewer_role != ParticipantRole::Root {
        return Err(ExperimentalSessionControlError::NotRootParticipant {
            thread_id: root_thread_id,
        });
    }

    Ok(bounded_projection(team, snapshot, root_thread_id))
}

fn bounded_projection(
    team: &TeamStateHandle,
    snapshot: TeamSnapshot,
    root_thread_id: ThreadId,
) -> ExperimentalSessionControlTeamProjection {
    let mut participants = team.participants();
    if let Some(root_index) = participants
        .iter()
        .position(|participant| participant.thread_id == root_thread_id)
    {
        participants.swap(0, root_index);
    }
    let omitted_participants = participants
        .len()
        .saturating_sub(MAX_PROJECTED_PARTICIPANTS);
    let participants = participants
        .into_iter()
        .take(MAX_PROJECTED_PARTICIPANTS)
        .map(|participant| ExperimentalSessionControlParticipant {
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
                .map(|version| ExperimentalSessionControlVersion {
                    id: version.id.to_string(),
                    author: version.author,
                    author_label: version.author_label,
                    summary: version.summary,
                    producer_state: version.producer_state.into(),
                    root_state: version.root_state.into(),
                    retired: version.retired,
                })
                .collect();
            ExperimentalSessionControlEvent {
                id: event.id.to_string(),
                title: event.title,
                versions,
                omitted_versions,
            }
        })
        .collect();

    ExperimentalSessionControlTeamProjection {
        team_instance: snapshot.instance.to_string(),
        revision: snapshot.revision.get(),
        root_thread_id,
        participants,
        omitted_participants,
        events,
        omitted_events,
    }
}

fn map_team_error(root_thread_id: ThreadId, error: TeamError) -> ExperimentalSessionControlError {
    match error {
        TeamError::UnknownParticipant => {
            ExperimentalSessionControlError::OwnerIdentityUnavailable {
                thread_id: root_thread_id,
            }
        }
        TeamError::InstanceReset {
            referenced_instance,
            current_instance,
        } => ExperimentalSessionControlError::TeamInstanceReset {
            referenced_instance: referenced_instance.to_string(),
            current_instance: current_instance.to_string(),
        },
        TeamError::SnapshotConflict { .. } => ExperimentalSessionControlError::SnapshotConflict,
        TeamError::OwnerIncarnationConflict => {
            ExperimentalSessionControlError::OwnerIncarnationConflict
        }
        TeamError::UnknownReference { reference } => {
            ExperimentalSessionControlError::UnknownReference { reference }
        }
        TeamError::MalformedReference { reference } => {
            ExperimentalSessionControlError::MalformedReference { reference }
        }
        TeamError::NotPermitted { reason } => ExperimentalSessionControlError::NotPermitted {
            reason: reason.to_string(),
        },
        TeamError::LifecycleConflict { current } => {
            ExperimentalSessionControlError::LifecycleConflict {
                current: current.into(),
            }
        }
        TeamError::VersionClosed { version_id } => ExperimentalSessionControlError::VersionClosed {
            version_id: version_id.to_string(),
        },
        TeamError::InvalidRequest { reason } => ExperimentalSessionControlError::InvalidRequest {
            reason: reason.to_string(),
        },
        TeamError::RootAttentionResolved { version_id } => {
            ExperimentalSessionControlError::RootAttentionResolved {
                version_id: version_id.to_string(),
            }
        }
        TeamError::ConflictingTargets { version_id } => {
            ExperimentalSessionControlError::ConflictingTargets {
                version_id: version_id.to_string(),
            }
        }
        TeamError::VersionRetired { version_id } => {
            ExperimentalSessionControlError::VersionRetired {
                version_id: version_id.to_string(),
            }
        }
        unexpected => ExperimentalSessionControlError::UnexpectedTeamError {
            message: unexpected.to_string(),
        },
    }
}

impl From<ParticipantRole> for ExperimentalSessionControlTeamRole {
    fn from(value: ParticipantRole) -> Self {
        match value {
            ParticipantRole::Root => Self::Root,
            ParticipantRole::Member => Self::Member,
        }
    }
}

impl From<ProducerState> for ExperimentalSessionControlProducerState {
    fn from(value: ProducerState) -> Self {
        match value {
            ProducerState::Open => Self::Open,
            ProducerState::Closed => Self::Closed,
        }
    }
}

impl From<ExperimentalSessionControlProducerState> for ProducerState {
    fn from(value: ExperimentalSessionControlProducerState) -> Self {
        match value {
            ExperimentalSessionControlProducerState::Open => Self::Open,
            ExperimentalSessionControlProducerState::Closed => Self::Closed,
        }
    }
}

impl From<RootState> for ExperimentalSessionControlRootState {
    fn from(value: RootState) -> Self {
        match value {
            RootState::Pending => Self::Pending,
            RootState::Tracking => Self::Tracking,
            RootState::Resolved => Self::Resolved,
        }
    }
}

impl From<ExperimentalSessionControlRootState> for RootState {
    fn from(value: ExperimentalSessionControlRootState) -> Self {
        match value {
            ExperimentalSessionControlRootState::Pending => Self::Pending,
            ExperimentalSessionControlRootState::Tracking => Self::Tracking,
            ExperimentalSessionControlRootState::Resolved => Self::Resolved,
        }
    }
}

impl From<LifecycleSnapshot> for ExperimentalSessionControlLifecycle {
    fn from(value: LifecycleSnapshot) -> Self {
        Self {
            version_id: value.version_id.to_string(),
            producer_state: value.producer_state.into(),
            root_state: value.root_state.into(),
        }
    }
}

#[cfg(test)]
#[path = "experimental_session_control_tests.rs"]
mod tests;
