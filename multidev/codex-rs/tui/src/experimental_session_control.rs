//! Parsing and deterministic rendering for the experimental `/session-control` UI.

use codex_app_server_client::MutationCertainty;
use codex_app_server_client::ViewFreshness;
use codex_app_server_protocol::ExperimentalSessionDomainLifecycle;
use codex_app_server_protocol::ExperimentalSessionFactProvenance;
use codex_app_server_protocol::ExperimentalSessionListResponse;
use codex_app_server_protocol::ExperimentalSessionOperation;
use codex_app_server_protocol::ExperimentalSessionOperationAvailability;
use codex_app_server_protocol::ExperimentalSessionOperationUnavailableReason;
use codex_app_server_protocol::ExperimentalSessionReadParams;
use codex_app_server_protocol::ExperimentalSessionResidency;
use codex_app_server_protocol::ExperimentalSessionTeamProducerState;
use codex_app_server_protocol::ExperimentalSessionTeamRootState;
use codex_app_server_protocol::ExperimentalSessionUpdateTeamLifecycleParams;
use codex_app_server_protocol::ExperimentalSessionView;

pub(crate) const SESSION_CONTROL_USAGE: &str = "Usage: /session-control [list | read <sessionId> [open|closing|closed|archived|failed|partial|unknown] | refresh | track <rootThreadId> <versionId> <open|closed> <pending|tracking|resolved> <pending|tracking|resolved> | unarchive <sessionId> | detach]";

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum ExperimentalSessionCommand {
    List,
    Read(ExperimentalSessionReadParams),
    Refresh,
    Track(ExperimentalSessionUpdateTeamLifecycleParams),
    Unarchive { session_id: String },
    Detach,
}

impl ExperimentalSessionCommand {
    pub(crate) fn parse(args: &str) -> Result<Self, &'static str> {
        let parts = args.split_whitespace().collect::<Vec<_>>();
        match parts.as_slice() {
            [] | ["list"] => Ok(Self::List),
            ["refresh"] => Ok(Self::Refresh),
            ["detach"] => Ok(Self::Detach),
            ["unarchive", session_id] => Ok(Self::Unarchive {
                session_id: (*session_id).to_string(),
            }),
            ["read", session_id] => Ok(Self::Read(ExperimentalSessionReadParams {
                session_id: (*session_id).to_string(),
                prototype_facts: None,
            })),
            ["read", session_id, lifecycle] => {
                let domain_lifecycle =
                    parse_domain_lifecycle(lifecycle).ok_or(SESSION_CONTROL_USAGE)?;
                Ok(Self::Read(ExperimentalSessionReadParams {
                    session_id: (*session_id).to_string(),
                    prototype_facts: Some(
                        codex_app_server_protocol::ExperimentalSessionPrototypeFacts {
                            domain_lifecycle,
                        },
                    ),
                }))
            }
            [
                "track",
                root_thread_id,
                version_id,
                expected_producer_state,
                expected_root_state,
                next_root_state,
            ] => Ok(Self::Track(ExperimentalSessionUpdateTeamLifecycleParams {
                root_thread_id: (*root_thread_id).to_string(),
                version_id: (*version_id).to_string(),
                expected_producer_state: parse_producer_state(expected_producer_state)
                    .ok_or(SESSION_CONTROL_USAGE)?,
                expected_root_state: parse_root_state(expected_root_state)
                    .ok_or(SESSION_CONTROL_USAGE)?,
                next_root_state: parse_root_state(next_root_state).ok_or(SESSION_CONTROL_USAGE)?,
            })),
            _ => Err(SESSION_CONTROL_USAGE),
        }
    }
}

pub(crate) fn render_list(response: &ExperimentalSessionListResponse) -> String {
    let mut lines = vec![
        "Session control prototype — discovery is not the S1 durable read model".to_string(),
        format!(
            "discovery: source={} complete={} next={}",
            provenance_label(response.provenance),
            response.complete,
            response.next_cursor.as_deref().unwrap_or("none")
        ),
    ];
    if response.data.is_empty() {
        lines.push(if response.complete {
            "sessions: none".to_string()
        } else {
            "sessions: unavailable or incomplete; an empty page is not authoritative".to_string()
        });
    } else {
        for view in &response.data {
            lines.push(format!(
                "- {} lifecycle={} residency={} root={}",
                view.identity.session_id,
                lifecycle_label(view.domain_lifecycle),
                residency_label(view.residency),
                view.identity.root_thread_id.as_deref().unwrap_or("unknown")
            ));
        }
    }
    lines.join("\n")
}

