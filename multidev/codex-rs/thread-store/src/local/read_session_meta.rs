use std::io;
use std::path::Path;
use std::path::PathBuf;

use codex_protocol::protocol::SessionMeta;

use super::LocalThreadStore;
use crate::ReadSessionMetaError;
use crate::ReadSessionMetaParams;

pub(super) async fn read_session_meta(
    store: &LocalThreadStore,
    params: ReadSessionMetaParams,
) -> Result<SessionMeta, ReadSessionMetaError> {
    let thread_id = params.thread_id;
    let state_db = store
        .state_db()
        .await
        .ok_or(ReadSessionMetaError::Unsupported {
            operation: "read_session_meta",
        })?;
    let active_path = find_rollout_candidate(state_db.as_ref(), thread_id, false).await?;
    let indexed_path = if active_path.is_some() || !params.include_archived {
        active_path
    } else {
        find_rollout_candidate(state_db.as_ref(), thread_id, true).await?
    }
    .ok_or(ReadSessionMetaError::NotFound { thread_id })?;
    let path = resolve_indexed_rollout_path_for_query(thread_id, indexed_path.as_path()).await?;
    let display_path = path.clone();
    let meta_line = tokio::task::spawn_blocking(move || {
        codex_rollout::read_session_meta_line_blocking(path.as_path())
    })
    .await
    .map_err(|error| ReadSessionMetaError::Unavailable {
        thread_id,
        message: format!(
            "failed to join bounded metadata read for {}: {error}",
            display_path.display()
        ),
    })?
    .map_err(|error| map_head_read_error(thread_id, display_path.as_path(), error))?;
    if meta_line.meta.id != thread_id {
        return Err(ReadSessionMetaError::IdentityMismatch {
            requested_thread_id: thread_id,
            actual_thread_id: meta_line.meta.id,
        });
    }
    Ok(meta_line.meta)
}

async fn find_rollout_candidate(
    state_db: &codex_state::StateRuntime,
    thread_id: codex_protocol::ThreadId,
    archived: bool,
) -> Result<Option<PathBuf>, ReadSessionMetaError> {
    state_db
        .find_rollout_path_by_id_for_query(thread_id, Some(archived))
        .await
        .map_err(|error| match error {
            codex_state::FindThreadRolloutPathError::Unavailable { message } => {
                ReadSessionMetaError::Unavailable {
                    thread_id,
                    message: format!(
                        "failed to query {} rollout locator: {message}",
                        if archived { "archived" } else { "active" }
                    ),
                }
            }
            codex_state::FindThreadRolloutPathError::Corrupt { message } => {
                ReadSessionMetaError::Corrupt {
                    thread_id,
                    message: format!(
                        "failed to decode {} rollout locator: {message}",
                        if archived { "archived" } else { "active" }
                    ),
                }
            }
        })
}

pub(super) async fn resolve_indexed_rollout_path_for_query(
    thread_id: codex_protocol::ThreadId,
    indexed_path: &Path,
) -> Result<PathBuf, ReadSessionMetaError> {
    let plain_path = codex_rollout::plain_rollout_path(indexed_path);
    let Some(file_name) = plain_path.file_name() else {
        return Err(ReadSessionMetaError::Corrupt {
            thread_id,
            message: format!(
                "state DB rollout locator has no file name: {}",
                indexed_path.display()
            ),
        });
    };
    let mut compressed_file_name = file_name.to_os_string();
    compressed_file_name.push(".zst");
    let compressed_path = plain_path.with_file_name(compressed_file_name);

    for candidate in [&plain_path, &compressed_path] {
        match tokio::fs::metadata(candidate).await {
            Ok(metadata) if metadata.is_file() => return Ok(candidate.clone()),
            Ok(_) => continue,
            Err(error) => map_rollout_metadata_error(thread_id, candidate, error)?,
        }
    }

    Err(ReadSessionMetaError::Corrupt {
        thread_id,
        message: format!(
            "state DB points to missing or non-file rollout {}",
            indexed_path.display()
        ),
    })
}

pub(super) fn map_rollout_metadata_error(
    thread_id: codex_protocol::ThreadId,
    path: &Path,
    error: io::Error,
) -> Result<(), ReadSessionMetaError> {
    if matches!(
        error.kind(),
        io::ErrorKind::NotFound | io::ErrorKind::NotADirectory
    ) {
        return Ok(());
    }
    Err(ReadSessionMetaError::Unavailable {
        thread_id,
        message: format!("failed to inspect rollout {}: {error}", path.display()),
    })
}

pub(super) fn map_head_read_error(
    thread_id: codex_protocol::ThreadId,
    path: &Path,
    error: io::Error,
) -> ReadSessionMetaError {
    let message = format!(
        "failed to read canonical metadata from {}: {error}",
        path.display()
    );
    let is_corrupt = match error.kind() {
        io::ErrorKind::InvalidData | io::ErrorKind::UnexpectedEof => true,
        // The rollout head helper currently uses custom `io::Error::other` values for semantic
        // header failures such as empty rollouts or a response item preceding SessionMeta. Keep
        // that explicit helper boundary typed as corruption, while OS-backed Other errors remain
        // source failures. Do not inspect diagnostic strings to reclassify either case.
        io::ErrorKind::Other => error.raw_os_error().is_none(),
        io::ErrorKind::NotFound
        | io::ErrorKind::PermissionDenied
        | io::ErrorKind::TimedOut
        | io::ErrorKind::Interrupted
        | io::ErrorKind::WouldBlock => false,
        _ => false,
    };
    if is_corrupt {
        ReadSessionMetaError::Corrupt { thread_id, message }
    } else {
        ReadSessionMetaError::Unavailable { thread_id, message }
    }
}
