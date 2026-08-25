use super::*;
use codex_app_server_protocol::DurableSessionIdentity;
use codex_app_server_protocol::DurableSessionOperation;
use codex_app_server_protocol::DurableSessionOperations;
use codex_app_server_protocol::DurableSessionProvenance;
use codex_app_server_protocol::DurableSessionTeamEventProjection;
use codex_app_server_protocol::DurableSessionTeamParticipantProjection;
use codex_app_server_protocol::DurableSessionTeamProjection;
use codex_app_server_protocol::DurableSessionTeamRole;
use codex_app_server_protocol::DurableSessionTeamVersionProjection;
use codex_app_server_protocol::DurableSessionTeamViewer;
use pretty_assertions::assert_eq;

fn operation(
    availability: DurableSessionOperationAvailability,
    provenance: DurableSessionFactProvenance,
) -> DurableSessionOperation {
    DurableSessionOperation {
        availability,
        provenance,
    }
}

fn unavailable_operation(
    reason: DurableSessionOperationAvailabilityReason,
    provenance: DurableSessionFactProvenance,
) -> DurableSessionOperation {
    operation(
        DurableSessionOperationAvailability::Unavailable { reason },
        provenance,
    )
}

fn unknown_operation(reason: DurableSessionOperationAvailabilityReason) -> DurableSessionOperation {
    operation(
        DurableSessionOperationAvailability::Unknown { reason },
        DurableSessionFactProvenance::Unavailable,
    )
}

fn unknown_operations(
    reason: DurableSessionOperationAvailabilityReason,
) -> DurableSessionOperations {
    DurableSessionOperations {
        resume: unknown_operation(reason),
        close: unknown_operation(reason),
        archive: unknown_operation(reason),
        unarchive: unknown_operation(reason),
        delete: unknown_operation(reason),
    }
}

fn authenticated_operations(
    storage_status: DurableSessionStorageStatus,
) -> DurableSessionOperations {
    let (archive, unarchive) = match storage_status {
        DurableSessionStorageStatus::Active => (
            unknown_operation(DurableSessionOperationAvailabilityReason::Unsupported),
            unavailable_operation(
                DurableSessionOperationAvailabilityReason::NotArchived,
                DurableSessionFactProvenance::ThreadStore,
            ),
        ),
        DurableSessionStorageStatus::Archived => (
            unavailable_operation(
                DurableSessionOperationAvailabilityReason::AlreadyArchived,
                DurableSessionFactProvenance::ThreadStore,
            ),
            unknown_operation(DurableSessionOperationAvailabilityReason::Unsupported),
        ),
        DurableSessionStorageStatus::Unknown => {
            return unknown_operations(
                DurableSessionOperationAvailabilityReason::StorageUnavailable,
            );
        }
    };
    DurableSessionOperations {
        resume: unknown_operation(DurableSessionOperationAvailabilityReason::Unsupported),
        close: unknown_operation(DurableSessionOperationAvailabilityReason::LifecycleUnknown),
        archive,
        unarchive,
        delete: unknown_operation(DurableSessionOperationAvailabilityReason::Unsupported),
    }
}

