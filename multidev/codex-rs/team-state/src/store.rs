//! The canonical team state for one live root tree.
//!
//! This type owns every invariant. It is deliberately synchronous and lock-free on its own: the
//! handle wraps it in a single mutex so each mutation checks preconditions and commits without an
//! intervening await, which is what makes concurrent appends, retries and racing lifecycle changes
//! well defined.

use crate::durable::DurableTeamIdentity;
use crate::durable::TeamDurabilityError;
use crate::evidence::PendingObservation;
use crate::evidence::TeamFact;
use crate::ids::EventId;
use crate::ids::InstanceTag;
use crate::ids::RouteId;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::ids::VersionId;
use crate::model::Participant;
use crate::model::ParticipantRole;
use crate::model::ProducerState;
use crate::model::RootState;
use crate::model::TeamEvent;
use crate::model::TeamRoute;
use crate::model::TeamVersion;
use crate::model::clamp_delivery_reason;
use crate::model::clamp_handoff;
use crate::model::clamp_retire_reason;
use crate::model::clamp_route_note;
use crate::model::clamp_summary;
use crate::model::clamp_title;
use crate::mutation::LifecycleChange;
use crate::mutation::LifecycleOutcome;
use crate::mutation::LifecycleRequest;
use crate::mutation::LifecycleSnapshot;
use crate::mutation::PublishOutcome;
use crate::mutation::PublishRequest;
use crate::mutation::PublishTarget;
use crate::mutation::RetireOutcome;
use crate::mutation::RetireRequest;
use crate::mutation::RouteIntent;
use crate::mutation::RouteRequest;
use crate::mutation::TeamError;
use crate::observe::ChangeKind;
use crate::observe::ChangeRecord;
use crate::observe::StoredWake;
use crate::view::EventHistory;
use crate::view::EventView;
use crate::view::HistoryPage;
use crate::view::HistoryQuery;
use crate::view::RouteView;
use crate::view::TeamSnapshot;
use crate::view::VersionView;
use crate::wake::WakeLedger;
use codex_protocol::ThreadId;
use serde::Deserialize;
use serde::Serialize;
use std::collections::HashMap;
use std::collections::HashSet;
use std::collections::VecDeque;

/// Evidence capture and read permission follow the same pattern: a child module with its own
/// invariants, reaching the same private state under the same single lock.
pub(crate) mod evidence;
pub(crate) mod observe;
/// Publish preparation and commit share one validation path while reaching this same private state.
pub(crate) mod publish;
pub(crate) mod retire;
/// Selective routing lives in a child module while route commits still reach the same private state
/// and follow the same validate-everything-then-commit-once discipline.
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
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
enum CommittedRequest {
    Publish(PublishRequest),
    Route(RouteRequest),
    Retire(RetireRequest),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
enum CommittedOutcome {
    /// A publish outcome is entirely made of facts fixed at commit time, so keeping it is safe.
    Publish(PublishOutcome),
    /// Only the route's identity is remembered. Its delivery state goes on changing after the
    /// commit, and a snapshot taken here would be taken before the notice was even attempted — a
    /// replay would then report `pending` over a failure that is meant to be visible and retryable.
    Route {
        route_id: RouteId,
    },
    Retire(RetireOutcome),
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct CommittedSubmission {
    /// The request as submitted. Comparing the structure itself is what makes "is this the same
    /// submission?" exact; any flattening into a string has to answer that question with an
    /// encoding, and an encoding of model-controlled text can be made to collide.
    request: CommittedRequest,
    outcome: CommittedOutcome,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
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
    #[serde(with = "committed_submissions")]
    committed: HashMap<(ThreadId, String), CommittedSubmission>,
    wake: WakeLedger,
    next_event_ordinal: u32,
    /// Recorded evidence, in the order Codex's retention of it was confirmed.
    facts: Vec<TeamFact>,
    /// Observations seen but not yet confirmed retained. Entries normally live only between tool
    /// completion and the ordered history-retention pass; discarded results are revoked explicitly.
    #[serde(skip, default)]
    pending_observations: VecDeque<PendingObservation>,
    next_fact_ordinal: u32,
    /// Per-producer publication cursor: the highest fact ordinal of its own that it has published.
    published_facts_through: HashMap<ThreadId, u32>,
    change_log: Vec<ChangeRecord>,
    /// Advances when dump layout can change without a team revision, currently fact minting and
    /// new participant registration. Dump cursors carry it so a page cannot silently skip or
    /// repeat those rows.
    observe_generation: u64,
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
            change_log: Vec::new(),
            observe_generation: 0,
        }
    }

