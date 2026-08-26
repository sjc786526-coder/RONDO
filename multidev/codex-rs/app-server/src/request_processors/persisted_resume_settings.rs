use codex_core::ThreadConfigSnapshot;
use codex_core::config::ConfigOverrides;
use codex_protocol::config_types::ApprovalsReviewer;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::RolloutItem;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::Value;
use std::collections::HashMap;

/// The resumable settings carried by canonical rollout history.
///
/// `active_permission_profile_id` is presence-aware: `None` means no carrier
/// in the history knew how to record identity, `Some(None)` is an explicit
/// clear, and `Some(Some(id))` is a profile that must be resolved again.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct PersistedResumeSettings {
    pub(super) approval_policy: AskForApproval,
    pub(super) approvals_reviewer: Option<ApprovalsReviewer>,
    pub(super) active_permission_profile_id: Option<Option<String>>,
    pub(super) writer_workspace_authority_roots: Option<Vec<AbsolutePathBuf>>,
}

impl From<ThreadConfigSnapshot> for PersistedResumeSettings {
    fn from(snapshot: ThreadConfigSnapshot) -> Self {
        Self {
            approval_policy: snapshot.approval_policy,
            approvals_reviewer: Some(snapshot.approvals_reviewer),
            active_permission_profile_id: Some(
                snapshot.active_permission_profile.map(|profile| profile.id),
            ),
            writer_workspace_authority_roots: snapshot.writer_workspace_authority_roots,
        }
    }
}

fn settings_applied_during_turn<'a>(
    history: &'a [RolloutItem],
    turn_context_index: usize,
    turn_id: &str,
) -> Option<&'a codex_protocol::protocol::ThreadSettingsSnapshot> {
    let turn_start = history[..turn_context_index].iter().rposition(|item| {
        matches!(
            item,
            RolloutItem::EventMsg(EventMsg::TurnStarted(event))
                if event.turn_id == turn_id
        )
    })?;

    history[turn_start + 1..turn_context_index]
        .iter()
        .rev()
        .find_map(|item| match item {
            RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) => {
                Some(&event.thread_settings)
            }
            _ => None,
        })
}

pub(super) fn latest_persisted_resume_settings(
    history: &[RolloutItem],
) -> Option<PersistedResumeSettings> {
    let approval_policy =
        history
            .iter()
            .enumerate()
            .rev()
            .find_map(|(index, item)| match item {
                RolloutItem::TurnContext(turn_context) => Some(
                    turn_context
                        .turn_id
                        .as_deref()
                        .and_then(|turn_id| settings_applied_during_turn(history, index, turn_id))
                        .map_or(turn_context.approval_policy, |settings| {
                            settings.approval_policy
                        }),
                ),
                RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) => {
                    Some(event.thread_settings.approval_policy)
                }
                _ => None,
            })?;

    let approvals_reviewer =
        history
            .iter()
            .enumerate()
            .rev()
            .find_map(|(index, item)| match item {
                RolloutItem::TurnContext(turn_context) => turn_context
                    .turn_id
                    .as_deref()
                    .and_then(|turn_id| settings_applied_during_turn(history, index, turn_id))
                    .map(|settings| settings.approvals_reviewer)
                    .or(turn_context.approvals_reviewer),
                RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) => {
                    Some(event.thread_settings.approvals_reviewer)
                }
                _ => None,
            });

    let mut active_permission_profile_id = None;
    for (index, item) in history.iter().enumerate().rev() {
        match item {
            RolloutItem::TurnContext(turn_context) => {
                active_permission_profile_id = if let Some(settings) = turn_context
                    .turn_id
                    .as_deref()
                    .and_then(|turn_id| settings_applied_during_turn(history, index, turn_id))
                {
                    Some(
                        settings
                            .active_permission_profile
                            .as_ref()
                            .map(|profile| profile.id.clone()),
                    )
                } else {
                    turn_context
                        .active_permission_profile
                        .as_ref()
                        .map(|profile| {
                            profile
                                .as_ref()
                                .map(|active_profile| active_profile.id.clone())
                        })
                };
                // Even a legacy TurnContext with no identity field is the
                // latest settings boundary. It uses current config rather than
                // reviving an older profile selection.
                break;
            }
            RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) => {
                active_permission_profile_id = Some(
                    event
                        .thread_settings
                        .active_permission_profile
                        .as_ref()
                        .map(|profile| profile.id.clone()),
                );
                break;
            }
            _ => {}
        }
    }

    let writer_workspace_authority_roots = history
        .iter()
        .rev()
        .find_map(|item| match item {
            RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) => {
                Some(&event.thread_settings)
            }
            _ => None,
        })
        .and_then(|settings| {
            settings
                .writer_workspace_binding
                .as_ref()
                .and(settings.writer_workspace_authority_roots.clone())
        });

    Some(PersistedResumeSettings {
        approval_policy,
        approvals_reviewer,
        active_permission_profile_id,
        writer_workspace_authority_roots,
    })
}

fn raw_override_has(request_overrides: Option<&HashMap<String, Value>>, key: &str) -> bool {
    request_overrides.is_some_and(|overrides| overrides.contains_key(key))
}

pub(super) fn has_permission_override(
    request_overrides: Option<&HashMap<String, Value>>,
    typesafe_overrides: &ConfigOverrides,
) -> bool {
    typesafe_overrides.sandbox_mode.is_some()
        || typesafe_overrides.permission_profile.is_some()
        || typesafe_overrides.default_permissions.is_some()
        || raw_override_has(request_overrides, "sandbox_mode")
        || raw_override_has(request_overrides, "default_permissions")
}

pub(super) fn merge_persisted_thread_settings(
    persisted_settings: PersistedResumeSettings,
    request_overrides: Option<&HashMap<String, Value>>,
    typesafe_overrides: &mut ConfigOverrides,
) {
    if typesafe_overrides.approval_policy.is_none()
        && !raw_override_has(request_overrides, "approval_policy")
    {
        typesafe_overrides.approval_policy = Some(persisted_settings.approval_policy);
    }
    if typesafe_overrides.approvals_reviewer.is_none()
        && !raw_override_has(request_overrides, "approvals_reviewer")
    {
        typesafe_overrides.approvals_reviewer = persisted_settings.approvals_reviewer;
    }
    if !has_permission_override(request_overrides, typesafe_overrides) {
        typesafe_overrides.persisted_permission_profile_id =
            persisted_settings.active_permission_profile_id.flatten();
    }
    if typesafe_overrides.workspace_roots.is_none()
        && !raw_override_has(request_overrides, "workspace_roots")
    {
        typesafe_overrides.workspace_roots = persisted_settings.writer_workspace_authority_roots;
    }
}
