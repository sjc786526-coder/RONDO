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
use crate::evidence::FactAvailability;
use crate::evidence::FactCategory;
use crate::evidence::FactView;
use crate::evidence::MAX_PENDING_OBSERVATIONS;
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
    pub fn note_observation(
        &mut self,
        producer: ThreadId,
        category: FactCategory,
        locator: ObservationLocator,
    ) {
        if self.participant(producer).is_none() {
            return;
        }
        // A repeat for the same call replaces the earlier note rather than queueing a second one:
        // one tool call retains one output, so two pending entries could only ever mint a duplicate.
        self.pending_observations.retain(|pending| {
            pending.producer != producer || pending.locator.call_id != locator.call_id
        });
        if self.pending_observations.len() >= MAX_PENDING_OBSERVATIONS {
            self.pending_observations.pop_front();
        }
        self.pending_observations.push_back(PendingObservation {
            producer,
            category,
            locator,
        });
    }

    /// Mint the fact for an observation the caller has confirmed Codex retained.
    ///
    /// Returns `None` when nothing was pending for this call, which is the normal answer for every
    /// tool result outside the supported set and for anything already confirmed.
    pub fn confirm_observation(&mut self, producer: ThreadId, call_id: &str) -> Option<FactId> {
        let position = self.pending_observations.iter().position(|pending| {
            pending.producer == producer && pending.locator.call_id == call_id
        })?;
        let pending = self.pending_observations.remove(position)?;
        let id = FactId::new(self.tag, self.next_fact_ordinal);
        self.next_fact_ordinal = self.next_fact_ordinal.saturating_add(1);
        self.facts.push(TeamFact::new(
            id,
            pending.producer,
            pending.category,
            pending.locator,
        ));
        Some(id)
    }

    /// The sequence position a participant joining now starts its first publication window at.
    ///
    /// Evidence recorded before a participant joined is not its own to publish, and a member that is
    /// unloaded and reloaded keeps the cursor it already had because registration is idempotent.
    pub(crate) fn current_fact_watermark(&self) -> u32 {
        self.next_fact_ordinal.saturating_sub(1)
    }

    /// Take this producer's unpublished facts and advance its cursor past them.
    ///
    /// Called from inside the publish commit, so the selection, the version that carries it and the
    /// cursor move are one indivisible step.
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
            availability: fact.availability(),
            locator: fact.locator().clone(),
        })
    }

    /// Record that a fact's observation is gone for good.
    ///
    /// Only callable by a reader that may already read the fact, and only in one direction. The
    /// reference itself stays: a version's authored content never changes, so the honest answer to
    /// "what did this point at" is a labelled absence rather than a missing entry.
    pub fn mark_fact_unavailable(
        &mut self,
        actor: ThreadId,
        fact_id: FactId,
    ) -> Result<(), TeamError> {
        self.read_fact(actor, fact_id)?;
        if let Some(fact) = self.facts.iter_mut().find(|fact| fact.id() == fact_id) {
            fact.availability = FactAvailability::Unavailable;
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "evidence_tests.rs"]
mod tests;
