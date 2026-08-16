//! The canonical team state for one live root tree.
//!
//! This type owns every invariant. It is deliberately synchronous and lock-free on its own: the
//! handle wraps it in a single mutex so each mutation checks preconditions and commits without an
//! intervening await, which is what makes concurrent appends, retries and racing lifecycle changes
//! well defined.

use crate::ids::EventId;
use crate::ids::InstanceTag;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::ids::VersionId;
use crate::model::AuthoredVersion;
use crate::model::Participant;
use crate::model::ParticipantRole;
use crate::model::ProducerState;
use crate::model::RootState;
use crate::model::TeamEvent;
use crate::model::TeamVersion;
use crate::mutation::LifecycleChange;
use crate::mutation::LifecycleOutcome;
use crate::mutation::LifecycleRequest;
use crate::mutation::LifecycleSnapshot;
use crate::mutation::PublishOutcome;
use crate::mutation::PublishRequest;
use crate::mutation::PublishTarget;
use crate::mutation::Submission;
use crate::mutation::TeamError;
use crate::view::EventHistory;
use crate::view::EventView;
use crate::view::HistoryPage;
use crate::view::HistoryQuery;
use crate::view::TeamSnapshot;
use crate::view::VersionView;
use crate::wake::WakeLedger;
use codex_protocol::ThreadId;
use std::collections::HashMap;

/// Hard ceiling on a single bounded history query, so a drill-down can never become unbounded.
pub const MAX_HISTORY_LIMIT: usize = 50;
const DEFAULT_HISTORY_LIMIT: usize = 10;

pub struct TeamStore {
    instance: TeamInstanceId,
    tag: InstanceTag,
    revision: TeamRevision,
    events: Vec<TeamEvent>,
    participants: HashMap<ThreadId, Participant>,
    /// Committed outcomes keyed by author and retry identity, so a repeated submission returns the
    /// original result instead of minting a second object.
    committed: HashMap<(ThreadId, String), PublishOutcome>,
    wake: WakeLedger,
    next_event_ordinal: u32,
}

impl Default for TeamStore {
    fn default() -> Self {
        Self::new()
    }
}

impl TeamStore {
    pub fn new() -> Self {
        let instance = TeamInstanceId::new();
        Self {
            instance,
            tag: instance.tag(),
            revision: TeamRevision::INITIAL,
            events: Vec::new(),
            participants: HashMap::new(),
            committed: HashMap::new(),
            wake: WakeLedger::default(),
            next_event_ordinal: 1,
        }
    }

    pub fn instance(&self) -> TeamInstanceId {
        self.instance
    }

    pub fn revision(&self) -> TeamRevision {
        self.revision
    }

    /// Register a participant of this team instance.
    ///
    /// Idempotent by thread id: a member that is unloaded and reloaded inside the same live root
    /// tree re-registers into the same instance and keeps its role and everything it authored.
    /// Returns whether this call created the registration.
    pub fn register_participant(
        &mut self,
        thread_id: ThreadId,
        role: ParticipantRole,
        label: String,
    ) -> bool {
        match self.participants.entry(thread_id) {
            std::collections::hash_map::Entry::Occupied(existing) => {
                if existing.get().role != role {
                    tracing::warn!(
                        %thread_id,
                        "team participant re-registered with a different role; keeping the original"
                    );
                }
                false
            }
            std::collections::hash_map::Entry::Vacant(slot) => {
                slot.insert(Participant {
                    thread_id,
                    role,
                    label,
                });
                true
            }
        }
    }

    pub fn participant(&self, thread_id: ThreadId) -> Option<&Participant> {
        self.participants.get(&thread_id)
    }

    fn require_participant(&self, thread_id: ThreadId) -> Result<&Participant, TeamError> {
        self.participants
            .get(&thread_id)
            .ok_or(TeamError::UnknownParticipant)
    }

    fn label_of(&self, thread_id: ThreadId) -> String {
        self.participants
            .get(&thread_id)
            .map(|participant| participant.label.clone())
            .unwrap_or_else(|| format!("<unregistered {thread_id}>"))
    }

    fn check_instance(&self, referenced: InstanceTag) -> Result<(), TeamError> {
        if referenced == self.tag {
            return Ok(());
        }
        Err(TeamError::InstanceReset {
            referenced_instance: referenced,
            current_instance: self.tag,
        })
    }

    fn event_index(&self, event_id: EventId) -> Result<usize, TeamError> {
        self.check_instance(event_id.instance())?;
        self.events
            .iter()
            .position(|event| event.id() == event_id)
            .ok_or_else(|| TeamError::UnknownReference {
                reference: event_id.to_string(),
            })
    }

    /// Resolve a version reference to its `(event, version)` position.
    fn locate_version(&self, version_id: VersionId) -> Result<(usize, usize), TeamError> {
        self.check_instance(version_id.instance())?;
        let event_index = self.event_index(version_id.event_id())?;
        let version_index = self.events[event_index]
            .version_position(version_id)
            .ok_or_else(|| TeamError::UnknownReference {
                reference: version_id.to_string(),
            })?;
        Ok((event_index, version_index))
    }

