//! Durable Team storage bound to the canonical Root thread writer.
//!
//! The Team crate owns the versioned snapshot and domain validation. This module supplies the
//! local committed medium and adapts the thread store's existing live-writer capability; it does
//! not introduce another lock or writer identity.

use codex_protocol::ThreadId;
use codex_team_state::DurableTeamIdentity;
use codex_team_state::TeamClosePermit;
use codex_team_state::TeamDurabilityError;
use codex_team_state::TeamDurabilityFuture;
use codex_team_state::TeamWriteAuthority;
use codex_team_state::TeamWritePermit;
use codex_team_state::committed_snapshot_generation;
use codex_thread_store::RootClosePermit;
use codex_thread_store::RootWritePermit;
use codex_thread_store::RootWriterAuthority;
use codex_thread_store::ThreadStore;
use codex_thread_store::ThreadStoreError;
#[cfg(unix)]
use std::fs::File;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

const TEAM_STATE_DIRECTORY: &str = "team-sessions/v1";
const TEAM_STATE_EXTENSION: &str = "team-state";

pub(crate) async fn root_team_write_authority(
    thread_store: &Arc<dyn ThreadStore>,
    codex_home: &Path,
    identity: DurableTeamIdentity,
) -> Result<Arc<dyn TeamWriteAuthority>, TeamDurabilityError> {
    let root_authority = thread_store
        .writer_authority(identity.root_thread_id())
        .await
        .map_err(map_thread_store_error)?;
    if root_authority.thread_id() != identity.root_thread_id() {
        return Err(TeamDurabilityError::unavailable(
            "thread store returned authority for the wrong Root thread",
        ));
    }
    Ok(Arc::new(LocalTeamWriteAuthority {
        identity,
        root_authority,
        snapshot_path: snapshot_path(codex_home, identity.root_thread_id()),
    }))
}

pub(crate) fn committed_snapshot_exists(
    codex_home: &Path,
    root_thread_id: ThreadId,
) -> Result<bool, TeamDurabilityError> {
    snapshot_path(codex_home, root_thread_id)
        .try_exists()
        .map_err(|error| {
            TeamDurabilityError::unavailable(format!(
                "cannot inspect durable Team snapshot: {error}"
            ))
        })
}

#[allow(dead_code)] // Narrow S1 read entry; control-plane consumers remain out of Plan 069 scope.
pub(crate) fn read_committed_snapshot(
    codex_home: &Path,
    root_thread_id: ThreadId,
) -> Result<Vec<u8>, TeamDurabilityError> {
    std::fs::read(snapshot_path(codex_home, root_thread_id)).map_err(|error| {
        TeamDurabilityError::unavailable(format!("cannot read durable Team snapshot: {error}"))
    })
}

fn snapshot_path(codex_home: &Path, root_thread_id: ThreadId) -> PathBuf {
    codex_home
        .join(TEAM_STATE_DIRECTORY)
        .join(format!("{root_thread_id}.{TEAM_STATE_EXTENSION}"))
}

struct LocalTeamWriteAuthority {
    identity: DurableTeamIdentity,
    root_authority: RootWriterAuthority,
    snapshot_path: PathBuf,
}

impl TeamWriteAuthority for LocalTeamWriteAuthority {
    fn identity(&self) -> DurableTeamIdentity {
        self.identity
    }

    fn begin_write(&self) -> Result<Box<dyn TeamWritePermit>, TeamDurabilityError> {
        let root_permit = self
            .root_authority
            .begin_write()
            .map_err(map_thread_store_error)?;
        Ok(Box::new(LocalTeamWritePermit {
            identity: self.identity,
            root_permit,
            snapshot_path: self.snapshot_path.clone(),
        }))
    }

    fn begin_close(&self) -> TeamDurabilityFuture<'_, Box<dyn TeamClosePermit>> {
        Box::pin(async move {
            let root_permit = self
                .root_authority
                .begin_close()
                .await
                .map_err(map_thread_store_error)?;
            Ok(Box::new(LocalTeamClosePermit {
                root_permit: Some(root_permit),
            }) as Box<dyn TeamClosePermit>)
        })
    }
}

struct LocalTeamWritePermit {
    identity: DurableTeamIdentity,
    #[allow(dead_code)]
    root_permit: RootWritePermit,
    snapshot_path: PathBuf,
}

