use std::collections::HashMap;

use codex_app_server_protocol::CodexErrorInfo;
use codex_app_server_protocol::GuardianApprovalReviewStatus;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnStatus;
use serde::Deserialize;
use serde::Serialize;
use ts_rs::TS;

const OBSERVATION_SCHEMA_VERSION: u32 = 1;

/// Body-free, task-level measurements emitted only by the explicit
/// `codex exec --json --rondo-local-observation` mode.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct RondoLocalTaskObservation {
    pub schema_version: u32,
    pub scope: String,
    pub event_stream_complete: bool,
    pub turn: ObservationTurn,
    pub responses: ObservationResponses,
    pub errors: ObservationErrors,
    pub tools: ObservationTools,
    pub compactions: ObservationCompactions,
    pub guardian: ObservationGuardian,
    pub unavailable: ObservationUnavailable,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct ObservationTurn {
    pub status: String,
    pub duration_ms: Option<u64>,
    pub items_view: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct ObservationUsage {
    pub input_tokens: u64,
    pub cached_input_tokens: u64,
    pub cache_write_input_tokens: u64,
    pub output_tokens: u64,
    pub reasoning_output_tokens: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct ObservationResponses {
    pub completed: u64,
    pub with_valid_usage: u64,
    pub missing_usage: u64,
    pub invalid_usage: u64,
    pub usage: ObservationUsage,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct ObservationErrors {
    pub total: u64,
    pub retryable: u64,
    pub context_window_exceeded: u64,
    pub bad_request: u64,
    pub response_stream_failure: u64,
    pub response_retry_limit: u64,
    pub budget_or_usage_limit: u64,
    pub other: u64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct ObservationTools {
    pub command: u64,
    pub mcp: u64,
    pub dynamic: u64,
    pub with_valid_duration: u64,
    pub missing_or_invalid_duration: u64,
    pub total_duration_ms: u64,
    pub command_output_bytes: u64,
    pub max_command_output_bytes: u64,
    pub repeated_exact_commands: u64,
    pub repeated_after_failure: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct ObservationCompactions {
    pub completed: u64,
    pub coverage: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct ObservationGuardian {
    pub started: u64,
    pub completed: u64,
    pub with_valid_duration: u64,
    pub invalid_duration: u64,
    pub total_duration_ms: u64,
    pub approved: u64,
    pub denied: u64,
    pub timed_out: u64,
    pub aborted: u64,
    pub non_terminal: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, TS)]
pub struct ObservationUnavailable {
    pub turn_phase_profile: bool,
    pub model_visible_output_truncation: bool,
    pub compaction_reason_and_tokens: bool,
    pub direct_tool_dispatch_handler_split: bool,
    pub guardian_token_breakdown: bool,
}

pub(crate) struct RondoLocalObservationCollector {
    event_stream_complete: bool,
    turn: ObservationTurn,
    responses: ObservationResponses,
    errors: ObservationErrors,
    tools: ObservationTools,
    compactions: ObservationCompactions,
    guardian: ObservationGuardian,
}

impl Default for RondoLocalObservationCollector {
    fn default() -> Self {
        Self {
            event_stream_complete: true,
            turn: ObservationTurn {
                status: "unknown".to_string(),
                duration_ms: None,
                items_view: "unavailable".to_string(),
            },
            responses: ObservationResponses {
                completed: 0,
                with_valid_usage: 0,
                missing_usage: 0,
                invalid_usage: 0,
                usage: ObservationUsage::default(),
            },
            errors: ObservationErrors::default(),
            tools: ObservationTools::default(),
            compactions: ObservationCompactions {
                completed: 0,
                coverage: "unavailable".to_string(),
            },
            guardian: ObservationGuardian::default(),
        }
    }
}

impl RondoLocalObservationCollector {
    pub(crate) fn note_event_stream_lag(&mut self) {
        self.event_stream_complete = false;
    }

    pub(crate) fn observe(&mut self, notification: &ServerNotification) {
        match notification {
            ServerNotification::RawResponseCompleted(notification) => {
                self.responses.completed = self.responses.completed.saturating_add(1);
                let Some(usage) = &notification.usage else {
                    self.responses.missing_usage = self.responses.missing_usage.saturating_add(1);
                    return;
                };
                let values = [
                    usage.input_tokens,
                    usage.cached_input_tokens,
                    usage.cache_write_input_tokens,
                    usage.output_tokens,
                    usage.reasoning_output_tokens,
                ];
                if values.iter().any(|value| *value < 0) {
                    self.responses.invalid_usage = self.responses.invalid_usage.saturating_add(1);
                    return;
                }
                self.responses.with_valid_usage = self.responses.with_valid_usage.saturating_add(1);
                let usage_total = &mut self.responses.usage;
                usage_total.input_tokens = usage_total
                    .input_tokens
                    .saturating_add(usage.input_tokens as u64);
                usage_total.cached_input_tokens = usage_total
                    .cached_input_tokens
                    .saturating_add(usage.cached_input_tokens as u64);
                usage_total.cache_write_input_tokens = usage_total
                    .cache_write_input_tokens
                    .saturating_add(usage.cache_write_input_tokens as u64);
                usage_total.output_tokens = usage_total
                    .output_tokens
                    .saturating_add(usage.output_tokens as u64);
                usage_total.reasoning_output_tokens = usage_total
                    .reasoning_output_tokens
                    .saturating_add(usage.reasoning_output_tokens as u64);
            }
            ServerNotification::Error(notification) => {
                self.observe_error(notification.error.codex_error_info.as_ref());
                if notification.will_retry {
                    self.errors.retryable = self.errors.retryable.saturating_add(1);
                }
            }
            ServerNotification::ItemGuardianApprovalReviewStarted(_) => {
                self.guardian.started = self.guardian.started.saturating_add(1);
            }
            ServerNotification::ItemGuardianApprovalReviewCompleted(notification) => {
                self.guardian.completed = self.guardian.completed.saturating_add(1);
                match notification
                    .completed_at_ms
                    .checked_sub(notification.started_at_ms)
                {
                    Some(duration) if duration >= 0 => {
                        self.guardian.with_valid_duration =
                            self.guardian.with_valid_duration.saturating_add(1);
                        self.guardian.total_duration_ms = self
                            .guardian
                            .total_duration_ms
                            .saturating_add(duration as u64);
                    }
                    _ => {
                        self.guardian.invalid_duration =
                            self.guardian.invalid_duration.saturating_add(1);
                    }
                }
                match notification.review.status {
                    GuardianApprovalReviewStatus::Approved => {
                        self.guardian.approved = self.guardian.approved.saturating_add(1)
                    }
                    GuardianApprovalReviewStatus::Denied => {
                        self.guardian.denied = self.guardian.denied.saturating_add(1)
                    }
                    GuardianApprovalReviewStatus::TimedOut => {
                        self.guardian.timed_out = self.guardian.timed_out.saturating_add(1)
                    }
                    GuardianApprovalReviewStatus::Aborted => {
                        self.guardian.aborted = self.guardian.aborted.saturating_add(1)
                    }
                    GuardianApprovalReviewStatus::InProgress => {
                        self.guardian.non_terminal = self.guardian.non_terminal.saturating_add(1)
                    }
                }
            }
            ServerNotification::TurnCompleted(notification) => {
                self.observe_turn(&notification.turn)
            }
            _ => {}
        }
    }

    fn observe_error(&mut self, error: Option<&CodexErrorInfo>) {
        self.errors.total = self.errors.total.saturating_add(1);
        match error {
            Some(CodexErrorInfo::ContextWindowExceeded) => {
                self.errors.context_window_exceeded =
                    self.errors.context_window_exceeded.saturating_add(1)
            }
            Some(CodexErrorInfo::BadRequest) => {
                self.errors.bad_request = self.errors.bad_request.saturating_add(1)
            }
            Some(
                CodexErrorInfo::HttpConnectionFailed { .. }
                | CodexErrorInfo::ResponseStreamConnectionFailed { .. }
                | CodexErrorInfo::ResponseStreamDisconnected { .. },
            ) => {
                self.errors.response_stream_failure =
                    self.errors.response_stream_failure.saturating_add(1)
            }
            Some(CodexErrorInfo::ResponseTooManyFailedAttempts { .. }) => {
                self.errors.response_retry_limit =
                    self.errors.response_retry_limit.saturating_add(1)
            }
            Some(CodexErrorInfo::SessionBudgetExceeded | CodexErrorInfo::UsageLimitExceeded) => {
                self.errors.budget_or_usage_limit =
                    self.errors.budget_or_usage_limit.saturating_add(1)
            }
            _ => self.errors.other = self.errors.other.saturating_add(1),
        }
    }

    fn observe_turn(&mut self, turn: &codex_app_server_protocol::Turn) {
        self.turn.status = match turn.status {
            TurnStatus::Completed => "completed",
            TurnStatus::Failed => "failed",
            TurnStatus::Interrupted => "interrupted",
            TurnStatus::InProgress => "in_progress",
        }
        .to_string();
        self.turn.duration_ms = turn.duration_ms.and_then(|value| value.try_into().ok());
        self.turn.items_view = match turn.items_view {
            TurnItemsView::Full => "full",
            TurnItemsView::Summary => "summary",
            TurnItemsView::NotLoaded => "not_loaded",
        }
        .to_string();
        if turn.items_view != TurnItemsView::Full {
            return;
        }
        self.compactions.coverage = "measured".to_string();
        let mut commands: HashMap<&str, bool> = HashMap::new();
        for item in &turn.items {
            match item {
                ThreadItem::CommandExecution {
                    command,
                    status,
                    aggregated_output,
                    duration_ms,
                    ..
                } => {
                    self.tools.command = self.tools.command.saturating_add(1);
                    self.observe_tool_duration(*duration_ms);
                    let output_bytes = aggregated_output
                        .as_ref()
                        .map_or(0, |output| output.len() as u64);
                    self.tools.command_output_bytes =
                        self.tools.command_output_bytes.saturating_add(output_bytes);
                    self.tools.max_command_output_bytes =
                        self.tools.max_command_output_bytes.max(output_bytes);
                    let failed = matches!(
                        status,
                        codex_app_server_protocol::CommandExecutionStatus::Failed
                    );
                    if let Some(previous_failed) = commands.get_mut(command.as_str()) {
                        self.tools.repeated_exact_commands =
                            self.tools.repeated_exact_commands.saturating_add(1);
                        if *previous_failed {
                            self.tools.repeated_after_failure =
                                self.tools.repeated_after_failure.saturating_add(1);
                        }
                        *previous_failed |= failed;
                    } else {
                        commands.insert(command.as_str(), failed);
                    }
                }
                ThreadItem::McpToolCall { duration_ms, .. } => {
                    self.tools.mcp = self.tools.mcp.saturating_add(1);
                    self.observe_tool_duration(*duration_ms);
                }
                ThreadItem::DynamicToolCall { duration_ms, .. } => {
                    self.tools.dynamic = self.tools.dynamic.saturating_add(1);
                    self.observe_tool_duration(*duration_ms);
                }
                ThreadItem::ContextCompaction { .. } => {
                    self.compactions.completed = self.compactions.completed.saturating_add(1);
                }
                _ => {}
            }
        }
    }

    fn observe_tool_duration(&mut self, duration_ms: Option<i64>) {
        match duration_ms {
            Some(duration) if duration >= 0 => {
                self.tools.with_valid_duration = self.tools.with_valid_duration.saturating_add(1);
                self.tools.total_duration_ms =
                    self.tools.total_duration_ms.saturating_add(duration as u64);
            }
            _ => {
                self.tools.missing_or_invalid_duration =
                    self.tools.missing_or_invalid_duration.saturating_add(1);
            }
        }
    }

    pub(crate) fn snapshot(&self) -> RondoLocalTaskObservation {
        RondoLocalTaskObservation {
            schema_version: OBSERVATION_SCHEMA_VERSION,
            scope: "rondo_local_task".to_string(),
            event_stream_complete: self.event_stream_complete,
            turn: self.turn.clone(),
            responses: self.responses.clone(),
            errors: self.errors.clone(),
            tools: self.tools.clone(),
            compactions: self.compactions.clone(),
            guardian: self.guardian.clone(),
            unavailable: ObservationUnavailable {
                turn_phase_profile: true,
                model_visible_output_truncation: true,
                compaction_reason_and_tokens: true,
                direct_tool_dispatch_handler_split: true,
                guardian_token_breakdown: true,
            },
        }
    }
}

#[cfg(test)]
#[path = "rondo_local_observation_tests.rs"]
mod tests;
