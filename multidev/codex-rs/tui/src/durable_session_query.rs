//! Parsing and deterministic rendering for the read-only Durable Session query UI.

use codex_app_server_client::QueryReadTicket;
use codex_app_server_client::QueryViewFreshness;
use codex_app_server_protocol::DurableSessionDomainLifecycle;
use codex_app_server_protocol::DurableSessionFactProvenance;
use codex_app_server_protocol::DurableSessionListIncompleteReason;
use codex_app_server_protocol::DurableSessionListResponse;
use codex_app_server_protocol::DurableSessionOperation;
use codex_app_server_protocol::DurableSessionOperationAvailability;
use codex_app_server_protocol::DurableSessionOperationAvailabilityReason;
use codex_app_server_protocol::DurableSessionReadIssue;
use codex_app_server_protocol::DurableSessionReadResponse;
use codex_app_server_protocol::DurableSessionReadStatus;
use codex_app_server_protocol::DurableSessionResidency;
use codex_app_server_protocol::DurableSessionStorageStatus;
use codex_app_server_protocol::DurableSessionTeamProducerState;
use codex_app_server_protocol::DurableSessionTeamRole;
use codex_app_server_protocol::DurableSessionTeamRootState;
use codex_app_server_protocol::DurableSessionView;

#[derive(Debug)]
pub(crate) enum DurableSessionQueryCompletion {
    List {
        ticket: QueryReadTicket,
        result: Result<DurableSessionListResponse, String>,
    },
    Session {
        ticket: QueryReadTicket,
        result: Box<Result<DurableSessionReadResponse, String>>,
    },
}

pub(crate) const DURABLE_SESSIONS_USAGE: &str =
    "Usage: /sessions [list [active|archived] | next | read <sessionId> <rootThreadId> | refresh]";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum DurableSessionListScope {
    Active,
    Archived,
}

