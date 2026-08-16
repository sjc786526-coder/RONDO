//! The model-facing surface of the canonical team world state.
//!
//! Three tools cover what M-1 needs: publish a semantic checkpoint, update the lifecycle of
//! specific entries, and drill back into history the active view has dropped. None of them accepts
//! an author, producer or root claim from the model; the acting participant is always the calling
//! session's own identity.

use crate::function_tool::FunctionCallError;
use crate::team::TeamAccess;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolOutput;
use crate::tools::context::ToolPayload;
use crate::tools::context::boxed_tool_output;
use crate::tools::handlers::multi_agents_common::function_arguments;
use crate::tools::handlers::multi_agents_common::tool_output_code_mode_result;
use crate::tools::handlers::multi_agents_common::tool_output_json_text;
use crate::tools::handlers::multi_agents_common::tool_output_response_item;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::CoreToolRuntime;
use crate::tools::registry::ToolExecutor;
use codex_protocol::models::ResponseInputItem;
use codex_team_state::TeamError;
use codex_tools::ToolName;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value as JsonValue;

pub(crate) use history::Handler as TeamHistoryHandler;
pub(crate) use publish::Handler as TeamPublishHandler;
pub(crate) use update::Handler as TeamUpdateHandler;

mod history;
mod publish;
pub(crate) mod spec;
mod update;

/// Team refusals are reported to the model rather than failing the turn: every one of them is
/// something the model can act on, such as re-reading the active view after a reset or a conflict.
fn team_error(err: TeamError) -> FunctionCallError {
    FunctionCallError::RespondToModel(err.to_string())
}

fn resolve_access(
    invocation_session: &crate::session::session::Session,
) -> Result<TeamAccess, FunctionCallError> {
    TeamAccess::resolve(invocation_session).map_err(team_error)
}
