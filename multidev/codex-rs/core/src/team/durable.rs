//! Durable Team storage bound to the canonical Root thread writer.
//!
//! The Team crate owns the versioned snapshot and domain validation. This module supplies the
//! local committed medium and adapts the thread store's existing live-writer capability; it does
//! not introduce another lock or writer identity.

use codex_protocol::ThreadId;
use codex_protocol::protocol::DurableTeamSessionMeta;
use codex_protocol::protocol::SessionMeta;
use codex_team_state::DurableTeamIdentity;
use codex_team_state::MAX_ENCODED_SNAPSHOT_BYTES;
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
use std::fs::File;
use std::io::ErrorKind;
use std::io::Read;
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
    intent: DurableTeamSessionMeta,
) -> Result<Arc<dyn TeamWriteAuthority>, TeamDurabilityError> {
    validate_intent(identity, intent)?;
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

/// True when the Team backend contains a committed snapshot. A malformed or oversized artifact is
/// an error, never evidence that a legacy resume is safe. Canonical durable intent is read from the
/// independently persisted Root SessionMeta by the caller.
pub(crate) fn durable_team_snapshot_exists(
    codex_home: &Path,
    identity: DurableTeamIdentity,
) -> Result<bool, TeamDurabilityError> {
    let snapshot = read_snapshot_file(&snapshot_path(codex_home, identity.root_thread_id()))?;
    if let Some(snapshot) = snapshot.as_ref() {
        committed_snapshot_generation(identity, snapshot)?;
    }
    Ok(snapshot.is_some())
}

/// Require a complete, cross-validated lineage before writable cold resume.
pub(crate) fn validate_durable_team_resume(
    codex_home: &Path,
    session_meta: &SessionMeta,
    identity: DurableTeamIdentity,
) -> Result<(), TeamDurabilityError> {
    validate_session_intent(session_meta, identity)?;
    let snapshot = read_snapshot_file(&snapshot_path(codex_home, identity.root_thread_id()))?
        .ok_or_else(|| {
            TeamDurabilityError::unavailable(
                "durable Team Session intent exists but its first committed snapshot is missing",
            )
        })?;
    committed_snapshot_generation(identity, &snapshot)?;
    Ok(())
}

pub(crate) fn validate_session_intent(
    session_meta: &SessionMeta,
    identity: DurableTeamIdentity,
) -> Result<(), TeamDurabilityError> {
    if session_meta.session_id != identity.session_id()
        || session_meta.id != identity.root_thread_id()
    {
        return Err(TeamDurabilityError::IdentityMismatch);
    }
    let intent = session_meta.durable_team.ok_or_else(|| {
        TeamDurabilityError::conflict(
            "persisted Session has no durable Team intent; legacy Sessions are not upgraded",
        )
    })?;
    validate_intent(identity, intent)
}

#[allow(dead_code)] // Strict wrapper retained for S1 invariant tests and future required reads.
pub(crate) fn read_committed_snapshot(
    codex_home: &Path,
    session_meta: &SessionMeta,
    identity: DurableTeamIdentity,
) -> Result<Vec<u8>, TeamDurabilityError> {
    read_committed_snapshot_if_present(codex_home, session_meta, identity)?.ok_or_else(|| {
        TeamDurabilityError::unavailable("cannot read durable Team snapshot: file is missing")
    })
}

pub(crate) fn read_committed_snapshot_if_present(
    codex_home: &Path,
    session_meta: &SessionMeta,
    identity: DurableTeamIdentity,
) -> Result<Option<Vec<u8>>, TeamDurabilityError> {
    validate_session_intent(session_meta, identity)?;
    read_committed_snapshot_after_validated_intent(codex_home, identity)
}

/// Read the committed medium after the caller has validated the canonical SessionMeta marker.
/// Keeping marker validation out of this step lets read-side callers preserve marker and snapshot
/// failures as separate typed axes without parsing diagnostics.
pub(crate) fn read_committed_snapshot_after_validated_intent(
    codex_home: &Path,
    identity: DurableTeamIdentity,
) -> Result<Option<Vec<u8>>, TeamDurabilityError> {
    read_snapshot_file(&snapshot_path(codex_home, identity.root_thread_id()))
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
            let mut root_permit = self
                .root_authority
                .begin_close()
                .await
                .map_err(map_thread_store_error)?;
            root_permit
                .require_session_meta(DurableTeamSessionMeta::current(
                    self.identity.session_id(),
                    self.identity.root_thread_id(),
                ))
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
        let snapshot = read_snapshot_file(&self.snapshot_path)?;
        if snapshot.is_some() {
            // A fresh Team intentionally has neither marker nor generation zero. Once any
            // committed snapshot exists, every owner read must prove the independent Root marker.
            self.validate_root_intent()?;
            sync_parent_directory(&self.snapshot_path, "durable Team snapshot")?;
        }
        Ok(snapshot)
    }

    fn compare_and_swap(
        &mut self,
        expected_generation: u64,
        snapshot: Vec<u8>,
    ) -> Result<(), TeamDurabilityError> {
        self.validate_root_intent()?;
        replace_snapshot(
            self.identity,
            &self.snapshot_path,
            expected_generation,
            &snapshot,
        )?;
        if let Err(error) = self.validate_root_intent() {
            // The Team snapshot is already complete, but lineage disappeared before the success
            // boundary. Report an indeterminate commit so reconciliation may later accept either
            // generation after the canonical marker becomes readable again.
            return Err(TeamDurabilityError::unknown(format!(
                "canonical Root SessionMeta became unreadable after Team snapshot replacement: {error}"
            )));
        }
        Ok(())
    }
}

