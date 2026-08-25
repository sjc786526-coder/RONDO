use super::*;
use crate::config::test_config;
use crate::thread_manager::StartThreadOptions;
use crate::thread_manager::ThreadManager;
use codex_features::Feature;
use codex_login::CodexAuth;
use codex_team_state::PublishOutcome;
use codex_team_state::PublishRequest;
use codex_team_state::PublishTarget;
use codex_team_state::Submission;
use core_test_support::PathExt;
use std::sync::Arc;
use tempfile::tempdir;

fn team() -> (TeamStateHandle, ThreadId, ThreadId) {
    let team = TeamStateHandle::default();
    let root = ThreadId::new();
    let member = ThreadId::new();
    team.register_participant(root, ParticipantRole::Root, "/root".to_string());
    team.register_participant(member, ParticipantRole::Member, "/root/member".to_string());
    (team, root, member)
}

fn publish_new(
    team: &TeamStateHandle,
    actor: ThreadId,
    request_id: &str,
    title: &str,
) -> PublishOutcome {
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

fn publish_append(
    team: &TeamStateHandle,
    actor: ThreadId,
    request_id: &str,
    event_id: codex_team_state::EventId,
) -> PublishOutcome {
    team.publish(
        actor,
        &Submission {
            based_on: team.revision(),
            request_id: request_id.to_string(),
        },
        PublishRequest {
            target: PublishTarget::ExistingEvent { event_id },
            summary: format!("summary {request_id}"),
            handoff: None,
        },
    )
    .unwrap_or_else(|error| panic!("test append should succeed: {error}"))
}

#[test]
fn bounded_projection_reports_omissions_and_keeps_the_latest_state() {
    let (team, root, _) = team();
    for index in 0..MAX_PROJECTED_PARTICIPANTS {
        team.register_participant(
            ThreadId::new(),
            ParticipantRole::Member,
            format!("/root/member-{index}"),
        );
    }

    let mut published = Vec::new();
    for index in 0..=MAX_PROJECTED_EVENTS {
        published.push(publish_new(
            &team,
            root,
            &format!("event-{index}"),
            &format!("event {index}"),
        ));
    }
    let newest_event = published
        .last()
        .map(|outcome| outcome.event_id)
        .unwrap_or_else(|| panic!("the test publishes at least one event"));
    let mut newest_version = published
        .last()
        .map(|outcome| outcome.version_id)
        .unwrap_or_else(|| panic!("the test publishes at least one version"));
    for index in 1..=MAX_PROJECTED_VERSIONS_PER_EVENT {
        newest_version =
            publish_append(&team, root, &format!("append-{index}"), newest_event).version_id;
    }

    let snapshot = team
        .snapshot_for(root)
        .unwrap_or_else(|error| panic!("root snapshot should succeed: {error}"));
    let projection = bounded_projection(&team, snapshot, root);

    assert_eq!(projection.root_thread_id, root);
    assert_eq!(projection.participants.len(), MAX_PROJECTED_PARTICIPANTS);
    assert_eq!(projection.omitted_participants, 2);
    assert_eq!(projection.participants[0].thread_id, root);
    assert_eq!(projection.events.len(), MAX_PROJECTED_EVENTS);
    assert_eq!(projection.omitted_events, 1);
    let newest = projection
        .events
        .last()
        .unwrap_or_else(|| panic!("newest event is retained"));
    assert_eq!(newest.id, newest_event.to_string());
    assert_eq!(newest.versions.len(), MAX_PROJECTED_VERSIONS_PER_EVENT);
    assert_eq!(newest.omitted_versions, 1);
    let newest_version = newest_version.to_string();
    assert_eq!(
        newest.versions.last().map(|version| version.id.as_str()),
        Some(newest_version.as_str())
    );
}

#[test]
fn lifecycle_delegate_enforces_root_role_and_maps_stale_preconditions() {
    let (team, root, member) = team();
    let published = publish_new(&team, member, "member-version", "finding");
    let params = ExperimentalSessionControlSetRootStateParams {
        version_id: published.version_id.to_string(),
        expected_producer_state: ExperimentalSessionControlProducerState::Open,
        expected_root_state: ExperimentalSessionControlRootState::Pending,
        next_root_state: ExperimentalSessionControlRootState::Tracking,
    };

    let non_root_error = match set_root_state_on_team(&team, member, params.clone()) {
        Err(error) => error,
        Ok(_) => panic!("a member must not own root lifecycle state"),
    };
    assert!(matches!(
        non_root_error,
        ExperimentalSessionControlError::NotPermitted { .. }
    ));

    let outcome = set_root_state_on_team(&team, root, params.clone())
        .unwrap_or_else(|error| panic!("root mutation should succeed: {error}"));
    assert!(outcome.changed);
    assert_eq!(outcome.updated.author, member);
    assert_eq!(
        outcome.updated.root_state,
        ExperimentalSessionControlRootState::Tracking
    );
    assert_eq!(outcome.projection.revision, outcome.mutation_revision);

    let conflict = match set_root_state_on_team(&team, root, params) {
        Err(error) => error,
        Ok(_) => panic!("the stale expected root state must be rejected"),
    };
    assert_eq!(
        conflict,
        ExperimentalSessionControlError::LifecycleConflict {
            current: ExperimentalSessionControlLifecycle {
                version_id: published.version_id.to_string(),
                producer_state: ExperimentalSessionControlProducerState::Open,
                root_state: ExperimentalSessionControlRootState::Tracking,
            },
        }
    );
}

#[test]
fn lifecycle_delegate_rejects_a_well_formed_unknown_version() {
    let (team, root, _) = team();
    let seed = publish_new(&team, root, "seed", "seed");
    let version_id = format!("ver-999.999-{}", seed.version_id.instance());

    let error = match set_root_state_on_team(
        &team,
        root,
        ExperimentalSessionControlSetRootStateParams {
            version_id,
            expected_producer_state: ExperimentalSessionControlProducerState::Open,
            expected_root_state: ExperimentalSessionControlRootState::Pending,
            next_root_state: ExperimentalSessionControlRootState::Tracking,
        },
    ) {
        Err(error) => error,
        Ok(_) => panic!("a reference outside the root snapshot must fail closed"),
    };

    assert_eq!(
        error,
        ExperimentalSessionControlError::UnknownReference {
            reference: format!("evt-999-{}", seed.version_id.instance()),
        }
    );
}

#[tokio::test]
async fn stopped_but_still_mapped_root_is_not_an_online_owner() {
    let temp_dir = tempdir().expect("tempdir");
    let mut config = test_config().await;
    config.codex_home = temp_dir.path().join("codex-home").abs();
    config.cwd = config.codex_home.abs();
    std::fs::create_dir_all(&config.codex_home).expect("create codex home");
    let _ = config.features.enable(Feature::MultiAgentV2);
    config.multi_agent_v2.team_state_enabled = true;
    let manager = ThreadManager::with_models_provider_and_home_for_tests(
        CodexAuth::from_api_key("dummy"),
        config.model_provider.clone(),
        config.codex_home.to_path_buf(),
        Arc::new(codex_exec_server::EnvironmentManager::default_for_tests()),
    );
    let root = manager
        .start_thread(StartThreadOptions::new(config))
        .await
        .expect("start root");

    root.thread
        .experimental_session_control_team_projection()
        .await
        .expect("running root should own its canonical Team");
    root.thread
        .shutdown_and_wait()
        .await
        .expect("shutdown root while leaving the map entry in place");
    assert!(
        manager.get_thread(root.thread_id).await.is_ok(),
        "the regression requires a dead resident that is still mapped"
    );
    assert!(!root.thread.is_running());

    let projection_error = root
        .thread
        .experimental_session_control_team_projection()
        .await
        .expect_err("dead resident must not project as a loaded owner");
    assert_eq!(
        projection_error,
        ExperimentalSessionControlError::OwnerUnavailable {
            thread_id: root.thread_id,
        }
    );

    let mutation_error = root
        .thread
        .experimental_session_control_set_root_state(ExperimentalSessionControlSetRootStateParams {
            version_id: "not-a-version".to_string(),
            expected_producer_state: ExperimentalSessionControlProducerState::Open,
            expected_root_state: ExperimentalSessionControlRootState::Pending,
            next_root_state: ExperimentalSessionControlRootState::Tracking,
        })
        .await
        .expect_err("dead resident must fail before parsing or mutating a Team target");
    assert_eq!(
        mutation_error,
        ExperimentalSessionControlError::OwnerUnavailable {
            thread_id: root.thread_id,
        }
    );
}
