use super::*;
use crate::ClientRequest;
use crate::ExperimentalApi;
use crate::RequestId;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn list_params_use_nullable_pagination_and_default_false_archived_source() {
    let params: DurableSessionListParams =
        serde_json::from_value(json!({})).expect("omitted list params should deserialize");
    assert_eq!(params, DurableSessionListParams::default());

    let request = ClientRequest::DurableSessionList {
        request_id: RequestId::Integer(11),
        params,
    };
    assert_eq!(ExperimentalApi::experimental_reason(&request), None);
    assert_eq!(
        serde_json::to_value(request).expect("list request should serialize"),
        json!({
            "method": "session/list",
            "id": 11,
            "params": {
                "cursor": null,
                "limit": null
            }
        })
    );

    let explicit: DurableSessionListParams = serde_json::from_value(json!({
        "cursor": "opaque-active-cursor",
        "limit": 25,
        "archived": false
    }))
    .expect("explicit list params should deserialize");
    assert_eq!(
        explicit,
        DurableSessionListParams {
            cursor: Some("opaque-active-cursor".to_string()),
            limit: Some(25),
            archived: false,
        }
    );
    assert_eq!(
        serde_json::to_value(explicit).expect("false archived selector should be omitted"),
        json!({
            "cursor": "opaque-active-cursor",
            "limit": 25
        })
    );

    let archived = DurableSessionListParams {
        archived: true,
        ..DurableSessionListParams::default()
    };
    assert_eq!(
        serde_json::to_value(archived).expect("true archived selector should serialize"),
        json!({
            "cursor": null,
            "limit": null,
            "archived": true
        })
    );
}

#[test]
fn read_request_uses_stable_session_method_without_prototype_facts() {
    let request = ClientRequest::DurableSessionRead {
        request_id: RequestId::Integer(12),
        params: DurableSessionReadParams {
            session_id: "session-1".to_string(),
            root_thread_id: "root-1".to_string(),
        },
    };
    assert_eq!(ExperimentalApi::experimental_reason(&request), None);
    assert_eq!(request.serialization_scope(), None);
    assert_eq!(
        serde_json::to_value(request).expect("read request should serialize"),
        json!({
            "method": "session/read",
            "id": 12,
            "params": {
                "sessionId": "session-1",
                "rootThreadId": "root-1"
            }
        })
    );
}

#[test]
fn list_response_serializes_completion_and_reason_independently() {
    let response = DurableSessionListResponse {
        data: Vec::new(),
        next_cursor: Some("continue-after-root".to_string()),
        complete: false,
        incomplete_reason: Some(DurableSessionListIncompleteReason::BudgetExhausted),
    };
    assert_eq!(
        serde_json::to_value(response).expect("list response should serialize"),
        json!({
            "data": [],
            "nextCursor": "continue-after-root",
            "complete": false,
            "incompleteReason": "budgetExhausted"
        })
    );

    let complete = DurableSessionListResponse {
        data: Vec::new(),
        next_cursor: None,
        complete: true,
        incomplete_reason: None,
    };
    assert_eq!(
        serde_json::to_value(complete).expect("complete response should serialize"),
        json!({
            "data": [],
            "nextCursor": null,
            "complete": true,
            "incompleteReason": null
        })
    );

    let unsupported = DurableSessionListResponse {
        data: Vec::new(),
        next_cursor: None,
        complete: false,
        incomplete_reason: Some(DurableSessionListIncompleteReason::SourceUnsupported),
    };
    assert_eq!(
        serde_json::to_value(unsupported).expect("unsupported source should serialize"),
        json!({
            "data": [],
            "nextCursor": null,
            "complete": false,
            "incompleteReason": "sourceUnsupported"
        })
    );
}

