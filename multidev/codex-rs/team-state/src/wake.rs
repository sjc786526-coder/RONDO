//! Wake bookkeeping for participants waiting on team changes.
//!
//! Wakes are counted rather than sent, so a change published before a participant starts waiting
//! is still there when it does, and a change it has already consumed cannot wake it again.

use codex_protocol::ThreadId;
use std::collections::HashMap;

#[derive(Default)]
pub(crate) struct WakeLedger {
    signalled: HashMap<ThreadId, u64>,
    consumed: HashMap<ThreadId, u64>,
}

impl WakeLedger {
    pub(crate) fn signal(&mut self, participant: ThreadId) {
        *self.signalled.entry(participant).or_default() += 1;
    }

    pub(crate) fn has_pending(&self, participant: ThreadId) -> bool {
        let signalled = self
            .signalled
            .get(&participant)
            .copied()
            .unwrap_or_default();
        let consumed = self.consumed.get(&participant).copied().unwrap_or_default();
        signalled > consumed
    }

    pub(crate) fn consume(&mut self, participant: ThreadId) -> bool {
        if !self.has_pending(participant) {
            return false;
        }
        let signalled = self
            .signalled
            .get(&participant)
            .copied()
            .unwrap_or_default();
        self.consumed.insert(participant, signalled);
        true
    }
}
