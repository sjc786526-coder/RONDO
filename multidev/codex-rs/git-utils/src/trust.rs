use codex_file_system::ExecutorFileSystem;
use codex_file_system::FindUpErrorPolicy;
use codex_file_system::find_nearest_native_ancestor_with_markers;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_path_uri::PathUri;

const MAX_GIT_METADATA_FILE_BYTES: u64 = 64 * 1024;

/// Filesystem-verified identity of a local Git linked worktree.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LinkedWorktreeIdentity {
    pub worktree_root: AbsolutePathBuf,
    pub git_dir: AbsolutePathBuf,
    pub common_dir: AbsolutePathBuf,
    pub repository_root: AbsolutePathBuf,
}

/// Resolve the path that should be used for trust checks. Similar to
/// [`crate::get_git_repo_root`], but resolves to the root of the main
/// repository. A linked worktree inherits that root only after its registration
/// and repository ownership have been verified without invoking `git`.
pub async fn resolve_root_git_project_for_trust(
    fs: &dyn ExecutorFileSystem,
    cwd: &AbsolutePathBuf,
) -> Option<AbsolutePathBuf> {
    resolve_git_project_for_trust(fs, cwd)
        .await
        .map(|resolved| resolved.repository_root)
}

/// Resolve and verify an exact linked-worktree root without invoking Git.
pub async fn resolve_linked_worktree_identity(
    fs: &dyn ExecutorFileSystem,
    worktree_root: &AbsolutePathBuf,
) -> Option<LinkedWorktreeIdentity> {
    let resolved = resolve_git_project_for_trust(fs, worktree_root).await?;
    let identity = resolved.linked_worktree?;
    (identity.worktree_root == *worktree_root).then_some(identity)
}

struct ResolvedGitProject {
    repository_root: AbsolutePathBuf,
    linked_worktree: Option<LinkedWorktreeIdentity>,
}

