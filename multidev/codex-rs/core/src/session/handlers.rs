use crate::realtime_conversation::handle_audio as handle_realtime_conversation_audio;
use crate::realtime_conversation::handle_close as handle_realtime_conversation_close;
use crate::realtime_conversation::handle_speech as handle_realtime_conversation_speech;
use crate::realtime_conversation::handle_start as handle_realtime_conversation_start;
use crate::realtime_conversation::handle_text as handle_realtime_conversation_text;
use async_channel::Receiver;
use codex_otel::set_parent_from_w3c_trace_context;
use codex_protocol::protocol::Submission;
use tracing::Instrument;
use tracing::debug_span;
use tracing::info_span;

use crate::session::SteerInputError;
use crate::session::TurnInput;
use crate::session::session::PreparedDurableSessionShutdownCompletion;
use crate::session::session::Session;
use crate::session::session::SessionSettingsUpdate;

use crate::config::Config;
use crate::review_prompts::resolve_review_request;
use crate::session::spawn_review_thread;
use crate::tasks::CompactTask;
use crate::tasks::UserShellCommandMode;
use crate::tasks::UserShellCommandTask;
use crate::tasks::execute_user_shell_command;
use crate::user_message_admission::UserMessageAdmission;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::models::ContentItem;
use codex_protocol::models::ResponseInputItem;
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::CodexErrorInfo;
use codex_protocol::protocol::ErrorEvent;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::GuardianAssessmentEvent;
use codex_protocol::protocol::GuardianAssessmentStatus;
use codex_protocol::protocol::InterAgentCommunication;
use codex_protocol::protocol::Op;
use codex_protocol::protocol::RealtimeConversationListVoicesResponseEvent;
use codex_protocol::protocol::RealtimeVoicesList;
use codex_protocol::protocol::ReviewDecision;
use codex_protocol::protocol::ReviewRequest;
use codex_protocol::protocol::RolloutItem;
use codex_protocol::protocol::ThreadMemoryMode;
use codex_protocol::protocol::ThreadRolledBackEvent;
use codex_protocol::protocol::ThreadSettingsAppliedEvent;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::protocol::TurnAbortReason;
use codex_protocol::protocol::WarningEvent;
use codex_protocol::request_permissions::RequestPermissionsResponse;
use codex_protocol::request_user_input::RequestUserInputResponse;

use crate::context_manager::is_user_turn_boundary;
use codex_protocol::dynamic_tools::DynamicToolResponse;
use codex_protocol::mcp::RequestId as ProtocolRequestId;
use codex_rmcp_client::ElicitationAction;
use codex_rmcp_client::ElicitationResponse;
use serde_json::Value;
use std::sync::Arc;
use tracing::debug;
use tracing::info;
use tracing::warn;

pub async fn interrupt(sess: &Arc<Session>) {
    sess.interrupt_task().await;
}

pub async fn clean_background_terminals(sess: &Arc<Session>) {
    sess.close_unified_exec_processes().await;
}

pub async fn realtime_conversation_list_voices(sess: &Session, sub_id: String) {
    sess.send_event_raw(Event {
        id: sub_id,
        msg: EventMsg::RealtimeConversationListVoicesResponse(
            RealtimeConversationListVoicesResponseEvent {
                voices: RealtimeVoicesList::builtin(),
            },
        ),
    })
    .await;
}

pub async fn user_input_or_turn(
    sess: &Arc<Session>,
    sub_id: String,
    op: Op,
    client_user_message_id: Option<String>,
    parent_turn_id: Option<String>,
) {
    let admission = user_input_or_turn_inner(
        sess,
        sub_id.clone(),
        op,
        client_user_message_id,
        parent_turn_id,
    )
    .await;
    sess.pending_user_message_admissions
        .complete(&sub_id, admission);
}

pub async fn update_thread_settings(
    sess: &Arc<Session>,
    sub_id: String,
    thread_settings: ThreadSettingsOverrides,
) {
    let updates = thread_settings_update(sess, thread_settings).await;
    match sess.update_settings(updates).await {
        Ok(()) => {
            sess.send_event_raw_without_materializing_rollout(Event {
                id: sub_id,
                msg: thread_settings_applied_event(sess).await,
            })
            .await;
        }
        Err(err) => {
            sess.send_event_raw(Event {
                id: sub_id,
                msg: EventMsg::Error(ErrorEvent {
                    message: format!("invalid thread settings override: {err}"),
                    codex_error_info: Some(CodexErrorInfo::BadRequest),
                }),
            })
            .await;
        }
    }
}

