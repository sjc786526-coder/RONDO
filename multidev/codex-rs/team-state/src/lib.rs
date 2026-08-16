//! Canonical team world state for a RONDO Multi root tree.
//!
//! The point of this crate is a single claim: the collaboration state a team depends on is owned
//! by the harness, not by any model's memory. Members publish semantic checkpoints as `Event`s and
//! immutable `Version`s; the harness keeps them, decides who still has to pay attention to what,
//! wakes the root when something it cares about changes, and re-derives every participant's view
//! from scratch for each sampling.
//!
//! Nothing here is persisted across processes; a team instance lives exactly as long as its root
//! tree. Members unloaded and reloaded inside that tree rejoin the same instance.

mod handle;
mod ids;
mod model;
mod mutation;
mod render;
mod store;
mod view;
mod wake;

pub use handle::TeamStateHandle;
pub use handle::TeamWakeWaiter;
pub use ids::EventId;
pub use ids::InstanceTag;
pub use ids::ReferenceParseError;
pub use ids::TeamInstanceId;
pub use ids::TeamRevision;
pub use ids::VersionId;
pub use model::AuthoredVersion;
pub use model::Participant;
pub use model::ParticipantRole;
pub use model::ProducerState;
pub use model::RootState;
pub use model::TeamEvent;
pub use model::TeamVersion;
pub use mutation::LifecycleChange;
pub use mutation::LifecycleOutcome;
pub use mutation::LifecycleRequest;
pub use mutation::LifecycleSnapshot;
pub use mutation::LifecycleTarget;
pub use mutation::PublishOutcome;
pub use mutation::PublishRequest;
pub use mutation::PublishTarget;
pub use mutation::Submission;
pub use mutation::TeamError;
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
pub use view::TeamSnapshot;
pub use view::VersionView;

#[cfg(test)]
mod test_support;
