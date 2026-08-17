//! The shared front door to a team instance.
//!
//! One handle exists per live root tree and is cloned into every member of that tree, which is
//! what makes the state canonical: there is no second copy to reconcile, and nothing about it
//! depends on which members happen to be loaded right now.

use crate::availability::AvailabilitySnapshot;
use crate::evidence::FactView;
use crate::evidence::NotedObservation;
use crate::ids::FactId;
use crate::ids::RouteId;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::model::Participant;
use crate::model::ParticipantRole;
use crate::mutation::DeliveryOutcome;
use crate::mutation::DeliveryResult;
use crate::mutation::EndAssignmentOutcome;
use crate::mutation::LifecycleOutcome;
use crate::mutation::LifecycleRequest;
use crate::mutation::PublishOutcome;
use crate::mutation::PublishRequest;
use crate::mutation::RetireOutcome;
use crate::mutation::RetireRequest;
use crate::mutation::RouteDispatch;
use crate::mutation::RouteOutcome;
use crate::mutation::RouteRequest;
use crate::mutation::Submission;
use crate::mutation::TeamError;
use crate::observe::ChangeLogPage;
use crate::observe::DumpCursor;
use crate::observe::ObserveQuery;
use crate::observe::PublicationStats;
use crate::observe::TeamDumpPage;
use crate::store::TeamStore;
use crate::view::HistoryPage;
use crate::view::HistoryQuery;
use crate::view::TeamSnapshot;
use codex_protocol::ThreadId;
use std::sync::Arc;
use std::sync::Mutex;
use tokio::sync::watch;

pub struct TeamStateHandle {
    store: Mutex<TeamStore>,
    /// Bumped on every wake-worthy change so waiters re-check their own ledger entry. The value
    /// itself carries no meaning; the per-participant ledger inside the store does.
    change_tx: watch::Sender<u64>,
}

impl Default for TeamStateHandle {
    fn default() -> Self {
        Self {
            store: Mutex::new(TeamStore::new()),
            change_tx: watch::Sender::new(0),
        }
    }
}

impl TeamStateHandle {
    fn with_store<R>(&self, f: impl FnOnce(&mut TeamStore) -> R) -> R {
        // A poisoned team mutex means a previous mutation panicked mid-commit. Recovering the
        // guard is still the right call here: the store's mutations validate before they write,
        // so the state a panicking caller leaves behind is the pre-mutation state.
        let mut store = self.store.lock().unwrap_or_else(|poisoned| {
            tracing::error!("team state mutex was poisoned; continuing with recovered state");
            poisoned.into_inner()
        });
        f(&mut store)
    }

    pub fn instance(&self) -> TeamInstanceId {
        self.with_store(|store| store.instance())
    }

    pub fn revision(&self) -> TeamRevision {
        self.with_store(|store| store.revision())
    }

    /// Register a participant derived from authoritative session identity.
    ///
    /// Idempotent, so a member that is unloaded and reloaded in the same live root tree keeps its
    /// instance, role and everything it authored.
    pub fn register_participant(
        &self,
        thread_id: ThreadId,
        role: ParticipantRole,
        label: String,
    ) -> bool {
        self.with_store(|store| store.register_participant(thread_id, role, label))
    }

    pub fn participant(&self, thread_id: ThreadId) -> Option<Participant> {
        self.with_store(|store| store.participant(thread_id).cloned())
    }

    pub fn participants(&self) -> Vec<Participant> {
        self.with_store(|store| store.participants())
    }

    /// The generation waiters observe. It only advances when a mutation actually changed canonical
    /// state, so a stable retry cannot look like new work.
    pub fn wake_generation(&self) -> u64 {
        *self.change_tx.borrow()
    }

    pub fn publish(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: PublishRequest,
    ) -> Result<PublishOutcome, TeamError> {
        let outcome = self.with_store(|store| store.publish(actor, submission, request));
        self.notify_if_changed(outcome.as_ref().is_ok_and(|outcome| !outcome.deduplicated));
        outcome
    }

    pub fn update_lifecycle(
        &self,
        actor: ThreadId,
        request: LifecycleRequest,
    ) -> Result<LifecycleOutcome, TeamError> {
        let outcome = self.with_store(|store| store.update_lifecycle(actor, request));
        self.notify_if_changed(outcome.is_ok());
        outcome
    }

    /// Commit a route: the visibility grant, and the assignment when work is intended.
    ///
    /// The notice is the caller's job and happens strictly after this returns, which is the whole
    /// ordering guarantee: nothing can be delivered about a grant that does not exist yet.
    pub fn route(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: RouteRequest,
    ) -> Result<RouteOutcome, TeamError> {
        let outcome = self.with_store(|store| store.route(actor, submission, request));
        self.notify_if_changed(outcome.as_ref().is_ok_and(|outcome| !outcome.deduplicated));
        outcome
    }

    pub fn record_delivery(
        &self,
        actor: ThreadId,
        route_id: RouteId,
        result: DeliveryResult,
    ) -> Result<DeliveryOutcome, TeamError> {
        let outcome = self.with_store(|store| store.record_delivery(actor, route_id, result));
        self.notify_if_changed(outcome.as_ref().is_ok_and(|outcome| outcome.changed));
        outcome
    }