impl LocalTeamWritePermit {
    fn validate_root_intent(&self) -> Result<(), TeamDurabilityError> {
        let session_meta = self
            .root_permit
            .read_session_meta()
            .map_err(map_thread_store_error)?;
        validate_session_intent(&session_meta, self.identity)
    }
}

fn validate_intent(
    expected: DurableTeamIdentity,
    intent: DurableTeamSessionMeta,
) -> Result<(), TeamDurabilityError> {
    if intent.version != DurableTeamSessionMeta::CURRENT_VERSION {
        return Err(TeamDurabilityError::UnsupportedVersion {
            found: intent.version,
            supported: DurableTeamSessionMeta::CURRENT_VERSION,
        });
    }
    if intent.session_id != expected.session_id()
        || intent.root_thread_id != expected.root_thread_id()
    {
        return Err(TeamDurabilityError::IdentityMismatch);
    }
    Ok(())
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

fn read_snapshot_file(path: &Path) -> Result<Option<Vec<u8>>, TeamDurabilityError> {
    read_bounded_file(path, MAX_ENCODED_SNAPSHOT_BYTES, "durable Team snapshot")
}

fn read_bounded_file(
    path: &Path,
    max_bytes: usize,
    label: &str,
) -> Result<Option<Vec<u8>>, TeamDurabilityError> {
    let file = match File::open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(TeamDurabilityError::unavailable(format!(
                "cannot open {label}: {error}"
            )));
        }
    };
    let metadata = file.metadata().map_err(|error| {
        TeamDurabilityError::unavailable(format!("cannot inspect {label}: {error}"))
    })?;
    if !metadata.file_type().is_file() {
        return Err(TeamDurabilityError::corrupt(format!(
            "{label} is not a regular file"
        )));
    }
    let max_u64 = u64::try_from(max_bytes)
        .map_err(|_| TeamDurabilityError::corrupt(format!("{label} size limit overflows u64")))?;
    if metadata.len() > max_u64 {
        return Err(TeamDurabilityError::corrupt(format!(
            "{label} exceeds the size limit"
        )));
    }
    let initial_capacity = usize::try_from(metadata.len())
        .unwrap_or(max_bytes)
        .min(max_bytes);
    let mut bytes = Vec::with_capacity(initial_capacity);
    file.take(max_u64.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|error| {
            TeamDurabilityError::unavailable(format!("cannot read {label}: {error}"))
        })?;
    if bytes.len() > max_bytes {
        return Err(TeamDurabilityError::corrupt(format!(
            "{label} exceeds the size limit"
        )));
    }
    Ok(Some(bytes))
}