async fn thread_settings_update(
    sess: &Session,
    thread_settings: ThreadSettingsOverrides,
) -> SessionSettingsUpdate {
    let ThreadSettingsOverrides {
        environments,
        profile_workspace_roots,
        approval_policy,
        approvals_reviewer,
        sandbox_policy,
        permission_profile,
        active_permission_profile,
        windows_sandbox_level,
        model,
        effort,
        summary,
        service_tier,
        collaboration_mode,
        personality,
    } = thread_settings;
    let collaboration_mode = match collaboration_mode {
        Some(collaboration_mode) => collaboration_mode,
        None => {
            let state = sess.state.lock().await;
            // Model and reasoning effort live in CollaborationMode settings today, so
            // partial thread-settings updates refresh those fields on the active mode.
            state
                .session_configuration
                .collaboration_mode
                .with_updates(model, effort, /*developer_instructions*/ None)
        }
    };
    SessionSettingsUpdate {
        environments,
        profile_workspace_roots,
        approval_policy,
        approvals_reviewer,
        sandbox_policy,
        permission_profile,
        active_permission_profile,
        windows_sandbox_level,
        collaboration_mode: Some(collaboration_mode),
        reasoning_summary: summary,
        service_tier,
        personality,
        ..Default::default()
    }
}

pub(super) async fn thread_settings_applied_event(sess: &Session) -> EventMsg {
    let snapshot = {
        let state = sess.state.lock().await;
        state.session_configuration.thread_config_snapshot()
    };
    EventMsg::ThreadSettingsApplied(ThreadSettingsAppliedEvent {
        thread_settings: snapshot.into_thread_settings_snapshot(),
    })
}

pub(super) async fn user_input_or_turn_inner(
    sess: &Arc<Session>,
    sub_id: String,
    op: Op,
    client_user_message_id: Option<String>,
    parent_turn_id: Option<String>,
) -> CodexResult<UserMessageAdmission> {
    let Op::UserInput {
        items,
        final_output_json_schema,
        responsesapi_client_metadata,
        additional_context,
        thread_settings,
    } = op
    else {
        unreachable!();
    };
    let emit_thread_settings_applied = thread_settings != ThreadSettingsOverrides::default();
    let mut updates = if emit_thread_settings_applied {
        thread_settings_update(sess, thread_settings).await
    } else {
        SessionSettingsUpdate::default()
    };
    updates.final_output_json_schema = Some(final_output_json_schema);

    // new_turn_with_sub_id already emits an error event when settings are invalid.
    let current_context = sess.new_turn_with_sub_id(sub_id.clone(), updates).await?;
    if emit_thread_settings_applied {
        sess.send_event_raw_without_materializing_rollout(Event {
            id: sub_id.clone(),
            msg: thread_settings_applied_event(sess).await,
        })
        .await;
    }
    sess.maybe_emit_model_warnings_for_turn(current_context.as_ref())
        .await;
    match sess
        .steer_input(
            items.clone(),
            additional_context.clone(),
            /*expected_turn_id*/ None,
            client_user_message_id.clone(),
            responsesapi_client_metadata.clone(),
        )
        .await
    {
        Ok(turn_id) => {
            current_context.session_telemetry.user_prompt(&items);
            Ok(UserMessageAdmission::Steered { turn_id })
        }
        Err(SteerInputError::NoActiveTurn(items)) => {
            if let Some(id) = parent_turn_id {
                current_context.turn_metadata_state.set_parent_turn_id(id);
            }
            if let Some(responsesapi_client_metadata) = responsesapi_client_metadata {
                current_context
                    .turn_metadata_state
                    .set_responsesapi_client_metadata(responsesapi_client_metadata);
            }
            current_context.session_telemetry.user_prompt(&items);
            let additional_context_input = {
                let mut state = sess.state.lock().await;
                state.additional_context.merge(additional_context)
            };
            let mut task_input = additional_context_input
                .into_iter()
                .map(ResponseItem::from)
                .map(TurnInput::ResponseItem)
                .collect::<Vec<_>>();
            if !items.is_empty() {
                task_input.push(TurnInput::UserInput {
                    content: items,
                    client_id: client_user_message_id,
                });
            }
            sess.spawn_task_checked(
                Arc::clone(&current_context),
                task_input,
                crate::tasks::RegularTask::new(),
            )
            .await?;
            Ok(UserMessageAdmission::Started { turn_id: sub_id })
        }
        Err(err) => {
            sess.send_event_raw(Event {
                id: sub_id.clone(),
                msg: EventMsg::Error(err.to_error_event()),
            })
            .await;
            Err(CodexErr::InvalidRequest(format!(
                "failed to admit user message: {err:?}"
            )))
        }
    }
}

