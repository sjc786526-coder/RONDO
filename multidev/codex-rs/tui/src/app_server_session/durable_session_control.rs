//! Formal Durable Session control synchronization owned by [`AppServerSession`].
//!
//! The query client state remains the only Session projection. This bridge
//! holds only the certainty of one send-once control attempt and always locks
//! the query before the attempt state when both must be changed.

use super::AppServerSession;
use codex_app_server_client::DurableSessionControlAttempt;
use codex_app_server_client::DurableSessionControlAttemptState;
use codex_app_server_client::DurableSessionControlAttemptTicket;
use codex_app_server_client::DurableSessionControlCaptureError;
use codex_app_server_client::DurableSessionControlCertainty;
use codex_app_server_client::DurableSessionQueryClientState;
use codex_app_server_client::QueryReadTicket;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlResponse;
use std::sync::Mutex;
use std::sync::MutexGuard;

const LAGGED_RESULT_MESSAGE: &str =
    "app-server events were lost while the Durable Session control result was pending";
const DISCONNECTED_RESULT_MESSAGE: &str =
    "app-server disconnected while the Durable Session control result was pending";
const EVENT_STREAM_CLOSED_RESULT_MESSAGE: &str =
    "app-server event stream closed while the Durable Session control result was pending";
const DETACHED_RESULT_MESSAGE: &str =
    "Durable Session control was detached while its result was pending";
const DISABLED_RESULT_MESSAGE: &str =
    "Durable Session control was disabled while its result was pending";
const ATTACHMENT_REPLACED_RESULT_MESSAGE: &str =
    "the Durable Session query attachment changed while the control result was pending";

pub(super) struct DurableSessionControlBridge {
    attempt: Mutex<DurableSessionControlAttemptState>,
}

impl DurableSessionControlBridge {
    pub(super) fn new() -> Self {
        Self {
            attempt: Mutex::new(DurableSessionControlAttemptState::new()),
        }
    }

    fn attempt(&self) -> MutexGuard<'_, DurableSessionControlAttemptState> {
        self.attempt
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn accepted_read_ticket(
        &self,
        query: &Mutex<DurableSessionQueryClientState>,
    ) -> Option<QueryReadTicket> {
        query
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .accepted_read_ticket()
    }

    fn begin(
        &self,
        query: &Mutex<DurableSessionQueryClientState>,
        accepted_read_ticket: QueryReadTicket,
        operation: DurableSessionControlOperation,
    ) -> Result<DurableSessionControlAttempt, DurableSessionControlCaptureError> {
        let query = query
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        self.attempt()
            .begin_attempt(&query, accepted_read_ticket, operation)
    }

    fn apply_response(
        &self,
        query: &Mutex<DurableSessionQueryClientState>,
        ticket: DurableSessionControlAttemptTicket,
        response: DurableSessionControlResponse,
    ) -> bool {
        let mut query = query
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        self.attempt().apply_response(&mut query, ticket, response)
    }

    fn apply_unknown(
        &self,
        query: &Mutex<DurableSessionQueryClientState>,
        ticket: DurableSessionControlAttemptTicket,
        message: impl Into<String>,
    ) -> bool {
        let mut query = query
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        self.attempt().apply_unknown(&mut query, ticket, message)
    }

    fn certainty(&self) -> DurableSessionControlCertainty {
        self.attempt().certainty().clone()
    }

    fn retire_pending_as_unknown(
        &self,
        query: &mut DurableSessionQueryClientState,
        message: &'static str,
    ) -> bool {
        self.attempt().retire_pending_as_unknown(query, message)
    }
}

impl AppServerSession {
    /// Captures the accepted authoritative read token shown by a confirmation view.
    pub(crate) fn durable_session_control_accepted_read_ticket(&self) -> Option<QueryReadTicket> {
        self.durable_session_control
            .accepted_read_ticket(&self.durable_session_query)
    }

    /// Revalidates a captured read and creates one send-once formal control request.
    pub(crate) fn durable_session_control_begin(
        &self,
        accepted_read_ticket: QueryReadTicket,
        operation: DurableSessionControlOperation,
    ) -> Result<DurableSessionControlAttempt, DurableSessionControlCaptureError> {
        self.durable_session_control.begin(
            &self.durable_session_query,
            accepted_read_ticket,
            operation,
        )
    }

    pub(crate) fn durable_session_control_apply_response(
        &self,
        ticket: DurableSessionControlAttemptTicket,
        response: DurableSessionControlResponse,
    ) -> bool {
        self.durable_session_control
            .apply_response(&self.durable_session_query, ticket, response)
    }

    pub(crate) fn durable_session_control_apply_unknown(
        &self,
        ticket: DurableSessionControlAttemptTicket,
        message: impl Into<String>,
    ) -> bool {
        self.durable_session_control
            .apply_unknown(&self.durable_session_query, ticket, message)
    }

    pub(crate) fn durable_session_control_certainty(&self) -> DurableSessionControlCertainty {
        self.durable_session_control.certainty()
    }

    pub(crate) fn durable_session_control_on_lagged(&self) -> bool {
        let mut query = self.durable_session_query();
        let retired = self
            .durable_session_control
            .retire_pending_as_unknown(&mut query, LAGGED_RESULT_MESSAGE);
        query.on_lagged();
        retired
    }

    pub(crate) fn durable_session_control_on_disconnected(&self) -> bool {
        let mut query = self.durable_session_query();
        let retired = self
            .durable_session_control
            .retire_pending_as_unknown(&mut query, DISCONNECTED_RESULT_MESSAGE);
        query.on_disconnected();
        retired
    }

    pub(crate) fn durable_session_control_on_event_stream_closed(&self) -> bool {
        let mut query = self.durable_session_query();
        let retired = self
            .durable_session_control
            .retire_pending_as_unknown(&mut query, EVENT_STREAM_CLOSED_RESULT_MESSAGE);
        query.on_event_stream_closed();
        retired
    }

    pub(crate) fn durable_session_control_detach(&self) -> bool {
        let mut query = self.durable_session_query();
        let retired = self
            .durable_session_control
            .retire_pending_as_unknown(&mut query, DETACHED_RESULT_MESSAGE);
        query.detach();
        retired
    }

    /// Disables mutation capability without discarding the read-only query attachment.
    pub(crate) fn durable_session_control_disable(&self) -> bool {
        let mut query = self.durable_session_query();
        let retired = self
            .durable_session_control
            .retire_pending_as_unknown(&mut query, DISABLED_RESULT_MESSAGE);
        query.on_lagged();
        retired
    }

    pub(super) fn durable_session_control_retire_for_attachment_change(
        &self,
        query: &mut DurableSessionQueryClientState,
    ) -> bool {
        self.durable_session_control
            .retire_pending_as_unknown(query, ATTACHMENT_REPLACED_RESULT_MESSAGE)
    }
}

#[cfg(test)]
#[path = "durable_session_control_tests.rs"]
mod tests;
