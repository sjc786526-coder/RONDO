use std::fs;
use std::io;
use std::path::Path;
use std::path::PathBuf;

use chrono::Utc;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionSource;
use codex_state::ThreadMetadataBuilder;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use uuid::Uuid;

use super::LocalThreadStore;
use super::read_session_meta::map_head_read_error;
use super::read_session_meta::map_rollout_metadata_error;
use super::read_session_meta::resolve_indexed_rollout_path_for_query;
use super::test_support::test_config;
use super::test_support::write_archived_session_file;
use super::test_support::write_session_file;
use crate::ReadSessionMetaError;
use crate::ReadSessionMetaParams;
use crate::ThreadStore;

#[tokio::test]
async fn canonical_session_meta_read_is_archive_aware_and_does_not_repair_state() {
    let home = TempDir::new().expect("temp dir");
    let config = test_config(home.path());
    let runtime = codex_state::StateRuntime::init(
        config.sqlite.clone(),
        config.default_model_provider_id.clone(),
    )
    .await
    .expect("state db should initialize");
    let store = LocalThreadStore::new(config, Some(runtime.clone()));
    let active_uuid = Uuid::from_u128(401);
    let active_thread_id =
        ThreadId::from_string(&active_uuid.to_string()).expect("valid active thread id");
    let active_path = write_session_file(home.path(), "2025-01-03T12-00-00", active_uuid)
        .expect("active session file");
    let archived_uuid = Uuid::from_u128(402);
    let archived_thread_id =
        ThreadId::from_string(&archived_uuid.to_string()).expect("valid archived thread id");
    let archived_path =
        write_archived_session_file(home.path(), "2025-01-03T12-00-00", archived_uuid)
            .expect("archived session file");
    let original_active_bytes = fs::read(&active_path).expect("read active fixture");
    let original_archived_bytes = fs::read(&archived_path).expect("read archived fixture");
    index_rollout(
        runtime.as_ref(),
        active_thread_id,
        active_path.clone(),
        /*archived*/ false,
    )
    .await;
    index_rollout(
        runtime.as_ref(),
        archived_thread_id,
        archived_path.clone(),
        /*archived*/ true,
    )
    .await;
    let active_row = runtime
        .get_thread(active_thread_id)
        .await
        .expect("query active state DB row")
        .expect("active state DB row");
    let archived_row = runtime
        .get_thread(archived_thread_id)
        .await
        .expect("query archived state DB row")
        .expect("archived state DB row");

    let active_meta = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id: active_thread_id,
            include_archived: false,
        },
    )
    .await
    .expect("read active canonical SessionMeta");
    let archived_error = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id: archived_thread_id,
            include_archived: false,
        },
    )
    .await
    .expect_err("active-only read must exclude archived metadata");
    let archived_meta = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id: archived_thread_id,
            include_archived: true,
        },
    )
    .await
    .expect("read archived canonical SessionMeta");

    assert_eq!(active_meta.id, active_thread_id);
    assert_eq!(archived_meta.id, archived_thread_id);
    assert_eq!(
        archived_error,
        ReadSessionMetaError::NotFound {
            thread_id: archived_thread_id,
        }
    );
    assert_eq!(
        runtime
            .get_thread(active_thread_id)
            .await
            .expect("query state db"),
        Some(active_row)
    );
    assert_eq!(
        runtime
            .get_thread(archived_thread_id)
            .await
            .expect("query state db"),
        Some(archived_row)
    );
    assert_eq!(
        fs::read(active_path).expect("reread active fixture"),
        original_active_bytes
    );
    assert_eq!(
        fs::read(archived_path).expect("reread archived fixture"),
        original_archived_bytes
    );
    assert!(store.live_recorders.lock().await.is_empty());
}

