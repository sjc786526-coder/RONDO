//! Client-side synchronization state for the experimental Session control UI.
//!
//! This module deliberately does not know the app-server RPC types. It only
//! coordinates attachment, authoritative reads, and mutation-result certainty
//! across lossy event streams and replaced connections. Callers remain
//! responsible for issuing each request explicitly; this state machine never
//! retries or replays a mutation.

/// Identifies one bound app-server connection.
///
/// A newly bound connection always receives a new epoch, so a response from a
/// retired connection cannot be accepted even if its request id is reused.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ConnectionEpoch(u64);

impl ConnectionEpoch {
    pub fn get(self) -> u64 {
        self.0
    }
}

/// Whether the projection for the current attachment can be shown as current.
///
/// Attachment is represented separately by [`ExperimentalSessionControl::attachment`].
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum ViewFreshness {
    /// No projection has been accepted for the current attachment.
    #[default]
    Absent,
    /// An explicit authoritative read is in flight.
    Refreshing,
    /// The current projection came from an accepted authoritative read.
    Fresh,
    /// A projection is retained for context but is no longer authoritative.
    Stale,
}

/// A server-classified terminal result for a mutation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KnownMutationOutcome {
    Succeeded,
    Rejected,
    Failed,
    Partial,
}

/// What the client can safely claim about the most recently started mutation.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MutationCertainty {
    /// No mutation result is associated with the current attachment.
    #[default]
    None,
    /// The request is in flight and no terminal response has been accepted.
    Pending,
    /// A terminal result was received from the connection that sent the request.
    Known(KnownMutationOutcome),
    /// The request may have been applied, but no authoritative response arrived.
    Unknown,
}

/// Identifies an explicit authoritative read.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ReadTicket {
    connection_epoch: ConnectionEpoch,
    attachment_generation: u64,
    read_generation: u64,
}

impl ReadTicket {
    pub fn connection_epoch(self) -> ConnectionEpoch {
        self.connection_epoch
    }

    pub fn read_generation(self) -> u64 {
        self.read_generation
    }
}

/// Identifies one explicitly started mutation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MutationTicket {
    connection_epoch: ConnectionEpoch,
    attachment_generation: u64,
    mutation_generation: u64,
}

impl MutationTicket {
    pub fn connection_epoch(self) -> ConnectionEpoch {
        self.connection_epoch
    }

    pub fn mutation_generation(self) -> u64 {
        self.mutation_generation
    }
}

/// Synchronizes one experimental Session-control attachment.
///
/// `A` is the caller's Session identity and `P` is its protocol projection.
/// Keeping both generic prevents this client-side lifecycle machinery from
/// becoming an alternative read model.
#[derive(Clone, Debug)]
pub struct ExperimentalSessionControl<A, P> {
    connection_epoch: ConnectionEpoch,
    connected: bool,
    attachment_generation: u64,
    read_generation: u64,
    mutation_generation: u64,
    attachment: Option<A>,
    projection: Option<P>,
    view_freshness: ViewFreshness,
    mutation_certainty: MutationCertainty,
    active_read: Option<ReadTicket>,
    pending_mutation: Option<MutationTicket>,
}

impl<A, P> Default for ExperimentalSessionControl<A, P> {
    fn default() -> Self {
        Self {
            connection_epoch: ConnectionEpoch::default(),
            connected: false,
            attachment_generation: 0,
            read_generation: 0,
            mutation_generation: 0,
            attachment: None,
            projection: None,
            view_freshness: ViewFreshness::Absent,
            mutation_certainty: MutationCertainty::None,
            active_read: None,
            pending_mutation: None,
        }
    }
}

impl<A, P> ExperimentalSessionControl<A, P> {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn connection_epoch(&self) -> ConnectionEpoch {
        self.connection_epoch
    }

    pub fn is_connected(&self) -> bool {
        self.connected
    }

    pub fn attachment(&self) -> Option<&A> {
        self.attachment.as_ref()
    }

    pub fn projection(&self) -> Option<&P> {
        self.projection.as_ref()
    }

    pub fn view_freshness(&self) -> ViewFreshness {
        self.view_freshness
    }

    pub fn mutation_certainty(&self) -> MutationCertainty {
        self.mutation_certainty
    }

    /// Binds a new connection and retires every ticket from the old epoch.
    pub fn bind_connection(&mut self) -> ConnectionEpoch {
        self.retire_connection();
        self.connection_epoch = ConnectionEpoch(next_generation(self.connection_epoch.0));
        self.connected = true;
        self.connection_epoch
    }

    /// Records an explicit disconnect event.
    pub fn on_disconnected(&mut self) {
        self.retire_connection();
    }

    /// Records event-stream EOF, which has the same certainty semantics as a
    /// disconnect even when no `Disconnected` event was delivered.
    pub fn on_event_stream_closed(&mut self) {
        self.retire_connection();
    }

    /// Attaches the UI to a Session, invalidating work for any prior attachment.
    pub fn attach(&mut self, attachment: A) {
        self.replace_attachment(Some(attachment));
    }

    /// Switches to a different Session without changing either Session's
    /// domain lifecycle.
    pub fn switch_attachment(&mut self, attachment: A) {
        self.replace_attachment(Some(attachment));
    }

    /// Detaches the UI without issuing an unsubscribe or lifecycle operation.
    pub fn detach(&mut self) {
        let pending_was_abandoned = self.pending_mutation.take().is_some();
        self.replace_attachment(None);
        if pending_was_abandoned {
            self.mutation_certainty = MutationCertainty::Unknown;
        }
    }