/// Queues an inter-agent message, then lets the shared pending-work scheduler
/// decide whether an idle session should start a regular turn.
pub async fn inter_agent_communication(
    sess: &Arc<Session>,
    sub_id: String,
    communication: InterAgentCommunication,
    parent_turn_id: Option<String>,
) {
    let trigger_turn = communication.trigger_turn;
    sess.input_queue
        .enqueue_mailbox_communication(communication, parent_turn_id.filter(|_| trigger_turn))
        .await;
    crate::agent_communication::emit_agent_communication_receive(&sub_id);
    if trigger_turn || sess.has_outstanding_durable_sleep() {
        sess.maybe_start_turn_for_pending_work_with_sub_id(sub_id)
            .await;
    }
}

pub async fn run_user_shell_command(sess: &Arc<Session>, sub_id: String, command: String) {
    if let Some((turn_context, cancellation_token)) =
        sess.active_turn_context_and_cancellation_token().await
    {
        let session = Arc::clone(sess);
        tokio::spawn(async move {
            execute_user_shell_command(
                session,
                turn_context,
                command,
                cancellation_token,
                UserShellCommandMode::ActiveTurnAuxiliary,
            )
            .await;
        });
        return;
    }

    let turn_context = sess.new_default_turn_with_sub_id(sub_id).await;
    sess.spawn_task(
        Arc::clone(&turn_context),
        Vec::new(),
        UserShellCommandTask::new(command),
    )
    .await;
}

pub async fn resolve_elicitation(
    sess: &Arc<Session>,
    server_name: String,
    request_id: ProtocolRequestId,
    decision: codex_protocol::approvals::ElicitationAction,
    content: Option<Value>,
    meta: Option<Value>,
) {
    let action = match decision {
        codex_protocol::approvals::ElicitationAction::Accept => ElicitationAction::Accept,
        codex_protocol::approvals::ElicitationAction::Decline => ElicitationAction::Decline,
        codex_protocol::approvals::ElicitationAction::Cancel => ElicitationAction::Cancel,
    };
    let content = match action {
        // Preserve the legacy fallback for clients that only send an action.
        ElicitationAction::Accept => Some(content.unwrap_or_else(|| serde_json::json!({}))),
        ElicitationAction::Decline | ElicitationAction::Cancel => None,
        _ => None,
    };
    let response = ElicitationResponse {
        action,
        content,
        meta,
    };
    let request_id = match request_id {
        ProtocolRequestId::String(value) => {
            rmcp::model::NumberOrString::String(std::sync::Arc::from(value))
        }
        ProtocolRequestId::Integer(value) => rmcp::model::NumberOrString::Number(value),
    };
    if let Err(err) = sess
        .resolve_elicitation(server_name, request_id, response)
        .await
    {
        warn!(
            error = %err,
            "failed to resolve elicitation request in session"
        );
    }
}

/// Propagate a user's exec approval decision to the session.
/// Also optionally applies an execpolicy amendment.
pub async fn exec_approval(
    sess: &Arc<Session>,
    approval_id: String,
    turn_id: Option<String>,
    decision: ReviewDecision,
) {
    let event_turn_id = turn_id.unwrap_or_else(|| approval_id.clone());
    if let ReviewDecision::ApprovedExecpolicyAmendment {
        proposed_execpolicy_amendment,
    } = &decision
        && let Err(err) = sess
            .persist_execpolicy_amendment(proposed_execpolicy_amendment)
            .await
    {
        let message = format!("Failed to apply execpolicy amendment: {err}");
        tracing::warn!("{message}");
        let warning = EventMsg::Warning(WarningEvent { message });
        sess.send_event_raw(Event {
            id: event_turn_id.clone(),
            msg: warning,
        })
        .await;
    }
    match decision {
        ReviewDecision::Abort => {
            sess.interrupt_task().await;
        }
        other => sess.notify_approval(&approval_id, other).await,
    }
}

pub async fn patch_approval(sess: &Arc<Session>, id: String, decision: ReviewDecision) {
    match decision {
        ReviewDecision::Abort => {
            sess.interrupt_task().await;
        }
        other => sess.notify_approval(&id, other).await,
    }
}

pub async fn request_user_input_response(
    sess: &Arc<Session>,
    id: String,
    response: RequestUserInputResponse,
) {
    sess.notify_user_input_response(&id, response).await;
}

pub async fn request_permissions_response(
    sess: &Arc<Session>,
    id: String,
    response: RequestPermissionsResponse,
) {
    sess.notify_request_permissions_response(&id, response)
        .await;
}

pub async fn dynamic_tool_response(sess: &Arc<Session>, id: String, response: DynamicToolResponse) {
    sess.notify_dynamic_tool_response(&id, response).await;
}

pub fn refresh_mcp_servers(sess: &Session) {
    sess.services.mcp_runtime.reconnect_on_next_refresh();
    sess.request_mcp_runtime_refresh();
}

pub async fn reload_user_config(sess: &Arc<Session>) {
    sess.reload_user_config_layer().await;
}

