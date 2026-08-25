//! Local hard-delete support for persisted threads.
//!
//! Existing rollout files are deleted before this operation reports success. A rollout file that
//! vanishes after discovery counts as already deleted. The app-server deletes main state DB rows
//! after every associated rollout is removed; this module deletes local history projection rows.

use std::collections::HashMap;
use std::collections::HashSet;
#[cfg(unix)]
use std::fs::File;
use std::io::ErrorKind;
use std::path::Path;
use std::path::PathBuf;

use codex_protocol::protocol::DurableTeamSessionMeta;
use codex_rollout::ARCHIVED_SESSIONS_SUBDIR;
use codex_rollout::RolloutReferenceIndex;
use codex_rollout::SESSIONS_SUBDIR;
use codex_rollout::find_archived_thread_path_by_id_str;
use codex_rollout::find_thread_path_by_id_str;
use codex_rollout::remove_thread_name_entries;

use super::LocalThreadStore;
use super::helpers::matching_rollout_file_name;
use super::helpers::scoped_rollout_path;
use crate::DeleteThreadParams;
use crate::DeleteThreadsParams;
use crate::ThreadStoreError;
use crate::ThreadStoreResult;
use crate::durable_team_snapshot_path;

pub(super) async fn delete_thread(
    store: &LocalThreadStore,
    params: DeleteThreadParams,
) -> ThreadStoreResult<()> {
    let thread_id = params.thread_id;
    let _lifecycle_guard = store.live_writer_locks.lock_lifecycle(thread_id).await;
    let _live_writer_guard = store.live_writer_locks.lock(thread_id).await;
    reject_live_writers(store, &[thread_id]).await?;
    let reference_index = scan_reference_index(store).await?;
    if reference_index.reference_count(thread_id) > 0 {
        return Err(referenced_thread_error(thread_id));
    }
    let mut writer_guards = store.acquire_writer_locks(&[thread_id]).await?;
    delete_durable_team_artifacts(store, &[thread_id]).await?;
    delete_thread_after_reference_check(store, thread_id, &mut writer_guards).await
}

pub(super) async fn delete_threads(
    store: &LocalThreadStore,
    params: DeleteThreadsParams,
) -> ThreadStoreResult<()> {
    let mut thread_ids = params.thread_ids;
    if thread_ids.is_empty() {
        return Ok(());
    }

    let deletion_set: HashSet<_> = thread_ids.iter().copied().collect();
    let mut lock_thread_ids: Vec<_> = deletion_set.iter().copied().collect();
    lock_thread_ids.sort_unstable_by_key(ToString::to_string);
    let mut _lifecycle_guards = Vec::with_capacity(lock_thread_ids.len());
    for thread_id in &lock_thread_ids {
        _lifecycle_guards.push(store.live_writer_locks.lock_lifecycle(*thread_id).await);
    }
    let mut _live_writer_guards = Vec::with_capacity(lock_thread_ids.len());
    for &thread_id in &lock_thread_ids {
        _live_writer_guards.push(store.live_writer_locks.lock(thread_id).await);
    }
    reject_live_writers(store, &lock_thread_ids).await?;

    let reference_index = scan_reference_index(store).await?;
    // References from children in this delete set are removed by the same request, so only
    // references from children outside the set should block it.
    let mut internal_reference_counts = HashMap::new();
    for child_thread_id in &deletion_set {
        if let Some(history_base) = reference_index.history_base(*child_thread_id)
            && history_base.thread_id != *child_thread_id
            && deletion_set.contains(&history_base.thread_id)
        {
            *internal_reference_counts
                .entry(history_base.thread_id)
                .or_default() += 1;
        }
    }
    for thread_id in &thread_ids {
        let internal_reference_count = internal_reference_counts
            .get(thread_id)
            .copied()
            .unwrap_or_default();
        if reference_index.reference_count(*thread_id) > internal_reference_count {
            return Err(referenced_thread_error(*thread_id));
        }
    }

    let mut writer_guards = store.acquire_writer_locks(&lock_thread_ids).await?;
    let durable_roots = durable_team_artifacts_for_deletion(store, &thread_ids).await?;
    delete_validated_durable_team_artifacts(&durable_roots)?;
    // The canonical Root marker is the retry anchor if a later rollout deletion fails after its
    // Team artifact was removed. Keep every durable Root last regardless of caller order.
    let durable_root_ids = durable_roots
        .iter()
        .map(|artifact| artifact.root_thread_id)
        .collect::<HashSet<_>>();
    thread_ids.sort_by_key(|thread_id| durable_root_ids.contains(thread_id));
    for thread_id in thread_ids {
        match delete_thread_after_reference_check(store, thread_id, &mut writer_guards).await {
            Ok(()) | Err(ThreadStoreError::ThreadNotFound { .. }) => {}
            Err(err) => return Err(err),
        }
    }
    Ok(())
}

#[derive(Debug)]
struct DurableTeamArtifactDeletion {
    root_thread_id: codex_protocol::ThreadId,
    path: PathBuf,
}

async fn delete_durable_team_artifacts(
    store: &LocalThreadStore,
    thread_ids: &[codex_protocol::ThreadId],
) -> ThreadStoreResult<()> {
    let artifacts = durable_team_artifacts_for_deletion(store, thread_ids).await?;
    delete_validated_durable_team_artifacts(&artifacts)
}

