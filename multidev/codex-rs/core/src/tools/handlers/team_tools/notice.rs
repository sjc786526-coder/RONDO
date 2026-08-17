//! Delivery of a route's compact notice.
//!
//! Everything here runs strictly after the canonical route has been committed, and every failure it
//! can produce is recorded on that route rather than raised as "the route did not happen". That
//! split is the point: loading the target, resolving its path and handing the message to its
//! delivery path are all things that can fail transiently, and none of them may decide whether the
//! target is allowed to read the event.

use crate::agent_communication::AgentCommunicationContext;
use crate::agent_communication::AgentCommunicationKind;
use crate::session::session::Session;
use crate::session::step_context::StepContext;
use crate::session::turn_context::TurnContext;
use crate::team::TeamAccess;
use crate::tools::context::ToolCallSource;
use crate::tools::handlers::multi_agents_common::build_agent_resume_config;
use crate::tools::handlers::multi_agents_v2::communication_from_tool_message;
use codex_protocol::AgentPath;
use codex_team_state::DeliveryOutcome;
use codex_team_state::DeliveryResult;
use codex_team_state::DeliveryState;
use codex_team_state::RouteDispatch;
use std::sync::Arc;

/// Deliver the notice for `dispatch` and record how it went on the canonical route.
///
/// The returned state is always the one now stored, so a caller reporting to the model cannot claim
/// a delivery the team state does not agree with.
pub(super) async fn deliver_and_record(
    access: &TeamAccess,
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    step_context: &StepContext,
    source: &ToolCallSource,
    dispatch: &RouteDispatch,
) -> DeliveryOutcome {
    let result = match deliver(session, turn, step_context, source, dispatch).await {
        Ok(()) => DeliveryResult::Delivered,
        Err(reason) => {
            tracing::warn!(
                route_id = %dispatch.route_id,
                %reason,
                "team route notice could not be delivered; the grant stands and the notice can be retried"
            );
            DeliveryResult::Failed { reason }
        }
    };
    match access
        .handle()
        .record_delivery(access.actor(), dispatch.route_id, result)
    {
        Ok(outcome) => outcome,
        Err(err) => {
            // Only reachable if the route vanished or changed hands between the two calls, which
            // the store's rules make impossible. Report the problem rather than a delivery nobody
            // recorded.
            tracing::error!(route_id = %dispatch.route_id, %err, "could not record route delivery");
            DeliveryOutcome {
                route_id: dispatch.route_id,
                delivery: DeliveryState::Failed {
                    reason: err.to_string(),
                },
                revision: access.handle().revision(),
                changed: false,
            }
        }
    }
}

async fn deliver(
    session: &Arc<Session>,
    turn: &Arc<TurnContext>,
    step_context: &StepContext,
    source: &ToolCallSource,
    dispatch: &RouteDispatch,
) -> Result<(), String> {
    let agent_control = &session.services.agent_control;
    let receiver = agent_control
        .ensure_agent_known(dispatch.target)
        .map_err(|err| err.to_string())?;
    let recipient = receiver
        .agent_path
        .clone()
        .ok_or_else(|| "the target agent has no agent path to deliver to".to_string())?;
    let resume_config =
        build_agent_resume_config(turn.as_ref(), step_context.environments.primary())
            .map_err(|err| err.to_string())?;
    // A member that was evicted from residency has to come back before anything can reach it.
    agent_control
        .ensure_v2_agent_loaded(resume_config, dispatch.target)
        .await
        .map_err(|err| err.to_string())?;

    let author = turn
        .session_source
        .get_agent_path()
        .unwrap_or_else(AgentPath::root);
    // Work asks the target to start or continue, which is what `trigger_turn` means; the existing
    // execution path then decides on its own whether that is a new turn or a message folded into
    // the turn already running. An informational notice never asks for either.
    let trigger_turn = dispatch.duty.is_assigned();
    let communication = communication_from_tool_message(
        author,
        recipient,
        notice_text(dispatch),
        source,
        trigger_turn,
    );
    let kind = if trigger_turn {
        AgentCommunicationKind::Followup
    } else {
        AgentCommunicationKind::Message
    };
    let parent_turn_id = trigger_turn.then(|| turn.sub_id.clone());
    agent_control
        .send_inter_agent_communication(
            dispatch.target,
            communication,
            AgentCommunicationContext::new(kind, session.thread_id),
            parent_turn_id,
        )
        .await
        .map_err(|err| err.to_string())?;
    Ok(())
}

/// The notice body: locators, what is being asked, and the root's own short hint.
///
/// It deliberately carries no title, summary, handoff or chain. The target reads those from the
/// canonical state, so a notice can never become a second copy that drifts from the real event —
/// and a duplicate notice is recognisable because it names the same route.
fn notice_text(dispatch: &RouteDispatch) -> String {
    let RouteDispatch {
        instance,
        route_id,
        event_id,
        duty,
        note,
        ..
    } = dispatch;
    let mut text = format!(
        "Team route {route_id} (team_instance={instance}): event {event_id} is now visible to you as {duty}.\n\
         Read its full chain with team_history(event_id=\"{event_id}\"); this notice carries no event content.\n"
    );
    // Only an assignment asks for anything. Telling an informational recipient to publish would
    // manufacture work out of a notice, which is the distinction the two intents exist to keep.
    if duty.is_assigned() {
        text.push_str(&format!(
            "Record what you conclude with team_publish(event_id=\"{event_id}\", ...), and end the assignment with team_route_update(route_id=\"{route_id}\", action=\"end\") when you are done.\n"
        ));
    } else {
        text.push_str(&format!(
            "Nothing is being asked of you. You may add to the event with team_publish(event_id=\"{event_id}\", ...) if you have something to contribute.\n"
        ));
    }
    if let Some(note) = note {
        text.push_str(&format!("Note from the root: {note}\n"));
    }
    text
}
