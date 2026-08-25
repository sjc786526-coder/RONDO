use codex_protocol::ThreadId;
use std::path::Path;
use std::path::PathBuf;

const DURABLE_TEAM_STATE_DIRECTORY: &str = "team-sessions/v1";
const DURABLE_TEAM_STATE_EXTENSION: &str = "team-state";

/// Returns the associated durable-Team snapshot path for a canonical Root rollout.
///
/// Keeping the path constructor in the thread-store crate lets live Team persistence and cold
/// thread deletion share one filesystem convention without creating a second registry.
pub fn durable_team_snapshot_path(codex_home: &Path, root_thread_id: ThreadId) -> PathBuf {
    codex_home
        .join(DURABLE_TEAM_STATE_DIRECTORY)
        .join(format!("{root_thread_id}.{DURABLE_TEAM_STATE_EXTENSION}"))
}
