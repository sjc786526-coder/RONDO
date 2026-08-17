//! The canonical team state for one live root tree.
//!
//! This type owns every invariant. It is deliberately synchronous and lock-free on its own: the
//! handle wraps it in a single mutex so each mutation checks preconditions and commits without an
//! intervening await, which is what makes concurrent appends, retries and racing lifecycle changes
//! well defined.

use crate::evidence::PendingObservation;
use crate::evidence::TeamFact;
use crate::ids::EventId;
use crate::ids::InstanceTag;
use crate::ids::RouteId;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::ids::VersionId;
use crate::model::AuthoredVersion;
use crate::model::Participant;
use crate::model::ParticipantRole;
use crate::model::ProducerState;
use crate::model::RootState;
use crate::model::TeamEvent;
use crate::model::TeamRoute;
use crate::model::TeamVersion;
use crate::model::clamp_handoff;
use crate::model::clamp_summary;
use crate::model::clamp_title;
use crate::mutation::LifecycleChange;
use crate::mutation::LifecycleOutcome;
use crate::mutation::LifecycleRequest;
use crate::mutation::LifecycleSnapshot;
use crate::mutation::PublishOutcome;
use crate::mutation::PublishRequest;
use crate::mutation::PublishTarget;
use crate::mutation::RouteRequest;
use crate::mutation::Submission;
use crate::mutation::TeamError;
use crate::view::EventHistory;
use crate::view::EventView;
use crate::view::HistoryPage;
use crate::view::HistoryQuery;
use crate::view::RouteView;
use crate::view::TeamSnapshot;
use crate::view::VersionView;
use crate::wake::WakeLedger;
use codex_protocol::ThreadId;
use std::collections::HashMap;
use std::collections::VecDeque;

/// Evidence capture and read permission follow the same pattern: a child module with its own
/// invariants, reaching the same private state under the same single lock.
pub(crate) mod evidence;
/// Selective routing lives in a child module so this file stays the single place that defines the
/// publish and lifecycle invariants, while route commits still reach the same private state and
/// follow the same validate-everything-then-commit-once discipline.
pub(crate) mod route;

/// Hard ceiling on a single bounded history query, so a drill-down can never become unbounded.
pub const MAX_HISTORY_LIMIT: usize = 50;
const DEFAULT_HISTORY_LIMIT: usize = 10;
/// In list mode each event only previews its newest entries; the full chain comes from an
/// event-scoped query, which is itself pageable. Without this a "bounded" list of 50 events could
/// still drag in every version the team ever wrote.
const LIST_MODE_VERSION_PREVIEW: usize = 2;

/// The two independent lifecycle axes of a version.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum LifecycleAxis {
    Producer,
    Root,
}

impl LifecycleAxis {
    fn of(change: LifecycleChange) -> Self {
        match change {
            LifecycleChange::CloseProducer => Self::Producer,
            LifecycleChange::SetRootState(_) => Self::Root,
        }
    }
}

/// The request half of a committed submission.
///
/// Every kind of submission shares one retry namespace per actor. Reusing an identity across kinds
/// is therefore refused rather than silently treated as a fresh operation of the other kind, which
/// is the same rule as reusing it for different content.
#[derive(Clone, Debug, Eq, PartialEq)]
enum CommittedRequest {
    Publish(PublishRequest),
    Route(RouteRequest),
}

#[derive(Clone, Debug)]
enum CommittedOutcome {
    /// A publish outcome is entirely made of facts fixed at commit time, so keeping it is safe.
    Publish(PublishOutcome),
    /// Only the route's identity is remembered. Its delivery state goes on changing after the
    /// commit, and a snapshot taken here would be taken before the notice was even attempted — a
    /// replay would then report `pending` over a failure that is meant to be visible and retryable.
    Route { route_id: RouteId },
}

struct CommittedSubmission {
    /// The request as submitted. Comparing the structure itself is what makes "is this the same
    /// submission?" exact; any flattening into a string has to answer that question with an
    /// encoding, and an encoding of model-controlled text can be made to collide.
    request: CommittedRequest,
    outcome: CommittedOutcome,
}

