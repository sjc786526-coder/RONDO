use crate::DeliveryResult;
use crate::DeliveryState;
use crate::EventId;
use crate::EventView;
use crate::HistoryQuery;
use crate::LifecycleChange;
use crate::LifecycleRequest;
use crate::LifecycleSnapshot;
use crate::LifecycleTarget;
use crate::MAX_HISTORY_LIMIT;
use crate::ProducerState;
use crate::PublishOutcome;
use crate::PublishRequest;
use crate::PublishTarget;
use crate::RootState;
use crate::RouteDispatch;
use crate::RouteDuty;
use crate::RouteId;
use crate::RouteIntent;
use crate::RouteRequest;
use crate::RouteView;
use crate::Submission;
use crate::TeamInstanceId;
use crate::TeamRevision;
use crate::VersionId;
use crate::VersionView;
use crate::store::TeamStore;
use crate::test_support::TeamFixture;
use crate::test_support::register_member;
use codex_protocol::ThreadId;
use pretty_assertions::assert_eq;
use proptest::collection::vec;
use proptest::prelude::*;
use proptest::strategy::ValueTree;
use proptest::test_runner::Config;
use proptest::test_runner::RngAlgorithm;
use proptest::test_runner::RngSeed;
use proptest::test_runner::TestCaseError;
use proptest::test_runner::TestRunner;
use std::collections::BTreeSet;

const DEFAULT_SEED: u64 = 20_260_820_047;
const CASES: u32 = 64;
const MAX_STEPS: usize = 32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
enum Slot {
    Root,
    MemberA,
    MemberB,
}

impl Slot {
    const ALL: [Self; 3] = [Self::Root, Self::MemberA, Self::MemberB];

    fn from_byte(value: u8) -> Self {
        match value % 3 {
            0 => Self::Root,
            1 => Self::MemberA,
            2 => Self::MemberB,
            _ => unreachable!(),
        }
    }

    fn member_from_byte(value: u8) -> Self {
        if value.is_multiple_of(2) {
            Self::MemberA
        } else {
            Self::MemberB
        }
    }

