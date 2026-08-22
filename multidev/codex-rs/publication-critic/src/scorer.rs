use crate::ModelIdentity;
use crate::PublicationPacket;
use crate::ScoringIdentity;
use std::fmt;
use tokio_util::sync::CancellationToken;

/// The scorer backend's current load/readiness state and observed identity.
///
/// `Ready` is only an observation. The service compares both identities with
/// its trusted configuration before reporting protocol readiness.
#[derive(Clone, Debug, PartialEq)]
pub enum ScorerStatus {
    Loading,
    Ready {
        model: ModelIdentity,
        scoring: Box<ScoringIdentity>,
    },
    Failed,
}

/// A backend result before the service validates identity, shape and score domain.
#[derive(Clone, PartialEq)]
pub struct RawScorerOutput {
    pub model: ModelIdentity,
    pub scoring: ScoringIdentity,
    pub scores: Vec<f64>,
}

impl fmt::Debug for RawScorerOutput {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("RawScorerOutput")
            .field("model", &self.model)
            .field("scoring", &self.scoring)
            .field("score_count", &self.scores.len())
            .finish()
    }
}

/// A body-free failure reported by a scorer implementation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScorerError {
    BackendUnavailable,
}

/// Replaceable scalar scoring backend used by the Publication Critic service.
///
/// Implementations must return exactly one score, must not detach work, and
/// must stop promptly when `cancellation` is cancelled. The service validates
/// all observed output before it can become a product verdict.
pub trait PublicationScorer: Send + Sync + 'static {
    fn status(&self) -> ScorerStatus;

    fn score(
        &self,
        packet: PublicationPacket,
        cancellation: CancellationToken,
    ) -> impl std::future::Future<Output = Result<RawScorerOutput, ScorerError>> + Send;
}
