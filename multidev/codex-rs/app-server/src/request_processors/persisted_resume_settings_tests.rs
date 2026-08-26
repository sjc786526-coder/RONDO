use super::persisted_resume_settings::PersistedResumeSettings;
use super::persisted_resume_settings::latest_persisted_resume_settings;
use super::persisted_resume_settings::merge_persisted_thread_settings;
use codex_core::config::ConfigOverrides;
use codex_protocol::config_types::ApprovalsReviewer;
use codex_protocol::config_types::CollaborationMode;
use codex_protocol::config_types::ModeKind;
use codex_protocol::config_types::ReasoningSummary;
use codex_protocol::config_types::Settings;
use codex_protocol::models::ActivePermissionProfile;
use codex_protocol::models::PermissionProfile;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::RolloutItem;
use codex_protocol::protocol::SandboxPolicy;
use codex_protocol::protocol::ThreadSettingsAppliedEvent;
use codex_protocol::protocol::ThreadSettingsSnapshot;
use codex_protocol::protocol::TurnContextItem;
use codex_protocol::protocol::TurnStartedEvent;
use codex_protocol::protocol::WriterWorkspaceBinding;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::collections::HashMap;

fn cwd() -> AbsolutePathBuf {
    AbsolutePathBuf::try_from(std::env::current_dir().expect("current directory"))
        .expect("absolute current directory")
}

fn settings_item(
    approval_policy: AskForApproval,
    approvals_reviewer: ApprovalsReviewer,
    active_permission_profile_id: Option<&str>,
) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(
        ThreadSettingsAppliedEvent {
            thread_settings: ThreadSettingsSnapshot {
                model: "gpt-5".to_string(),
                model_provider_id: "openai".to_string(),
                service_tier: None,
                approval_policy,
                approvals_reviewer,
                permission_profile: PermissionProfile::read_only(),
                active_permission_profile: active_permission_profile_id
                    .map(ActivePermissionProfile::new),
                cwd: cwd(),
                reasoning_effort: None,
                reasoning_summary: None,
                personality: None,
                collaboration_mode: CollaborationMode {
                    mode: ModeKind::Default,
                    settings: Settings {
                        model: "gpt-5".to_string(),
                        reasoning_effort: None,
                        developer_instructions: None,
                    },
                },
                writer_workspace_binding: None,
                writer_workspace_authority_roots: None,
            },
        },
    ))
}

fn turn_started_item(turn_id: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnStarted(TurnStartedEvent {
        turn_id: turn_id.to_string(),
        trace_id: None,
        started_at: None,
        model_context_window: None,
        collaboration_mode_kind: ModeKind::Default,
    }))
}

fn turn_context_item(
    turn_id: &str,
    approval_policy: AskForApproval,
    approvals_reviewer: Option<ApprovalsReviewer>,
    active_permission_profile_id: Option<Option<&str>>,
) -> RolloutItem {
    RolloutItem::TurnContext(TurnContextItem {
        turn_id: Some(turn_id.to_string()),
        cwd: cwd(),
        workspace_roots: None,
        current_date: None,
        timezone: None,
        approval_policy,
        approvals_reviewer,
        sandbox_policy: SandboxPolicy::new_read_only_policy(),
        permission_profile: Some(PermissionProfile::read_only()),
        active_permission_profile: active_permission_profile_id
            .map(|profile_id| profile_id.map(ActivePermissionProfile::new)),
        network: None,
        file_system_sandbox_policy: None,
        model: "gpt-5".to_string(),
        comp_hash: None,
        personality: None,
        collaboration_mode: None,
        multi_agent_version: None,
        multi_agent_mode: None,
        realtime_active: None,
        effort: None,
        summary: ReasoningSummary::Auto,
    })
}

#[test]
fn latest_settings_snapshot_wins() {
    let history = vec![
        settings_item(AskForApproval::Never, ApprovalsReviewer::User, Some("old")),
        settings_item(
            AskForApproval::OnRequest,
            ApprovalsReviewer::AutoReview,
            Some("dev"),
        ),
    ];

    assert_eq!(
        latest_persisted_resume_settings(&history),
        Some(PersistedResumeSettings {
            approval_policy: AskForApproval::OnRequest,
            approvals_reviewer: Some(ApprovalsReviewer::AutoReview),
            active_permission_profile_id: Some(Some("dev".to_string())),
            writer_workspace_authority_roots: None,
        })
    );
}

#[test]
fn legacy_turn_context_does_not_revive_older_identity() {
    let history = vec![
        settings_item(
            AskForApproval::Never,
            ApprovalsReviewer::AutoReview,
            Some("dev"),
        ),
        turn_context_item(
            "turn-2",
            AskForApproval::OnRequest,
            Some(ApprovalsReviewer::User),
            /* active_permission_profile_id */ None,
        ),
    ];

    assert_eq!(
        latest_persisted_resume_settings(&history),
        Some(PersistedResumeSettings {
            approval_policy: AskForApproval::OnRequest,
            approvals_reviewer: Some(ApprovalsReviewer::User),
            active_permission_profile_id: None,
            writer_workspace_authority_roots: None,
        })
    );
}

#[test]
fn explicit_identity_clear_does_not_revive_older_profile() {
    let history = vec![
        settings_item(
            AskForApproval::Never,
            ApprovalsReviewer::AutoReview,
            Some("dev"),
        ),
        turn_context_item(
            "turn-2",
            AskForApproval::OnRequest,
            Some(ApprovalsReviewer::User),
            Some(None),
        ),
    ];

    assert_eq!(
        latest_persisted_resume_settings(&history)
            .expect("persisted settings")
            .active_permission_profile_id,
        Some(None)
    );
}