#[test]
fn view_serializes_independent_axes_provenance_and_typed_statuses() {
    let view = DurableSessionView {
        identity: DurableSessionIdentity {
            session_id: "session-1".to_string(),
            root_thread_id: Some("root-1".to_string()),
        },
        storage_status: DurableSessionStorageStatus::Archived,
        domain_lifecycle: DurableSessionDomainLifecycle::Unknown,
        residency: DurableSessionResidency::NotObservedHere,
        operation_availability: DurableSessionOperations {
            resume: DurableSessionOperation {
                availability: DurableSessionOperationAvailability::Unknown {
                    reason: DurableSessionOperationAvailabilityReason::NotObservedHere,
                },
                provenance: DurableSessionFactProvenance::ServerRuntimeObservation,
            },
            close: DurableSessionOperation {
                availability: DurableSessionOperationAvailability::Unavailable {
                    reason: DurableSessionOperationAvailabilityReason::LifecycleUnknown,
                },
                provenance: DurableSessionFactProvenance::DerivedPolicy,
            },
            archive: DurableSessionOperation {
                availability: DurableSessionOperationAvailability::Unavailable {
                    reason: DurableSessionOperationAvailabilityReason::AlreadyArchived,
                },
                provenance: DurableSessionFactProvenance::ThreadStore,
            },
            unarchive: DurableSessionOperation {
                availability: DurableSessionOperationAvailability::Available,
                provenance: DurableSessionFactProvenance::ThreadStore,
            },
            delete: DurableSessionOperation {
                availability: DurableSessionOperationAvailability::Unavailable {
                    reason: DurableSessionOperationAvailabilityReason::ReadIncomplete,
                },
                provenance: DurableSessionFactProvenance::DerivedPolicy,
            },
        },
        provenance: DurableSessionProvenance {
            identity: DurableSessionFactProvenance::SessionMeta,
            storage_status: DurableSessionFactProvenance::ThreadStore,
            domain_lifecycle: DurableSessionFactProvenance::Unavailable,
            residency: DurableSessionFactProvenance::ServerRuntimeObservation,
            team: DurableSessionFactProvenance::Unavailable,
        },
        read_status: DurableSessionReadStatus::Incomplete {
            issue: DurableSessionReadIssue::TeamSnapshotMissing,
        },
        team: None,
    };

    assert_eq!(
        serde_json::to_value(view).expect("view should serialize"),
        json!({
            "identity": {
                "sessionId": "session-1",
                "rootThreadId": "root-1"
            },
            "storageStatus": "archived",
            "domainLifecycle": "unknown",
            "residency": "notObservedHere",
            "operationAvailability": {
                "resume": {
                    "availability": {
                        "status": "unknown",
                        "reason": "notObservedHere"
                    },
                    "provenance": "serverRuntimeObservation"
                },
                "close": {
                    "availability": {
                        "status": "unavailable",
                        "reason": "lifecycleUnknown"
                    },
                    "provenance": "derivedPolicy"
                },
                "archive": {
                    "availability": {
                        "status": "unavailable",
                        "reason": "alreadyArchived"
                    },
                    "provenance": "threadStore"
                },
                "unarchive": {
                    "availability": {
                        "status": "available"
                    },
                    "provenance": "threadStore"
                },
                "delete": {
                    "availability": {
                        "status": "unavailable",
                        "reason": "readIncomplete"
                    },
                    "provenance": "derivedPolicy"
                }
            },
            "provenance": {
                "identity": "sessionMeta",
                "storageStatus": "threadStore",
                "domainLifecycle": "unavailable",
                "residency": "serverRuntimeObservation",
                "team": "unavailable"
            },
            "readStatus": {
                "status": "incomplete",
                "issue": "teamSnapshotMissing"
            },
            "team": null
        })
    );
}