async fn durable_team_artifacts_for_deletion(
    store: &LocalThreadStore,
    thread_ids: &[codex_protocol::ThreadId],
) -> ThreadStoreResult<Vec<DurableTeamArtifactDeletion>> {
    let state_db_ctx = store.state_db().await;
    let mut artifacts = Vec::new();
    for &thread_id in thread_ids {
        let thread_id_string = thread_id.to_string();
        let artifact_path =
            durable_team_snapshot_path(store.config.codex_home.as_path(), thread_id);
        let artifact_exists = match std::fs::symlink_metadata(&artifact_path) {
            Ok(metadata) if metadata.file_type().is_file() => true,
            Ok(_) => {
                return Err(ThreadStoreError::InvalidRequest {
                    message: format!(
                        "durable Team artifact for Root {thread_id} is not a regular file"
                    ),
                });
            }
            Err(error) if error.kind() == ErrorKind::NotFound => false,
            Err(error) => {
                return Err(ThreadStoreError::Internal {
                    message: format!(
                        "failed to inspect durable Team artifact for Root {thread_id}: {error}"
                    ),
                });
            }
        };
        let active = find_thread_path_by_id_str(
            store.config.codex_home.as_path(),
            thread_id_string.as_str(),
            state_db_ctx.as_deref(),
        )
        .await
        .map_err(|error| ThreadStoreError::InvalidRequest {
            message: format!(
                "failed to inspect durable Team intent for thread {thread_id}: {error}"
            ),
        })?;
        let archived = find_archived_thread_path_by_id_str(
            store.config.codex_home.as_path(),
            thread_id_string.as_str(),
            state_db_ctx.as_deref(),
        )
        .await
        .map_err(|error| ThreadStoreError::InvalidRequest {
            message: format!(
                "failed to inspect archived durable Team intent for thread {thread_id}: {error}"
            ),
        })?;
        let mut rollout_candidates = Vec::new();
        if let Some(path) = active {
            rollout_candidates.push((
                path,
                store.config.codex_home.join(SESSIONS_SUBDIR),
                "sessions",
            ));
        }
        if let Some(path) = archived {
            rollout_candidates.push((
                path,
                store.config.codex_home.join(ARCHIVED_SESSIONS_SUBDIR),
                "archived sessions",
            ));
        }
        if rollout_candidates.is_empty() {
            if artifact_exists {
                return Err(ThreadStoreError::Conflict {
                    message: format!(
                        "cannot delete durable Team artifact for Root {thread_id} without a canonical Root marker"
                    ),
                });
            }
            continue;
        }

        let mut durable_intent = None;
        let mut saw_non_durable_marker = false;
        let mut saw_unreadable_marker = false;
        for (rollout_path, rollout_root, scope_label) in rollout_candidates {
            let canonical_rollout_path =
                scoped_rollout_path(rollout_root, rollout_path.as_path(), scope_label)?;
            matching_rollout_file_name(
                canonical_rollout_path.as_path(),
                thread_id,
                rollout_path.as_path(),
            )?;
            let session_meta = match codex_rollout::read_session_meta_line(&canonical_rollout_path)
                .await
            {
                Ok(session_meta) => session_meta.meta,
                Err(_error) if !artifact_exists => {
                    // Preserve the existing explicit-delete contract for a corrupt ordinary
                    // rollout. With no Team artifact present there is nothing in the durable Team
                    // authority domain to orphan. If another marker proves this id is a durable
                    // Root below, the unreadable marker still makes the lineage ambiguous.
                    saw_unreadable_marker = true;
                    continue;
                }
                Err(error) => {
                    return Err(ThreadStoreError::InvalidRequest {
                        message: format!(
                            "failed to read canonical SessionMeta before deleting thread {thread_id}: {error}"
                        ),
                    });
                }
            };
            let Some(intent) = session_meta.durable_team else {
                saw_non_durable_marker = true;
                continue;
            };
            if intent.version != DurableTeamSessionMeta::CURRENT_VERSION {
                return Err(ThreadStoreError::Unsupported {
                    operation: "delete_durable_team_snapshot_version",
                });
            }
            if session_meta.id != thread_id
                || session_meta.session_id != intent.session_id
                || intent.root_thread_id != thread_id
            {
                return Err(ThreadStoreError::Conflict {
                    message: format!(
                        "durable Team intent for thread {thread_id} does not match its canonical Root lineage"
                    ),
                });
            }
            if durable_intent.is_some_and(|expected| expected != intent) {
                return Err(ThreadStoreError::Conflict {
                    message: format!(
                        "active and archived Root markers for thread {thread_id} disagree on durable Team lineage"
                    ),
                });
            }
            durable_intent = Some(intent);
        }
        if durable_intent.is_some() && saw_non_durable_marker {
            return Err(ThreadStoreError::Conflict {
                message: format!(
                    "active and archived Root markers for thread {thread_id} disagree on durable Team ownership"
                ),
            });
        }
        if durable_intent.is_some() && saw_unreadable_marker {
            return Err(ThreadStoreError::Conflict {
                message: format!(
                    "active and archived Root markers for thread {thread_id} do not prove one durable Team lineage"
                ),
            });
        }
        if durable_intent.is_some() {
            artifacts.push(DurableTeamArtifactDeletion {
                root_thread_id: thread_id,
                path: artifact_path,
            });
        } else if artifact_exists {
            return Err(ThreadStoreError::Conflict {
                message: format!(
                    "durable Team artifact for Root {thread_id} has no matching canonical Root intent"
                ),
            });
        }
    }
    Ok(artifacts)
}

