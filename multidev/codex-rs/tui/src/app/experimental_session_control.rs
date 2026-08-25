//! Thin App wiring for the default-off `/sessions` prototype.

use super::*;
use crate::experimental_session_control::ExperimentalSessionCommand;
use crate::experimental_session_control::SESSIONS_USAGE;
use crate::experimental_session_control::render_detached;
use crate::experimental_session_control::render_list;
use crate::experimental_session_control::render_mutation_status;
use crate::experimental_session_control::render_projection;

impl App {
    pub(super) async fn handle_experimental_session_control_command(
        &mut self,
        app_server: &mut AppServerSession,
        args: &str,
    ) {
        // Defense in depth: the popup and ChatWidget dispatch both gate this,
        // but an injected AppEvent must not bypass the product opt-in.
        if !self
            .config
            .features
            .enabled(Feature::ExperimentalSessionControl)
        {
            return;
        }

        let command = match ExperimentalSessionCommand::parse(args) {
            Ok(command) => command,
            Err(_) => {
                self.chat_widget
                    .add_error_message(SESSIONS_USAGE.to_string());
                return;
            }
        };

        match command {
            ExperimentalSessionCommand::List => {
                match app_server.experimental_session_list().await {
                    Ok(response) => self.add_experimental_session_output(render_list(&response)),
                    Err(err) => self
                        .chat_widget
                        .add_error_message(format!("Session prototype list failed: {err}")),
                }
            }
            ExperimentalSessionCommand::Read(params) => {
                match app_server.experimental_session_read(params).await {
                    Ok(view) => self.add_experimental_session_output(render_projection(
                        &view,
                        app_server.experimental_session_view_freshness(),
                        app_server.experimental_session_mutation_certainty(),
                    )),
                    Err(err) => {
                        self.render_retained_experimental_session_projection(app_server);
                        self.chat_widget
                            .add_error_message(format!("Session prototype read failed: {err}"));
                    }
                }
            }
            ExperimentalSessionCommand::Refresh => {
                match app_server.experimental_session_refresh().await {
                    Ok(view) => self.add_experimental_session_output(render_projection(
                        &view,
                        app_server.experimental_session_view_freshness(),
                        app_server.experimental_session_mutation_certainty(),
                    )),
                    Err(err) => {
                        self.render_retained_experimental_session_projection(app_server);
                        self.chat_widget.add_error_message(format!(
                            "Session prototype refresh failed; no mutation was replayed: {err}"
                        ));
                    }
                }
            }
            ExperimentalSessionCommand::Track(params) => {
                match app_server.experimental_session_track(params).await {
                    Ok(response) => self.add_experimental_session_output(render_mutation_status(
                        &format!(
                            "track response received; team={} revision={} changed={}",
                            response.team_instance_id, response.revision, response.changed
                        ),
                        app_server.experimental_session_view_freshness(),
                        app_server.experimental_session_mutation_certainty(),
                    )),
                    Err(err) => {
                        self.render_experimental_session_mutation_error(app_server, "track", &err);
                    }
                }
            }
            ExperimentalSessionCommand::Unarchive { session_id } => {
                match app_server.experimental_session_unarchive(&session_id).await {
                    Ok(()) => self.add_experimental_session_output(render_mutation_status(
                        "unarchive response received",
                        app_server.experimental_session_view_freshness(),
                        app_server.experimental_session_mutation_certainty(),
                    )),
                    Err(err) => {
                        self.render_experimental_session_mutation_error(
                            app_server,
                            "unarchive",
                            &err,
                        );
                    }
                }
            }
            ExperimentalSessionCommand::Detach => {
                app_server.experimental_session_detach();
                self.add_experimental_session_output(render_detached());
            }
        }
    }

    fn render_retained_experimental_session_projection(&mut self, app_server: &AppServerSession) {
        if let Some(view) = app_server.experimental_session_projection() {
            self.add_experimental_session_output(render_projection(
                &view,
                app_server.experimental_session_view_freshness(),
                app_server.experimental_session_mutation_certainty(),
            ));
        }
    }

    pub(super) fn render_experimental_session_sync_loss(
        &mut self,
        app_server: &AppServerSession,
        reason: &str,
    ) {
        if !self
            .config
            .features
            .enabled(Feature::ExperimentalSessionControl)
        {
            return;
        }
        let Some(view) = app_server.experimental_session_projection() else {
            return;
        };
        self.add_experimental_session_output(format!(
            "Session control prototype sync lost: {reason}\n{}",
            render_projection(
                &view,
                app_server.experimental_session_view_freshness(),
                app_server.experimental_session_mutation_certainty(),
            )
        ));
    }

    fn render_experimental_session_mutation_error(
        &mut self,
        app_server: &AppServerSession,
        operation: &str,
        error: &crate::app_server_session::ExperimentalSessionMutationAttemptError,
    ) {
        match error.outcome() {
            crate::app_server_session::ExperimentalSessionMutationAttemptOutcome::Rejected => {
                self.add_experimental_session_output(render_mutation_status(
                    &format!("{operation} rejected before side effects"),
                    app_server.experimental_session_view_freshness(),
                    codex_app_server_client::MutationCertainty::Known(
                        codex_app_server_client::KnownMutationOutcome::Rejected,
                    ),
                ));
                self.chat_widget.add_error_message(format!(
                    "Session prototype {operation} was rejected: {error}"
                ));
            }
            crate::app_server_session::ExperimentalSessionMutationAttemptOutcome::ResultUnknown => {
                self.add_experimental_session_output(render_mutation_status(
                    &format!("{operation} result is unknown"),
                    app_server.experimental_session_view_freshness(),
                    codex_app_server_client::MutationCertainty::Unknown,
                ));
                self.chat_widget.add_error_message(format!(
                    "Session prototype {operation} result is unknown; it was not replayed: {error}"
                ));
            }
            crate::app_server_session::ExperimentalSessionMutationAttemptOutcome::NotSubmitted => {
                self.chat_widget.add_error_message(format!(
                    "Session prototype {operation} was not submitted: {error}"
                ));
            }
        }
    }

    fn add_experimental_session_output(&mut self, rendered: String) {
        self.chat_widget.add_plain_history_lines(
            rendered
                .lines()
                .map(|line| Line::from(line.to_string()))
                .collect(),
        );
    }
}