#[test]
fn read_status_serializes_each_typed_state_exactly() {
    assert_eq!(
        serde_json::to_value(DurableSessionStorageStatus::Unknown)
            .expect("unknown storage status should serialize"),
        json!("unknown")
    );

    let statuses = [
        (
            DurableSessionReadStatus::Available,
            json!({"status": "available"}),
        ),
        (
            DurableSessionReadStatus::Incomplete {
                issue: DurableSessionReadIssue::SourceChanged,
            },
            json!({"status": "incomplete", "issue": "sourceChanged"}),
        ),
        (
            DurableSessionReadStatus::Unavailable {
                issue: DurableSessionReadIssue::SourceUnavailable,
            },
            json!({"status": "unavailable", "issue": "sourceUnavailable"}),
        ),
        (
            DurableSessionReadStatus::Unsupported {
                issue: DurableSessionReadIssue::SourceUnsupported,
            },
            json!({"status": "unsupported", "issue": "sourceUnsupported"}),
        ),
        (
            DurableSessionReadStatus::Unavailable {
                issue: DurableSessionReadIssue::NotCanonicalRoot,
            },
            json!({"status": "unavailable", "issue": "notCanonicalRoot"}),
        ),
        (
            DurableSessionReadStatus::Unavailable {
                issue: DurableSessionReadIssue::SessionRootIdentityMismatch,
            },
            json!({
                "status": "unavailable",
                "issue": "sessionRootIdentityMismatch"
            }),
        ),
        (
            DurableSessionReadStatus::Unsupported {
                issue: DurableSessionReadIssue::DurableMarkerIncompatible,
            },
            json!({
                "status": "unsupported",
                "issue": "durableMarkerIncompatible"
            }),
        ),
        (
            DurableSessionReadStatus::Unavailable {
                issue: DurableSessionReadIssue::DurableMarkerIdentityMismatch,
            },
            json!({
                "status": "unavailable",
                "issue": "durableMarkerIdentityMismatch"
            }),
        ),
        (
            DurableSessionReadStatus::Unsupported {
                issue: DurableSessionReadIssue::LegacySession,
            },
            json!({"status": "unsupported", "issue": "legacySession"}),
        ),
    ];

    for (status, wire) in statuses {
        assert_eq!(
            serde_json::to_value(&status).expect("read status should serialize"),
            wire
        );
        assert_eq!(
            serde_json::from_value::<DurableSessionReadStatus>(wire)
                .expect("read status should deserialize"),
            status
        );
    }
}

#[test]
fn committed_team_projection_keeps_commit_and_revision_independent() {
    let projection = DurableSessionTeamProjection {
        team_instance_id: "0123456789ab".to_string(),
        commit_generation: 9,
        commit_fingerprint:
            "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".to_string(),
        revision: 4,
        viewer: DurableSessionTeamViewer {
            thread_id: "member-1".to_string(),
            role: DurableSessionTeamRole::Member,
        },
        participants: vec![DurableSessionTeamParticipantProjection {
            thread_id: "root-1".to_string(),
            role: DurableSessionTeamRole::Root,
            label: "root".to_string(),
        }],
        omitted_participants: 3,
        events: vec![DurableSessionTeamEventProjection {
            event_id: "evt-1-0123456789ab".to_string(),
            title: "bounded event".to_string(),
            versions: vec![DurableSessionTeamVersionProjection {
                version_id: "ver-1.1-0123456789ab".to_string(),
                author_thread_id: "member-1".to_string(),
                author_label: "writer".to_string(),
                summary: "candidate answer".to_string(),
                producer_state: DurableSessionTeamProducerState::Closed,
                root_state: DurableSessionTeamRootState::Tracking,
                retired: false,
            }],
            omitted_versions: 2,
        }],
        omitted_events: 5,
    };

    assert_eq!(
        serde_json::to_value(projection).expect("Team projection should serialize"),
        json!({
            "teamInstanceId": "0123456789ab",
            "commitGeneration": 9,
            "commitFingerprint": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "revision": 4,
            "viewer": {
                "threadId": "member-1",
                "role": "member"
            },
            "participants": [{
                "threadId": "root-1",
                "role": "root",
                "label": "root"
            }],
            "omittedParticipants": 3,
            "events": [{
                "eventId": "evt-1-0123456789ab",
                "title": "bounded event",
                "versions": [{
                    "versionId": "ver-1.1-0123456789ab",
                    "authorThreadId": "member-1",
                    "authorLabel": "writer",
                    "summary": "candidate answer",
                    "producerState": "closed",
                    "rootState": "tracking",
                    "retired": false
                }],
                "omittedVersions": 2
            }],
            "omittedEvents": 5
        })
    );
}