#[tokio::test]
async fn canonical_session_meta_read_types_missing_bounded_and_mismatched_rollouts() {
    let no_db_home = TempDir::new().expect("temp dir");
    let no_db_uuid = Uuid::from_u128(406);
    let no_db_thread_id =
        ThreadId::from_string(&no_db_uuid.to_string()).expect("valid no-DB thread id");
    write_session_file(no_db_home.path(), "2025-01-03T12-00-00", no_db_uuid)
        .expect("no-DB session file");
    let no_db_store = LocalThreadStore::new(test_config(no_db_home.path()), /*state_db*/ None);
    let unsupported = ThreadStore::read_session_meta(
        &no_db_store,
        ReadSessionMetaParams {
            thread_id: no_db_thread_id,
            include_archived: true,
        },
    )
    .await
    .expect_err("store without state DB must not scan rollouts");
    assert_eq!(
        unsupported,
        ReadSessionMetaError::Unsupported {
            operation: "read_session_meta",
        }
    );

    let home = TempDir::new().expect("temp dir");
    let config = test_config(home.path());
    let runtime = codex_state::StateRuntime::init(
        config.sqlite.clone(),
        config.default_model_provider_id.clone(),
    )
    .await
    .expect("state DB should initialize");
    let store = LocalThreadStore::new(config, Some(runtime.clone()));
    let requested_uuid = Uuid::from_u128(403);
    let requested_thread_id =
        ThreadId::from_string(&requested_uuid.to_string()).expect("valid requested thread id");
    let missing_thread_id =
        ThreadId::from_string(&Uuid::from_u128(405).to_string()).expect("valid missing thread id");
    let actual_thread_id =
        ThreadId::from_string(&Uuid::from_u128(404).to_string()).expect("valid actual thread id");
    let missing = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id: missing_thread_id,
            include_archived: true,
        },
    )
    .await
    .expect_err("missing rollout must remain missing");
    assert_eq!(
        missing,
        ReadSessionMetaError::NotFound {
            thread_id: missing_thread_id,
        }
    );
    let rollout_path = write_session_file(home.path(), "2025-01-03T12-00-00", requested_uuid)
        .expect("session file");
    index_rollout(
        runtime.as_ref(),
        requested_thread_id,
        rollout_path.clone(),
        /*archived*/ false,
    )
    .await;
    let contents = fs::read_to_string(&rollout_path).expect("read session file");
    let (head, tail) = contents
        .split_once('\n')
        .expect("fixture contains SessionMeta and history");
    let mut head = serde_json::from_str::<serde_json::Value>(head).expect("parse SessionMeta line");
    head["payload"]["id"] = serde_json::json!(actual_thread_id);
    fs::write(&rollout_path, format!("{head}\n{tail}")).expect("rewrite fixture identity");

    let mismatch = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id: requested_thread_id,
            include_archived: false,
        },
    )
    .await
    .expect_err("mismatched canonical identity must fail closed");
    assert_eq!(
        mismatch,
        ReadSessionMetaError::IdentityMismatch {
            requested_thread_id,
            actual_thread_id,
        }
    );

    let pre_header_event = serde_json::json!({
        "timestamp": "2025-01-03T12:00:00Z",
        "type": "event_msg",
        "payload": {
            "type": "user_message",
            "message": "before metadata",
            "kind": "plain"
        }
    });
    let bounded_fixture = std::iter::repeat_n(pre_header_event.to_string(), 11)
        .chain(std::iter::once(contents))
        .collect::<Vec<_>>()
        .join("\n");
    fs::write(&rollout_path, bounded_fixture).expect("write bounded-head fixture");
    let bounded_error = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id: requested_thread_id,
            include_archived: false,
        },
    )
    .await
    .expect_err("metadata beyond the bounded rollout head must fail closed");
    let ReadSessionMetaError::Corrupt { thread_id, message } = bounded_error else {
        panic!("bounded head failure must be typed as corrupt");
    };
    assert_eq!(thread_id, requested_thread_id);
    assert!(message.contains("first 10 records"), "{message}");

    let stale_uuid = Uuid::from_u128(407);
    let stale_thread_id =
        ThreadId::from_string(&stale_uuid.to_string()).expect("valid stale thread id");
    let stale_path = home.path().join("missing-rollout.jsonl");
    index_rollout(
        runtime.as_ref(),
        stale_thread_id,
        stale_path.clone(),
        /*archived*/ false,
    )
    .await;
    let stale = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id: stale_thread_id,
            include_archived: false,
        },
    )
    .await
    .expect_err("stale indexed rollout path must fail closed");
    let ReadSessionMetaError::Corrupt { thread_id, message } = stale else {
        panic!("stale locator must be typed as corrupt");
    };
    assert_eq!(thread_id, stale_thread_id);
    assert!(
        message.contains(&stale_path.display().to_string()),
        "{message}"
    );
}

#[tokio::test]
async fn canonical_session_meta_read_types_locator_outage_as_unavailable() {
    let home = TempDir::new().expect("temp dir");
    let config = test_config(home.path());
    let runtime = codex_state::StateRuntime::init(
        config.sqlite.clone(),
        config.default_model_provider_id.clone(),
    )
    .await
    .expect("state DB should initialize");
    let store = LocalThreadStore::new(config, Some(runtime.clone()));
    runtime.close().await;
    let thread_id = ThreadId::default();

    let error = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id,
            include_archived: true,
        },
    )
    .await
    .expect_err("closed locator backend must be unavailable");

    let display = error.to_string();
    let ReadSessionMetaError::Unavailable {
        thread_id: error_thread_id,
        message,
    } = error
    else {
        panic!("locator backend failure must be typed as unavailable");
    };
    assert_eq!(error_thread_id, thread_id);
    assert!(message.contains("active rollout locator"), "{message}");
    assert!(
        display.contains("source") && display.contains("unavailable"),
        "{display}"
    );
}

