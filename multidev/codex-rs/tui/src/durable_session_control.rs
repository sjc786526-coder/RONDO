//! Parsing and deterministic copy for the formal `/session-control` UI.

use codex_app_server_client::DurableSessionControlPreview;
use codex_app_server_protocol::DurableSessionControlEffect;
use codex_app_server_protocol::DurableSessionControlOperation;
use codex_app_server_protocol::DurableSessionControlOutcome;
use codex_app_server_protocol::DurableSessionControlResponse;
use codex_app_server_protocol::DurableSessionTeamProducerState;
use codex_app_server_protocol::DurableSessionTeamRootState;

pub(crate) const DURABLE_SESSION_CONTROL_USAGE: &str = "Usage: /session-control [show | read <sessionId> <rootThreadId> | refresh | track <versionId> <open|closed> <pending|tracking|resolved> <pending|tracking|resolved> | close | archive | unarchive | delete | detach]";

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum DurableSessionControlCommand {
    Show,
    Read {
        session_id: String,
        root_thread_id: String,
    },
    Refresh,
    Mutate(DurableSessionControlOperation),
    Detach,
}

impl DurableSessionControlCommand {
    pub(crate) fn parse(args: &str) -> Result<Self, &'static str> {
        let parts = args.split_whitespace().collect::<Vec<_>>();
        match parts.as_slice() {
            [] | ["show"] => Ok(Self::Show),
            ["read", session_id, root_thread_id] => Ok(Self::Read {
                session_id: (*session_id).to_string(),
                root_thread_id: (*root_thread_id).to_string(),
            }),
            ["refresh"] => Ok(Self::Refresh),
            ["close"] => Ok(Self::Mutate(DurableSessionControlOperation::Close)),
            ["archive"] => Ok(Self::Mutate(DurableSessionControlOperation::Archive)),
            ["unarchive"] => Ok(Self::Mutate(DurableSessionControlOperation::Unarchive)),
            ["delete"] => Ok(Self::Mutate(DurableSessionControlOperation::Delete)),
            ["detach"] => Ok(Self::Detach),
            [
                "track",
                version_id,
                expected_producer_state,
                expected_root_state,
                next_root_state,
            ] => Ok(Self::Mutate(DurableSessionControlOperation::SetRootState {
                version_id: (*version_id).to_string(),
                expected_producer_state: parse_producer_state(expected_producer_state)
                    .ok_or(DURABLE_SESSION_CONTROL_USAGE)?,
                expected_root_state: parse_root_state(expected_root_state)
                    .ok_or(DURABLE_SESSION_CONTROL_USAGE)?,
                next_root_state: parse_root_state(next_root_state)
                    .ok_or(DURABLE_SESSION_CONTROL_USAGE)?,
            })),
            _ => Err(DURABLE_SESSION_CONTROL_USAGE),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct DurableSessionControlConfirmation {
    pub(crate) preview: DurableSessionControlPreview,
}

pub(crate) fn operation_label(operation: &DurableSessionControlOperation) -> &'static str {
    match operation {
        DurableSessionControlOperation::SetRootState { .. } => "update root state",
        DurableSessionControlOperation::Close => "close",
        DurableSessionControlOperation::Archive => "archive",
        DurableSessionControlOperation::Unarchive => "unarchive",
        DurableSessionControlOperation::Delete => "permanently delete",
    }
}

pub(crate) fn confirmation_target(
    session_id: &str,
    root_thread_id: &str,
    operation: &DurableSessionControlOperation,
) -> String {
    let target = format!("Session={session_id}; canonical Root={root_thread_id}");
    match operation {
        DurableSessionControlOperation::SetRootState {
            version_id,
            expected_producer_state,
            expected_root_state,
            next_root_state,
        } => format!(
            "{target}; version={version_id}; expected producer={}; expected Root={}; next Root={}",
            producer_state_label(*expected_producer_state),
            root_state_label(*expected_root_state),
            root_state_label(*next_root_state),
        ),
        DurableSessionControlOperation::Close => {
            format!("{target}; target=loaded canonical Root owner")
        }
        DurableSessionControlOperation::Archive | DurableSessionControlOperation::Delete => {
            format!("{target}; target=canonical Root subtree")
        }
        DurableSessionControlOperation::Unarchive => {
            format!("{target}; target=stored canonical Root")
        }
    }
}

pub(crate) fn render_pending(operation: &DurableSessionControlOperation) -> String {
    format!(
        "Durable Session control: {} submitted once\nresult: pending; this mutation will not be replayed automatically",
        operation_label(operation)
    )
}

pub(crate) fn render_completion(response: &DurableSessionControlResponse) -> String {
    let detail = match &response.outcome {
        DurableSessionControlOutcome::Applied { effect } => match effect {
            DurableSessionControlEffect::RootStateUpdated {
                changed,
                mutation_revision,
            } => format!(
                "applied root-state update; changed={changed}; mutation revision={mutation_revision}"
            ),
            DurableSessionControlEffect::OwnerClosed => {
                "applied close to the loaded Root owner".to_string()
            }
            DurableSessionControlEffect::Archived {
                affected_thread_ids,
            } => format!(
                "applied archive; affected threads={}",
                affected_thread_ids.len()
            ),
            DurableSessionControlEffect::Unarchived => "applied unarchive".to_string(),
            DurableSessionControlEffect::Deleted {
                affected_thread_ids,
            } => format!(
                "applied permanent delete; affected threads={}",
                affected_thread_ids.len()
            ),
        },
        DurableSessionControlOutcome::Rejected {
            operation,
            reason,
            message,
        } => {
            format!("rejected {operation:?}; reason={reason:?}; no effect was confirmed: {message}")
        }
        DurableSessionControlOutcome::Partial {
            operation,
            completed_thread_ids,
            message,
        } => format!(
            "partial {operation:?}; completed threads={}; {message}",
            completed_thread_ids.len()
        ),
        DurableSessionControlOutcome::Unknown { operation, message } => {
            format!("result unknown for {operation:?}; do not retry automatically: {message}")
        }
    };
    format!(
        "Durable Session control: {detail}\nThe attached query view is stale; a fresh session/read is required before another mutation."
    )
}

pub(crate) fn render_transport_unknown(message: &str) -> String {
    format!(
        "Durable Session control result unknown: {message}\nThe request was submitted once and was not replayed. A fresh session/read is required before another mutation."
    )
}

pub(crate) fn render_detached() -> String {
    "Durable Session control detached locally; Session and Team lifecycle were not changed."
        .to_string()
}

fn parse_producer_state(value: &str) -> Option<DurableSessionTeamProducerState> {
    match value.to_ascii_lowercase().as_str() {
        "open" => Some(DurableSessionTeamProducerState::Open),
        "closed" => Some(DurableSessionTeamProducerState::Closed),
        _ => None,
    }
}

fn producer_state_label(state: DurableSessionTeamProducerState) -> &'static str {
    match state {
        DurableSessionTeamProducerState::Open => "open",
        DurableSessionTeamProducerState::Closed => "closed",
    }
}

fn parse_root_state(value: &str) -> Option<DurableSessionTeamRootState> {
    match value.to_ascii_lowercase().as_str() {
        "pending" => Some(DurableSessionTeamRootState::Pending),
        "tracking" => Some(DurableSessionTeamRootState::Tracking),
        "resolved" => Some(DurableSessionTeamRootState::Resolved),
        _ => None,
    }
}

fn root_state_label(state: DurableSessionTeamRootState) -> &'static str {
    match state {
        DurableSessionTeamRootState::Pending => "pending",
        DurableSessionTeamRootState::Tracking => "tracking",
        DurableSessionTeamRootState::Resolved => "resolved",
    }
}

#[cfg(test)]
#[path = "durable_session_control_tests.rs"]
mod tests;