pub async fn compact(sess: &Arc<Session>, sub_id: String) {
    let turn_context = sess.new_default_turn_with_sub_id(sub_id).await;

    sess.spawn_task(Arc::clone(&turn_context), Vec::new(), CompactTask)
        .await;
}

pub async fn thread_rollback(sess: &Arc<Session>, sub_id: String, num_turns: u32) {
    if num_turns == 0 {
        sess.send_event_raw(Event {
            id: sub_id,
            msg: EventMsg::Error(ErrorEvent {
                message: "num_turns must be >= 1".to_string(),
                codex_error_info: Some(CodexErrorInfo::ThreadRollbackFailed),
            }),
        })
        .await;
        return;
    }

    let has_active_turn = { sess.active_turn.lock().await.is_some() };
    if has_active_turn {
        sess.send_event_raw(Event {
            id: sub_id,
            msg: EventMsg::Error(ErrorEvent {
                message: "Cannot rollback while a turn is in progress.".to_string(),
                codex_error_info: Some(CodexErrorInfo::ThreadRollbackFailed),
            }),
        })
        .await;
        return;
    }

    let turn_context = sess.new_default_turn_with_sub_id(sub_id).await;
    let live_thread = match sess.live_thread_for_persistence("rollback thread") {
        Ok(live_thread) => live_thread,
        Err(_) => {
            sess.send_event_raw(Event {
                id: turn_context.sub_id.clone(),
                msg: EventMsg::Error(ErrorEvent {
                    message: "thread rollback requires persisted thread history".to_string(),
                    codex_error_info: Some(CodexErrorInfo::ThreadRollbackFailed),
                }),
            })
            .await;
            return;
        }
    };
    if let Err(err) = live_thread.flush().await {
        sess.send_event_raw(Event {
            id: turn_context.sub_id.clone(),
            msg: EventMsg::Error(ErrorEvent {
                message: format!("failed to flush thread persistence for rollback replay: {err}"),
                codex_error_info: Some(CodexErrorInfo::ThreadRollbackFailed),
            }),
        })
        .await;
        return;
    }

    let stored_history = match live_thread.load_history(/*include_archived*/ false).await {
        Ok(history) => history,
        Err(err) => {
            sess.send_event_raw(Event {
                id: turn_context.sub_id.clone(),
                msg: EventMsg::Error(ErrorEvent {
                    message: format!("failed to load thread history for rollback replay: {err}"),
                    codex_error_info: Some(CodexErrorInfo::ThreadRollbackFailed),
                }),
            })
            .await;
            return;
        }
    };

    let rollback_event = ThreadRolledBackEvent { num_turns };
    let rollback_msg = EventMsg::ThreadRolledBack(rollback_event.clone());
    let replay_items = stored_history
        .items
        .into_iter()
        .chain(std::iter::once(RolloutItem::EventMsg(rollback_msg.clone())))
        .collect::<Vec<_>>();
    sess.apply_rollout_reconstruction(turn_context.as_ref(), replay_items.as_slice())
        .await;
    sess.services
        .agent_control
        .rollout_budget()
        .rearm_reminder(sess.thread_id());
    sess.recompute_token_usage(turn_context.as_ref()).await;

    sess.persist_rollout_items(&[RolloutItem::EventMsg(rollback_msg.clone())])
        .await;
    if let Err(err) = sess.flush_rollout().await {
        sess.send_event(
            turn_context.as_ref(),
            EventMsg::Warning(WarningEvent {
                message: format!(
                    "Rolled the thread back, but failed to save the rollback marker. Codex will continue retrying. Error: {err}"
                ),
            }),
        )
        .await;
    }

    sess.deliver_event_raw(Event {
        id: turn_context.sub_id.clone(),
        msg: rollback_msg,
    })
    .await;
}

pub(super) async fn persist_thread_memory_mode_update(
    sess: &Arc<Session>,
    mode: ThreadMemoryMode,
) -> anyhow::Result<()> {
    let live_thread = sess.live_thread_for_persistence("update thread memory mode")?;
    live_thread.persist().await?;
    live_thread.flush().await?;
    live_thread
        .update_memory_mode(mode, /*include_archived*/ false)
        .await?;
    live_thread.flush().await?;
    Ok(())
}

/// Persists thread-level memory mode metadata for the active session.
///
/// This does not involve the model and only affects whether the thread is
/// eligible for future memory generation.
pub async fn set_thread_memory_mode(sess: &Arc<Session>, sub_id: String, mode: ThreadMemoryMode) {
    if let Err(err) = persist_thread_memory_mode_update(sess, mode).await {
        warn!("Failed to persist thread memory mode update to rollout: {err}");
        let event = Event {
            id: sub_id,
            msg: EventMsg::Error(ErrorEvent {
                message: err.to_string(),
                codex_error_info: Some(CodexErrorInfo::Other),
            }),
        };
        sess.send_event_raw(event).await;
    }
}

