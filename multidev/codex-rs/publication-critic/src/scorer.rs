use crate::CloudFiveDimensionDecisions;
use crate::ModelIdentity;
use crate::PublicationPacket;
use crate::ScoringContract;
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
        scoring: Box<ScoringContract>,
    },
    Failed,
}

/// The observed backend projection. Scalar scores still go through a threshold;
/// five-dimension decisions never do.
#[derive(Clone, Debug, PartialEq)]
pub enum ScorerProjection {
    Scalar {
        scores: Vec<f64>,
    },
    FiveDimension {
        decisions: CloudFiveDimensionDecisions,
    },
}

/// A backend result before the service validates identity and derives a verdict.
#[derive(Clone, PartialEq)]
pub struct RawScorerOutput {
    pub model: ModelIdentity,
    pub scoring: ScoringContract,
    pub projection: ScorerProjection,
}

impl fmt::Debug for RawScorerOutput {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match &self.projection {
            ScorerProjection::Scalar { scores } => f
                .debug_struct("RawScorerOutput")
                .field("model", &self.model)
                .field("scoring", &self.scoring)
                .field("score_count", &scores.len())
                .finish(),
            ScorerProjection::FiveDimension { .. } => f
                .debug_struct("RawScorerOutput")
                .field("model", &self.model)
                .field("scoring", &self.scoring)
                .field("projection", &"five_dimension")
                .finish(),
        }
    }
}

/// A body-free failure reported by a scorer implementation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ScorerError {
    BackendUnavailable,
}

/// Replaceable scoring backend used by the Publication Critic service.
///
/// Scalar implementations return exactly one score. Five-dimension cloud
/// implementations return typed decisions. Implementations must not detach
/// work, and must stop promptly when `cancellation` is cancelled. The service
/// validates all observed output before it can become a product verdict.
pub trait PublicationScorer: Send + Sync + 'static {
    fn status(&self) -> ScorerStatus;

    fn score(
        &self,
        packet: PublicationPacket,
        cancellation: CancellationToken,
    ) -> impl std::future::Future<Output = Result<RawScorerOutput, ScorerError>> + Send;
}
