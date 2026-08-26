//! Stable Durable Session control boundary.
//!
//! Every attempt re-projects the formal query under the app-server lifecycle permit and compares
//! the exact proof supplied by the caller. This module owns no Session state: online mutations go
//! through the current `CodexThread`, while cold lifecycle operations reuse the existing
//! ThreadStore-backed request processor helpers.

use super::durable_session_query::CanonicalMetaFailure;
use super::durable_session_query::StorageScope;
use super::thread_processor::FormalThreadRemovalError;
use super::*;
use codex_app_server_protocol::DurableSessionControlEffect;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlOperationKind;
use codex_app_server_protocol::DurableSessionControlOutcome;
use codex_app_server_protocol::DurableSessionControlParams;
use codex_app_server_protocol::DurableSessionControlPrecondition;
use codex_app_server_protocol::DurableSessionControlRejectionReason;
use codex_app_server_protocol::DurableSessionControlResponse;
use codex_app_server_protocol::DurableSessionResidency;
use codex_app_server_protocol::DurableSessionStorageStatus;
use codex_app_server_protocol::DurableSessionTeamProducerState;
use codex_app_server_protocol::DurableSessionTeamRootState;
use codex_core::DurableSessionControlSetRootStateParams as CoreSetRootStateParams;
use codex_core::DurableSessionControlShutdownParams as CoreShutdownParams;
use codex_core::ExperimentalSessionControlError as CoreControlError;
use codex_core::ExperimentalSessionControlProducerState as CoreProducerState;
use codex_core::ExperimentalSessionControlRootState as CoreRootState;
use codex_protocol::SessionId;