fn delete_validated_durable_team_artifacts(
    artifacts: &[DurableTeamArtifactDeletion],
) -> ThreadStoreResult<()> {
    for artifact in artifacts {
        match std::fs::remove_file(&artifact.path) {
            Ok(()) => sync_durable_team_artifact_parent(artifact)?,
            // A retry can observe the file as already absent after an earlier unlink. Syncing the
            // directory again turns an earlier unknown durability result into proved absence
            // before the canonical Root marker is removed.
            Err(error) if error.kind() == ErrorKind::NotFound => {
                sync_durable_team_artifact_parent(artifact)?;
            }
            Err(error) => {
                return Err(ThreadStoreError::Internal {
                    message: format!(
                        "failed to delete durable Team artifact for Root {}: {error}",
                        artifact.root_thread_id
                    ),
                });
            }
        }
    }
    Ok(())
}

#[cfg(unix)]
fn sync_durable_team_artifact_parent(
    artifact: &DurableTeamArtifactDeletion,
) -> ThreadStoreResult<()> {
    let parent = artifact
        .path
        .parent()
        .ok_or_else(|| ThreadStoreError::Internal {
            message: "durable Team artifact path has no parent".to_string(),
        })?;
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| ThreadStoreError::Internal {
            message: format!(
                "durable Team artifact deletion for Root {} has an unknown durability result: {error}",
                artifact.root_thread_id
            ),
        })
}

#[cfg(not(unix))]
fn sync_durable_team_artifact_parent(
    _artifact: &DurableTeamArtifactDeletion,
) -> ThreadStoreResult<()> {
    Ok(())
}

async fn reject_live_writers(
    store: &LocalThreadStore,
    thread_ids: &[codex_protocol::ThreadId],
) -> ThreadStoreResult<()> {
    let live_recorders = store.live_recorders.lock().await;
    if let Some(thread_id) = thread_ids
        .iter()
        .find(|thread_id| live_recorders.contains_key(thread_id))
    {
        return Err(ThreadStoreError::Conflict {
            message: format!("thread {thread_id} already has an active writer"),
        });
    }
    Ok(())
}

async fn scan_reference_index(
    store: &LocalThreadStore,
) -> ThreadStoreResult<RolloutReferenceIndex> {
    RolloutReferenceIndex::scan(store.config.codex_home.as_path())
        .await
        .map_err(|err| ThreadStoreError::Internal {
            message: format!("failed to scan fork history references: {err}"),
        })
}

fn referenced_thread_error(thread_id: codex_protocol::ThreadId) -> ThreadStoreError {
    ThreadStoreError::InvalidRequest {
        message: format!("cannot delete thread {thread_id}: forked history still references it"),
    }
}

async fn delete_thread_after_reference_check(
    store: &LocalThreadStore,
    thread_id: codex_protocol::ThreadId,
    _writer_guards: &mut Vec<super::writer_lock::WriterLockGuard>,
) -> ThreadStoreResult<()> {
    let thread_id_str = thread_id.to_string();
    let state_db_ctx = store.state_db().await;
    let mut rollout_paths = Vec::new();
    match find_thread_path_by_id_str(
        store.config.codex_home.as_path(),
        thread_id_str.as_str(),
        state_db_ctx.as_deref(),
    )
    .await
    {
        Ok(Some(path)) => rollout_paths.push(path),
        Ok(None) => {}
        Err(err) => {
            return Err(ThreadStoreError::InvalidRequest {
                message: format!("failed to locate thread id {thread_id}: {err}"),
            });
        }
    }
    match find_archived_thread_path_by_id_str(
        store.config.codex_home.as_path(),
        thread_id_str.as_str(),
        state_db_ctx.as_deref(),
    )
    .await
    {
        Ok(Some(path)) => {
            if !rollout_paths.contains(&path) {
                rollout_paths.push(path);
            }
        }
        Ok(None) => {}
        Err(err) => {
            return Err(ThreadStoreError::InvalidRequest {
                message: format!("failed to locate archived thread id {thread_id}: {err}"),
            });
        }
    }
    super::thread_history::delete_thread(store, thread_id).await?;

    let found_rollout_path = !rollout_paths.is_empty();
    for rollout_path in rollout_paths {
        delete_rollout_file(store, rollout_path.as_path(), thread_id)?;
    }
    remove_thread_name_entries(store.config.codex_home.as_path(), thread_id)
        .await
        .map_err(|err| ThreadStoreError::Internal {
            message: format!("failed to delete thread name index entries for {thread_id}: {err}"),
        })?;

    if !found_rollout_path {
        return Err(ThreadStoreError::ThreadNotFound { thread_id });
    }

    Ok(())
}

fn delete_rollout_file(
    store: &LocalThreadStore,
    rollout_path: &Path,
    thread_id: codex_protocol::ThreadId,
) -> ThreadStoreResult<bool> {
    let plain_path = codex_rollout::plain_rollout_path(rollout_path);
    let compressed_path = plain_path.with_extension("jsonl.zst");
    let deleted_plain = delete_rollout_path(store, plain_path.as_path(), thread_id)?;
    let deleted_compressed = delete_rollout_path(store, compressed_path.as_path(), thread_id)?;
    Ok(deleted_plain || deleted_compressed)
}

