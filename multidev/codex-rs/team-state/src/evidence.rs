//! Evidence: stable references to observations Codex actually kept.
//!
//! A fact is not a copy of a tool result and not a claim that the result still holds. It is an
//! identity plus enough metadata to find one retained observation again, so a version's summary can
//! be traced back to what the harness saw at the time instead of being taken on the author's word.
//!
//! Two rules shape everything here. A fact is only minted once retention has been confirmed, which
//! is why an observation first arrives as a [`PendingObservation`] and only becomes a fact when the
//! capture layer comes back to say it was kept. And the payload stays where Codex put it: this
//! module holds locators, never output.

use crate::ids::FactId;
use codex_protocol::ThreadId;
use serde::Serialize;
use std::fmt;

/// How many of a version's references one tool result names.
///
/// The version itself keeps every reference its publication window selected: the association between
/// an entry and what its author had observed is authored content, and a context budget must not
/// change it. What a budget may bound is how much of that list one answer prints, which is what this
/// caps — always alongside the count it leaves out.
pub(crate) const MAX_REPORTED_EVIDENCE_REFS: usize = 32;

/// Split a version's references into the ones an answer names and the number it leaves out.
pub fn reported_evidence_refs(refs: &[FactId]) -> (&[FactId], usize) {
    let shown = refs.len().min(MAX_REPORTED_EVIDENCE_REFS);
    (&refs[..shown], refs.len() - shown)
}

/// What kind of observation a fact points at.
///
/// The first version supports exactly one family — a completed tool call whose retained result is
/// text — split by what that result reported, because "the check failed" is as much an observation
/// as "the check passed" and a reader has to be able to tell them apart without fetching the body.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FactCategory {
    ToolResultSuccess,
    ToolResultFailure,
}

impl fmt::Display for FactCategory {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::ToolResultSuccess => "tool_result_success",
            Self::ToolResultFailure => "tool_result_failure",
        })
    }
}

/// Which of the producer's retained items a fact points at.
///
/// Everything here is a harness fact recorded at capture time. None of it is model input, and none
/// of it is the observation itself: resolving a locator is the harness's job and happens only when
/// someone permitted to read the fact asks.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ObservationLocator {
    /// The identity Codex assigned the retained item, which is what makes this locator resolve to one
    /// observation and no other.
    ///
    /// A call id cannot do that job: it comes from the model's request, so two calls can carry the
    /// same one, and a reference matched on it could be answered with a different call's output — or
    /// silently redirected onto a later one after compaction dropped the original. This identity is
    /// minted per retained item by the harness. It is not stable across a replay, and does not need
    /// to be: what a replay reproduces is the fact ordinals and the window each publication carried.
    pub item_id: String,
    /// The tool call the observation came from. Metadata for the reader, never the locator.
    pub call_id: String,
    /// The tool the harness dispatched, as the harness recorded it.
    pub tool: String,
}

/// What the capture layer knows about a tool result before it is retained.
///
/// Codex reserves the item identity before dispatch so it can pair concurrent results exactly. The
/// identity is only a locator at this point: no Fact exists until the retention boundary confirms
/// that the item carrying it was formally kept.
pub struct NotedObservation {
    /// The identity already reserved for the result item. This is the pairing identity as well as
    /// the eventual locator: unlike a model-provided call id, it is unique per harness invocation.
    pub item_id: String,
    pub call_id: String,
    pub category: FactCategory,
    pub tool: String,
}

/// A tool result the harness has seen but whose retention it has not yet confirmed.
///
/// Nothing outside this crate can observe a pending entry. It exists so that fact ordering and
/// existence are decided at the retention boundary, while the pre-reserved item identity pairs that
/// confirmation back to exactly one completed invocation.
pub(crate) struct PendingObservation {
    pub(crate) producer: ThreadId,
    pub(crate) noted: NotedObservation,
}

/// One recorded piece of evidence.
///
/// There is no stored "is it still there" flag. A fact is not minted until retention is confirmed,
/// and after that whether the observation can be fetched is a question about the producer's live
/// history right now — one only the harness can answer, and only at the moment of reading. Keeping a
/// cached answer here would mean writing a reference off on evidence that cannot establish
/// permanence: an ordinary compaction drops tool results from the window while the rollout still
/// holds them.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TeamFact {
    id: FactId,
    /// The participant whose work produced the observation, from the authoritative session identity.
    producer: ThreadId,
    category: FactCategory,
    locator: ObservationLocator,
}

impl TeamFact {
    pub(crate) fn new(
        id: FactId,
        producer: ThreadId,
        category: FactCategory,
        locator: ObservationLocator,
    ) -> Self {
        Self {
            id,
            producer,
            category,
            locator,
        }
    }

    pub fn id(&self) -> FactId {
        self.id
    }

    pub fn producer(&self) -> ThreadId {
        self.producer
    }

    pub fn category(&self) -> FactCategory {
        self.category
    }

    pub fn locator(&self) -> &ObservationLocator {
        &self.locator
    }
}

/// One fact as a permitted reader may see it, without the observation body.
///
/// The locator travels because the caller is the harness, which has to resolve it. What reaches a
/// model is decided by the caller, and never includes the arguments the tool was called with or
/// anything else from the producer's context.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FactView {
    pub id: FactId,
    pub producer: ThreadId,
    pub producer_label: String,
    pub category: FactCategory,
    pub locator: ObservationLocator,
}