impl ThreadRequestProcessor {
    pub(crate) async fn durable_session_control(
        &self,
        params: DurableSessionControlParams,
    ) -> Result<Option<ClientResponsePayload>, JSONRPCErrorError> {
        let operation = params.operation.kind();
        if !self.config.features.enabled(Feature::DurableSessionQuery)
            || !self.config.features.enabled(Feature::DurableSessionControl)
        {
            return Ok(Some(rejected(
                operation,
                DurableSessionControlRejectionReason::Unsupported,
                "Durable Session query and control features must both be enabled",
            )));
        }

        let root_thread_id = match ThreadId::from_string(&params.root_thread_id) {
            Ok(value) => value,
            Err(error) => {
                return Ok(Some(rejected(
                    operation,
                    DurableSessionControlRejectionReason::InvalidState,
                    format!("invalid Root thread id: {error}"),
                )));
            }
        };
        let session_id = match SessionId::from_string(&params.session_id) {
            Ok(value) => value,
            Err(error) => {
                return Ok(Some(rejected(
                    operation,
                    DurableSessionControlRejectionReason::InvalidState,
                    format!("invalid Session id: {error}"),
                )));
            }
        };

        let _thread_list_state_permit = self.acquire_thread_list_state_permit().await?;
        let (meta, scope) = match self.read_canonical_meta_anywhere(root_thread_id).await {
            Ok(value) => value,
            Err(error) => {
                return Ok(Some(meta_rejection(operation, error)));
            }
        };
        if meta.parent_thread_id.is_some() {
            return Ok(Some(rejected(
                operation,
                DurableSessionControlRejectionReason::NotCurrentOwner,
                "the requested thread is not a canonical Session Root",
            )));
        }
        let current = self
            .project_authenticated_session(meta, scope, root_thread_id)
            .await;
        if current.identity.session_id != session_id.to_string()
            || current.identity.root_thread_id.as_deref() != Some(params.root_thread_id.as_str())
        {
            return Ok(Some(rejected(
                operation,
                DurableSessionControlRejectionReason::NotCurrentOwner,
                "the supplied Session and Root identities are not the canonical lineage",
            )));
        }
        let Some(current_precondition) = current.control_precondition.as_ref() else {
            return Ok(Some(rejected(
                operation,
                DurableSessionControlRejectionReason::InvalidState,
                "the canonical Session query could not produce a complete control proof",
            )));
        };
        if current_precondition != &params.precondition {
            let reason = if precondition_storage(current_precondition)
                != precondition_storage(&params.precondition)
            {
                DurableSessionControlRejectionReason::WrongStorage
            } else if precondition_residency(current_precondition)
                != precondition_residency(&params.precondition)
                || owner_incarnation_changed(current_precondition, &params.precondition)
            {
                DurableSessionControlRejectionReason::NotCurrentOwner
            } else {
                DurableSessionControlRejectionReason::StalePrecondition
            };
            return Ok(Some(rejected(
                operation,
                reason,
                "the canonical Session changed after the control view was read",
            )));
        }
        if matches!(
            &params.precondition,
            DurableSessionControlPrecondition::DeleteRetryAnchor { .. }
        ) && operation != DurableSessionControlOperationKind::Delete
        {
            return Ok(Some(rejected(
                operation,
                DurableSessionControlRejectionReason::InvalidState,
                "a delete retry anchor can authorize only an explicit delete attempt",
            )));
        }

        if let Some(hook) = &self.durable_session_control_preflight_hook {
            hook(root_thread_id, operation).await;
        }

        let outcome = match params.operation {
            DurableSessionControlOperation::SetRootState {
                version_id,
                expected_producer_state,
                expected_root_state,
                next_root_state,
            } => {
                if !matches!(scope, StorageScope::Active)
                    || current.residency != DurableSessionResidency::ObservedOwnerHere
                {
                    DurableSessionControlOutcome::Rejected {
                        operation,
                        reason: DurableSessionControlRejectionReason::OwnerUnavailable,
                        message: "root-state control requires the current loaded Root owner"
                            .to_string(),
                    }
                } else {
                    let DurableSessionControlPrecondition::CommittedTeam {
                        team_instance_id,
                        team_revision,
                        commit_generation,
                        owner_incarnation: Some(owner_incarnation),
                        ..
                    } = &params.precondition
                    else {
                        return Ok(Some(rejected(
                            operation,
                            DurableSessionControlRejectionReason::NotCurrentOwner,
                            "loaded Root control requires an owner-incarnation proof",
                        )));
                    };
                    self.control_set_root_state(
                        root_thread_id,
                        team_instance_id,
                        *team_revision,
                        *commit_generation,
                        owner_incarnation,
                        version_id,
                        expected_producer_state,
                        expected_root_state,
                        next_root_state,
                    )
                    .await
                }
            }
            DurableSessionControlOperation::Close => {
                if !matches!(scope, StorageScope::Active)
                    || current.residency != DurableSessionResidency::ObservedOwnerHere
                {
                    rejected_outcome(
                        operation,
                        DurableSessionControlRejectionReason::OwnerUnavailable,
                        "close requires the current loaded Root owner",
                    )
                } else {
                    match self
                        .control_shutdown_loaded_root_at_snapshot(
                            root_thread_id,
                            &params.precondition,
                            operation,
                        )
                        .await
                    {
                        Ok(()) => DurableSessionControlOutcome::Applied {
                            effect: DurableSessionControlEffect::OwnerClosed,
                        },
                        Err(outcome) => outcome,
                    }
                }
            }
            DurableSessionControlOperation::Archive => {
                if current.storage_status != DurableSessionStorageStatus::Active {
                    rejected_outcome(
                        operation,
                        DurableSessionControlRejectionReason::WrongStorage,
                        "only an active Session can be archived",
                    )
                } else if !matches!(
                    current.residency,
                    DurableSessionResidency::ObservedOwnerHere
                        | DurableSessionResidency::NotObservedHere
                ) {
                    rejected_outcome(
                        operation,
                        DurableSessionControlRejectionReason::OwnerUnavailable,
                        "archive requires either the current loaded Root owner or a cold Root",
                    )
                } else if current.residency == DurableSessionResidency::ObservedOwnerHere
                    && let Err(outcome) = self
                        .control_shutdown_loaded_root_at_snapshot(
                            root_thread_id,
                            &params.precondition,
                            operation,
                        )
                        .await
                {
                    outcome
                } else {
                    match self
                        .thread_archive_response(ThreadArchiveParams {
                            thread_id: params.root_thread_id.clone(),
                        })
                        .await
                    {
                        Ok((_, affected_thread_ids)) => {
                            for thread_id in &affected_thread_ids {
                                self.outgoing
                                    .send_server_notification(ServerNotification::ThreadArchived(
                                        ThreadArchivedNotification {
                                            thread_id: thread_id.clone(),
                                        },
                                    ))
                                    .await;
                            }
                            DurableSessionControlOutcome::Applied {
                                effect: DurableSessionControlEffect::Archived {
                                    affected_thread_ids,
                                },
                            }
                        }
                        Err(error) => lifecycle_error(operation, error),
                    }
                }
            }
            DurableSessionControlOperation::Unarchive => {
                if current.storage_status != DurableSessionStorageStatus::Archived {
                    rejected_outcome(
                        operation,
                        DurableSessionControlRejectionReason::WrongStorage,
                        "only an archived Session can be unarchived",
                    )
                } else {
                    match self
                        .thread_unarchive_response(ThreadUnarchiveParams {
                            thread_id: params.root_thread_id.clone(),
                        })
                        .await
                    {
                        Ok((_, thread_id)) => {
                            self.outgoing
                                .send_server_notification(ServerNotification::ThreadUnarchived(
                                    ThreadUnarchivedNotification { thread_id },
                                ))
                                .await;
                            DurableSessionControlOutcome::Applied {
                                effect: DurableSessionControlEffect::Unarchived,
                            }
                        }
                        Err(error) => lifecycle_error(operation, error),
                    }
                }
            }
            DurableSessionControlOperation::Delete => {
                if !matches!(
                    current.residency,
                    DurableSessionResidency::ObservedOwnerHere
                        | DurableSessionResidency::NotObservedHere
                ) {
                    rejected_outcome(
                        operation,
                        DurableSessionControlRejectionReason::OwnerUnavailable,
                        "delete requires either the current loaded Root owner or a cold Root",
                    )
                } else if current.residency == DurableSessionResidency::ObservedOwnerHere
                    && let Err(outcome) = self
                        .control_shutdown_loaded_root_at_snapshot(
                            root_thread_id,
                            &params.precondition,
                            operation,
                        )
                        .await
                {
                    outcome
                } else {
                    let mut affected_thread_ids = Vec::new();
                    match self
                        .thread_delete_response(
                            ThreadDeleteParams {
                                thread_id: params.root_thread_id,
                            },
                            &mut affected_thread_ids,
                        )
                        .await
                    {
                        Ok(_) => {
                            self.send_thread_deleted_notifications(affected_thread_ids.clone())
                                .await;
                            DurableSessionControlOutcome::Applied {
                                effect: DurableSessionControlEffect::Deleted {
                                    affected_thread_ids,
                                },
                            }
                        }
                        Err(error) => lifecycle_error(operation, error),
                    }
                }
            }
        };

        Ok(Some(DurableSessionControlResponse { outcome }.into()))
    }

