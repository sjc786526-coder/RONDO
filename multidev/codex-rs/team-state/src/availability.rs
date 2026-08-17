//! Derived producer availability.
//!
//! The four classes are the product contract. This crate stores and compares them; it does not
//! invent them. The harness derives a snapshot from AgentControl, the registry, residency and the
//! same-tree resume path, then hands that snapshot to retirement, projection and diagnostics.
//!
//! A snapshot is identified by an epoch computed from its classified entries, so a retirement
//! submitted against an older picture can be refused instead of silently covering a producer that
//! became recoverable again.

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
/// Equal snapshots of the same classified set produce the same epoch, so a no-op re-read does not
/// look like a change. The value is session-local; it is not a hash of private context.
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

    fn of(entries: &[(ThreadId, ProducerAvailability)]) -> Self {
        // FNV-1a 64. Stable for the life of this process, which is the lifetime of a team instance.
        let mut hash = 0xcbf29ce484222325_u64;
        for (thread_id, class) in entries {
            for byte in thread_id.to_string().as_bytes() {
                hash ^= u64::from(*byte);
                hash = hash.wrapping_mul(0x100_0000_01b3);
            }
            hash ^= match class {
                ProducerAvailability::Available => 1,
                ProducerAvailability::RecoverableUnloaded => 2,
                ProducerAvailability::Unavailable => 3,
                ProducerAvailability::Unknown => 4,
            };
            hash = hash.wrapping_mul(0x100_0000_01b3);
        }
        Self(hash)
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
    pub fn from_entries(mut entries: Vec<(ThreadId, ProducerAvailability)>) -> Self {
        entries.sort_by(|left, right| {
            left.0
                .to_string()
                .cmp(&right.0.to_string())
                .then_with(|| format!("{:?}", left.1).cmp(&format!("{:?}", right.1)))
        });
        entries.dedup_by(|left, right| left.0 == right.0);
        let epoch = AvailabilityEpoch::of(&entries);
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
