//! Test-only M4-W0 seam for comparing caller-relative execution with an admitted writer binding.
//!
//! This module deliberately does not define product configuration, persistence, or a public API.
//! It exercises the existing `Config` permission/workspace model and system Git closely enough to
//! decide whether a structural binding is worth implementing in M4-W1.

use crate::config::Config;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::fs;
use std::path::Path;
use std::process::Command;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum BindingFailure {
    WorktreeMissing,
    RepositoryMismatch,
    WorkspaceRootsIncompatible,
    PermissionIncompatible,
    ExecutionContextMismatch,
    ActionFailed,
}

#[derive(Debug)]
struct BindingError {
    failure: BindingFailure,
    detail: String,
}

impl BindingError {
    fn new(failure: BindingFailure, detail: impl Into<String>) -> Self {
        Self {
            failure,
            detail: detail.into(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct GitIdentity {
    worktree_root: AbsolutePathBuf,
    common_dir: AbsolutePathBuf,
    git_dir: AbsolutePathBuf,
}

impl GitIdentity {
    fn inspect(worktree_root: &AbsolutePathBuf) -> Result<Self, BindingError> {
        let worktree_root = canonical_absolute(worktree_root.as_path()).map_err(|error| {
            BindingError::new(
                BindingFailure::WorktreeMissing,
                format!(
                    "worktree {} is unavailable: {error}",
                    worktree_root.display()
                ),
            )
        })?;
        let reported_top_level =
            canonical_git_path(&worktree_root, &["rev-parse", "--show-toplevel"])?;
        if reported_top_level != worktree_root {
            return Err(BindingError::new(
                BindingFailure::RepositoryMismatch,
                format!(
                    "{} is not the exact Git worktree top-level {}",
                    worktree_root.display(),
                    reported_top_level.display()
                ),
            ));
        }
        let common_dir = canonical_git_path(
            &worktree_root,
            &["rev-parse", "--path-format=absolute", "--git-common-dir"],
        )?;
        let git_dir = canonical_git_path(&worktree_root, &["rev-parse", "--absolute-git-dir"])?;
        Ok(Self {
            worktree_root,
            common_dir,
            git_dir,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct WriterWorkspaceBinding {
    git_identity: GitIdentity,
    execution_environment_id: String,
}

impl WriterWorkspaceBinding {
    fn capture(
        worktree_root: AbsolutePathBuf,
        execution_environment_id: impl Into<String>,
    ) -> Result<Self, BindingError> {
        Ok(Self {
            git_identity: GitIdentity::inspect(&worktree_root)?,
            execution_environment_id: execution_environment_id.into(),
        })
    }

    fn worktree_root(&self) -> &AbsolutePathBuf {
        &self.git_identity.worktree_root
    }

    fn verify_git_identity(&self) -> Result<(), BindingError> {
        let current = GitIdentity::inspect(self.worktree_root())?;
        if current != self.git_identity {
            return Err(BindingError::new(
                BindingFailure::RepositoryMismatch,
                format!(
                    "{} no longer identifies the admitted repository/worktree",
                    self.worktree_root().display()
                ),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
struct BoundWriterRuntime {
    binding: WriterWorkspaceBinding,
    effective_config: Config,
    execution_environment_id: String,
}

impl BoundWriterRuntime {
    fn bind(
        caller_config: &Config,
        worktree_root: AbsolutePathBuf,
        execution_environment_id: &str,
    ) -> Result<Self, BindingError> {
        let binding =
            WriterWorkspaceBinding::capture(worktree_root, execution_environment_id.to_string())?;
        Self::reload(binding, caller_config, execution_environment_id)
    }

    /// Rebuild an effective runtime from the current caller authorization and immutable binding.
    /// No prior in-process validation result is reused.
    fn reload(
        binding: WriterWorkspaceBinding,
        caller_config: &Config,
        execution_environment_id: &str,
    ) -> Result<Self, BindingError> {
        if execution_environment_id != binding.execution_environment_id {
            return Err(BindingError::new(
                BindingFailure::ExecutionContextMismatch,
                format!(
                    "execution environment {execution_environment_id} does not match {}",
                    binding.execution_environment_id
                ),
            ));
        }
        ensure_pre_authorized(caller_config, binding.worktree_root())?;

        let mut effective_config = caller_config.clone();
        effective_config.cwd = binding.worktree_root().clone();
        effective_config.workspace_roots = vec![binding.worktree_root().clone()];
        effective_config.workspace_roots_explicit = true;
        effective_config
            .permissions
            .set_workspace_roots(vec![binding.worktree_root().clone()]);

        let runtime = Self {
            binding,
            effective_config,
            execution_environment_id: execution_environment_id.to_string(),
        };
        runtime.revalidate()?;
        Ok(runtime)
    }

    fn revalidate(&self) -> Result<(), BindingError> {
        if self.execution_environment_id != self.binding.execution_environment_id {
            return Err(BindingError::new(
                BindingFailure::ExecutionContextMismatch,
                "runtime execution environment changed after admission",
            ));
        }
        if self.effective_config.cwd != *self.binding.worktree_root()
            || self.effective_config.effective_workspace_roots()
                != vec![self.binding.worktree_root().clone()]
        {
            return Err(BindingError::new(
                BindingFailure::ExecutionContextMismatch,
                "effective cwd/workspace roots no longer match the binding",
            ));
        }
        ensure_write_permission(&self.effective_config, self.binding.worktree_root())?;
        self.binding.verify_git_identity()
    }

    fn run(&self, action: &FakeWriterAction) -> Result<WriterObservation, BindingError> {
        if action.intended_worktree != *self.binding.worktree_root() {
            return Err(BindingError::new(
                BindingFailure::ExecutionContextMismatch,
                "writer action targets a different worktree",
            ));
        }
        self.revalidate()?;
        action.execute(&self.effective_config)
    }
}

struct WriterSlot {
    runtime: BoundWriterRuntime,
}

impl WriterSlot {
    fn replace(
        &mut self,
        caller_config: &Config,
        worktree_root: AbsolutePathBuf,
        execution_environment_id: &str,
    ) -> Result<(), BindingError> {
        let replacement =
            BoundWriterRuntime::bind(caller_config, worktree_root, execution_environment_id)?;
        self.runtime = replacement;
        Ok(())
    }
}

#[derive(Clone, Debug)]
struct FakeWriterAction {
    intended_worktree: AbsolutePathBuf,
    relative_path: &'static str,
    content: &'static str,
}

impl FakeWriterAction {
    fn execute(&self, config: &Config) -> Result<WriterObservation, BindingError> {
        let output_path = config.cwd.join(self.relative_path);
        fs::write(&output_path, self.content).map_err(|error| {
            BindingError::new(
                BindingFailure::ActionFailed,
                format!("write {}: {error}", output_path.display()),
            )
        })?;
        Ok(WriterObservation {
            effective_cwd: config.cwd.clone(),
            output_path,
        })
    }
}

#[derive(Debug, PartialEq, Eq)]
struct WriterObservation {
    effective_cwd: AbsolutePathBuf,
    output_path: AbsolutePathBuf,
}

#[derive(Debug, PartialEq, Eq)]
/// Existing Git facts observed at handoff time; this is not stored binding or handoff state.
struct ObservedGitFacts {
    branch: String,
    head: String,
    status: String,
    diff: String,
}

impl ObservedGitFacts {
    fn inspect(worktree_root: &AbsolutePathBuf) -> Result<Self, BindingError> {
        Ok(Self {
            branch: git_stdout(worktree_root, &["symbolic-ref", "--short", "HEAD"])?,
            head: git_stdout(worktree_root, &["rev-parse", "HEAD"])?,
            status: git_stdout(
                worktree_root,
                &["status", "--short", "--untracked-files=all"],
            )?,
            diff: git_stdout(worktree_root, &["diff", "--no-ext-diff"])?,
        })
    }
}

fn ensure_pre_authorized(
    caller_config: &Config,
    worktree_root: &AbsolutePathBuf,
) -> Result<(), BindingError> {
    if !caller_config
        .effective_workspace_roots()
        .iter()
        .any(|root| root == worktree_root)
    {
        return Err(BindingError::new(
            BindingFailure::WorkspaceRootsIncompatible,
            format!(
                "{} is not one of the caller-authorized workspace roots",
                worktree_root.display()
            ),
        ));
    }
    ensure_write_permission(caller_config, worktree_root)
}

fn ensure_write_permission(
    config: &Config,
    worktree_root: &AbsolutePathBuf,
) -> Result<(), BindingError> {
    let probe_path = worktree_root.join("writer-output.txt");
    if !config
        .permissions
        .file_system_sandbox_policy()
        .can_write_path_with_cwd(probe_path.as_path(), config.cwd.as_path())
    {
        return Err(BindingError::new(
            BindingFailure::PermissionIncompatible,
            format!(
                "current permission profile cannot write {}",
                worktree_root.display()
            ),
        ));
    }
    Ok(())
}

fn canonical_git_path(
    worktree_root: &AbsolutePathBuf,
    args: &[&str],
) -> Result<AbsolutePathBuf, BindingError> {
    let output = git_stdout(worktree_root, args)?;
    canonical_absolute(Path::new(&output)).map_err(|error| {
        BindingError::new(
            BindingFailure::RepositoryMismatch,
            format!("Git returned an invalid repository path {output}: {error}"),
        )
    })
}

fn canonical_absolute(path: &Path) -> std::io::Result<AbsolutePathBuf> {
    let canonical = fs::canonicalize(path)?;
    AbsolutePathBuf::try_from(canonical).map_err(std::io::Error::other)
}

fn git_stdout(worktree_root: &AbsolutePathBuf, args: &[&str]) -> Result<String, BindingError> {
    let output = Command::new("git")
        .args(args)
        .current_dir(worktree_root)
        .output()
        .map_err(|error| {
            BindingError::new(
                BindingFailure::RepositoryMismatch,
                format!("run git {}: {error}", args.join(" ")),
            )
        })?;
    if !output.status.success() {
        return Err(BindingError::new(
            BindingFailure::RepositoryMismatch,
            format!(
                "git {} failed in {}: {}",
                args.join(" "),
                worktree_root.display(),
                String::from_utf8_lossy(&output.stderr).trim()
            ),
        ));
    }
    String::from_utf8(output.stdout)
        .map(|stdout| stdout.trim().to_string())
        .map_err(|error| {
            BindingError::new(
                BindingFailure::RepositoryMismatch,
                format!("git output was not UTF-8: {error}"),
            )
        })
}

#[cfg(test)]
#[path = "workspace_binding_w0_tests.rs"]
mod tests;