fn view(session_id: &str, storage_status: DurableSessionStorageStatus) -> DurableSessionView {
    DurableSessionView {
        identity: DurableSessionIdentity {
            session_id: session_id.to_string(),
            root_thread_id: Some(format!("root-{session_id}")),
        },
        storage_status,
        domain_lifecycle: DurableSessionDomainLifecycle::Unknown,
        residency: DurableSessionResidency::NotObservedHere,
        operation_availability: authenticated_operations(storage_status),
        provenance: DurableSessionProvenance {
            identity: DurableSessionFactProvenance::SessionMeta,
            storage_status: DurableSessionFactProvenance::ThreadStore,
            domain_lifecycle: DurableSessionFactProvenance::Unavailable,
            residency: DurableSessionFactProvenance::ServerRuntimeObservation,
            team: DurableSessionFactProvenance::CommittedTeamSnapshot,
        },
        read_status: DurableSessionReadStatus::Available,
        team: Some(DurableSessionTeamProjection {
            team_instance_id: format!("team-{session_id}"),
            commit_generation: 9,
            commit_fingerprint:
                "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    .to_string(),
            revision: 17,
            viewer: DurableSessionTeamViewer {
                thread_id: format!("root-{session_id}"),
                role: DurableSessionTeamRole::Root,
            },
            participants: vec![DurableSessionTeamParticipantProjection {
                thread_id: format!("member-{session_id}"),
                role: DurableSessionTeamRole::Member,
                label: "reviewer".to_string(),
            }],
            omitted_participants: 2,
            events: vec![DurableSessionTeamEventProjection {
                event_id: "event-a".to_string(),
                title: "bounded event".to_string(),
                versions: vec![DurableSessionTeamVersionProjection {
                    version_id: "version-a".to_string(),
                    author_thread_id: format!("root-{session_id}"),
                    author_label: "root".to_string(),
                    summary: "accepted result".to_string(),
                    producer_state: DurableSessionTeamProducerState::Closed,
                    root_state: DurableSessionTeamRootState::Resolved,
                    retired: false,
                }],
                omitted_versions: 3,
            }],
            omitted_events: 4,
        }),
    }
}

fn unavailable_view(session_id: &str, read_status: DurableSessionReadStatus) -> DurableSessionView {
    DurableSessionView {
        identity: DurableSessionIdentity {
            session_id: session_id.to_string(),
            root_thread_id: None,
        },
        storage_status: DurableSessionStorageStatus::Unknown,
        domain_lifecycle: DurableSessionDomainLifecycle::Unknown,
        residency: DurableSessionResidency::Unknown,
        operation_availability: unknown_operations(
            DurableSessionOperationAvailabilityReason::IdentityUnavailable,
        ),
        provenance: DurableSessionProvenance {
            identity: DurableSessionFactProvenance::Unavailable,
            storage_status: DurableSessionFactProvenance::Unavailable,
            domain_lifecycle: DurableSessionFactProvenance::Unavailable,
            residency: DurableSessionFactProvenance::Unavailable,
            team: DurableSessionFactProvenance::Unavailable,
        },
        read_status,
        team: None,
    }
}

#[test]
fn parses_only_query_commands() {
    assert_eq!(
        DurableSessionCommand::parse(""),
        Ok(DurableSessionCommand::List {
            scope: DurableSessionListScope::Active,
        })
    );
    assert_eq!(
        DurableSessionCommand::parse("list archived"),
        Ok(DurableSessionCommand::List {
            scope: DurableSessionListScope::Archived,
        })
    );
    assert_eq!(
        DurableSessionCommand::parse("read session-a root-a"),
        Ok(DurableSessionCommand::Read {
            session_id: "session-a".to_string(),
            root_thread_id: "root-a".to_string(),
        })
    );
    assert_eq!(
        DurableSessionCommand::parse("next"),
        Ok(DurableSessionCommand::Next)
    );
    assert_eq!(
        DurableSessionCommand::parse("refresh"),
        Ok(DurableSessionCommand::Refresh)
    );

    for mutation in [
        "track root-a version-a open pending resolved",
        "unarchive session-a",
        "detach",
        "read session-a",
    ] {
        assert_eq!(
            DurableSessionCommand::parse(mutation),
            Err(DURABLE_SESSIONS_USAGE),
            "formal query accepted mutation-shaped input: {mutation}"
        );
    }
}

#[test]
fn durable_session_query_list_pages() {
    let active = view("active-a", DurableSessionStorageStatus::Active);
    let response = DurableSessionListResponse {
        data: vec![active],
        next_cursor: Some("opaque-and-hidden".to_string()),
        complete: true,
        incomplete_reason: None,
    };

    insta::assert_snapshot!(
        "durable_session_query_list_pages",
        render_list(
            &response,
            QueryViewFreshness::Fresh,
            DurableSessionListScope::Active
        )
    );
}

