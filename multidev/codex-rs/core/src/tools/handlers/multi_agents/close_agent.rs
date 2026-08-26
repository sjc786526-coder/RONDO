use super::*;
use crate::tools::handlers::multi_agents_spec::create_close_agent_tool_v1;
use codex_protocol::AgentPath;
use codex_protocol::error::CodexErrorDetails;
use codex_tools::ToolSpec;

pub(crate) struct Handler;

impl ToolExecutor<ToolInvocation> for Handler {
    fn tool_name(&self) -> ToolName {
        ToolName::namespaced(MULTI_AGENT_V1_NAMESPACE, "close_agent")
    }

    fn spec(&self) -> ToolSpec {
        create_close_agent_tool_v1()
    }

    fn search_info(&self) -> Option<ToolSearchInfo> {
        multi_agent_tool_search_info(
            "close_agent close shutdown stop agent subagent thread status target",
            self.spec(),
        )
    }

    fn handle(&self, invocation: ToolInvocation) -> codex_tools::ToolExecutorFuture<'_> {
        Box::pin(async move {
            handle_close_agent(invocation, /*resolve_v2_target*/ false)
                .await
                .map(boxed_tool_output)
        })
    }
}

pub(crate) async fn handle_close_agent(
    invocation: ToolInvocation,
    resolve_v2_target: bool,
) -> Result<CloseAgentResult, FunctionCallError> {
    let ToolInvocation {
        session,
        turn,
        payload,
        call_id,
        ..
    } = invocation;
    let arguments = function_arguments(payload)?;
    let args: CloseAgentArgs = parse_arguments(&arguments)?;
    let agent_id = if resolve_v2_target {
        crate::agent::agent_resolver::resolve_agent_target(&session, &turn, &args.target).await?
    } else {
        parse_agent_id_target(&args.target)?
    };
    let receiver_agent = if resolve_v2_target {
        let receiver_agent = session
            .services
            .agent_control
            .ensure_agent_known(agent_id)
            .map_err(|err| collab_agent_error(agent_id, err))?;
        if receiver_agent
            .agent_path
            .as_ref()
            .is_some_and(AgentPath::is_root)
        {
            return Err(FunctionCallError::RespondToModel(
                "root is not a spawned agent".to_string(),
            ));
        }
        if agent_id == session.thread_id {
            return Err(FunctionCallError::RespondToModel(
                "an agent cannot close itself; return your result and let the parent close you if needed"
                    .to_string(),
            ));
        }
        Some(receiver_agent)
    } else {
        session.services.agent_control.get_agent_metadata(agent_id)
    };
    let known_agent = receiver_agent.is_some();
    let receiver_agent = receiver_agent.unwrap_or_default();
    session
        .emit_turn_item_started(
            &turn,
            &TurnItem::CollabAgentToolCall(CollabAgentToolCallItem {
                id: call_id.clone(),
                tool: CollabAgentTool::CloseAgent,
                status: CollabAgentToolCallStatus::InProgress,
                sender_thread_id: session.thread_id,
                receiver_thread_ids: vec![agent_id],
                receiver_agents: Vec::new(),
                prompt: None,
                model: None,
                reasoning_effort: None,
                agents_states: Default::default(),
            }),
        )
        .await;
    let status = match session
        .services
        .agent_control
        .subscribe_status(agent_id)
        .await
    {
        Ok(mut status_rx) => status_rx.borrow_and_update().clone(),
        Err(err)
            if known_agent && matches!(err.details(), CodexErrorDetails::ThreadNotFound(_)) =>
        {
            session.services.agent_control.get_status(agent_id).await
        }
        Err(err) => {
            let status = session.services.agent_control.get_status(agent_id).await;
            session
                .emit_turn_item_completed(
                    &turn,
                    TurnItem::CollabAgentToolCall(CollabAgentToolCallItem {
                        id: call_id.clone(),
                        tool: CollabAgentTool::CloseAgent,
                        status: collab_tool_call_status(&status, Some(agent_id)),
                        sender_thread_id: session.thread_id(),
                        receiver_thread_ids: vec![agent_id],
                        receiver_agents: vec![CollabAgentRef {
                            thread_id: agent_id,
                            agent_nickname: receiver_agent.agent_nickname.clone(),
                            agent_role: receiver_agent.agent_role.clone(),
                        }],
                        prompt: None,
                        model: None,
                        reasoning_effort: None,
                        agents_states: [(agent_id, status)].into_iter().collect(),
                    }),
                )
                .await;
            return Err(collab_agent_error(agent_id, err));
        }
    };
    let result = Box::pin(session.services.agent_control.close_agent(agent_id))
        .await
        .map_err(|err| collab_agent_error(agent_id, err))
        .map(|_| ());
    let call_status = if result.is_ok() {
        CollabAgentToolCallStatus::Completed
    } else {
        collab_tool_call_status(&status, Some(agent_id))
    };
    session
        .emit_turn_item_completed(
            &turn,
            TurnItem::CollabAgentToolCall(CollabAgentToolCallItem {
                id: call_id,
                tool: CollabAgentTool::CloseAgent,
                status: call_status,
                sender_thread_id: session.thread_id,
                receiver_thread_ids: vec![agent_id],
                receiver_agents: vec![CollabAgentRef {
                    thread_id: agent_id,
                    agent_nickname: receiver_agent.agent_nickname,
                    agent_role: receiver_agent.agent_role,
                }],
                prompt: None,
                model: None,
                reasoning_effort: None,
                agents_states: [(agent_id, status.clone())].into_iter().collect(),
            }),
        )
        .await;
    result?;

    Ok(CloseAgentResult {
        previous_status: status,
    })
}

impl CoreToolRuntime for Handler {
    fn matches_kind(&self, payload: &ToolPayload) -> bool {
        matches!(payload, ToolPayload::Function { .. })
    }
}

#[derive(Debug, Deserialize, Serialize)]
pub(crate) struct CloseAgentResult {
    pub(crate) previous_status: AgentStatus,
}

impl ToolOutput for CloseAgentResult {
    fn log_preview(&self) -> String {
        tool_output_json_text(self, "close_agent")
    }

    fn success_for_logging(&self) -> bool {
        true
    }

    fn to_response_item(&self, call_id: &str, payload: &ToolPayload) -> ResponseInputItem {
        tool_output_response_item(call_id, payload, self, Some(true), "close_agent")
    }

    fn code_mode_result(&self, _payload: &ToolPayload) -> JsonValue {
        tool_output_code_mode_result(self, "close_agent")
    }
}

#[derive(Debug, Deserialize)]
struct CloseAgentArgs {
    target: String,
}