    fn index(self) -> usize {
        match self {
            Self::Root => 0,
            Self::MemberA => 1,
            Self::MemberB => 2,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Root => "/root",
            Self::MemberA => "/root/worker",
            Self::MemberB => "/root/b",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
#[rustfmt::skip]
enum Step {
    NewEvent { actor: u8, content: u8 },
    Append { actor: u8, event: u8, content: u8, lag: u8 },
    CloseProducer { version: u8 },
    SetRootState { version: u8, resolved: bool },
    Assign { event: u8, target: u8, note: u8 },
    Notify { event: u8, target: u8, note: u8 },
    DeliveryFailed { route: u8, reason: u8 },
    DeliveryDelivered { route: u8 },
    Retry { request: u8 },
    EndAssignment { route: u8, by_target: bool },
    ConsumeWake { participant: u8 },
}

fn step_strategy() -> impl Strategy<Value = Step> {
    prop_oneof![
        4 => (any::<u8>(), any::<u8>())
            .prop_map(|(actor, content)| Step::NewEvent { actor, content }),
        5 => (any::<u8>(), any::<u8>(), any::<u8>(), any::<u8>()).prop_map(
            |(actor, event, content, lag)| Step::Append { actor, event, content, lag }
        ),
        2 => any::<u8>().prop_map(|version| Step::CloseProducer { version }),
        3 => (any::<u8>(), any::<bool>()).prop_map(|(version, resolved)| {
            Step::SetRootState { version, resolved }
        }),
        3 => (any::<u8>(), any::<u8>(), any::<u8>())
            .prop_map(|(event, target, note)| Step::Assign { event, target, note }),
        1 => (any::<u8>(), any::<u8>(), any::<u8>())
            .prop_map(|(event, target, note)| Step::Notify { event, target, note }),
        2 => (any::<u8>(), any::<u8>())
            .prop_map(|(route, reason)| Step::DeliveryFailed { route, reason }),
        2 => any::<u8>().prop_map(|route| Step::DeliveryDelivered { route }),
        3 => any::<u8>().prop_map(|request| Step::Retry { request }),
        1 => (any::<u8>(), any::<bool>())
            .prop_map(|(route, by_target)| Step::EndAssignment { route, by_target }),
        2 => any::<u8>().prop_map(|participant| Step::ConsumeWake { participant }),
    ]
}

fn sequence_strategy() -> impl Strategy<Value = Vec<Step>> {
    vec(step_strategy(), 1..=MAX_STEPS)
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RefVersion {
    id: VersionId,
    author: Slot,
    summary: String,
    producer: ProducerState,
    root: RootState,
    stale: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RefRoute {
    id: RouteId,
    target: Slot,
    note: Option<String>,
    duty: RouteDuty,
    delivery: DeliveryState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RefEvent {
    id: EventId,
    title: String,
    created_by: Slot,
    last_changed: u64,
    versions: Vec<RefVersion>,
    routes: Vec<RefRoute>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum RetryRecord {
    Publish {
        actor: Slot,
        submission: Submission,
        request: PublishRequest,
        event_id: EventId,
        version_id: VersionId,
        revision: TeamRevision,
    },
    Route {
        submission: Submission,
        request: RouteRequest,
        route_id: RouteId,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct RefState {
    instance: TeamInstanceId,
    participants: [ThreadId; 3],
    revision: u64,
    events: Vec<RefEvent>,
    wakes: [bool; 3],
}

impl RefState {
    fn thread(&self, slot: Slot) -> ThreadId {
        self.participants[slot.index()]
    }

    fn event_index(&self, selector: u8) -> Option<usize> {
        (!self.events.is_empty()).then(|| usize::from(selector) % self.events.len())
    }

    fn version_position(&self, selector: u8) -> Option<(usize, usize)> {
        let count: usize = self.events.iter().map(|event| event.versions.len()).sum();
        let mut selected = usize::from(selector) % count.max(1);
        for (event_index, event) in self.events.iter().enumerate() {
            if selected < event.versions.len() {
                return Some((event_index, selected));
            }
            selected -= event.versions.len();
        }
        None
    }

    fn route_position(&self, selector: u8) -> Option<(usize, usize)> {
        let count: usize = self.events.iter().map(|event| event.routes.len()).sum();
        let mut selected = usize::from(selector) % count.max(1);
        for (event_index, event) in self.events.iter().enumerate() {
            if selected < event.routes.len() {
                return Some((event_index, selected));
            }
            selected -= event.routes.len();
        }
        None
    }

    fn visible_to(event: &RefEvent, slot: Slot) -> bool {
        slot == Slot::Root
            || event.created_by == slot
            || event.versions.iter().any(|version| version.author == slot)
            || event.routes.iter().any(|route| route.target == slot)
    }

    fn active_for(event: &RefEvent, slot: Slot) -> bool {
        event
            .versions
            .iter()
            .any(|version| version.author == slot && version.producer == ProducerState::Open)
            || event
                .routes
                .iter()
                .any(|route| route.target == slot && route.duty == RouteDuty::Assigned)
            || (slot == Slot::Root
                && event
                    .versions
                    .iter()
                    .any(|version| version.root != RootState::Resolved))
    }

    fn find_route(&self, route_id: RouteId) -> Option<&RefRoute> {
        self.events
            .iter()
            .flat_map(|event| &event.routes)
            .find(|route| route.id == route_id)
    }

    fn expected_observation(&self) -> Observation {
        let mut events: Vec<EventView> = self
            .events
            .iter()
            .map(|event| EventView {
                id: event.id,
                title: event.title.clone(),
                versions: event
                    .versions
                    .iter()
                    .map(|version| VersionView {
                        id: version.id,
                        author: self.thread(version.author),
                        author_label: version.author.label().to_string(),
                        summary: version.summary.clone(),
                        handoff: None,
                        evidence_refs: Vec::new(),
                        producer_state: version.producer,
                        root_state: version.root,
                        authored_on_stale_view: version.stale,
                        retired: false,
                        producer_availability: None,
                    })
                    .collect(),
                routes: event
                    .routes
                    .iter()
                    .map(|route| RouteView {
                        id: route.id,
                        target_label: route.target.label().to_string(),
                        duty: route.duty,
                        delivery: route.delivery.clone(),
                        note: route.note.clone(),
                    })
                    .collect(),
            })
            .collect();
        events.sort_by_key(|event| event.id);
        let visible = std::array::from_fn(|index| {
            let slot = Slot::ALL[index];
            sorted_event_ids(
                self.events
                    .iter()
                    .filter(|event| Self::visible_to(event, slot)),
            )
        });
        let active = std::array::from_fn(|index| {
            let slot = Slot::ALL[index];
            sorted_event_ids(
                self.events
                    .iter()
                    .filter(|event| Self::active_for(event, slot)),
            )
        });
        let routes = std::array::from_fn(|index| {
            let slot = Slot::ALL[index];
            let mut ids: Vec<RouteId> = self
                .events
                .iter()
                .filter(|event| Self::visible_to(event, slot))
                .flat_map(|event| &event.routes)
                .filter(|route| slot == Slot::Root || route.target == slot)
                .map(|route| route.id)
                .collect();
            ids.sort();
            ids
        });
        Observation {
            instance: self.instance,
            revision: TeamRevision::from_raw(self.revision),
            events,
            visible,
            active,
            routes,
            wakes: self.wakes,
        }
    }

    fn check_invariants(&self) -> Result<(), String> {
        let mut events = BTreeSet::new();
        let mut versions = BTreeSet::new();
        let mut routes = BTreeSet::new();
        for event in &self.events {
            if !events.insert(event.id) || event.versions.is_empty() {
                return Err("duplicate or empty canonical event".to_string());
            }
            let mut active_targets = BTreeSet::new();
            for version in &event.versions {
                if version.id.event_id() != event.id || !versions.insert(version.id) {
                    return Err("canonical version binding mismatch".to_string());
                }
            }
            for route in &event.routes {
                if route.id.event_id() != event.id || !routes.insert(route.id) {
                    return Err("canonical route binding mismatch".to_string());
                }
                if route.target == Slot::Root {
                    return Err("route target is not a member".to_string());
                }
                if route.duty == RouteDuty::Assigned && !active_targets.insert(route.target) {
                    return Err("two active assignments target the same event/member".to_string());
                }
            }
        }
        Ok(())
    }

    fn summary(&self) -> String {
        let versions: usize = self.events.iter().map(|event| event.versions.len()).sum();
        let routes: usize = self.events.iter().map(|event| event.routes.len()).sum();
        format!(
            "revision={} events={} versions={} routes={} wakes={:?}",
            self.revision,
            self.events.len(),
            versions,
            routes,
            self.wakes
        )
    }
}

fn sorted_event_ids<'a>(events: impl Iterator<Item = &'a RefEvent>) -> Vec<EventId> {
    let mut ids: Vec<EventId> = events.map(|event| event.id).collect();
    ids.sort();
    ids
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Observation {
    instance: TeamInstanceId,
    revision: TeamRevision,
    events: Vec<EventView>,
    visible: [Vec<EventId>; 3],
    active: [Vec<EventId>; 3],
    routes: [Vec<RouteId>; 3],
    wakes: [bool; 3],
}

struct Driver {
    store: TeamStore,
    reference: RefState,
    retries: Vec<RetryRecord>,
    request_serial: u64,
    product_calls: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Applied {
    Called,
    NotApplicable,
}

impl Driver {
    fn new() -> Self {
        let TeamFixture {
            mut store,
            root,
            worker,
        } = TeamFixture::new();
        let member_b = register_member(&mut store, Slot::MemberB.label());
        let participants = [root, worker, member_b];
        let reference = RefState {
            instance: store.instance(),
            participants,
            revision: 0,
            events: Vec::new(),
            wakes: [false; 3],
        };
        Self {
            store,
            reference,
            retries: Vec::new(),
            request_serial: 0,
            product_calls: 0,
        }
    }

    fn request_id(&mut self) -> String {
        let request_id = format!("sequence-{}", self.request_serial);
        self.request_serial = self.request_serial.saturating_add(1);
        request_id
    }

    fn observe_store(&self) -> Result<Observation, String> {
        let root = self.reference.thread(Slot::Root);
        let root_page = self
            .store
            .history(
                root,
                &HistoryQuery {
                    limit: Some(MAX_HISTORY_LIMIT),
                    ..Default::default()
                },
            )
            .map_err(|error| error.to_string())?;
        if root_page.omitted_events != 0 {
            return Err("bounded sequence unexpectedly exceeded history capacity".to_string());
        }
        let mut events = Vec::new();
        for listed in root_page.events {
            let page = self
                .store
                .history(
                    root,
                    &HistoryQuery {
                        event_id: Some(listed.event.id),
                        limit: Some(MAX_HISTORY_LIMIT),
                        before: None,
                    },
                )
                .map_err(|error| error.to_string())?;
            let history = page
                .events
                .into_iter()
                .next()
                .ok_or("event history vanished")?;
            if history.omitted_versions != 0 {
                return Err("bounded sequence unexpectedly exceeded version capacity".to_string());
            }
            events.push(history.event);
        }
        events.sort_by_key(|event| event.id);

        let mut visible: [Vec<EventId>; 3] = std::array::from_fn(|_| Vec::new());
        let mut active: [Vec<EventId>; 3] = std::array::from_fn(|_| Vec::new());
        let mut routes: [Vec<RouteId>; 3] = std::array::from_fn(|_| Vec::new());
        let mut wakes = [false; 3];
        for slot in Slot::ALL {
            let index = slot.index();
            let participant = self.reference.thread(slot);
            let page = self
                .store
                .history(
                    participant,
                    &HistoryQuery {
                        limit: Some(MAX_HISTORY_LIMIT),
                        ..Default::default()
                    },
                )
                .map_err(|error| error.to_string())?;
            visible[index] = page.events.iter().map(|history| history.event.id).collect();
            visible[index].sort();
            for event_id in &visible[index] {
                let page = self
                    .store
                    .history(
                        participant,
                        &HistoryQuery {
                            event_id: Some(*event_id),
                            limit: Some(MAX_HISTORY_LIMIT),
                            before: None,
                        },
                    )
                    .map_err(|error| error.to_string())?;
                routes[index].extend(
                    page.events
                        .into_iter()
                        .flat_map(|history| history.event.routes)
                        .map(|route| route.id),
                );
            }
            routes[index].sort();
            active[index] = self
                .store
                .snapshot_for(participant)
                .map_err(|error| error.to_string())?
                .events
                .into_iter()
                .map(|event| event.id)
                .collect();
            active[index].sort();
            wakes[index] = self.store.has_pending_wake(participant);
        }
        Ok(Observation {
            instance: self.store.instance(),
            revision: self.store.revision(),
            events,
            visible,
            active,
            routes,
            wakes,
        })
    }

    fn check_state(&self) -> Result<(), String> {
        self.reference.check_invariants()?;
        let expected = self.reference.expected_observation();
        let actual = self.observe_store()?;
        if expected != actual {
            return Err(format!(
                "reference/product mismatch\nreference: {}\nexpected={expected:#?}\nactual={actual:#?}",
                self.reference.summary()
            ));
        }
        Ok(())
    }

    fn not_applicable(
        &self,
        before_reference: &RefState,
        before_store: &Observation,
        before_calls: usize,
    ) -> Result<Applied, String> {
        if &self.reference != before_reference
            || self.product_calls != before_calls
            || &self.observe_store()? != before_store
        {
            return Err(
                "not_applicable step changed reference, store, revision, wake, or API call count"
                    .to_string(),
            );
        }
        self.check_state()?;
        Ok(Applied::NotApplicable)
    }

    fn apply(&mut self, step: &Step) -> Result<Applied, String> {
        let before_reference = self.reference.clone();
        let before_store = self.observe_store()?;
        let before_calls = self.product_calls;
        match *step {
            Step::NewEvent { actor, content } => self.publish_new(actor, content)?,
            Step::Append {
                actor,
                event,
                content,
                lag,
            } => {
                let Some(event_index) = self.reference.event_index(event) else {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                };
                let actor = Slot::from_byte(actor);
                if !RefState::visible_to(&self.reference.events[event_index], actor) {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                }
                self.publish_append(actor, event_index, content, lag)?;
            }
            Step::CloseProducer { version } => {
                let Some((event_index, version_index)) = self.reference.version_position(version)
                else {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                };
                if self.reference.events[event_index].versions[version_index].producer
                    == ProducerState::Closed
                {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                }
                self.close_producer(event_index, version_index)?;
            }
            Step::SetRootState { version, resolved } => {
                let Some((event_index, version_index)) = self.reference.version_position(version)
                else {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                };
                if self.reference.events[event_index].versions[version_index].root
                    == RootState::Resolved
                {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                }
                self.set_root_state(event_index, version_index, resolved)?;
            }
            Step::Assign {
                event,
                target,
                note,
            }
            | Step::Notify {
                event,
                target,
                note,
            } => {
                let Some(event_index) = self.reference.event_index(event) else {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                };
                let intent = if matches!(step, Step::Assign { .. }) {
                    RouteIntent::Assign
                } else {
                    RouteIntent::Notify
                };
                let target = Slot::member_from_byte(target);
                let note = route_note(note);
                if intent == RouteIntent::Assign
                    && self.reference.events[event_index]
                        .routes
                        .iter()
                        .any(|route| {
                            route.target == target
                                && route.duty == RouteDuty::Assigned
                                && route.note != note
                        })
                {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                }
                self.route(event_index, target, intent, note)?;
            }
            Step::DeliveryFailed { route, reason } => {
                let Some((event_index, route_index)) = self.reference.route_position(route) else {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                };
                if self.reference.events[event_index].routes[route_index]
                    .delivery
                    .is_delivered()
                {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                }
                self.delivery_failed(event_index, route_index, reason)?;
            }
            Step::DeliveryDelivered { route } => {
                let Some((event_index, route_index)) = self.reference.route_position(route) else {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                };
                if self.reference.events[event_index].routes[route_index]
                    .delivery
                    .is_delivered()
                {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                }
                self.delivery_delivered(event_index, route_index)?;
            }
            Step::Retry { request } => {
                if self.retries.is_empty() {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                }
                self.retry(usize::from(request) % self.retries.len())?;
            }
            Step::EndAssignment { route, by_target } => {
                let Some((event_index, route_index)) = self.reference.route_position(route) else {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                };
                if self.reference.events[event_index].routes[route_index].duty
                    != RouteDuty::Assigned
                {
                    return self.not_applicable(&before_reference, &before_store, before_calls);
                }
                self.end_assignment(event_index, route_index, by_target)?;
            }
            Step::ConsumeWake { participant } => self.consume_wake(Slot::from_byte(participant))?,
        }
        self.check_state()?;
        Ok(Applied::Called)
    }

    fn publish_new(&mut self, actor: u8, content: u8) -> Result<(), String> {
        let actor = Slot::from_byte(actor);
        let event_ordinal = u32::try_from(self.reference.events.len().saturating_add(1))
            .map_err(|_| "reference event ordinal overflow")?;
        let expected_event_id = EventId::new(self.reference.instance.tag(), event_ordinal);
        let expected_version_id = VersionId::new(self.reference.instance.tag(), event_ordinal, 1);
        let submission = Submission {
            based_on: TeamRevision::from_raw(self.reference.revision),
            request_id: self.request_id(),
        };
        let request = PublishRequest {
            target: PublishTarget::NewEvent {
                title: format!("event-{}", content % 8),
            },
            summary: format!("summary-{}", content % 8),
            handoff: None,
        };
        self.product_calls += 1;
        let outcome = self
            .store
            .publish(self.reference.thread(actor), &submission, request.clone())
            .map_err(|error| error.to_string())?;
        self.reference.revision += 1;
        let root = if actor == Slot::Root {
            RootState::Tracking
        } else {
            RootState::Pending
        };
        if actor != Slot::Root {
            self.reference.wakes[Slot::Root.index()] = true;
        }
        assert_publish(&outcome, self.reference.revision, false, false)?;
        if outcome.event_id != expected_event_id || outcome.version_id != expected_version_id {
            return Err(format!(
                "new publish minted unexpected canonical IDs: {outcome:?}"
            ));
        }
        let PublishTarget::NewEvent { title } = &request.target else {
            unreachable!()
        };
        self.reference.events.push(RefEvent {
            id: outcome.event_id,
            title: title.clone(),
            created_by: actor,
            last_changed: self.reference.revision,
            versions: vec![RefVersion {
                id: outcome.version_id,
                author: actor,
                summary: request.summary.clone(),
                producer: ProducerState::Open,
                root,
                stale: false,
            }],
            routes: Vec::new(),
        });
        self.retries.push(RetryRecord::Publish {
            actor,
            submission,
            request,
            event_id: outcome.event_id,
            version_id: outcome.version_id,
            revision: outcome.revision,
        });
        Ok(())
    }

    fn publish_append(
        &mut self,
        actor: Slot,
        event_index: usize,
        content: u8,
        lag: u8,
    ) -> Result<(), String> {
        let based_on = self.reference.revision.saturating_sub(u64::from(lag % 4));
        let submission = Submission {
            based_on: TeamRevision::from_raw(based_on),
            request_id: self.request_id(),
        };
        let event_id = self.reference.events[event_index].id;
        let version_ordinal = u32::try_from(
            self.reference.events[event_index]
                .versions
                .len()
                .saturating_add(1),
        )
        .map_err(|_| "reference version ordinal overflow")?;
        let expected_version_id = VersionId::new(
            self.reference.instance.tag(),
            event_id.ordinal(),
            version_ordinal,
        );
        let stale = self.reference.events[event_index].last_changed > based_on;
        let request = PublishRequest {
            target: PublishTarget::ExistingEvent { event_id },
            summary: format!("append-{}", content % 8),
            handoff: None,
        };
        self.product_calls += 1;
        let outcome = self
            .store
            .publish(self.reference.thread(actor), &submission, request.clone())
            .map_err(|error| error.to_string())?;
        self.reference.revision += 1;
        assert_publish(&outcome, self.reference.revision, stale, false)?;
        if outcome.event_id != event_id {
            return Err("append returned a different canonical event".to_string());
        }
        if outcome.version_id != expected_version_id {
            return Err(format!(
                "append minted an unexpected canonical version: {outcome:?}"
            ));
        }
        let root = if actor == Slot::Root {
            RootState::Tracking
        } else {
            RootState::Pending
        };
        let event = &mut self.reference.events[event_index];
        event.last_changed = self.reference.revision;
        event.versions.push(RefVersion {
            id: outcome.version_id,
            author: actor,
            summary: request.summary.clone(),
            producer: ProducerState::Open,
            root,
            stale,
        });
        if actor != Slot::Root {
            self.reference.wakes[Slot::Root.index()] = true;
        }
        self.retries.push(RetryRecord::Publish {
            actor,
            submission,
            request,
            event_id,
            version_id: outcome.version_id,
            revision: outcome.revision,
        });
        Ok(())
    }

    fn close_producer(&mut self, event_index: usize, version_index: usize) -> Result<(), String> {
        let version = self.reference.events[event_index].versions[version_index].clone();
        let request = LifecycleRequest {
            targets: vec![LifecycleTarget {
                version_id: version.id,
                expected_producer_state: version.producer,
                expected_root_state: version.root,
                change: LifecycleChange::CloseProducer,
            }],
        };
        self.product_calls += 1;
        let outcome = self
            .store
            .update_lifecycle(self.reference.thread(version.author), request)
            .map_err(|error| error.to_string())?;
        self.reference.revision += 1;
        let updated = LifecycleSnapshot {
            version_id: version.id,
            producer_state: ProducerState::Closed,
            root_state: version.root,
        };
        if outcome.revision.get() != self.reference.revision
            || outcome.updated != [updated]
            || !outcome.changed
        {
            return Err(format!(
                "unexpected producer lifecycle outcome: {outcome:?}"
            ));
        }
        let event = &mut self.reference.events[event_index];
        event.versions[version_index].producer = ProducerState::Closed;
        event.last_changed = self.reference.revision;
        if version.root != RootState::Resolved {
            self.reference.wakes[Slot::Root.index()] = true;
        }
        Ok(())
    }

    fn set_root_state(
        &mut self,
        event_index: usize,
        version_index: usize,
        resolved: bool,
    ) -> Result<(), String> {
        let version = self.reference.events[event_index].versions[version_index].clone();
        let next = if resolved {
            RootState::Resolved
        } else {
            RootState::Tracking
        };
        let changed = version.root != next;
        let request = LifecycleRequest {
            targets: vec![LifecycleTarget {
                version_id: version.id,
                expected_producer_state: version.producer,
                expected_root_state: version.root,
                change: LifecycleChange::SetRootState(next),
            }],
        };
        self.product_calls += 1;
        let outcome = self
            .store
            .update_lifecycle(self.reference.thread(Slot::Root), request)
            .map_err(|error| error.to_string())?;
        if changed {
            self.reference.revision += 1;
            self.reference.events[event_index].last_changed = self.reference.revision;
        }
        self.reference.events[event_index].versions[version_index].root = next;
        let updated = LifecycleSnapshot {
            version_id: version.id,
            producer_state: version.producer,
            root_state: next,
        };
        if outcome.revision.get() != self.reference.revision
            || outcome.updated != [updated]
            || outcome.changed != changed
        {
            return Err(format!("unexpected root lifecycle outcome: {outcome:?}"));
        }
        Ok(())
    }

    fn route(
        &mut self,
        event_index: usize,
        target: Slot,
        intent: RouteIntent,
        note: Option<String>,
    ) -> Result<(), String> {
        let event_id = self.reference.events[event_index].id;
        let submission = Submission {
            based_on: TeamRevision::from_raw(self.reference.revision),
            request_id: self.request_id(),
        };
        let request = RouteRequest {
            event_id,
            target: self.reference.thread(target),
            intent,
            note: note.clone(),
        };
        let existing = self.reference.events[event_index]
            .routes
            .iter()
            .find(|route| {
                intent == RouteIntent::Assign
                    && route.target == target
                    && route.duty == RouteDuty::Assigned
            })
            .cloned();
        let expected_new_route_id = RouteId::new(
            self.reference.instance.tag(),
            event_id.ordinal(),
            u32::try_from(
                self.reference.events[event_index]
                    .routes
                    .len()
                    .saturating_add(1),
            )
            .map_err(|_| "reference route ordinal overflow")?,
        );
        self.product_calls += 1;
        let outcome = self
            .store
            .route(
                self.reference.thread(Slot::Root),
                &submission,
                request.clone(),
            )
            .map_err(|error| error.to_string())?;
        let route_id = if let Some(existing) = existing {
            if !outcome.deduplicated
                || outcome.dispatch.route_id != existing.id
                || outcome.revision.get() != self.reference.revision
            {
                return Err(format!(
                    "assignment alias did not reuse canonical route: {outcome:?}"
                ));
            }
            existing.id
        } else {
            self.reference.revision += 1;
            let duty = if intent == RouteIntent::Assign {
                RouteDuty::Assigned
            } else {
                RouteDuty::Notice
            };
            let expected = RouteDispatch {
                instance: self.reference.instance,
                route_id: expected_new_route_id,
                event_id,
                target: self.reference.thread(target),
                duty,
                note: note.clone(),
                delivery: DeliveryState::Pending,
            };
            if outcome.dispatch != expected
                || outcome.revision.get() != self.reference.revision
                || outcome.deduplicated
            {
                return Err(format!("unexpected route outcome: {outcome:?}"));
            }
            self.reference.events[event_index].last_changed = self.reference.revision;
            self.reference.events[event_index].routes.push(RefRoute {
                id: expected_new_route_id,
                target,
                note,
                duty,
                delivery: DeliveryState::Pending,
            });
            if intent == RouteIntent::Assign {
                self.reference.wakes[target.index()] = true;
            }
            expected_new_route_id
        };
        self.retries.push(RetryRecord::Route {
            submission,
            request,
            route_id,
        });
        Ok(())
    }

    fn delivery_failed(
        &mut self,
        event_index: usize,
        route_index: usize,
        reason: u8,
    ) -> Result<(), String> {
        let route = self.reference.events[event_index].routes[route_index].clone();
        let next = DeliveryState::Failed {
            reason: format!("failure-{}", reason % 4),
        };
        let changed = route.delivery != next;
        let DeliveryState::Failed { reason } = &next else {
            unreachable!()
        };
        self.product_calls += 1;
        let outcome = self
            .store
            .record_delivery(
                self.reference.thread(Slot::Root),
                route.id,
                DeliveryResult::Failed {
                    reason: reason.clone(),
                },
            )
            .map_err(|error| error.to_string())?;
        if changed {
            self.reference.revision += 1;
            self.reference.events[event_index].last_changed = self.reference.revision;
        }
        self.reference.events[event_index].routes[route_index].delivery = next.clone();
        if outcome.route_id != route.id
            || outcome.delivery != next
            || outcome.revision.get() != self.reference.revision
            || outcome.changed != changed
        {
            return Err(format!("unexpected failed-delivery outcome: {outcome:?}"));
        }
        Ok(())
    }

    fn delivery_delivered(&mut self, event_index: usize, route_index: usize) -> Result<(), String> {
        let route_id = self.reference.events[event_index].routes[route_index].id;
        self.product_calls += 1;
        let outcome = self
            .store
            .record_delivery(
                self.reference.thread(Slot::Root),
                route_id,
                DeliveryResult::Delivered,
            )
            .map_err(|error| error.to_string())?;
        self.reference.revision += 1;
        self.reference.events[event_index].last_changed = self.reference.revision;
        self.reference.events[event_index].routes[route_index].delivery = DeliveryState::Delivered;
        if outcome.route_id != route_id
            || outcome.delivery != DeliveryState::Delivered
            || outcome.revision.get() != self.reference.revision
            || !outcome.changed
        {
            return Err(format!("unexpected delivered outcome: {outcome:?}"));
        }
        Ok(())
    }

    fn retry(&mut self, retry_index: usize) -> Result<(), String> {
        let retry = self.retries[retry_index].clone();
        self.product_calls += 1;
        match retry {
            RetryRecord::Publish {
                actor,
                submission,
                request,
                event_id,
                version_id,
                revision,
            } => {
                let outcome = self
                    .store
                    .publish(self.reference.thread(actor), &submission, request)
                    .map_err(|error| error.to_string())?;
                let expected = PublishOutcome {
                    event_id,
                    version_id,
                    revision,
                    evidence_refs: Vec::new(),
                    authored_on_stale_view: self
                        .reference
                        .events
                        .iter()
                        .flat_map(|event| &event.versions)
                        .find(|version| version.id == version_id)
                        .is_some_and(|version| version.stale),
                    deduplicated: true,
                };
                if outcome != expected {
                    return Err(format!(
                        "publish retry missed canonical outcome: {outcome:?}"
                    ));
                }
            }
            RetryRecord::Route {
                submission,
                request,
                route_id,
            } => {
                let route = self
                    .reference
                    .find_route(route_id)
                    .ok_or("route retry lost its canonical binding")?;
                let expected = RouteDispatch {
                    instance: self.reference.instance,
                    route_id: route.id,
                    event_id: route.id.event_id(),
                    target: self.reference.thread(route.target),
                    duty: route.duty,
                    note: route.note.clone(),
                    delivery: route.delivery.clone(),
                };
                let outcome = self
                    .store
                    .route(self.reference.thread(Slot::Root), &submission, request)
                    .map_err(|error| error.to_string())?;
                if !outcome.deduplicated
                    || outcome.revision.get() != self.reference.revision
                    || outcome.dispatch != expected
                {
                    return Err(format!("route retry missed canonical outcome: {outcome:?}"));
                }
            }
        }
        Ok(())
    }

    fn end_assignment(
        &mut self,
        event_index: usize,
        route_index: usize,
        by_target: bool,
    ) -> Result<(), String> {
        let route = self.reference.events[event_index].routes[route_index].clone();
        let actor = if by_target { route.target } else { Slot::Root };
        self.product_calls += 1;
        let outcome = self
            .store
            .end_assignment(self.reference.thread(actor), route.id)
            .map_err(|error| error.to_string())?;
        self.reference.revision += 1;
        self.reference.events[event_index].last_changed = self.reference.revision;
        self.reference.events[event_index].routes[route_index].duty = RouteDuty::Ended;
        if actor != Slot::Root {
            self.reference.wakes[Slot::Root.index()] = true;
        }
        if outcome.route_id != route.id
            || outcome.event_id != route.id.event_id()
            || outcome.duty != RouteDuty::Ended
            || outcome.delivery != route.delivery
            || outcome.revision.get() != self.reference.revision
        {
            return Err(format!("unexpected end-assignment outcome: {outcome:?}"));
        }
        Ok(())
    }

    fn consume_wake(&mut self, participant: Slot) -> Result<(), String> {
        let expected = self.reference.wakes[participant.index()];
        self.product_calls += 1;
        let actual = self.store.consume_wake(self.reference.thread(participant));
        if actual != expected {
            return Err(format!(
                "wake mismatch for {participant:?}: expected={expected} actual={actual}"
            ));
        }
        self.reference.wakes[participant.index()] = false;
        Ok(())
    }
}

fn route_note(value: u8) -> Option<String> {
    Some(format!("note-{}", value % 4))
}

fn assert_publish(
    outcome: &PublishOutcome,
    revision: u64,
    stale: bool,
    deduplicated: bool,
) -> Result<(), String> {
    if outcome.revision.get() != revision
        || outcome.authored_on_stale_view != stale
        || outcome.deduplicated != deduplicated
        || !outcome.evidence_refs.is_empty()
    {
        return Err(format!("unexpected publish outcome: {outcome:?}"));
    }
    Ok(())
}

fn run_sequence(steps: &[Step]) -> Result<[bool; 11], String> {
    let mut driver = Driver::new();
    let mut coverage = [false; 11];
    for (index, step) in steps.iter().enumerate() {
        let result = driver.apply(step).map_err(|error| {
            format!(
                "step_index={index} step={step:?}\n{}\n{error}",
                driver.reference.summary()
            )
        })?;
        if result == Applied::Called {
            coverage[coverage_index(step)] = true;
        }
    }
    Ok(coverage)
}

fn coverage_index(step: &Step) -> usize {
    match step {
        Step::NewEvent { .. } => 0,
        Step::Append { .. } => 1,
        Step::CloseProducer { .. } => 2,
        Step::SetRootState { .. } => 3,
        Step::Assign { .. } => 4,
        Step::Notify { .. } => 5,
        Step::DeliveryFailed { .. } => 6,
        Step::DeliveryDelivered { .. } => 7,
        Step::Retry { .. } => 8,
        Step::EndAssignment { .. } => 9,
        Step::ConsumeWake { .. } => 10,
    }
}

#[rustfmt::skip]
fn core_sequence() -> Vec<Step> {
    vec![
        Step::Append {
            actor: 1,
            event: 0,
            content: 0,
            lag: 0,
        },
        Step::DeliveryFailed {
            route: 0,
            reason: 0,
        },
        Step::NewEvent {
            actor: 1,
            content: 1,
        },
        Step::ConsumeWake { participant: 0 },
        Step::Assign {
            event: 0,
            target: 1,
            note: 1,
        },
        Step::DeliveryFailed {
            route: 0,
            reason: 1,
        },
        Step::ConsumeWake { participant: 2 },
        Step::DeliveryDelivered { route: 0 },
        Step::Retry { request: 1 },
        Step::Append {
            actor: 2,
            event: 0,
            content: 2,
            lag: 1,
        },
        Step::SetRootState {
            version: 1,
            resolved: false,
        },
        Step::CloseProducer { version: 1 },
        Step::SetRootState {
            version: 1,
            resolved: true,
        },
        Step::SetRootState {
            version: 0,
            resolved: false,
        },
        Step::SetRootState {
            version: 0,
            resolved: true,
        },
        Step::CloseProducer { version: 0 },
        Step::EndAssignment {
            route: 0,
            by_target: true,
        },
        Step::ConsumeWake { participant: 2 },
        Step::ConsumeWake { participant: 0 },
        Step::NewEvent {
            actor: 0,
            content: 3,
        },
        Step::Retry { request: 3 },
        Step::Notify {
            event: 1,
            target: 0,
            note: 2,
        },
        Step::DeliveryFailed {
            route: 1,
            reason: 2,
        },
        Step::DeliveryDelivered { route: 1 },
        Step::Retry { request: 4 },
        Step::Assign {
            event: 1,
            target: 1,
            note: 3,
        },
        Step::EndAssignment {
            route: 2,
            by_target: false,
        },
        Step::Append {
            actor: 1,
            event: 1,
            content: 4,
            lag: 2,
        },
        Step::SetRootState {
            version: 3,
            resolved: false,
        },
        Step::CloseProducer { version: 3 },
        Step::SetRootState {
            version: 3,
            resolved: true,
        },
        Step::ConsumeWake { participant: 0 },
    ]
}

fn runner_config(seed: u64, cases: u32) -> Config {
    Config {
        cases,
        max_shrink_iters: 4_096,
        failure_persistence: None,
        rng_algorithm: RngAlgorithm::ChaCha,
        rng_seed: RngSeed::Fixed(seed),
        ..Config::default()
    }
}

fn first_candidate(seed: u64) -> Vec<Step> {
    let mut runner = TestRunner::new(runner_config(seed, 1));
    sequence_strategy()
        .new_tree(&mut runner)
        .expect("bounded sequence strategy creates a candidate")
        .current()
}

#[test]
fn the_same_seed_generates_the_same_symbolic_candidate_sequence() {
    let first = first_candidate(DEFAULT_SEED);
    let second = first_candidate(DEFAULT_SEED);
    assert_eq!(first, second);
    assert!(!first.is_empty());
    assert!(first.len() <= MAX_STEPS);
}

#[test]
fn invariant_checker_rejects_a_wrong_canonical_binding() {
    let mut driver = Driver::new();
    driver
        .apply(&Step::NewEvent {
            actor: 0,
            content: 0,
        })
        .expect("fixture publish succeeds");
    driver
        .apply(&Step::NewEvent {
            actor: 1,
            content: 1,
        })
        .expect("fixture publish succeeds");
    let mut broken = driver.reference;
    broken.events[0].versions[0].id = broken.events[1].versions[0].id;
    assert_eq!(
        broken.check_invariants(),
        Err("canonical version binding mismatch".to_string())
    );
}

#[test]
fn invariant_checker_rejects_two_active_assignments_for_one_target() {
    let mut driver = Driver::new();
    driver
        .apply(&Step::NewEvent {
            actor: 0,
            content: 0,
        })
        .expect("fixture publish succeeds");
    driver
        .apply(&Step::Assign {
            event: 0,
            target: 0,
            note: 0,
        })
        .expect("fixture route succeeds");
    let mut broken = driver.reference;
    let mut duplicate = broken.events[0].routes[0].clone();
    duplicate.id = RouteId::new(
        broken.events[0].id.instance(),
        broken.events[0].id.ordinal(),
        99,
    );
    broken.events[0].routes.push(duplicate);
    assert_eq!(
        broken.check_invariants(),
        Err("two active assignments target the same event/member".to_string())
    );
}

#[test]
#[ignore = "run with `just team-state-sequence-properties [seed]`"]
fn team_state_sequence_properties() {
    let seed = std::env::var("TEAM_STATE_SEQUENCE_SEED")
        .ok()
        .map(|value| {
            value
                .parse::<u64>()
                .expect("seed must be an unsigned integer")
        })
        .unwrap_or(DEFAULT_SEED);
    let core = core_sequence();
    assert_eq!(core.len(), MAX_STEPS);
    let coverage = run_sequence(&core).unwrap_or_else(|error| {
        panic!("fixed core sequence failed: seed={seed}\nsteps={core:#?}\n{error}")
    });
    assert!(
        coverage.into_iter().all(|covered| covered),
        "fixed core sequence did not exercise every operation family: {coverage:?}"
    );

    let strategy = sequence_strategy();
    let mut runner = TestRunner::new(runner_config(seed, CASES));
    let result = runner.run(&strategy, |steps| {
        run_sequence(&steps)
            .map(|_| ())
            .map_err(|error| TestCaseError::fail(format!("seed={seed}\nsteps={steps:#?}\n{error}")))
    });
    if let Err(error) = result {
        panic!(
            "Team State sequence property failed: seed={seed} cases={CASES} max_steps={MAX_STEPS}\n{error}"
        );
    }
}
