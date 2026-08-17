//! Root retirement of a version whose producer is confirmed truly unavailable.
//!
//! Retirement is an independent terminal. It does not pretend the author closed the item, does not
//! consume root attention, and does not touch routes, other versions or authored content.

use super::CommittedOutcome;
use super::CommittedRequest;
use super::CommittedSubmission;
use super::TeamStore;
use crate::availability::AvailabilityEpoch;
use crate::availability::AvailabilitySnapshot;
use crate::availability::ProducerAvailability;
use crate::model::ProducerState;
use crate::model::RetirementRecord;
use crate::model::clamp_retire_reason;
use crate::mutation::RetireOutcome;
use crate::mutation::RetireRequest;
use crate::mutation::Submission;
use crate::mutation::TeamError;
use crate::observe::ChangeKind;
use crate::observe::ChangeRecord;
use crate::observe::StoredWake;
use codex_protocol::ThreadId;

impl TeamStore {
    /// Retire one still-open version after the harness has confirmed its author is unrecoverable.
    ///
    /// `availability` is a freshly derived snapshot. The caller's expected epoch and class are
    /// checked against it so a stale picture cannot retire a producer that has become recoverable.
    pub fn retire(
        &mut self,
        actor: ThreadId,
        submission: &Submission,
        request: RetireRequest,
        availability: &AvailabilitySnapshot,
        live_epoch: AvailabilityEpoch,
    ) -> Result<RetireOutcome, TeamError> {
        let role = self.require_participant(actor)?.role;
        if !role.is_root() {
            return Err(TeamError::NotPermitted {
                reason: "only the root may retire a version",
            });
        }
        if request.reason.trim().is_empty() {
            return Err(TeamError::InvalidRequest {
                reason: "a non-empty retirement reason is required",
            });
        }

        let retry_key = (actor, submission.request_id.clone());
        let original_request = CommittedRequest::Retire(request.clone());
        if let Some(existing) = self.committed.get(&retry_key) {
            if existing.request != original_request {
                return Err(TeamError::RetryIdentityReused);
            }
            let CommittedOutcome::Retire(outcome) = &existing.outcome else {
                return Err(TeamError::RetryIdentityReused);
            };
            return Ok(RetireOutcome {
                deduplicated: true,
                ..outcome.clone()
            });
        }

        let (event_index, version_index) = self.locate_version(request.version_id)?;
        let version = &self.events[event_index].versions[version_index];
        if version.producer_state() != request.expected_producer_state
            || version.root_state() != request.expected_root_state
        {
            return Err(TeamError::LifecycleConflict {
                current: crate::mutation::LifecycleSnapshot {
                    version_id: request.version_id,
                    producer_state: version.producer_state(),
                    root_state: version.root_state(),
                },
            });
        }
        if version.is_retired() {
            return Err(TeamError::VersionRetired {
                version_id: request.version_id,
            });
        }
        if version.producer_state() != ProducerState::Open {
            return Err(TeamError::VersionClosed {
                version_id: request.version_id,
            });
        }

        let author = version.authored().author;
        if live_epoch != availability.epoch {
            return Err(TeamError::AvailabilityConflict {
                availability: ProducerAvailability::Unknown,
                availability_epoch: live_epoch,
            });
        }
        let current_class = availability
            .class_of(author)
            .unwrap_or(ProducerAvailability::Unknown);
        if availability.epoch != request.expected_availability_epoch
            || request.expected_availability != current_class
        {
            return Err(TeamError::AvailabilityConflict {
                availability: current_class,
                availability_epoch: availability.epoch,
            });
        }
        if !current_class.is_unavailable() {
            return Err(TeamError::ProducerNotUnavailable {
                availability: current_class,
                availability_epoch: availability.epoch,
            });
        }

        let reason = clamp_retire_reason(&request.reason);
        let revision = self.revision.next();
        let event = &mut self.events[event_index];
        let version = &mut event.versions[version_index];
        let before = format!(
            "producer={} root={}",
            version.producer_state, version.root_state
        );
        let after = format!(
            "producer={} root={} retired availability={} epoch={} reason={}",
            version.producer_state, version.root_state, current_class, availability.epoch, reason
        );
        version.retirement = Some(RetirementRecord {
            retired_by: actor,
            reason: reason.clone(),
            retired_at: revision,
            availability: current_class,
            availability_epoch: availability.epoch,
        });
        event.last_changed_at = revision;
        self.revision = revision;
        self.push_change(ChangeRecord {
            revision,
            actor,
            kind: ChangeKind::Retire,
            target: request.version_id.to_string(),
            before: Some(before),
            after: Some(after),
            wake: StoredWake::None {
                rule: "root_does_not_self_wake",
            },
        });

        let outcome = RetireOutcome {
            revision,
            version_id: request.version_id,
            retired_by: actor,
            reason,
            availability: current_class,
            availability_epoch: availability.epoch,
            deduplicated: false,
        };
        self.committed.insert(
            retry_key,
            CommittedSubmission {
                request: original_request,
                outcome: CommittedOutcome::Retire(outcome.clone()),
            },
        );
        Ok(outcome)
    }
}

#[cfg(test)]
#[path = "retire_tests.rs"]
mod tests;
