use super::*;
use crate::agent::agent_resolver::resolve_agent_target;
use crate::tools::handlers::team_tools::notice::deliver_and_record;
use crate::tools::handlers::team_tools::publish::parse_event_id;
use crate::tools::handlers::team_tools::spec::create_team_route_tool;
use codex_team_state::RouteIntent;
use codex_team_state::RouteRequest;
use codex_team_state::Submission;
use codex_team_state::TeamRevision;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_route")
    }

    fn spec(&self) -> ToolSpec {
        create_team_route_tool()
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(handle_call(invocation))
    }
}

impl CoreToolRuntime for Handler {
    fn matches_kind(&self, payload: &ToolPayload) -> bool {
        matches!(payload, ToolPayload::Function { .. })
    }
}

async fn handle_call(invocation: ToolInvocation) -> Result<Box<dyn ToolOutput>, FunctionCallError> {
    let ToolInvocation {
        session,
        turn,
        step_context,
        payload,
        call_id,
        source,
        ..
    } = invocation;
    let arguments = function_arguments(payload)?;
    let args: RouteArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session).await?;

    let event_id = parse_event_id(&args.event_id)?;
    // Naming the target is part of deciding whether this route is legitimate at all, so it happens
    // before the commit: a target that cannot be named never becomes a grant. Everything that can
    // only fail while *delivering* is deliberately kept on the far side of the commit.
    let target = resolve_agent_target(&session, &turn, &args.target).await?;

    let submission = Submission {
        based_on: TeamRevision::from_raw(args.based_on_revision.unwrap_or_default()),
        request_id: args.request_id.unwrap_or(call_id),
    };
    let intent = match args.intent {
        WireIntent::Assign => RouteIntent::Assign,
        WireIntent::Notify => RouteIntent::Notify,
    };
    let outcome = access
        .handle()
        .route(
            access.actor(),
            &submission,
            RouteRequest {
                event_id,
                target,
                intent,
                note: args.note,
            },
        )
        .map_err(team_error)?;

    // From here the grant and, for work, the assignment are canonical facts. A repeat of a route
    // that already exists is not re-delivered: the notice for it was already sent or already
    // recorded as failed, and sending another copy on every retry is how a duplicate turns into a
    // second piece of apparent work. Its reported state comes from the canonical route, so a
    // failure waiting to be retried is never papered over as still pending.
    //
    // The revision travels with whichever state is reported, so the two always describe the same
    // canonical snapshot rather than the commit and its after-effect.
    let (delivery, revision) = if outcome.deduplicated {
        (outcome.dispatch.delivery.clone(), outcome.revision)
    } else {
        let recorded = deliver_and_record(
            &access,
            &session,
            &turn,
            &step_context,
            &source,
            &outcome.dispatch,
        )
        .await
        .map_err(team_error)?;
        (recorded.delivery, recorded.revision)
    };

    Ok(boxed_tool_output(TeamRouteResult {
        route_id: outcome.dispatch.route_id.to_string(),
        event_id: outcome.dispatch.event_id.to_string(),
        target: outcome.dispatch.target.to_string(),
        duty: outcome.dispatch.duty.to_string(),
        delivery: delivery.label().to_string(),
        delivery_error: delivery.failure_reason().map(str::to_string),
        revision: revision.get(),
        deduplicated: outcome.deduplicated,
    }))
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireIntent {
    Assign,
    Notify,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RouteArgs {
    event_id: String,
    target: String,
    intent: WireIntent,
    note: Option<String>,
    based_on_revision: Option<u64>,
    /// Optional caller-chosen retry identity. Omitted in the tool schema; the call id is the
    /// default and is what the harness itself can vouch for.
    #[serde(default)]
    request_id: Option<String>,
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamRouteResult {
    route_id: String,
    event_id: String,
    target: String,
    duty: String,
    /// `pending`, `delivered` or `failed`. The grant and assignment hold in every case.
    delivery: String,
    delivery_error: Option<String>,
    revision: u64,
    deduplicated: bool,
}

impl ToolOutput for TeamRouteResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_route")
    }

    fn success_for_logging(&self) -> bool {
        self.delivery_error.is_none()
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        // The route itself succeeded whatever the notice did, so the tool call is not reported as a
        // failure; the delivery fields are where the model reads what still needs retrying.
        tool_output_response_item(call_id, payload, self, Some(true), "team_route")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_route")
    }
}

#[cfg(test)]
#[path = "route_tests.rs"]
mod tests;