pub(crate) fn render_projection(
    view: &ExperimentalSessionView,
    freshness: ViewFreshness,
    certainty: MutationCertainty,
) -> String {
    let mut lines = vec![
        "Session control prototype — facts may be prototype, unknown, or unavailable".to_string(),
        format!("session: {}", view.identity.session_id),
        format!(
            "identity: root={} source={}",
            view.identity.root_thread_id.as_deref().unwrap_or("unknown"),
            provenance_label(view.provenance.identity)
        ),
        format!(
            "domain lifecycle: {} source={}",
            lifecycle_label(view.domain_lifecycle),
            provenance_label(view.provenance.domain_lifecycle)
        ),
        format!(
            "owner/runtime residency: {} source={}",
            residency_label(view.residency),
            provenance_label(view.provenance.residency)
        ),
        format!(
            "operations: track={} archive={} unarchive={}",
            operation_label(&view.operation_availability.update_team_lifecycle),
            operation_label(&view.operation_availability.archive),
            operation_label(&view.operation_availability.unarchive),
        ),
        format!(
            "client sync: view={} mutation-result={}",
            freshness_label(freshness),
            certainty_label(certainty)
        ),
    ];
    match &view.team {
        Some(team) => {
            lines.push(format!(
                "team prototype: instance={} revision={} viewer={} role={:?} omitted-participants={} omitted-events={} source={}",
                team.team_instance_id,
                team.revision,
                team.viewer_thread_id,
                team.viewer_role,
                team.omitted_participants,
                team.omitted_events,
                provenance_label(view.provenance.team)
            ));
            for event in &team.events {
                lines.push(format!(
                    "  event={} omitted-versions={}",
                    event.event_id, event.omitted_versions
                ));
                for version in &event.versions {
                    lines.push(format!(
                        "    version={} producer={} root={} retired={}",
                        version.version_id,
                        producer_label(version.producer_state),
                        root_state_label(version.root_state),
                        version.retired
                    ));
                }
            }
        }
        None => lines.push(format!(
            "team prototype: unavailable source={}",
            provenance_label(view.provenance.team)
        )),
    }
    lines.join("\n")
}

pub(crate) fn render_detached() -> String {
    "Session control prototype detached; Team lifecycle was not changed.".to_string()
}

pub(crate) fn render_mutation_status(
    label: &str,
    freshness: ViewFreshness,
    certainty: MutationCertainty,
) -> String {
    format!(
        "Session control prototype: {label}\nclient sync: view={} mutation-result={}\nRun /session-control refresh before another mutation when the view is stale.",
        freshness_label(freshness),
        certainty_label(certainty)
    )
}

fn parse_domain_lifecycle(value: &str) -> Option<ExperimentalSessionDomainLifecycle> {
    match value.to_ascii_lowercase().as_str() {
        "open" => Some(ExperimentalSessionDomainLifecycle::Open),
        "closing" => Some(ExperimentalSessionDomainLifecycle::Closing),
        "closed" => Some(ExperimentalSessionDomainLifecycle::Closed),
        "archived" => Some(ExperimentalSessionDomainLifecycle::Archived),
        "failed" => Some(ExperimentalSessionDomainLifecycle::Failed),
        "partial" => Some(ExperimentalSessionDomainLifecycle::Partial),
        "unknown" => Some(ExperimentalSessionDomainLifecycle::Unknown),
        _ => None,
    }
}

fn parse_producer_state(value: &str) -> Option<ExperimentalSessionTeamProducerState> {
    match value.to_ascii_lowercase().as_str() {
        "open" => Some(ExperimentalSessionTeamProducerState::Open),
        "closed" => Some(ExperimentalSessionTeamProducerState::Closed),
        _ => None,
    }
}

fn parse_root_state(value: &str) -> Option<ExperimentalSessionTeamRootState> {
    match value.to_ascii_lowercase().as_str() {
        "pending" => Some(ExperimentalSessionTeamRootState::Pending),
        "tracking" => Some(ExperimentalSessionTeamRootState::Tracking),
        "resolved" => Some(ExperimentalSessionTeamRootState::Resolved),
        _ => None,
    }
}

fn lifecycle_label(value: ExperimentalSessionDomainLifecycle) -> &'static str {
    match value {
        ExperimentalSessionDomainLifecycle::Open => "open",
        ExperimentalSessionDomainLifecycle::Closing => "closing (not closed)",
        ExperimentalSessionDomainLifecycle::Closed => "closed",
        ExperimentalSessionDomainLifecycle::Archived => "archived",
        ExperimentalSessionDomainLifecycle::Failed => "failed (not closed)",
        ExperimentalSessionDomainLifecycle::Partial => "partial (not closed)",
        ExperimentalSessionDomainLifecycle::Unknown => "unknown (not closed)",
    }
}

