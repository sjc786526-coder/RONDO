use super::*;
use codex_protocol::protocol::DurableTeamSessionMeta;
use codex_team_state::ParticipantRole;
use codex_team_state::PublishRequest;
use codex_team_state::PublishTarget;
use codex_team_state::Submission;
use codex_team_state::TeamStateHandle;
use pretty_assertions::assert_eq;
use tempfile::tempdir;

fn publish_new(
    team: &TeamStateHandle,
    actor: ThreadId,
    request_id: &str,
    title: &str,
) -> codex_team_state::PublishOutcome {
    team.publish(
        actor,
        &Submission {
            based_on: team.revision(),
            request_id: request_id.to_string(),
        },
        PublishRequest {
            target: PublishTarget::NewEvent {
                title: title.to_string(),
            },
            summary: format!("summary {request_id}"),
            handoff: None,
        },
    )
    .unwrap_or_else(|error| panic!("test publication should succeed: {error}"))
}

#[test]
fn bounded_projection_keeps_commit_generation_separate_from_team_revision() {
    let team = TeamStateHandle::default();
    let root = ThreadId::new();
    let member = ThreadId::new();
    team.register_participant(root, ParticipantRole::Root, "/root".to_string());
    team.register_participant(member, ParticipantRole::Member, "/root/member".to_string());
    let published = publish_new(&team, member, "member-version", "finding");
    let snapshot = team
        .snapshot_for(root)
        .unwrap_or_else(|error| panic!("root snapshot should succeed: {error}"));
    let revision = snapshot.revision.get();
    let team_instance = snapshot.instance.to_string();
    let commit_generation = revision + 40;
    let commit_fingerprint = format!("sha256:{}", "ab".repeat(32));

    let projection = bounded_projection(
        &team,
        snapshot,
        DurableTeamIdentity::new(SessionId::from(root), root),
        commit_generation,
        commit_fingerprint.clone(),
    );

    assert_eq!(projection.session_id, SessionId::from(root));
    assert_eq!(projection.root_thread_id, root);
    assert_eq!(projection.team_instance, team_instance);
    assert_eq!(projection.commit_generation, commit_generation);
    assert_eq!(projection.commit_fingerprint, commit_fingerprint);
    assert_eq!(projection.revision, revision);
    assert_eq!(
        projection.participants,
        vec![
            DurableSessionParticipant {
                thread_id: root,
                role: DurableSessionTeamRole::Root,
                label: "/root".to_string(),
            },
            DurableSessionParticipant {
                thread_id: member,
                role: DurableSessionTeamRole::Member,
                label: "/root/member".to_string(),
            },
        ]
    );
    assert_eq!(projection.omitted_participants, 0);
    assert_eq!(projection.events.len(), 1);
    assert_eq!(projection.omitted_events, 0);
    assert_eq!(projection.events[0].versions.len(), 1);
    assert_eq!(
        projection.events[0].versions[0].id,
        published.version_id.to_string()
    );
}

#[test]
fn commit_fingerprint_has_a_stable_wire_shape() {
    assert_eq!(
        format_commit_fingerprint([0xab; 32]),
        format!("sha256:{}", "ab".repeat(32))
    );
}

#[test]
fn canonical_session_without_durable_marker_is_not_recast_as_durable() {
    let home = tempdir().expect("tempdir");
    let root = ThreadId::new();
    let session_meta = SessionMeta {
        session_id: root.into(),
        id: root,
        ..SessionMeta::default()
    };

    assert_eq!(
        project_committed_durable_session(home.path(), &session_meta),
        Err(DurableSessionReadError::NotDurable)
    );
}

#[test]
fn missing_snapshot_is_distinct_from_an_unavailable_source() {
    let home = tempdir().expect("tempdir");
    let root = ThreadId::new();
    let session_id = SessionId::from(root);
    let session_meta = SessionMeta {
        session_id,
        id: root,
        durable_team: Some(DurableTeamSessionMeta::current(session_id, root)),
        ..SessionMeta::default()
    };

    assert_eq!(
        project_committed_durable_session(home.path(), &session_meta),
        Err(DurableSessionReadError::SnapshotMissing)
    );
}

#[test]
fn marker_version_failure_is_not_reported_as_a_snapshot_failure() {
    let home = tempdir().expect("tempdir");
    let root = ThreadId::new();
    let session_id = SessionId::from(root);
    let mut marker = DurableTeamSessionMeta::current(session_id, root);
    marker.version += 1;
    let session_meta = SessionMeta {
        session_id,
        id: root,
        durable_team: Some(marker),
        ..SessionMeta::default()
    };

    assert_eq!(
        project_committed_durable_session(home.path(), &session_meta),
        Err(DurableSessionReadError::MarkerUnsupportedVersion {
            found: marker.version,
            supported: DurableTeamSessionMeta::CURRENT_VERSION,
        })
    );
    assert_eq!(
        map_snapshot_error(TeamDurabilityError::UnsupportedVersion {
            found: marker.version,
            supported: DurableTeamSessionMeta::CURRENT_VERSION,
        }),
        DurableSessionReadError::UnsupportedVersion {
            found: marker.version,
            supported: DurableTeamSessionMeta::CURRENT_VERSION,
        }
    );
}

#[test]
fn marker_identity_failure_is_not_reported_as_a_snapshot_failure() {
    let home = tempdir().expect("tempdir");
    let root = ThreadId::new();
    let other_root = ThreadId::new();
    let session_id = SessionId::from(root);
    let session_meta = SessionMeta {
        session_id,
        id: root,
        durable_team: Some(DurableTeamSessionMeta::current(session_id, other_root)),
        ..SessionMeta::default()
    };

    assert_eq!(
        project_committed_durable_session(home.path(), &session_meta),
        Err(DurableSessionReadError::MarkerIdentityMismatch)
    );
    assert_eq!(
        map_snapshot_error(TeamDurabilityError::IdentityMismatch),
        DurableSessionReadError::IdentityMismatch
    );
}
