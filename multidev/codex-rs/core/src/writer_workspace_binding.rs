use codex_exec_server::EnvironmentManager;
use codex_file_system::ExecutorFileSystem;
use codex_git_utils::LinkedWorktreeIdentity;
use codex_git_utils::resolve_linked_worktree_identity;
use codex_git_utils::resolve_root_git_project_for_trust;
use codex_protocol::models::AdditionalPermissionProfile;
use codex_protocol::models::PermissionProfile;
use codex_protocol::models::SandboxEnforcement;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::protocol::TurnEnvironmentSelection;
use codex_protocol::protocol::TurnEnvironmentSelections;
use codex_protocol::protocol::WriterWorkspaceBinding;
use codex_protocol::protocol::WriterWorkspaceBindingAvailability;
use codex_protocol::protocol::WriterWorkspaceBindingSnapshot;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_path_uri::PathUri;
use std::sync::Arc;
use thiserror::Error;

use crate::config::Config;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WriterWorkspaceBindingRequest {
    pub worktree_root: AbsolutePathBuf,
    pub environment_id: Option<String>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WriterWorkspaceBindingReplaceOutcome {
    Applied(WriterWorkspaceBindingSnapshot),
    Unknown {
        snapshot: WriterWorkspaceBindingSnapshot,
        message: String,
    },
}

#[derive(Clone, Debug)]
pub(crate) struct WriterWorkspaceBindingState {
    pub(crate) snapshot: WriterWorkspaceBindingSnapshot,
    execution_environments: TurnEnvironmentSelections,
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum WriterWorkspaceBindingError {
    #[error("writer workspace binding requires durable thread persistence")]
    EphemeralThread,
    #[error("writer workspace binding requires a configured local execution environment")]
    MissingLocalEnvironment,
    #[error("writer workspace binding environment `{0}` is not selected for this thread")]
    EnvironmentNotSelected(String),
    #[error("writer workspace binding environment `{0}` is remote")]
    RemoteEnvironment(String),
    #[error("writer workspace root must be an exact, canonical Git linked-worktree root")]
    InvalidLinkedWorktree,
    #[error("writer workspace binding must stay in the currently authorized Git repository")]
    RepositoryMismatch,
    #[error("writer workspace root is not an exact current workspace root")]
    WorkspaceRootMismatch,
    #[error("writer workspace binding requires a managed filesystem sandbox")]
    UnsupportedSandbox,
    #[error("current permission profile does not allow writes to the writer workspace root")]
    PermissionDenied,
    #[error("writer workspace binding identity changed")]
    IdentityChanged,
    #[error("writer workspace binding execution environment changed")]
    ExecutionEnvironmentChanged,
    #[error("writer external-write grants require existing canonical path targets")]
    InvalidExternalWriteTarget,
    #[error("writer external-write grant target changed after approval")]
    ExternalWriteTargetChanged,
}

/// Resolve every W1 write target before it reaches the reviewer.
///
/// Ordinary permission requests intentionally preserve logical symlinks. A bound writer cannot:
/// the sandbox resolves those links again when it starts, so a link retargeted while approval is
/// pending would otherwise change the approved object. W1 therefore asks the reviewer to approve
/// only existing physical targets. Callers that need to create a path can request its existing
/// parent directory.
pub(crate) async fn canonicalize_external_write_permissions(
    mut permissions: AdditionalPermissionProfile,
    fs: &dyn ExecutorFileSystem,
) -> Result<AdditionalPermissionProfile, WriterWorkspaceBindingError> {
    let Some(file_system) = permissions.file_system.as_mut() else {
        return Ok(permissions);
    };
    for entry in &mut file_system.entries {
        if !entry.access.can_write() {
            continue;
        }
        let FileSystemPath::Path { path } = &mut entry.path else {
            return Err(WriterWorkspaceBindingError::InvalidExternalWriteTarget);
        };
        let canonical = fs
            .canonicalize(&PathUri::from_abs_path(path), /*sandbox*/ None)
            .await
            .ok()
            .and_then(|path| path.to_abs_path().ok())
            .ok_or(WriterWorkspaceBindingError::InvalidExternalWriteTarget)?;
        *path = canonical;
    }
    Ok(permissions)
}

/// Revalidate the physical W1 targets immediately before a side effect.
pub(crate) async fn revalidate_external_write_permissions(
    permissions: &AdditionalPermissionProfile,
    fs: &dyn ExecutorFileSystem,
) -> Result<(), WriterWorkspaceBindingError> {
    let Some(file_system) = permissions.file_system.as_ref() else {
        return Ok(());
    };
    for entry in &file_system.entries {
        if !entry.access.can_write() {
            continue;
        }
        let FileSystemPath::Path { path } = &entry.path else {
            return Err(WriterWorkspaceBindingError::ExternalWriteTargetChanged);
        };
        let canonical = fs
            .canonicalize(&PathUri::from_abs_path(path), /*sandbox*/ None)
            .await
            .ok()
            .and_then(|path| path.to_abs_path().ok())
            .ok_or(WriterWorkspaceBindingError::ExternalWriteTargetChanged)?;
        if canonical != *path {
            return Err(WriterWorkspaceBindingError::ExternalWriteTargetChanged);
        }
    }
    Ok(())
}

impl WriterWorkspaceBindingState {
    pub(crate) fn available(binding: WriterWorkspaceBinding) -> Self {
        let execution_environments = execution_environments(&binding);
        Self {
            snapshot: WriterWorkspaceBindingSnapshot {
                binding,
                availability: WriterWorkspaceBindingAvailability::Available,
            },
            execution_environments,
        }
    }

    pub(crate) fn resumed(binding: WriterWorkspaceBinding) -> Self {
        let mut state = Self::available(binding);
        state.snapshot.availability = WriterWorkspaceBindingAvailability::Unavailable {
            reason: "writer workspace binding has not been revalidated".to_string(),
        };
        state
    }

    pub(crate) fn execution_environments(&self) -> &TurnEnvironmentSelections {
        &self.execution_environments
    }

    pub(crate) fn mark_available(&mut self) {
        self.snapshot.availability = WriterWorkspaceBindingAvailability::Available;
    }

    pub(crate) fn mark_unavailable(&mut self, error: &WriterWorkspaceBindingError) {
        self.snapshot.availability = WriterWorkspaceBindingAvailability::Unavailable {
            reason: error.to_string(),
        };
    }
}

pub(crate) async fn capture_initial_binding(
    request: WriterWorkspaceBindingRequest,
    config: &Config,
    authority_environments: &TurnEnvironmentSelections,
    environment_manager: &EnvironmentManager,
) -> Result<WriterWorkspaceBindingState, WriterWorkspaceBindingError> {
    if config.ephemeral {
        return Err(WriterWorkspaceBindingError::EphemeralThread);
    }
    let (selection, fs) = selected_local_environment(
        request.environment_id.as_deref(),
        authority_environments,
        environment_manager,
    )?;
    let identity = capture_identity(fs.as_ref(), &request.worktree_root).await?;
    validate_repository_for_initial_binding(fs.as_ref(), config, &identity).await?;
    validate_authority(
        &identity.worktree_root,
        config.permissions.permission_profile(),
        authority_workspace_roots(config, authority_environments, selection),
    )?;
    Ok(WriterWorkspaceBindingState::available(
        binding_from_identity(identity, selection.environment_id.clone(), 1),
    ))
}

pub(crate) async fn capture_replacement_binding(
    request: WriterWorkspaceBindingRequest,
    current: &WriterWorkspaceBinding,
    authority_profile: &PermissionProfile,
    authority_environments: &TurnEnvironmentSelections,
    authority_profile_workspace_roots: &[AbsolutePathBuf],
    environment_manager: &EnvironmentManager,
) -> Result<WriterWorkspaceBindingState, WriterWorkspaceBindingError> {
    let requested_environment_id = request
        .environment_id
        .as_deref()
        .unwrap_or(current.environment_id.as_str());
    let (selection, fs) = selected_local_environment(
        Some(requested_environment_id),
        authority_environments,
        environment_manager,
    )?;
    let identity = capture_identity(fs.as_ref(), &request.worktree_root).await?;
    if identity.repository_root != current.repository_root {
        return Err(WriterWorkspaceBindingError::RepositoryMismatch);
    }
    let mut roots = native_workspace_roots(selection);
    roots.extend(authority_profile_workspace_roots.iter().cloned());
    dedupe_paths(&mut roots);
    validate_authority(&identity.worktree_root, authority_profile, roots)?;
    Ok(WriterWorkspaceBindingState::available(
        binding_from_identity(
            identity,
            selection.environment_id.clone(),
            current.generation.saturating_add(1),
        ),
    ))
}

pub(crate) async fn revalidate_binding(
    state: &WriterWorkspaceBindingState,
    authority_profile: &PermissionProfile,
    authority_environments: &TurnEnvironmentSelections,
    authority_profile_workspace_roots: &[AbsolutePathBuf],
    environment_manager: &EnvironmentManager,
) -> Result<(), WriterWorkspaceBindingError> {
    let binding = &state.snapshot.binding;
    let (selection, fs) = selected_local_environment(
        Some(binding.environment_id.as_str()),
        authority_environments,
        environment_manager,
    )?;
    let identity = capture_identity(fs.as_ref(), &binding.worktree_root).await?;
    if binding_from_identity(identity, binding.environment_id.clone(), binding.generation)
        != *binding
    {
        return Err(WriterWorkspaceBindingError::IdentityChanged);
    }
    let mut roots = native_workspace_roots(selection);
    roots.extend(authority_profile_workspace_roots.iter().cloned());
    dedupe_paths(&mut roots);
    validate_authority(&binding.worktree_root, authority_profile, roots)?;
    let expected = execution_environments(binding);
    if state.execution_environments != expected {
        return Err(WriterWorkspaceBindingError::ExecutionEnvironmentChanged);
    }
    Ok(())
}

fn selected_local_environment<'a>(
    requested_environment_id: Option<&str>,
    authority_environments: &'a TurnEnvironmentSelections,
    environment_manager: &EnvironmentManager,
) -> Result<(&'a TurnEnvironmentSelection, Arc<dyn ExecutorFileSystem>), WriterWorkspaceBindingError>
{
    let selection = match requested_environment_id {
        Some(environment_id) => authority_environments
            .environments
            .iter()
            .find(|selection| selection.environment_id == environment_id)
            .ok_or_else(|| {
                WriterWorkspaceBindingError::EnvironmentNotSelected(environment_id.to_string())
            })?,
        None => authority_environments
            .environments
            .first()
            .ok_or(WriterWorkspaceBindingError::MissingLocalEnvironment)?,
    };
    let environment = environment_manager
        .get_environment(&selection.environment_id)
        .ok_or_else(|| {
            WriterWorkspaceBindingError::EnvironmentNotSelected(selection.environment_id.clone())
        })?;
    if environment.is_remote() {
        return Err(WriterWorkspaceBindingError::RemoteEnvironment(
            selection.environment_id.clone(),
        ));
    }
    Ok((selection, environment.get_filesystem()))
}

async fn capture_identity(
    fs: &dyn ExecutorFileSystem,
    worktree_root: &AbsolutePathBuf,
) -> Result<LinkedWorktreeIdentity, WriterWorkspaceBindingError> {
    let canonical = fs
        .canonicalize(
            &PathUri::from_abs_path(worktree_root),
            /*sandbox*/ None,
        )
        .await
        .ok()
        .and_then(|path| path.to_abs_path().ok())
        .ok_or(WriterWorkspaceBindingError::InvalidLinkedWorktree)?;
    if canonical != *worktree_root {
        return Err(WriterWorkspaceBindingError::InvalidLinkedWorktree);
    }
    resolve_linked_worktree_identity(fs, worktree_root)
        .await
        .ok_or(WriterWorkspaceBindingError::InvalidLinkedWorktree)
}

async fn validate_repository_for_initial_binding(
    fs: &dyn ExecutorFileSystem,
    config: &Config,
    identity: &LinkedWorktreeIdentity,
) -> Result<(), WriterWorkspaceBindingError> {
    let trust_root = resolve_root_git_project_for_trust(fs, &config.cwd)
        .await
        .ok_or(WriterWorkspaceBindingError::RepositoryMismatch)?;
    let trust_root = fs
        .canonicalize(&PathUri::from_abs_path(&trust_root), /*sandbox*/ None)
        .await
        .ok()
        .and_then(|path| path.to_abs_path().ok())
        .ok_or(WriterWorkspaceBindingError::RepositoryMismatch)?;
    (trust_root == identity.repository_root)
        .then_some(())
        .ok_or(WriterWorkspaceBindingError::RepositoryMismatch)
}

fn validate_authority(
    worktree_root: &AbsolutePathBuf,
    permission_profile: &PermissionProfile,
    workspace_roots: Vec<AbsolutePathBuf>,
) -> Result<(), WriterWorkspaceBindingError> {
    if !workspace_roots.iter().any(|root| root == worktree_root) {
        return Err(WriterWorkspaceBindingError::WorkspaceRootMismatch);
    }
    if permission_profile.enforcement() != SandboxEnforcement::Managed {
        return Err(WriterWorkspaceBindingError::UnsupportedSandbox);
    }
    let profile = permission_profile
        .clone()
        .materialize_project_roots_with_workspace_roots(&workspace_roots);
    profile
        .file_system_sandbox_policy()
        .can_write_path_with_cwd(worktree_root.as_path(), worktree_root.as_path())
        .then_some(())
        .ok_or(WriterWorkspaceBindingError::PermissionDenied)
}

fn authority_workspace_roots(
    config: &Config,
    authority_environments: &TurnEnvironmentSelections,
    selected: &TurnEnvironmentSelection,
) -> Vec<AbsolutePathBuf> {
    let mut roots = native_workspace_roots(selected);
    roots.extend(configured_authority_workspace_roots(config));
    for selection in &authority_environments.environments {
        roots.extend(native_workspace_roots(selection));
    }
    dedupe_paths(&mut roots);
    roots
}

pub(crate) fn configured_authority_workspace_roots(config: &Config) -> Vec<AbsolutePathBuf> {
    let mut roots = config.permissions.user_visible_workspace_roots().to_vec();
    roots.extend(config.permissions.profile_workspace_roots().iter().cloned());
    dedupe_paths(&mut roots);
    roots
}

fn native_workspace_roots(selection: &TurnEnvironmentSelection) -> Vec<AbsolutePathBuf> {
    selection
        .workspace_roots
        .iter()
        .filter_map(|root| root.to_abs_path().ok())
        .collect()
}

fn dedupe_paths(paths: &mut Vec<AbsolutePathBuf>) {
    let mut deduped = Vec::with_capacity(paths.len());
    for path in paths.drain(..) {
        if !deduped.iter().any(|existing| existing == &path) {
            deduped.push(path);
        }
    }
    *paths = deduped;
}

fn binding_from_identity(
    identity: LinkedWorktreeIdentity,
    environment_id: String,
    generation: u64,
) -> WriterWorkspaceBinding {
    WriterWorkspaceBinding {
        generation,
        worktree_root: identity.worktree_root,
        git_dir: identity.git_dir,
        common_dir: identity.common_dir,
        repository_root: identity.repository_root,
        environment_id,
    }
}

fn execution_environments(binding: &WriterWorkspaceBinding) -> TurnEnvironmentSelections {
    let root = PathUri::from_abs_path(&binding.worktree_root);
    TurnEnvironmentSelections::new(
        binding.worktree_root.clone(),
        vec![TurnEnvironmentSelection {
            environment_id: binding.environment_id.clone(),
            cwd: root.clone(),
            workspace_roots: vec![root],
        }],
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::PermissionProfileSnapshot;
    use crate::config::test_config;
    use codex_exec_server::LOCAL_ENVIRONMENT_ID;
    use codex_protocol::models::ActivePermissionProfile;
    use codex_protocol::models::FileSystemPermissions;
    use std::path::Path;
    use std::process::Command;
    use tempfile::TempDir;

    fn run_git(repo: &Path, args: &[&str]) {
        let output = Command::new("git")
            .env("GIT_CONFIG_GLOBAL", "/dev/null")
            .env("GIT_CONFIG_NOSYSTEM", "1")
            .args(args)
            .current_dir(repo)
            .output()
            .expect("run git");
        assert!(
            output.status.success(),
            "git {args:?} failed: {}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    fn create_repository_with_two_worktrees(
        temp: &TempDir,
    ) -> (AbsolutePathBuf, AbsolutePathBuf, AbsolutePathBuf) {
        let repository = temp.path().join("repository");
        let writer_a = temp.path().join("writer-a");
        let writer_b = temp.path().join("writer-b");
        std::fs::create_dir(&repository).expect("create repository");
        run_git(&repository, &["init"]);
        run_git(&repository, &["config", "user.name", "Writer Binding Test"]);
        run_git(
            &repository,
            &["config", "user.email", "writer-binding@example.invalid"],
        );
        std::fs::write(repository.join("README.md"), "seed\n").expect("write seed");
        run_git(&repository, &["add", "README.md"]);
        run_git(&repository, &["commit", "-m", "seed"]);
        run_git(
            &repository,
            &[
                "worktree",
                "add",
                "-b",
                "writer-a",
                writer_a.to_str().unwrap(),
            ],
        );
        run_git(
            &repository,
            &[
                "worktree",
                "add",
                "-b",
                "writer-b",
                writer_b.to_str().unwrap(),
            ],
        );
        let absolute = |path: &Path| {
            AbsolutePathBuf::from_absolute_path(
                std::fs::canonicalize(path).expect("canonicalize test path"),
            )
            .expect("absolute test path")
        };
        (
            absolute(&repository),
            absolute(&writer_a),
            absolute(&writer_b),
        )
    }

    fn selections(
        repository: &AbsolutePathBuf,
        writer_a: &AbsolutePathBuf,
        writer_b: &AbsolutePathBuf,
    ) -> TurnEnvironmentSelections {
        TurnEnvironmentSelections::new(
            repository.clone(),
            vec![TurnEnvironmentSelection {
                environment_id: LOCAL_ENVIRONMENT_ID.to_string(),
                cwd: PathUri::from_abs_path(repository),
                workspace_roots: vec![
                    PathUri::from_abs_path(repository),
                    PathUri::from_abs_path(writer_a),
                    PathUri::from_abs_path(writer_b),
                ],
            }],
        )
    }

    #[tokio::test]
    async fn binding_capture_revalidation_and_replacement_use_exact_identity() {
        let temp = TempDir::new().expect("tempdir");
        let (repository, writer_a, writer_b) = create_repository_with_two_worktrees(&temp);
        let mut config = test_config().await;
        config.cwd = repository.clone();
        config.ephemeral = false;
        config
            .permissions
            .replace_permission_profile_from_session_snapshot(PermissionProfileSnapshot::active(
                PermissionProfile::workspace_write(),
                ActivePermissionProfile::new(":workspace"),
            ))
            .expect("install managed workspace profile");
        let authority_environments = selections(&repository, &writer_a, &writer_b);
        let manager = EnvironmentManager::default_for_tests();

        let binding = capture_initial_binding(
            WriterWorkspaceBindingRequest {
                worktree_root: writer_a.clone(),
                environment_id: None,
            },
            &config,
            &authority_environments,
            &manager,
        )
        .await
        .expect("capture writer A");
        assert_eq!(binding.snapshot.binding.generation, 1);
        assert_eq!(binding.snapshot.binding.worktree_root, writer_a);
        assert_eq!(binding.snapshot.binding.repository_root, repository);
        revalidate_binding(
            &binding,
            config.permissions.permission_profile(),
            &authority_environments,
            config.permissions.profile_workspace_roots(),
            &manager,
        )
        .await
        .expect("revalidate writer A");

        let replacement = capture_replacement_binding(
            WriterWorkspaceBindingRequest {
                worktree_root: writer_b.clone(),
                environment_id: None,
            },
            &binding.snapshot.binding,
            config.permissions.permission_profile(),
            &authority_environments,
            config.permissions.profile_workspace_roots(),
            &manager,
        )
        .await
        .expect("replace with writer B");
        assert_eq!(replacement.snapshot.binding.generation, 2);
        assert_eq!(replacement.snapshot.binding.worktree_root, writer_b);

        std::fs::remove_file(binding.snapshot.binding.worktree_root.join(".git"))
            .expect("invalidate writer A identity");
        assert_eq!(
            revalidate_binding(
                &binding,
                config.permissions.permission_profile(),
                &authority_environments,
                config.permissions.profile_workspace_roots(),
                &manager,
            )
            .await,
            Err(WriterWorkspaceBindingError::InvalidLinkedWorktree)
        );
    }

    #[tokio::test]
    async fn binding_rejects_ephemeral_threads_before_identity_reads() {
        let temp = TempDir::new().expect("tempdir");
        let (repository, writer_a, writer_b) = create_repository_with_two_worktrees(&temp);
        let mut config = test_config().await;
        config.cwd = repository.clone();
        config.ephemeral = true;
        let result = capture_initial_binding(
            WriterWorkspaceBindingRequest {
                worktree_root: writer_a.clone(),
                environment_id: None,
            },
            &config,
            &selections(&repository, &writer_a, &writer_b),
            &EnvironmentManager::default_for_tests(),
        )
        .await;
        assert!(matches!(
            result,
            Err(WriterWorkspaceBindingError::EphemeralThread)
        ));
    }

    #[cfg(unix)]
    #[tokio::test]
    async fn external_write_target_is_canonicalized_and_revalidated_before_use() {
        use std::os::unix::fs::symlink;

        let temp = TempDir::new().expect("tempdir");
        let approved_target = temp.path().join("approved-target");
        let replacement_target = temp.path().join("replacement-target");
        let requested_alias = temp.path().join("requested-alias");
        std::fs::create_dir(&approved_target).expect("create approved target");
        std::fs::create_dir(&replacement_target).expect("create replacement target");
        symlink(&approved_target, &requested_alias).expect("create requested alias");
        let requested_alias = AbsolutePathBuf::from_absolute_path(requested_alias)
            .expect("requested alias is absolute");
        let approved_target = AbsolutePathBuf::from_absolute_path(
            std::fs::canonicalize(&approved_target).expect("canonical approved target"),
        )
        .expect("approved target is absolute");
        let manager = EnvironmentManager::default_for_tests();
        let fs = manager
            .get_environment(LOCAL_ENVIRONMENT_ID)
            .expect("local environment")
            .get_filesystem();

        let permissions = canonicalize_external_write_permissions(
            AdditionalPermissionProfile {
                file_system: Some(FileSystemPermissions::from_read_write_roots(
                    /*read*/ None,
                    Some(vec![requested_alias]),
                )),
                ..Default::default()
            },
            fs.as_ref(),
        )
        .await
        .expect("canonicalize reviewer target");
        let stored_target = match &permissions
            .file_system
            .as_ref()
            .expect("filesystem permissions")
            .entries[0]
            .path
        {
            FileSystemPath::Path { path } => path,
            other => panic!("expected exact path, got {other:?}"),
        };
        assert_eq!(stored_target, &approved_target);

        let displaced_target = temp.path().join("displaced-target");
        std::fs::rename(approved_target.as_path(), &displaced_target)
            .expect("displace approved target");
        symlink(&replacement_target, approved_target.as_path())
            .expect("retarget approved physical path");

        assert_eq!(
            revalidate_external_write_permissions(&permissions, fs.as_ref()).await,
            Err(WriterWorkspaceBindingError::ExternalWriteTargetChanged)
        );
    }
}
