//! Non-blocking App wiring for proof-bound, send-once Durable Session control.

use super::*;
use crate::durable_session_control::DURABLE_SESSION_CONTROL_USAGE;
use crate::durable_session_control::DurableSessionControlCommand;
use crate::durable_session_control::DurableSessionControlConfirmation;
use crate::durable_session_control::operation_label;
use crate::durable_session_control::render_completion;
use crate::durable_session_control::render_detached;
use crate::durable_session_control::render_pending;
use crate::durable_session_control::render_transport_unknown;
use crate::durable_session_query::render_refreshing;
use codex_app_server_client::DurableSessionControlAttempt;
use codex_app_server_client::DurableSessionControlAttemptTicket;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlResponse;
use codex_app_server_protocol::RequestId;

const DURABLE_SESSION_CONTROL_CONFIRMATION_VIEW_ID: &str = "durable-session-control-confirmation";
const DURABLE_SESSION_CONTROL_TIMEOUT: Duration = Duration::from_secs(/*secs*/ 15);

pub(super) fn durable_session_control_confirmation_view_params(
    label: &str,
    confirm_actions: Vec<SelectionAction>,
) -> SelectionViewParams {
    SelectionViewParams {
        view_id: Some(DURABLE_SESSION_CONTROL_CONFIRMATION_VIEW_ID),
        title: Some(format!("Confirm Durable Session {label}?")),
        subtitle: Some(
            "Proof rechecked at confirm. Sent once; unknown results are never retried.".to_string(),
        ),
        footer_hint: Some(standard_popup_hint_line()),
        items: vec![
            SelectionItem {
                name: format!("Confirm {label}"),
                description: Some("Submit this mutation once".to_string()),
                actions: confirm_actions,
                dismiss_on_select: true,
                ..Default::default()
            },
            SelectionItem {
                name: "Cancel".to_string(),
                description: Some("Do not submit the mutation".to_string()),
                dismiss_on_select: true,
                ..Default::default()
            },
        ],
        ..Default::default()
    }
}

impl App {
    pub(super) fn handle_durable_session_control_command(
        &mut self,
        app_server: &AppServerSession,
        args: &str,
    ) {
        if !self.formal_durable_session_control_enabled() {
            return;
        }

        let command = match DurableSessionControlCommand::parse(args) {
            Ok(command) => command,
            Err(_) => {
                self.chat_widget
                    .add_error_message(DURABLE_SESSION_CONTROL_USAGE.to_string());
                return;
            }
        };
        match command {
            DurableSessionControlCommand::Show => {
                if let Some(rendered) = self.render_durable_session_projection(app_server) {
                    self.add_durable_session_output(rendered);
                } else {
                    self.chat_widget.add_error_message(
                        "show requires an attached Durable Session query view".to_string(),
                    );
                }
            }
            DurableSessionControlCommand::Read {
                session_id,
                root_thread_id,
            } => self.handle_durable_session_query_command(
                app_server,
                &format!("read {session_id} {root_thread_id}"),
            ),
            DurableSessionControlCommand::Refresh => {
                self.handle_durable_session_query_command(app_server, "refresh");
            }
            DurableSessionControlCommand::Mutate(operation) => {
                self.show_durable_session_control_confirmation(app_server, operation);
            }
            DurableSessionControlCommand::Detach => {
                if app_server.durable_session_detach() {
                    self.add_durable_session_output(render_transport_unknown(
                        "the local attachment was detached while an attempt was pending",
                    ));
                }
                self.add_durable_session_output(render_detached());
            }
        }
    }