    #[allow(clippy::too_many_arguments)]
    async fn control_set_root_state(
        &self,
        root_thread_id: ThreadId,
        team_instance_id: &str,
        team_revision: u64,
        commit_generation: u64,
        owner_incarnation: &str,
        version_id: String,
        expected_producer_state: DurableSessionTeamProducerState,
        expected_root_state: DurableSessionTeamRootState,
        next_root_state: DurableSessionTeamRootState,
    ) -> DurableSessionControlOutcome {
        let thread = match self.thread_manager.get_thread(root_thread_id).await {
            Ok(thread) => thread,
            Err(_) => {
                return rejected_outcome(
                    DurableSessionControlOperationKind::SetRootState,
                    DurableSessionControlRejectionReason::OwnerUnavailable,
                    "the loaded Root owner disappeared before mutation",
                );
            }
        };
        match thread.durable_session_control_owner_incarnation_id().await {
            Ok(current) if current == owner_incarnation => {}
            Ok(_) | Err(_) => {
                return rejected_outcome(
                    DurableSessionControlOperationKind::SetRootState,
                    DurableSessionControlRejectionReason::NotCurrentOwner,
                    "the loaded Root writer incarnation changed before mutation",
                );
            }
        }
        match thread
            .durable_session_control_set_root_state(CoreSetRootStateParams {
                owner_incarnation_id: owner_incarnation.to_string(),
                team_instance_id: team_instance_id.to_string(),
                team_revision,
                commit_generation,
                version_id,
                expected_producer_state: core_producer_state(expected_producer_state),
                expected_root_state: core_root_state(expected_root_state),
                next_root_state: core_root_state(next_root_state),
            })
            .await
        {
            Ok(outcome) => DurableSessionControlOutcome::Applied {
                effect: DurableSessionControlEffect::RootStateUpdated {
                    changed: outcome.changed,
                    mutation_revision: outcome.mutation_revision,
                },
            },
            Err(error) => {
                core_control_outcome(DurableSessionControlOperationKind::SetRootState, error)
            }
        }
    }