    /// Publish a new event or append a version to an existing one.
    pub fn publish(
        &mut self,
        actor: ThreadId,
        submission: &Submission,
        request: PublishRequest,
    ) -> Result<PublishOutcome, TeamError> {
        let role = self.require_participant(actor)?.role;
        if request.summary.trim().is_empty() {
            return Err(TeamError::InvalidRequest {
                reason: "summary must not be empty",
            });
        }

        let retry_key = (actor, submission.request_id.clone());
        if let Some(existing) = self.committed.get(&retry_key) {
            return Ok(PublishOutcome {
                deduplicated: true,
                ..existing.clone()
            });
        }

        let PublishRequest {
            target,
            summary,
            handoff,
        } = request;
        // Resolve the target before bumping the revision so a failed lookup leaves no trace.
        let existing_index = match &target {
            PublishTarget::NewEvent { title } if title.trim().is_empty() => {
                return Err(TeamError::InvalidRequest {
                    reason: "title must not be empty when opening a new event",
                });
            }
            PublishTarget::NewEvent { .. } => None,
            PublishTarget::ExistingEvent { event_id } => Some(self.event_index(*event_id)?),
        };

        let revision = self.revision.next();
        // Only an append can be authored against a stale view; an event nobody has seen yet has no
        // older state to be stale against.
        let previously_changed_at =
            existing_index.map(|index| self.events[index].last_changed_at());
        let event_index = match (existing_index, target) {
            (Some(index), _) => index,
            (None, PublishTarget::NewEvent { title }) => {
                let ordinal = self.next_event_ordinal;
                self.next_event_ordinal = self.next_event_ordinal.saturating_add(1);
                self.events.push(TeamEvent::new(
                    EventId::new(self.tag, ordinal),
                    title,
                    actor,
                    revision,
                ));
                self.events.len() - 1
            }
            (None, PublishTarget::ExistingEvent { .. }) => {
                unreachable!("an existing-event target always resolves to an index above")
            }
        };

        // The root's own entries start as tracking and never wake the root; anyone else's start
        // as pending and give the root a coordination opportunity.
        let root_state = if role.is_root() {
            RootState::Tracking
        } else {
            RootState::Pending
        };
        let authored_on_stale_view = previously_changed_at
            .filter(|changed_at| *changed_at > submission.based_on)
            .map(|_| submission.based_on);
        let event = &mut self.events[event_index];
        let version_id = VersionId::new(
            self.tag,
            event.id().ordinal(),
            u32::try_from(event.versions().len().saturating_add(1)).unwrap_or(u32::MAX),
        );
        event.versions.push(TeamVersion::new(
            version_id,
            AuthoredVersion {
                author: actor,
                summary,
                handoff,
                evidence_refs: Vec::new(),
            },
            root_state,
            revision,
            authored_on_stale_view,
        ));
        event.last_changed_at = revision;
        let event_id = event.id();
        self.revision = revision;

        if !role.is_root() {
            self.wake_root();
        }

        let outcome = PublishOutcome {
            event_id,
            version_id,
            revision,
            authored_on_stale_view: authored_on_stale_view.is_some(),
            deduplicated: false,
        };
        self.committed.insert(retry_key, outcome.clone());
        Ok(outcome)
    }

    /// Apply an all-or-nothing batch of lifecycle changes.
    pub fn update_lifecycle(
        &mut self,
        actor: ThreadId,
        request: LifecycleRequest,
    ) -> Result<LifecycleOutcome, TeamError> {
        let role = self.require_participant(actor)?.role;
        if request.targets.is_empty() {
            return Err(TeamError::InvalidRequest {
                reason: "at least one target is required",
            });
        }

        // Validate every target first; nothing is written until all of them pass.
        let mut resolved = Vec::with_capacity(request.targets.len());
        for target in &request.targets {
            let (event_index, version_index) = self.locate_version(target.version_id)?;
            let version = &self.events[event_index].versions[version_index];
            match target.change {
                LifecycleChange::CloseProducer => {
                    if version.authored().author != actor {
                        return Err(TeamError::NotPermitted {
                            reason: "only the author of a version may close it",
                        });
                    }
                    if version.producer_state() == ProducerState::Closed {
                        return Err(TeamError::VersionClosed {
                            version_id: target.version_id,
                        });
                    }
                }
                LifecycleChange::SetRootState(_) => {
                    if !role.is_root() {
                        return Err(TeamError::NotPermitted {
                            reason: "only the root may change root attention state",
                        });
                    }
                }
            }
            if version.producer_state() != target.expected_producer_state
                || version.root_state() != target.expected_root_state
            {
                return Err(TeamError::LifecycleConflict {
                    current: LifecycleSnapshot {
                        version_id: target.version_id,
                        producer_state: version.producer_state(),
                        root_state: version.root_state(),
                    },
                });
            }
            resolved.push((event_index, version_index, *target));
        }

        let revision = self.revision.next();
        let mut updated = Vec::with_capacity(resolved.len());
        let mut wake_root = false;
        for (event_index, version_index, target) in resolved {
            let event = &mut self.events[event_index];
            let version = &mut event.versions[version_index];
            match target.change {
                LifecycleChange::CloseProducer => {
                    version.producer_state = ProducerState::Closed;
                    // Closing something the root has not finished with gives the root another
                    // coordination opportunity; closing something already resolved does not.
                    wake_root |= version.root_state.occupies_root_attention();
                }
                LifecycleChange::SetRootState(state) => version.root_state = state,
            }
            updated.push(LifecycleSnapshot {
                version_id: target.version_id,
                producer_state: version.producer_state,
                root_state: version.root_state,
            });
            event.last_changed_at = revision;
        }
        self.revision = revision;
        if wake_root {
            self.wake_root();
        }

        Ok(LifecycleOutcome { revision, updated })
    }