    fn show_durable_session_control_confirmation(
        &mut self,
        app_server: &AppServerSession,
        operation: DurableSessionControlOperation,
    ) {
        let Some(accepted_query_read_ticket) =
            app_server.durable_session_control_accepted_read_ticket()
        else {
            self.chat_widget.add_error_message(
                "control requires a fresh attached session/read result; use /session-control read or refresh"
                    .to_string(),
            );
            return;
        };
        let confirmation = DurableSessionControlConfirmation {
            accepted_query_read_ticket,
            operation,
        };
        let action_confirmation = confirmation.clone();
        let label = operation_label(&confirmation.operation);
        let confirm_actions: Vec<SelectionAction> = vec![Box::new(move |tx| {
            tx.send(AppEvent::DurableSessionControlConfirmed(
                action_confirmation.clone(),
            ));
        })];
        self.chat_widget
            .show_selection_view(durable_session_control_confirmation_view_params(
                label,
                confirm_actions,
            ));
    }

    pub(super) fn handle_durable_session_control_confirmed(
        &mut self,
        app_server: &AppServerSession,
        confirmation: DurableSessionControlConfirmation,
    ) {
        if !self.formal_durable_session_control_enabled() {
            self.chat_widget.add_error_message(
                "Durable Session control was disabled before confirmation".to_string(),
            );
            app_server.durable_session_detach();
            return;
        }
        let attempt = match app_server.durable_session_control_begin(
            confirmation.accepted_query_read_ticket,
            confirmation.operation,
        ) {
            Ok(attempt) => attempt,
            Err(error) => {
                self.chat_widget.add_error_message(format!(
                    "Durable Session control confirmation expired or is unavailable: {error:?}"
                ));
                return;
            }
        };
        self.add_durable_session_output(render_pending(&attempt.params.operation));
        self.spawn_durable_session_control(app_server, attempt);
    }

    fn spawn_durable_session_control(
        &self,
        app_server: &AppServerSession,
        attempt: DurableSessionControlAttempt,
    ) {
        let request_handle = app_server.request_handle();
        let app_event_tx = self.app_event_tx.clone();
        tokio::spawn(async move {
            let result = tokio::time::timeout(
                DURABLE_SESSION_CONTROL_TIMEOUT,
                request_handle.request_typed::<DurableSessionControlResponse>(
                    ClientRequest::DurableSessionControl {
                        request_id: RequestId::String(Uuid::new_v4().to_string()),
                        params: attempt.params,
                    },
                ),
            )
            .await
            .map_err(|_| {
                "session/control timed out after submission; no retry was attempted".to_string()
            })
            .and_then(|result| result.map_err(|error| error.to_string()));
            app_event_tx.send(AppEvent::DurableSessionControlCompleted {
                ticket: attempt.ticket,
                result,
            });
        });
    }

    pub(super) fn handle_durable_session_control_completion(
        &mut self,
        app_server: &AppServerSession,
        ticket: DurableSessionControlAttemptTicket,
        result: Result<DurableSessionControlResponse, String>,
    ) {
        let applied = match &result {
            Ok(response) => {
                app_server.durable_session_control_apply_response(ticket, response.clone())
            }
            Err(message) => {
                app_server.durable_session_control_apply_unknown(ticket, message.clone())
            }
        };
        if !applied {
            return;
        }

        match result {
            Ok(response) => self.add_durable_session_output(render_completion(&response)),
            Err(message) => self.add_durable_session_output(render_transport_unknown(&message)),
        }
        if self.formal_durable_session_control_enabled() {
            match app_server.durable_session_begin_refresh() {
                Ok(request) => {
                    self.add_durable_session_output(render_refreshing());
                    self.spawn_durable_session_query(app_server, request);
                }
                Err(error) => self.chat_widget.add_error_message(format!(
                    "Durable Session control completed, but session/read resync could not start: {error}"
                )),
            }
        } else {
            app_server.durable_session_detach();
        }
    }

    pub(super) fn render_durable_session_control_sync_loss(
        &mut self,
        pending_retired: bool,
        reason: &str,
    ) {
        if pending_retired {
            self.add_durable_session_output(render_transport_unknown(reason));
        }
    }

    fn formal_durable_session_control_enabled(&self) -> bool {
        self.config.features.enabled(Feature::DurableSessionQuery)
            && self.config.features.enabled(Feature::DurableSessionControl)
    }
}