#[derive(Clone, Copy)]
enum RuntimeShutdownMode {
    Standard,
    BoundWriterAlreadyQuiesced,
}

async fn quiesce_bound_writer_before_durable_persistence(
    sess: &Arc<Session>,
) -> Result<RuntimeShutdownMode, String> {
    if sess.writer_workspace_binding_snapshot().await.is_none() {
        return Ok(RuntimeShutdownMode::Standard);
    }
    sess.services
        .unified_exec_manager
        .terminate_all_processes_confirmed()
        .await
        .map_err(|err| format!("failed to revoke bound writer processes: {err}"))?;
    sess.abort_all_tasks(TurnAbortReason::Interrupted).await;
    // A tool may have crossed its final authority check before the first snapshot and inserted a
    // process while its task was being cancelled. Close that window before persistence becomes
    // irreversible.
    sess.services
        .unified_exec_manager
        .terminate_all_processes_confirmed()
        .await
        .map_err(|err| format!("failed to revoke late bound writer processes: {err}"))?;
    Ok(RuntimeShutdownMode::BoundWriterAlreadyQuiesced)
}

async fn shutdown_session_runtime(
    sess: &Arc<Session>,
    mode: RuntimeShutdownMode,
) -> Result<(), String> {
    if let Some(startup_prewarm) = sess.take_session_startup_prewarm().await {
        startup_prewarm.abort().await;
    }
    let _ = sess.conversation.shutdown().await;
    if matches!(mode, RuntimeShutdownMode::Standard) {
        sess.abort_all_tasks(TurnAbortReason::Interrupted).await;
        if sess.writer_workspace_binding_snapshot().await.is_some() {
            sess.services
                .unified_exec_manager
                .terminate_all_processes_confirmed()
                .await
                .map_err(|err| format!("failed to revoke bound writer processes: {err}"))?;
        } else {
            sess.services
                .unified_exec_manager
                .terminate_all_processes()
                .await;
        }
    }
    if let Err(err) = sess.services.code_mode_service.shutdown().await {
        warn!("failed to shutdown code mode session: {err}");
    }
    sess.stop_mcp_prewarm_worker().await;
    {
        let _refresh = sess.mcp_refresh.acquire().await;
        sess.mcp_refresh.close();
        sess.services.mcp_runtime.shutdown().await;
    }
    sess.guardian_review_session.shutdown().await;

    crate::hook_runtime::run_session_end_hooks(sess).await;
    Ok(())
}

async fn emit_thread_stop_lifecycle(sess: &Session) {
    for contributor in sess.services.extensions.thread_lifecycle_contributors() {
        contributor
            .on_thread_stop(codex_extension_api::ThreadStopInput {
                session_store: &sess.services.session_extension_data,
                thread_store: &sess.services.thread_extension_data,
            })
            .await;
    }
}

