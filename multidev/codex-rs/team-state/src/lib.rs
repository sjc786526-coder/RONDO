//! Canonical team world state for a RONDO Multi root tree.
//!
//! The point of this crate is a single claim: the collaboration state a team depends on is owned
//! by the harness, not by any model's memory. Members publish semantic checkpoints as `Event`s and
//! immutable `Version`s; the harness keeps them, decides who still has to pay attention to what,
//! wakes the root when something it cares about changes, and re-derives every participant's view
//! from scratch for each sampling.
//!
//! Versions can also carry evidence: stable references to observations Codex actually kept, chosen
//! by the harness from what their author had recorded since its last publish. A reference proves
//! what was observed at the time, never that it still holds, and the observation itself stays where
//! Codex put it — this crate holds identities and locators, not tool output.
//!
//! By default a team instance lives exactly as long as its root tree. An explicitly configured
//! durable root can instead bind this same canonical state to its session lineage and commit it
//! through the root thread's existing writer authority.

mod availability;
mod durable;
mod evidence;
mod handle;
mod ids;
mod model;
mod mutation;
mod observe;
mod publish;
mod render;
mod store;
mod view;
mod wake;

pub use availability::AvailabilityEpoch;
pub use availability::AvailabilitySnapshot;
pub use availability::ProducerAvailability;
pub use durable::DurableTeamIdentity;
pub use durable::MAX_ENCODED_SNAPSHOT_BYTES;
pub use durable::TeamClosePermit;
pub use durable::TeamDurabilityError;
pub use durable::TeamDurabilityFuture;
pub use durable::TeamDurabilityStatus;
pub use durable::TeamWriteAuthority;
pub use durable::TeamWritePermit;
pub use durable::committed_snapshot_generation;
pub use evidence::FactCategory;
pub use evidence::FactView;
pub use evidence::NotedObservation;
pub use evidence::ObservationLocator;
pub use evidence::reported_evidence_refs;
pub use handle::TeamStateHandle;
pub use handle::TeamWakeWaiter;
pub use ids::EventId;
pub use ids::FactId;
pub use ids::InstanceTag;
pub use ids::ReferenceParseError;
pub use ids::RouteId;
pub use ids::TeamInstanceId;
pub use ids::TeamRevision;
pub use ids::VersionId;
pub use model::AuthoredVersion;
pub use model::DeliveryState;
pub use model::Participant;
pub use model::ParticipantRole;
pub use model::ProducerState;
pub use model::RetirementRecord;
pub use model::RootState;
pub use model::RouteDuty;
pub use model::TeamEvent;
pub use model::TeamRoute;
pub use model::TeamVersion;
pub use mutation::DeliveryOutcome;
pub use mutation::DeliveryResult;
pub use mutation::EndAssignmentOutcome;
pub use mutation::LifecycleChange;
pub use mutation::LifecycleOutcome;
pub use mutation::LifecycleRequest;
pub use mutation::LifecycleSnapshot;
pub use mutation::LifecycleTarget;
pub use mutation::PublishOutcome;
pub use mutation::PublishRequest;
pub use mutation::PublishTarget;
pub use mutation::RetireOutcome;
pub use mutation::RetireRequest;
pub use mutation::RouteDispatch;
pub use mutation::RouteIntent;
pub use mutation::RouteOutcome;
pub use mutation::RouteRequest;
pub use mutation::Submission;
pub use mutation::TeamError;
pub use observe::ChangeKind;
pub use observe::ChangeLogPage;
pub use observe::ChangeLogView;
pub use observe::DumpCursor;
pub use observe::DumpEntry;
pub use observe::MAX_OBSERVE_LIMIT;
pub use observe::ObserveQuery;
pub use observe::PublicationStats;
pub use observe::PublicationStatsPage;
pub use observe::TeamDumpPage;
pub use observe::WakeDecisionView;
pub use publish::PreparedPublish;
pub use publish::PreparedPublishHistory;
pub use publish::PreparedPublishHistoryVersion;
pub use publish::PreparedPublishTarget;
pub use publish::PublishPreparation;
pub use render::MAX_PROJECTION_TOKENS;
pub use render::ProjectionBudget;
pub use render::ProjectionOutcome;
pub use render::RenderedProjection;
pub use render::TEAM_WORLD_STATE_CLOSE_TAG;
pub use render::TEAM_WORLD_STATE_OPEN_TAG;
pub use render::render_active_world_index;
pub use store::MAX_HISTORY_LIMIT;
pub use view::EventHistory;
pub use view::EventView;
pub use view::HistoryPage;
pub use view::HistoryQuery;
pub use view::RouteView;
pub use view::TeamSnapshot;
pub use view::VersionView;

#[cfg(test)]
mod test_support;

#[cfg(test)]
#[path = "publish_preparation_tests.rs"]
mod publish_preparation_tests;

#[cfg(test)]
#[path = "sequence_properties_tests.rs"]
mod sequence_properties_tests;