fn residency_label(value: ExperimentalSessionResidency) -> &'static str {
    match value {
        ExperimentalSessionResidency::LoadedOwner => "loaded owner",
        ExperimentalSessionResidency::LoadedNonOwner => "loaded non-owner",
        ExperimentalSessionResidency::UnloadedResumable => "unloaded resumable",
        ExperimentalSessionResidency::UnloadedNotResumable => "unloaded not-resumable",
        ExperimentalSessionResidency::OwnerUnavailable => "owner unavailable",
        ExperimentalSessionResidency::Unknown => "unknown",
    }
}

fn availability_label(value: &ExperimentalSessionOperationAvailability) -> String {
    match value {
        ExperimentalSessionOperationAvailability::Available => "available".to_string(),
        ExperimentalSessionOperationAvailability::Unavailable { reason } => {
            format!("unavailable({})", unavailable_reason_label(*reason))
        }
    }
}

fn operation_label(value: &ExperimentalSessionOperation) -> String {
    format!(
        "{}[source={}]",
        availability_label(&value.availability),
        provenance_label(value.provenance)
    )
}

fn unavailable_reason_label(reason: ExperimentalSessionOperationUnavailableReason) -> &'static str {
    match reason {
        ExperimentalSessionOperationUnavailableReason::Archived => "archived",
        ExperimentalSessionOperationUnavailableReason::NotArchived => "not-archived",
        ExperimentalSessionOperationUnavailableReason::NotLoaded => "not-loaded",
        ExperimentalSessionOperationUnavailableReason::NotOwner => "not-owner",
        ExperimentalSessionOperationUnavailableReason::ChildOnly => "child-only",
        ExperimentalSessionOperationUnavailableReason::OwnerUnavailable => "owner-unavailable",
        ExperimentalSessionOperationUnavailableReason::IdentityUnavailable => {
            "identity-unavailable"
        }
        ExperimentalSessionOperationUnavailableReason::TeamUnavailable => "team-unavailable",
        ExperimentalSessionOperationUnavailableReason::Unsupported => "unsupported",
        ExperimentalSessionOperationUnavailableReason::Unknown => "unknown",
    }
}

fn provenance_label(value: ExperimentalSessionFactProvenance) -> &'static str {
    match value {
        ExperimentalSessionFactProvenance::LiveOwner => "live-owner",
        ExperimentalSessionFactProvenance::LiveRuntime => "live-runtime",
        ExperimentalSessionFactProvenance::ThreadStore => "thread-store",
        ExperimentalSessionFactProvenance::StateDbPrototype => "state-db-prototype",
        ExperimentalSessionFactProvenance::RolloutPrototype => "rollout-prototype",
        ExperimentalSessionFactProvenance::PrototypeInput => "prototype-input",
        ExperimentalSessionFactProvenance::Unavailable => "unavailable",
    }
}

fn producer_label(value: ExperimentalSessionTeamProducerState) -> &'static str {
    match value {
        ExperimentalSessionTeamProducerState::Open => "open",
        ExperimentalSessionTeamProducerState::Closed => "closed",
    }
}

fn root_state_label(value: ExperimentalSessionTeamRootState) -> &'static str {
    match value {
        ExperimentalSessionTeamRootState::Pending => "pending",
        ExperimentalSessionTeamRootState::Tracking => "tracking",
        ExperimentalSessionTeamRootState::Resolved => "resolved",
    }
}

fn freshness_label(value: ViewFreshness) -> &'static str {
    match value {
        ViewFreshness::Absent => "absent",
        ViewFreshness::Refreshing => "refreshing",
        ViewFreshness::Fresh => "fresh",
        ViewFreshness::Stale => "stale",
    }
}

fn certainty_label(value: MutationCertainty) -> &'static str {
    match value {
        MutationCertainty::None => "none",
        MutationCertainty::Pending => "pending",
        MutationCertainty::Known(outcome) => match outcome {
            codex_app_server_client::KnownMutationOutcome::Succeeded => "known-success",
            codex_app_server_client::KnownMutationOutcome::Rejected => "known-rejected",
            codex_app_server_client::KnownMutationOutcome::Failed => "known-failed",
            codex_app_server_client::KnownMutationOutcome::Partial => "known-partial",
        },
        MutationCertainty::Unknown => "unknown",
    }
}

#[cfg(test)]
#[path = "experimental_session_control_tests.rs"]
mod tests;
