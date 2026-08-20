//! Implements the MultiAgentV2 collaboration tool surface.

use crate::agent::AgentStatus;
use crate::agent::agent_resolver::resolve_agent_target;
use crate::context::ContextualUserFragment;
use crate::context::InterAgentMessage;
use crate::context::InterAgentMessageType;
use crate::function_tool::FunctionCallError;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolOutput;
use crate::tools::context::ToolPayload;
use crate::tools::context::boxed_tool_output;
use crate::tools::handlers::multi_agents_common::*;
use crate::tools::handlers::parse_arguments;
use crate::tools::registry::CoreToolRuntime;
use crate::tools::registry::ToolExecutor;
use codex_protocol::AgentPath;
use codex_protocol::items::CollabAgentTool;
use codex_protocol::items::CollabAgentToolCallItem;
use codex_protocol::items::CollabAgentToolCallStatus;
use codex_protocol::items::SubAgentActivityItem;
use codex_protocol::items::TurnItem;
use codex_protocol::models::ResponseInputItem;
use codex_protocol::openai_models::ReasoningEffort;
use codex_protocol::protocol::InterAgentCommunication;
use codex_protocol::protocol::SubAgentActivityKind;
use codex_tools::ToolName;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value as JsonValue;

pub(crate) use followup_task::Handler as FollowupTaskHandler;
pub(crate) use interrupt_agent::Handler as InterruptAgentHandler;
pub(crate) use list_agents::Handler as ListAgentsHandler;
pub(crate) use send_message::Handler as SendMessageHandler;
pub(crate) use spawn::Handler as SpawnAgentHandler;
pub(crate) use wait::Handler as WaitAgentHandler;

mod followup_task;
mod interrupt_agent;
mod list_agents;
mod message_tool;
mod send_message;
mod spawn;
pub(crate) mod wait;

pub(crate) async fn emit_sub_agent_activity(
    session: &crate::session::session::Session,
    turn: &crate::session::turn_context::TurnContext,
    item: SubAgentActivityItem,
) {
    let item = TurnItem::SubAgentActivity(item);
    session.emit_turn_item_started(turn, &item).await;
    session.emit_turn_item_completed(turn, item).await;
}

pub(crate) fn communication_from_tool_message(
    author: AgentPath,
    recipient: AgentPath,
    message: String,
    source: &crate::tools::context::ToolCallSource,
    trigger_turn: bool,
) -> InterAgentCommunication {
    // Only a call whose arguments actually arrived encrypted may be wrapped as
    // encrypted content. Code-mode nested calls never do: the runtime builds
    // `ToolPayload::Function` by serializing the model's own JS object and sets
    // `encrypted_function_args: None`, so `message` here is plain text.
    //
    // Wrapping it anyway put the literal task string into the child's first
    // request as `agent_message.content[].encrypted_content`, and the provider
    // rejected every such request with `invalid_encrypted_content` -- 8 of 8
    // member turns in the 2026-08-19 smoke, against 0 failures on root. The
    // member never completed a turn, so no team tool could ever be called.
    //
    // `Direct` keeps the existing behaviour: there the model may genuinely send
    // encrypted arguments, and `ToolCall::direct_source` is what distinguishes
    // that from the plaintext case.
    if !matches!(
        source,
        crate::tools::context::ToolCallSource::DirectPlaintextMessage
            | crate::tools::context::ToolCallSource::CodeMode { .. }
    ) {
        return InterAgentCommunication::new_encrypted(
            author,
            recipient,
            Vec::new(),
            message,
            trigger_turn,
        );
    }
    let message_type = if trigger_turn {
        InterAgentMessageType::NewTask
    } else {
        InterAgentMessageType::Message
    };
    let content =
        InterAgentMessage::new(message_type, recipient.clone(), author.clone(), message).render();
    InterAgentCommunication::new(author, recipient, Vec::new(), content, trigger_turn)
}

#[cfg(test)]
#[path = "multi_agents_v2_tests.rs"]
mod tests;