#[test]
fn settings_applied_during_turn_wins_over_stale_compaction_context() {
    let history = vec![
        turn_started_item("turn-1"),
        settings_item(
            AskForApproval::Never,
            ApprovalsReviewer::AutoReview,
            Some("dev"),
        ),
        turn_context_item(
            "turn-1",
            AskForApproval::OnRequest,
            Some(ApprovalsReviewer::User),
            Some(Some("stale")),
        ),
    ];

    assert_eq!(
        latest_persisted_resume_settings(&history),
        Some(PersistedResumeSettings {
            approval_policy: AskForApproval::Never,
            approvals_reviewer: Some(ApprovalsReviewer::AutoReview),
            active_permission_profile_id: Some(Some("dev".to_string())),
            writer_workspace_authority_roots: None,
        })
    );
}

#[test]
fn later_turn_context_wins_over_earlier_turn_update() {
    let history = vec![
        turn_started_item("turn-1"),
        settings_item(
            AskForApproval::Never,
            ApprovalsReviewer::AutoReview,
            Some("dev"),
        ),
        turn_context_item(
            "turn-1",
            AskForApproval::OnRequest,
            Some(ApprovalsReviewer::User),
            Some(Some("stale")),
        ),
        turn_started_item("turn-2"),
        turn_context_item(
            "turn-2",
            AskForApproval::UnlessTrusted,
            Some(ApprovalsReviewer::User),
            Some(Some("current")),
        ),
    ];

    assert_eq!(
        latest_persisted_resume_settings(&history),
        Some(PersistedResumeSettings {
            approval_policy: AskForApproval::UnlessTrusted,
            approvals_reviewer: Some(ApprovalsReviewer::User),
            active_permission_profile_id: Some(Some("current".to_string())),
            writer_workspace_authority_roots: None,
        })
    );
}

#[test]
fn raw_request_overrides_stay_ahead_of_persisted_settings() {
    let persisted = PersistedResumeSettings {
        approval_policy: AskForApproval::Never,
        approvals_reviewer: Some(ApprovalsReviewer::AutoReview),
        active_permission_profile_id: Some(Some("persisted".to_string())),
        writer_workspace_authority_roots: None,
    };
    let request_overrides = HashMap::from([
        ("approval_policy".to_string(), json!("on-request")),
        ("approvals_reviewer".to_string(), json!("user")),
        ("default_permissions".to_string(), json!(":read-only")),
    ]);
    let mut typesafe_overrides = ConfigOverrides::default();

    merge_persisted_thread_settings(persisted, Some(&request_overrides), &mut typesafe_overrides);

    assert_eq!(typesafe_overrides.approval_policy, None);
    assert_eq!(typesafe_overrides.approvals_reviewer, None);
    assert_eq!(typesafe_overrides.persisted_permission_profile_id, None);
}

#[test]
fn writer_authority_roots_resume_but_explicit_runtime_roots_win() {
    let root = cwd();
    let sibling = root.join("writer-sibling");
    let mut item = settings_item(
        AskForApproval::OnRequest,
        ApprovalsReviewer::User,
        Some(":workspace"),
    );
    let RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) = &mut item else {
        panic!("settings helper must return a settings event");
    };
    event.thread_settings.writer_workspace_binding = Some(WriterWorkspaceBinding {
        generation: 1,
        worktree_root: root.clone(),
        git_dir: root.join(".git/worktrees/writer"),
        common_dir: root.join(".git"),
        repository_root: root.clone(),
        environment_id: "local".to_string(),
    });
    event.thread_settings.writer_workspace_authority_roots =
        Some(vec![root.clone(), sibling.clone()]);

    let persisted = latest_persisted_resume_settings(&[item]).expect("persisted settings");
    let mut restored = ConfigOverrides::default();
    merge_persisted_thread_settings(persisted.clone(), None, &mut restored);
    assert_eq!(restored.workspace_roots, Some(vec![root, sibling]));

    let explicit = cwd().join("explicit");
    let mut overridden = ConfigOverrides {
        workspace_roots: Some(vec![explicit.clone()]),
        ..Default::default()
    };
    merge_persisted_thread_settings(persisted, None, &mut overridden);
    assert_eq!(overridden.workspace_roots, Some(vec![explicit]));
}

#[test]
fn newer_unbound_settings_tombstone_older_writer_authority_roots() {
    let root = cwd();
    let mut bound = settings_item(
        AskForApproval::OnRequest,
        ApprovalsReviewer::User,
        Some(":workspace"),
    );
    let RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) = &mut bound else {
        panic!("settings helper must return a settings event");
    };
    event.thread_settings.writer_workspace_binding = Some(WriterWorkspaceBinding {
        generation: 1,
        worktree_root: root.clone(),
        git_dir: root.join(".git/worktrees/writer"),
        common_dir: root.join(".git"),
        repository_root: root.clone(),
        environment_id: "local".to_string(),
    });
    event.thread_settings.writer_workspace_authority_roots = Some(vec![root]);
    let unbound = settings_item(
        AskForApproval::OnRequest,
        ApprovalsReviewer::User,
        Some(":workspace"),
    );

    assert_eq!(
        latest_persisted_resume_settings(&[bound, unbound])
            .expect("persisted settings")
            .writer_workspace_authority_roots,
        None
    );
}