    /// Compare only the state represented by a durable snapshot. Hash-map equality is semantic
    /// and independent of randomized iteration order; pending observations are deliberately
    /// excluded because they exist only between live capture and history retention.
    pub(crate) fn same_durable_state(&self, other: &Self) -> bool {
        self.instance == other.instance
            && self.tag == other.tag
            && self.revision == other.revision
            && self.events == other.events
            && self.participants == other.participants
            && self.committed == other.committed
            && self.wake == other.wake
            && self.next_event_ordinal == other.next_event_ordinal
            && self.facts == other.facts
            && self.next_fact_ordinal == other.next_fact_ordinal
            && self.published_facts_through == other.published_facts_through
            && self.change_log == other.change_log
            && self.observe_generation == other.observe_generation
    }

    /// Restore live observations that still have no committed Fact in a hydrated snapshot.
    /// Reconciliation must not lose unrelated capture work, nor resurrect the observation whose
    /// confirmation is already present in the committed generation.
    pub(crate) fn restore_uncommitted_observations_from(&mut self, live: &Self) {
        let mut seen = HashSet::new();
        self.pending_observations = live
            .pending_observations
            .iter()
            .filter(|pending| self.participants.contains_key(&pending.producer))
            .filter(|pending| {
                !self.facts.iter().any(|fact| {
                    fact.producer() == pending.producer
                        && fact.locator().item_id == pending.noted.item_id
                })
            })
            .filter(|pending| seen.insert((pending.producer, pending.noted.item_id.clone())))
            .cloned()
            .collect();
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
                self.observe_generation = self.observe_generation.saturating_add(1);
                true
            }
        }
    }

    pub(crate) fn register_durable_participant(
        &mut self,
        identity: DurableTeamIdentity,
        thread_id: ThreadId,
        role: ParticipantRole,
        label: String,
    ) -> Result<bool, TeamDurabilityError> {
        if role.is_root() != (thread_id == identity.root_thread_id()) {
            return Err(TeamDurabilityError::IdentityMismatch);
        }
        if let Some(existing) = self.participants.get(&thread_id) {
            if existing.role == role && existing.label == label {
                return Ok(false);
            }
            return Err(TeamDurabilityError::conflict(
                "durable participant registration disagrees with the committed identity",
            ));
        }
        if role.is_root()
            && self
                .participants
                .values()
                .any(|participant| participant.role.is_root())
        {
            return Err(TeamDurabilityError::conflict(
                "a durable Team cannot register a second Root",
            ));
        }
        if !role.is_root() && !self.participants.contains_key(&identity.root_thread_id()) {
            return Err(TeamDurabilityError::conflict(
                "the authoritative Root must be registered before durable members",
            ));
        }
        Ok(self.register_participant(thread_id, role, label))
    }

    pub fn participant(&self, thread_id: ThreadId) -> Option<&Participant> {
        self.participants.get(&thread_id)
    }

    /// Registered participants, sorted by label then thread id so diagnostics do not depend on
    /// HashMap iteration order.
    pub fn participants(&self) -> Vec<Participant> {
        let mut participants: Vec<Participant> = self.participants.values().cloned().collect();
        participants.sort_by(|left, right| {
            left.label
                .cmp(&right.label)
                .then_with(|| left.thread_id.to_string().cmp(&right.thread_id.to_string()))
        });
        participants
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
                LifecycleChange::CloseProducer if version.is_retired() => {
                    return Err(TeamError::VersionRetired {
                        version_id: target.version_id,
                    });
                }
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

        let mut updated = Vec::with_capacity(resolved.len());
        let mut meaningful = Vec::new();
        for (event_index, version_index, target) in resolved {
            let version = &self.events[event_index].versions[version_index];
            let changes = match target.change {
                LifecycleChange::CloseProducer => version.producer_state() != ProducerState::Closed,
                LifecycleChange::SetRootState(state) => version.root_state() != state,
            };
            updated.push(LifecycleSnapshot {
                version_id: target.version_id,
                producer_state: match target.change {
                    LifecycleChange::CloseProducer => ProducerState::Closed,
                    LifecycleChange::SetRootState(_) => version.producer_state(),
                },
                root_state: match target.change {
                    LifecycleChange::CloseProducer => version.root_state(),
                    LifecycleChange::SetRootState(state) => state,
                },
            });
            if changes {
                meaningful.push((event_index, version_index, target));
            }
        }
        if meaningful.is_empty() {
            return Ok(LifecycleOutcome {
                revision: self.revision,
                updated,
                changed: false,
            });
        }

        let revision = self.revision.next();
        let root_id = self.root_id();
        for (event_index, version_index, target) in meaningful {
            let event = &mut self.events[event_index];
            let version = &mut event.versions[version_index];
            let before = format!(
                "producer={} root={}",
                version.producer_state, version.root_state
            );
            let (kind, wake) = match target.change {
                LifecycleChange::CloseProducer => {
                    version.producer_state = ProducerState::Closed;
                    let occupies = version.root_state.occupies_root_attention();
                    (
                        ChangeKind::CloseProducer,
                        if occupies {
                            if let Some(root_id) = root_id {
                                self.wake.signal(root_id);
                                StoredWake::signalled(root_id, "producer_closed_while_root_active")
                            } else {
                                StoredWake::none("producer_closed_while_root_active")
                            }
                        } else {
                            StoredWake::none("producer_closed_after_root_resolved")
                        },
                    )
                }
                LifecycleChange::SetRootState(state) => {
                    version.root_state = state;
                    (
                        ChangeKind::SetRootState,
                        StoredWake::none("root_does_not_self_wake"),
                    )
                }
            };
            let after = format!(
                "producer={} root={}",
                version.producer_state, version.root_state
            );
            event.last_changed_at = revision;
            self.change_log.push(ChangeRecord {
                revision,
                actor,
                kind,
                target: target.version_id.to_string(),
                before: Some(before),
                after: Some(after),
                wake,
            });
        }
        self.revision = revision;

        Ok(LifecycleOutcome {
            revision,
            updated,
            changed: true,
        })
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
            availability_epoch: None,
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
            author: version.authored().author,
            author_label: self.label_of(version.authored().author),
            summary: version.authored().summary.clone(),
            handoff: version.authored().handoff.clone(),
            // The references travel with the entry that authored them, which is what lets a reader
            // that may see this version go on to ask for the observations behind it.
            evidence_refs: version.authored().evidence_refs.clone(),
            producer_state: version.producer_state(),
            root_state: version.root_state(),
            authored_on_stale_view: version.authored_on_stale_view().is_some(),
            retired: version.is_retired(),
            producer_availability: None,
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
        if let Some(root) = self.root_id() {
            self.wake.signal(root);
        }
    }

    fn root_id(&self) -> Option<ThreadId> {
        self.participants
            .values()
            .find(|participant| participant.role.is_root())
            .map(|participant| participant.thread_id)
    }

    fn root_wake(&self, rule: &'static str) -> StoredWake {
        match self.root_id() {
            Some(participant) => StoredWake::signalled(participant, rule),
            None => StoredWake::none(rule),
        }
    }

    fn push_change(&mut self, record: ChangeRecord) {
        self.change_log.push(record);
    }

    pub fn has_pending_wake(&self, participant: ThreadId) -> bool {
        self.wake.has_pending(participant)
    }

    /// Take the pending wake for a participant, if any. Consuming it is what stops an already
    /// handled change from waking the same participant again.
    pub fn consume_wake(&mut self, participant: ThreadId) -> bool {
        self.wake.consume(participant)
    }

    /// Refuse any decoded state that could not have been produced by this store's mutation paths.
    /// This is intentionally stricter than serde shape checking: a valid-looking graph with a
    /// forged root, dangling reference, rewound counter, or impossible lifecycle is not hydrated.
    pub(crate) fn validate_durable(
        &self,
        identity: DurableTeamIdentity,
    ) -> Result<(), TeamDurabilityError> {
        let corrupt = |message: &str| TeamDurabilityError::corrupt(message);
        if self.instance.tag() != self.tag {
            return Err(corrupt("Team instance and instance tag disagree"));
        }
        let mut participant_ids = HashSet::with_capacity(self.participants.len());
        let mut roots = Vec::new();
        for (id, participant) in &self.participants {
            if *id != participant.thread_id {
                return Err(corrupt("participant map key does not match its record"));
            }
            if participant.label.chars().count() > 4_096 {
                return Err(corrupt("participant label exceeds the durable bound"));
            }
            participant_ids.insert(*id);
            if participant.role.is_root() {
                roots.push(*id);
            }
        }
        if roots.as_slice() != [identity.root_thread_id()] {
            return Err(corrupt(
                "snapshot does not contain exactly its authoritative root",
            ));
        }
        let expected_observe_generation = self
            .participants
            .len()
            .checked_add(self.facts.len())
            .and_then(|value| u64::try_from(value).ok())
            .ok_or_else(|| corrupt("observe generation overflows"))?;
        if self.observe_generation != expected_observe_generation {
            return Err(corrupt(
                "observe generation does not match participants and facts",
            ));
        }
        if !self.wake.references_only(&participant_ids) {
            return Err(corrupt(
                "wake ledger contains an impossible participant or counter",
            ));
        }

        let expected_next_event = u32::try_from(self.events.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or_else(|| corrupt("event ordinal space is exhausted"))?;
        if self.next_event_ordinal != expected_next_event {
            return Err(corrupt(
                "next event ordinal does not follow the event sequence",
            ));
        }
        let expected_next_fact = u32::try_from(self.facts.len())
            .ok()
            .and_then(|value| value.checked_add(1))
            .ok_or_else(|| corrupt("fact ordinal space is exhausted"))?;
        if self.next_fact_ordinal != expected_next_fact {
            return Err(corrupt(
                "next fact ordinal does not follow the fact sequence",
            ));
        }

        let mut fact_items = HashSet::with_capacity(self.facts.len());
        for (index, fact) in self.facts.iter().enumerate() {
            let ordinal =
                u32::try_from(index + 1).map_err(|_| corrupt("fact ordinal space is exhausted"))?;
            if fact.id().instance() != self.tag || fact.id().ordinal() != ordinal {
                return Err(corrupt("fact identity is not in canonical sequence"));
            }
            if !participant_ids.contains(&fact.producer()) {
                return Err(corrupt("fact producer is not a participant"));
            }
            if fact.locator().item_id.is_empty()
                || fact.locator().call_id.is_empty()
                || fact.locator().tool.is_empty()
            {
                return Err(corrupt("fact locator contains an empty identity"));
            }
            if !fact_items.insert((fact.producer(), fact.locator().item_id.as_str())) {
                return Err(corrupt("fact item identity is duplicated for its producer"));
            }
        }

        let mut version_ids = HashSet::new();
        let mut route_ids = HashSet::new();
        for (event_index, event) in self.events.iter().enumerate() {
            let ordinal = u32::try_from(event_index + 1)
                .map_err(|_| corrupt("event ordinal space is exhausted"))?;
            if event.id().instance() != self.tag || event.id().ordinal() != ordinal {
                return Err(corrupt("event identity is not in canonical sequence"));
            }
            if !participant_ids.contains(&event.created_by())
                || event.versions().is_empty()
                || clamp_title(event.title()) != event.title()
                || event.created_at() == TeamRevision::INITIAL
                || event.created_at() > event.last_changed_at()
                || event.last_changed_at() > self.revision
            {
                return Err(corrupt("event record has impossible metadata"));
            }
            for (version_index, version) in event.versions().iter().enumerate() {
                let version_ordinal = u32::try_from(version_index + 1)
                    .map_err(|_| corrupt("version ordinal space is exhausted"))?;
                if version.id().instance() != self.tag
                    || version.id().event_id() != event.id()
                    || version.id().ordinal() != version_ordinal
                    || !participant_ids.contains(&version.authored().author)
                    || clamp_summary(&version.authored().summary) != version.authored().summary
                    || version
                        .authored()
                        .handoff
                        .as_deref()
                        .is_some_and(|value| clamp_handoff(value) != value)
                    || version.created_at() < event.created_at()
                    || version.created_at() > event.last_changed_at()
                    || version
                        .authored_on_stale_view()
                        .is_some_and(|revision| revision > version.created_at())
                {
                    return Err(corrupt("version record has impossible metadata"));
                }
                let mut previous_fact = 0;
                for fact_id in &version.authored().evidence_refs {
                    let fact = self
                        .facts
                        .iter()
                        .find(|fact| fact.id() == *fact_id)
                        .ok_or_else(|| corrupt("version references an unknown fact"))?;
                    if fact.producer() != version.authored().author
                        || fact_id.ordinal() <= previous_fact
                    {
                        return Err(corrupt("version evidence window is not canonical"));
                    }
                    previous_fact = fact_id.ordinal();
                }
                if let Some(retirement) = version.retirement()
                    && (version.producer_state() != ProducerState::Open
                        || retirement.retired_by != identity.root_thread_id()
                        || !retirement.availability.is_unavailable()
                        || retirement.retired_at < version.created_at()
                        || retirement.retired_at > event.last_changed_at()
                        || retirement.reason.trim().is_empty()
                        || clamp_retire_reason(&retirement.reason) != retirement.reason)
                {
                    return Err(corrupt("version retirement is impossible"));
                }
                version_ids.insert(version.id());
            }

            let mut assigned_targets = HashSet::new();
            for (route_index, route) in event.routes().iter().enumerate() {
                let route_ordinal = u32::try_from(route_index + 1)
                    .map_err(|_| corrupt("route ordinal space is exhausted"))?;
                if route.id().instance() != self.tag
                    || route.id().event_id() != event.id()
                    || route.id().ordinal() != route_ordinal
                    || route.routed_by() != identity.root_thread_id()
                    || route.target() == identity.root_thread_id()
                    || !participant_ids.contains(&route.target())
                    || route.created_at() < event.created_at()
                    || route.created_at() > event.last_changed_at()
                    || route
                        .note()
                        .is_some_and(|value| clamp_route_note(value) != value)
                    || route
                        .delivery()
                        .failure_reason()
                        .is_some_and(|value| clamp_delivery_reason(value) != value)
                {
                    return Err(corrupt("route record has impossible metadata"));
                }
                match route.duty() {
                    crate::model::RouteDuty::Ended => {
                        let Some(ended_by) = route.ended_by() else {
                            return Err(corrupt("ended route lacks its actor"));
                        };
                        let Some(ended_at) = route.ended_at() else {
                            return Err(corrupt("ended route lacks its revision"));
                        };
                        if !participant_ids.contains(&ended_by)
                            || (ended_by != route.target() && ended_by != identity.root_thread_id())
                            || ended_at < route.created_at()
                            || ended_at > event.last_changed_at()
                        {
                            return Err(corrupt("ended route has impossible metadata"));
                        }
                    }
                    crate::model::RouteDuty::Notice | crate::model::RouteDuty::Assigned => {
                        if route.ended_by().is_some() || route.ended_at().is_some() {
                            return Err(corrupt("live route carries end metadata"));
                        }
                    }
                }
                if route.duty().is_assigned() && !assigned_targets.insert(route.target()) {
                    return Err(corrupt(
                        "participant has duplicate active assignments for one event",
                    ));
                }
                route_ids.insert(route.id());
            }
        }

        for (producer, ordinal) in &self.published_facts_through {
            if !participant_ids.contains(producer)
                || *ordinal == 0
                || !self
                    .facts
                    .iter()
                    .any(|fact| fact.producer() == *producer && fact.id().ordinal() == *ordinal)
            {
                return Err(corrupt(
                    "published fact cursor does not name a producer fact",
                ));
            }
        }

        let mut previous_revision = TeamRevision::INITIAL;
        for change in &self.change_log {
            if change.revision == TeamRevision::INITIAL
                || change.revision < previous_revision
                || change.revision > self.revision
                || !participant_ids.contains(&change.actor)
            {
                return Err(corrupt("change log ordering or actor is invalid"));
            }
            match change.kind {
                ChangeKind::Publish
                | ChangeKind::CloseProducer
                | ChangeKind::SetRootState
                | ChangeKind::Retire => {
                    let id = change
                        .target
                        .parse()
                        .map_err(|_| corrupt("change log version target is malformed"))?;
                    if !version_ids.contains(&id) {
                        return Err(corrupt("change log references an unknown version"));
                    }
                }
                ChangeKind::Route | ChangeKind::Delivery | ChangeKind::EndAssignment => {
                    let id = change
                        .target
                        .parse()
                        .map_err(|_| corrupt("change log route target is malformed"))?;
                    if !route_ids.contains(&id) {
                        return Err(corrupt("change log references an unknown route"));
                    }
                }
            }
            previous_revision = change.revision;
        }
        if self.revision == TeamRevision::INITIAL {
            if !self.change_log.is_empty() {
                return Err(corrupt("initial revision has a change log"));
            }
        } else if previous_revision != self.revision {
            return Err(corrupt("change log does not reach the current revision"));
        }

        for ((actor, request_id), submission) in &self.committed {
            if !participant_ids.contains(actor) || request_id.trim().is_empty() {
                return Err(corrupt("retry ledger key is invalid"));
            }
            match (&submission.request, &submission.outcome) {
                (CommittedRequest::Publish(request), CommittedOutcome::Publish(outcome)) => {
                    let Some(event) = self
                        .events
                        .iter()
                        .find(|event| event.id() == outcome.event_id)
                    else {
                        return Err(corrupt("publish retry event is missing"));
                    };
                    let Some(version) = event
                        .versions()
                        .iter()
                        .find(|version| version.id() == outcome.version_id)
                    else {
                        return Err(corrupt("publish retry version is missing"));
                    };
                    let target_matches = match &request.target {
                        PublishTarget::NewEvent { title } => {
                            version.id().ordinal() == 1
                                && event.created_by() == *actor
                                && clamp_title(title) == event.title()
                        }
                        PublishTarget::ExistingEvent { event_id } => *event_id == event.id(),
                    };
                    if !target_matches
                        || version.authored().author != *actor
                        || clamp_summary(&request.summary) != version.authored().summary
                        || request.handoff.as_deref().map(clamp_handoff)
                            != version.authored().handoff.clone()
                        || outcome.event_id != event.id()
                        || outcome.version_id != version.id()
                        || outcome.revision != version.created_at()
                        || outcome.evidence_refs.as_slice()
                            != version.authored().evidence_refs.as_slice()
                        || outcome.authored_on_stale_view
                            != version.authored_on_stale_view().is_some()
                        || outcome.deduplicated
                    {
                        return Err(corrupt("publish retry outcome is invalid"));
                    }
                }
                (CommittedRequest::Route(request), CommittedOutcome::Route { route_id }) => {
                    let route = self
                        .events
                        .iter()
                        .flat_map(super::model::TeamEvent::routes)
                        .find(|route| route.id() == *route_id);
                    let Some(route) = route else {
                        return Err(corrupt("route retry target is missing"));
                    };
                    let intent_matches = match request.intent {
                        RouteIntent::Assign => {
                            matches!(
                                route.duty(),
                                crate::model::RouteDuty::Assigned | crate::model::RouteDuty::Ended
                            )
                        }
                        RouteIntent::Notify => {
                            matches!(route.duty(), crate::model::RouteDuty::Notice)
                        }
                    };
                    if route.routed_by() != *actor
                        || route.id().event_id() != request.event_id
                        || route.target() != request.target
                        || route.note() != request.note.as_deref().map(clamp_route_note).as_deref()
                        || !intent_matches
                    {
                        return Err(corrupt("route retry outcome is invalid"));
                    }
                }
                (CommittedRequest::Retire(request), CommittedOutcome::Retire(outcome)) => {
                    let version = self
                        .events
                        .iter()
                        .flat_map(super::model::TeamEvent::versions)
                        .find(|version| version.id() == outcome.version_id);
                    let Some(version) = version else {
                        return Err(corrupt("retirement retry version is missing"));
                    };
                    let Some(retirement) = version.retirement() else {
                        return Err(corrupt("retirement retry has no retirement record"));
                    };
                    let expected_before = format!(
                        "producer={} root={}",
                        request.expected_producer_state, request.expected_root_state
                    );
                    let expected_after = format!(
                        "producer={} root={} retired availability={} epoch={} reason={}",
                        request.expected_producer_state,
                        request.expected_root_state,
                        request.expected_availability,
                        request.expected_availability_epoch,
                        clamp_retire_reason(&request.reason)
                    );
                    let matching_changes = self
                        .change_log
                        .iter()
                        .filter(|change| {
                            change.kind == ChangeKind::Retire
                                && change.revision == outcome.revision
                                && change.actor == *actor
                                && change.target == outcome.version_id.to_string()
                                && change.before.as_deref() == Some(expected_before.as_str())
                                && change.after.as_deref() == Some(expected_after.as_str())
                        })
                        .count();
                    if request.version_id != version.id()
                        || request.expected_producer_state != ProducerState::Open
                        || clamp_retire_reason(&request.reason) != retirement.reason
                        || request.expected_availability != retirement.availability
                        || request.expected_availability_epoch != retirement.availability_epoch
                        || outcome.retired_by != *actor
                        || outcome.retired_by != retirement.retired_by
                        || outcome.revision != retirement.retired_at
                        || outcome.reason != retirement.reason
                        || outcome.availability != retirement.availability
                        || outcome.availability_epoch != retirement.availability_epoch
                        || outcome.deduplicated
                        || matching_changes != 1
                    {
                        return Err(corrupt("retirement retry outcome is invalid"));
                    }
                }
                _ => return Err(corrupt("retry request and outcome kinds disagree")),
            }
        }
        Ok(())
    }
}

