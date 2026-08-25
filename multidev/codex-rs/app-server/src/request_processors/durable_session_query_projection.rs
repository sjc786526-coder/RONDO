//! Wire projection for the formal Durable Session query.

use super::StorageScope;
use codex_app_server_protocol::DurableSessionDomainLifecycle;
use codex_app_server_protocol::DurableSessionFactProvenance;
use codex_app_server_protocol::DurableSessionIdentity;
use codex_app_server_protocol::DurableSessionOperation;
use codex_app_server_protocol::DurableSessionOperationAvailability;
use codex_app_server_protocol::DurableSessionOperationAvailabilityReason;
use codex_app_server_protocol::DurableSessionOperations;
use codex_app_server_protocol::DurableSessionProvenance;
use codex_app_server_protocol::DurableSessionReadIssue;
use codex_app_server_protocol::DurableSessionReadStatus;
use codex_app_server_protocol::DurableSessionResidency;
use codex_app_server_protocol::DurableSessionStorageStatus;
use codex_app_server_protocol::DurableSessionTeamEventProjection;
use codex_app_server_protocol::DurableSessionTeamParticipantProjection;
use codex_app_server_protocol::DurableSessionTeamProducerState as ApiProducerState;
use codex_app_server_protocol::DurableSessionTeamProjection;
use codex_app_server_protocol::DurableSessionTeamRole as ApiTeamRole;
use codex_app_server_protocol::DurableSessionTeamRootState as ApiRootState;
use codex_app_server_protocol::DurableSessionTeamVersionProjection;
use codex_app_server_protocol::DurableSessionTeamViewer;
use codex_app_server_protocol::DurableSessionView;
use codex_core::DurableSessionProducerState as CoreProducerState;
use codex_core::DurableSessionReadError as CoreReadError;
use codex_core::DurableSessionRootState as CoreRootState;
use codex_core::DurableSessionTeamProjection as CoreTeamProjection;
use codex_core::DurableSessionTeamRole as CoreTeamRole;
use codex_protocol::SessionId;
use codex_protocol::protocol::SessionMeta;

pub(super) fn authenticated_view(
    meta: &SessionMeta,
    scope: StorageScope,
    read_status: DurableSessionReadStatus,
    residency: DurableSessionResidency,
    team: Option<DurableSessionTeamProjection>,
) -> DurableSessionView {
    let read_available = matches!(&read_status, DurableSessionReadStatus::Available);
    let team_available = team.is_some();
    DurableSessionView {
        identity: DurableSessionIdentity {
            session_id: meta.session_id.to_string(),
            root_thread_id: Some(meta.id.to_string()),
        },
        storage_status: scope.status(),
        domain_lifecycle: DurableSessionDomainLifecycle::Unknown,
        residency,
        operation_availability: operations(scope, read_available),
        provenance: DurableSessionProvenance {
            identity: DurableSessionFactProvenance::SessionMeta,
            storage_status: DurableSessionFactProvenance::ThreadStore,
            domain_lifecycle: DurableSessionFactProvenance::Unavailable,
            residency: DurableSessionFactProvenance::ServerRuntimeObservation,
            team: if team_available {
                DurableSessionFactProvenance::CommittedTeamSnapshot
            } else {
                DurableSessionFactProvenance::Unavailable
            },
        },
        read_status,
        team,
    }
}

pub(super) fn unavailable_view(
    session_id: SessionId,
    read_status: DurableSessionReadStatus,
) -> DurableSessionView {
    DurableSessionView {
        identity: DurableSessionIdentity {
            // This is the normalized request locator, not an authenticated identity. Provenance
            // remains unavailable and the Root identity is deliberately absent.
            session_id: session_id.to_string(),
            root_thread_id: None,
        },
        storage_status: DurableSessionStorageStatus::Unknown,
        domain_lifecycle: DurableSessionDomainLifecycle::Unknown,
        residency: DurableSessionResidency::Unknown,
        operation_availability: unknown_operations(
            DurableSessionOperationAvailabilityReason::IdentityUnavailable,
        ),
        provenance: DurableSessionProvenance {
            identity: DurableSessionFactProvenance::Unavailable,
            storage_status: DurableSessionFactProvenance::Unavailable,
            domain_lifecycle: DurableSessionFactProvenance::Unavailable,
            residency: DurableSessionFactProvenance::Unavailable,
            team: DurableSessionFactProvenance::Unavailable,
        },
        read_status,
        team: None,
    }
}

