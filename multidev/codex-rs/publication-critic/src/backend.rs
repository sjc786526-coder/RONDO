use crate::ScorerStatus;
use crate::ServiceDescriptor;
use crate::wire::ServiceFailureCode;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum BackendState {
    Loading,
    Ready,
    Failed(ServiceFailureCode),
}

pub(crate) fn classify_backend(status: ScorerStatus, expected: &ServiceDescriptor) -> BackendState {
    match status {
        ScorerStatus::Loading => BackendState::Loading,
        ScorerStatus::Failed => BackendState::Failed(ServiceFailureCode::BackendFailed),
        ScorerStatus::Ready { model, .. } if model != expected.identity.model => {
            BackendState::Failed(ServiceFailureCode::BackendModelIdentityMismatch)
        }
        ScorerStatus::Ready { scoring, .. } if *scoring != expected.identity.scoring => {
            BackendState::Failed(ServiceFailureCode::BackendScoringIdentityMismatch)
        }
        ScorerStatus::Ready { .. } => BackendState::Ready,
    }
}
