//! Client-side attempt state for formal Durable Session control.
//!
//! [`DurableSessionQueryClientState`] remains the only Session projection. This
//! module only captures one fresh query proof, issues one attempt token, and
//! preserves what can be claimed about its terminal result. It performs no
//! I/O, never retries a mutation, and never installs a mutation response as a
//! Session view.

use crate::DurableSessionQueryAttachment;
use crate::DurableSessionQueryClientState;
use crate::DurableSessionQueryProjection;
use crate::QueryReadTicket;
use crate::QueryViewFreshness;
use codex_app_server_protocol::DurableSessionControlEffect;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlOperationKind;
use codex_app_server_protocol::DurableSessionControlOutcome;
use codex_app_server_protocol::DurableSessionControlParams;
use codex_app_server_protocol::DurableSessionControlPrecondition;
use codex_app_server_protocol::DurableSessionControlRejectionReason;
use codex_app_server_protocol::DurableSessionControlResponse;
use codex_app_server_protocol::DurableSessionOperationAvailability;
use std::error::Error;
use std::fmt;

/// Identifies one explicitly started control attempt.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct DurableSessionControlAttemptTicket(u64);

impl DurableSessionControlAttemptTicket {
    pub fn get(self) -> u64 {
        self.0
    }
}

/// The one request produced when a fresh formal query view is captured.
///
/// Callers should send `params` at most once and retain `ticket` for the
/// corresponding completion. This type intentionally contains no response or
/// projection state.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DurableSessionControlAttempt {
    pub ticket: DurableSessionControlAttemptTicket,
    pub params: DurableSessionControlParams,
}

/// Confirmation-time capture of one fresh formal Session control target.
///
/// A preview is not a sendable request and does not put the attempt state into
/// `Pending`. [`DurableSessionControlAttemptState::begin_attempt`] consumes it
/// and revalidates the captured query read before producing request params.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DurableSessionControlPreview {
    accepted_read_ticket: QueryReadTicket,
    params: DurableSessionControlParams,
}

impl DurableSessionControlPreview {
    pub fn session_id(&self) -> &str {
        &self.params.session_id
    }

    pub fn root_thread_id(&self) -> &str {
        &self.params.root_thread_id
    }

    pub fn operation(&self) -> &DurableSessionControlOperation {
        &self.params.operation
    }
}

/// Why a control attempt could not be captured from the query attachment.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DurableSessionControlCaptureError {
    AttemptPending,
    QueryDisconnected,
    QueryViewNotFresh,
    ReadTicketRetired,
    NotSessionAttachment,
    SessionProjectionMissing,
    SessionProjectionMismatch,
    RootIdentityUnavailable,
    ControlProofUnavailable,
    OperationUnavailable,
}

impl fmt::Display for DurableSessionControlCaptureError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::AttemptPending => "a Durable Session control attempt is already pending",
            Self::QueryDisconnected => "the Durable Session query connection is disconnected",
            Self::QueryViewNotFresh => "Durable Session control requires a fresh session/read",
            Self::ReadTicketRetired => "the confirmed session/read view has been retired",
            Self::NotSessionAttachment => "Durable Session control requires a Session attachment",
            Self::SessionProjectionMissing => {
                "Durable Session control requires a complete Session projection"
            }
            Self::SessionProjectionMismatch => {
                "the Session projection does not match its query attachment"
            }
            Self::RootIdentityUnavailable => {
                "the canonical Durable Session Root identity is unavailable"
            }
            Self::ControlProofUnavailable => {
                "the fresh Session projection has no formal control proof"
            }
            Self::OperationUnavailable => {
                "the requested operation is unavailable in the fresh Session projection"
            }
        })
    }
}

impl Error for DurableSessionControlCaptureError {}