fn delete_rollout_path(
    store: &LocalThreadStore,
    rollout_path: &Path,
    thread_id: codex_protocol::ThreadId,
) -> ThreadStoreResult<bool> {
    let canonical_rollout_path = scoped_rollout_path(
        store.config.codex_home.join(SESSIONS_SUBDIR),
        rollout_path,
        "sessions",
    )
    .or_else(|_| {
        scoped_rollout_path(
            store.config.codex_home.join(ARCHIVED_SESSIONS_SUBDIR),
            rollout_path,
            "archived sessions",
        )
    })
    .or_else(|err| match rollout_path.try_exists() {
        Ok(false) => Ok(rollout_path.to_path_buf()),
        Ok(true) | Err(_) => Err(err),
    })?;
    matching_rollout_file_name(&canonical_rollout_path, thread_id, rollout_path)?;
    match std::fs::remove_file(&canonical_rollout_path) {
        Ok(()) => Ok(true),
        Err(err) if err.kind() == ErrorKind::NotFound => Ok(false),
        Err(err) => Err(ThreadStoreError::Internal {
            message: format!(
                "failed to delete rollout file `{}`: {err}",
                canonical_rollout_path.display()
            ),
        }),
    }
}

#[cfg(test)]
mod tests {
    use codex_protocol::SessionId;
    use codex_protocol::ThreadId;
    use codex_protocol::protocol::DurableTeamSessionMeta;
    use codex_protocol::protocol::HistoryPosition;
    use codex_protocol::protocol::ThreadHistoryMode;
    use codex_protocol::protocol::ThreadMemoryMode;
    use codex_utils_absolute_path::test_support::PathExt;
    use pretty_assertions::assert_eq;
    use tempfile::TempDir;
    use uuid::Uuid;

    use super::*;
    use crate::ResumeThreadParams;
    use crate::ThreadPersistenceMetadata;
    use crate::ThreadStore;
    use crate::durable_team_snapshot_path;
    use crate::local::LocalThreadStore;
    use crate::local::test_support::test_config;
    use crate::local::test_support::write_archived_session_file;
    use crate::local::test_support::write_session_file;
    use crate::local::test_support::write_session_file_with;
    use crate::local::test_support::write_session_file_with_history_mode;

    #[tokio::test]
    async fn delete_thread_removes_active_and_archived_rollouts() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let active_path =
            write_session_file(home.path(), "2025-01-03T12-00-00", Uuid::from_u128(301))
                .expect("session file");
        let compressed_path = active_path.with_extension("jsonl.zst");
        std::fs::write(&compressed_path, b"compressed sibling").expect("compressed sibling");
        let cases = [
            (Uuid::from_u128(301), active_path),
            (
                Uuid::from_u128(302),
                write_archived_session_file(
                    home.path(),
                    "2025-01-03T12-00-00",
                    Uuid::from_u128(302),
                )
                .expect("archived session file"),
            ),
        ];

