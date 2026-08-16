use super::*;
use crate::tools::handlers::team_tools::spec::create_team_update_tool;
use codex_team_state::LifecycleChange;
use codex_team_state::LifecycleRequest;
use codex_team_state::LifecycleTarget;
use codex_team_state::ProducerState;
use codex_team_state::RootState;
use codex_team_state::VersionId;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::plain("team_update")
    }

    fn spec(&self) -> ToolSpec {
        create_team_update_tool()
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
    let args: UpdateArgs = parse_arguments(&arguments)?;
    let access = resolve_access(&session)?;

    let mut targets = Vec::with_capacity(args.targets.len());
    for target in args.targets {
        let change = match (target.set_producer_state, target.set_root_state) {
            (Some(WireProducerState::Closed), None) => LifecycleChange::CloseProducer,
            (None, Some(state)) => LifecycleChange::SetRootState(state.into()),
            (Some(WireProducerState::Open), _) => {
                return Err(FunctionCallError::RespondToModel(
                    "a version cannot be reopened; publish a new version instead".to_string(),
                ));
            }
            (None, None) => {
                return Err(FunctionCallError::RespondToModel(
                    "each target must set either set_producer_state or set_root_state".to_string(),
                ));
            }
            (Some(WireProducerState::Closed), Some(_)) => {
                return Err(FunctionCallError::RespondToModel(
                    "producer state and root state are independent; change them in separate targets"
                        .to_string(),
                ));
            }
        };
        targets.push(LifecycleTarget {
            version_id: parse_version_id(&target.version_id)?,
            expected_producer_state: target.expect_producer_state.into(),
            expected_root_state: target.expect_root_state.into(),
            change,
        });
    }

    let outcome = access
        .handle()
        .update_lifecycle(access.actor(), LifecycleRequest { targets })
        .map_err(team_error)?;

    Ok(boxed_tool_output(TeamUpdateResult {
        revision: outcome.revision.get(),
        updated: outcome
            .updated
            .into_iter()
            .map(|snapshot| UpdatedVersion {
                version_id: snapshot.version_id.to_string(),
                producer_state: snapshot.producer_state.to_string(),
                root_state: snapshot.root_state.to_string(),
            })
            .collect(),
    }))
}

fn parse_version_id(value: &str) -> Result<VersionId, FunctionCallError> {
    value.parse().map_err(|_| {
        team_error(TeamError::MalformedReference {
            reference: value.to_string(),
        })
    })
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct UpdateArgs {
    targets: Vec<UpdateTargetArgs>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct UpdateTargetArgs {
    version_id: String,
    expect_producer_state: WireProducerState,
    expect_root_state: WireRootState,
    set_producer_state: Option<WireProducerState>,
    set_root_state: Option<WireRootState>,
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireProducerState {
    Open,
    Closed,
}

impl From<WireProducerState> for ProducerState {
    fn from(value: WireProducerState) -> Self {
        match value {
            WireProducerState::Open => Self::Open,
            WireProducerState::Closed => Self::Closed,
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum WireRootState {
    Pending,
    Tracking,
    Resolved,
}

impl From<WireRootState> for RootState {
    fn from(value: WireRootState) -> Self {
        match value {
            WireRootState::Pending => Self::Pending,
            WireRootState::Tracking => Self::Tracking,
            WireRootState::Resolved => Self::Resolved,
        }
    }
}

#[derive(Debug, Serialize)]
struct UpdatedVersion {
    version_id: String,
    producer_state: String,
    root_state: String,
}

#[derive(Debug, Serialize)]
pub(crate) struct TeamUpdateResult {
    revision: u64,
    updated: Vec<UpdatedVersion>,
}

impl ToolOutput for TeamUpdateResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "team_update")
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "team_update")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "team_update")
    }
}
