//! Derived producer availability.
//!
//! The four classes are the product contract. This crate stores and compares them; it does not
//! invent them. The harness derives a snapshot from the same restore gate that would actually
//! reload a member, then hands that snapshot to retirement, projection and diagnostics.
//!
//! A snapshot carries a harness-assigned monotonic epoch. Equal classified sets do not reuse an
//! epoch across an intervening change: `unavailable → available → unavailable` must not look like
//! the original picture, or a stale retirement could land after a producer had come back.

use codex_protocol::ThreadId;
use serde::Serialize;
use std::fmt;

/// What the harness currently believes about one producer's recoverability in this team instance.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProducerAvailability {
    /// Currently loaded, or otherwise able to receive work without a restore.
    Available,
    /// Not resident, but the same live root tree can restore it.
    RecoverableUnloaded,
    /// Authoritative control-plane facts say it cannot be restored in this instance.
    Unavailable,
    /// Facts were missing, contradictory, or could not be read. Fail closed.
    Unknown,
}

impl ProducerAvailability {
    pub fn is_unavailable(self) -> bool {
        matches!(self, Self::Unavailable)
    }
}

impl fmt::Display for ProducerAvailability {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Available => "available",
            Self::RecoverableUnloaded => "recoverable_unloaded",
            Self::Unavailable => "unavailable",
            Self::Unknown => "unknown",
        })
    }
}

/// Identity of one availability snapshot.
///
/// The harness assigns this from a monotonic generation that advances on load, unload, restore and
/// stored-thread deletion. It is not a hash of the classified set, so an ABA cycle cannot replay
/// an earlier epoch. The value is session-local.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct AvailabilityEpoch(u64);

impl AvailabilityEpoch {
    pub const INITIAL: Self = Self(0);

    pub fn get(self) -> u64 {
        self.0
    }

    pub fn from_raw(raw: u64) -> Self {
        Self(raw)
    }
}

impl fmt::Display for AvailabilityEpoch {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// One complete, sorted availability picture for the current team participants.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AvailabilitySnapshot {
    pub epoch: AvailabilityEpoch,
    entries: Vec<(ThreadId, ProducerAvailability)>,
}

impl AvailabilitySnapshot {
    /// Build a snapshot from unsorted classifications. Missing participants are not invented.
    ///
    /// Tests that do not care about the epoch can use [`Self::from_entries`], which stamps
    /// [`AvailabilityEpoch::INITIAL`]. Product code must pass the harness generation.
    pub fn from_entries(entries: Vec<(ThreadId, ProducerAvailability)>) -> Self {
        Self::from_entries_at(AvailabilityEpoch::INITIAL, entries)
    }

    pub fn from_entries_at(
        epoch: AvailabilityEpoch,
        mut entries: Vec<(ThreadId, ProducerAvailability)>,
    ) -> Self {
        entries.sort_by(|left, right| {
            left.0
                .to_string()
                .cmp(&right.0.to_string())
                .then_with(|| format!("{:?}", left.1).cmp(&format!("{:?}", right.1)))
        });
        entries.dedup_by(|left, right| left.0 == right.0);
        Self { epoch, entries }
    }

    pub fn class_of(&self, thread_id: ThreadId) -> Option<ProducerAvailability> {
        self.entries
            .iter()
            .find(|(id, _)| *id == thread_id)
            .map(|(_, class)| *class)
    }

    pub fn entries(&self) -> &[(ThreadId, ProducerAvailability)] {
        &self.entries
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}

impl Default for AvailabilitySnapshot {
    fn default() -> Self {
        Self::from_entries(Vec::new())
    }
}

#[cfg(test)]
#[path = "availability_tests.rs"]
mod tests;
