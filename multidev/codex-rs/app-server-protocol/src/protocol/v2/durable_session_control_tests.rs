use super::*;
use crate::ClientRequest;
use crate::ClientRequestSerializationScope;
use crate::ExperimentalApi;
use crate::RequestId;
use pretty_assertions::assert_eq;
use serde_json::json;

fn precondition() -> DurableSessionControlPrecondition {
    DurableSessionControlPrecondition::CommittedTeam {
        expected_storage_status: DurableSessionStorageStatus::Active,
        expected_residency: DurableSessionResidency::ObservedOwnerHere,
        owner_incarnation: Some("019d2a93-2865-7e31-96af-ab81ab5c65af".to_string()),
        team_instance_id: "0123456789ab".to_string(),
        team_revision: 4,
        commit_generation: 9,
        commit_fingerprint:
            "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef".to_string(),
    }
}

#[test]
fn control_request_is_stable_typed_and_serialized_by_root() {
    let request = ClientRequest::DurableSessionControl {
        request_id: RequestId::Integer(13),
        params: DurableSessionControlParams {
            session_id: "session-1".to_string(),
            root_thread_id: "root-1".to_string(),
            precondition: precondition(),
            operation: DurableSessionControlOperation::SetRootState {
                version_id: "ver-1.1-0123456789ab".to_string(),
                expected_producer_state: DurableSessionTeamProducerState::Open,
                expected_root_state: DurableSessionTeamRootState::Pending,
                next_root_state: DurableSessionTeamRootState::Tracking,
            },
        },
    };

    assert_eq!(ExperimentalApi::experimental_reason(&request), None);
    assert_eq!(
        request.serialization_scope(),
        Some(ClientRequestSerializationScope::Thread {
            thread_id: "root-1".to_string(),
        })
    );
    assert_eq!(
        serde_json::to_value(request).expect("control request should serialize"),
        json!({
            "method": "session/control",
            "id": 13,
            "params": {
                "sessionId": "session-1",
                "rootThreadId": "root-1",
                "precondition": {
                    "type": "committedTeam",
                    "expectedStorageStatus": "active",
                    "expectedResidency": "observedOwnerHere",
                    "ownerIncarnation": "019d2a93-2865-7e31-96af-ab81ab5c65af",
                    "teamInstanceId": "0123456789ab",
                    "teamRevision": 4,
                    "commitGeneration": 9,
                    "commitFingerprint": "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
                },
                "operation": {
                    "type": "setRootState",
                    "versionId": "ver-1.1-0123456789ab",
                    "expectedProducerState": "open",
                    "expectedRootState": "pending",
                    "nextRootState": "tracking"
                }
            }
        })
    );
}

#[test]
fn delete_retry_anchor_is_a_distinct_narrow_proof() {
    let proof = DurableSessionControlPrecondition::DeleteRetryAnchor {
        expected_storage_status: DurableSessionStorageStatus::Archived,
        expected_residency: DurableSessionResidency::NotObservedHere,
        root_marker_fingerprint: "sha256:0123456789abcdef".to_string(),
    };

    let wire = json!({
        "type": "deleteRetryAnchor",
        "expectedStorageStatus": "archived",
        "expectedResidency": "notObservedHere",
        "rootMarkerFingerprint": "sha256:0123456789abcdef"
    });
    assert_eq!(
        serde_json::to_value(&proof).expect("delete retry proof should serialize"),
        wire
    );
    assert_eq!(
        serde_json::from_value::<DurableSessionControlPrecondition>(wire)
            .expect("delete retry proof should deserialize"),
        proof
    );
}

