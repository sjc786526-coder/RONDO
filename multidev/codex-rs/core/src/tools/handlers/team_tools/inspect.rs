use super::*;
use crate::tools::handlers::team_tools::spec::create_team_inspect_tool;
use codex_team_state::DumpCursor;
use codex_team_state::MAX_OBSERVE_LIMIT;
use codex_team_state::ObserveQuery;
use codex_team_state::TeamRevision;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_inspect")
    }

    fn spec(&self) -> ToolSpec {
        create_team_inspect_tool()
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
        session, payload, ..
    } = invocation;
    let arguments = function_arguments(payload)?;
    let args: InspectArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session)?;
    let query = ObserveQuery {
        limit: args.limit,
        offset: args.offset,
        after: args.after.map(TeamRevision::from_raw),
    };

    let payload = match args.action {
        InspectAction::Dump => {
            let availability = session
                .services
                .agent_control
                .producer_availability_snapshot()
                .await;
            let cursor = args
                .cursor
                .as_deref()
                .map(DumpCursor::decode)
                .transpose()
                .map_err(team_error)?;
            let page = access
                .handle()
                .dump(access.actor(), &availability, query, cursor)
                .map_err(team_error)?;
            let next_cursor = page.next_offset.map(|offset| {
                DumpCursor {
                    revision: page.revision,
                    availability_epoch: page.availability_epoch,
                    observe_generation: page.observe_generation,
                    offset,
                }
                .encode()
            });
            serde_json::json!({
                "action": "dump",
                "instance": page.instance.to_string(),
                "revision": page.revision.get(),
                "wake_generation": page.wake_generation,
                "availability_epoch": page.availability_epoch.get(),
                "observe_generation": page.observe_generation,
                "entries": page.entries,
                "total_entries": page.total_entries,
                "next_cursor": next_cursor,
                "limit": MAX_OBSERVE_LIMIT,
            })
        }
        InspectAction::Log => {
            let page = access
                .handle()
                .change_log(access.actor(), query)
                .map_err(team_error)?;
            serde_json::json!({
                "action": "log",
                "instance": page.instance.to_string(),
                "revision": page.revision.get(),
                "wake_generation": page.wake_generation,
                "entries": page.entries,
                "total_entries": page.total_entries,
                "next_offset": page.next_offset,
                "limit": MAX_OBSERVE_LIMIT,
            })
        }
        InspectAction::Stats => {
            let page = access
                .handle()
                .publication_stats(access.actor(), query)
                .map_err(team_error)?;
            serde_json::json!({
                "action": "stats",
                "authored_chars_unit": "unicode_scalar_values",
                "authored_chars_fields": [
                    "event_title_on_opening_version",
                    "version_summary",
                    "version_handoff"
                ],
                "revision": page.revision.get(),
                "wake_generation": page.wake_generation,
                "participants": page.entries,
                "total_entries": page.total_entries,
                "next_offset": page.next_offset,
                "limit": MAX_OBSERVE_LIMIT,
            })
        }
    };

    Ok(boxed_tool_output(TeamInspectResult { payload }))
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct InspectArgs {
    action: InspectAction,
    limit: Option<usize>,
    offset: Option<u32>,
    after: Option<u64>,
    cursor: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum InspectAction {
    Dump,
    Log,
    Stats,
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamInspectResult {
    #[serde(flatten)]
    payload: JsonValue,
}

impl ToolOutput for TeamInspectResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_inspect")
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_inspect")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_inspect")
    }
}
