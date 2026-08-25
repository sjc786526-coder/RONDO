use super::*;
use codex_app_server_protocol::ExperimentalSessionIdentity;
use codex_app_server_protocol::ExperimentalSessionOperation;
use codex_app_server_protocol::ExperimentalSessionOperations;
use codex_app_server_protocol::ExperimentalSessionProvenance;
use codex_app_server_protocol::ExperimentalSessionTeamEventProjection;
use codex_app_server_protocol::ExperimentalSessionTeamProjection;
use codex_app_server_protocol::ExperimentalSessionTeamVersionProjection;
use codex_app_server_protocol::ExperimentalSessionTeamViewerRole;

fn view(
    session_id: &str,
    lifecycle: ExperimentalSessionDomainLifecycle,
    residency: ExperimentalSessionResidency,
    unavailable_reason: Option<ExperimentalSessionOperationUnavailableReason>,
) -> ExperimentalSessionView {
    let update_team_lifecycle = unavailable_reason.map_or(
        ExperimentalSessionOperationAvailability::Available,
        |reason| ExperimentalSessionOperationAvailability::Unavailable { reason },
    );
    ExperimentalSessionView {
        identity: ExperimentalSessionIdentity {
            session_id: session_id.to_string(),
            root_thread_id: Some(format!("root-{session_id}")),
        },
        domain_lifecycle: lifecycle,
        residency,
        operation_availability: ExperimentalSessionOperations {
            update_team_lifecycle: ExperimentalSessionOperation {
                availability: update_team_lifecycle,
                provenance: ExperimentalSessionFactProvenance::StateDbPrototype,
            },
            archive: ExperimentalSessionOperation {
                availability: ExperimentalSessionOperationAvailability::Unavailable {
                    reason: ExperimentalSessionOperationUnavailableReason::Unsupported,
                },
                provenance: ExperimentalSessionFactProvenance::Unavailable,
            },
            unarchive: ExperimentalSessionOperation {
                availability: ExperimentalSessionOperationAvailability::Unavailable {
                    reason: ExperimentalSessionOperationUnavailableReason::NotArchived,
                },
                provenance: ExperimentalSessionFactProvenance::StateDbPrototype,
            },
        },
        provenance: ExperimentalSessionProvenance {
            identity: ExperimentalSessionFactProvenance::StateDbPrototype,
            domain_lifecycle: ExperimentalSessionFactProvenance::PrototypeInput,
            residency: ExperimentalSessionFactProvenance::StateDbPrototype,
            team: ExperimentalSessionFactProvenance::Unavailable,
        },
        team: None,
    }
}

fn archived_view() -> ExperimentalSessionView {
    let mut view = view(
        "archived",
        ExperimentalSessionDomainLifecycle::Archived,
        ExperimentalSessionResidency::UnloadedNotResumable,
        None,
    );
    view.operation_availability
        .update_team_lifecycle
        .availability = ExperimentalSessionOperationAvailability::Unavailable {
        reason: ExperimentalSessionOperationUnavailableReason::Archived,
    };
    view.operation_availability.update_team_lifecycle.provenance =
        ExperimentalSessionFactProvenance::ThreadStore;
    view.operation_availability.unarchive.availability =
        ExperimentalSessionOperationAvailability::Available;
    view.operation_availability.unarchive.provenance =
        ExperimentalSessionFactProvenance::ThreadStore;
    view.provenance.identity = ExperimentalSessionFactProvenance::ThreadStore;
    view.provenance.domain_lifecycle = ExperimentalSessionFactProvenance::ThreadStore;
    view.provenance.residency = ExperimentalSessionFactProvenance::ThreadStore;
    view
}

fn loaded_owner_view() -> ExperimentalSessionView {
    let mut view = view(
        "loaded",
        ExperimentalSessionDomainLifecycle::Unknown,
        ExperimentalSessionResidency::LoadedOwner,
        None,
    );
    view.provenance.identity = ExperimentalSessionFactProvenance::LiveRuntime;
    view.provenance.domain_lifecycle = ExperimentalSessionFactProvenance::Unavailable;
    view.provenance.residency = ExperimentalSessionFactProvenance::LiveRuntime;
    view.operation_availability.update_team_lifecycle.provenance =
        ExperimentalSessionFactProvenance::LiveOwner;
    view.operation_availability.unarchive.provenance =
        ExperimentalSessionFactProvenance::ThreadStore;
    view.provenance.team = ExperimentalSessionFactProvenance::LiveOwner;
    view.team = Some(ExperimentalSessionTeamProjection {
        team_instance_id: "team-loaded".to_string(),
        revision: 7,
        viewer_thread_id: "root-loaded".to_string(),
        viewer_role: ExperimentalSessionTeamViewerRole::Root,
        omitted_participants: 2,
        events: vec![ExperimentalSessionTeamEventProjection {
            event_id: "event-a".to_string(),
            title: "prototype event".to_string(),
            versions: vec![ExperimentalSessionTeamVersionProjection {
                version_id: "version-a".to_string(),
                author_thread_id: "root-loaded".to_string(),
                producer_state: ExperimentalSessionTeamProducerState::Open,
                root_state: ExperimentalSessionTeamRootState::Pending,
                retired: false,
            }],
            omitted_versions: 3,
        }],
        omitted_events: 4,
    });
    view
}

