use super::spec::create_team_retire_tool;
use super::update::WireProducerState;
use super::update::WireRootState;
use super::update::parse_version_id;
use super::*;
use codex_team_state::AvailabilityEpoch;
use codex_team_state::ProducerAvailability;
use codex_team_state::RetireRequest;
use codex_team_state::Submission;
use codex_team_state::TeamRevision;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_retire")
    }

    fn spec(&self) -> ToolSpec {
        create_team_retire_tool()
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
    let args: RetireArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session)?;
    let control = session.services.agent_control.clone();
    let availability = control.producer_availability_snapshot().await;
    let state = control.upgrade().ok();
    let _gate = state
        .as_ref()
        .map(|state| state.lock_availability_transition());
    if state
        .as_ref()
        .is_some_and(|state| state.store_transition_in_progress())
    {
        return Err(team_error(
            codex_team_state::TeamError::AvailabilityConflict {
                availability: ProducerAvailability::Unknown,
                availability_epoch: control.availability_epoch(),
            },
        ));
    }

    let submission = Submission {
        based_on: TeamRevision::from_raw(args.based_on_revision.unwrap_or_default()),
        request_id: args.request_id.unwrap_or(call_id),
    };
    let outcome = access
        .handle()
        .retire(
            access.actor(),
            &submission,
            RetireRequest {
                version_id: parse_version_id(&args.version_id)?,
                expected_producer_state: args.expect_producer_state.into(),
                expected_root_state: args.expect_root_state.into(),
                expected_availability: args.expect_availability.into(),
                expected_availability_epoch: AvailabilityEpoch::from_raw(
                    args.expect_availability_epoch,
                ),
                reason: args.reason,
            },
            &availability,
            || control.availability_epoch(),
        )
        .map_err(team_error)?;

    Ok(boxed_tool_output(TeamRetireResult {
        revision: outcome.revision.get(),
        version_id: outcome.version_id.to_string(),
        retired_by: access
            .handle()
            .participant(outcome.retired_by)
            .map(|participant| participant.label)
            .unwrap_or_else(|| outcome.retired_by.to_string()),
        reason: outcome.reason,
        availability: outcome.availability.to_string(),
        availability_epoch: outcome.availability_epoch.get(),
        deduplicated: outcome.deduplicated,
    }))
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct RetireArgs {
    version_id: String,
    expect_producer_state: WireProducerState,
    expect_root_state: WireRootState,
    expect_availability: WireAvailability,
    expect_availability_epoch: u64,
    reason: String,
    based_on_revision: Option<u64>,
    #[serde(default)]
    request_id: Option<String>,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireAvailability {
    Available,
    RecoverableUnloaded,
    Unavailable,
    Unknown,
}

impl From<WireAvailability> for ProducerAvailability {
    fn from(value: WireAvailability) -> Self {
        match value {
            WireAvailability::Available => Self::Available,
            WireAvailability::RecoverableUnloaded => Self::RecoverableUnloaded,
            WireAvailability::Unavailable => Self::Unavailable,
            WireAvailability::Unknown => Self::Unknown,
        }
    }
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamRetireResult {
    revision: u64,
    version_id: String,
    retired_by: String,
    reason: String,
    availability: String,
    availability_epoch: u64,
    deduplicated: bool,
}

impl ToolOutput for TeamRetireResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_retire")
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_retire")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_retire")
    }
}
