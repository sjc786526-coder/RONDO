//! Canonical publish preparation, validation and commit.

use super::CommittedOutcome;
use super::CommittedRequest;
use super::CommittedSubmission;
use super::MAX_HISTORY_LIMIT;
use super::TeamStore;
use crate::ids::EventId;
use crate::ids::VersionId;
use crate::model::AuthoredVersion;
use crate::model::RootState;
use crate::model::TeamEvent;
use crate::model::TeamVersion;
use crate::model::clamp_handoff;
use crate::model::clamp_summary;
use crate::model::clamp_title;
use crate::mutation::PublishOutcome;
use crate::mutation::PublishRequest;
use crate::mutation::PublishTarget;
use crate::mutation::Submission;
use crate::mutation::TeamError;
use crate::observe::ChangeKind;
use crate::observe::ChangeRecord;
use crate::observe::StoredWake;
use crate::publish::PreparedPublish;
use crate::publish::PreparedPublishHistory;
use crate::publish::PreparedPublishHistoryVersion;
use crate::publish::PreparedPublishTarget;
use crate::publish::PublishPreparation;
use codex_protocol::ThreadId;

struct ValidatedPublish {
    existing_index: Option<usize>,
    prepared: PreparedPublish,
}

enum PublishValidation {
    Committed(PublishOutcome),
    Ready(ValidatedPublish),
}

impl TeamStore {
    fn validate_publish(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: &PublishRequest,
    ) -> Result<PublishValidation, TeamError> {
        let role = self.require_participant(actor)?.role;
        if request.summary.trim().is_empty() {
            return Err(TeamError::InvalidRequest {
                reason: "summary must not be empty",
            });
        }

        let retry_key = (actor, submission.request_id.clone());
        if let Some(existing) = self.committed.get(&retry_key) {
            return match &existing.request {
                CommittedRequest::Publish(original) if original == request => {
                    match &existing.outcome {
                        CommittedOutcome::Publish(outcome) => {
                            Ok(PublishValidation::Committed(PublishOutcome {
                                deduplicated: true,
                                ..outcome.clone()
                            }))
                        }
                        CommittedOutcome::Route { .. } | CommittedOutcome::Retire(_) => {
                            Err(TeamError::RetryIdentityReused)
                        }
                    }
                }
                CommittedRequest::Publish(_)
                | CommittedRequest::Route(_)
                | CommittedRequest::Retire(_) => Err(TeamError::RetryIdentityReused),
            };
        }

        // Resolve the target before bumping the revision so a failed lookup leaves no trace.
        let (existing_index, target) = match &request.target {
            PublishTarget::NewEvent { title } if title.trim().is_empty() => {
                return Err(TeamError::InvalidRequest {
                    reason: "title must not be empty when opening a new event",
                });
            }
            PublishTarget::NewEvent { title } => (
                None,
                PreparedPublishTarget::NewEvent {
                    title: clamp_title(title),
                },
            ),
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
                (
                    Some(index),
                    PreparedPublishTarget::ExistingEvent {
                        event_id: *event_id,
                        title: self.events[index].title().to_string(),
                        authored_on_stale_view: self.events[index].last_changed_at()
                            > submission.based_on,
                    },
                )
            }
        };