impl DurableSessionListScope {
    pub(crate) fn archived(self) -> bool {
        match self {
            Self::Active => false,
            Self::Archived => true,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Active => "active",
            Self::Archived => "archived",
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum DurableSessionCommand {
    List {
        scope: DurableSessionListScope,
    },
    Next,
    Read {
        session_id: String,
        root_thread_id: String,
    },
    Refresh,
}

impl DurableSessionCommand {
    pub(crate) fn parse(args: &str) -> Result<Self, &'static str> {
        let parts = args.split_whitespace().collect::<Vec<_>>();
        match parts.as_slice() {
            [] | ["list"] | ["list", "active"] => Ok(Self::List {
                scope: DurableSessionListScope::Active,
            }),
            ["list", "archived"] => Ok(Self::List {
                scope: DurableSessionListScope::Archived,
            }),
            ["next"] => Ok(Self::Next),
            ["read", session_id, root_thread_id] => Ok(Self::Read {
                session_id: (*session_id).to_string(),
                root_thread_id: (*root_thread_id).to_string(),
            }),
            ["refresh"] => Ok(Self::Refresh),
            _ => Err(DURABLE_SESSIONS_USAGE),
        }
    }
}

pub(crate) fn render_list(
    response: &DurableSessionListResponse,
    freshness: QueryViewFreshness,
    scope: DurableSessionListScope,
) -> String {
    let mut lines = vec![
        "Durable Sessions — read only".to_string(),
        format!(
            "client view: {} | storage source: {} | complete: {} | next: {}",
            freshness_label(freshness),
            scope.label(),
            response.complete,
            if response.next_cursor.is_some() {
                "available"
            } else {
                "none"
            }
        ),
    ];
    if let Some(reason) = response.incomplete_reason {
        lines.push(format!("incomplete: {}", incomplete_reason_label(reason)));
    }
    if response.data.is_empty() {
        lines.push(if response.complete {
            "sessions: none in this storage source".to_string()
        } else {
            "sessions: no authoritative rows in this incomplete page".to_string()
        });
    }
    for view in &response.data {
        lines.push(format!(
            "- {} | storage={} | lifecycle={} | residency={} | read={}",
            view.identity.session_id,
            storage_label(view.storage_status),
            lifecycle_label(view.domain_lifecycle),
            residency_label(view.residency),
            read_status_label(&view.read_status)
        ));
        lines.push(format!(
            "  root={} | Team {}",
            view.identity
                .root_thread_id
                .as_deref()
                .unwrap_or("unavailable"),
            team_summary(view)
        ));
    }
    lines.join("\n")
}

pub(crate) fn render_projection(
    view: &DurableSessionView,
    freshness: QueryViewFreshness,
) -> String {
    let mut lines = vec![
        "Durable Session — read only".to_string(),
        format!("client view: {}", freshness_label(freshness)),
        format!("session: {}", view.identity.session_id),
        format!(
            "identity: root={} | source={}",
            view.identity
                .root_thread_id
                .as_deref()
                .unwrap_or("unavailable"),
            provenance_label(view.provenance.identity)
        ),
        format!(
            "storage: {} | source={}",
            storage_label(view.storage_status),
            provenance_label(view.provenance.storage_status)
        ),
        format!(
            "domain lifecycle: {} | source={}",
            lifecycle_label(view.domain_lifecycle),
            provenance_label(view.provenance.domain_lifecycle)
        ),
        format!(
            "runtime residency: {} | source={}",
            residency_label(view.residency),
            provenance_label(view.provenance.residency)
        ),
        format!("durable read: {}", read_status_label(&view.read_status)),
        format!(
            "operations: resume={} | set-root-state={} | close={} | archive={} | unarchive={} | delete={}",
            operation_label(&view.operation_availability.resume),
            operation_label(&view.operation_availability.set_root_state),
            operation_label(&view.operation_availability.close),
            operation_label(&view.operation_availability.archive),
            operation_label(&view.operation_availability.unarchive),
            operation_label(&view.operation_availability.delete),
        ),
    ];
    match &view.team {
        Some(team) => {
            lines.push(format!(
                "Team: instance={} | commit generation={} | commit fingerprint={} | domain revision={} | viewer={} ({}) | source={}",
                team.team_instance_id,
                team.commit_generation,
                team.commit_fingerprint,
                team.revision,
                team.viewer.thread_id,
                team_role_label(team.viewer.role),
                provenance_label(view.provenance.team)
            ));
            lines.push(format!(
                "Team bounds: omitted participants={} | omitted events={}",
                team.omitted_participants, team.omitted_events
            ));
            for participant in &team.participants {
                lines.push(format!(
                    "  participant={} | role={} | label={}",
                    participant.thread_id,
                    team_role_label(participant.role),
                    single_line_authored_text(&participant.label)
                ));
            }
            for event in &team.events {
                lines.push(format!(
                    "  event={} | omitted versions={}",
                    event.event_id, event.omitted_versions
                ));
                for version in &event.versions {
                    lines.push(format!(
                        "    version={} | author={} ({}) | summary={} | producer={} | root={} | retired={}",
                        version.version_id,
                        version.author_thread_id,
                        single_line_authored_text(&version.author_label),
                        single_line_authored_text(&version.summary),
                        producer_label(version.producer_state),
                        root_state_label(version.root_state),
                        version.retired
                    ));
                }
            }
        }
        None => lines.push(format!(
            "Team: unavailable | source={}",
            provenance_label(view.provenance.team)
        )),
    }
    lines.join("\n")
}

fn single_line_authored_text(value: &str) -> String {
    let mut normalized = String::with_capacity(value.len());
    let mut separator_pending = false;
    for character in value.chars() {
        if character.is_whitespace() || character.is_control() {
            separator_pending = !normalized.is_empty();
            continue;
        }
        if separator_pending {
            normalized.push(' ');
            separator_pending = false;
        }
        normalized.push(character);
    }
    normalized
}

pub(crate) fn render_refreshing() -> String {
    "Durable Sessions — read only\nclient view: refreshing".to_string()
}

pub(crate) fn render_query_failure(retained: Option<String>, error: &str) -> String {
    match retained {
        Some(retained) => format!(
            "Durable Session query failed: {error}\nRetained stale context (not current):\n{retained}"
        ),
        None => {
            format!(
                "Durable Session query failed: {error}\nclient view: unavailable; no retained view"
            )
        }
    }
}

pub(crate) fn render_sync_loss(retained: Option<String>, reason: &str) -> String {
    match retained {
        Some(retained) => format!(
            "Durable Session query sync lost: {reason}\nRetained stale context (not current):\n{retained}"
        ),
        None => format!(
            "Durable Session query sync lost: {reason}\nclient view: unavailable; no retained view"
        ),
    }
}

fn team_summary(view: &DurableSessionView) -> String {
    match &view.team {
        Some(team) => format!(
            "instance={} commit-generation={} commit-fingerprint={} domain-revision={}",
            team.team_instance_id, team.commit_generation, team.commit_fingerprint, team.revision
        ),
        None => format!(
            "unavailable(source={})",
            provenance_label(view.provenance.team)
        ),
    }
}

fn freshness_label(value: QueryViewFreshness) -> &'static str {
    match value {
        QueryViewFreshness::Absent => "absent",
        QueryViewFreshness::Refreshing => "refreshing",
        QueryViewFreshness::Fresh => "fresh",
        QueryViewFreshness::Stale => "stale",
    }
}

fn storage_label(value: DurableSessionStorageStatus) -> &'static str {
    match value {
        DurableSessionStorageStatus::Active => "active",
        DurableSessionStorageStatus::Archived => "archived",
        DurableSessionStorageStatus::Unknown => "unknown",
    }
}