#[test]
fn durable_session_query_detail_gallery() {
    let mut observed = view("observed", DurableSessionStorageStatus::Active);
    observed.residency = DurableSessionResidency::ObservedOwnerHere;
    let mut archived = view("archived", DurableSessionStorageStatus::Archived);
    archived.team = None;
    archived.provenance.team = DurableSessionFactProvenance::Unavailable;
    archived.read_status = DurableSessionReadStatus::Incomplete {
        issue: DurableSessionReadIssue::TeamSnapshotCorrupt,
    };
    archived.operation_availability =
        unknown_operations(DurableSessionOperationAvailabilityReason::ReadIncomplete);
    let identity_mismatch = unavailable_view(
        "identity-mismatch",
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SessionRootIdentityMismatch,
        },
    );

    let rendered = [
        render_projection(&observed, QueryViewFreshness::Fresh),
        render_projection(&archived, QueryViewFreshness::Fresh),
        render_projection(&identity_mismatch, QueryViewFreshness::Fresh),
    ]
    .join("\n\n");
    insta::assert_snapshot!("durable_session_query_detail_gallery", rendered);
}

#[test]
fn authored_text_normalization_is_single_line_and_trimmed() {
    assert_eq!(
        single_line_authored_text(" \t reviewer\r\nroot\u{1b}[2J\u{7}\u{2028}summary \u{85} ",),
        "reviewer root [2J summary"
    );
}

#[test]
fn durable_session_query_authored_text_is_single_line() {
    let mut projection = view("authored-text", DurableSessionStorageStatus::Active);
    let team = projection.team.as_mut().expect("Team projection");
    team.participants[0].label = "reviewer\nFAKE lifecycle: closed\t\u{1b}[2J".to_string();
    let version = &mut team.events[0].versions[0];
    version.author_label = "root\r\nFAKE operations: available".to_string();
    version.summary = "accepted\u{7}\nFAKE storage: archived".to_string();

    let rendered = render_projection(&projection, QueryViewFreshness::Fresh);

    assert_eq!(
        rendered
            .lines()
            .filter(|line| line.contains("participant="))
            .count(),
        1
    );
    assert_eq!(
        rendered
            .lines()
            .filter(|line| line.contains("version="))
            .count(),
        1
    );
    assert!(
        rendered
            .lines()
            .all(|line| !line.chars().any(char::is_control))
    );
    assert!(
        !rendered
            .lines()
            .any(|line| line.trim_start().starts_with("FAKE "))
    );
    insta::assert_snapshot!(
        "durable_session_query_authored_text_is_single_line",
        rendered
    );
}

#[test]
fn durable_session_query_incomplete_and_stale() {
    let mut incomplete = view("partial", DurableSessionStorageStatus::Archived);
    incomplete.team = None;
    incomplete.provenance.team = DurableSessionFactProvenance::Unavailable;
    incomplete.read_status = DurableSessionReadStatus::Unsupported {
        issue: DurableSessionReadIssue::SourceUnsupported,
    };
    incomplete.operation_availability =
        unknown_operations(DurableSessionOperationAvailabilityReason::ReadIncomplete);
    let response = DurableSessionListResponse {
        data: vec![incomplete],
        next_cursor: None,
        complete: false,
        incomplete_reason: Some(DurableSessionListIncompleteReason::BudgetExhausted),
    };
    let retained = render_list(
        &response,
        QueryViewFreshness::Stale,
        DurableSessionListScope::Archived,
    );
    let unknown = render_list(
        &DurableSessionListResponse {
            data: Vec::new(),
            next_cursor: None,
            complete: false,
            incomplete_reason: Some(DurableSessionListIncompleteReason::Unknown),
        },
        QueryViewFreshness::Fresh,
        DurableSessionListScope::Active,
    );
    let rendered = [
        render_query_failure(
            Some(retained),
            "session/list timed out; no retry was attempted",
        ),
        unknown,
    ]
    .join("\n\n");

    insta::assert_snapshot!("durable_session_query_incomplete_and_stale", rendered);
}
