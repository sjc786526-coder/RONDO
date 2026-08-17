use super::*;
use crate::team::evidence::read_observation;
use crate::tools::handlers::team_tools::spec::create_team_evidence_tool;
use codex_team_state::FactId;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_evidence")
    }

    fn spec(&self) -> ToolSpec {
        create_team_evidence_tool()
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
    let args: EvidenceArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session)?;

    // Permission is decided from the canonical state before anything is fetched: holding an
    // identifier is not access, and a refusal must not be distinguishable by how long it took.
    let fact_id = parse_fact_id(&args.fact_id)?;
    let fact = access
        .handle()
        .read_fact(access.actor(), fact_id)
        .map_err(team_error)?;

    // Whether the observation can be fetched is a question about the producer's history right now,
    // so it is answered here and not cached on the fact. Nothing is written off: the reference stays
    // valid and resolvable, and a later read can succeed where this one did not.
    let read = read_observation(&session, &fact).await;

    Ok(boxed_tool_output(TeamEvidenceResult {
        fact_id: fact.id.to_string(),
        producer: fact.producer_label,
        tool: fact.locator.tool,
        category: fact.category.to_string(),
        availability: read.availability().to_string(),
        unavailable_reason: read.unavailable_reason().map(str::to_string),
        observation: read.observation().map(str::to_string),
        truncated: read.truncated(),
        total_chars: read.total_chars(),
    }))
}

fn parse_fact_id(value: &str) -> Result<FactId, FunctionCallError> {
    value.parse().map_err(|_| {
        team_error(TeamError::MalformedReference {
            reference: value.to_string(),
        })
    })
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct EvidenceArgs {
    fact_id: String,
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamEvidenceResult {
    fact_id: String,
    /// The participant whose work produced the observation.
    producer: String,
    /// The tool the harness dispatched, as the harness recorded it.
    tool: String,
    category: String,
    availability: String,
    unavailable_reason: Option<String>,
    /// The retained text, bounded. Absent when the observation is no longer readable.
    observation: Option<String>,
    truncated: bool,
    /// Length of the retained observation, so a truncated read says how much was left out.
    total_chars: Option<usize>,
}

impl ToolOutput for TeamEvidenceResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_evidence")
    }

    fn success_for_logging(&self) -> bool {
        self.observation.is_some()
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        // An honestly reported absence is a successful read of the team state, not a tool failure:
        // the reference resolved, and what it resolved to is that the observation is gone.
        tool_output_response_item(call_id, payload, self, Some(true), "team_evidence")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_evidence")
    }
}
