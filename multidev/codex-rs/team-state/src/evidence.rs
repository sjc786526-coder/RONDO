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

/// How many unconfirmed observations one team instance keeps waiting for confirmation.
///
/// An observation whose retention is never confirmed — an abandoned turn, a result the harness
/// discarded — would otherwise sit here for the life of the instance. Dropping the oldest is safe
/// because a dropped entry only costs a fact that was never confirmed anyway.
pub(crate) const MAX_PENDING_OBSERVATIONS: usize = 256;

/// How many evidence references one version may carry.
///
/// A publication window is as large as the work its author did since it last published, so without a
/// cap a single version could hold an unbounded list — and that list is read back by `team_history`
/// into the model's context. The count that did not fit is reported rather than dropped in silence.
pub(crate) const MAX_VERSION_EVIDENCE_REFS: usize = 32;

/// The retained item shape that carries a tool result.
///
/// Kept beside the call id so a locator names one specific item rather than "whatever currently
/// answers to this call id".
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RetainedOutputKind {
    FunctionCallOutput,
    CustomToolCallOutput,
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
    /// The tool call whose retained output this fact points at.
    pub call_id: String,
    pub output_kind: RetainedOutputKind,
    /// The tool the harness dispatched, as the harness recorded it.
    pub tool: String,
}

/// A tool result the harness has seen but whose retention it has not yet confirmed.
///
/// Nothing outside this crate can observe a pending entry. It exists so that the identity, the
/// ordering and the availability of a fact are all decided at the same moment — the moment Codex is
/// known to have kept the observation — rather than optimistically when the tool returned.
pub(crate) struct PendingObservation {
    pub(crate) producer: ThreadId,
    pub(crate) category: FactCategory,
    pub(crate) locator: ObservationLocator,
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