    async fn control_shutdown_loaded_root_at_snapshot(
        &self,
        root_thread_id: ThreadId,
        precondition: &DurableSessionControlPrecondition,
        operation: DurableSessionControlOperationKind,
    ) -> Result<(), DurableSessionControlOutcome> {
        let DurableSessionControlPrecondition::CommittedTeam {
            owner_incarnation: Some(owner_incarnation),
            team_instance_id,
            team_revision,
            commit_generation,
            ..
        } = precondition
        else {
            return Err(rejected_outcome(
                operation,
                DurableSessionControlRejectionReason::NotCurrentOwner,
                "loaded Root lifecycle control requires an owner-incarnation proof",
            ));
        };
        self.prepare_thread_for_removal_at_snapshot(
            root_thread_id,
            CoreShutdownParams {
                owner_incarnation_id: owner_incarnation.clone(),
                team_instance_id: team_instance_id.clone(),
                team_revision: *team_revision,
                commit_generation: *commit_generation,
            },
        )
        .await
        .map_err(|error| formal_removal_outcome(operation, error))
    }
}

fn precondition_storage(
    precondition: &DurableSessionControlPrecondition,
) -> DurableSessionStorageStatus {
    match precondition {
        DurableSessionControlPrecondition::CommittedTeam {
            expected_storage_status,
            ..
        }
        | DurableSessionControlPrecondition::DeleteRetryAnchor {
            expected_storage_status,
            ..
        } => *expected_storage_status,
    }
}

fn precondition_residency(
    precondition: &DurableSessionControlPrecondition,
) -> DurableSessionResidency {
    match precondition {
        DurableSessionControlPrecondition::CommittedTeam {
            expected_residency, ..
        }
        | DurableSessionControlPrecondition::DeleteRetryAnchor {
            expected_residency, ..
        } => *expected_residency,
    }
}

fn owner_incarnation_changed(
    current: &DurableSessionControlPrecondition,
    supplied: &DurableSessionControlPrecondition,
) -> bool {
    match (current, supplied) {
        (
            DurableSessionControlPrecondition::CommittedTeam {
                owner_incarnation: current,
                ..
            },
            DurableSessionControlPrecondition::CommittedTeam {
                owner_incarnation: supplied,
                ..
            },
        ) => current != supplied,
        _ => false,
    }
}

fn rejected(
    operation: DurableSessionControlOperationKind,
    reason: DurableSessionControlRejectionReason,
    message: impl Into<String>,
) -> ClientResponsePayload {
    DurableSessionControlResponse {
        outcome: rejected_outcome(operation, reason, message),
    }
    .into()
}

fn rejected_outcome(
    operation: DurableSessionControlOperationKind,
    reason: DurableSessionControlRejectionReason,
    message: impl Into<String>,
) -> DurableSessionControlOutcome {
    DurableSessionControlOutcome::Rejected {
        operation,
        reason,
        message: message.into(),
    }
}

fn unknown_outcome(
    operation: DurableSessionControlOperationKind,
    message: impl Into<String>,
) -> DurableSessionControlOutcome {
    DurableSessionControlOutcome::Unknown {
        operation,
        message: message.into(),
    }
}

fn meta_rejection(
    operation: DurableSessionControlOperationKind,
    error: CanonicalMetaFailure,
) -> ClientResponsePayload {
    let (reason, message) = match error {
        CanonicalMetaFailure::NotFound => (
            DurableSessionControlRejectionReason::NotFound,
            "the canonical Session was not found",
        ),
        CanonicalMetaFailure::Unsupported => (
            DurableSessionControlRejectionReason::Unsupported,
            "the Session store does not support canonical control reads",
        ),
        CanonicalMetaFailure::IdentityMismatch => (
            DurableSessionControlRejectionReason::NotCurrentOwner,
            "the canonical Session identity does not match the requested Root",
        ),
        CanonicalMetaFailure::Unavailable
        | CanonicalMetaFailure::Corrupt
        | CanonicalMetaFailure::SourceChanged => (
            DurableSessionControlRejectionReason::Conflict,
            "the canonical Session proof is unavailable or changed",
        ),
    };
    rejected(operation, reason, message)
}