pub async fn shutdown(sess: &Arc<Session>, sub_id: String) -> bool {
    let team = sess.services.agent_control.team();
    let durable_root = team
        .durable_identity()
        .is_some_and(|identity| identity.root_thread_id() == sess.thread_id());
    let mut durable_lifecycle_close = None;
    let mut durable_team_close = None;
    let mut formal_shutdown_completion = None;
    if durable_root {
        if let Some(claimed) = sess.take_prepared_durable_session_shutdown(&sub_id) {
            durable_lifecycle_close = Some(claimed.prepared.lifecycle_close);
            durable_team_close = Some(claimed.prepared.team_close);
            formal_shutdown_completion = Some(claimed.completion);
        } else {
            if let Err(error) = sess.ensure_durable_root_activation().await {
                send_durable_close_error(sess, &sub_id, error.to_string()).await;
                sess.finish_failed_experimental_session_control_shutdown();
                return false;
            }
            let lifecycle_close = match sess
                .services
                .agent_control
                .begin_durable_team_root_close(sess.thread_id())
            {
                Ok(close) => close,
                Err(error) => {
                    send_durable_close_error(sess, &sub_id, error.to_string()).await;
                    sess.finish_failed_experimental_session_control_shutdown();
                    return false;
                }
            };
            if let Err(error) = lifecycle_close.ensure_no_live_descendants().await {
                send_durable_close_error(sess, &sub_id, error.to_string()).await;
                sess.finish_failed_experimental_session_control_shutdown();
                return false;
            }
            let team_close = match team.begin_close().await {
                Ok(close) => close,
                Err(error) => {
                    send_durable_close_error(sess, &sub_id, error.to_string()).await;
                    sess.finish_failed_experimental_session_control_shutdown();
                    return false;
                }
            };
            durable_lifecycle_close = Some(lifecycle_close);
            durable_team_close = Some(team_close);
        }
    }

    let runtime_shutdown_mode = if durable_root {
        match quiesce_bound_writer_before_durable_persistence(sess).await {
            Ok(mode) => mode,
            Err(error) => {
                if let Some(team_close) = durable_team_close.take()
                    && let Err(abort_error) = team_close.abort().await
                {
                    warn!(
                        "failed to abort durable Team close after writer quiescence failure: {abort_error}"
                    );
                }
                if let Some(lifecycle_close) = durable_lifecycle_close.take() {
                    lifecycle_close.abort();
                }
                send_durable_close_error(sess, &sub_id, error.clone()).await;
                if let Some(completion) = formal_shutdown_completion.take() {
                    let _ = completion.send(
                        PreparedDurableSessionShutdownCompletion::RetainedError(error),
                    );
                }
                sess.finish_failed_experimental_session_control_shutdown();
                return false;
            }
        }
    } else {
        RuntimeShutdownMode::Standard
    };

    // A durable Root must retain its fully usable runtime when persistence cannot cross the close
    // boundary. Close its canonical writer first while the Team/lifecycle permits block new
    // mutation; only a successful persistence shutdown commits us to runtime teardown.
    if durable_root
        && let Some(live_thread) = sess.live_thread()
        && let Err(e) = live_thread.shutdown().await
    {
        warn!("failed to shutdown thread persistence: {e}");
        if let Some(team_close) = durable_team_close.take()
            && let Err(abort_error) = team_close.abort().await
        {
            warn!("failed to abort durable Team close after persistence failure: {abort_error}");
        }
        if let Some(lifecycle_close) = durable_lifecycle_close.take() {
            lifecycle_close.abort();
        }
        send_durable_close_error(
            sess,
            &sub_id,
            "Failed to shutdown thread persistence".to_string(),
        )
        .await;
        if let Some(completion) = formal_shutdown_completion.take() {
            let _ = completion.send(PreparedDurableSessionShutdownCompletion::RetainedError(
                "Failed to shutdown thread persistence".to_string(),
            ));
        }
        sess.finish_failed_experimental_session_control_shutdown();
        return false;
    }

    if let Err(error) = shutdown_session_runtime(sess, runtime_shutdown_mode).await {
        if let Some(team_close) = durable_team_close.take()
            && let Err(abort_error) = team_close.abort().await
        {
            warn!("failed to abort durable Team close after runtime failure: {abort_error}");
        }
        if let Some(lifecycle_close) = durable_lifecycle_close.take() {
            lifecycle_close.abort();
        }
        send_durable_close_error(sess, &sub_id, error.clone()).await;
        if let Some(completion) = formal_shutdown_completion.take() {
            let _ = completion.send(PreparedDurableSessionShutdownCompletion::RetainedError(
                error,
            ));
        }
        sess.finish_failed_experimental_session_control_shutdown();
        return false;
    }
    info!("Shutting down Codex instance");
    let history = sess.clone_history().await;
    let turn_count = history
        .raw_items()
        .iter()
        .filter(|item| is_user_turn_boundary(item))
        .count();
    sess.services.session_telemetry.counter(
        "codex.conversation.turn.count",
        i64::try_from(turn_count).unwrap_or(0),
        &[],
    );

    emit_thread_stop_lifecycle(sess.as_ref()).await;

    // Gracefully flush and shutdown thread persistence on session end so tests
    // that inspect durable state do not race with the background writer.
    if !durable_root
        && let Some(live_thread) = sess.live_thread()
        && let Err(e) = live_thread.shutdown().await
    {
        warn!("failed to shutdown thread persistence: {e}");
    }

    if let Some(team_close) = durable_team_close.take()
        && let Err(error) = team_close.complete().await
    {
        let message = error.to_string();
        // Persistence and runtime teardown have already crossed the rollback boundary. Keeping the
        // submission loop alive here would expose a mapped but unusable Root. Close admission,
        // terminate the loop, and let app-server retire only this exact owner mapping.
        if let Some(lifecycle_close) = durable_lifecycle_close.take() {
            lifecycle_close.complete();
        }
        send_durable_close_error(sess, &sub_id, message.clone()).await;
        sess.services
            .rollout_thread_trace
            .record_ended(codex_rollout_trace::RolloutStatus::Failed);
        if let Some(completion) = formal_shutdown_completion.take() {
            let _ = completion.send(PreparedDurableSessionShutdownCompletion::TerminatedError(
                message,
            ));
        }
        return true;
    }
    if let Some(lifecycle_close) = durable_lifecycle_close.take() {
        lifecycle_close.complete();
    }

    let event = Event {
        id: sub_id,
        msg: EventMsg::ShutdownComplete,
    };
    sess.services
        .rollout_thread_trace
        .record_protocol_event(&event.msg);
    sess.deliver_event_raw(event).await;
    sess.services
        .rollout_thread_trace
        .record_ended(codex_rollout_trace::RolloutStatus::Completed);
    if let Some(completion) = formal_shutdown_completion.take() {
        let _ = completion.send(PreparedDurableSessionShutdownCompletion::Completed);
    }
    true
}