        Ok(PublishValidation::Ready(ValidatedPublish {
            existing_index,
            prepared: PreparedPublish {
                actor_role: role,
                target,
                summary: clamp_summary(&request.summary),
                handoff: request.handoff.as_deref().map(clamp_handoff),
            },
        }))
    }

    /// Read-only publish validation and canonical authored-field preparation.
    pub fn prepare_publish(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: &PublishRequest,
    ) -> Result<PublishPreparation, TeamError> {
        match self.validate_publish(actor, submission, request)? {
            PublishValidation::Committed(outcome) => Ok(PublishPreparation::Committed(outcome)),
            PublishValidation::Ready(validated) => {
                Ok(PublishPreparation::Ready(validated.prepared))
            }
        }
    }

    /// Prepare a publish request and, for an existing Event, capture only the bounded public
    /// continuity fields used by Publication Critic from the same immutable store view.
    pub fn prepare_publish_with_history(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: &PublishRequest,
        history_limit: usize,
    ) -> Result<(PublishPreparation, Option<PreparedPublishHistory>), TeamError> {
        match self.validate_publish(actor, submission, request)? {
            PublishValidation::Committed(outcome) => {
                Ok((PublishPreparation::Committed(outcome), None))
            }
            PublishValidation::Ready(validated) => {
                let history = validated.existing_index.map(|index| {
                    let event = &self.events[index];
                    let versions = event.versions();
                    let limit = history_limit.clamp(1, MAX_HISTORY_LIMIT);
                    let omitted_versions = versions.len().saturating_sub(limit);
                    let versions = versions[omitted_versions..]
                        .iter()
                        .map(|version| PreparedPublishHistoryVersion {
                            summary: version.authored().summary.clone(),
                            handoff: version.authored().handoff.clone(),
                            evidence_reference_count: version.authored().evidence_refs.len(),
                        })
                        .collect();
                    PreparedPublishHistory {
                        event_id: event.id(),
                        revision: self.revision,
                        versions,
                        omitted_versions,
                    }
                });
                Ok((PublishPreparation::Ready(validated.prepared), history))
            }
        }
    }

    /// Publish a new event or append a version to an existing one.
    pub fn publish(
        &mut self,
        actor: ThreadId,
        submission: &Submission,
        request: PublishRequest,
    ) -> Result<PublishOutcome, TeamError> {
        let validated = match self.validate_publish(actor, submission, &request)? {
            PublishValidation::Committed(outcome) => return Ok(outcome),
            PublishValidation::Ready(validated) => validated,
        };
        let ValidatedPublish {
            existing_index,
            prepared,
        } = validated;
        let PreparedPublish {
            actor_role: role,
            target,
            summary,
            handoff,
        } = prepared;
        let retry_key = (actor, submission.request_id.clone());
        let original_request = CommittedRequest::Publish(request);

        let revision = self.revision.next();
        // Only an append can be authored against a stale view; an event nobody has seen yet has no
        // older state to be stale against.
        let authored_on_stale_view = match &target {
            PreparedPublishTarget::NewEvent { .. } => None,
            PreparedPublishTarget::ExistingEvent {
                authored_on_stale_view,
                ..
            } => (*authored_on_stale_view).then_some(submission.based_on),
        };
        let event_index = match (existing_index, target) {
            (Some(index), PreparedPublishTarget::ExistingEvent { .. }) => index,
            (Some(_), PreparedPublishTarget::NewEvent { .. }) => {
                unreachable!("a new-event target never resolves to an existing index")
            }
            (None, PreparedPublishTarget::NewEvent { title }) => {
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
            (None, PreparedPublishTarget::ExistingEvent { .. }) => {
                unreachable!("an existing-event target always resolves to an index above")
            }
        };

        // The root's own entries start as tracking and never wake the root; anyone else's start as
        // pending and give the root a coordination opportunity.
        let root_state = if role.is_root() {
            RootState::Tracking
        } else {
            RootState::Pending
        };
        // Evidence is attached mechanically, from what this author has recorded since its last
        // successful publish. The model is never asked to list it, and everything after this point
        // is infallible, so taking the window here is the same step as committing the version.
        let evidence_refs = self.take_publish_window(actor);
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
                evidence_refs: evidence_refs.clone(),
            },
            root_state,
            revision,
            authored_on_stale_view,
        ));
        event.last_changed_at = revision;
        let event_id = event.id();
        self.revision = revision;

        let wake = if role.is_root() {
            StoredWake::none("root_does_not_self_wake")
        } else {
            self.wake_root();
            self.root_wake("member_publish")
        };
        self.push_change(ChangeRecord {
            revision,
            actor,
            kind: ChangeKind::Publish,
            target: version_id.to_string(),
            before: None,
            after: Some(format!("producer=open root={root_state}")),
            wake,
        });

        let outcome = PublishOutcome {
            event_id,
            version_id,
            revision,
            evidence_refs,
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
}