    /// The active view for one participant, as of right now.
    pub fn snapshot_for(&self, viewer: ThreadId) -> Result<TeamSnapshot, TeamError> {
        let participant = self.require_participant(viewer)?;
        let role = participant.role;
        let viewer_label = participant.label.clone();
        let events = self
            .events
            .iter()
            .filter(|event| event.is_active_for(viewer, role))
            .map(|event| self.event_view(event))
            .collect();
        Ok(TeamSnapshot {
            instance: self.instance,
            revision: self.revision,
            viewer,
            viewer_label,
            viewer_role: role,
            events,
        })
    }

    fn event_view(&self, event: &TeamEvent) -> EventView {
        EventView {
            id: event.id(),
            title: event.title().to_string(),
            versions: event
                .versions()
                .iter()
                .map(|version| VersionView {
                    id: version.id(),
                    author_label: self.label_of(version.authored().author),
                    summary: version.authored().summary.clone(),
                    handoff: version.authored().handoff.clone(),
                    producer_state: version.producer_state(),
                    root_state: version.root_state(),
                    authored_on_stale_view: version.authored_on_stale_view().is_some(),
                })
                .collect(),
        }
    }

    /// Bounded, permission-scoped history read.
    ///
    /// Leaving the active view never deletes anything: this is how a participant gets back to
    /// entries the projection has dropped.
    pub fn history(
        &self,
        viewer: ThreadId,
        query: &HistoryQuery,
    ) -> Result<HistoryPage, TeamError> {
        let participant = self.require_participant(viewer)?;
        let role = participant.role;
        let limit = query
            .limit
            .unwrap_or(DEFAULT_HISTORY_LIMIT)
            .clamp(1, MAX_HISTORY_LIMIT);

        if let Some(event_id) = query.event_id {
            let index = self.event_index(event_id)?;
            let event = &self.events[index];
            if !event.is_readable_by(viewer, role) {
                return Err(TeamError::NotPermitted {
                    reason: "this event is not visible to you",
                });
            }
            let total_versions = event.versions().len();
            let mut view = self.event_view(event);
            // Keep the newest entries when the chain is longer than the caller asked for.
            let dropped = total_versions.saturating_sub(limit);
            view.versions.drain(..dropped);
            return Ok(HistoryPage {
                instance: self.instance,
                revision: self.revision,
                events: vec![EventHistory {
                    event: view,
                    total_versions,
                    omitted_versions: dropped,
                }],
                total_events: 1,
                omitted_events: 0,
            });
        }

        let readable: Vec<&TeamEvent> = self
            .events
            .iter()
            .filter(|event| event.is_readable_by(viewer, role))
            .collect();
        let total_events = readable.len();
        let omitted_events = total_events.saturating_sub(limit);
        let events = readable
            .into_iter()
            .skip(omitted_events)
            .map(|event| {
                let total_versions = event.versions().len();
                EventHistory {
                    event: self.event_view(event),
                    total_versions,
                    omitted_versions: 0,
                }
            })
            .collect();
        Ok(HistoryPage {
            instance: self.instance,
            revision: self.revision,
            events,
            total_events,
            omitted_events,
        })
    }

    fn wake_root(&mut self) {
        let roots: Vec<ThreadId> = self
            .participants
            .values()
            .filter(|participant| participant.role.is_root())
            .map(|participant| participant.thread_id)
            .collect();
        for root in roots {
            self.wake.signal(root);
        }
    }

    pub fn has_pending_wake(&self, participant: ThreadId) -> bool {
        self.wake.has_pending(participant)
    }

    /// Take the pending wake for a participant, if any. Consuming it is what stops an already
    /// handled change from waking the same participant again.
    pub fn consume_wake(&mut self, participant: ThreadId) -> bool {
        self.wake.consume(participant)
    }
}

#[cfg(test)]
#[path = "store_tests.rs"]
mod tests;