/// What the client can safely claim about the latest formal control attempt.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub enum DurableSessionControlCertainty {
    #[default]
    None,
    Pending {
        operation: DurableSessionControlOperationKind,
    },
    Applied {
        effect: DurableSessionControlEffect,
    },
    Rejected {
        operation: DurableSessionControlOperationKind,
        reason: DurableSessionControlRejectionReason,
        message: String,
    },
    Partial {
        operation: DurableSessionControlOperationKind,
        completed_thread_ids: Vec<String>,
        message: String,
    },
    Unknown {
        operation: DurableSessionControlOperationKind,
        message: String,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct PendingAttempt {
    ticket: DurableSessionControlAttemptTicket,
    session_id: String,
    root_thread_id: String,
    operation: DurableSessionControlOperationKind,
}

/// Thin formal mutation-attempt state bound to the authoritative query state.
#[derive(Clone, Debug, Default)]
pub struct DurableSessionControlAttemptState {
    attempt_generation: u64,
    pending: Option<PendingAttempt>,
    certainty: DurableSessionControlCertainty,
}

impl DurableSessionControlAttemptState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn certainty(&self) -> &DurableSessionControlCertainty {
        &self.certainty
    }

    pub fn pending_ticket(&self) -> Option<DurableSessionControlAttemptTicket> {
        self.pending.as_ref().map(|pending| pending.ticket)
    }

    /// Captures one fresh `session/read` target for a confirmation surface.
    ///
    /// This performs no mutation-state transition. Any intervening refresh,
    /// lag, attachment change, or reconnect retires the returned preview.
    pub fn preview_attempt(
        &self,
        query: &DurableSessionQueryClientState,
        operation: DurableSessionControlOperation,
    ) -> Result<DurableSessionControlPreview, DurableSessionControlCaptureError> {
        if self.pending.is_some() {
            return Err(DurableSessionControlCaptureError::AttemptPending);
        }
        let captured = capture_query(query, None, operation)?;
        Ok(DurableSessionControlPreview {
            accepted_read_ticket: captured.accepted_read_ticket,
            params: captured.params,
        })
    }

    /// Revalidates and consumes a preview, then creates one send-once request.
    ///
    /// Pending is installed only after the preview's read ticket, attachment,
    /// identity, operation availability, and proof all still match the current
    /// authoritative query view.
    pub fn begin_attempt(
        &mut self,
        query: &DurableSessionQueryClientState,
        preview: DurableSessionControlPreview,
    ) -> Result<DurableSessionControlAttempt, DurableSessionControlCaptureError> {
        if self.pending.is_some() {
            return Err(DurableSessionControlCaptureError::AttemptPending);
        }
        let captured = capture_query(
            query,
            Some(preview.accepted_read_ticket),
            preview.params.operation.clone(),
        )?;
        if captured.params != preview.params {
            return Err(DurableSessionControlCaptureError::ReadTicketRetired);
        }
        let operation_kind = captured.params.operation.kind();
        self.attempt_generation = next_generation(self.attempt_generation);
        let ticket = DurableSessionControlAttemptTicket(self.attempt_generation);
        let params = captured.params;
        self.pending = Some(PendingAttempt {
            ticket,
            session_id: params.session_id.clone(),
            root_thread_id: params.root_thread_id.clone(),
            operation: operation_kind,
        });
        self.certainty = DurableSessionControlCertainty::Pending {
            operation: operation_kind,
        };
        Ok(DurableSessionControlAttempt { ticket, params })
    }

    /// Applies one typed server response without deriving or installing a view.
    pub fn apply_response(
        &mut self,
        query: &mut DurableSessionQueryClientState,
        ticket: DurableSessionControlAttemptTicket,
        response: DurableSessionControlResponse,
    ) -> bool {
        let Some(pending) = self.take_current(ticket) else {
            return false;
        };
        self.certainty = match response.outcome {
            DurableSessionControlOutcome::Applied { effect } => {
                DurableSessionControlCertainty::Applied { effect }
            }
            DurableSessionControlOutcome::Rejected {
                operation,
                reason,
                message,
            } => DurableSessionControlCertainty::Rejected {
                operation,
                reason,
                message,
            },
            DurableSessionControlOutcome::Partial {
                operation,
                completed_thread_ids,
                message,
            } => DurableSessionControlCertainty::Partial {
                operation,
                completed_thread_ids,
                message,
            },
            DurableSessionControlOutcome::Unknown { operation, message } => {
                DurableSessionControlCertainty::Unknown { operation, message }
            }
        };
        query.invalidate_after_control_completion(&pending.session_id, &pending.root_thread_id);
        true
    }

    /// Records transport, JSON-RPC, decode, timeout, EOF, or disconnect loss
    /// after submission. The attempt is never replayed automatically.
    pub fn apply_unknown(
        &mut self,
        query: &mut DurableSessionQueryClientState,
        ticket: DurableSessionControlAttemptTicket,
        message: impl Into<String>,
    ) -> bool {
        let Some(pending) = self.take_current(ticket) else {
            return false;
        };
        self.certainty = DurableSessionControlCertainty::Unknown {
            operation: pending.operation,
            message: message.into(),
        };
        query.invalidate_after_control_completion(&pending.session_id, &pending.root_thread_id);
        true
    }

    /// Retires the pending attempt when its connection or attachment is lost.
    pub fn retire_pending_as_unknown(
        &mut self,
        query: &mut DurableSessionQueryClientState,
        message: impl Into<String>,
    ) -> bool {
        let Some(ticket) = self.pending_ticket() else {
            return false;
        };
        self.apply_unknown(query, ticket, message)
    }

    fn take_current(
        &mut self,
        ticket: DurableSessionControlAttemptTicket,
    ) -> Option<PendingAttempt> {
        if self.pending.as_ref().map(|pending| pending.ticket) != Some(ticket) {
            return None;
        }
        self.pending.take()
    }
}

