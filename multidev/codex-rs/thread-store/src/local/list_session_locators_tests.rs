use chrono::DateTime;
use chrono::Utc;
use codex_protocol::ThreadId;
use codex_state::ThreadMetadataBuilder;
use pretty_assertions::assert_eq;
use tempfile::TempDir;
use uuid::Uuid;

use super::LocalThreadStore;
use super::test_support::test_config;
use super::test_support::write_session_file;
use crate::ListSessionLocatorsError;
use crate::ListSessionLocatorsParams;
use crate::SessionLocator;
use crate::SessionLocatorCursor;
use crate::SessionLocatorPage;
use crate::SessionLocatorStorage;
use crate::ThreadStore;

#[tokio::test]
async fn local_locator_list_is_stable_includes_empty_preview_and_separates_archive() {
    let home = TempDir::new().expect("temp dir");
    let config = test_config(home.path());
    let runtime = codex_state::StateRuntime::init(
        config.sqlite.clone(),
        config.default_model_provider_id.clone(),
    )
    .await
    .expect("state db should initialize");
    let store = LocalThreadStore::new(config, Some(runtime.clone()));
    let created_at = DateTime::<Utc>::from_timestamp(1_700_000_456, 789_000_000)
        .expect("valid creation timestamp");
    let active_low = thread_id(501);
    let active_high = thread_id(502);
    let archived = thread_id(503);
    index_locator(
        runtime.as_ref(),
        home.path(),
        active_low,
        created_at,
        /*archived*/ false,
    )
    .await;
    index_locator(
        runtime.as_ref(),
        home.path(),
        active_high,
        created_at,
        /*archived*/ false,
    )
    .await;
    index_locator(
        runtime.as_ref(),
        home.path(),
        archived,
        created_at,
        /*archived*/ true,
    )
    .await;

    let first = ThreadStore::list_session_locators(
        &store,
        ListSessionLocatorsParams {
            page_size: 1,
            cursor: None,
            storage: SessionLocatorStorage::Active,
        },
    )
    .await
    .expect("first active locator page");
    let expected_cursor = SessionLocatorCursor {
        storage: SessionLocatorStorage::Active,
        created_at,
        thread_id: active_high,
    };
    assert_eq!(
        first,
        SessionLocatorPage {
            items: vec![SessionLocator {
                thread_id: active_high,
                created_at,
            }],
            next_cursor: Some(expected_cursor.clone()),
        }
    );

    let second = ThreadStore::list_session_locators(
        &store,
        ListSessionLocatorsParams {
            page_size: 1,
            cursor: Some(expected_cursor),
            storage: SessionLocatorStorage::Active,
        },
    )
    .await
    .expect("second active locator page");
    assert_eq!(
        second,
        SessionLocatorPage {
            items: vec![SessionLocator {
                thread_id: active_low,
                created_at,
            }],
            next_cursor: None,
        }
    );

    let archived_page = ThreadStore::list_session_locators(
        &store,
        ListSessionLocatorsParams {
            page_size: 10,
            cursor: None,
            storage: SessionLocatorStorage::Archived,
        },
    )
    .await
    .expect("archived locator page");
    assert_eq!(
        archived_page,
        SessionLocatorPage {
            items: vec![SessionLocator {
                thread_id: archived,
                created_at,
            }],
            next_cursor: None,
        }
    );
    assert!(store.live_recorders.lock().await.is_empty());
}

#[tokio::test]
async fn local_locator_list_fails_closed_without_or_after_losing_state_db() {
    let no_db_home = TempDir::new().expect("temp dir");
    write_session_file(
        no_db_home.path(),
        "2025-01-03T12-00-00",
        Uuid::from_u128(504),
    )
    .expect("unindexed rollout fixture");
    let no_db_store = LocalThreadStore::new(test_config(no_db_home.path()), /*state_db*/ None);
    let unsupported = ThreadStore::list_session_locators(
        &no_db_store,
        ListSessionLocatorsParams {
            page_size: 10,
            cursor: None,
            storage: SessionLocatorStorage::Active,
        },
    )
    .await
    .expect_err("a missing state DB must not fall back to rollout scanning");
    assert_eq!(
        unsupported,
        ListSessionLocatorsError::Unsupported {
            operation: "list_session_locators",
        }
    );

    let closed_home = TempDir::new().expect("temp dir");
    let config = test_config(closed_home.path());
    let runtime = codex_state::StateRuntime::init(
        config.sqlite.clone(),
        config.default_model_provider_id.clone(),
    )
    .await
    .expect("state db should initialize");
    let closed_store = LocalThreadStore::new(config, Some(runtime.clone()));
    runtime.close().await;
    let unavailable = ThreadStore::list_session_locators(
        &closed_store,
        ListSessionLocatorsParams {
            page_size: 10,
            cursor: None,
            storage: SessionLocatorStorage::Active,
        },
    )
    .await
    .expect_err("a failed state DB query must be unavailable");
    let ListSessionLocatorsError::Unavailable { message } = unavailable else {
        panic!("closed DB must map to unavailable");
    };
    assert!(
        message.contains("failed to query state DB locators"),
        "{message}"
    );
}

