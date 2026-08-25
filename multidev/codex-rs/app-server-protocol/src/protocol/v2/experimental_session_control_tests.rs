use super::*;
use crate::ClientRequest;
use crate::ExperimentalApi;
use crate::RequestId;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn read_params_round_trip_explicit_prototype_lifecycle() {
    let wire = json!({
        "sessionId": "01900000-0000-7000-8000-000000000001",
        "prototypeFacts": {
            "domainLifecycle": "closing"
        }
    });

    let params: ExperimentalSessionReadParams =
        serde_json::from_value(wire.clone()).expect("read params should deserialize");
    assert_eq!(
        params,
        ExperimentalSessionReadParams {
            session_id: "01900000-0000-7000-8000-000000000001".to_string(),
            prototype_facts: Some(ExperimentalSessionPrototypeFacts {
                domain_lifecycle: ExperimentalSessionDomainLifecycle::Closing,
            }),
        }
    );
    assert_eq!(
        serde_json::to_value(params).expect("read params should serialize"),
        wire
    );
}

#[test]
fn read_params_accept_missing_prototype_facts_but_serialize_null() {
    let params: ExperimentalSessionReadParams = serde_json::from_value(json!({
        "sessionId": "01900000-0000-7000-8000-000000000001"
    }))
    .expect("omitted prototype facts should deserialize");
    assert_eq!(params.prototype_facts, None);
    assert_eq!(
        serde_json::to_value(ClientRequest::ExperimentalSessionRead {
            request_id: RequestId::Integer(7),
            params,
        })
        .expect("request should serialize"),
        json!({
            "method": "experimentalSession/read",
            "id": 7,
            "params": {
                "sessionId": "01900000-0000-7000-8000-000000000001",
                "prototypeFacts": null
            }
        })
    );
}

#[test]
fn list_response_marks_unavailable_discovery_as_incomplete() {
    let response = ExperimentalSessionListResponse {
        data: Vec::new(),
        next_cursor: None,
        provenance: ExperimentalSessionFactProvenance::Unavailable,
        complete: false,
    };

    assert_eq!(
        serde_json::to_value(response).expect("list response should serialize"),
        json!({
            "data": [],
            "nextCursor": null,
            "provenance": "unavailable",
            "complete": false
        })
    );

    let complete_empty = ExperimentalSessionListResponse {
        data: Vec::new(),
        next_cursor: None,
        provenance: ExperimentalSessionFactProvenance::StateDbPrototype,
        complete: true,
    };
    assert_eq!(
        serde_json::to_value(complete_empty).expect("complete list response should serialize"),
        json!({
            "data": [],
            "nextCursor": null,
            "provenance": "stateDbPrototype",
            "complete": true
        })
    );
}

#[test]
fn view_serializes_state_axes_and_provenance_independently() {
    let view = ExperimentalSessionView {
        identity: ExperimentalSessionIdentity {
            session_id: "session-1".to_string(),
            root_thread_id: None,
        },
        domain_lifecycle: ExperimentalSessionDomainLifecycle::Partial,
        residency: ExperimentalSessionResidency::OwnerUnavailable,
        operation_availability: ExperimentalSessionOperations {
            update_team_lifecycle: ExperimentalSessionOperation {
                availability: ExperimentalSessionOperationAvailability::Unavailable {
                    reason: ExperimentalSessionOperationUnavailableReason::OwnerUnavailable,
                },
                provenance: ExperimentalSessionFactProvenance::LiveRuntime,
            },
            archive: ExperimentalSessionOperation {
                availability: ExperimentalSessionOperationAvailability::Unavailable {
                    reason: ExperimentalSessionOperationUnavailableReason::Unsupported,
                },
                provenance: ExperimentalSessionFactProvenance::Unavailable,
            },
            unarchive: ExperimentalSessionOperation {
                availability: ExperimentalSessionOperationAvailability::Unavailable {
                    reason: ExperimentalSessionOperationUnavailableReason::Unknown,
                },
                provenance: ExperimentalSessionFactProvenance::Unavailable,
            },
        },
        provenance: ExperimentalSessionProvenance {
            identity: ExperimentalSessionFactProvenance::LiveRuntime,
            domain_lifecycle: ExperimentalSessionFactProvenance::PrototypeInput,
            residency: ExperimentalSessionFactProvenance::Unavailable,
            team: ExperimentalSessionFactProvenance::Unavailable,
        },
        team: None,
    };

    assert_eq!(
        serde_json::to_value(view).expect("view should serialize"),
        json!({
            "identity": {
                "sessionId": "session-1",
                "rootThreadId": null
            },
            "domainLifecycle": "partial",
            "residency": "ownerUnavailable",
            "operationAvailability": {
                "updateTeamLifecycle": {
                    "availability": {
                        "type": "unavailable",
                        "reason": "ownerUnavailable"
                    },
                    "provenance": "liveRuntime"
                },
                "archive": {
                    "availability": {
                        "type": "unavailable",
                        "reason": "unsupported"
                    },
                    "provenance": "unavailable"
                },
                "unarchive": {
                    "availability": {
                        "type": "unavailable",
                        "reason": "unknown"
                    },
                    "provenance": "unavailable"
                }
            },
            "provenance": {
                "identity": "liveRuntime",
                "domainLifecycle": "prototypeInput",
                "residency": "unavailable",
                "team": "unavailable"
            },
            "team": null
        })
    );
}

