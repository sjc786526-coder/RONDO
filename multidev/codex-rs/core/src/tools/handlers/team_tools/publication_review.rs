//! Publication Critic orchestration in front of the canonical Team State publish mutation.

use crate::config::PublicationCriticConfig;
use crate::session::turn_context::TurnContext;
use codex_protocol::ThreadId;
use codex_publication_critic::ActorRole;
use codex_publication_critic::ContextFreshness;
use codex_publication_critic::ContinuityContext;
use codex_publication_critic::ContinuityCoverage;
use codex_publication_critic::CriticFailure;
use codex_publication_critic::FactReferenceCountCoverage;
use codex_publication_critic::LocalScope;
use codex_publication_critic::MAX_PRIOR_PUBLICATIONS;
use codex_publication_critic::MAX_VISIBLE_FACT_REFERENCES;
use codex_publication_critic::PriorEvidence;
use codex_publication_critic::PriorPublication;
use codex_publication_critic::PublicationCandidate;
use codex_publication_critic::PublicationCriticClient;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::TargetKind;
use codex_publication_critic::Verdict;
use codex_team_state::EventId;
use codex_team_state::ParticipantRole;
use codex_team_state::PreparedPublish;
use codex_team_state::PreparedPublishHistory;
use codex_team_state::PreparedPublishTarget;
use codex_team_state::PublishOutcome;
use codex_team_state::PublishPreparation;
use codex_team_state::PublishRequest;
use codex_team_state::PublishTarget;
use codex_team_state::Submission;
use codex_team_state::TeamError;
use codex_team_state::TeamInstanceId;
use codex_team_state::TeamStateHandle;
use serde::Serialize;
use std::collections::HashMap;
use std::fmt;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

const MAX_ATTEMPT_RECORDS_PER_TURN: usize = 64;

const FEEDBACK_V1: &str = "Publication Critic feedback v1: revise this candidate to satisfy the minimum publication qualification, then retry with the returned review_cycle_id.";
const FEEDBACK_V2: &str = "Publication Critic feedback v2 (final rewrite opportunity): make a focused correction to this candidate, then retry with the returned review_cycle_id; the next review is non-blocking.";

#[derive(Clone, Eq, PartialEq, Serialize)]
pub(crate) struct CanonicalCandidate {
    pub(crate) title: String,
    pub(crate) summary: String,
    pub(crate) handoff: Option<String>,
}

