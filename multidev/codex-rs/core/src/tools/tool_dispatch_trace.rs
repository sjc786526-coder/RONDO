//! Adapter between core tool dispatch objects and rollout-trace events.
//!
//! `codex-rollout-trace` owns the event schema and writer behavior. This module
//! keeps the core-specific mapping from registry invocations/results out of the
//! registry control flow.

use crate::function_tool::FunctionCallError;
use crate::tools::context::FunctionToolOutput;
use crate::tools::context::ToolCallSource;
use crate::tools::context::ToolInvocation;
use crate::tools::context::ToolOutput;
use crate::tools::context::ToolPayload;
use codex_rollout_trace::ExecutionStatus;
use codex_rollout_trace::ToolDispatchInvocation;
use codex_rollout_trace::ToolDispatchPayload;
use codex_rollout_trace::ToolDispatchRequester;
use codex_rollout_trace::ToolDispatchResult;
use codex_rollout_trace::ToolDispatchTraceContext;

/// Keeps registry early-return paths paired with trace end events.
pub(crate) struct ToolDispatchTrace {
    context: ToolDispatchTraceContext,
}

impl ToolDispatchTrace {
    pub(crate) fn start(invocation: &ToolInvocation, log_payload_override: Option<&str>) -> Self {
        let context = invocation
            .session
            .services
            .rollout_thread_trace
            .start_tool_dispatch_trace(|| {
                tool_dispatch_invocation(invocation, log_payload_override)
            });
        Self { context }
    }

    pub(crate) fn record_completed(
        &self,
        invocation: &ToolInvocation,
        call_id: &str,
        payload: &ToolPayload,
        result: &dyn ToolOutput,
        redact_bodies: bool,
    ) {
        if !self.context.is_enabled() {
            return;
        }

        let Some(result_payload) =
            tool_dispatch_result(invocation, call_id, payload, result, redact_bodies)
        else {
            return;
        };
        let status = if result.success_for_logging() {
            ExecutionStatus::Completed
        } else {
            ExecutionStatus::Failed
        };
        self.context.record_completed(status, result_payload);
    }

    pub(crate) fn record_failed(&self, error: &FunctionCallError) {
        self.context.record_failed(error);
    }
}

fn tool_dispatch_invocation(
    invocation: &ToolInvocation,
    log_payload_override: Option<&str>,
) -> Option<ToolDispatchInvocation> {
    let requester = match &invocation.source {
        ToolCallSource::Direct | ToolCallSource::DirectPlaintextMessage => {
            ToolDispatchRequester::Model {
                model_visible_call_id: invocation.call_id.clone(),
            }
        }
        ToolCallSource::CodeMode {
            cell_id,
            runtime_tool_call_id,
        } => ToolDispatchRequester::CodeCell {
            runtime_cell_id: cell_id.clone(),
            runtime_tool_call_id: runtime_tool_call_id.clone(),
        },
    };

    Some(ToolDispatchInvocation {
        thread_id: invocation.session.thread_id.to_string(),
        codex_turn_id: invocation.turn.sub_id.clone(),
        tool_call_id: invocation.call_id.clone(),
        tool_name: invocation.tool_name.name.clone(),
        tool_namespace: invocation
            .tool_name
            .namespace
            .as_ref()
            .filter(|_| !invocation.tool_name.is_default_namespace())
            .cloned(),
        requester,
        payload: tool_dispatch_payload(&invocation.payload, log_payload_override),
    })
}

fn tool_dispatch_result(
    invocation: &ToolInvocation,
    call_id: &str,
    payload: &ToolPayload,
    result: &dyn ToolOutput,
    redact_bodies: bool,
) -> Option<ToolDispatchResult> {
    if redact_bodies {
        let safe_response = result.post_tool_use_response(call_id, payload)?;
        return match invocation.source {
            ToolCallSource::Direct | ToolCallSource::DirectPlaintextMessage => {
                Some(ToolDispatchResult::DirectResponse {
                    response_item: FunctionToolOutput::from_text(
                        safe_response.to_string(),
                        Some(result.success_for_logging()),
                    )
                    .to_response_item(call_id, payload),
                })
            }
            ToolCallSource::CodeMode { .. } => Some(ToolDispatchResult::CodeModeResponse {
                value: safe_response,
            }),
        };
    }

    match invocation.source {
        ToolCallSource::Direct | ToolCallSource::DirectPlaintextMessage => {
            Some(ToolDispatchResult::DirectResponse {
                response_item: result.to_response_item(call_id, payload),
            })
        }
        ToolCallSource::CodeMode { .. } => Some(ToolDispatchResult::CodeModeResponse {
            value: result.code_mode_result(payload),
        }),
    }
}

fn tool_dispatch_payload(
    payload: &ToolPayload,
    log_payload_override: Option<&str>,
) -> ToolDispatchPayload {
    match payload {
        ToolPayload::Function { arguments } => ToolDispatchPayload::Function {
            arguments: log_payload_override.unwrap_or(arguments).to_string(),
        },
        ToolPayload::ToolSearch { arguments } => {
            let mut arguments = arguments.clone();
            if let Some(log_payload_override) = log_payload_override {
                arguments.query = log_payload_override.to_string();
            }
            ToolDispatchPayload::ToolSearch { arguments }
        }
        ToolPayload::Custom { input } => ToolDispatchPayload::Custom {
            input: log_payload_override.unwrap_or(input).to_string(),
        },
    }
}

#[cfg(test)]
#[path = "tool_dispatch_trace_tests.rs"]
mod tests;
