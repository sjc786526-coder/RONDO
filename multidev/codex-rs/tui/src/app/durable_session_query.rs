//! Non-blocking App wiring for the default-off Durable Session query UI.

use super::*;
use crate::app_server_session::DurableSessionQueryRequest;
use crate::durable_session_control::render_transport_unknown;
use crate::durable_session_query::DURABLE_SESSIONS_USAGE;
use crate::durable_session_query::DurableSessionCommand;
use crate::durable_session_query::DurableSessionListScope;
use crate::durable_session_query::DurableSessionQueryCompletion;
use crate::durable_session_query::render_list;
use crate::durable_session_query::render_projection;
use crate::durable_session_query::render_query_failure;
use crate::durable_session_query::render_refreshing;
use crate::durable_session_query::render_sync_loss;
use codex_app_server_client::DurableSessionControlCertainty;
use codex_app_server_client::DurableSessionQueryAttachment;
use codex_app_server_client::DurableSessionQueryProjection;
use codex_app_server_client::QueryReadApplyResult;
use codex_app_server_protocol::DurableSessionListParams;
use codex_app_server_protocol::DurableSessionListResponse;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use codex_app_server_protocol::RequestId;

const DURABLE_SESSION_QUERY_PAGE_LIMIT: u32 = 25;
const DURABLE_SESSION_QUERY_TIMEOUT: Duration = Duration::from_secs(/*secs*/ 15);

impl App {
    pub(super) fn handle_durable_session_query_command(
        &mut self,
        app_server: &AppServerSession,
        args: &str,
    ) {
        if !self.config.features.enabled(Feature::DurableSessionQuery) {
            return;
        }

        let command = match DurableSessionCommand::parse(args) {
            Ok(command) => command,
            Err(_) => {
                self.chat_widget
                    .add_error_message(DURABLE_SESSIONS_USAGE.to_string());
                return;
            }
        };
        let control_was_pending = matches!(
            app_server.durable_session_control_certainty(),
            DurableSessionControlCertainty::Pending { .. }
        );
        let request = match command {
            DurableSessionCommand::List { scope } => {
                app_server.durable_session_begin_list(DurableSessionListParams {
                    cursor: None,
                    limit: Some(DURABLE_SESSION_QUERY_PAGE_LIMIT),
                    archived: scope.archived(),
                })
            }
            DurableSessionCommand::Next => app_server.durable_session_begin_next(),
            DurableSessionCommand::Read {
                session_id,
                root_thread_id,
            } => app_server.durable_session_begin_read(DurableSessionReadParams {
                session_id,
                root_thread_id,
            }),
            DurableSessionCommand::Refresh => app_server.durable_session_begin_refresh(),
        };
        let request = match request {
            Ok(request) => request,
            Err(error) => {
                self.chat_widget.add_error_message(error.to_string());
                return;
            }
        };
        if control_was_pending
            && !matches!(
                app_server.durable_session_control_certainty(),
                DurableSessionControlCertainty::Pending { .. }
            )
        {
            self.add_durable_session_output(render_transport_unknown(
                "the query attachment changed while a control attempt was pending",
            ));
        }

        self.add_durable_session_output(render_refreshing());
        self.spawn_durable_session_query(app_server, request);
    }

    pub(super) fn spawn_durable_session_query(
        &self,
        app_server: &AppServerSession,
        request: DurableSessionQueryRequest,
    ) {
        let request_handle = app_server.request_handle();
        let app_event_tx = self.app_event_tx.clone();
        tokio::spawn(async move {
            let completion = match request {
                DurableSessionQueryRequest::List { ticket, params } => {
                    let result = tokio::time::timeout(
                        DURABLE_SESSION_QUERY_TIMEOUT,
                        request_handle.request_typed::<DurableSessionListResponse>(
                            ClientRequest::DurableSessionList {
                                request_id: RequestId::String(Uuid::new_v4().to_string()),
                                params,
                            },
                        ),
                    )
                    .await
                    .map_err(|_| {
                        "session/list timed out after 15s; no retry was attempted".to_string()
                    })
                    .and_then(|result| result.map_err(|error| error.to_string()));
                    DurableSessionQueryCompletion::List { ticket, result }
                }
                DurableSessionQueryRequest::Session { ticket, params } => {
                    let result = tokio::time::timeout(
                        DURABLE_SESSION_QUERY_TIMEOUT,
                        request_handle.request_typed::<DurableSessionReadResponse>(
                            ClientRequest::DurableSessionRead {
                                request_id: RequestId::String(Uuid::new_v4().to_string()),
                                params,
                            },
                        ),
                    )
                    .await
                    .map_err(|_| {
                        "session/read timed out after 15s; no retry was attempted".to_string()
                    })
                    .and_then(|result| result.map_err(|error| error.to_string()));
                    DurableSessionQueryCompletion::Session {
                        ticket,
                        result: Box::new(result),
                    }
                }
            };
            app_event_tx.send(AppEvent::DurableSessionQueryCompleted(completion));
        });
    }

