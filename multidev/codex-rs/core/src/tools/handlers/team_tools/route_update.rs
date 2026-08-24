use super::*;
use crate::tools::handlers::team_tools::notice::deliver_and_record;
use crate::tools::handlers::team_tools::spec::create_team_route_update_tool;
use codex_team_state::RouteId;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_route_update")
    }

    fn spec(&self) -> ToolSpec {
        create_team_route_update_tool()
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
        source,
        ..
    } = invocation;
    let arguments = function_arguments(payload)?;
    let args: RouteUpdateArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session)?;
    let route_id = parse_route_id(&args.route_id)?;

    let result = match args.action {
        WireAction::End => {
            let outcome = access
                .handle()
                .end_assignment(access.actor(), route_id)
                .map_err(team_error)?;
            TeamRouteUpdateResult {
                route_id: outcome.route_id.to_string(),
                event_id: outcome.event_id.to_string(),
                duty: outcome.duty.to_string(),
                delivery: outcome.delivery.label().to_string(),
                delivery_error: outcome.delivery.failure_reason().map(str::to_string),
                revision: outcome.revision.get(),
            }
        }
        WireAction::RetryNotice => {
            // The route is re-read from the canonical state rather than rebuilt from anything the
            // model remembers, so a retry sends the same notice the grant was made with. Taking the
            // dispatch is itself the authorization, and it happens before the target is loaded or
            // anything is sent: only the participant that routed the event may resend its notice,
            // which is the same authority that records the result.
            let dispatch = access
                .handle()
                .route_dispatch(access.actor(), route_id)
                .map_err(team_error)?;
            let (delivery, revision) = if dispatch.delivery.is_delivered() {
                (dispatch.delivery.clone(), access.handle().revision())
            } else {
                let recorded =
                    deliver_and_record(&access, &session, &turn, &step_context, &source, &dispatch)
                        .await
                        .map_err(team_error)?;
                (recorded.delivery, recorded.revision)
            };
            TeamRouteUpdateResult {
                route_id: dispatch.route_id.to_string(),
                event_id: dispatch.event_id.to_string(),
                duty: dispatch.duty.to_string(),
                delivery: delivery.label().to_string(),
                delivery_error: delivery.failure_reason().map(str::to_string),
                revision: revision.get(),
            }
        }
    };

    Ok(boxed_tool_output(result))
}

fn parse_route_id(value: &str) -> Result<RouteId, FunctionCallError> {
    value.parse().map_err(|_| {
        team_error(TeamError::MalformedReference {
            reference: value.to_string(),
        })
    })
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireAction {
    End,
    RetryNotice,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RouteUpdateArgs {
    route_id: String,
    action: WireAction,
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamRouteUpdateResult {
    route_id: String,
    event_id: String,
    duty: String,
    delivery: String,
    delivery_error: Option<String>,
    revision: u64,
}

impl ToolOutput for TeamRouteUpdateResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_route_update")
    }

    fn success_for_logging(&self) -> bool {
        self.delivery_error.is_none()
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_route_update")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_route_update")
    }
}
