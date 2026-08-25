//! Selective routing: the root hands one event to one other participant.
//!
//! The ordering here is the whole point of the feature. A route commits the visibility grant and,
//! for work, the assignment; only then does anything get delivered. That is what makes "the notice
//! arrived but the target still cannot read the event" impossible — by the time a notice can be
//! observed, the grant it refers to already exists. Delivery is therefore a side effect with its
//! own retryable state on the committed object, and a notice that fails leaves the grant and the
//! assignment exactly where they were.

use super::CommittedOutcome;
use super::CommittedRequest;
use super::CommittedSubmission;
use super::TeamStore;
use crate::ids::RouteId;
use crate::model::DeliveryState;
use crate::model::RouteDuty;
use crate::model::TeamRoute;
use crate::model::clamp_delivery_reason;
use crate::model::clamp_route_note;
use crate::mutation::DeliveryOutcome;
use crate::mutation::DeliveryResult;
use crate::mutation::EndAssignmentOutcome;
use crate::mutation::RouteDispatch;
use crate::mutation::RouteIntent;
use crate::mutation::RouteOutcome;
use crate::mutation::RouteRequest;
use crate::mutation::Submission;
use crate::mutation::TeamError;
use crate::observe::ChangeKind;
use crate::observe::ChangeRecord;
use crate::observe::StoredWake;
use codex_protocol::ThreadId;

impl TeamStore {
    /// Grant `request.target` visibility of an event and, when work is intended, open an assignment.
    ///
    /// Everything is validated before the revision moves, so a refused route leaves no trace at all
    /// and a committed one is complete: there is no state in which the target has been notified of
    /// something it is not yet allowed to read.
    pub fn route(
        &mut self,
        actor: ThreadId,
        submission: &Submission,
        request: RouteRequest,
    ) -> Result<RouteOutcome, TeamError> {
        let role = self.require_participant(actor)?.role;
        if !role.is_root() {
            return Err(TeamError::NotPermitted {
                reason: "only the root routes events; publish instead to make your work visible",
            });
        }
        if request.target == actor {
            return Err(TeamError::NotPermitted {
                reason: "an event cannot be routed to yourself",
            });
        }
        // The target has to be a registered participant of *this* instance. Nothing about it comes
        // from the caller's payload beyond the name it asked for.
        if self.participant(request.target).is_none() {
            return Err(TeamError::UnknownTarget);
        }

        let retry_key = (actor, submission.request_id.clone());
        let original_request = CommittedRequest::Route(request.clone());
        // A replay is answered from the canonical route, not from a copy of what it looked like at
        // commit time: delivery keeps changing afterwards, and a frozen snapshot would report the
        // `pending` that every route starts with over a failure the caller still has to retry.
        let replayed = match self.committed.get(&retry_key) {
            Some(existing) => {
                if existing.request != original_request {
                    return Err(TeamError::RetryIdentityReused);
                }
                match existing.outcome {
                    CommittedOutcome::Route { route_id } => Some(route_id),
                    CommittedOutcome::Publish(_) | CommittedOutcome::Retire(_) => {
                        return Err(TeamError::RetryIdentityReused);
                    }
                }
            }
            None => None,
        };
        if let Some(route_id) = replayed {
            return self.deduplicated_outcome(route_id);
        }

        // Resolve the event before the revision moves, so a failed lookup leaves no trace.
        let event_index = self.event_index(request.event_id)?;

        // A hand-over the target is still working on is not repeated. Retry identity already covers
        // a replayed call, but a root that asks twice in two different turns would otherwise stack
        // a second assignment on the same participant for the same matter, and ending one of them
        // would then leave the event sitting in its view for no reason anyone can point at.
        if matches!(request.intent, RouteIntent::Assign) {
            let in_progress = self.events[event_index]
                .assignment_in_progress_for(request.target)
                .map(|route| (route.id(), route.note().map(str::to_string)));
            if let Some((existing_id, existing_note)) = in_progress {
                // Only an identical instruction is the same hand-over. Answering a changed note
                // with the old assignment would drop what the root just said, and opening a second
                // one would give the target two reasons to hold the same event. Refusing says so.
                if existing_note != request.note.as_deref().map(clamp_route_note) {
                    return Err(TeamError::AssignmentInProgress {
                        route_id: existing_id,
                    });
                }
                // Bind this identity to the assignment it was answered with. Without that the
                // identity stays unclaimed, and replaying it after the assignment ends would mint
                // a second one instead of repeating this answer.
                self.committed.insert(
                    retry_key,
                    CommittedSubmission {
                        request: original_request,
                        outcome: CommittedOutcome::Route {
                            route_id: existing_id,
                        },
                    },
                );
                return self.deduplicated_outcome(existing_id);
            }
        }

        let duty = match request.intent {
            RouteIntent::Assign => RouteDuty::Assigned,
            RouteIntent::Notify => RouteDuty::Notice,
        };
        let revision = self.revision.next();
        let tag = self.tag;
        let event = &mut self.events[event_index];
        let route_id = RouteId::new(
            tag,
            event.id().ordinal(),
            u32::try_from(event.routes().len().saturating_add(1)).unwrap_or(u32::MAX),
        );
        event.routes.push(TeamRoute::new(
            route_id,
            request.target,
            actor,
            request.note.clone(),
            duty,
            revision,
        ));
        event.last_changed_at = revision;
        self.revision = revision;

        // An assignment is a claim on the target's attention, so a member parked in a team wait
        // learns about it the same way the root does. An informational route deliberately does not:
        // being told something must never be dressed up as being given work.
        let wake = if matches!(request.intent, RouteIntent::Assign) {
            self.wake.signal(request.target);
            StoredWake::signalled(request.target, "assignment_wakes_target")
        } else {
            StoredWake::none("informational_route_does_not_wake")
        };
        self.push_change(ChangeRecord {
            revision,
            actor,
            kind: ChangeKind::Route,
            target: route_id.to_string(),
            before: None,
            after: Some(format!("duty={duty}")),
            wake,
        });

        // Read the committed route back rather than re-deriving it, so the dispatch reports the note
        // exactly as it was stored, clamp and all.
        let route_index = self.events[event_index].routes().len() - 1;
        let outcome = RouteOutcome {
            dispatch: self.dispatch_of(&self.events[event_index].routes()[route_index]),
            revision,
            deduplicated: false,
        };
        self.committed.insert(
            retry_key,
            CommittedSubmission {
                request: original_request,
                outcome: CommittedOutcome::Route { route_id },
            },
        );
        Ok(outcome)
    }