fn lifecycle_label(value: DurableSessionDomainLifecycle) -> &'static str {
    match value {
        DurableSessionDomainLifecycle::Open => "open",
        DurableSessionDomainLifecycle::Closing => "closing",
        DurableSessionDomainLifecycle::Closed => "closed",
        DurableSessionDomainLifecycle::Failed => "failed",
        DurableSessionDomainLifecycle::Unknown => "unknown (no canonical lifecycle fact)",
    }
}

fn residency_label(value: DurableSessionResidency) -> &'static str {
    match value {
        DurableSessionResidency::ObservedOwnerHere => "owner observed in this app-server",
        DurableSessionResidency::OwnerUnavailableHere => "owner unavailable in this app-server",
        DurableSessionResidency::NotObservedHere => "owner not observed in this app-server",
        DurableSessionResidency::Unknown => "unknown",
    }
}

fn provenance_label(value: DurableSessionFactProvenance) -> &'static str {
    match value {
        DurableSessionFactProvenance::SessionMeta => "SessionMeta",
        DurableSessionFactProvenance::ThreadStore => "ThreadStore",
        DurableSessionFactProvenance::CommittedTeamSnapshot => "committed Team snapshot",
        DurableSessionFactProvenance::ServerRuntimeObservation => "this app-server observation",
        DurableSessionFactProvenance::DerivedPolicy => "query policy",
        DurableSessionFactProvenance::Unavailable => "unavailable",
    }
}

fn operation_label(operation: &DurableSessionOperation) -> String {
    let availability = match &operation.availability {
        DurableSessionOperationAvailability::Available => "available".to_string(),
        DurableSessionOperationAvailability::Unknown { reason } => {
            format!("unknown({})", operation_reason_label(*reason))
        }
        DurableSessionOperationAvailability::Unavailable { reason } => {
            format!("unavailable({})", operation_reason_label(*reason))
        }
    };
    format!(
        "{}[source={}]",
        availability,
        provenance_label(operation.provenance)
    )
}

fn operation_reason_label(reason: DurableSessionOperationAvailabilityReason) -> &'static str {
    match reason {
        DurableSessionOperationAvailabilityReason::ReadIncomplete => "read-incomplete",
        DurableSessionOperationAvailabilityReason::IdentityUnavailable => "identity-unavailable",
        DurableSessionOperationAvailabilityReason::StorageUnavailable => "storage-unavailable",
        DurableSessionOperationAvailabilityReason::LifecycleUnknown => "lifecycle-unknown",
        DurableSessionOperationAvailabilityReason::ResidencyUnknown => "residency-unknown",
        DurableSessionOperationAvailabilityReason::OwnerUnavailableHere => "owner-unavailable-here",
        DurableSessionOperationAvailabilityReason::NotObservedHere => "not-observed-here",
        DurableSessionOperationAvailabilityReason::ControlDisabled => "control-disabled",
        DurableSessionOperationAvailabilityReason::AlreadyLoaded => "already-loaded",
        DurableSessionOperationAvailabilityReason::AlreadyArchived => "already-archived",
        DurableSessionOperationAvailabilityReason::NotArchived => "not-archived",
        DurableSessionOperationAvailabilityReason::Closing => "closing",
        DurableSessionOperationAvailabilityReason::Closed => "closed",
        DurableSessionOperationAvailabilityReason::Failed => "failed",
        DurableSessionOperationAvailabilityReason::ChildSession => "child-session",
        DurableSessionOperationAvailabilityReason::Unsupported => "unsupported",
    }
}