    pub(super) fn handle_durable_session_query_completion(
        &mut self,
        app_server: &AppServerSession,
        completion: DurableSessionQueryCompletion,
    ) {
        if !self.config.features.enabled(Feature::DurableSessionQuery) {
            app_server.durable_session_detach();
            return;
        }

        match completion {
            DurableSessionQueryCompletion::List { ticket, result } => match result {
                Ok(response) => {
                    let apply = app_server.durable_session_apply_list(ticket, response);
                    self.render_applied_durable_session_query(app_server, apply);
                }
                Err(error) => self.render_durable_session_query_failure(app_server, ticket, &error),
            },
            DurableSessionQueryCompletion::Session { ticket, result } => match *result {
                Ok(response) => {
                    let apply = app_server.durable_session_apply_read(ticket, response);
                    self.render_applied_durable_session_query(app_server, apply);
                }
                Err(error) => self.render_durable_session_query_failure(app_server, ticket, &error),
            },
        }
    }

    fn render_applied_durable_session_query(
        &mut self,
        app_server: &AppServerSession,
        apply: QueryReadApplyResult,
    ) {
        match apply {
            QueryReadApplyResult::Applied => {
                if let Some(rendered) = self.render_durable_session_projection(app_server) {
                    self.add_durable_session_output(rendered);
                }
            }
            QueryReadApplyResult::Retired => {}
            QueryReadApplyResult::AttachmentMismatch => {
                tracing::warn!("ignored mismatched Durable Session query completion");
            }
            QueryReadApplyResult::RejectedCommittedProjection(conflict) => {
                let retained = self.render_durable_session_projection(app_server);
                self.add_durable_session_output(render_query_failure(
                    retained,
                    &format!("committed Team projection conflict: {conflict:?}"),
                ));
            }
            QueryReadApplyResult::RejectedInvalidListProjection(error) => {
                let retained = self.render_durable_session_projection(app_server);
                self.add_durable_session_output(render_query_failure(
                    retained,
                    &format!("invalid Durable Session list projection: {error:?}"),
                ));
            }
            QueryReadApplyResult::RejectedInvalidSessionProjection(error) => {
                let retained = self.render_durable_session_projection(app_server);
                self.add_durable_session_output(render_query_failure(
                    retained,
                    &format!("invalid Durable Session read projection: {error:?}"),
                ));
            }
        }
    }

    fn render_durable_session_query_failure(
        &mut self,
        app_server: &AppServerSession,
        ticket: codex_app_server_client::QueryReadTicket,
        error: &str,
    ) {
        if !app_server.durable_session_apply_failure(ticket) {
            return;
        }
        let retained = self.render_durable_session_projection(app_server);
        self.add_durable_session_output(render_query_failure(retained, error));
    }

    pub(super) fn render_durable_session_projection(
        &self,
        app_server: &AppServerSession,
    ) -> Option<String> {
        let freshness = app_server.durable_session_view_freshness();
        match (
            app_server.durable_session_attachment(),
            app_server.durable_session_projection(),
        ) {
            (
                Some(DurableSessionQueryAttachment::List(params)),
                Some(DurableSessionQueryProjection::List(response)),
            ) => Some(render_list(
                &response,
                freshness,
                if params.archived {
                    DurableSessionListScope::Archived
                } else {
                    DurableSessionListScope::Active
                },
            )),
            (
                Some(DurableSessionQueryAttachment::Session(_)),
                Some(DurableSessionQueryProjection::Session(response)),
            ) => Some(render_projection(&response.session, freshness)),
            _ => None,
        }
    }

    pub(super) fn render_durable_session_sync_loss(
        &mut self,
        app_server: &AppServerSession,
        reason: &str,
    ) {
        if !self.config.features.enabled(Feature::DurableSessionQuery)
            || app_server.durable_session_attachment().is_none()
        {
            return;
        }
        let retained = self.render_durable_session_projection(app_server);
        self.add_durable_session_output(render_sync_loss(retained, reason));
    }

    pub(super) fn add_durable_session_output(&mut self, rendered: String) {
        self.chat_widget.add_plain_history_lines(
            rendered
                .lines()
                .map(|line| Line::from(line.to_string()))
                .collect(),
        );
    }
}