#[test]
fn control_operations_keep_a_field_free_kind_for_outcomes() {
    let operations = [
        (
            DurableSessionControlOperation::SetRootState {
                version_id: "version-1".to_string(),
                expected_producer_state: DurableSessionTeamProducerState::Closed,
                expected_root_state: DurableSessionTeamRootState::Tracking,
                next_root_state: DurableSessionTeamRootState::Resolved,
            },
            DurableSessionControlOperationKind::SetRootState,
        ),
        (
            DurableSessionControlOperation::Close,
            DurableSessionControlOperationKind::Close,
        ),
        (
            DurableSessionControlOperation::Archive,
            DurableSessionControlOperationKind::Archive,
        ),
        (
            DurableSessionControlOperation::Unarchive,
            DurableSessionControlOperationKind::Unarchive,
        ),
        (
            DurableSessionControlOperation::Delete,
            DurableSessionControlOperationKind::Delete,
        ),
    ];

    for (operation, expected) in operations {
        assert_eq!(operation.kind(), expected);
    }
}

#[test]
fn control_outcomes_preserve_applied_rejected_partial_and_unknown_certainty() {
    let cases = [
        (
            DurableSessionControlResponse {
                outcome: DurableSessionControlOutcome::Applied {
                    effect: DurableSessionControlEffect::RootStateUpdated {
                        changed: true,
                        mutation_revision: 5,
                    },
                },
            },
            json!({
                "outcome": {
                    "type": "applied",
                    "effect": {
                        "type": "rootStateUpdated",
                        "changed": true,
                        "mutationRevision": 5
                    }
                }
            }),
        ),
        (
            DurableSessionControlResponse {
                outcome: DurableSessionControlOutcome::Rejected {
                    operation: DurableSessionControlOperationKind::Close,
                    reason: DurableSessionControlRejectionReason::ActiveWriter,
                    message: "a descendant can still mutate the Team".to_string(),
                },
            },
            json!({
                "outcome": {
                    "type": "rejected",
                    "operation": "close",
                    "reason": "activeWriter",
                    "message": "a descendant can still mutate the Team"
                }
            }),
        ),
        (
            DurableSessionControlResponse {
                outcome: DurableSessionControlOutcome::Partial {
                    operation: DurableSessionControlOperationKind::Archive,
                    completed_thread_ids: vec!["child-1".to_string()],
                    message: "the Root remained active".to_string(),
                },
            },
            json!({
                "outcome": {
                    "type": "partial",
                    "operation": "archive",
                    "completedThreadIds": ["child-1"],
                    "message": "the Root remained active"
                }
            }),
        ),
        (
            DurableSessionControlResponse {
                outcome: DurableSessionControlOutcome::Unknown {
                    operation: DurableSessionControlOperationKind::Delete,
                    message: "the response was lost after dispatch".to_string(),
                },
            },
            json!({
                "outcome": {
                    "type": "unknown",
                    "operation": "delete",
                    "message": "the response was lost after dispatch"
                }
            }),
        ),
    ];

    for (response, wire) in cases {
        assert_eq!(
            serde_json::to_value(&response).expect("control response should serialize"),
            wire
        );
        assert_eq!(
            serde_json::from_value::<DurableSessionControlResponse>(wire)
                .expect("control response should deserialize"),
            response
        );
    }
}

#[test]
fn applied_lifecycle_effects_keep_affected_thread_sets_typed() {
    let effects = [
        (
            DurableSessionControlEffect::OwnerClosed,
            json!({"type": "ownerClosed"}),
        ),
        (
            DurableSessionControlEffect::Archived {
                affected_thread_ids: vec!["root-1".to_string(), "child-1".to_string()],
            },
            json!({
                "type": "archived",
                "affectedThreadIds": ["root-1", "child-1"]
            }),
        ),
        (
            DurableSessionControlEffect::Unarchived,
            json!({"type": "unarchived"}),
        ),
        (
            DurableSessionControlEffect::Deleted {
                affected_thread_ids: vec!["root-1".to_string()],
            },
            json!({
                "type": "deleted",
                "affectedThreadIds": ["root-1"]
            }),
        ),
    ];

    for (effect, wire) in effects {
        assert_eq!(
            serde_json::to_value(&effect).expect("control effect should serialize"),
            wire
        );
        assert_eq!(
            serde_json::from_value::<DurableSessionControlEffect>(wire)
                .expect("control effect should deserialize"),
            effect
        );
    }
}