    /// Starts an explicit authoritative read for the current attachment.
    ///
    /// Reads are withheld while a mutation response is pending so that a
    /// pre-mutation projection cannot be mistaken for reconciliation.
    pub fn begin_read(&mut self) -> Option<ReadTicket> {
        if !self.connected
            || self.attachment.is_none()
            || self.mutation_certainty == MutationCertainty::Pending
        {
            return None;
        }

        self.read_generation = next_generation(self.read_generation);
        let ticket = ReadTicket {
            connection_epoch: self.connection_epoch,
            attachment_generation: self.attachment_generation,
            read_generation: self.read_generation,
        };
        self.active_read = Some(ticket);
        self.view_freshness = ViewFreshness::Refreshing;
        Some(ticket)
    }

    /// Accepts a projection only for the currently active read ticket.
    pub fn apply_read_success(&mut self, ticket: ReadTicket, projection: P) -> bool {
        if !self.read_ticket_is_current(ticket) {
            return false;
        }

        self.active_read = None;
        self.projection = Some(projection);
        self.view_freshness = ViewFreshness::Fresh;
        true
    }

    /// Completes a read without replacing the projection.
    ///
    /// A prior projection is retained as stale context. With no prior
    /// projection, the view returns to `Absent`.
    pub fn apply_read_failure(&mut self, ticket: ReadTicket) -> bool {
        if !self.read_ticket_is_current(ticket) {
            return false;
        }

        self.active_read = None;
        self.mark_view_not_fresh();
        true
    }

    /// Invalidates the projection after a lag marker without assuming that an
    /// independently delivered mutation response was lost.
    pub fn on_lagged(&mut self) {
        self.active_read = None;
        self.mark_view_not_fresh();
    }

    /// Starts one caller-requested mutation.
    ///
    /// A fresh authoritative view is required. This method records intent but
    /// performs no I/O and is never called automatically by the state machine.
    pub fn begin_mutation(&mut self) -> Option<MutationTicket> {
        if !self.connected
            || self.attachment.is_none()
            || self.view_freshness != ViewFreshness::Fresh
            || self.pending_mutation.is_some()
        {
            return None;
        }

        self.mutation_generation = next_generation(self.mutation_generation);
        let ticket = MutationTicket {
            connection_epoch: self.connection_epoch,
            attachment_generation: self.attachment_generation,
            mutation_generation: self.mutation_generation,
        };
        self.pending_mutation = Some(ticket);
        self.mutation_certainty = MutationCertainty::Pending;
        Some(ticket)
    }

    /// Records a server-classified terminal mutation result.
    ///
    /// Success, failure, and partial completion can all change the authoritative
    /// projection, so each forces a new read. A side-effect-free rejection keeps
    /// an otherwise fresh projection fresh.
    pub fn apply_mutation_outcome(
        &mut self,
        ticket: MutationTicket,
        outcome: KnownMutationOutcome,
    ) -> bool {
        if !self.mutation_ticket_is_current(ticket) {
            return false;
        }

        self.pending_mutation = None;
        self.mutation_certainty = MutationCertainty::Known(outcome);
        if outcome != KnownMutationOutcome::Rejected {
            self.active_read = None;
            self.mark_view_not_fresh();
        }
        true
    }

    /// Records loss of a mutation response without claiming that the mutation
    /// failed or replaying it.
    pub fn apply_mutation_response_loss(&mut self, ticket: MutationTicket) -> bool {
        if !self.mutation_ticket_is_current(ticket) {
            return false;
        }

        self.pending_mutation = None;
        self.mutation_certainty = MutationCertainty::Unknown;
        self.active_read = None;
        self.mark_view_not_fresh();
        true
    }

    fn read_ticket_is_current(&self, ticket: ReadTicket) -> bool {
        self.connected
            && self.attachment.is_some()
            && self.active_read == Some(ticket)
            && ticket.connection_epoch == self.connection_epoch
            && ticket.attachment_generation == self.attachment_generation
            && ticket.read_generation == self.read_generation
    }

    fn mutation_ticket_is_current(&self, ticket: MutationTicket) -> bool {
        self.connected
            && self.attachment.is_some()
            && self.pending_mutation == Some(ticket)
            && ticket.connection_epoch == self.connection_epoch
            && ticket.attachment_generation == self.attachment_generation
            && ticket.mutation_generation == self.mutation_generation
    }

    fn retire_connection(&mut self) {
        self.connected = false;
        self.active_read = None;
        if self.pending_mutation.take().is_some() {
            self.mutation_certainty = MutationCertainty::Unknown;
        }
        self.mark_view_not_fresh();
    }

    fn replace_attachment(&mut self, attachment: Option<A>) {
        self.attachment_generation = next_generation(self.attachment_generation);
        self.read_generation = next_generation(self.read_generation);
        self.active_read = None;
        self.pending_mutation = None;
        self.attachment = attachment;
        self.projection = None;
        self.view_freshness = ViewFreshness::Absent;
        self.mutation_certainty = MutationCertainty::None;
    }

    fn mark_view_not_fresh(&mut self) {
        self.view_freshness = if self.projection.is_some() {
            ViewFreshness::Stale
        } else {
            ViewFreshness::Absent
        };
    }
}

fn next_generation(current: u64) -> u64 {
    // A process would need to retire more than u64::MAX generations before an
    // old ticket could compare equal again. Wrapping keeps the invalidation
    // path total instead of turning a transport event into a client panic.
    current.wrapping_add(1)
}

#[cfg(test)]
#[path = "experimental_session_control_tests.rs"]
mod tests;