fn sync_parent_directory(path: &Path, label: &str) -> Result<(), TeamDurabilityError> {
    #[cfg(unix)]
    {
        let parent = path.parent().ok_or_else(|| {
            TeamDurabilityError::unavailable(format!("{label} path has no parent"))
        })?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| {
                TeamDurabilityError::unavailable(format!(
                    "cannot establish {label} directory durability: {error}"
                ))
            })?;
    }
    Ok(())
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

    match read_snapshot_file(snapshot_path)? {
        Some(_) if expected_generation == 0 => {
            return Err(TeamDurabilityError::conflict(
                "durable Team snapshot already exists at initial commit",
            ));
        }
        Some(committed) => {
            let actual_generation = committed_snapshot_generation(identity, &committed)?;
            if actual_generation != expected_generation {
                return Err(TeamDurabilityError::conflict(format!(
                    "durable Team generation changed: expected {expected_generation}, found {actual_generation}"
                )));
            }
        }
        None if expected_generation == 0 => {}
        None => {
            return Err(TeamDurabilityError::conflict(
                "durable Team snapshot disappeared before commit",
            ));
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
        let first = committed_reader(home.path(), identity).await;
        let first_view = first
            .snapshot_for(root_thread_id)
            .expect("first committed view");
        assert_eq!(first_view.events.len(), 1);
        assert_eq!(first_view.events[0].title, "first process");
        assert!(
            first
                .has_pending_durable_wake(root_thread_id)
                .expect("read persisted Root wake")
        );
        let original_instance = first.instance();

        run_child_stage(home.path(), identity, "resume");
        let second = committed_reader(home.path(), identity).await;
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

    #[tokio::test]
    async fn session_intent_requires_a_matching_committed_snapshot_for_resume() {
        let home = TempDir::new().expect("temp durable Team home");
        let root_thread_id = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::new(), root_thread_id);
        let thread_store = local_thread_store(home.path());
        let live_thread = LiveThread::create(
            Arc::clone(&thread_store),
            create_thread_params(home.path(), identity),
        )
        .await
        .expect("create Root thread");
        live_thread
            .persist()
            .await
            .expect("materialize Root rollout");
        let session_meta = session_meta(home.path(), identity).await;

        assert!(
            !durable_team_snapshot_exists(home.path(), identity)
                .expect("probe bounded durable snapshot")
        );
        assert!(matches!(
            validate_durable_team_resume(home.path(), &session_meta, identity),
            Err(TeamDurabilityError::Unavailable { .. })
        ));

        let other_identity = DurableTeamIdentity::new(SessionId::new(), root_thread_id);
        assert!(matches!(
            validate_session_intent(&session_meta, other_identity),
            Err(TeamDurabilityError::IdentityMismatch)
        ));
        let mut mismatched_inner = session_meta.clone();
        mismatched_inner
            .durable_team
            .as_mut()
            .expect("durable Session intent")
            .session_id = SessionId::new();
        assert!(matches!(
            validate_session_intent(&mismatched_inner, identity),
            Err(TeamDurabilityError::IdentityMismatch)
        ));

        let intent = session_meta.durable_team.expect("durable Session intent");
        let authority = root_team_write_authority(&thread_store, home.path(), identity, intent)
            .await
            .expect("derive Root authority");
        let team = TeamStateHandle::create_durable(authority).expect("create durable Team");
        team.register_durable_participant(
            root_thread_id,
            ParticipantRole::Root,
            "/root".to_string(),
        )
        .expect("commit initial Team snapshot");
        assert!(
            durable_team_snapshot_exists(home.path(), identity)
                .expect("snapshot remains a detectable durable artifact")
        );

        let mut orphaned_meta = session_meta.clone();
        orphaned_meta.durable_team = None;
        assert!(matches!(
            validate_durable_team_resume(home.path(), &orphaned_meta, identity),
            Err(TeamDurabilityError::Conflict { .. })
        ));
        assert!(matches!(
            read_committed_snapshot(home.path(), &orphaned_meta, identity),
            Err(TeamDurabilityError::Conflict { .. })
        ));

        let mut unsupported_meta = session_meta;
        unsupported_meta
            .durable_team
            .as_mut()
            .expect("durable Session intent")
            .version += 1;
        assert!(matches!(
            validate_durable_team_resume(home.path(), &unsupported_meta, identity),
            Err(TeamDurabilityError::UnsupportedVersion { .. })
        ));
    }

    #[tokio::test]
    async fn live_owner_rejects_reads_and_mutations_after_session_meta_disappears() {
        let home = TempDir::new().expect("temp durable Team home");
        let root_thread_id = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::new(), root_thread_id);
        let thread_store = local_thread_store(home.path());
        let live_thread = LiveThread::create(
            Arc::clone(&thread_store),
            create_thread_params(home.path(), identity),
        )
        .await
        .expect("create Root thread");
        live_thread
            .persist()
            .await
            .expect("materialize canonical Root rollout");
        let rollout_path = live_thread
            .local_rollout_path()
            .await
            .expect("read live rollout path")
            .expect("local Root has a rollout path");
        let session_meta = session_meta(home.path(), identity).await;
        let authority = root_team_write_authority(
            &thread_store,
            home.path(),
            identity,
            session_meta.durable_team.expect("durable Session intent"),
        )
        .await
        .expect("derive Root authority");
        let team = TeamStateHandle::create_durable(authority).expect("create durable Team");
        team.register_durable_participant(
            root_thread_id,
            ParticipantRole::Root,
            "/root".to_string(),
        )
        .expect("commit initial Team snapshot");
        let snapshot_path = snapshot_path(home.path(), root_thread_id);
        let before = std::fs::read(&snapshot_path).expect("read generation 1");

        std::fs::remove_file(&rollout_path).expect("remove canonical Root SessionMeta");
        assert!(matches!(
            team.snapshot_for(root_thread_id),
            Err(codex_team_state::TeamError::Durability { .. })
        ));
        assert!(matches!(
            team.publish(
                root_thread_id,
                &Submission {
                    based_on: team.revision(),
                    request_id: "missing-root-marker".to_string(),
                },
                publish_request("must fail closed"),
            ),
            Err(codex_team_state::TeamError::Durability { .. })
        ));
        assert_eq!(
            std::fs::read(&snapshot_path).expect("read unchanged Team snapshot"),
            before,
            "a missing Root marker must prevent the next Team generation"
        );
    }

    #[tokio::test]
    async fn every_snapshot_read_rejects_an_oversized_sparse_file_before_allocation() {
        let home = TempDir::new().expect("temp durable Team home");
        let root_thread_id = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::new(), root_thread_id);
        let thread_store = local_thread_store(home.path());
        let live_thread = LiveThread::create(
            Arc::clone(&thread_store),
            create_thread_params(home.path(), identity),
        )
        .await
        .expect("create Root thread");
        live_thread
            .persist()
            .await
            .expect("materialize Root rollout");
        let session_meta = session_meta(home.path(), identity).await;
        let authority = root_team_write_authority(
            &thread_store,
            home.path(),
            identity,
            session_meta.durable_team.expect("durable Session intent"),
        )
        .await
        .expect("derive Root authority");
        let team =
            TeamStateHandle::create_durable(Arc::clone(&authority)).expect("create durable Team");
        team.register_durable_participant(
            root_thread_id,
            ParticipantRole::Root,
            "/root".to_string(),
        )
        .expect("commit initial Team snapshot");

        std::fs::OpenOptions::new()
            .write(true)
            .open(snapshot_path(home.path(), root_thread_id))
            .expect("open committed Team snapshot")
            .set_len((MAX_ENCODED_SNAPSHOT_BYTES as u64) + 1)
            .expect("make sparse oversized snapshot");

        assert!(matches!(
            read_committed_snapshot(home.path(), &session_meta, identity),
            Err(TeamDurabilityError::Corrupt { .. })
        ));
        assert!(matches!(
            durable_team_snapshot_exists(home.path(), identity),
            Err(TeamDurabilityError::Corrupt { .. })
        ));
        let mut permit = authority.begin_write().expect("acquire Root write permit");
        assert!(matches!(
            permit.read_snapshot(),
            Err(TeamDurabilityError::Corrupt { .. })
        ));
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
        if mode == "create" {
            live_thread
                .persist()
                .await
                .expect("materialize canonical Root rollout before Team success");
        }
        let session_meta = session_meta(&home, identity).await;
        match mode {
            "create" => validate_session_intent(&session_meta, identity)
                .expect("validate canonical durable Team Session intent"),
            "resume" => validate_durable_team_resume(&home, &session_meta, identity)
                .expect("cross-validate durable Team Session and snapshot"),
            _ => unreachable!("mode checked above"),
        }
        let authority = root_team_write_authority(
            &thread_store,
            &home,
            identity,
            session_meta.durable_team.expect("durable Session intent"),
        )
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
        let actor = if mode == "create" {
            let member = ThreadId::new();
            team.register_durable_participant(
                member,
                ParticipantRole::Member,
                "/root/member".to_string(),
            )
            .expect("register durable member");
            member
        } else {
            root_thread_id
        };
        let expected_events = usize::from(mode == "resume");
        assert_eq!(
            team.snapshot_for(root_thread_id)
                .expect("pre-mutation Team view")
                .events
                .len(),
            expected_events
        );
        team.publish(
            actor,
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

    async fn committed_reader(home: &Path, identity: DurableTeamIdentity) -> TeamStateHandle {
        let session_meta = session_meta(home, identity).await;
        let committed = read_committed_snapshot(home, &session_meta, identity)
            .expect("read committed Team snapshot");
        TeamStateHandle::from_committed_snapshot(identity, &committed)
            .expect("hydrate non-owner committed reader")
    }

    async fn session_meta(home: &Path, identity: DurableTeamIdentity) -> SessionMeta {
        let rollout_path = codex_rollout::find_thread_path_by_id_str(
            home,
            &identity.root_thread_id().to_string(),
            None,
        )
        .await
        .expect("locate persisted Root thread")
        .expect("persisted Root rollout exists");
        codex_rollout::read_session_meta_line(&rollout_path)
            .await
            .expect("read canonical SessionMeta")
            .meta
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
            durable_team: Some(DurableTeamSessionMeta::current(
                identity.session_id(),
                identity.root_thread_id(),
            )),
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