        for (uuid, path) in cases {
            let thread_id = ThreadId::from_string(&uuid.to_string()).expect("valid thread id");
            store
                .delete_thread(DeleteThreadParams { thread_id })
                .await
                .expect("delete thread");

            assert!(!path.exists());
        }
        assert!(!compressed_path.exists());
    }

    #[tokio::test]
    async fn delete_threads_removes_the_durable_root_artifact_before_the_root_marker() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let root_uuid = Uuid::from_u128(321);
        let root_thread_id = ThreadId::from_string(&root_uuid.to_string()).expect("root id");
        let root_path = write_session_file(home.path(), "2025-01-03T12-00-00", root_uuid)
            .expect("root rollout");
        mark_rollout_as_durable_root(&root_path, root_thread_id);
        let child_uuid = Uuid::from_u128(322);
        let child_thread_id = ThreadId::from_string(&child_uuid.to_string()).expect("child id");
        let child_path = write_session_file(home.path(), "2025-01-03T12-00-01", child_uuid)
            .expect("child rollout");
        let snapshot_path = durable_team_snapshot_path(home.path(), root_thread_id);
        std::fs::create_dir_all(snapshot_path.parent().expect("snapshot parent"))
            .expect("snapshot directory");
        std::fs::write(&snapshot_path, b"committed Team snapshot").expect("snapshot");

        store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![root_thread_id, child_thread_id],
            })
            .await
            .expect("delete durable subtree");

        assert!(!snapshot_path.exists());
        assert!(!child_path.exists());
        assert!(!root_path.exists());
    }

    #[tokio::test]
    async fn durable_artifact_post_unlink_retry_removes_the_root_marker() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let root_uuid = Uuid::from_u128(326);
        let root_thread_id = ThreadId::from_string(&root_uuid.to_string()).expect("root id");
        let root_path = write_session_file(home.path(), "2025-01-03T12-00-00", root_uuid)
            .expect("root rollout");
        mark_rollout_as_durable_root(&root_path, root_thread_id);
        let snapshot_path = durable_team_snapshot_path(home.path(), root_thread_id);
        std::fs::create_dir_all(snapshot_path.parent().expect("snapshot parent"))
            .expect("snapshot directory left by the first unlink attempt");
        assert!(!snapshot_path.exists());

        store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![root_thread_id],
            })
            .await
            .expect("retry should prove artifact absence before deleting the Root marker");

        assert!(!root_path.exists());
        assert!(!snapshot_path.exists());
    }

    #[tokio::test]
    async fn durable_artifact_preflight_failure_keeps_rollouts_and_retry_completes() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let root_uuid = Uuid::from_u128(323);
        let root_thread_id = ThreadId::from_string(&root_uuid.to_string()).expect("root id");
        let root_path = write_session_file(home.path(), "2025-01-03T12-00-00", root_uuid)
            .expect("root rollout");
        mark_rollout_as_durable_root(&root_path, root_thread_id);
        let snapshot_path = durable_team_snapshot_path(home.path(), root_thread_id);
        std::fs::create_dir_all(&snapshot_path).expect("non-file artifact fixture");

        let error = store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![root_thread_id],
            })
            .await
            .expect_err("non-file Team artifact must fail closed");
        assert!(error.to_string().contains("not a regular file"));
        assert!(
            root_path.is_file(),
            "failed preflight must retain Root marker"
        );
        assert!(snapshot_path.is_dir());

        std::fs::remove_dir(&snapshot_path).expect("remove task-owned invalid artifact");
        std::fs::write(&snapshot_path, b"committed Team snapshot").expect("valid artifact shape");
        store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![root_thread_id],
            })
            .await
            .expect("same explicit delete should be retryable");
        assert!(!root_path.exists());
        assert!(!snapshot_path.exists());
    }

    #[tokio::test]
    async fn delete_threads_rejects_an_orphaned_durable_team_artifact() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let root_uuid = Uuid::from_u128(324);
        let root_thread_id = ThreadId::from_string(&root_uuid.to_string()).expect("root id");
        let root_path = write_session_file(home.path(), "2025-01-03T12-00-00", root_uuid)
            .expect("root rollout");
        mark_rollout_as_durable_root(&root_path, root_thread_id);
        let child_uuid = Uuid::from_u128(325);
        let child_thread_id = ThreadId::from_string(&child_uuid.to_string()).expect("child id");
        let child_path = write_session_file(home.path(), "2025-01-03T12-00-01", child_uuid)
            .expect("child rollout");
        let snapshot_path = durable_team_snapshot_path(home.path(), root_thread_id);
        std::fs::create_dir_all(snapshot_path.parent().expect("snapshot parent"))
            .expect("snapshot directory");
        std::fs::write(&snapshot_path, b"committed Team snapshot").expect("snapshot");
        std::fs::remove_file(&root_path).expect("simulate a missing canonical Root marker");

        let error = store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![child_thread_id, root_thread_id],
            })
            .await
            .expect_err("an orphaned Team artifact must not become terminal success");

        assert!(matches!(error, ThreadStoreError::Conflict { .. }));
        assert!(
            error
                .to_string()
                .contains("without a canonical Root marker")
        );
        assert!(snapshot_path.is_file());
        assert!(child_path.is_file());
    }

    fn mark_rollout_as_durable_root(path: &Path, root_thread_id: ThreadId) {
        let contents = std::fs::read_to_string(path).expect("read rollout fixture");
        let mut lines = contents.lines();
        let mut session_meta: serde_json::Value =
            serde_json::from_str(lines.next().expect("session metadata line"))
                .expect("parse session metadata");
        session_meta["payload"]["durable_team"] = serde_json::to_value(
            DurableTeamSessionMeta::current(SessionId::from(root_thread_id), root_thread_id),
        )
        .expect("serialize durable intent");
        let mut rewritten = serde_json::to_string(&session_meta).expect("serialize SessionMeta");
        rewritten.push('\n');
        for line in lines {
            rewritten.push_str(line);
            rewritten.push('\n');
        }
        std::fs::write(path, rewritten).expect("rewrite durable Root fixture");
    }

    #[tokio::test]
    async fn delete_thread_rejects_referenced_paginated_history() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let source_uuid = Uuid::from_u128(303);
        let source_thread_id =
            ThreadId::from_string(&source_uuid.to_string()).expect("valid source thread id");
        let source_path = write_session_file_with_history_mode(
            home.path(),
            "2025-01-03T12-00-00",
            source_uuid,
            ThreadHistoryMode::Paginated,
        )
        .expect("source session file");
        let child_path = write_session_file_with(
            home.path(),
            home.path().join(ARCHIVED_SESSIONS_SUBDIR),
            "2025-01-03T12-00-01",
            Uuid::from_u128(304),
            "Archived user message",
            Some("test-provider"),
            ThreadHistoryMode::Paginated,
        )
        .expect("child session file");
        set_history_base(
            child_path.as_path(),
            HistoryPosition {
                thread_id: source_thread_id,
                end_ordinal_exclusive: 1,
                end_byte_offset: std::fs::metadata(source_path.as_path())
                    .expect("source rollout metadata")
                    .len(),
            },
        );

        let err = store
            .delete_thread(DeleteThreadParams {
                thread_id: source_thread_id,
            })
            .await
            .expect_err("referenced source should not be deleted");

        assert_eq!(
            err.to_string(),
            format!(
                "invalid thread-store request: cannot delete thread {source_thread_id}: forked history still references it"
            )
        );
        assert!(source_path.exists());
    }

    #[tokio::test]
    async fn delete_thread_ignores_unreadable_reference_metadata() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let source_uuid = Uuid::from_u128(305);
        let source_thread_id =
            ThreadId::from_string(&source_uuid.to_string()).expect("valid source thread id");
        let source_path = write_session_file(home.path(), "2025-01-03T12-00-00", source_uuid)
            .expect("source session file");
        let unreadable_path = source_path.with_file_name(format!(
            "rollout-2025-01-03T12-00-01-{}.jsonl",
            Uuid::from_u128(306)
        ));
        std::fs::write(unreadable_path, "{not json}\n").expect("unreadable rollout metadata");

        store
            .delete_thread(DeleteThreadParams {
                thread_id: source_thread_id,
            })
            .await
            .expect("unreadable metadata should not block delete");

        assert!(!source_path.exists());
    }

    #[tokio::test]
    async fn delete_threads_allows_internal_history_references() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let source_uuid = Uuid::from_u128(307);
        let source_thread_id =
            ThreadId::from_string(&source_uuid.to_string()).expect("valid source thread id");
        let source_path = write_session_file_with_history_mode(
            home.path(),
            "2025-01-03T12-00-00",
            source_uuid,
            ThreadHistoryMode::Paginated,
        )
        .expect("source session file");
        let child_uuid = Uuid::from_u128(308);
        let child_thread_id =
            ThreadId::from_string(&child_uuid.to_string()).expect("valid child thread id");
        let child_path = write_session_file_with_history_mode(
            home.path(),
            "2025-01-03T12-00-01",
            child_uuid,
            ThreadHistoryMode::Paginated,
        )
        .expect("child session file");
        set_history_base(
            child_path.as_path(),
            HistoryPosition {
                thread_id: source_thread_id,
                end_ordinal_exclusive: 1,
                end_byte_offset: std::fs::metadata(source_path.as_path())
                    .expect("source rollout metadata")
                    .len(),
            },
        );

        store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![child_thread_id, source_thread_id],
            })
            .await
            .expect("internal references should not block batch delete");

        assert!(!source_path.exists());
        assert!(!child_path.exists());
    }

    #[tokio::test]
    async fn delete_threads_rejects_owned_descendants_before_deleting_anything() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let owner = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        for (parent_uuid, child_uuid, history_mode) in [
            (
                Uuid::from_u128(309),
                Uuid::from_u128(310),
                ThreadHistoryMode::Legacy,
            ),
            (
                Uuid::from_u128(312),
                Uuid::from_u128(313),
                ThreadHistoryMode::Paginated,
            ),
        ] {
            let parent_thread_id =
                ThreadId::from_string(&parent_uuid.to_string()).expect("valid parent thread id");
            let parent_path = write_session_file_with_history_mode(
                home.path(),
                "2025-01-03T12-00-00",
                parent_uuid,
                history_mode,
            )
            .expect("parent session file");
            let child_thread_id =
                ThreadId::from_string(&child_uuid.to_string()).expect("valid child thread id");
            let child_path = write_session_file_with_history_mode(
                home.path(),
                "2025-01-03T12-00-01",
                child_uuid,
                history_mode,
            )
            .expect("child session file");
            let _owner_guard = owner
                .writer_lock_coordinator
                .acquire(child_thread_id)
                .expect("acquire child writer lock");

            let error = store
                .delete_threads(DeleteThreadsParams {
                    thread_ids: vec![parent_thread_id, child_thread_id],
                })
                .await
                .expect_err("owned descendant should block deletion");

            assert!(matches!(error, ThreadStoreError::Conflict { .. }));
            assert!(parent_path.exists());
            assert!(child_path.exists());
        }
    }

    #[tokio::test]
    async fn delete_threads_rejects_owned_thread_before_rollout_materializes() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let owner = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let thread_id = ThreadId::default();
        let _owner_guard = owner
            .writer_lock_coordinator
            .acquire(thread_id)
            .expect("acquire writer lock before rollout exists");

        let error = store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![thread_id],
            })
            .await
            .expect_err("owned thread should block deletion before rollout exists");

        assert!(matches!(error, ThreadStoreError::Conflict { .. }));
    }

    #[tokio::test]
    async fn delete_threads_removes_rollout_with_unreadable_metadata() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let uuid = Uuid::from_u128(311);
        let thread_id = ThreadId::from_string(&uuid.to_string()).expect("valid thread id");
        let rollout_path =
            write_session_file(home.path(), "2025-01-03T12-00-00", uuid).expect("session file");
        std::fs::write(&rollout_path, "{not json}\n").expect("damage rollout metadata");

        store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![thread_id],
            })
            .await
            .expect("delete rollout with unreadable metadata");

        assert!(!rollout_path.exists());
    }

    #[tokio::test]
    async fn delete_threads_keeps_an_artifact_when_the_root_marker_is_unreadable() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let root_uuid = Uuid::from_u128(327);
        let root_thread_id = ThreadId::from_string(&root_uuid.to_string()).expect("root id");
        let root_path = write_session_file(home.path(), "2025-01-03T12-00-00", root_uuid)
            .expect("root rollout");
        std::fs::write(&root_path, "{not json}\n").expect("damage Root marker");
        let snapshot_path = durable_team_snapshot_path(home.path(), root_thread_id);
        std::fs::create_dir_all(snapshot_path.parent().expect("snapshot parent"))
            .expect("snapshot directory");
        std::fs::write(&snapshot_path, b"committed Team snapshot").expect("snapshot");

        let error = store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![root_thread_id],
            })
            .await
            .expect_err("unreadable Root marker must not orphan an existing Team artifact");

        assert!(matches!(error, ThreadStoreError::InvalidRequest { .. }));
        assert!(root_path.is_file());
        assert!(snapshot_path.is_file());
    }

    #[tokio::test]
    async fn delete_rollout_file_treats_vanished_path_as_already_deleted() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let uuid = Uuid::from_u128(305);
        let thread_id = ThreadId::from_string(&uuid.to_string()).expect("valid thread id");
        let path =
            write_session_file(home.path(), "2025-01-03T12-00-00", uuid).expect("session file");
        std::fs::remove_file(&path).expect("remove session file");

        assert!(!delete_rollout_file(&store, path.as_path(), thread_id).expect("delete rollout"));
    }

    #[tokio::test]
    async fn delete_thread_without_state_db_preserves_materialized_thread_history() {
        let home = TempDir::new().expect("temp dir");
        let config = test_config(home.path());
        let store = LocalThreadStore::new(config.clone(), /*state_db*/ None);
        let uuid = Uuid::from_u128(312);
        let thread_id = ThreadId::from_string(&uuid.to_string()).expect("valid thread id");
        let rollout_path = write_session_file_with_history_mode(
            home.path(),
            "2025-01-03T12-00-00",
            uuid,
            ThreadHistoryMode::Paginated,
        )
        .expect("session file");
        let pool = codex_state::open_thread_history_db(&config.sqlite)
            .await
            .expect("open existing thread history database");
        let thread_id_string = thread_id.to_string();
        sqlx::query(
            "INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status) VALUES (?, 'turn-1', 1, 'completed')",
        )
        .bind(thread_id_string.as_str())
        .execute(&pool)
        .await
        .expect("insert turn");
        sqlx::query(
            "INSERT INTO thread_items (thread_id, turn_id, item_id, rollout_ordinal, created_at_ms, item_json) VALUES (?, 'turn-1', 'item-1', 2, 1, '{}')",
        )
        .bind(thread_id_string.as_str())
        .execute(&pool)
        .await
        .expect("insert item");
        sqlx::query(
            "INSERT INTO thread_history_projection_state (thread_id, next_rollout_byte_offset, next_rollout_ordinal) VALUES (?, 3, 3)",
        )
        .bind(thread_id_string.as_str())
        .execute(&pool)
        .await
        .expect("insert projection state");

        let error = store
            .delete_thread(DeleteThreadParams { thread_id })
            .await
            .expect_err("projected history without a state database should prevent deletion");

        assert!(matches!(
            error,
            ThreadStoreError::Unsupported {
                operation: "paginated_history"
            }
        ));
        assert!(rollout_path.exists());
        let counts = sqlx::query_as::<_, (i64, i64, i64)>(
            r#"
SELECT
    (SELECT COUNT(*) FROM thread_turns WHERE thread_id = ?),
    (SELECT COUNT(*) FROM thread_items WHERE thread_id = ?),
    (SELECT COUNT(*) FROM thread_history_projection_state WHERE thread_id = ?)
            "#,
        )
        .bind(thread_id_string.as_str())
        .bind(thread_id_string.as_str())
        .bind(thread_id_string.as_str())
        .fetch_one(&pool)
        .await
        .expect("read preserved history rows");
        assert_eq!(counts, (1, 1, 1));
    }

    #[tokio::test]
    async fn delete_thread_rejects_live_writer_before_removing_materialized_history() {
        let home = TempDir::new().expect("temp dir");
        let config = test_config(home.path());
        let state_db = codex_state::StateRuntime::init(
            config.sqlite.clone(),
            config.default_model_provider_id.clone(),
        )
        .await
        .expect("initialize state database for materialized history");
        let store = LocalThreadStore::new(config, Some(state_db));
        let uuid = Uuid::from_u128(306);
        let thread_id = ThreadId::from_string(&uuid.to_string()).expect("valid thread id");
        let rollout_path = write_session_file_with_history_mode(
            home.path(),
            "2025-01-03T12-00-00",
            uuid,
            ThreadHistoryMode::Paginated,
        )
        .expect("session file");
        let pool = codex_state::open_thread_history_db(
            &codex_state::SqliteConfig::new_for_testing(home.path().abs()),
        )
        .await
        .expect("open thread history db");
        let thread_id_string = thread_id.to_string();
        sqlx::query(
            "INSERT INTO thread_turns (thread_id, turn_id, rollout_ordinal, status) VALUES (?, 'turn-1', 1, 'completed')",
        )
        .bind(thread_id_string.as_str())
        .execute(&pool)
        .await
        .expect("insert turn");
        sqlx::query(
            "INSERT INTO thread_items (thread_id, turn_id, item_id, rollout_ordinal, created_at_ms, item_json) VALUES (?, 'turn-1', 'item-1', 2, 1, '{}')",
        )
        .bind(thread_id_string.as_str())
        .execute(&pool)
        .await
        .expect("insert item");
        sqlx::query(
            "INSERT INTO thread_history_projection_state (thread_id, next_rollout_byte_offset, next_rollout_ordinal) VALUES (?, 3, 3)",
        )
        .bind(thread_id_string.as_str())
        .execute(&pool)
        .await
        .expect("insert projection state");

        store
            .resume_thread(ResumeThreadParams {
                thread_id,
                rollout_path: Some(rollout_path.clone()),
                history: None,
                include_archived: false,
                metadata: ThreadPersistenceMetadata {
                    cwd: Some(home.path().to_path_buf()),
                    model_provider: "test-provider".to_string(),
                    memory_mode: ThreadMemoryMode::Enabled,
                },
            })
            .await
            .expect("resume paginated writer before deletion");
        let lock_path = home
            .path()
            .join("thread-writer-locks")
            .join(format!("{thread_id}.lock"));
        assert!(lock_path.exists());

        let authority = store
            .writer_authority(thread_id)
            .await
            .expect("get Root writer authority");
        let permit = authority.begin_write().expect("begin Root write");

        let error = store
            .delete_thread(DeleteThreadParams { thread_id })
            .await
            .expect_err("a live writer must block deletion");
        assert!(matches!(error, ThreadStoreError::Conflict { .. }));
        assert!(lock_path.exists());
        assert!(rollout_path.exists());

        let preserved_counts = sqlx::query_as::<_, (i64, i64, i64)>(
            r#"
SELECT
    (SELECT COUNT(*) FROM thread_turns WHERE thread_id = ?),
    (SELECT COUNT(*) FROM thread_items WHERE thread_id = ?),
    (SELECT COUNT(*) FROM thread_history_projection_state WHERE thread_id = ?)
            "#,
        )
        .bind(thread_id_string.as_str())
        .bind(thread_id_string.as_str())
        .bind(thread_id_string.as_str())
        .fetch_one(&pool)
        .await
        .expect("read preserved history rows");
        assert_eq!(preserved_counts, (1, 1, 1));

        drop(permit);
        store
            .shutdown_thread(thread_id)
            .await
            .expect("shut down live writer");
        store
            .delete_thread(DeleteThreadParams { thread_id })
            .await
            .expect("delete closed thread");
        assert!(!lock_path.exists());
        assert!(!rollout_path.exists());
        let deleted_counts = sqlx::query_as::<_, (i64, i64, i64)>(
            r#"
SELECT
    (SELECT COUNT(*) FROM thread_turns WHERE thread_id = ?),
    (SELECT COUNT(*) FROM thread_items WHERE thread_id = ?),
    (SELECT COUNT(*) FROM thread_history_projection_state WHERE thread_id = ?)
            "#,
        )
        .bind(thread_id_string.as_str())
        .bind(thread_id_string.as_str())
        .bind(thread_id_string.as_str())
        .fetch_one(&pool)
        .await
        .expect("read deleted history rows");
        assert_eq!(deleted_counts, (0, 0, 0));
    }

    #[tokio::test]
    async fn delete_threads_rejects_same_store_live_writer_before_deleting_anything() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let cold_uuid = Uuid::from_u128(314);
        let cold_thread =
            ThreadId::from_string(&cold_uuid.to_string()).expect("valid cold thread id");
        let cold_path = write_session_file(home.path(), "2025-01-03T12-00-00", cold_uuid)
            .expect("cold session file");
        let live_uuid = Uuid::from_u128(315);
        let live_thread =
            ThreadId::from_string(&live_uuid.to_string()).expect("valid live thread id");
        let live_path = write_session_file(home.path(), "2025-01-03T12-00-01", live_uuid)
            .expect("live session file");
        store
            .resume_thread(ResumeThreadParams {
                thread_id: live_thread,
                rollout_path: Some(live_path.clone()),
                history: None,
                include_archived: false,
                metadata: ThreadPersistenceMetadata {
                    cwd: Some(home.path().to_path_buf()),
                    model_provider: "test-provider".to_string(),
                    memory_mode: ThreadMemoryMode::Enabled,
                },
            })
            .await
            .expect("resume live writer");
        let authority = store
            .writer_authority(live_thread)
            .await
            .expect("get live Root authority");
        let permit = authority.begin_write().expect("begin live Root write");

        let error = store
            .delete_threads(DeleteThreadsParams {
                thread_ids: vec![cold_thread, live_thread],
            })
            .await
            .expect_err("one live writer must reject the whole batch");
        assert!(matches!(error, ThreadStoreError::Conflict { .. }));
        assert!(cold_path.exists());
        assert!(live_path.exists());
        assert!(authority.begin_write().is_ok());

        drop(permit);
        store
            .shutdown_thread(live_thread)
            .await
            .expect("shut down live writer");
    }

    #[tokio::test]
    async fn delete_thread_reports_missing_thread() {
        let home = TempDir::new().expect("temp dir");
        let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
        let thread_id =
            ThreadId::from_string("00000000-0000-0000-0000-000000000304").expect("valid thread id");

        let err = store
            .delete_thread(DeleteThreadParams { thread_id })
            .await
            .expect_err("missing thread should fail");
        assert_eq!(
            err.to_string(),
            "thread 00000000-0000-0000-0000-000000000304 not found"
        );
    }

    fn set_history_base(path: &Path, history_base: HistoryPosition) {
        let mut session_meta: serde_json::Value = serde_json::from_str(
            std::fs::read_to_string(path)
                .expect("read session file")
                .lines()
                .next()
                .expect("session metadata"),
        )
        .expect("parse session metadata");
        session_meta["payload"]["history_base"] =
            serde_json::to_value(history_base).expect("serialize history base");
        std::fs::write(path, format!("{session_meta}\n")).expect("write session file");
    }
}