    /// Answer a repeated submission from the route it already produced.
    ///
    /// Both halves come from the state as it stands now, so the delivery reported here is the one
    /// the caller still has to act on and the revision belongs to the same snapshot as the rest.
    fn deduplicated_outcome(&self, route_id: RouteId) -> Result<RouteOutcome, TeamError> {
        let (event_index, route_index) = self.locate_route(route_id)?;
        Ok(RouteOutcome {
            dispatch: self.dispatch_of(&self.events[event_index].routes()[route_index]),
            revision: self.revision,
            deduplicated: true,
        })
    }

    /// Record how the notice for `route_id` went.
    ///
    /// Only the participant that made the route may report on it, and `Delivered` is terminal: a
    /// later report cannot un-deliver a notice the target already has, so an at-least-once delivery
    /// path that reports twice settles rather than oscillates.
    pub fn record_delivery(
        &mut self,
        actor: ThreadId,
        route_id: RouteId,
        result: DeliveryResult,
    ) -> Result<DeliveryOutcome, TeamError> {
        self.require_participant(actor)?;
        let (event_index, route_index) = self.locate_route(route_id)?;
        let route = &self.events[event_index].routes[route_index];
        if route.routed_by() != actor {
            return Err(TeamError::NotPermitted {
                reason: "only the participant that routed this event may report on its notice",
            });
        }

        let next = match result {
            DeliveryResult::Delivered => DeliveryState::Delivered,
            DeliveryResult::Failed { reason } => DeliveryState::Failed {
                reason: clamp_delivery_reason(&reason),
            },
        };
        if route.delivery().is_delivered() || *route.delivery() == next {
            return Ok(DeliveryOutcome {
                route_id,
                delivery: route.delivery().clone(),
                revision: self.revision,
                changed: false,
            });
        }

        let before = route.delivery().label().to_string();
        let revision = self.revision.next();
        let event = &mut self.events[event_index];
        event.routes[route_index].delivery = next.clone();
        event.last_changed_at = revision;
        self.revision = revision;
        self.push_change(ChangeRecord {
            revision,
            actor,
            kind: ChangeKind::Delivery,
            target: route_id.to_string(),
            before: Some(before),
            after: Some(next.label().to_string()),
            wake: StoredWake::none("delivery_does_not_wake"),
        });
        Ok(DeliveryOutcome {
            route_id,
            delivery: next,
            revision,
            changed: true,
        })
    }