    pub fn end_assignment(
        &self,
        actor: ThreadId,
        route_id: RouteId,
    ) -> Result<EndAssignmentOutcome, TeamError> {
        let outcome = self.with_store(|store| store.end_assignment(actor, route_id));
        self.notify_if_changed(outcome.is_ok());
        outcome
    }

    pub fn retire(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: RetireRequest,
        availability: &AvailabilitySnapshot,
    ) -> Result<RetireOutcome, TeamError> {
        let outcome =
            self.with_store(|store| store.retire(actor, submission, request, availability));
        self.notify_if_changed(outcome.as_ref().is_ok_and(|outcome| !outcome.deduplicated));
        outcome
    }

    pub fn dump(
        &self,
        actor: ThreadId,
        availability: &AvailabilitySnapshot,
        query: ObserveQuery,
        cursor: Option<DumpCursor>,
    ) -> Result<TeamDumpPage, TeamError> {
        let wake_generation = self.wake_generation();
        self.with_store(|store| store.dump(actor, availability, wake_generation, query, cursor))
    }

    pub fn change_log(
        &self,
        actor: ThreadId,
        query: ObserveQuery,
    ) -> Result<ChangeLogPage, TeamError> {
        let wake_generation = self.wake_generation();
        self.with_store(|store| store.change_log(actor, wake_generation, query))
    }

    pub fn publication_stats(&self, actor: ThreadId) -> Result<Vec<PublicationStats>, TeamError> {
        self.with_store(|store| store.publication_stats(actor))
    }

    pub fn route_dispatch(
        &self,
        actor: ThreadId,
        route_id: RouteId,
    ) -> Result<RouteDispatch, TeamError> {
        self.with_store(|store| store.route_dispatch(actor, route_id))
    }

    /// Note a completed, supported tool result whose retention is not confirmed yet.
    pub fn note_observation(&self, producer: ThreadId, noted: NotedObservation) {
        self.with_store(|store| store.note_observation(producer, noted));
    }

    /// Mint the fact for an observation the caller has confirmed Codex retained.
    ///
    /// No change notification follows: recording evidence is not itself a team event, and nothing in
    /// anyone's active view moves until an author decides to publish.
    pub fn confirm_observation(&self, producer: ThreadId, item_id: &str) -> Option<FactId> {
        self.with_store(|store| store.confirm_observation(producer, item_id))
    }

    /// Drop a note whose result the harness ended up throwing away.
    pub fn discard_observation(&self, producer: ThreadId, item_id: &str) {
        self.with_store(|store| store.discard_observation(producer, item_id));
    }

    pub fn read_fact(&self, actor: ThreadId, fact_id: FactId) -> Result<FactView, TeamError> {
        self.with_store(|store| store.read_fact(actor, fact_id))
    }

    pub fn snapshot_for(&self, viewer: ThreadId) -> Result<TeamSnapshot, TeamError> {
        self.with_store(|store| store.snapshot_for(viewer))
    }

    pub fn history(
        &self,
        viewer: ThreadId,
        query: &HistoryQuery,
    ) -> Result<HistoryPage, TeamError> {
        self.with_store(|store| store.history(viewer, query))
    }

    pub fn has_pending_wake(&self, participant: ThreadId) -> bool {
        self.with_store(|store| store.has_pending_wake(participant))
    }

    pub fn consume_wake(&self, participant: ThreadId) -> bool {
        self.with_store(|store| store.consume_wake(participant))
    }

    fn notify_if_changed(&self, changed: bool) {
        if changed {
            self.notify_change();
        }
    }

    fn notify_change(&self) {
        self.change_tx.send_modify(|value| {
            *value = value.wrapping_add(1);
        });
    }

    /// Start listening for team changes addressed to `participant`.
    ///
    /// The subscription is taken before the first check, so a change published between the two
    /// cannot be lost: it either shows up in the check or in the watch channel.
    pub fn wake_waiter(self: &Arc<Self>, participant: ThreadId) -> TeamWakeWaiter {
        let change_rx = self.change_tx.subscribe();
        TeamWakeWaiter {
            handle: Arc::clone(self),
            participant,
            change_rx,
        }
    }
}

/// A pending wait for team activity. Resolving it consumes the wake.
pub struct TeamWakeWaiter {
    handle: Arc<TeamStateHandle>,
    participant: ThreadId,
    change_rx: watch::Receiver<u64>,
}

impl TeamWakeWaiter {
    /// Resolve as soon as this participant has an unconsumed team change, consuming it so the same
    /// change cannot wake it a second time.
    pub async fn wait(mut self) {
        loop {
            if self.handle.consume_wake(self.participant) {
                return;
            }
            if self.change_rx.changed().await.is_err() {
                // The sender lives inside the handle this waiter holds, so this is unreachable in
                // practice; park rather than reporting a wake that did not happen.
                std::future::pending::<()>().await;
            }
        }
    }
}

#[cfg(test)]
#[path = "handle_tests.rs"]
mod tests;