struct CapturedQueryControl {
    accepted_read_ticket: QueryReadTicket,
    params: DurableSessionControlParams,
}

fn capture_query(
    query: &DurableSessionQueryClientState,
    expected_read_ticket: Option<QueryReadTicket>,
    operation: DurableSessionControlOperation,
) -> Result<CapturedQueryControl, DurableSessionControlCaptureError> {
    if !query.is_connected() {
        return Err(DurableSessionControlCaptureError::QueryDisconnected);
    }
    if query.view_freshness() != QueryViewFreshness::Fresh {
        return Err(DurableSessionControlCaptureError::QueryViewNotFresh);
    }
    let accepted_read_ticket = query
        .accepted_read_ticket()
        .ok_or(DurableSessionControlCaptureError::ReadTicketRetired)?;
    if expected_read_ticket.is_some_and(|expected| expected != accepted_read_ticket) {
        return Err(DurableSessionControlCaptureError::ReadTicketRetired);
    }

    let attachment = match query.attachment() {
        Some(DurableSessionQueryAttachment::Session(attachment)) => attachment,
        _ => return Err(DurableSessionControlCaptureError::NotSessionAttachment),
    };
    let response = match query.projection() {
        Some(DurableSessionQueryProjection::Session(response)) => response,
        _ => return Err(DurableSessionControlCaptureError::SessionProjectionMissing),
    };
    if response.session.identity.session_id != attachment.session_id {
        return Err(DurableSessionControlCaptureError::SessionProjectionMismatch);
    }
    let root_thread_id = response
        .session
        .identity
        .root_thread_id
        .as_deref()
        .ok_or(DurableSessionControlCaptureError::RootIdentityUnavailable)?;
    if root_thread_id != attachment.root_thread_id {
        return Err(DurableSessionControlCaptureError::SessionProjectionMismatch);
    }

    let operation_kind = operation.kind();
    let availability = match operation_kind {
        DurableSessionControlOperationKind::SetRootState => {
            &response
                .session
                .operation_availability
                .set_root_state
                .availability
        }
        DurableSessionControlOperationKind::Close => {
            &response.session.operation_availability.close.availability
        }
        DurableSessionControlOperationKind::Archive => {
            &response.session.operation_availability.archive.availability
        }
        DurableSessionControlOperationKind::Unarchive => {
            &response
                .session
                .operation_availability
                .unarchive
                .availability
        }
        DurableSessionControlOperationKind::Delete => {
            &response.session.operation_availability.delete.availability
        }
    };
    if !matches!(availability, DurableSessionOperationAvailability::Available) {
        return Err(DurableSessionControlCaptureError::OperationUnavailable);
    }

    let precondition = response
        .session
        .control_precondition
        .clone()
        .ok_or(DurableSessionControlCaptureError::ControlProofUnavailable)?;
    let proof_matches_projection = match &precondition {
        DurableSessionControlPrecondition::CommittedTeam {
            expected_storage_status,
            expected_residency,
            owner_incarnation,
            team_instance_id,
            team_revision,
            commit_generation,
            commit_fingerprint,
        } => {
            let owner_proof_is_consistent = match response.session.residency {
                codex_app_server_protocol::DurableSessionResidency::ObservedOwnerHere => {
                    owner_incarnation.is_some()
                }
                _ => owner_incarnation.is_none(),
            };
            response.session.team.as_ref().is_some_and(|team| {
                expected_storage_status == &response.session.storage_status
                    && expected_residency == &response.session.residency
                    && owner_proof_is_consistent
                    && team_instance_id == &team.team_instance_id
                    && team_revision == &team.revision
                    && commit_generation == &team.commit_generation
                    && commit_fingerprint == &team.commit_fingerprint
            })
        }
        DurableSessionControlPrecondition::DeleteRetryAnchor {
            expected_storage_status,
            expected_residency,
            root_marker_fingerprint,
        } => {
            operation_kind == DurableSessionControlOperationKind::Delete
                && expected_storage_status == &response.session.storage_status
                && expected_residency == &response.session.residency
                && *expected_residency
                    == codex_app_server_protocol::DurableSessionResidency::NotObservedHere
                && !root_marker_fingerprint.is_empty()
                && response.session.team.is_none()
        }
    };
    if !proof_matches_projection {
        return Err(DurableSessionControlCaptureError::ControlProofUnavailable);
    }
    Ok(CapturedQueryControl {
        accepted_read_ticket,
        params: DurableSessionControlParams {
            session_id: attachment.session_id.clone(),
            root_thread_id: attachment.root_thread_id.clone(),
            precondition,
            operation,
        },
    })
}

fn next_generation(current: u64) -> u64 {
    current.wrapping_add(1)
}

#[cfg(test)]
#[path = "durable_session_control_tests.rs"]
mod tests;
