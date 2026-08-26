//! Wire projection for the formal Durable Session query.

use super::StorageScope;
use codex_app_server_protocol::DurableSessionControlPrecondition;
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
use sha2::Digest;
use sha2::Sha256;

pub(super) fn authenticated_view(
    meta: &SessionMeta,
    scope: StorageScope,
    read_status: DurableSessionReadStatus,
    residency: DurableSessionResidency,
    team: Option<DurableSessionTeamProjection>,
    control_enabled: bool,
    owner_incarnation: Option<String>,
) -> DurableSessionView {
    let read_available = matches!(&read_status, DurableSessionReadStatus::Available);
    let team_available = team.is_some();
    let control_precondition = (control_enabled && read_available)
        .then(|| {
            let team = team.as_ref()?;
            if residency == DurableSessionResidency::ObservedOwnerHere
                && owner_incarnation.is_none()
            {
                return None;
            }
            Some(DurableSessionControlPrecondition::CommittedTeam {
                expected_storage_status: scope.status(),
                expected_residency: residency,
                owner_incarnation,
                team_instance_id: team.team_instance_id.clone(),
                team_revision: team.revision,
                commit_generation: team.commit_generation,
                commit_fingerprint: team.commit_fingerprint.clone(),
            })
        })
        .flatten();
    DurableSessionView {
        identity: DurableSessionIdentity {
            session_id: meta.session_id.to_string(),
            root_thread_id: Some(meta.id.to_string()),
        },
        storage_status: scope.status(),
        domain_lifecycle: DurableSessionDomainLifecycle::Unknown,
        residency,
        operation_availability: operations(scope, read_available, residency, control_enabled),
        control_precondition,
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

/// Project the one intentional incomplete-read recovery case: an earlier delete proved the
/// canonical durable Root marker but already removed its Team snapshot. The marker remains the
/// existing ThreadStore retry anchor; no lifecycle state is inferred or persisted here.
pub(super) fn authenticated_delete_retry_view(
    meta: &SessionMeta,
    scope: StorageScope,
    residency: DurableSessionResidency,
    control_enabled: bool,
) -> DurableSessionView {
    let delete_retry_available = control_enabled
        && residency == DurableSessionResidency::NotObservedHere
        && meta.parent_thread_id.is_none();
    let control_precondition =
        delete_retry_available.then(|| DurableSessionControlPrecondition::DeleteRetryAnchor {
            expected_storage_status: scope.status(),
            expected_residency: residency,
            root_marker_fingerprint: root_marker_fingerprint(meta),
        });
    let mut operation_availability = if control_enabled {
        unknown_operations(DurableSessionOperationAvailabilityReason::ReadIncomplete)
    } else {
        unavailable_operations(DurableSessionOperationAvailabilityReason::ControlDisabled)
    };
    if delete_retry_available {
        operation_availability.delete = operation(
            DurableSessionOperationAvailability::Available,
            DurableSessionFactProvenance::ThreadStore,
        );
    }
    DurableSessionView {
        identity: DurableSessionIdentity {
            session_id: meta.session_id.to_string(),
            root_thread_id: Some(meta.id.to_string()),
        },
        storage_status: scope.status(),
        domain_lifecycle: DurableSessionDomainLifecycle::Unknown,
        residency,
        operation_availability,
        control_precondition,
        provenance: DurableSessionProvenance {
            identity: DurableSessionFactProvenance::SessionMeta,
            storage_status: DurableSessionFactProvenance::ThreadStore,
            domain_lifecycle: DurableSessionFactProvenance::Unavailable,
            residency: DurableSessionFactProvenance::ServerRuntimeObservation,
            team: DurableSessionFactProvenance::Unavailable,
        },
        read_status: DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotMissing,
        },
        team: None,
    }
}

fn root_marker_fingerprint(meta: &SessionMeta) -> String {
    let mut digest = Sha256::new();
    digest.update(b"RONDO-DURABLE-ROOT-MARKER\0v1\0");
    update_fingerprint_component(&mut digest, meta.session_id.to_string().as_bytes());
    update_fingerprint_component(&mut digest, meta.id.to_string().as_bytes());
    update_fingerprint_component(&mut digest, meta.timestamp.as_bytes());
    if let Some(intent) = meta.durable_team {
        digest.update(intent.version.to_be_bytes());
        update_fingerprint_component(&mut digest, intent.session_id.to_string().as_bytes());
        update_fingerprint_component(&mut digest, intent.root_thread_id.to_string().as_bytes());
    }
    format!("sha256:{:x}", digest.finalize())
}

fn update_fingerprint_component(digest: &mut Sha256, value: &[u8]) {
    digest.update(u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    digest.update(value);
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
        control_precondition: None,
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

fn operations(
    scope: StorageScope,
    read_available: bool,
    residency: DurableSessionResidency,
    control_enabled: bool,
) -> DurableSessionOperations {
    if !read_available {
        return unknown_operations(DurableSessionOperationAvailabilityReason::ReadIncomplete);
    }
    if !control_enabled {
        return unavailable_operations(DurableSessionOperationAvailabilityReason::ControlDisabled);
    }
    let available = || {
        operation(
            DurableSessionOperationAvailability::Available,
            DurableSessionFactProvenance::DerivedPolicy,
        )
    };
    let (resume, set_root_state, close, archive, unarchive) = match scope {
        StorageScope::Active => (
            match residency {
                DurableSessionResidency::NotObservedHere => available(),
                DurableSessionResidency::ObservedOwnerHere => operation(
                    DurableSessionOperationAvailability::Unavailable {
                        reason: DurableSessionOperationAvailabilityReason::AlreadyLoaded,
                    },
                    DurableSessionFactProvenance::ServerRuntimeObservation,
                ),
                DurableSessionResidency::OwnerUnavailableHere => operation(
                    DurableSessionOperationAvailability::Unavailable {
                        reason: DurableSessionOperationAvailabilityReason::OwnerUnavailableHere,
                    },
                    DurableSessionFactProvenance::ServerRuntimeObservation,
                ),
                DurableSessionResidency::Unknown => operation(
                    DurableSessionOperationAvailability::Unknown {
                        reason: DurableSessionOperationAvailabilityReason::ResidencyUnknown,
                    },
                    DurableSessionFactProvenance::ServerRuntimeObservation,
                ),
            },
            owner_operation(residency),
            owner_operation(residency),
            available(),
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
                    reason: DurableSessionOperationAvailabilityReason::Unsupported,
                },
                DurableSessionFactProvenance::ThreadStore,
            ),
            operation(
                DurableSessionOperationAvailability::Unavailable {
                    reason: DurableSessionOperationAvailabilityReason::NotObservedHere,
                },
                DurableSessionFactProvenance::ThreadStore,
            ),
            operation(
                DurableSessionOperationAvailability::Unavailable {
                    reason: DurableSessionOperationAvailabilityReason::NotObservedHere,
                },
                DurableSessionFactProvenance::ThreadStore,
            ),
            operation(
                DurableSessionOperationAvailability::Unavailable {
                    reason: DurableSessionOperationAvailabilityReason::AlreadyArchived,
                },
                DurableSessionFactProvenance::ThreadStore,
            ),
            available(),
        ),
    };
    DurableSessionOperations {
        resume,
        set_root_state,
        close,
        archive,
        unarchive,
        delete: available(),
    }
}

fn owner_operation(residency: DurableSessionResidency) -> DurableSessionOperation {
    match residency {
        DurableSessionResidency::ObservedOwnerHere => operation(
            DurableSessionOperationAvailability::Available,
            DurableSessionFactProvenance::ServerRuntimeObservation,
        ),
        DurableSessionResidency::OwnerUnavailableHere => operation(
            DurableSessionOperationAvailability::Unavailable {
                reason: DurableSessionOperationAvailabilityReason::OwnerUnavailableHere,
            },
            DurableSessionFactProvenance::ServerRuntimeObservation,
        ),
        DurableSessionResidency::NotObservedHere => operation(
            DurableSessionOperationAvailability::Unavailable {
                reason: DurableSessionOperationAvailabilityReason::NotObservedHere,
            },
            DurableSessionFactProvenance::ServerRuntimeObservation,
        ),
        DurableSessionResidency::Unknown => operation(
            DurableSessionOperationAvailability::Unknown {
                reason: DurableSessionOperationAvailabilityReason::ResidencyUnknown,
            },
            DurableSessionFactProvenance::ServerRuntimeObservation,
        ),
    }
}

fn unavailable_operations(
    reason: DurableSessionOperationAvailabilityReason,
) -> DurableSessionOperations {
    let unavailable = || {
        operation(
            DurableSessionOperationAvailability::Unavailable { reason },
            DurableSessionFactProvenance::DerivedPolicy,
        )
    };
    DurableSessionOperations {
        resume: unavailable(),
        set_root_state: unavailable(),
        close: unavailable(),
        archive: unavailable(),
        unarchive: unavailable(),
        delete: unavailable(),
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
        set_root_state: unknown(),
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