impl TeamWritePermit for LocalTeamWritePermit {
    fn read_snapshot(&mut self) -> Result<Option<Vec<u8>>, TeamDurabilityError> {
        match std::fs::read(&self.snapshot_path) {
            Ok(snapshot) => Ok(Some(snapshot)),
            Err(error) if error.kind() == ErrorKind::NotFound => Ok(None),
            Err(error) => Err(TeamDurabilityError::unavailable(format!(
                "cannot read durable Team snapshot: {error}"
            ))),
        }
    }

    fn compare_and_swap(
        &mut self,
        expected_generation: u64,
        snapshot: Vec<u8>,
    ) -> Result<(), TeamDurabilityError> {
        replace_snapshot(
            self.identity,
            &self.snapshot_path,
            expected_generation,
            &snapshot,
        )
    }
}

struct LocalTeamClosePermit {
    root_permit: Option<RootClosePermit>,
}

impl TeamClosePermit for LocalTeamClosePermit {
    fn abort(mut self: Box<Self>) -> TeamDurabilityFuture<'static, ()> {
        let root_permit = self.root_permit.take();
        Box::pin(async move {
            root_permit
                .ok_or_else(|| TeamDurabilityError::unavailable("Team close permit was consumed"))?
                .abort()
                .map_err(map_thread_store_error)
        })
    }

    fn complete(mut self: Box<Self>) -> TeamDurabilityFuture<'static, ()> {
        let root_permit = self.root_permit.take();
        Box::pin(async move {
            root_permit
                .ok_or_else(|| TeamDurabilityError::unavailable("Team close permit was consumed"))?
                .complete()
                .map_err(map_thread_store_error)
        })
    }
}

fn replace_snapshot(
    identity: DurableTeamIdentity,
    snapshot_path: &Path,
    expected_generation: u64,
    snapshot: &[u8],
) -> Result<(), TeamDurabilityError> {
    let parent = snapshot_path.parent().ok_or_else(|| {
        TeamDurabilityError::unavailable("durable Team snapshot path has no parent")
    })?;
    std::fs::create_dir_all(parent).map_err(|error| {
        TeamDurabilityError::unavailable(format!("cannot create durable Team directory: {error}"))
    })?;

    match std::fs::read(snapshot_path) {
        Ok(_) if expected_generation == 0 => {
            return Err(TeamDurabilityError::conflict(
                "durable Team snapshot already exists at initial commit",
            ));
        }
        Ok(committed) => {
            let actual_generation = committed_snapshot_generation(identity, &committed)?;
            if actual_generation != expected_generation {
                return Err(TeamDurabilityError::conflict(format!(
                    "durable Team generation changed: expected {expected_generation}, found {actual_generation}"
                )));
            }
        }
        Err(error) if error.kind() == ErrorKind::NotFound && expected_generation == 0 => {}
        Err(error) if error.kind() == ErrorKind::NotFound => {
            return Err(TeamDurabilityError::conflict(
                "durable Team snapshot disappeared before commit",
            ));
        }
        Err(error) => {
            return Err(TeamDurabilityError::unavailable(format!(
                "cannot read durable Team snapshot before commit: {error}"
            )));
        }
    }

    let mut temporary = tempfile::NamedTempFile::new_in(parent).map_err(|error| {
        TeamDurabilityError::unavailable(format!(
            "cannot create durable Team temporary snapshot: {error}"
        ))
    })?;
    temporary.write_all(snapshot).map_err(|error| {
        TeamDurabilityError::unavailable(format!(
            "cannot write durable Team temporary snapshot: {error}"
        ))
    })?;
    temporary.as_file_mut().sync_all().map_err(|error| {
        TeamDurabilityError::unavailable(format!(
            "cannot sync durable Team temporary snapshot: {error}"
        ))
    })?;
    temporary.persist(snapshot_path).map_err(|error| {
        TeamDurabilityError::unknown(format!(
            "atomic durable Team replacement had an indeterminate result: {}",
            error.error
        ))
    })?;

    #[cfg(unix)]
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| {
            TeamDurabilityError::unknown(format!(
                "durable Team replacement reached the file but directory sync failed: {error}"
            ))
        })?;
    Ok(())
}

