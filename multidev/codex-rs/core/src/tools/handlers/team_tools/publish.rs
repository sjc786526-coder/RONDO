use super::*;
use crate::tools::handlers::team_tools::spec::create_team_publish_tool;
use codex_team_state::EventId;
use codex_team_state::PublishRequest;
use codex_team_state::PublishTarget;
use codex_team_state::Submission;
use codex_team_state::TeamRevision;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_publish")
    }

    fn spec(&self) -> ToolSpec {
        create_team_publish_tool()
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
        payload,
        call_id,
        ..
    } = invocation;
    let arguments = function_arguments(payload)?;
    let args: PublishArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session)?;

    let target = match args.event_id {
        Some(event_id) => PublishTarget::ExistingEvent {
            event_id: parse_event_id(&event_id)?,
        },
        None => PublishTarget::NewEvent {
            title: args.title.ok_or_else(|| {
                FunctionCallError::RespondToModel(
                    "title is required when opening a new event".to_string(),
                )
            })?,
        },
    };

    // The retry identity is the harness's own call id unless the caller supplied a stable one, so
    // a replayed submission cannot mint a second event or version even if the model forgets to
    // pass anything. A caller that has not seen a revision is treated as working from the
    // beginning of time, which is exactly what the stale-view label is for.
    let submission = Submission {
        based_on: TeamRevision::from_raw(args.based_on_revision.unwrap_or_default()),
        request_id: args.request_id.unwrap_or(call_id),
    };
    let outcome = access
        .handle()
        .publish(
            access.actor(),
            &submission,
            PublishRequest {
                target,
                summary: args.summary,
                handoff: args.handoff,
            },
        )
        .map_err(team_error)?;

    Ok(boxed_tool_output(TeamPublishResult {
        event_id: outcome.event_id.to_string(),
        version_id: outcome.version_id.to_string(),
        revision: outcome.revision.get(),
        authored_on_stale_view: outcome.authored_on_stale_view,
        deduplicated: outcome.deduplicated,
    }))
}

pub(crate) fn parse_event_id(value: &str) -> Result<EventId, FunctionCallError> {
    value.parse().map_err(|_| {
        team_error(TeamError::MalformedReference {
            reference: value.to_string(),
        })
    })
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PublishArgs {
    event_id: Option<String>,
    title: Option<String>,
    summary: String,
    handoff: Option<String>,
    based_on_revision: Option<u64>,
    /// Optional caller-chosen retry identity. Omitted in the tool schema; the call id is the
    /// default and is what the harness itself can vouch for.
    #[serde(default)]
    request_id: Option<String>,
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamPublishResult {
    event_id: String,
    version_id: String,
    revision: u64,
    authored_on_stale_view: bool,
    deduplicated: bool,
}

impl ToolOutput for TeamPublishResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_publish")
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_publish")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_publish")
    }
}
