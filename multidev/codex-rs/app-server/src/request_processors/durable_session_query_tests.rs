use super::*;
use codex_core::DurableSessionReadError as CoreReadError;
use codex_protocol::SessionId;
use codex_protocol::ThreadId;
use codex_protocol::protocol::SessionMeta;
use pretty_assertions::assert_eq;

#[test]
fn source_unavailable_stays_distinct_from_an_unreadable_record() {
    assert_eq!(
        meta_failure_status(CanonicalMetaFailure::Unavailable),
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::SourceUnavailable,
        }
    );
    assert_eq!(
        meta_failure_status(CanonicalMetaFailure::Corrupt),
        DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::SessionMetaUnreadable,
        }
    );
    assert_eq!(
        meta_failure_status(CanonicalMetaFailure::Unsupported),
        DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::SourceUnsupported,
        }
    );
}

#[test]
fn marker_and_snapshot_failures_keep_their_own_categories() {
    assert_eq!(
        core_read_status(CoreReadError::MarkerConflict),
        DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::DurableMarkerMissing,
        }
    );
    assert_eq!(
        core_read_status(CoreReadError::MarkerUnsupportedVersion {
            found: 2,
            supported: 1,
        }),
        DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::DurableMarkerIncompatible,
        }
    );
    assert_eq!(
        core_read_status(CoreReadError::MarkerIdentityMismatch),
        DurableSessionReadStatus::Unavailable {
            issue: DurableSessionReadIssue::DurableMarkerIdentityMismatch,
        }
    );
    assert_eq!(
        core_read_status(CoreReadError::UnsupportedVersion {
            found: 2,
            supported: 1,
        }),
        DurableSessionReadStatus::Unsupported {
            issue: DurableSessionReadIssue::TeamSnapshotIncompatible,
        }
    );
    assert_eq!(
        core_read_status(CoreReadError::IdentityMismatch),
        DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotValidationFailed,
        }
    );
}

#[test]
fn list_cursor_is_bound_to_its_storage_scope() {
    let source_cursor = SessionLocatorCursor {
        storage: SessionLocatorStorage::Active,
        created_at: chrono::Utc::now(),
        thread_id: ThreadId::new(),
    };
    let cursor = encode_session_list_cursor(&source_cursor, StorageScope::Active)
        .expect("cursor should encode");
    assert_eq!(
        decode_session_list_cursor(&cursor, StorageScope::Active)
            .expect("matching scope should decode"),
        source_cursor
    );
    assert!(decode_session_list_cursor(&cursor, StorageScope::Archived).is_err());
}

#[test]
fn locator_failures_keep_invalid_unsupported_and_unavailable_distinct() {
    assert!(
        locator_failure_reason(ListSessionLocatorsError::InvalidRequest {
            message: "bad keyset".to_string(),
        })
        .is_err()
    );
    assert_eq!(
        locator_failure_reason(ListSessionLocatorsError::Unsupported {
            operation: "list_session_locators",
        })
        .expect("unsupported is a typed incomplete list"),
        DurableSessionListIncompleteReason::SourceUnsupported
    );
    assert_eq!(
        locator_failure_reason(ListSessionLocatorsError::Unavailable {
            message: "fixture outage".to_string(),
        })
        .expect("outage is a typed incomplete list"),
        DurableSessionListIncompleteReason::SourceUnavailable
    );
    assert_eq!(
        locator_failure_reason(ListSessionLocatorsError::Corrupt {
            message: "malformed locator row".to_string(),
        })
        .expect("malformed locator row is a typed incomplete list"),
        DurableSessionListIncompleteReason::ClassificationFailed
    );
}

#[test]
fn wire_identity_preserves_distinct_session_and_root_ids() {
    let session_id = SessionId::new();
    let root_thread_id = ThreadId::new();
    let meta = SessionMeta {
        session_id,
        id: root_thread_id,
        ..SessionMeta::default()
    };
    let view = authenticated_view(
        &meta,
        StorageScope::Active,
        DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotMissing,
        },
        DurableSessionResidency::NotObservedHere,
        None,
        false,
        None,
    );
    assert_eq!(view.identity.session_id, session_id.to_string());
    assert_eq!(
        view.identity.root_thread_id,
        Some(root_thread_id.to_string())
    );
    assert_ne!(view.identity.session_id, root_thread_id.to_string());
}
