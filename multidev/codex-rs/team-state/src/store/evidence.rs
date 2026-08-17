//! Evidence capture, publication windows and read permission.
//!
//! Three invariants live here and nowhere else.
//!
//! *Retention first.* An observation is noted when the tool completes and only becomes a fact when
//! the capture layer confirms Codex kept it. Ordinals are handed out at that second step, so fact
//! order is Codex's retention order rather than wall-clock completion order, and a run that is
//! replayed along the same trajectory numbers its facts the same way.
//!
//! *The window belongs to the producer.* Each participant carries a cursor into the fact sequence.
//! A successful publish takes everything of its own that arrived after the cursor and advances the
//! cursor in the same mutation, so a refused publish cannot consume evidence and a retry that is
//! answered from the committed submission cannot drift onto observations that arrived later.
//!
//! *Reads follow the event graph.* The root reads its team's evidence, a producer reads its own, and
//! anyone else reads only what a version of an event they can see explicitly referenced. Holding a
//! fact identifier is not a permission.

use super::TeamStore;
use crate::evidence::FactView;
use crate::evidence::NotedObservation;
use crate::evidence::ObservationLocator;
use crate::evidence::PendingObservation;
use crate::evidence::TeamFact;
use crate::ids::FactId;
use crate::mutation::TeamError;
use codex_protocol::ThreadId;

impl TeamStore {
    /// Note a completed, supported tool result whose retention is not confirmed yet.
    ///
    /// Nothing is minted here. A producer that is not a registered participant of this instance is
    /// ignored outright, which is the same fail-closed rule the team tools follow: an unidentified
    /// session gets no team capability, and that includes leaving evidence behind.
    pub fn note_observation(&mut self, producer: ThreadId, noted: NotedObservation) {
        if self.participant(producer).is_none() {
            return;
        }
        // The harness reserves one item identity per invocation before dispatch. It is the pairing
        // identity here because call ids come from the model and may be reused concurrently.
        if noted.item_id.is_empty() {
            return;
        }
        if self
            .pending_observations
            .iter()
            .any(|pending| pending.producer == producer && pending.noted.item_id == noted.item_id)
        {
            return;
        }
        self.pending_observations
            .push_back(PendingObservation { producer, noted });
    }

    /// Drop a note whose result the harness ended up throwing away.
    ///
    /// An interrupted tool call can still finish its teardown and return an outcome, which the host
    /// then discards in favour of its own filler answer. The filler reaches history under the same
    /// call id, so without revoking the note it would be confirmed as though the tool had reported
    /// it — turning an interrupted call into evidence.
    pub fn discard_observation(&mut self, producer: ThreadId, item_id: &str) {
        self.pending_observations
            .retain(|pending| pending.producer != producer || pending.noted.item_id != item_id);
    }

    /// Mint the fact for an observation the caller has confirmed Codex retained as `item_id`.
    ///
    /// The item identity was reserved before dispatch and arrives here on the retained item itself.
    /// Pairing by that harness identity gives the fact a locator that resolves to one observation,
    /// even when model-provided call ids are reused. Returns `None` when nothing was pending for this
    /// item, which is the normal answer outside the supported set and after an earlier confirmation.
    pub fn confirm_observation(&mut self, producer: ThreadId, item_id: &str) -> Option<FactId> {
        if item_id.is_empty() {
            return None;
        }
        let position = self
            .pending_observations
            .iter()
            .position(|pending| pending.producer == producer && pending.noted.item_id == item_id)?;
        let pending = self.pending_observations.remove(position)?;
        let id = FactId::new(self.tag, self.next_fact_ordinal);
        self.next_fact_ordinal = self.next_fact_ordinal.saturating_add(1);
        self.facts.push(TeamFact::new(
            id,
            pending.producer,
            pending.noted.category,
            ObservationLocator {
                item_id: item_id.to_string(),
                call_id: pending.noted.call_id,
                tool: pending.noted.tool,
            },
        ));
        self.observe_generation = self.observe_generation.saturating_add(1);
        Some(id)
    }

    /// Take this producer's unpublished facts and advance its cursor past them.
    ///
    /// Called from inside the publish commit, so the selection, the version that carries it and the
    /// cursor move are one indivisible step.
    ///
    /// A participant's first publish starts from its own first observation rather than from the
    /// team's: the filter is on `producer`, and a participant cannot have evidence from before it
    /// registered because [`Self::note_observation`] refuses unregistered sessions.
    ///
    /// The whole window goes into the version. Consuming an observation without anchoring it would
    /// lose it for good — the cursor has moved past it, so no later publish can pick it up — and no
    /// context budget is worth that. Budgets belong to the surfaces that print the list, which cap
    /// what they show and say how much they left out.
    pub(crate) fn take_publish_window(&mut self, producer: ThreadId) -> Vec<FactId> {
        let cursor = self
            .published_facts_through
            .get(&producer)
            .copied()
            .unwrap_or_default();
        let window: Vec<FactId> = self
            .facts
            .iter()
            .filter(|fact| fact.producer() == producer && fact.id().ordinal() > cursor)
            .map(TeamFact::id)
            .collect();
        if let Some(last) = window.last() {
            self.published_facts_through
                .insert(producer, last.ordinal());
        }
        window
    }

    /// Resolve a fact reference for `actor`, or refuse.
    ///
    /// The refusals are deliberately distinct: a reference from a previous instance reports a reset,
    /// one that names nothing reports that, and one that exists but was never shown to this reader
    /// reports a permission failure. Guessing a well-formed identifier therefore gets a reader
    /// nothing it did not already have.
    pub fn read_fact(&self, actor: ThreadId, fact_id: FactId) -> Result<FactView, TeamError> {
        let role = self.require_participant(actor)?.role;
        self.check_instance(fact_id.instance())?;
        let fact = self
            .facts
            .iter()
            .find(|fact| fact.id() == fact_id)
            .ok_or_else(|| TeamError::UnknownReference {
                reference: fact_id.to_string(),
            })?;

        let permitted = role.is_root()
            || fact.producer() == actor
            || self.events.iter().any(|event| {
                event.is_visible_to(actor, role)
                    && event
                        .versions()
                        .iter()
                        .any(|version| version.authored().evidence_refs.contains(&fact_id))
            });
        if !permitted {
            return Err(TeamError::NotPermitted {
                reason: "this evidence was not produced by you and is not referenced by any team event you can see",
            });
        }

        Ok(FactView {
            id: fact.id(),
            producer: fact.producer(),
            producer_label: self.label_of(fact.producer()),
            category: fact.category(),
            locator: fact.locator().clone(),
        })
    }
}

#[cfg(test)]
#[path = "evidence_tests.rs"]
mod tests;