    /// End the assignment carried by `route_id`.
    ///
    /// This retires one reason the event is in the target's active view and nothing else. The grant
    /// stays — what the target was shown remains readable through bounded history — and any other
    /// reason it is still active, including its own unfinished versions and other assignments,
    /// is untouched.
    pub fn end_assignment(
        &mut self,
        actor: ThreadId,
        route_id: RouteId,
    ) -> Result<EndAssignmentOutcome, TeamError> {
        let role = self.require_participant(actor)?.role;
        let (event_index, route_index) = self.locate_route(route_id)?;
        let route = &self.events[event_index].routes[route_index];
        if route.target() != actor && !role.is_root() {
            return Err(TeamError::NotPermitted {
                reason: "only the assignment's target or the root may end it",
            });
        }
        match route.duty() {
            RouteDuty::Notice => return Err(TeamError::NotAnAssignment { route_id }),
            RouteDuty::Ended => return Err(TeamError::AssignmentEnded { route_id }),
            RouteDuty::Assigned => {}
        }

        let revision = self.revision.next();
        let event = &mut self.events[event_index];
        let route = &mut event.routes[route_index];
        route.duty = RouteDuty::Ended;
        route.ended_by = Some(actor);
        route.ended_at = Some(revision);
        let delivery = route.delivery().clone();
        event.last_changed_at = revision;
        let event_id = event.id();
        self.revision = revision;
        // A member finishing what it was given is a change the root coordinates on.
        let wake = if !role.is_root() {
            self.wake_root();
            self.root_wake("member_ended_assignment")
        } else {
            StoredWake::none("root_does_not_self_wake")
        };
        self.push_change(ChangeRecord {
            revision,
            actor,
            kind: ChangeKind::EndAssignment,
            target: route_id.to_string(),
            before: Some("duty=assigned".to_string()),
            after: Some("duty=ended".to_string()),
            wake,
        });

        Ok(EndAssignmentOutcome {
            route_id,
            event_id,
            duty: RouteDuty::Ended,
            delivery,
            revision,
        })
    }

    /// Everything needed to build this route's notice again, for a retry.
    ///
    /// Only the participant that made the route may take this, which is the same authority that
    /// may record the result. Resending is an action on someone else's attention, so letting the
    /// target take a dispatch would let it send itself notices that the canonical state then
    /// refuses to account for — the send having already happened. The harness still never has to
    /// ask the model to remember what it was routing.
    pub fn route_dispatch(
        &self,
        actor: ThreadId,
        route_id: RouteId,
    ) -> Result<RouteDispatch, TeamError> {
        self.require_participant(actor)?;
        let (event_index, route_index) = self.locate_route(route_id)?;
        let route = &self.events[event_index].routes[route_index];
        if route.routed_by() != actor {
            return Err(TeamError::NotPermitted {
                reason: "only the participant that routed this event may resend its notice",
            });
        }
        Ok(self.dispatch_of(route))
    }

    fn dispatch_of(&self, route: &TeamRoute) -> RouteDispatch {
        RouteDispatch {
            instance: self.instance(),
            route_id: route.id(),
            event_id: route.id().event_id(),
            target: route.target(),
            duty: route.duty(),
            note: route.note().map(str::to_string),
            delivery: route.delivery().clone(),
        }
    }

    /// Resolve a route reference to its `(event, route)` position.
    fn locate_route(&self, route_id: RouteId) -> Result<(usize, usize), TeamError> {
        self.check_instance(route_id.instance())?;
        let event_index = self.event_index(route_id.event_id())?;
        let route_index = self.events[event_index]
            .route_position(route_id)
            .ok_or_else(|| TeamError::UnknownReference {
                reference: route_id.to_string(),
            })?;
        Ok((event_index, route_index))
    }
}

#[cfg(test)]
#[path = "route_tests.rs"]
mod tests;