fn lifecycle_error(
    operation: DurableSessionControlOperationKind,
    error: JSONRPCErrorError,
) -> DurableSessionControlOutcome {
    if let Some(data) = error.data.as_ref()
        && data.get("type").and_then(serde_json::Value::as_str) == Some("partial")
    {
        let completed_thread_ids = data
            .get("completedThreadIds")
            .and_then(serde_json::Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(serde_json::Value::as_str)
            .map(ToString::to_string)
            .collect();
        return DurableSessionControlOutcome::Partial {
            operation,
            completed_thread_ids,
            message: error.message,
        };
    }
    unknown_outcome(operation, error.message)
}

fn core_control_outcome(
    operation: DurableSessionControlOperationKind,
    error: CoreControlError,
) -> DurableSessionControlOutcome {
    match error {
        CoreControlError::SnapshotConflict
        | CoreControlError::LifecycleConflict { .. }
        | CoreControlError::TeamInstanceReset { .. } => rejected_outcome(
            operation,
            DurableSessionControlRejectionReason::StalePrecondition,
            error.to_string(),
        ),
        CoreControlError::OwnerIncarnationConflict
        | CoreControlError::OwnerUnavailable { .. }
        | CoreControlError::NotRootOwner { .. }
        | CoreControlError::NotRootParticipant { .. }
        | CoreControlError::OwnerIdentityUnavailable { .. } => rejected_outcome(
            operation,
            DurableSessionControlRejectionReason::NotCurrentOwner,
            error.to_string(),
        ),
        CoreControlError::InvalidVersionId { .. }
        | CoreControlError::UnknownReference { .. }
        | CoreControlError::MalformedReference { .. }
        | CoreControlError::NotPermitted { .. }
        | CoreControlError::VersionClosed { .. }
        | CoreControlError::InvalidRequest { .. }
        | CoreControlError::RootAttentionResolved { .. }
        | CoreControlError::ConflictingTargets { .. }
        | CoreControlError::VersionRetired { .. }
        | CoreControlError::TeamUnavailable { .. } => rejected_outcome(
            operation,
            DurableSessionControlRejectionReason::InvalidState,
            error.to_string(),
        ),
        CoreControlError::UnexpectedTeamError { message }
        | CoreControlError::ShutdownHandoff { message }
        | CoreControlError::ShutdownTerminatedWithError { message } => {
            unknown_outcome(operation, message)
        }
    }
}

fn formal_removal_outcome(
    operation: DurableSessionControlOperationKind,
    error: FormalThreadRemovalError,
) -> DurableSessionControlOutcome {
    match error {
        FormalThreadRemovalError::AlreadyClosing => rejected_outcome(
            operation,
            DurableSessionControlRejectionReason::Conflict,
            "the Root owner already has a lifecycle operation in progress",
        ),
        FormalThreadRemovalError::OwnerUnavailable => rejected_outcome(
            operation,
            DurableSessionControlRejectionReason::OwnerUnavailable,
            "the loaded Root owner disappeared before lifecycle control",
        ),
        FormalThreadRemovalError::Control(error) => core_control_outcome(operation, error),
        FormalThreadRemovalError::Replaced => unknown_outcome(
            operation,
            "the snapshot-bound shutdown completed but the Root owner was replaced before removal",
        ),
    }
}

fn core_producer_state(value: DurableSessionTeamProducerState) -> CoreProducerState {
    match value {
        DurableSessionTeamProducerState::Open => CoreProducerState::Open,
        DurableSessionTeamProducerState::Closed => CoreProducerState::Closed,
    }
}

fn core_root_state(value: DurableSessionTeamRootState) -> CoreRootState {
    match value {
        DurableSessionTeamRootState::Pending => CoreRootState::Pending,
        DurableSessionTeamRootState::Tracking => CoreRootState::Tracking,
        DurableSessionTeamRootState::Resolved => CoreRootState::Resolved,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepted_shutdown_terminal_error_maps_to_typed_unknown() {
        let outcome = core_control_outcome(
            DurableSessionControlOperationKind::Close,
            CoreControlError::ShutdownTerminatedWithError {
                message: "accepted shutdown terminated without a known final result".to_string(),
            },
        );

        assert!(matches!(
            outcome,
            DurableSessionControlOutcome::Unknown {
                operation: DurableSessionControlOperationKind::Close,
                message,
            } if message.contains("without a known final result")
        ));
    }
}