#[test]
fn parses_all_explicit_commands() {
    assert!(SESSION_CONTROL_USAGE.starts_with("Usage: /session-control "));
    let mutation_status = render_mutation_status(
        "attempt not submitted",
        ViewFreshness::Stale,
        MutationCertainty::None,
    );
    assert!(mutation_status.contains("Run /session-control refresh"));
    assert!(!mutation_status.contains("Run /sessions refresh"));
    assert_eq!(
        ExperimentalSessionCommand::parse(""),
        Ok(ExperimentalSessionCommand::List)
    );
    assert!(matches!(
        ExperimentalSessionCommand::parse("read session-a closed"),
        Ok(ExperimentalSessionCommand::Read(_))
    ));
    assert_eq!(
        ExperimentalSessionCommand::parse("refresh"),
        Ok(ExperimentalSessionCommand::Refresh)
    );
    assert!(matches!(
        ExperimentalSessionCommand::parse("track root-a version-a open pending tracking"),
        Ok(ExperimentalSessionCommand::Track(_))
    ));
    assert_eq!(
        ExperimentalSessionCommand::parse("unarchive session-a"),
        Ok(ExperimentalSessionCommand::Unarchive {
            session_id: "session-a".to_string()
        })
    );
    assert_eq!(
        ExperimentalSessionCommand::parse("detach"),
        Ok(ExperimentalSessionCommand::Detach)
    );
    assert_eq!(
        ExperimentalSessionCommand::parse("track nope"),
        Err(SESSION_CONTROL_USAGE)
    );
}

#[test]
fn snapshots_loaded_unloaded_archived_owner_unavailable_and_stale_unknown() {
    let mut unloaded = view(
        "unloaded",
        ExperimentalSessionDomainLifecycle::Unknown,
        ExperimentalSessionResidency::UnloadedResumable,
        Some(ExperimentalSessionOperationUnavailableReason::OwnerUnavailable),
    );
    unloaded.provenance.identity = ExperimentalSessionFactProvenance::StateDbPrototype;
    unloaded.provenance.domain_lifecycle = ExperimentalSessionFactProvenance::Unavailable;
    unloaded.provenance.residency = ExperimentalSessionFactProvenance::StateDbPrototype;

    let mut owner_away = view(
        "owner-away",
        ExperimentalSessionDomainLifecycle::Unknown,
        ExperimentalSessionResidency::OwnerUnavailable,
        Some(ExperimentalSessionOperationUnavailableReason::OwnerUnavailable),
    );
    owner_away.provenance.identity = ExperimentalSessionFactProvenance::LiveRuntime;
    owner_away.provenance.domain_lifecycle = ExperimentalSessionFactProvenance::Unavailable;
    owner_away.provenance.residency = ExperimentalSessionFactProvenance::LiveRuntime;
    owner_away
        .operation_availability
        .update_team_lifecycle
        .provenance = ExperimentalSessionFactProvenance::LiveRuntime;
    owner_away.operation_availability.unarchive.provenance =
        ExperimentalSessionFactProvenance::ThreadStore;

    let cases = [loaded_owner_view(), unloaded, archived_view(), owner_away];
    let rendered = cases
        .iter()
        .map(|case| render_projection(case, ViewFreshness::Fresh, MutationCertainty::None))
        .collect::<Vec<_>>()
        .join("\n---\n");
    insta::assert_snapshot!("experimental_session_projection_gallery", rendered);
    insta::assert_snapshot!(
        "experimental_session_stale_result_unknown",
        render_projection(&cases[0], ViewFreshness::Stale, MutationCertainty::Unknown,)
    );
}

#[test]
fn snapshots_prototype_terminal_and_uncertain_lifecycles_without_claiming_closed() {
    let rendered = [
        ExperimentalSessionDomainLifecycle::Closing,
        ExperimentalSessionDomainLifecycle::Closed,
        ExperimentalSessionDomainLifecycle::Failed,
        ExperimentalSessionDomainLifecycle::Partial,
        ExperimentalSessionDomainLifecycle::Unknown,
    ]
    .into_iter()
    .map(|lifecycle| {
        let mut prototype = view(
            "prototype",
            lifecycle,
            ExperimentalSessionResidency::UnloadedResumable,
            Some(ExperimentalSessionOperationUnavailableReason::OwnerUnavailable),
        );
        prototype.provenance.identity = ExperimentalSessionFactProvenance::ThreadStore;
        prototype.provenance.residency = ExperimentalSessionFactProvenance::ThreadStore;
        prototype
            .operation_availability
            .update_team_lifecycle
            .provenance = ExperimentalSessionFactProvenance::ThreadStore;
        prototype.operation_availability.unarchive.provenance =
            ExperimentalSessionFactProvenance::ThreadStore;
        render_projection(&prototype, ViewFreshness::Fresh, MutationCertainty::None)
    })
    .collect::<Vec<_>>()
    .join("\n---\n");
    insta::assert_snapshot!("experimental_session_prototype_lifecycle_gallery", rendered);
}

#[test]
fn detach_copy_explicitly_disclaims_lifecycle_change() {
    insta::assert_snapshot!(render_detached(), @"Session control prototype detached; Team lifecycle was not changed.");
}
