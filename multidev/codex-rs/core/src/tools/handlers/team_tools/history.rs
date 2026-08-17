use super::*;
use crate::tools::handlers::team_tools::publish::parse_event_id;
use crate::tools::handlers::team_tools::spec::create_team_history_tool;
use codex_team_state::EventHistory;
use codex_team_state::FactId;
use codex_team_state::HistoryQuery;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_history")
    }

    fn spec(&self) -> ToolSpec {
        create_team_history_tool()
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
    let args: HistoryArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session)?;

    let event_id = args.event_id.as_deref().map(parse_event_id).transpose()?;
    let page = access
        .handle()
        .history(
            access.actor(),
            &HistoryQuery {
                event_id,
                limit: args.limit,
                before: args.before,
            },
        )
        .map_err(team_error)?;

    Ok(boxed_tool_output(TeamHistoryResult {
        revision: page.revision.get(),
        total_events: page.total_events,
        omitted_events: page.omitted_events,
        next_before: page.next_before,
        events: page.events.into_iter().map(render_event).collect(),
    }))
}

fn render_event(entry: EventHistory) -> HistoryEvent {
    let EventHistory {
        event,
        total_versions,
        omitted_versions,
    } = entry;
    HistoryEvent {
        event_id: event.id.to_string(),
        title: event.title,
        total_versions,
        omitted_versions,
        versions: event
            .versions
            .into_iter()
            .map(|version| HistoryVersion {
                version_id: version.id.to_string(),
                author: version.author_label,
                summary: version.summary,
                handoff: version.handoff,
                // The full list, unlike the projection's bounded preview: this is where a reader
                // comes to reach everything a version was published with.
                evidence_refs: version
                    .evidence_refs
                    .iter()
                    .map(FactId::to_string)
                    .collect(),
                producer_state: version.producer_state.to_string(),
                root_state: version.root_state.to_string(),
                authored_on_stale_view: version.authored_on_stale_view,
            })
            .collect(),
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct HistoryArgs {
    event_id: Option<String>,
    limit: Option<usize>,
    before: Option<u32>,
}

#[derive(Debug, Serialize)]
struct HistoryVersion {
    version_id: String,
    author: String,
    summary: String,
    handoff: Option<String>,
    /// Everything this version was published with. Read one with `team_evidence`.
    evidence_refs: Vec<String>,
    producer_state: String,
    root_state: String,
    authored_on_stale_view: bool,
}

#[derive(Debug, Serialize)]
struct HistoryEvent {
    event_id: String,
    title: String,
    total_versions: usize,
    omitted_versions: usize,
    versions: Vec<HistoryVersion>,
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamHistoryResult {
    revision: u64,
    total_events: usize,
    omitted_events: usize,
    /// Pass back as `before` to read the next page; absent when this page reached the oldest entry.
    next_before: Option<u32>,
    events: Vec<HistoryEvent>,
}

impl ToolOutput for TeamHistoryResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_history")
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_history")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_history")
    }
}