fn map_thread_store_error(error: ThreadStoreError) -> TeamDurabilityError {
    match error {
        ThreadStoreError::Conflict { message } => TeamDurabilityError::conflict(message),
        ThreadStoreError::Unsupported { operation } => TeamDurabilityError::unavailable(format!(
            "thread store does not support canonical Root authority ({operation})"
        )),
        error => TeamDurabilityError::unavailable(error.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use std::process::Command;

    use codex_protocol::SessionId;
    use codex_protocol::models::BaseInstructions;
    use codex_protocol::protocol::EventMsg;
    use codex_protocol::protocol::MultiAgentVersion;
    use codex_protocol::protocol::RolloutItem;
    use codex_protocol::protocol::SessionSource;
    use codex_protocol::protocol::ThreadHistoryMode;
    use codex_protocol::protocol::ThreadMemoryMode;
    use codex_protocol::protocol::UserMessageEvent;
    use codex_team_state::ParticipantRole;
    use codex_team_state::PublishRequest;
    use codex_team_state::PublishTarget;
    use codex_team_state::Submission;
    use codex_team_state::TeamDurabilityStatus;
    use codex_team_state::TeamStateHandle;
    use codex_thread_store::CreateThreadParams;
    use codex_thread_store::LiveThread;
    use codex_thread_store::LocalThreadStore;
    use codex_thread_store::LocalThreadStoreConfig;
    use codex_thread_store::ResumeThreadParams;
    use codex_thread_store::ThreadPersistenceMetadata;
    use codex_utils_absolute_path::test_support::PathExt;
    use tempfile::TempDir;

    use super::*;

    const PROCESS_TEST: &str =
        "team::durable::tests::durable_team_recovers_and_continues_in_a_new_process";
    const PROCESS_MODE: &str = "CODEX_DURABLE_TEAM_PROCESS_MODE";
    const PROCESS_HOME: &str = "CODEX_DURABLE_TEAM_PROCESS_HOME";
    const PROCESS_ROOT: &str = "CODEX_DURABLE_TEAM_PROCESS_ROOT";
    const PROCESS_SESSION: &str = "CODEX_DURABLE_TEAM_PROCESS_SESSION";

    #[tokio::test]
    async fn durable_team_recovers_and_continues_in_a_new_process() {
        if let Ok(mode) = std::env::var(PROCESS_MODE) {
            run_process_stage(&mode).await;
            return;
        }

        let home = TempDir::new().expect("temp durable Team home");
        let root_thread_id = ThreadId::new();
        let session_id = SessionId::new();
        let identity = DurableTeamIdentity::new(session_id, root_thread_id);

        run_child_stage(home.path(), identity, "create");
        let first = committed_reader(home.path(), identity);
        let first_view = first
            .snapshot_for(root_thread_id)
            .expect("first committed view");
        assert_eq!(first_view.events.len(), 1);
        assert_eq!(first_view.events[0].title, "first process");
        let original_instance = first.instance();

        run_child_stage(home.path(), identity, "resume");
        let second = committed_reader(home.path(), identity);
        let second_view = second
            .snapshot_for(root_thread_id)
            .expect("continued committed view");
        assert_eq!(second.instance(), original_instance);
        assert_eq!(second_view.events.len(), 2);
        assert_eq!(
            second_view
                .events
                .iter()
                .map(|event| event.title.as_str())
                .collect::<Vec<_>>(),
            vec!["first process", "second process"]
        );
        assert!(matches!(
            second.durability_status(),
            TeamDurabilityStatus::ReadOnly { .. }
        ));
        assert!(
            second
                .publish(
                    root_thread_id,
                    &Submission {
                        based_on: second.revision(),
                        request_id: "read-only-write".to_string(),
                    },
                    publish_request("must not commit"),
                )
                .is_err(),
            "a non-owner committed reader must not gain write authority"
        );
    }

    async fn run_process_stage(mode: &str) {
        let home = PathBuf::from(std::env::var_os(PROCESS_HOME).expect("process home"));
        let root_thread_id =
            ThreadId::from_string(&std::env::var(PROCESS_ROOT).expect("process Root thread id"))
                .expect("valid process Root thread id");
        let session_id =
            SessionId::from_string(&std::env::var(PROCESS_SESSION).expect("process Session id"))
                .expect("valid process Session id");
        let identity = DurableTeamIdentity::new(session_id, root_thread_id);
        let thread_store = local_thread_store(&home);

        let live_thread = match mode {
            "create" => LiveThread::create(
                Arc::clone(&thread_store),
                create_thread_params(&home, identity),
            )
            .await
            .expect("create persisted Root thread"),
            "resume" => {
                let rollout_path = codex_rollout::find_thread_path_by_id_str(
                    &home,
                    &root_thread_id.to_string(),
                    None,
                )
                .await
                .expect("locate persisted Root thread")
                .expect("persisted Root rollout exists");
                LiveThread::resume(
                    Arc::clone(&thread_store),
                    ThreadHistoryMode::Legacy,
                    ResumeThreadParams {
                        thread_id: root_thread_id,
                        rollout_path: Some(rollout_path),
                        history: None,
                        include_archived: false,
                        metadata: thread_metadata(&home),
                    },
                )
                .await
                .expect("resume persisted Root thread")
            }
            other => panic!("unexpected durable Team process mode {other}"),
        };
        let authority = root_team_write_authority(&thread_store, &home, identity)
            .await
            .expect("derive canonical Root authority");
        let team = match mode {
            "create" => TeamStateHandle::create_durable(authority).expect("create durable Team"),
            "resume" => TeamStateHandle::resume_durable(authority).expect("resume durable Team"),
            _ => unreachable!("mode checked above"),
        };
        team.register_durable_participant(
            root_thread_id,
            ParticipantRole::Root,
            "/root".to_string(),
        )
        .expect("register canonical Root");
        let expected_events = usize::from(mode == "resume");
        assert_eq!(
            team.snapshot_for(root_thread_id)
                .expect("pre-mutation Team view")
                .events
                .len(),
            expected_events
        );
        team.publish(
            root_thread_id,
            &Submission {
                based_on: team.revision(),
                request_id: format!("{mode}-publish"),
            },
            publish_request(if mode == "create" {
                "first process"
            } else {
                "second process"
            }),
        )
        .expect("durably publish from process");
        live_thread
            .append_items(&[RolloutItem::EventMsg(EventMsg::UserMessage(
                UserMessageEvent {
                    client_id: None,
                    message: format!("durable Team {mode} process"),
                    images: None,
                    local_images: Vec::new(),
                    text_elements: Vec::new(),
                    ..Default::default()
                },
            ))])
            .await
            .expect("materialize Root rollout");
        live_thread.flush().await.expect("flush Root rollout");
        // Deliberately rely on process exit rather than a graceful Team close. The next process
        // must acquire the same native Root writer, hydrate the committed Team, and continue it.
    }

    fn run_child_stage(home: &Path, identity: DurableTeamIdentity, mode: &str) {
        let output = Command::new(std::env::current_exe().expect("current test executable"))
            .arg("--exact")
            .arg(PROCESS_TEST)
            .arg("--nocapture")
            .env(PROCESS_MODE, mode)
            .env(PROCESS_HOME, home)
            .env(PROCESS_ROOT, identity.root_thread_id().to_string())
            .env(PROCESS_SESSION, identity.session_id().to_string())
            .output()
            .expect("run durable Team child process");
        assert!(
            output.status.success(),
            "durable Team child failed: status={:?}\nstdout={}\nstderr={}",
            output.status.code(),
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr),
        );
    }

    fn committed_reader(home: &Path, identity: DurableTeamIdentity) -> TeamStateHandle {
        let committed = read_committed_snapshot(home, identity.root_thread_id())
            .expect("read committed Team snapshot");
        TeamStateHandle::from_committed_snapshot(identity, &committed)
            .expect("hydrate non-owner committed reader")
    }

    fn local_thread_store(home: &Path) -> Arc<dyn ThreadStore> {
        Arc::new(LocalThreadStore::new(
            LocalThreadStoreConfig {
                codex_home: home.to_path_buf(),
                sqlite: codex_state::SqliteConfig::new_for_testing(home.abs()),
                default_model_provider_id: "test-provider".to_string(),
            },
            None,
        ))
    }

    fn create_thread_params(home: &Path, identity: DurableTeamIdentity) -> CreateThreadParams {
        CreateThreadParams {
            session_id: identity.session_id(),
            thread_id: identity.root_thread_id(),
            extra_config: None,
            forked_from_id: None,
            parent_thread_id: None,
            source: SessionSource::Exec,
            thread_source: None,
            originator: "durable-team-process-test".to_string(),
            base_instructions: BaseInstructions::default(),
            dynamic_tools: Vec::new(),
            selected_capability_roots: Vec::new(),
            multi_agent_version: Some(MultiAgentVersion::V2),
            history_mode: ThreadHistoryMode::Legacy,
            history_base: None,
            subagent_history_start_ordinal: None,
            initial_window_id: uuid::Uuid::now_v7().to_string(),
            metadata: thread_metadata(home),
        }
    }

    fn thread_metadata(home: &Path) -> ThreadPersistenceMetadata {
        ThreadPersistenceMetadata {
            cwd: Some(home.to_path_buf()),
            model_provider: "test-provider".to_string(),
            memory_mode: ThreadMemoryMode::Disabled,
        }
    }

    fn publish_request(title: &str) -> PublishRequest {
        PublishRequest {
            target: PublishTarget::NewEvent {
                title: title.to_string(),
            },
            summary: format!("committed from {title}"),
            handoff: None,
        }
    }
}
