//! Shared fixtures for the crate's own tests.

use crate::ids::TeamRevision;
use crate::model::ParticipantRole;
use crate::mutation::PublishRequest;
use crate::mutation::PublishTarget;
use crate::mutation::Submission;
use crate::store::TeamStore;
use codex_protocol::ThreadId;

pub(crate) struct TeamFixture {
    pub(crate) store: TeamStore,
    pub(crate) root: ThreadId,
    pub(crate) worker: ThreadId,
}

impl TeamFixture {
    /// A team with a root and one spawned member registered.
    pub(crate) fn new() -> Self {
        let mut store = TeamStore::new();
        let root = ThreadId::new();
        let worker = ThreadId::new();
        store.register_participant(root, ParticipantRole::Root, "/root".to_string());
        store.register_participant(worker, ParticipantRole::Member, "/root/worker".to_string());
        Self {
            store,
            root,
            worker,
        }
    }
}

pub(crate) fn submission(based_on: TeamRevision, request_id: &str) -> Submission {
    Submission {
        based_on,
        request_id: request_id.to_string(),
    }
}

pub(crate) fn new_event(title: &str, summary: &str) -> PublishRequest {
    PublishRequest {
        target: PublishTarget::NewEvent {
            title: title.to_string(),
        },
        summary: summary.to_string(),
        handoff: None,
    }
}

pub(crate) fn append(event_id: crate::ids::EventId, summary: &str) -> PublishRequest {
    PublishRequest {
        target: PublishTarget::ExistingEvent { event_id },
        summary: summary.to_string(),
        handoff: None,
    }
}