async fn send_durable_close_error(sess: &Session, sub_id: &str, message: String) {
    let event = Event {
        id: sub_id.to_string(),
        msg: EventMsg::Error(ErrorEvent {
            message,
            codex_error_info: Some(CodexErrorInfo::Other),
        }),
    };
    sess.send_event_raw(event).await;
}

pub async fn review(
    sess: &Arc<Session>,
    config: &Arc<Config>,
    sub_id: String,
    review_request: ReviewRequest,
) {
    let turn_context = sess.new_default_turn_with_sub_id(sub_id.clone()).await;
    sess.maybe_emit_model_warnings_for_turn(turn_context.as_ref())
        .await;
    #[allow(deprecated)]
    match resolve_review_request(review_request, &turn_context.cwd) {
        Ok(resolved) => {
            spawn_review_thread(
                Arc::clone(sess),
                Arc::clone(config),
                turn_context.clone(),
                sub_id,
                resolved,
            )
            .await;
        }
        Err(err) => {
            let event = Event {
                id: sub_id,
                msg: EventMsg::Error(ErrorEvent {
                    message: err.to_string(),
                    codex_error_info: Some(CodexErrorInfo::Other),
                }),
            };
            sess.send_event(&turn_context, event.msg).await;
        }
    }
}

pub(super) async fn submission_loop(
    sess: Arc<Session>,
    config: Arc<Config>,
    rx_sub: Receiver<Submission>,
) {
    // To break out of this loop, send Op::Shutdown.
    let mut shutdown_received = false;
    while let Ok(sub) = rx_sub.recv().await {
        debug!(?sub, "Submission");
        let dispatch_span = submission_dispatch_span(&sub);
        let should_exit = async {
            match sub.op.clone() {
                Op::Interrupt => {
                    interrupt(&sess).await;
                    false
                }
                Op::CleanBackgroundTerminals => {
                    clean_background_terminals(&sess).await;
                    false
                }
                Op::RealtimeConversationStart(params) => {
                    if let Err(err) =
                        handle_realtime_conversation_start(&sess, sub.id.clone(), params).await
                    {
                        sess.send_event_raw(Event {
                            id: sub.id.clone(),
                            msg: EventMsg::Error(ErrorEvent {
                                message: err.to_string(),
                                codex_error_info: Some(CodexErrorInfo::Other),
                            }),
                        })
                        .await;
                    }
                    false
                }
                Op::RealtimeConversationAudio(params) => {
                    handle_realtime_conversation_audio(&sess, sub.id.clone(), params).await;
                    false
                }
                Op::RealtimeConversationText(params) => {
                    handle_realtime_conversation_text(&sess, sub.id.clone(), params).await;
                    false
                }
                Op::RealtimeConversationSpeech(params) => {
                    handle_realtime_conversation_speech(&sess, sub.id.clone(), params).await;
                    false
                }
                Op::RealtimeConversationClose => {
                    handle_realtime_conversation_close(&sess, sub.id.clone()).await;
                    false
                }
                Op::RealtimeConversationListVoices => {
                    realtime_conversation_list_voices(&sess, sub.id.clone()).await;
                    false
                }
                Op::UserInput { .. } => {
                    user_input_or_turn(
                        &sess,
                        sub.id.clone(),
                        sub.op,
                        sub.client_user_message_id,
                        sub.parent_turn_id,
                    )
                    .await;
                    false
                }
                Op::ThreadSettings { thread_settings } => {
                    update_thread_settings(&sess, sub.id.clone(), thread_settings).await;
                    false
                }
                Op::InterAgentCommunication { communication } => {
                    inter_agent_communication(
                        &sess,
                        sub.id.clone(),
                        communication,
                        sub.parent_turn_id,
                    )
                    .await;
                    false
                }
                Op::ExecApproval {
                    id: approval_id,
                    turn_id,
                    decision,
                } => {
                    exec_approval(&sess, approval_id, turn_id, decision).await;
                    false
                }
                Op::PatchApproval { id, decision } => {
                    patch_approval(&sess, id, decision).await;
                    false
                }
                Op::UserInputAnswer { id, response } => {
                    request_user_input_response(&sess, id, response).await;
                    false
                }
                Op::RequestPermissionsResponse { id, response } => {
                    request_permissions_response(&sess, id, response).await;
                    false
                }
                Op::DynamicToolResponse { id, response } => {
                    dynamic_tool_response(&sess, id, response).await;
                    false
                }
                Op::RefreshMcpServers => {
                    refresh_mcp_servers(&sess);
                    false
                }
                Op::ReloadUserConfig => {
                    reload_user_config(&sess).await;
                    false
                }
                Op::Compact => {
                    compact(&sess, sub.id.clone()).await;
                    false
                }
                Op::ThreadRollback { num_turns } => {
                    thread_rollback(&sess, sub.id.clone(), num_turns).await;
                    false
                }
                Op::SetThreadMemoryMode { mode } => {
                    set_thread_memory_mode(&sess, sub.id.clone(), mode).await;
                    false
                }
                Op::RunUserShellCommand { command } => {
                    run_user_shell_command(&sess, sub.id.clone(), command).await;
                    false
                }
                Op::ResolveElicitation {
                    server_name,
                    request_id,
                    decision,
                    content,
                    meta,
                } => {
                    resolve_elicitation(&sess, server_name, request_id, decision, content, meta)
                        .await;
                    false
                }
                Op::Shutdown => shutdown(&sess, sub.id.clone()).await,
                Op::Review { review_request } => {
                    review(&sess, &config, sub.id.clone(), review_request).await;
                    false
                }
                Op::ApproveGuardianDeniedAction { event } => {
                    approve_guardian_denied_action(&sess, event).await;
                    false
                }
                _ => false, // Ignore unknown ops; enum is non_exhaustive to allow extensions.
            }
        }
        .instrument(dispatch_span)
        .await;
        if should_exit {
            shutdown_received = true;
            break;
        }
    }
    // If the submission loop exits because the channel closed without an
    // explicit shutdown op, still run session teardown.
    if !shutdown_received {
        if let Err(error) = shutdown_session_runtime(&sess, RuntimeShutdownMode::Standard).await {
            warn!("submission channel closed with incomplete runtime cleanup: {error}");
        }
        emit_thread_stop_lifecycle(sess.as_ref()).await;
        let durable_root = sess
            .services
            .agent_control
            .team()
            .durable_identity()
            .is_some_and(|identity| identity.root_thread_id() == sess.thread_id());
        if durable_root {
            // Losing the submission task is not a successful durable close. Keep the live Root
            // writer registered so another process cannot take authority while this process still
            // owns an unresolved Team lifecycle.
            warn!(
                "submission channel closed without a durable Team close; retaining Root writer authority"
            );
        } else if let Some(live_thread) = sess.live_thread()
            && let Err(err) = live_thread.shutdown().await
        {
            warn!("failed to shutdown thread persistence after submission channel closed: {err}");
        }
    }
    debug!("Agent loop exited");
}