#[tokio::test]
async fn local_locator_list_preserves_malformed_row_classification() {
    let home = TempDir::new().expect("temp dir");
    let config = test_config(home.path());
    let sqlite = config.sqlite.clone();
    let runtime =
        codex_state::StateRuntime::init(sqlite.clone(), config.default_model_provider_id.clone())
            .await
            .expect("state db should initialize");
    let store = LocalThreadStore::new(config, Some(runtime.clone()));
    let thread_id = thread_id(506);
    index_locator(
        runtime.as_ref(),
        home.path(),
        thread_id,
        Utc::now(),
        /*archived*/ false,
    )
    .await;
    let pool = sqlite
        .open_read_write_pool(sqlite.state_db_path().as_path())
        .await
        .expect("open state DB for fault injection");
    sqlx::query("UPDATE threads SET created_at_ms = ? WHERE id = ?")
        .bind(i64::MAX)
        .bind(thread_id.to_string())
        .execute(&pool)
        .await
        .expect("inject out-of-range locator timestamp");
    pool.close().await;

    let error = ThreadStore::list_session_locators(
        &store,
        ListSessionLocatorsParams {
            page_size: 10,
            cursor: None,
            storage: SessionLocatorStorage::Active,
        },
    )
    .await
    .expect_err("malformed state row must fail closed");
    let ListSessionLocatorsError::Corrupt { message } = error else {
        panic!("malformed row must stay distinct from backend unavailability");
    };
    assert!(message.contains("invalid created_at millis"), "{message}");
    assert!(message.contains(&thread_id.to_string()), "{message}");
}

#[tokio::test]
async fn local_locator_list_rejects_invalid_bounds_and_cross_collection_cursors() {
    let home = TempDir::new().expect("temp dir");
    let store = LocalThreadStore::new(test_config(home.path()), /*state_db*/ None);
    for page_size in [0, 101, usize::MAX] {
        let error = ThreadStore::list_session_locators(
            &store,
            ListSessionLocatorsParams {
                page_size,
                cursor: None,
                storage: SessionLocatorStorage::Active,
            },
        )
        .await
        .expect_err("page size outside the locator bound must fail");
        assert_eq!(
            error,
            ListSessionLocatorsError::InvalidRequest {
                message: "page_size must be between 1 and 100".to_string(),
            }
        );
    }

    let cross_collection = ThreadStore::list_session_locators(
        &store,
        ListSessionLocatorsParams {
            page_size: 10,
            cursor: Some(SessionLocatorCursor {
                storage: SessionLocatorStorage::Archived,
                created_at: Utc::now(),
                thread_id: thread_id(505),
            }),
            storage: SessionLocatorStorage::Active,
        },
    )
    .await
    .expect_err("cursor must remain bound to its storage collection");
    assert_eq!(
        cross_collection,
        ListSessionLocatorsError::InvalidRequest {
            message: "cursor belongs to another storage collection".to_string(),
        }
    );
}

fn thread_id(value: u128) -> ThreadId {
    ThreadId::from_string(&Uuid::from_u128(value).to_string()).expect("valid thread id")
}

async fn index_locator(
    runtime: &codex_state::StateRuntime,
    home: &std::path::Path,
    thread_id: ThreadId,
    created_at: DateTime<Utc>,
    archived: bool,
) {
    let mut metadata = ThreadMetadataBuilder::new(
        thread_id,
        home.join(format!("missing-{thread_id}.jsonl")),
        created_at,
        codex_protocol::protocol::SessionSource::Cli,
    )
    .build("test-provider");
    metadata.preview = None;
    metadata.first_user_message = None;
    metadata.archived_at = archived.then_some(created_at);
    runtime
        .upsert_thread(&metadata)
        .await
        .expect("index locator row");
}