impl fmt::Debug for CanonicalCandidate {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("CanonicalCandidate")
            .field("title_scalars", &self.title.chars().count())
            .field("summary_scalars", &self.summary.chars().count())
            .field("handoff_present", &self.handoff.is_some())
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct RewriteRequired {
    pub(crate) status: &'static str,
    pub(crate) feedback_version: &'static str,
    pub(crate) feedback: &'static str,
    pub(crate) review_cycle_id: String,
    pub(crate) review_attempt: u8,
    pub(crate) blocking_rewrite_count: u8,
    pub(crate) candidate: CanonicalCandidate,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum FinalReviewStatus {
    Pass,
    RewriteExhausted,
    FailureFallback,
    CommittedReplay,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct FinalReviewMetadata {
    pub(crate) status: FinalReviewStatus,
    pub(crate) review_attempt: Option<u8>,
    pub(crate) blocking_rewrite_count: u8,
    pub(crate) failure_kind: Option<&'static str>,
}

#[derive(Debug)]
pub(crate) enum ReviewPublishResult {
    Committed {
        outcome: PublishOutcome,
        review: FinalReviewMetadata,
    },
    RewriteRequired(RewriteRequired),
}

#[derive(Debug)]
pub(crate) enum ReviewPublishError {
    Team(TeamError),
    CachedRefusal(String),
    InvalidPreparation,
    Cycle(String),
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum CycleTarget {
    NewEvent,
    ExistingEvent(EventId),
}

impl CycleTarget {
    fn from_request(request: &PublishRequest) -> Self {
        match &request.target {
            PublishTarget::NewEvent { .. } => Self::NewEvent,
            PublishTarget::ExistingEvent { event_id } => Self::ExistingEvent(*event_id),
        }
    }
}

#[derive(Debug)]
struct ActiveCycle {
    id: String,
    instance: TeamInstanceId,
    actor: ThreadId,
    target: CycleTarget,
    next_review_index: u8,
    blocking_rewrite_count: u8,
}

#[derive(Clone, Debug)]
enum CachedAttempt {
    BlockingRewrite(RewriteRequired),
    Refused(String),
    Cancelled,
}

#[derive(Clone)]
struct AttemptRecord {
    request: PublishRequest,
    outcome: CachedAttempt,
}

#[derive(Default)]
struct ReviewState {
    active: Option<ActiveCycle>,
    attempts: HashMap<String, AttemptRecord>,
}

#[derive(Default)]
pub(crate) struct TurnPublicationReviews {
    state: Arc<Mutex<ReviewState>>,
}

struct ReviewAttempt {
    cycle_id: String,
    review_index: u8,
    blocking_rewrite_count: u8,
}

pub(crate) struct ReviewedPublishAttempt {
    pub(crate) actor: ThreadId,
    pub(crate) submission: Submission,
    pub(crate) request: PublishRequest,
    pub(crate) continuation: Option<String>,
}

struct PendingCommit {
    actor: ThreadId,
    submission: Submission,
    request: PublishRequest,
    attempt: ReviewAttempt,
}

struct CommitDecision {
    status: FinalReviewStatus,
    failure_kind: Option<&'static str>,
}

impl ReviewState {
    fn active_continuation_matches(
        &self,
        instance: TeamInstanceId,
        actor: ThreadId,
        request: &PublishRequest,
        continuation: Option<&str>,
    ) -> bool {
        self.active.as_ref().is_some_and(|cycle| {
            cycle.instance == instance
                && cycle.actor == actor
                && cycle.target == CycleTarget::from_request(request)
                && continuation == Some(cycle.id.as_str())
        })
    }

    fn cached_attempt(
        &self,
        request_id: &str,
        request: &PublishRequest,
    ) -> Result<Option<CachedAttempt>, ReviewPublishError> {
        let Some(record) = self.attempts.get(request_id) else {
            return Ok(None);
        };
        if record.request != *request {
            return Err(ReviewPublishError::Team(TeamError::RetryIdentityReused));
        }
        Ok(Some(record.outcome.clone()))
    }

    fn begin_attempt(
        &mut self,
        instance: TeamInstanceId,
        actor: ThreadId,
        request: &PublishRequest,
        continuation: Option<&str>,
    ) -> Result<ReviewAttempt, ReviewPublishError> {
        let target = CycleTarget::from_request(request);
        let cycle = match self.active.as_mut() {
            Some(cycle) => {
                if cycle.instance != instance {
                    self.active = None;
                    return Err(ReviewPublishError::Cycle(
                        "publication review cycle is no longer valid for this team turn".into(),
                    ));
                }
                if cycle.actor != actor {
                    return Err(ReviewPublishError::Cycle(
                        "publication review cycle belongs to a different actor".into(),
                    ));
                }
                if continuation != Some(cycle.id.as_str()) {
                    return Err(ReviewPublishError::Cycle(
                        "review_cycle_id must match the active publication review cycle".into(),
                    ));
                }
                if cycle.target != target {
                    return Err(ReviewPublishError::Cycle(
                        "publication review target cannot change within a cycle".into(),
                    ));
                }
                cycle
            }
            None => {
                if continuation.is_some() {
                    return Err(ReviewPublishError::Cycle(
                        "review_cycle_id does not name an active publication review cycle".into(),
                    ));
                }
                self.active.insert(ActiveCycle {
                    id: uuid::Uuid::new_v4().to_string(),
                    instance,
                    actor,
                    target,
                    next_review_index: 0,
                    blocking_rewrite_count: 0,
                })
            }
        };
        Ok(ReviewAttempt {
            cycle_id: cycle.id.clone(),
            review_index: cycle.next_review_index,
            blocking_rewrite_count: cycle.blocking_rewrite_count,
        })
    }

    fn advance_after_blocking_rewrite(
        &mut self,
        attempt: &ReviewAttempt,
        blocking_rewrite_count: u8,
    ) -> Result<String, ReviewPublishError> {
        let Some(active) = self.active.as_mut() else {
            return Err(ReviewPublishError::Cycle(
                "publication review cycle ended unexpectedly".into(),
            ));
        };
        if active.id != attempt.cycle_id
            || active.next_review_index != attempt.review_index
            || active.blocking_rewrite_count != attempt.blocking_rewrite_count
        {
            return Err(ReviewPublishError::Cycle(
                "publication review cycle advanced unexpectedly".into(),
            ));
        }
        let next_continuation = uuid::Uuid::new_v4().to_string();
        active.id.clone_from(&next_continuation);
        active.next_review_index = attempt.review_index + 1;
        active.blocking_rewrite_count = blocking_rewrite_count;
        Ok(next_continuation)
    }

    fn cache(
        &mut self,
        request_id: String,
        request: PublishRequest,
        outcome: CachedAttempt,
    ) -> Result<(), ReviewPublishError> {
        if self.attempts.len() >= MAX_ATTEMPT_RECORDS_PER_TURN {
            return Err(ReviewPublishError::Cycle(
                "publication review attempt limit reached for this turn".into(),
            ));
        }
        self.attempts
            .insert(request_id, AttemptRecord { request, outcome });
        Ok(())
    }

    fn clear_active(&mut self) {
        self.active = None;
    }
}

pub(crate) async fn review_and_publish(
    turn: &TurnContext,
    cancellation: &CancellationToken,
    config: &PublicationCriticConfig,
    handle: &TeamStateHandle,
    reviewed: ReviewedPublishAttempt,
) -> Result<ReviewPublishResult, ReviewPublishError> {
    if cancellation.is_cancelled() {
        return Err(ReviewPublishError::Cancelled);
    }

    let ReviewedPublishAttempt {
        actor,
        submission,
        request,
        continuation,
    } = reviewed;

    let reviews = turn
        .extension_data
        .get_or_init(TurnPublicationReviews::default);
    let state = Arc::clone(&reviews.state);
    let mut state = tokio::select! {
        guard = state.lock_owned() => guard,
        () = cancellation.cancelled() => return Err(ReviewPublishError::Cancelled),
    };

    if cancellation.is_cancelled() {
        if state.active_continuation_matches(
            handle.instance(),
            actor,
            &request,
            continuation.as_deref(),
        ) {
            state.clear_active();
        }
        return Err(ReviewPublishError::Cancelled);
    }

    if state
        .active
        .as_ref()
        .is_some_and(|cycle| cycle.instance != handle.instance())
    {
        state.clear_active();
    }

    let belongs_to_active_cycle = state.active_continuation_matches(
        handle.instance(),
        actor,
        &request,
        continuation.as_deref(),
    );

    let (preparation, history) = match handle.prepare_publish_with_history(
        actor,
        &submission,
        &request,
        MAX_PRIOR_PUBLICATIONS,
    ) {
        Ok(preparation) => preparation,
        Err(error) => {
            if belongs_to_active_cycle {
                state.clear_active();
            }
            observe(None, 0, None, None, false, "preparation_refused");
            return Err(ReviewPublishError::Team(error));
        }
    };
    match preparation {
        PublishPreparation::Committed(outcome) => {
            observe(None, 0, Some("committed_replay"), None, false, "committed");
            Ok(ReviewPublishResult::Committed {
                outcome,
                review: FinalReviewMetadata {
                    status: FinalReviewStatus::CommittedReplay,
                    review_attempt: None,
                    blocking_rewrite_count: 0,
                    failure_kind: None,
                },
            })
        }
        PublishPreparation::Ready(prepared) => {
            if let Some(cached) = state.cached_attempt(&submission.request_id, &request)? {
                return cached_result(cached);
            }

            if state.attempts.len() >= MAX_ATTEMPT_RECORDS_PER_TURN {
                return Err(ReviewPublishError::Cycle(
                    "publication review attempt limit reached for this turn".into(),
                ));
            }

            let attempt =
                state.begin_attempt(handle.instance(), actor, &request, continuation.as_deref())?;
            let client = match config.client() {
                Ok(client) => client,
                Err(_) => {
                    state.clear_active();
                    return Err(ReviewPublishError::InvalidPreparation);
                }
            };
            let packet = match build_packet(&client, prepared.clone(), history) {
                Ok(packet) => packet,
                Err(error) => {
                    state.clear_active();
                    observe(
                        Some(attempt.review_index + 1),
                        attempt.blocking_rewrite_count,
                        None,
                        None,
                        false,
                        "preparation_refused",
                    );
                    return Err(error);
                }
            };

            let verdict = match review(&client, packet, cancellation.clone()).await {
                Ok(verdict) => Some(verdict),
                Err(CriticFailure::Cancelled) => {
                    state.clear_active();
                    state.cache(submission.request_id, request, CachedAttempt::Cancelled)?;
                    observe(
                        Some(attempt.review_index + 1),
                        attempt.blocking_rewrite_count,
                        None,
                        None,
                        true,
                        "not_committed",
                    );
                    return Err(ReviewPublishError::Cancelled);
                }
                Err(failure) => {
                    let failure_kind = failure.log_code();
                    return commit(
                        &mut state,
                        cancellation,
                        handle,
                        PendingCommit {
                            actor,
                            submission,
                            request,
                            attempt,
                        },
                        CommitDecision {
                            status: FinalReviewStatus::FailureFallback,
                            failure_kind: Some(failure_kind),
                        },
                    );
                }
            };

            match verdict {
                Some(Verdict::Rewrite) if attempt.review_index < 2 => {
                    let rewrite_count = attempt.blocking_rewrite_count + 1;
                    let next_continuation =
                        state.advance_after_blocking_rewrite(&attempt, rewrite_count)?;
                    let rewrite = RewriteRequired {
                        status: "rewrite_required",
                        feedback_version: if attempt.review_index == 0 {
                            "v1"
                        } else {
                            "v2"
                        },
                        feedback: if attempt.review_index == 0 {
                            FEEDBACK_V1
                        } else {
                            FEEDBACK_V2
                        },
                        review_cycle_id: next_continuation,
                        review_attempt: attempt.review_index + 1,
                        blocking_rewrite_count: rewrite_count,
                        candidate: canonical_candidate(&prepared),
                    };
                    state.cache(
                        submission.request_id,
                        request,
                        CachedAttempt::BlockingRewrite(rewrite.clone()),
                    )?;
                    observe(
                        Some(rewrite.review_attempt),
                        rewrite.blocking_rewrite_count,
                        Some("rewrite"),
                        None,
                        false,
                        "blocked",
                    );
                    Ok(ReviewPublishResult::RewriteRequired(rewrite))
                }
                Some(Verdict::Rewrite) => commit(
                    &mut state,
                    cancellation,
                    handle,
                    PendingCommit {
                        actor,
                        submission,
                        request,
                        attempt,
                    },
                    CommitDecision {
                        status: FinalReviewStatus::RewriteExhausted,
                        failure_kind: None,
                    },
                ),
                Some(Verdict::Pass) => commit(
                    &mut state,
                    cancellation,
                    handle,
                    PendingCommit {
                        actor,
                        submission,
                        request,
                        attempt,
                    },
                    CommitDecision {
                        status: FinalReviewStatus::Pass,
                        failure_kind: None,
                    },
                ),
                None => unreachable!("typed review result is handled above"),
            }
        }
    }
}

fn cached_result(cached: CachedAttempt) -> Result<ReviewPublishResult, ReviewPublishError> {
    match cached {
        CachedAttempt::BlockingRewrite(rewrite) => {
            observe(
                Some(rewrite.review_attempt),
                rewrite.blocking_rewrite_count,
                Some("rewrite_replay"),
                None,
                false,
                "blocked",
            );
            Ok(ReviewPublishResult::RewriteRequired(rewrite))
        }
        CachedAttempt::Refused(message) => Err(ReviewPublishError::CachedRefusal(message)),
        CachedAttempt::Cancelled => Err(ReviewPublishError::Cancelled),
    }
}

async fn review(
    client: &PublicationCriticClient,
    packet: PublicationPacket,
    cancellation: CancellationToken,
) -> Result<Verdict, CriticFailure> {
    client.wait_until_ready(cancellation.clone()).await?;
    if cancellation.is_cancelled() {
        return Err(CriticFailure::Cancelled);
    }
    client.review_with_cancellation(packet, cancellation).await
}

fn commit(
    state: &mut ReviewState,
    cancellation: &CancellationToken,
    handle: &TeamStateHandle,
    pending: PendingCommit,
    decision: CommitDecision,
) -> Result<ReviewPublishResult, ReviewPublishError> {
    let PendingCommit {
        actor,
        submission,
        request,
        attempt,
    } = pending;
    let CommitDecision {
        status,
        failure_kind,
    } = decision;
    if cancellation.is_cancelled() {
        state.clear_active();
        state.cache(submission.request_id, request, CachedAttempt::Cancelled)?;
        observe(
            Some(attempt.review_index + 1),
            attempt.blocking_rewrite_count,
            None,
            failure_kind,
            true,
            "not_committed",
        );
        return Err(ReviewPublishError::Cancelled);
    }

    let outcome = match handle.publish(actor, &submission, request.clone()) {
        Ok(outcome) => outcome,
        Err(error) => {
            let message = error.to_string();
            state.clear_active();
            state.cache(
                submission.request_id,
                request,
                CachedAttempt::Refused(message),
            )?;
            observe(
                Some(attempt.review_index + 1),
                attempt.blocking_rewrite_count,
                status_verdict(&status),
                failure_kind,
                false,
                "refused",
            );
            return Err(ReviewPublishError::Team(error));
        }
    };
    state.clear_active();
    observe(
        Some(attempt.review_index + 1),
        attempt.blocking_rewrite_count,
        status_verdict(&status),
        failure_kind,
        false,
        "committed",
    );
    Ok(ReviewPublishResult::Committed {
        outcome,
        review: FinalReviewMetadata {
            status,
            review_attempt: Some(attempt.review_index + 1),
            blocking_rewrite_count: attempt.blocking_rewrite_count,
            failure_kind,
        },
    })
}

fn status_verdict(status: &FinalReviewStatus) -> Option<&'static str> {
    match status {
        FinalReviewStatus::Pass => Some("pass"),
        FinalReviewStatus::RewriteExhausted => Some("rewrite"),
        FinalReviewStatus::FailureFallback | FinalReviewStatus::CommittedReplay => None,
    }
}

fn build_packet(
    client: &PublicationCriticClient,
    prepared: PreparedPublish,
    history: Option<PreparedPublishHistory>,
) -> Result<PublicationPacket, ReviewPublishError> {
    let actor_role = match prepared.actor_role {
        ParticipantRole::Root => ActorRole::Root,
        ParticipantRole::Member => ActorRole::Member,
    };
    let (target_kind, title, continuity) = match &prepared.target {
        PreparedPublishTarget::NewEvent { title } => {
            if history.is_some() {
                return Err(ReviewPublishError::InvalidPreparation);
            }
            (
                TargetKind::NewEvent,
                title.clone(),
                ContinuityContext::NotApplicable,
            )
        }
        PreparedPublishTarget::ExistingEvent {
            event_id,
            title,
            authored_on_stale_view,
        } => {
            let history = history.ok_or(ReviewPublishError::InvalidPreparation)?;
            if history.event_id != *event_id {
                return Err(ReviewPublishError::InvalidPreparation);
            }
            let mut prior_publications = Vec::with_capacity(history.versions.len());
            for version in history.versions {
                let evidence_count = version.evidence_reference_count;
                let evidence = if evidence_count == 0 {
                    PriorEvidence::none()
                } else {
                    PriorEvidence::present(
                        evidence_count.min(usize::from(MAX_VISIBLE_FACT_REFERENCES)) as u16,
                        if evidence_count > usize::from(MAX_VISIBLE_FACT_REFERENCES) {
                            FactReferenceCountCoverage::Omitted
                        } else {
                            FactReferenceCountCoverage::Complete
                        },
                    )
                    .map_err(|_| ReviewPublishError::InvalidPreparation)?
                };
                let mut publication = PriorPublication::new(version.summary, evidence)
                    .map_err(|_| ReviewPublishError::InvalidPreparation)?;
                if let Some(handoff) = version.handoff {
                    publication = publication
                        .with_handoff(handoff)
                        .map_err(|_| ReviewPublishError::InvalidPreparation)?;
                }
                prior_publications.push(publication);
            }
            let coverage = if history.omitted_versions == 0 {
                ContinuityCoverage::Complete
            } else {
                ContinuityCoverage::Partial {
                    omitted_count: u32::try_from(history.omitted_versions).ok(),
                }
            };
            let continuity = ContinuityContext::available(
                history.revision.get(),
                if *authored_on_stale_view {
                    ContextFreshness::KnownStale
                } else {
                    ContextFreshness::Current
                },
                coverage,
                prior_publications,
            )
            .map_err(|_| ReviewPublishError::InvalidPreparation)?;
            (TargetKind::ExistingEvent, title.clone(), continuity)
        }
    };

    let local_scope = LocalScope::new(title).map_err(|_| ReviewPublishError::InvalidPreparation)?;
    let mut candidate = PublicationCandidate::new(prepared.summary)
        .map_err(|_| ReviewPublishError::InvalidPreparation)?;
    if let Some(handoff) = prepared.handoff {
        candidate = candidate
            .with_handoff(handoff)
            .map_err(|_| ReviewPublishError::InvalidPreparation)?;
    }
    PublicationPacket::new(
        client.expected_descriptor().identity.qualification.clone(),
        actor_role,
        target_kind,
        local_scope,
        candidate,
        continuity,
    )
    .map_err(|_| ReviewPublishError::InvalidPreparation)
}

fn canonical_candidate(prepared: &PreparedPublish) -> CanonicalCandidate {
    let title = match &prepared.target {
        PreparedPublishTarget::NewEvent { title }
        | PreparedPublishTarget::ExistingEvent { title, .. } => title.clone(),
    };
    CanonicalCandidate {
        title,
        summary: prepared.summary.clone(),
        handoff: prepared.handoff.clone(),
    }
}

fn observe(
    review_attempt: Option<u8>,
    blocking_rewrite_count: u8,
    verdict: Option<&'static str>,
    failure_kind: Option<&'static str>,
    cancelled: bool,
    commit_outcome: &'static str,
) {
    tracing::info!(
        target: "codex_core::publication_critic",
        publication_critic_mode = "enforced",
        review_attempt,
        blocking_rewrite_count,
        verdict,
        failure_kind,
        cancelled,
        commit_outcome,
        "publication review outcome"
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_publication_critic::MAX_HANDOFF_BYTES;
    use codex_publication_critic::MAX_HANDOFF_SCALARS;
    use codex_publication_critic::MAX_SUMMARY_BYTES;
    use codex_publication_critic::MAX_SUMMARY_SCALARS;
    use codex_publication_critic::MAX_TITLE_BYTES;
    use codex_publication_critic::MAX_TITLE_SCALARS;
    use codex_publication_critic::ModelIdentity;
    use codex_publication_critic::PassRule;
    use codex_publication_critic::QualificationIdentity;
    use codex_publication_critic::RuntimeLimits;
    use codex_publication_critic::ScoringIdentity;
    use codex_publication_critic::controlled_test_descriptor;
    use codex_team_state::FactCategory;
    use codex_team_state::HistoryQuery;
    use codex_team_state::NotedObservation;
    use codex_team_state::TeamRevision;
    use serde_json::Value;
    use std::time::Duration;

    fn request(target: PublishTarget, summary: &str) -> PublishRequest {
        PublishRequest {
            target,
            summary: summary.to_string(),
            handoff: None,
        }
    }

    #[test]
    fn cycle_requires_exact_continuation_and_stable_target() {
        let actor = ThreadId::new();
        let instance = TeamInstanceId::new();
        let event_id = format!("evt-1-{}", instance.tag())
            .parse()
            .expect("event id should parse");
        let original = request(PublishTarget::ExistingEvent { event_id }, "first");
        let mut state = ReviewState::default();
        let first = state
            .begin_attempt(instance, actor, &original, None)
            .expect("first attempt should start a cycle");

        assert!(matches!(
            state.begin_attempt(instance, actor, &original, None),
            Err(ReviewPublishError::Cycle(_))
        ));
        let other = request(
            PublishTarget::NewEvent {
                title: "different".to_string(),
            },
            "second",
        );
        assert!(matches!(
            state.begin_attempt(instance, actor, &other, Some(&first.cycle_id)),
            Err(ReviewPublishError::Cycle(_))
        ));
    }

    #[test]
    fn attempt_cache_distinguishes_raw_requests_after_canonical_collision() {
        let target = PublishTarget::NewEvent {
            title: "title".to_string(),
        };
        let first = request(target.clone(), "summary");
        let second = request(target, "different summary");
        let mut state = ReviewState::default();
        state
            .cache(
                "attempt".to_string(),
                first.clone(),
                CachedAttempt::Cancelled,
            )
            .unwrap();

        assert!(matches!(
            state.cached_attempt("attempt", &first),
            Ok(Some(CachedAttempt::Cancelled))
        ));
        assert!(matches!(
            state.cached_attempt("attempt", &second),
            Err(ReviewPublishError::Team(TeamError::RetryIdentityReused))
        ));
    }

    fn test_client() -> PublicationCriticClient {
        PublicationCriticConfig::new(
            "127.0.0.1:43119".parse::<std::net::SocketAddr>().unwrap(),
            controlled_test_descriptor(RuntimeLimits::production()),
            Duration::from_secs(1),
            Duration::from_secs(1),
        )
        .unwrap()
        .client()
        .unwrap()
    }

    fn contains_key(value: &Value, denied: &str) -> bool {
        match value {
            Value::Object(object) => {
                object.contains_key(denied)
                    || object.values().any(|value| contains_key(value, denied))
            }
            Value::Array(array) => array.iter().any(|value| contains_key(value, denied)),
            Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => false,
        }
    }

    fn assert_packet_golden(name: &str, packet: &PublicationPacket) -> Value {
        let goldens: Value =
            serde_json::from_str(include_str!("fixtures/publication_packet_v1.json"))
                .expect("tracked publication packet goldens must be valid JSON");
        let expected = goldens
            .get(name)
            .unwrap_or_else(|| panic!("missing publication packet golden {name}"));
        let actual = serde_json::to_value(packet).expect("packet must serialize");
        assert_eq!(&actual, expected);

        let decoded: PublicationPacket = serde_json::from_value(expected.clone())
            .expect("golden must use the typed packet wire");
        decoded.validate().expect("golden packet must validate");
        assert_eq!(
            serde_json::to_value(decoded).expect("decoded golden must serialize"),
            expected.clone()
        );
        actual
    }

    #[test]
    fn measurement_freeze_v2_matches_typed_publication_critic_identities() {
        let freeze_path = codex_utils_cargo_bin::find_resource!(
            "../../../eval/manifests/publication-critic/measurement-freeze-v2.json"
        )
        .expect("measurement freeze path must resolve");
        let freeze: Value =
            serde_json::from_slice(&std::fs::read(&freeze_path).unwrap_or_else(|error| {
                panic!(
                    "failed to read measurement freeze {}: {error}",
                    freeze_path.display()
                )
            }))
            .expect("measurement freeze must be valid JSON");

        let qualification_value = freeze["qualification_identity"].clone();
        let qualification: QualificationIdentity =
            serde_json::from_value(qualification_value.clone())
                .expect("qualification identity must match the Plan 055 type");
        assert_eq!(
            serde_json::to_value(&qualification).expect("qualification identity must serialize"),
            qualification_value
        );
        assert_eq!(
            qualification.packet_schema.name(),
            "rondo-publication-packet"
        );
        assert_eq!(qualification.packet_schema.revision(), "v1");
        assert_eq!(
            qualification.rubric.name(),
            "rondo-publication-qualification"
        );
        assert_eq!(qualification.rubric.revision(), "v1");

        let model_value = freeze["model_identity"].clone();
        let model: ModelIdentity = serde_json::from_value(model_value.clone())
            .expect("model identity must match the Plan 055 type");
        assert_eq!(
            serde_json::to_value(&model).expect("model identity must serialize"),
            model_value
        );
        assert_eq!(model.model.name(), "skywork-reward-v2-qwen3-1.7b");
        assert_eq!(
            model.model.revision(),
            "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc"
        );
        assert_eq!(
            model.tokenizer.name(),
            "skywork-reward-v2-qwen3-1.7b-tokenizer"
        );
        assert_eq!(
            model.tokenizer.revision(),
            "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc"
        );

        let scoring_value = freeze["scoring_identity"].clone();
        let scoring: ScoringIdentity = serde_json::from_value(scoring_value.clone())
            .expect("scoring identity must match the Plan 055 type");
        scoring.validate().expect("scoring identity must validate");
        assert_eq!(
            serde_json::to_value(&scoring).expect("scoring identity must serialize"),
            scoring_value
        );
        assert_eq!(scoring.domain.min(), 0.0);
        assert_eq!(scoring.domain.max(), 1.0);
        assert_eq!(scoring.threshold(), 0.9350569011196121);
        assert_eq!(
            scoring.pass_rule,
            PassRule::ScoreGreaterThanOrEqualToThreshold
        );
        assert_eq!(
            scoring.input_template.name(),
            "rondo-publication-packet-render"
        );
        assert_eq!(
            scoring.input_template.revision(),
            "v2-sha256-7765e03093e55b680fb9b6cfff5ee3974cfdd6a5b95362521756be918bb5cf9d"
        );
        assert_eq!(
            freeze["inference_contract"]["output_shape"],
            serde_json::json!(["batch", 1])
        );
    }

    #[test]
    fn existing_event_packet_is_bounded_event_local_and_never_serializes_fact_ids() {
        let handle = Arc::new(TeamStateHandle::default());
        let root = ThreadId::new();
        handle.register_participant(root, ParticipantRole::Root, "root".to_string());
        let initial = handle
            .publish(
                root,
                &Submission {
                    based_on: TeamRevision::INITIAL,
                    request_id: "initial".to_string(),
                },
                request(
                    PublishTarget::NewEvent {
                        title: "packet scope".to_string(),
                    },
                    "version 1",
                ),
            )
            .unwrap();
        for ordinal in 2..=5 {
            handle
                .publish(
                    root,
                    &Submission {
                        based_on: handle.revision(),
                        request_id: format!("prior-{ordinal}"),
                    },
                    request(
                        PublishTarget::ExistingEvent {
                            event_id: initial.event_id,
                        },
                        &format!("version {ordinal}"),
                    ),
                )
                .unwrap();
        }

        let mut one_fact_id = None;
        for ordinal in 0..33 {
            let item_id = format!("retained-item-{ordinal}");
            handle.note_observation(
                root,
                NotedObservation {
                    item_id: item_id.clone(),
                    call_id: format!("call-{ordinal}"),
                    category: FactCategory::ToolResultSuccess,
                    tool: "read_file".to_string(),
                },
            );
            one_fact_id = handle.confirm_observation(root, &item_id).or(one_fact_id);
        }
        handle
            .publish(
                root,
                &Submission {
                    based_on: handle.revision(),
                    request_id: "prior-6".to_string(),
                },
                request(
                    PublishTarget::ExistingEvent {
                        event_id: initial.event_id,
                    },
                    "version 6",
                ),
            )
            .unwrap();

        let raw = PublishRequest {
            target: PublishTarget::ExistingEvent {
                event_id: initial.event_id,
            },
            summary: "candidate summary".to_string(),
            handoff: Some("bounded handoff".to_string()),
        };
        let submission = Submission {
            based_on: TeamRevision::from_raw(5),
            request_id: "candidate".to_string(),
        };
        let (PublishPreparation::Ready(prepared), history) = handle
            .prepare_publish_with_history(root, &submission, &raw, MAX_PRIOR_PUBLICATIONS)
            .unwrap()
        else {
            panic!("candidate should not be committed yet")
        };
        let expected_summary = prepared.summary.clone();
        let packet = build_packet(&test_client(), prepared, history).unwrap();
        let packet = assert_packet_golden("existing_event", &packet);

        let keys = packet
            .as_object()
            .unwrap()
            .keys()
            .cloned()
            .collect::<Vec<_>>();
        assert_eq!(
            keys,
            vec![
                "actor_role",
                "candidate",
                "continuity",
                "evidence_v1",
                "local_scope",
                "qualification",
                "target_kind",
            ]
        );
        assert_eq!(packet["actor_role"], "root");
        assert_eq!(packet["target_kind"], "existing_event");
        assert_eq!(packet["candidate"]["summary"], expected_summary);
        assert_eq!(packet["continuity"]["state"], "available");
        assert_eq!(packet["continuity"]["freshness"], "known_stale");
        assert_eq!(packet["continuity"]["coverage"]["state"], "partial");
        assert_eq!(packet["continuity"]["coverage"]["omitted_count"], 2);
        assert_eq!(
            packet["continuity"]["prior_publications"]
                .as_array()
                .unwrap()
                .len(),
            MAX_PRIOR_PUBLICATIONS
        );
        assert!(
            packet["continuity"]["prior_publications"]
                .as_array()
                .unwrap()
                .iter()
                .any(|prior| {
                    prior["evidence"]["fact_references"]["visible_count"]
                        == MAX_VISIBLE_FACT_REFERENCES
                        && prior["evidence"]["fact_references"]["count_omitted"] == true
                })
        );
        for denied in [
            "event_id",
            "fact_id",
            "evidence_refs",
            "observation",
            "producer",
            "tool",
        ] {
            assert!(
                !contains_key(&packet, denied),
                "packet contains denied key {denied}"
            );
        }
        assert!(
            !packet
                .to_string()
                .contains(&one_fact_id.unwrap().to_string())
        );
    }

    #[test]
    fn new_event_packet_uses_authoritative_member_role_and_no_continuity() {
        let handle = Arc::new(TeamStateHandle::default());
        let member = ThreadId::new();
        handle.register_participant(member, ParticipantRole::Member, "member".to_string());
        let raw = request(
            PublishTarget::NewEvent {
                title: "member scope".to_string(),
            },
            "member candidate",
        );
        let (PublishPreparation::Ready(prepared), history) = handle
            .prepare_publish_with_history(
                member,
                &Submission {
                    based_on: TeamRevision::INITIAL,
                    request_id: "member-candidate".to_string(),
                },
                &raw,
                MAX_PRIOR_PUBLICATIONS,
            )
            .unwrap()
        else {
            panic!("candidate should not be committed yet")
        };
        let packet = build_packet(&test_client(), prepared, history).unwrap();
        let packet = assert_packet_golden("new_event", &packet);
        assert_eq!(packet["actor_role"], "member");
        assert_eq!(packet["target_kind"], "new_event");
        assert_eq!(packet["continuity"]["state"], "not_applicable");
    }

    #[test]
    fn packet_uses_the_same_canonical_over_cap_fields_that_store_commits() {
        let handle = Arc::new(TeamStateHandle::default());
        let member = ThreadId::new();
        handle.register_participant(member, ParticipantRole::Member, "member".to_string());
        let raw = PublishRequest {
            target: PublishTarget::NewEvent {
                title: "题".repeat(/*n*/ 230),
            },
            summary: "结".repeat(/*n*/ 2_030),
            handoff: Some("续".repeat(/*n*/ 1_030)),
        };
        let submission = Submission {
            based_on: TeamRevision::INITIAL,
            request_id: "canonical-over-cap".to_string(),
        };
        let (PublishPreparation::Ready(prepared), history) = handle
            .prepare_publish_with_history(member, &submission, &raw, MAX_PRIOR_PUBLICATIONS)
            .unwrap()
        else {
            panic!("candidate should not be committed yet")
        };
        let PreparedPublishTarget::NewEvent { title } = &prepared.target else {
            panic!("new event preparation must retain its target kind")
        };
        let expected_title = title.clone();
        let expected_summary = prepared.summary.clone();
        let expected_handoff = prepared
            .handoff
            .clone()
            .expect("the canonical handoff remains present");

        assert_eq!(expected_title.chars().count(), MAX_TITLE_SCALARS);
        assert_eq!(expected_summary.chars().count(), MAX_SUMMARY_SCALARS);
        assert_eq!(expected_handoff.chars().count(), MAX_HANDOFF_SCALARS);
        for value in [&expected_title, &expected_summary, &expected_handoff] {
            assert!(value.ends_with(" […truncated]"));
        }

        let packet = build_packet(&test_client(), prepared, history).unwrap();
        assert_eq!(packet.local_scope.title(), expected_title);
        assert_eq!(packet.candidate.summary(), expected_summary);
        assert_eq!(packet.candidate.handoff(), Some(expected_handoff.as_str()));

        let outcome = handle.publish(member, &submission, raw).unwrap();
        let committed = handle
            .history(
                member,
                &HistoryQuery {
                    event_id: Some(outcome.event_id),
                    limit: Some(1),
                    before: None,
                },
            )
            .unwrap();
        let event = &committed.events[0].event;
        let version = &event.versions[0];
        assert_eq!(event.title, expected_title);
        assert_eq!(version.summary, expected_summary);
        assert_eq!(version.handoff.as_deref(), Some(expected_handoff.as_str()));
    }

    #[test]
    fn plan054_sample_packets_deserialize_as_the_product_packet() {
        let fixture = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../eval/fixtures/publication-critic-v1/packets.jsonl");
        let body = std::fs::read_to_string(&fixture).unwrap_or_else(|error| {
            panic!(
                "cannot read Plan 054 packet fixture {}: {error}",
                fixture.display()
            )
        });
        let mut count = 0;
        for (index, line) in body.lines().enumerate() {
            let row: serde_json::Value = serde_json::from_str(line)
                .unwrap_or_else(|error| panic!("invalid Plan 054 JSON row {}: {error}", index + 1));
            let packet: PublicationPacket = serde_json::from_value(row["packet"].clone())
                .unwrap_or_else(|error| {
                    panic!(
                        "invalid Plan 054 PublicationPacket row {}: {error}",
                        index + 1
                    )
                });
            packet.validate().unwrap_or_else(|error| {
                panic!(
                    "invalid Plan 054 packet contract row {}: {error}",
                    index + 1
                )
            });
            count += 1;
        }
        assert_eq!(count, 24);
    }

    #[test]
    fn plan054_limit_document_matches_the_product_constants() {
        let fixture = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../../eval/templates/publication-critic/product-packet-limits-v1.json");
        let body = std::fs::read_to_string(&fixture).unwrap_or_else(|error| {
            panic!(
                "cannot read Plan 054 limit fixture {}: {error}",
                fixture.display()
            )
        });
        let limits: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(limits["title"]["max_scalars"], MAX_TITLE_SCALARS);
        assert_eq!(limits["title"]["max_bytes"], MAX_TITLE_BYTES);
        assert_eq!(limits["summary"]["max_scalars"], MAX_SUMMARY_SCALARS);
        assert_eq!(limits["summary"]["max_bytes"], MAX_SUMMARY_BYTES);
        assert_eq!(limits["handoff"]["max_scalars"], MAX_HANDOFF_SCALARS);
        assert_eq!(limits["handoff"]["max_bytes"], MAX_HANDOFF_BYTES);
        assert_eq!(limits["max_prior_publications"], MAX_PRIOR_PUBLICATIONS);
        assert_eq!(
            limits["max_visible_fact_references"],
            MAX_VISIBLE_FACT_REFERENCES
        );
    }
}

#[cfg(test)]
#[path = "publication_review_regression_tests.rs"]
mod regression_tests;

#[cfg(test)]
#[path = "publication_review_process_tests.rs"]
mod process_tests;