#[test]
fn team_projection_serializes_explicit_omission_counts() {
    let projection = ExperimentalSessionTeamProjection {
        team_instance_id: "0123456789ab".to_string(),
        revision: 4,
        viewer_thread_id: "root-1".to_string(),
        viewer_role: ExperimentalSessionTeamViewerRole::Root,
        omitted_participants: 3,
        events: vec![ExperimentalSessionTeamEventProjection {
            event_id: "evt-1-0123456789ab".to_string(),
            title: "bounded event".to_string(),
            versions: Vec::new(),
            omitted_versions: 2,
        }],
        omitted_events: 5,
    };

    assert_eq!(
        serde_json::to_value(projection).expect("team projection should serialize"),
        json!({
            "teamInstanceId": "0123456789ab",
            "revision": 4,
            "viewerThreadId": "root-1",
            "viewerRole": "root",
            "omittedParticipants": 3,
            "events": [{
                "eventId": "evt-1-0123456789ab",
                "title": "bounded event",
                "versions": [],
                "omittedVersions": 2
            }],
            "omittedEvents": 5
        })
    );
}

#[test]
fn update_team_lifecycle_params_parse_opaque_ids_and_preconditions() {
    let params: ExperimentalSessionUpdateTeamLifecycleParams = serde_json::from_value(json!({
        "rootThreadId": "01900000-0000-7000-8000-000000000001",
        "versionId": "ver-1.1-0123456789ab",
        "expectedProducerState": "open",
        "expectedRootState": "pending",
        "nextRootState": "tracking"
    }))
    .expect("update params should deserialize");

    assert_eq!(
        params,
        ExperimentalSessionUpdateTeamLifecycleParams {
            root_thread_id: "01900000-0000-7000-8000-000000000001".to_string(),
            version_id: "ver-1.1-0123456789ab".to_string(),
            expected_producer_state: ExperimentalSessionTeamProducerState::Open,
            expected_root_state: ExperimentalSessionTeamRootState::Pending,
            next_root_state: ExperimentalSessionTeamRootState::Tracking,
        }
    );
}

#[test]
fn requests_use_registered_experimental_method_names() {
    let requests = [
        (
            ClientRequest::ExperimentalSessionList {
                request_id: RequestId::Integer(1),
                params: ExperimentalSessionListParams::default(),
            },
            "experimentalSession/list",
        ),
        (
            ClientRequest::ExperimentalSessionRead {
                request_id: RequestId::Integer(2),
                params: ExperimentalSessionReadParams {
                    session_id: "session-1".to_string(),
                    prototype_facts: None,
                },
            },
            "experimentalSession/read",
        ),
        (
            ClientRequest::ExperimentalSessionUpdateTeamLifecycle {
                request_id: RequestId::Integer(3),
                params: ExperimentalSessionUpdateTeamLifecycleParams {
                    root_thread_id: "root-1".to_string(),
                    version_id: "ver-1.1-0123456789ab".to_string(),
                    expected_producer_state: ExperimentalSessionTeamProducerState::Open,
                    expected_root_state: ExperimentalSessionTeamRootState::Pending,
                    next_root_state: ExperimentalSessionTeamRootState::Resolved,
                },
            },
            "experimentalSession/updateTeamLifecycle",
        ),
    ];

    for (request, method) in requests {
        assert_eq!(ExperimentalApi::experimental_reason(&request), Some(method));
        assert_eq!(
            serde_json::to_value(request)
                .expect("request should serialize")
                .get("method")
                .and_then(serde_json::Value::as_str),
            Some(method)
        );
    }
}