/// JSON object keys cannot represent `(ThreadId, request_id)` without inventing an ambiguous text
/// encoding. Persist the retry ledger as a sorted row sequence and reject duplicate decoded keys.
mod committed_submissions {
    use super::CommittedSubmission;
    use codex_protocol::ThreadId;
    use serde::Deserialize;
    use serde::Serialize;
    use serde::de::Error as _;
    use std::collections::HashMap;

    #[derive(Deserialize, Serialize)]
    #[serde(deny_unknown_fields)]
    struct Row {
        actor: ThreadId,
        request_id: String,
        submission: CommittedSubmission,
    }

    pub(super) fn serialize<S>(
        submissions: &HashMap<(ThreadId, String), CommittedSubmission>,
        serializer: S,
    ) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        let mut rows: Vec<Row> = submissions
            .iter()
            .map(|((actor, request_id), submission)| Row {
                actor: *actor,
                request_id: request_id.clone(),
                submission: submission.clone(),
            })
            .collect();
        rows.sort_by(|left, right| {
            left.actor
                .to_string()
                .cmp(&right.actor.to_string())
                .then_with(|| left.request_id.cmp(&right.request_id))
        });
        rows.serialize(serializer)
    }

    pub(super) fn deserialize<'de, D>(
        deserializer: D,
    ) -> Result<HashMap<(ThreadId, String), CommittedSubmission>, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let rows = Vec::<Row>::deserialize(deserializer)?;
        let mut submissions = HashMap::with_capacity(rows.len());
        for row in rows {
            if submissions
                .insert((row.actor, row.request_id), row.submission)
                .is_some()
            {
                return Err(D::Error::custom("duplicate committed Team submission"));
            }
        }
        Ok(submissions)
    }
}

#[cfg(test)]
#[path = "store_tests.rs"]
mod tests;