async fn resolve_git_project_for_trust(
    fs: &dyn ExecutorFileSystem,
    cwd: &AbsolutePathBuf,
) -> Option<ResolvedGitProject> {
    let cwd_uri = PathUri::from_abs_path(cwd);
    let base = match fs.get_metadata(&cwd_uri, /*sandbox*/ None).await {
        Ok(metadata) if metadata.is_directory => cwd.clone(),
        _ => cwd.parent()?,
    };
    let repo_root = find_nearest_native_ancestor_with_markers(
        fs,
        &base,
        vec![".git".to_string()],
        FindUpErrorPolicy::Ignore,
        /*sandbox*/ None,
    )
    .await
    .ok()??;
    let dot_git = repo_root.join(".git");
    let dot_git_uri = PathUri::from_abs_path(&dot_git);
    let dot_git_metadata = fs.get_metadata(&dot_git_uri, /*sandbox*/ None).await.ok()?;
    if dot_git_metadata.is_directory {
        return Some(ResolvedGitProject {
            repository_root: repo_root,
            linked_worktree: None,
        });
    }
    if !dot_git_metadata.is_file
        || dot_git_metadata.is_symlink
        || dot_git_metadata.size > MAX_GIT_METADATA_FILE_BYTES
    {
        return None;
    }

    let git_dir_uri = read_gitdir_file(fs, &dot_git_uri).await?;
    let git_dir_path = git_dir_uri.to_abs_path().ok()?;
    let git_dir_metadata = fs.get_metadata(&git_dir_uri, /*sandbox*/ None).await.ok()?;
    if !git_dir_metadata.is_directory || git_dir_metadata.is_symlink {
        return None;
    }

    let canonical_git_dir_uri = fs.canonicalize(&git_dir_uri, /*sandbox*/ None).await.ok()?;
    let worktrees_dir_uri = canonical_git_dir_uri.parent()?;
    if worktrees_dir_uri.basename().as_deref() != Some("worktrees") {
        return None;
    }
    let common_dir_uri = worktrees_dir_uri.parent()?;
    let worktree_gitdir_uri = canonical_git_dir_uri.join("gitdir").ok()?;
    let commondir_uri = canonical_git_dir_uri.join("commondir").ok()?;
    let (worktree_gitdir_bytes, commondir_bytes) = tokio::join!(
        read_metadata_file(fs, &worktree_gitdir_uri),
        read_metadata_file(fs, &commondir_uri),
    );
    let worktree_gitdir_bytes = worktree_gitdir_bytes?;
    let worktree_gitdir = worktree_gitdir_bytes.trim_ascii();
    if worktree_gitdir.is_empty() {
        return None;
    }
    let worktree_dot_git_uri = canonical_git_dir_uri
        .join_native_bytes(worktree_gitdir)
        .ok()?;
    if worktree_dot_git_uri.basename().as_deref() != Some(".git") {
        return None;
    }
    let commondir_bytes = commondir_bytes?;
    let commondir = commondir_bytes.trim_ascii();
    if commondir.is_empty() {
        return None;
    }
    let linked_common_dir_uri = canonical_git_dir_uri.join_native_bytes(commondir).ok()?;
    let registered_checkout_uri = worktree_dot_git_uri.parent()?;
    let checkout_uri = PathUri::from_abs_path(&repo_root);
    // Compare checkout directories, not the final .git entries. Following a
    // substituted .git symlink must never turn an unrelated checkout into the
    // registered one, even if it is swapped after the metadata check above.
    let (registered_checkout, checkout, linked_common_dir) = tokio::join!(
        fs.canonicalize(&registered_checkout_uri, /*sandbox*/ None),
        fs.canonicalize(&checkout_uri, /*sandbox*/ None),
        fs.canonicalize(&linked_common_dir_uri, /*sandbox*/ None),
    );
    let registered_checkout = registered_checkout.ok()?;
    let checkout = checkout.ok()?;
    let linked_common_dir = linked_common_dir.ok()?;
    // PathUri equality folds Windows ASCII case, but even Windows directories
    // can be case-sensitive. Canonical filesystem identities must match exactly.
    if registered_checkout.to_url() != checkout.to_url()
        || linked_common_dir.to_url() != common_dir_uri.to_url()
    {
        return None;
    }

    // Preserve the existing trust key (including path aliases), but prove that
    // its main checkout actually owns the canonical common directory. A main
    // checkout made with --separate-git-dir may have a regular .git pointer.
    let common_dir = git_dir_path.parent()?.parent()?;
    let main_root = common_dir.parent()?;
    let main_dot_git_uri = PathUri::from_abs_path(&main_root.join(".git"));
    let main_metadata = fs
        .get_metadata(&main_dot_git_uri, /*sandbox*/ None)
        .await
        .ok()?;
    let main_git_dir_uri = if main_metadata.is_directory {
        main_dot_git_uri
    } else {
        read_gitdir_file(fs, &main_dot_git_uri).await?
    };
    if fs
        .canonicalize(&main_git_dir_uri, /*sandbox*/ None)
        .await
        .ok()?
        .to_url()
        != common_dir_uri.to_url()
    {
        return None;
    }
    let canonical_main_root = fs
        .canonicalize(&PathUri::from_abs_path(&main_root), /*sandbox*/ None)
        .await
        .ok()
        .and_then(|path| path.to_abs_path().ok());
    let linked_worktree = canonical_main_root.and_then(|repository_root| {
        Some(LinkedWorktreeIdentity {
            worktree_root: checkout.to_abs_path().ok()?,
            git_dir: canonical_git_dir_uri.to_abs_path().ok()?,
            common_dir: linked_common_dir.to_abs_path().ok()?,
            repository_root,
        })
    });
    Some(ResolvedGitProject {
        repository_root: main_root,
        linked_worktree,
    })
}

async fn read_gitdir_file(fs: &dyn ExecutorFileSystem, path: &PathUri) -> Option<PathUri> {
    let contents = read_metadata_file(fs, path).await?;
    let target = contents.trim_ascii().strip_prefix(b"gitdir:")?.trim_ascii();
    if target.is_empty() {
        return None;
    }
    path.parent()?.join_native_bytes(target).ok()
}

async fn read_metadata_file(fs: &dyn ExecutorFileSystem, path: &PathUri) -> Option<Vec<u8>> {
    let metadata = fs.get_metadata(path, /*sandbox*/ None).await.ok()?;
    if !metadata.is_file || metadata.is_symlink || metadata.size > MAX_GIT_METADATA_FILE_BYTES {
        return None;
    }
    // Keep using fs/readFile for independently deployed older exec-servers.
    // Their streaming fs/open API is not universally available yet.
    let bytes = fs.read_file(path, /*sandbox*/ None).await.ok()?;
    (bytes.len() as u64 <= MAX_GIT_METADATA_FILE_BYTES).then_some(bytes)
}