pub struct TeamStore {
    instance: TeamInstanceId,
    tag: InstanceTag,
    revision: TeamRevision,
    events: Vec<TeamEvent>,
    participants: HashMap<ThreadId, Participant>,
    /// Committed submissions keyed by author and retry identity, so a repeated submission returns
    /// the original result instead of minting a second object. The original request is kept
    /// alongside the outcome: reusing an identity for different content is a caller mistake, not a
    /// retry, and must not silently discard the second piece of content.
    committed: HashMap<(ThreadId, String), CommittedSubmission>,
    wake: WakeLedger,
    next_event_ordinal: u32,
    /// Recorded evidence, in the order Codex's retention of it was confirmed.
    facts: Vec<TeamFact>,
    /// Observations seen but not yet confirmed retained. Bounded; see `MAX_PENDING_OBSERVATIONS`.
    pending_observations: VecDeque<PendingObservation>,
    next_fact_ordinal: u32,
    /// Per-producer publication cursor: the highest fact ordinal of its own that it has published.
    published_facts_through: HashMap<ThreadId, u32>,
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
            facts: Vec::new(),
            pending_observations: VecDeque::new(),
            next_fact_ordinal: 1,
            published_facts_through: HashMap::new(),
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
        let original_request = CommittedRequest::Publish(request.clone());
        if let Some(existing) = self.committed.get(&retry_key) {
            if existing.request != original_request {
                return Err(TeamError::RetryIdentityReused);
            }
            let CommittedOutcome::Publish(outcome) = &existing.outcome else {
                // The same identity already stands for a route. Treating it as a fresh publish
                // would put two different objects behind one retry identity.
                return Err(TeamError::RetryIdentityReused);
            };
            return Ok(PublishOutcome {
                deduplicated: true,
                ..outcome.clone()
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
            PublishTarget::ExistingEvent { event_id } => {
                let index = self.event_index(*event_id)?;
                // Contributing requires already being able to see the event. Without this, an
                // identifier — which is guessable, being an instance tag plus a small ordinal —
                // would be enough to write into a sibling's event and, by becoming one of its
                // authors, to read the whole chain afterwards.
                if !self.events[index].is_visible_to(actor, role) {
                    return Err(TeamError::NotPermitted {
                        reason: "this event is not visible to you, so you cannot add to it",
                    });
                }
                Some(index)
            }
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
                    clamp_title(&title),
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
        // Evidence is attached mechanically, from what this author has recorded since its last
        // successful publish. The model is never asked to list it, and everything after this point
        // is infallible, so taking the window here is the same step as committing the version.
        let (evidence_refs, evidence_refs_omitted) = self.take_publish_window(actor);
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
                summary: clamp_summary(&summary),
                handoff: handoff.as_deref().map(clamp_handoff),
                evidence_refs: evidence_refs.clone(),
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
            evidence_refs,
            evidence_refs_omitted,
            authored_on_stale_view: authored_on_stale_view.is_some(),
            deduplicated: false,
        };
        self.committed.insert(
            retry_key,
            CommittedSubmission {
                request: original_request,
                outcome: CommittedOutcome::Publish(outcome.clone()),
            },
        );
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
        //
        // Each target is checked against the state as it stands before the batch, so a batch that
        // named the same version twice on the same axis could have both halves pass against the
        // old state and then apply in sequence — which is how a terminal state would be walked
        // around. Naming an axis twice is refused instead. The producer and root axes are
        // independent, so touching both in one batch stays legal.
        let mut claimed: Vec<(VersionId, LifecycleAxis)> = Vec::new();
        let mut resolved = Vec::with_capacity(request.targets.len());
        for target in &request.targets {
            let axis = LifecycleAxis::of(target.change);
            if claimed.contains(&(target.version_id, axis)) {
                return Err(TeamError::ConflictingTargets {
                    version_id: target.version_id,
                });
            }
            claimed.push((target.version_id, axis));

            let (event_index, version_index) = self.locate_version(target.version_id)?;
            let version = &self.events[event_index].versions[version_index];

            // Who may act comes first, then whether the caller's picture is still current, and only
            // then whether the transition is legal. A caller working from a stale picture has to
            // learn the current state rather than a rule about a state it did not know about.
            match target.change {
                LifecycleChange::CloseProducer if version.authored().author != actor => {
                    return Err(TeamError::NotPermitted {
                        reason: "only the author of a version may close it",
                    });
                }
                LifecycleChange::SetRootState(_) if !role.is_root() => {
                    return Err(TeamError::NotPermitted {
                        reason: "only the root may change root attention state",
                    });
                }
                _ => {}
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
            match target.change {
                LifecycleChange::CloseProducer
                    if version.producer_state() == ProducerState::Closed =>
                {
                    return Err(TeamError::VersionClosed {
                        version_id: target.version_id,
                    });
                }
                // `resolved` ends coordination on this entry for good. Walking it back would pull
                // an old entry into the active view in place; the way to make a matter current
                // again is to publish a new version of it.
                LifecycleChange::SetRootState(_) if version.root_state() == RootState::Resolved => {
                    return Err(TeamError::RootAttentionResolved {
                        version_id: target.version_id,
                    });
                }
                _ => {}
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
            .map(|event| self.event_view(viewer, role, event))
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

    /// Render one event for `viewer`.
    ///
    /// Routes are scoped rather than listed wholesale: the root coordinates the team and sees them
    /// all, while a member is only shown the ones addressed to it. Who else was handed the same
    /// event is the root's coordination picture, and selective propagation is worth little if the
    /// view leaks it back out.
    fn event_view(&self, viewer: ThreadId, role: ParticipantRole, event: &TeamEvent) -> EventView {
        EventView {
            id: event.id(),
            title: event.title().to_string(),
            versions: event
                .versions()
                .iter()
                .map(|version| self.version_view(version))
                .collect(),
            routes: event
                .routes()
                .iter()
                .filter(|route| role.is_root() || route.target() == viewer)
                .map(|route| self.route_view(route))
                .collect(),
        }
    }

    fn route_view(&self, route: &TeamRoute) -> RouteView {
        RouteView {
            id: route.id(),
            target_label: self.label_of(route.target()),
            duty: route.duty(),
            delivery: route.delivery().clone(),
            note: route.note().map(str::to_string),
        }
    }

    fn version_view(&self, version: &TeamVersion) -> VersionView {
        VersionView {
            id: version.id(),
            author_label: self.label_of(version.authored().author),
            summary: version.authored().summary.clone(),
            handoff: version.authored().handoff.clone(),
            // The references travel with the entry that authored them, which is what lets a reader
            // that may see this version go on to ask for the observations behind it.
            evidence_refs: version.authored().evidence_refs.clone(),
            producer_state: version.producer_state(),
            root_state: version.root_state(),
            authored_on_stale_view: version.authored_on_stale_view().is_some(),
        }
    }

    /// Bounded, permission-scoped history read.
    ///
    /// Leaving the active view never deletes anything, so this is how a participant gets back to
    /// entries the projection dropped. Every mode is both capped and pageable: the cap keeps a
    /// single answer bounded, and the cursor is what makes the material behind the cap reachable
    /// rather than merely reported as missing.
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

        match query.event_id {
            Some(event_id) => self.event_history(viewer, role, event_id, query.before, limit),
            None => Ok(self.event_list(viewer, role, query.before, limit)),
        }
    }

    /// One event's chain, newest first, walking backwards from `before`.
    fn event_history(
        &self,
        viewer: ThreadId,
        role: ParticipantRole,
        event_id: EventId,
        before: Option<u32>,
        limit: usize,
    ) -> Result<HistoryPage, TeamError> {
        let index = self.event_index(event_id)?;
        let event = &self.events[index];
        if !event.is_visible_to(viewer, role) {
            return Err(TeamError::NotPermitted {
                reason: "this event is not visible to you",
            });
        }

        let total_versions = event.versions().len();
        let eligible: Vec<&TeamVersion> = event
            .versions()
            .iter()
            .filter(|version| before.is_none_or(|before| version.id().ordinal() < before))
            .collect();
        let dropped = eligible.len().saturating_sub(limit);
        let window: Vec<&TeamVersion> = eligible.into_iter().skip(dropped).collect();
        // The oldest entry returned is where the next page picks up.
        let next_before = (dropped > 0)
            .then(|| window.first().map(|version| version.id().ordinal()))
            .flatten();

        let mut view = self.event_view(viewer, role, event);
        view.versions = window
            .iter()
            .map(|version| self.version_view(version))
            .collect();
        Ok(HistoryPage {
            instance: self.instance,
            revision: self.revision,
            events: vec![EventHistory {
                event: view,
                total_versions,
                omitted_versions: dropped,
            }],
            total_events: 1,
            omitted_events: 0,
            next_before,
        })
    }

    /// The events this participant may read, newest first, walking backwards from `before`.
    ///
    /// Each event only previews its newest entries; the rest is reached by querying that event.
    fn event_list(
        &self,
        viewer: ThreadId,
        role: ParticipantRole,
        before: Option<u32>,
        limit: usize,
    ) -> HistoryPage {
        let visible: Vec<&TeamEvent> = self
            .events
            .iter()
            .filter(|event| event.is_visible_to(viewer, role))
            .collect();
        let total_events = visible.len();
        let eligible: Vec<&TeamEvent> = visible
            .into_iter()
            .filter(|event| before.is_none_or(|before| event.id().ordinal() < before))
            .collect();
        let dropped = eligible.len().saturating_sub(limit);
        let window: Vec<&TeamEvent> = eligible.into_iter().skip(dropped).collect();
        let next_before = (dropped > 0)
            .then(|| window.first().map(|event| event.id().ordinal()))
            .flatten();

        let events = window
            .into_iter()
            .map(|event| {
                let total_versions = event.versions().len();
                let preview_dropped = total_versions.saturating_sub(LIST_MODE_VERSION_PREVIEW);
                let mut view = self.event_view(viewer, role, event);
                view.versions.drain(..preview_dropped);
                EventHistory {
                    event: view,
                    total_versions,
                    omitted_versions: preview_dropped,
                }
            })
            .collect();
        HistoryPage {
            instance: self.instance,
            revision: self.revision,
            events,
            total_events,
            omitted_events: dropped,
            next_before,
        }
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