async fn approve_guardian_denied_action(sess: &Arc<Session>, event: GuardianAssessmentEvent) {
    if event.status != GuardianAssessmentStatus::Denied {
        warn!(
            review_id = event.id.as_str(),
            "ignoring approval for non-denied Guardian assessment"
        );
        return;
    }

    let approved_action = serde_json::json!({
        "action": &event.action,
        "outcome": "allowed",
    });
    let approved_action_json = match serde_json::to_string_pretty(&approved_action) {
        Ok(approved_action_json) => approved_action_json,
        Err(error) => {
            warn!(%error, review_id = event.id.as_str(), "failed to serialize approved Guardian action");
            return;
        }
    };
    let approval_prefix = crate::guardian::AUTO_REVIEW_DENIED_ACTION_APPROVAL_DEVELOPER_PREFIX;
    let text = format!(
        r#"{approval_prefix}

Treat this as approval to perform that exact action in the same context in which it was originally requested.
Do not assume this also authorizes similar operations with different payloads.

Approved action:
{approved_action_json}"#,
    );
    let items = vec![ResponseItem::from(ResponseInputItem::Message {
        role: "developer".to_string(),
        content: vec![ContentItem::InputText { text }],
        phase: None,
    })];

    sess.inject_no_new_turn(items, /*current_turn_context*/ None)
        .await;
}

pub(super) fn submission_dispatch_span(sub: &Submission) -> tracing::Span {
    let op_name = sub.op.kind();
    let span_name = format!("op.dispatch.{op_name}");
    let dispatch_span = match &sub.op {
        Op::RealtimeConversationAudio(_) => {
            debug_span!(
                "submission_dispatch",
                otel.name = span_name.as_str(),
                submission.id = sub.id.as_str(),
                codex.op = op_name
            )
        }
        _ => info_span!(
            "submission_dispatch",
            otel.name = span_name.as_str(),
            submission.id = sub.id.as_str(),
            codex.op = op_name
        ),
    };
    if let Some(trace) = sub.trace.as_ref()
        && !set_parent_from_w3c_trace_context(&dispatch_span, trace)
    {
        warn!(
            submission.id = sub.id.as_str(),
            "ignoring invalid submission trace carrier"
        );
    }
    dispatch_span
}