#[tokio::test]
async fn rollout_locator_prefers_plain_and_reads_a_compressed_only_sibling() {
    let home = TempDir::new().expect("temp dir");
    let config = test_config(home.path());
    let runtime = codex_state::StateRuntime::init(
        config.sqlite.clone(),
        config.default_model_provider_id.clone(),
    )
    .await
    .expect("state DB should initialize");
    let store = LocalThreadStore::new(config, Some(runtime.clone()));
    let uuid = Uuid::from_u128(408);
    let thread_id = ThreadId::from_string(&uuid.to_string()).expect("valid thread id");
    let plain_path =
        write_session_file(home.path(), "2025-01-03T12-00-00", uuid).expect("plain session file");
    let mut compressed_name = plain_path
        .file_name()
        .expect("rollout file name")
        .to_os_string();
    compressed_name.push(".zst");
    let compressed_path = plain_path.with_file_name(compressed_name);
    let compressed = zstd::stream::encode_all(
        fs::File::open(&plain_path).expect("open rollout for compression"),
        /*level*/ 0,
    )
    .expect("compress rollout");
    fs::write(&compressed_path, compressed).expect("write compressed sibling");
    index_rollout(
        runtime.as_ref(),
        thread_id,
        plain_path.clone(),
        /*archived*/ false,
    )
    .await;

    assert_eq!(
        resolve_indexed_rollout_path_for_query(thread_id, &compressed_path)
            .await
            .expect("both siblings should resolve"),
        plain_path,
        "plain rollout must win even when the indexed path is compressed"
    );
    fs::remove_file(&plain_path).expect("remove task fixture plain sibling");
    assert_eq!(
        resolve_indexed_rollout_path_for_query(thread_id, &plain_path)
            .await
            .expect("compressed-only sibling should resolve"),
        compressed_path
    );
    let meta = ThreadStore::read_session_meta(
        &store,
        ReadSessionMetaParams {
            thread_id,
            include_archived: false,
        },
    )
    .await
    .expect("canonical metadata should read from compressed-only sibling");
    assert_eq!(meta.id, thread_id);
}

#[test]
fn canonical_session_meta_head_errors_distinguish_corruption_from_source_outage() {
    let thread_id = ThreadId::default();
    let path = Path::new("/fixture/rollout.jsonl");

    for kind in [io::ErrorKind::InvalidData, io::ErrorKind::UnexpectedEof] {
        let error = map_head_read_error(thread_id, path, io::Error::new(kind, "fixture"));
        assert!(
            matches!(&error, ReadSessionMetaError::Corrupt { thread_id: actual, .. } if *actual == thread_id),
            "{kind:?}: {error}"
        );
    }
    let semantic_other = map_head_read_error(
        thread_id,
        path,
        io::Error::other("rollout does not start with SessionMeta"),
    );
    assert!(matches!(
        semantic_other,
        ReadSessionMetaError::Corrupt { thread_id: actual, .. } if actual == thread_id
    ));

    for kind in [
        io::ErrorKind::NotFound,
        io::ErrorKind::PermissionDenied,
        io::ErrorKind::TimedOut,
        io::ErrorKind::Interrupted,
        io::ErrorKind::WouldBlock,
        io::ErrorKind::ConnectionReset,
    ] {
        let error = map_head_read_error(thread_id, path, io::Error::new(kind, "fixture"));
        assert!(
            matches!(&error, ReadSessionMetaError::Unavailable { thread_id: actual, .. } if *actual == thread_id),
            "{kind:?}: {error}"
        );
    }
}

#[test]
fn rollout_locator_metadata_errors_preserve_missing_and_source_outage() {
    let thread_id = ThreadId::default();
    let path = Path::new("/fixture/rollout.jsonl");

    for kind in [io::ErrorKind::NotFound, io::ErrorKind::NotADirectory] {
        assert_eq!(
            map_rollout_metadata_error(thread_id, path, io::Error::new(kind, "fixture")),
            Ok(()),
            "{kind:?} should permit the compressed sibling probe"
        );
    }
    for kind in [
        io::ErrorKind::PermissionDenied,
        io::ErrorKind::TimedOut,
        io::ErrorKind::Interrupted,
        io::ErrorKind::WouldBlock,
    ] {
        let error = map_rollout_metadata_error(thread_id, path, io::Error::new(kind, "fixture"))
            .expect_err("source errors must not be collapsed into a missing rollout");
        assert!(
            matches!(&error, ReadSessionMetaError::Unavailable { thread_id: actual, .. } if *actual == thread_id),
            "{kind:?}: {error}"
        );
    }
}

async fn index_rollout(
    runtime: &codex_state::StateRuntime,
    thread_id: ThreadId,
    rollout_path: PathBuf,
    archived: bool,
) {
    let mut builder =
        ThreadMetadataBuilder::new(thread_id, rollout_path, Utc::now(), SessionSource::Cli);
    builder.model_provider = Some("test-provider".to_string());
    let mut metadata = builder.build("test-provider");
    if archived {
        metadata.archived_at = Some(metadata.updated_at);
    }
    runtime
        .upsert_thread(&metadata)
        .await
        .expect("index rollout in state DB");
}