fn read_status_label(status: &DurableSessionReadStatus) -> String {
    match status {
        DurableSessionReadStatus::Available => "available".to_string(),
        DurableSessionReadStatus::Incomplete { issue } => {
            format!("incomplete({})", read_issue_label(*issue))
        }
        DurableSessionReadStatus::Unavailable { issue } => {
            format!("unavailable({})", read_issue_label(*issue))
        }
        DurableSessionReadStatus::Unsupported { issue } => {
            format!("unsupported({})", read_issue_label(*issue))
        }
    }
}

fn read_issue_label(issue: DurableSessionReadIssue) -> &'static str {
    match issue {
        DurableSessionReadIssue::SourceUnavailable => "source-unavailable",
        DurableSessionReadIssue::SourceUnsupported => "source-unsupported",
        DurableSessionReadIssue::SourceChanged => "source-changed",
        DurableSessionReadIssue::BudgetExhausted => "budget-exhausted",
        DurableSessionReadIssue::IdentityUnavailable => "identity-unavailable",
        DurableSessionReadIssue::SessionNotFound => "session-not-found",
        DurableSessionReadIssue::NotCanonicalRoot => "not-canonical-root",
        DurableSessionReadIssue::SessionRootIdentityMismatch => "session-root-identity-mismatch",
        DurableSessionReadIssue::SessionMetaUnreadable => "SessionMeta-unreadable",
        DurableSessionReadIssue::SessionMetaIncompatible => "SessionMeta-incompatible",
        DurableSessionReadIssue::DurableMarkerMissing => "durable-marker-missing",
        DurableSessionReadIssue::DurableMarkerIncompatible => "durable-marker-incompatible",
        DurableSessionReadIssue::DurableMarkerIdentityMismatch => {
            "durable-marker-identity-mismatch"
        }
        DurableSessionReadIssue::TeamSnapshotMissing => "Team-snapshot-missing",
        DurableSessionReadIssue::TeamSnapshotCorrupt => "Team-snapshot-corrupt",
        DurableSessionReadIssue::TeamSnapshotIncompatible => "Team-snapshot-incompatible",
        DurableSessionReadIssue::TeamSnapshotValidationFailed => "Team-snapshot-validation-failed",
        DurableSessionReadIssue::LegacySession => "legacy-session",
        DurableSessionReadIssue::DurableSessionsDisabled => "durable-Sessions-disabled",
        DurableSessionReadIssue::Unknown => "unknown",
    }
}

fn incomplete_reason_label(reason: DurableSessionListIncompleteReason) -> &'static str {
    match reason {
        DurableSessionListIncompleteReason::SourceUnavailable => "source-unavailable",
        DurableSessionListIncompleteReason::SourceUnsupported => "source-unsupported",
        DurableSessionListIncompleteReason::SourceChanged => "source-changed",
        DurableSessionListIncompleteReason::BudgetExhausted => "budget-exhausted",
        DurableSessionListIncompleteReason::RecordUnreadable => "record-unreadable",
        DurableSessionListIncompleteReason::RecordIncompatible => "record-incompatible",
        DurableSessionListIncompleteReason::ClassificationFailed => "classification-failed",
        DurableSessionListIncompleteReason::Unknown => "unknown",
    }
}

fn team_role_label(value: DurableSessionTeamRole) -> &'static str {
    match value {
        DurableSessionTeamRole::Root => "Root",
        DurableSessionTeamRole::Member => "member",
    }
}

fn producer_label(value: DurableSessionTeamProducerState) -> &'static str {
    match value {
        DurableSessionTeamProducerState::Open => "open",
        DurableSessionTeamProducerState::Closed => "closed",
    }
}

fn root_state_label(value: DurableSessionTeamRootState) -> &'static str {
    match value {
        DurableSessionTeamRootState::Pending => "pending",
        DurableSessionTeamRootState::Tracking => "tracking",
        DurableSessionTeamRootState::Resolved => "resolved",
    }
}

#[cfg(test)]
#[path = "durable_session_query_tests.rs"]
mod tests;