fn operations(scope: StorageScope, read_available: bool) -> DurableSessionOperations {
    if !read_available {
        return unknown_operations(DurableSessionOperationAvailabilityReason::ReadIncomplete);
    }
    let unknown = || {
        operation(
            DurableSessionOperationAvailability::Unknown {
                reason: DurableSessionOperationAvailabilityReason::Unsupported,
            },
            DurableSessionFactProvenance::Unavailable,
        )
    };
    let (archive, unarchive) = match scope {
        StorageScope::Active => (
            unknown(),
            operation(
                DurableSessionOperationAvailability::Unavailable {
                    reason: DurableSessionOperationAvailabilityReason::NotArchived,
                },
                DurableSessionFactProvenance::ThreadStore,
            ),
        ),
        StorageScope::Archived => (
            operation(
                DurableSessionOperationAvailability::Unavailable {
                    reason: DurableSessionOperationAvailabilityReason::AlreadyArchived,
                },
                DurableSessionFactProvenance::ThreadStore,
            ),
            unknown(),
        ),
    };
    DurableSessionOperations {
        resume: unknown(),
        close: operation(
            DurableSessionOperationAvailability::Unknown {
                reason: DurableSessionOperationAvailabilityReason::LifecycleUnknown,
            },
            DurableSessionFactProvenance::Unavailable,
        ),
        archive,
        unarchive,
        delete: unknown(),
    }
}

fn unknown_operations(
    reason: DurableSessionOperationAvailabilityReason,
) -> DurableSessionOperations {
    let unknown = || {
        operation(
            DurableSessionOperationAvailability::Unknown { reason },
            DurableSessionFactProvenance::Unavailable,
        )
    };
    DurableSessionOperations {
        resume: unknown(),
        close: unknown(),
        archive: unknown(),
        unarchive: unknown(),
        delete: unknown(),
    }
}

fn operation(
    availability: DurableSessionOperationAvailability,
    provenance: DurableSessionFactProvenance,
) -> DurableSessionOperation {
    DurableSessionOperation {
        availability,
        provenance,
    }
}

pub(super) fn core_read_status(error: CoreReadError) -> DurableSessionReadStatus {
    match error {
        CoreReadError::NotDurable => DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::DurableMarkerMissing,
        },
        CoreReadError::MarkerConflict => DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::DurableMarkerMissing,
        },
        CoreReadError::Unavailable => DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SourceUnavailable,
        },
        CoreReadError::SnapshotMissing => DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotMissing,
        },
        CoreReadError::MarkerUnsupportedVersion { .. } => DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::DurableMarkerIncompatible,
        },
        CoreReadError::MarkerIdentityMismatch => DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::DurableMarkerIdentityMismatch,
        },
        CoreReadError::Conflict | CoreReadError::Indeterminate => {
            DurableSessionReadStatus::Incomplete {
                issue: DurableSessionReadIssue::SourceChanged,
            }
        }
        CoreReadError::Corrupt => DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotCorrupt,
        },
        CoreReadError::UnsupportedVersion { .. } => DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::TeamSnapshotIncompatible,
        },
        CoreReadError::IdentityMismatch | CoreReadError::InvalidTeamState => {
            DurableSessionReadStatus::Incomplete {
                issue: DurableSessionReadIssue::TeamSnapshotValidationFailed,
            }
        }
    }
}

pub(super) fn team_projection(value: CoreTeamProjection) -> DurableSessionTeamProjection {
    DurableSessionTeamProjection {
        team_instance_id: value.team_instance,
        commit_generation: value.commit_generation,
        commit_fingerprint: value.commit_fingerprint,
        revision: value.revision,
        viewer: DurableSessionTeamViewer {
            thread_id: value.root_thread_id.to_string(),
            role: ApiTeamRole::Root,
        },
        participants: value
            .participants
            .into_iter()
            .map(|participant| DurableSessionTeamParticipantProjection {
                thread_id: participant.thread_id.to_string(),
                role: api_team_role(participant.role),
                label: participant.label,
            })
            .collect(),
        omitted_participants: usize_to_u32(value.omitted_participants),
        events: value
            .events
            .into_iter()
            .map(|event| DurableSessionTeamEventProjection {
                event_id: event.id,
                title: event.title,
                versions: event
                    .versions
                    .into_iter()
                    .map(|version| DurableSessionTeamVersionProjection {
                        version_id: version.id,
                        author_thread_id: version.author.to_string(),
                        author_label: version.author_label,
                        summary: version.summary,
                        producer_state: api_producer_state(version.producer_state),
                        root_state: api_root_state(version.root_state),
                        retired: version.retired,
                    })
                    .collect(),
                omitted_versions: usize_to_u32(event.omitted_versions),
            })
            .collect(),
        omitted_events: usize_to_u32(value.omitted_events),
    }
}

fn api_team_role(role: CoreTeamRole) -> ApiTeamRole {
    match role {
        CoreTeamRole::Root => ApiTeamRole::Root,
        CoreTeamRole::Member => ApiTeamRole::Member,
    }
}

fn api_producer_state(state: CoreProducerState) -> ApiProducerState {
    match state {
        CoreProducerState::Open => ApiProducerState::Open,
        CoreProducerState::Closed => ApiProducerState::Closed,
    }
}

fn api_root_state(state: CoreRootState) -> ApiRootState {
    match state {
        CoreRootState::Pending => ApiRootState::Pending,
        CoreRootState::Tracking => ApiRootState::Tracking,
        CoreRootState::Resolved => ApiRootState::Resolved,
    }
}

fn usize_to_u32(value: usize) -> u32 {
    u32::try_from(value).unwrap_or(u32::MAX)
}
