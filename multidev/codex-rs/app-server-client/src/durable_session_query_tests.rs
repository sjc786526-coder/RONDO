use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

#[derive(Clone, Debug, PartialEq, Eq)]
struct ListAttachment {
    archived: bool,
    cursor: Option<&'static str>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
struct SessionView {
    label: &'static str,
    team_revision: u64,
}

type Query = DurableSessionQueryState<
    ListAttachment,
    &'static str,
    &'static [&'static str],
    SessionView,
    &'static str,
>;

fn view(label: &'static str, team_revision: u64) -> SessionView {
    SessionView {
        label,
        team_revision,
    }
}

fn committed(generation: u64, fingerprint: &'static str) -> SessionCommittedRead<&'static str> {
    SessionCommittedRead::Available(CommittedProjection::new(generation, fingerprint))
}

fn committed_projection(
    generation: u64,
    fingerprint: &'static str,
) -> CommittedProjection<&'static str> {
    CommittedProjection::new(generation, fingerprint)
}

fn protocol_view(
    session_id: &str,
    root_thread_id: Option<&str>,
    committed: Option<(u64, &str)>,
) -> Value {
    let team = committed.map(|(commit_generation, commit_fingerprint)| {
        json!({
            "teamInstanceId": format!("team-{session_id}"),
            "commitGeneration": commit_generation,
            "commitFingerprint": commit_fingerprint,
            "revision": 1,
            "viewer": {
                "threadId": root_thread_id.unwrap_or("missing-root"),
                "role": "root"
            },
            "participants": [],
            "omittedParticipants": 0,
            "events": [],
            "omittedEvents": 0
        })
    });
    json!({
        "identity": {
            "sessionId": session_id,
            "rootThreadId": root_thread_id
        },
        "storageStatus": "active",
        "domainLifecycle": "unknown",
        "residency": "notObservedHere",
        "operationAvailability": {
            "resume": unknown_protocol_operation(),
            "close": unknown_protocol_operation(),
            "archive": unknown_protocol_operation(),
            "unarchive": unknown_protocol_operation(),
            "delete": unknown_protocol_operation()
        },
        "provenance": {
            "identity": "sessionMeta",
            "storageStatus": "threadStore",
            "domainLifecycle": "unavailable",
            "residency": "serverRuntimeObservation",
            "team": if team.is_some() { "committedTeamSnapshot" } else { "unavailable" }
        },
        "readStatus": { "status": "available" },
        "team": team
    })
}

fn unknown_protocol_operation() -> Value {
    json!({
        "availability": {
            "status": "unknown",
            "reason": "unsupported"
        },
        "provenance": "derivedPolicy"
    })
}

fn protocol_list_response(data: Vec<Value>) -> DurableSessionListResponse {
    serde_json::from_value(json!({
        "data": data,
        "nextCursor": null,
        "complete": true,
        "incompleteReason": null
    }))
    .expect("valid protocol list fixture")
}

fn protocol_read_response(session: Value) -> DurableSessionReadResponse {
    serde_json::from_value(json!({ "session": session })).expect("valid protocol read fixture")
}

fn invalid_committed_protocol_views() -> Vec<(
    Value,
    InvalidSessionListProjection,
    InvalidSessionReadProjection,
)> {
    let mut unavailable_team =
        protocol_view("session-a", Some("root-a"), Some((9, "checksum-new")));
    unavailable_team["readStatus"] = json!({
        "status": "incomplete",
        "issue": "teamSnapshotMissing"
    });

    let mut wrong_viewer = protocol_view("session-a", Some("root-a"), Some((9, "checksum-new")));
    wrong_viewer["team"]["viewer"]["threadId"] = json!("root-b");

    let mut member_viewer = protocol_view("session-a", Some("root-a"), Some((9, "checksum-new")));
    member_viewer["team"]["viewer"]["role"] = json!("member");

    vec![
        (
            unavailable_team,
            InvalidSessionListProjection::UnexpectedCommittedProjection,
            InvalidSessionReadProjection::UnexpectedCommittedProjection,
        ),
        (
            wrong_viewer,
            InvalidSessionListProjection::InvalidTeamViewer,
            InvalidSessionReadProjection::InvalidTeamViewer,
        ),
        (
            member_viewer,
            InvalidSessionListProjection::InvalidTeamViewer,
            InvalidSessionReadProjection::InvalidTeamViewer,
        ),
    ]
}

fn connected_session() -> Query {
    let mut query = Query::new();
    query.bind_connection();
    query.attach_session("session-a");
    query
}

fn fresh_session() -> Query {
    let mut query = connected_session();
    let ticket = query.begin_read().expect("read should start");
    assert_eq!(
        query.apply_session_read_success(ticket, view("view-a", 9), committed(4, "checksum-a")),
        QueryReadApplyResult::Applied
    );
    query
}

#[test]
fn authoritative_read_accepts_only_the_latest_ticket() {
    let mut query = connected_session();
    let old = query.begin_read().expect("first read should start");
    let current = query.begin_read().expect("replacement read should start");

    assert_eq!(
        query.apply_session_read_success(old, view("old", 8), committed(3, "checksum-old")),
        QueryReadApplyResult::Retired
    );
    assert_eq!(
        query.apply_session_read_success(
            current,
            view("current", 9),
            committed(4, "checksum-current"),
        ),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        query.projection(),
        Some(&DurableSessionQueryProjection::Session(view("current", 9)))
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn list_pages_are_explicit_attachments_and_whole_view_replacements() {
    let mut query = Query::new();
    query.bind_connection();
    query.attach_list(ListAttachment {
        archived: false,
        cursor: None,
    });
    let first = query.begin_read().expect("first page read should start");
    assert_eq!(
        query.apply_list_read_success(first, &["session-a", "session-b"]),
        QueryReadApplyResult::Applied
    );

    query.attach_list(ListAttachment {
        archived: false,
        cursor: Some("cursor-2"),
    });
    assert_eq!(query.projection(), None);
    let second = query.begin_read().expect("second page read should start");
    assert_eq!(
        query.apply_list_read_success(second, &["session-c"]),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        query.projection(),
        Some(&DurableSessionQueryProjection::List(&["session-c"][..]))
    );
}

#[test]
fn list_and_session_reads_share_committed_generation_high_water_in_both_directions() {
    let mut read_then_list = fresh_session();
    read_then_list.attach_list(ListAttachment {
        archived: false,
        cursor: None,
    });
    let list = read_then_list.begin_read().expect("list read should start");
    assert_eq!(
        read_then_list.apply_list_read_success_with_committed(
            list,
            &["regressed-session-a"],
            Ok(vec![(
                "session-a",
                committed_projection(3, "checksum-regressed"),
            )]),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
    assert_ne!(read_then_list.view_freshness(), QueryViewFreshness::Fresh);

    let mut list_then_read = Query::new();
    list_then_read.bind_connection();
    list_then_read.attach_list(ListAttachment {
        archived: false,
        cursor: None,
    });
    let list = list_then_read.begin_read().expect("list read should start");
    assert_eq!(
        list_then_read.apply_list_read_success_with_committed(
            list,
            &["session-a"],
            Ok(vec![("session-a", committed_projection(4, "checksum-a"),)]),
        ),
        QueryReadApplyResult::Applied
    );
    list_then_read.attach_session("session-a");
    let read = list_then_read
        .begin_read()
        .expect("Session read should start");
    assert_eq!(
        list_then_read.apply_session_read_success(
            read,
            view("regressed-after-list", 2),
            committed(3, "checksum-regressed"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
}

#[test]
fn list_and_session_reads_share_same_generation_fingerprint_protection() {
    let mut read_then_list = fresh_session();
    read_then_list.attach_list(ListAttachment {
        archived: false,
        cursor: None,
    });
    let list = read_then_list.begin_read().expect("list read should start");
    assert_eq!(
        read_then_list.apply_list_read_success_with_committed(
            list,
            &["changed-session-a"],
            Ok(vec![(
                "session-a",
                committed_projection(4, "checksum-changed"),
            )]),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::SameGenerationChanged { generation: 4 }
        )
    );

    let mut list_then_read = Query::new();
    list_then_read.bind_connection();
    list_then_read.attach_list(ListAttachment {
        archived: false,
        cursor: None,
    });
    let list = list_then_read.begin_read().expect("list read should start");
    assert_eq!(
        list_then_read.apply_list_read_success_with_committed(
            list,
            &["session-a"],
            Ok(vec![("session-a", committed_projection(4, "checksum-a"),)]),
        ),
        QueryReadApplyResult::Applied
    );
    list_then_read.attach_session("session-a");
    let read = list_then_read
        .begin_read()
        .expect("Session read should start");
    assert_eq!(
        list_then_read.apply_session_read_success(
            read,
            view("changed-after-list", 2),
            committed(4, "checksum-changed"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::SameGenerationChanged { generation: 4 }
        )
    );
}

#[test]
fn rejected_list_does_not_partially_advance_an_earlier_rows_high_water() {
    let mut query = fresh_session();
    query.attach_list(ListAttachment {
        archived: false,
        cursor: None,
    });
    let list = query.begin_read().expect("list read should start");
    assert_eq!(
        query.apply_list_read_success_with_committed(
            list,
            &["session-b", "session-a"],
            Ok(vec![
                ("session-b", committed_projection(9, "checksum-b")),
                ("session-a", committed_projection(3, "checksum-regressed"),),
            ]),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
    query.attach_session("session-b");
    assert_eq!(query.committed_high_water(), None);
}

#[test]
fn protocol_list_rejects_duplicate_conflicting_and_missing_root_identities() {
    let cases = [
        (
            vec![
                protocol_view("session-a", Some("root-a"), Some((4, "checksum-a"))),
                protocol_view("session-a", Some("root-a"), Some((4, "checksum-a"))),
            ],
            InvalidSessionListProjection::DuplicateSessionIdentity,
        ),
        (
            vec![
                protocol_view("session-a", Some("root-a"), Some((4, "checksum-a"))),
                protocol_view("session-a", Some("root-b"), Some((4, "checksum-a"))),
            ],
            InvalidSessionListProjection::ConflictingRootIdentity,
        ),
        (
            vec![protocol_view("session-a", None, Some((4, "checksum-a")))],
            InvalidSessionListProjection::MissingRootIdentity,
        ),
        (
            vec![protocol_view("session-a", Some("root-a"), None)],
            InvalidSessionListProjection::MissingCommittedProjection,
        ),
    ];

    for (data, expected) in cases {
        let mut query = DurableSessionQueryClientState::new();
        query.bind_connection();
        query.attach_list(DurableSessionListParams::default());
        let ticket = query.begin_read().expect("list read should start");
        assert_eq!(
            query.apply_protocol_list_read_success(ticket, protocol_list_response(data)),
            QueryReadApplyResult::RejectedInvalidListProjection(expected)
        );
        assert_ne!(query.view_freshness(), QueryViewFreshness::Fresh);
    }

    let mut unavailable_view = protocol_view("session-a", None, None);
    unavailable_view["readStatus"] = json!({
        "status": "unavailable",
        "issue": "sessionNotFound"
    });
    let mut unavailable = DurableSessionQueryClientState::new();
    unavailable.bind_connection();
    unavailable.attach_list(DurableSessionListParams::default());
    let ticket = unavailable.begin_read().expect("list read should start");
    assert_eq!(
        unavailable.apply_protocol_list_read_success(
            ticket,
            protocol_list_response(vec![unavailable_view]),
        ),
        QueryReadApplyResult::Applied
    );
}

#[test]
fn protocol_list_and_read_use_the_same_committed_identity_key() {
    let params = DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-a".to_string(),
    };

    let mut read_then_list = DurableSessionQueryClientState::new();
    read_then_list.bind_connection();
    read_then_list.attach_session(params.clone());
    let read = read_then_list
        .begin_read()
        .expect("Session read should start");
    assert_eq!(
        read_then_list.apply_protocol_session_read_success(
            read,
            protocol_read_response(protocol_view(
                "session-a",
                Some("root-a"),
                Some((4, "checksum-a")),
            )),
        ),
        QueryReadApplyResult::Applied
    );
    read_then_list.attach_list(DurableSessionListParams::default());
    let list = read_then_list.begin_read().expect("list read should start");
    assert_eq!(
        read_then_list.apply_protocol_list_read_success(
            list,
            protocol_list_response(vec![protocol_view(
                "session-a",
                Some("root-a"),
                Some((3, "checksum-regressed")),
            )]),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );

    let mut list_then_read = DurableSessionQueryClientState::new();
    list_then_read.bind_connection();
    list_then_read.attach_list(DurableSessionListParams::default());
    let list = list_then_read.begin_read().expect("list read should start");
    assert_eq!(
        list_then_read.apply_protocol_list_read_success(
            list,
            protocol_list_response(vec![protocol_view(
                "session-a",
                Some("root-a"),
                Some((4, "checksum-a")),
            )]),
        ),
        QueryReadApplyResult::Applied
    );
    list_then_read.attach_session(params);
    let read = list_then_read
        .begin_read()
        .expect("Session read should start");
    assert_eq!(
        list_then_read.apply_protocol_session_read_success(
            read,
            protocol_read_response(protocol_view(
                "session-a",
                Some("root-a"),
                Some((3, "checksum-regressed")),
            )),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
}

#[test]
fn protocol_read_rejects_mismatched_identity_without_polluting_high_water() {
    let params = DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-a".to_string(),
    };
    let mut query = DurableSessionQueryClientState::new();
    query.bind_connection();
    query.attach_list(DurableSessionListParams::default());
    let list = query.begin_read().expect("list read should start");
    assert_eq!(
        query.apply_protocol_list_read_success(
            list,
            protocol_list_response(vec![protocol_view(
                "session-a",
                Some("root-a"),
                Some((4, "checksum-a")),
            )]),
        ),
        QueryReadApplyResult::Applied
    );
    query.attach_session(params.clone());
    let mismatched = query.begin_read().expect("Session read should start");
    assert_eq!(
        query.apply_protocol_session_read_success(
            mismatched,
            protocol_read_response(protocol_view(
                "session-b",
                Some("root-b"),
                Some((9, "checksum-b")),
            )),
        ),
        QueryReadApplyResult::RejectedInvalidSessionProjection(
            InvalidSessionReadProjection::SessionIdentityMismatch
        )
    );
    assert_ne!(query.view_freshness(), QueryViewFreshness::Fresh);

    query.attach_session(params);
    let regressed = query.begin_read().expect("Session reread should start");
    assert_eq!(
        query.apply_protocol_session_read_success(
            regressed,
            protocol_read_response(protocol_view(
                "session-a",
                Some("root-a"),
                Some((3, "checksum-regressed")),
            )),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
}

#[test]
fn protocol_read_rejects_wrong_or_missing_root_before_updating_high_water() {
    let cases = [
        (
            protocol_view("session-a", Some("root-b"), Some((5, "checksum-b"))),
            InvalidSessionReadProjection::RootIdentityMismatch,
        ),
        (
            protocol_view("session-a", None, Some((5, "checksum-missing-root"))),
            InvalidSessionReadProjection::MissingRootIdentity,
        ),
        (
            protocol_view("session-a", Some("root-a"), None),
            InvalidSessionReadProjection::MissingCommittedProjection,
        ),
    ];
    for (response, expected) in cases {
        let mut query = DurableSessionQueryClientState::new();
        query.bind_connection();
        query.attach_session(DurableSessionReadParams {
            session_id: "session-a".to_string(),
            root_thread_id: "root-a".to_string(),
        });
        let ticket = query.begin_read().expect("Session read should start");
        assert_eq!(
            query.apply_protocol_session_read_success(ticket, protocol_read_response(response),),
            QueryReadApplyResult::RejectedInvalidSessionProjection(expected)
        );
        assert_eq!(query.committed_high_water(), None);
        assert_ne!(query.view_freshness(), QueryViewFreshness::Fresh);
    }
}

#[test]
fn protocol_list_and_read_reject_inconsistent_committed_team_without_state_pollution() {
    let params = DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-a".to_string(),
    };

    for (invalid_view, list_error, read_error) in invalid_committed_protocol_views() {
        let accepted_list = protocol_list_response(vec![protocol_view(
            "session-a",
            Some("root-a"),
            Some((4, "checksum-accepted")),
        )]);
        let mut list_state = DurableSessionQueryClientState::new();
        list_state.bind_connection();
        list_state.attach_list(DurableSessionListParams::default());
        let initial = list_state.begin_read().expect("initial list read");
        assert_eq!(
            list_state.apply_protocol_list_read_success(initial, accepted_list.clone()),
            QueryReadApplyResult::Applied
        );
        assert_eq!(list_state.view_freshness(), QueryViewFreshness::Fresh);

        let refresh = list_state.begin_read().expect("list refresh");
        assert_eq!(
            list_state.apply_protocol_list_read_success(
                refresh,
                protocol_list_response(vec![
                    protocol_view("session-b", Some("root-b"), Some((9, "checksum-b"))),
                    invalid_view.clone(),
                ]),
            ),
            QueryReadApplyResult::RejectedInvalidListProjection(list_error)
        );
        assert_eq!(list_state.view_freshness(), QueryViewFreshness::Stale);
        assert_eq!(
            list_state.projection(),
            Some(&DurableSessionQueryProjection::List(accepted_list))
        );
        assert_eq!(list_state.committed_high_water_by_session.len(), 1);
        assert_eq!(
            list_state
                .committed_high_water_by_session
                .get(&params)
                .map(CommittedProjection::generation),
            Some(4)
        );
        assert_eq!(list_state.canonical_root_by_session.len(), 1);
        assert!(
            !list_state
                .canonical_root_by_session
                .contains_key("session-b")
        );
        assert_eq!(
            list_state
                .canonical_root_by_session
                .get("session-a")
                .map(String::as_str),
            Some("root-a")
        );

        let accepted_read = protocol_read_response(protocol_view(
            "session-a",
            Some("root-a"),
            Some((4, "checksum-accepted")),
        ));
        let mut read_state = DurableSessionQueryClientState::new();
        read_state.bind_connection();
        read_state.attach_session(params.clone());
        let initial = read_state.begin_read().expect("initial Session read");
        assert_eq!(
            read_state.apply_protocol_session_read_success(initial, accepted_read.clone()),
            QueryReadApplyResult::Applied
        );
        assert_eq!(read_state.view_freshness(), QueryViewFreshness::Fresh);

        let refresh = read_state.begin_read().expect("Session refresh");
        assert_eq!(
            read_state.apply_protocol_session_read_success(
                refresh,
                protocol_read_response(invalid_view),
            ),
            QueryReadApplyResult::RejectedInvalidSessionProjection(read_error)
        );
        assert_eq!(read_state.view_freshness(), QueryViewFreshness::Stale);
        assert_eq!(
            read_state.projection(),
            Some(&DurableSessionQueryProjection::Session(accepted_read))
        );
        assert_eq!(
            read_state
                .committed_high_water()
                .map(CommittedProjection::generation),
            Some(4)
        );
        assert_eq!(read_state.committed_high_water_by_session.len(), 1);
        assert_eq!(read_state.canonical_root_by_session.len(), 1);
        assert_eq!(
            read_state
                .canonical_root_by_session
                .get("session-a")
                .map(String::as_str),
            Some("root-a")
        );
    }
}

#[test]
fn protocol_read_accepts_typed_unavailable_without_a_root_or_team() {
    let mut unavailable = protocol_view("session-a", None, None);
    unavailable["readStatus"] = json!({
        "status": "unavailable",
        "issue": "sessionNotFound"
    });
    let mut query = DurableSessionQueryClientState::new();
    query.bind_connection();
    query.attach_session(DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-a".to_string(),
    });
    let ticket = query.begin_read().expect("Session read should start");
    assert_eq!(
        query.apply_protocol_session_read_success(ticket, protocol_read_response(unavailable),),
        QueryReadApplyResult::Applied
    );
    assert_eq!(query.committed_high_water(), None);
    assert_eq!(query.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn typed_unavailable_cannot_authenticate_an_attachment_with_a_conflicting_known_root() {
    let mut query = DurableSessionQueryClientState::new();
    query.bind_connection();
    query.attach_list(DurableSessionListParams::default());
    let list = query.begin_read().expect("list read should start");
    assert_eq!(
        query.apply_protocol_list_read_success(
            list,
            protocol_list_response(vec![protocol_view(
                "session-a",
                Some("root-a"),
                Some((4, "checksum-a")),
            )]),
        ),
        QueryReadApplyResult::Applied
    );

    let mut unavailable = protocol_view("session-a", None, None);
    unavailable["readStatus"] = json!({
        "status": "unavailable",
        "issue": "sessionNotFound"
    });
    query.attach_session(DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-b".to_string(),
    });
    let read = query.begin_read().expect("conflicting Session read");
    assert_eq!(
        query.apply_protocol_session_read_success(read, protocol_read_response(unavailable)),
        QueryReadApplyResult::RejectedInvalidSessionProjection(
            InvalidSessionReadProjection::ConflictingRootIdentity
        )
    );
    assert_ne!(query.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn protocol_root_identity_is_stable_across_list_and_read_boundaries() {
    fn list_with_root(root: &str, generation: u64) -> DurableSessionListResponse {
        protocol_list_response(vec![protocol_view(
            "session-a",
            Some(root),
            Some((generation, "checksum-a")),
        )])
    }

    let mut list_then_list = DurableSessionQueryClientState::new();
    list_then_list.bind_connection();
    list_then_list.attach_list(DurableSessionListParams::default());
    let first = list_then_list.begin_read().expect("first list read");
    assert_eq!(
        list_then_list.apply_protocol_list_read_success(first, list_with_root("root-a", 4)),
        QueryReadApplyResult::Applied
    );
    list_then_list.attach_list(DurableSessionListParams::default());
    let conflicting = list_then_list.begin_read().expect("conflicting list read");
    assert_eq!(
        list_then_list.apply_protocol_list_read_success(conflicting, list_with_root("root-b", 3),),
        QueryReadApplyResult::RejectedInvalidListProjection(
            InvalidSessionListProjection::ConflictingRootIdentity
        )
    );
    assert_eq!(list_then_list.committed_high_water_by_session.len(), 1);
    assert_ne!(list_then_list.view_freshness(), QueryViewFreshness::Fresh);

    let mut list_then_read = DurableSessionQueryClientState::new();
    list_then_read.bind_connection();
    list_then_read.attach_list(DurableSessionListParams::default());
    let list = list_then_read.begin_read().expect("list read");
    assert_eq!(
        list_then_read.apply_protocol_list_read_success(list, list_with_root("root-a", 4)),
        QueryReadApplyResult::Applied
    );
    list_then_read.attach_session(DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-b".to_string(),
    });
    let read = list_then_read
        .begin_read()
        .expect("conflicting Session read");
    assert_eq!(
        list_then_read.apply_protocol_session_read_success(
            read,
            protocol_read_response(protocol_view(
                "session-a",
                Some("root-b"),
                Some((3, "checksum-regressed")),
            )),
        ),
        QueryReadApplyResult::RejectedInvalidSessionProjection(
            InvalidSessionReadProjection::ConflictingRootIdentity
        )
    );
    assert_eq!(list_then_read.committed_high_water_by_session.len(), 1);
    assert_ne!(list_then_read.view_freshness(), QueryViewFreshness::Fresh);

    let mut read_then_list = DurableSessionQueryClientState::new();
    read_then_list.bind_connection();
    read_then_list.attach_session(DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-a".to_string(),
    });
    let read = read_then_list.begin_read().expect("Session read");
    assert_eq!(
        read_then_list.apply_protocol_session_read_success(
            read,
            protocol_read_response(protocol_view(
                "session-a",
                Some("root-a"),
                Some((4, "checksum-a")),
            )),
        ),
        QueryReadApplyResult::Applied
    );
    read_then_list.attach_list(DurableSessionListParams::default());
    let list = read_then_list.begin_read().expect("conflicting list read");
    assert_eq!(
        read_then_list.apply_protocol_list_read_success(list, list_with_root("root-b", 3)),
        QueryReadApplyResult::RejectedInvalidListProjection(
            InvalidSessionListProjection::ConflictingRootIdentity
        )
    );
    assert_eq!(read_then_list.committed_high_water_by_session.len(), 1);
    assert_ne!(read_then_list.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn canonical_root_identity_survives_typed_team_unavailability() {
    fn incomplete_without_team(session_id: &str, root_thread_id: &str) -> Value {
        let mut view = protocol_view(session_id, Some(root_thread_id), None);
        view["readStatus"] = json!({
            "status": "incomplete",
            "issue": "teamSnapshotMissing"
        });
        view
    }

    let mut list_state = DurableSessionQueryClientState::new();
    list_state.bind_connection();
    list_state.attach_list(DurableSessionListParams::default());
    let first = list_state.begin_read().expect("incomplete list read");
    assert_eq!(
        list_state.apply_protocol_list_read_success(
            first,
            protocol_list_response(vec![incomplete_without_team("session-a", "root-a")]),
        ),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        list_state
            .canonical_root_by_session
            .get("session-a")
            .map(String::as_str),
        Some("root-a")
    );
    assert!(list_state.committed_high_water_by_session.is_empty());
    list_state.attach_list(DurableSessionListParams::default());
    let conflicting = list_state.begin_read().expect("conflicting list read");
    assert_eq!(
        list_state.apply_protocol_list_read_success(
            conflicting,
            protocol_list_response(vec![protocol_view(
                "session-a",
                Some("root-b"),
                Some((1, "checksum-b")),
            )]),
        ),
        QueryReadApplyResult::RejectedInvalidListProjection(
            InvalidSessionListProjection::ConflictingRootIdentity
        )
    );

    let mut read_state = DurableSessionQueryClientState::new();
    read_state.bind_connection();
    read_state.attach_session(DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-a".to_string(),
    });
    let first = read_state.begin_read().expect("incomplete Session read");
    assert_eq!(
        read_state.apply_protocol_session_read_success(
            first,
            protocol_read_response(incomplete_without_team("session-a", "root-a")),
        ),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        read_state
            .canonical_root_by_session
            .get("session-a")
            .map(String::as_str),
        Some("root-a")
    );
    assert!(read_state.committed_high_water_by_session.is_empty());
    read_state.attach_session(DurableSessionReadParams {
        session_id: "session-a".to_string(),
        root_thread_id: "root-b".to_string(),
    });
    let conflicting = read_state.begin_read().expect("conflicting Session read");
    assert_eq!(
        read_state.apply_protocol_session_read_success(
            conflicting,
            protocol_read_response(protocol_view(
                "session-a",
                Some("root-b"),
                Some((1, "checksum-b")),
            )),
        ),
        QueryReadApplyResult::RejectedInvalidSessionProjection(
            InvalidSessionReadProjection::ConflictingRootIdentity
        )
    );
}

#[test]
fn rejected_list_does_not_partially_bind_canonical_roots() {
    let mut state = DurableSessionQueryClientState::new();
    state.bind_connection();
    state.attach_list(DurableSessionListParams::default());
    let first = state.begin_read().expect("first list read");
    assert_eq!(
        state.apply_protocol_list_read_success(
            first,
            protocol_list_response(vec![protocol_view(
                "session-a",
                Some("root-a"),
                Some((4, "checksum-a")),
            )]),
        ),
        QueryReadApplyResult::Applied
    );
    let mut incomplete_b = protocol_view("session-b", Some("root-b"), None);
    incomplete_b["readStatus"] = json!({
        "status": "incomplete",
        "issue": "teamSnapshotMissing"
    });
    state.attach_list(DurableSessionListParams::default());
    let conflicting = state.begin_read().expect("conflicting list read");
    assert_eq!(
        state.apply_protocol_list_read_success(
            conflicting,
            protocol_list_response(vec![
                incomplete_b,
                protocol_view(
                    "session-a",
                    Some("root-conflict"),
                    Some((3, "checksum-conflict")),
                ),
            ]),
        ),
        QueryReadApplyResult::RejectedInvalidListProjection(
            InvalidSessionListProjection::ConflictingRootIdentity
        )
    );
    assert_eq!(state.canonical_root_by_session.len(), 1);
    assert!(!state.canonical_root_by_session.contains_key("session-b"));
    assert_ne!(state.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn response_kind_mismatch_consumes_the_read_and_cannot_be_reused() {
    let mut query = connected_session();
    let ticket = query.begin_read().expect("read should start");
    assert_eq!(
        query.apply_list_read_success(ticket, &["wrong-kind"]),
        QueryReadApplyResult::AttachmentMismatch
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Absent);
    assert_eq!(
        query.apply_session_read_success(
            ticket,
            view("late-correction", 1),
            committed(1, "checksum"),
        ),
        QueryReadApplyResult::Retired
    );
}

#[test]
fn attachment_switch_and_detach_retire_old_reads() {
    let mut query = connected_session();
    let session_read = query.begin_read().expect("session read should start");
    query.attach_list(ListAttachment {
        archived: true,
        cursor: None,
    });
    assert_eq!(
        query.apply_session_read_success(session_read, view("wrong", 1), committed(1, "checksum"),),
        QueryReadApplyResult::Retired
    );

    let list_read = query.begin_read().expect("list read should start");
    query.detach();
    assert_eq!(
        query.apply_list_read_success(list_read, &["detached"]),
        QueryReadApplyResult::Retired
    );
    assert_eq!(query.attachment(), None);
    assert_eq!(query.projection(), None);
}

#[test]
fn failure_lag_disconnect_and_eof_never_restore_freshness() {
    let mut query = fresh_session();
    let refresh = query.begin_read().expect("refresh should start");
    assert!(query.apply_read_failure(refresh));
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);

    let refresh = query.begin_read().expect("refresh should start");
    query.on_lagged();
    assert!(!query.apply_read_failure(refresh));
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);

    query.on_disconnected();
    assert!(!query.is_connected());
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);

    query.bind_connection();
    let refresh = query.begin_read().expect("refresh should start");
    query.on_event_stream_closed();
    assert!(!query.apply_read_failure(refresh));
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
}

#[test]
fn reconnect_requires_a_new_read_and_retires_old_connection_completion() {
    let mut query = fresh_session();
    let old_epoch = query.connection_epoch();
    let old_read = query.begin_read().expect("old read should start");
    query.on_disconnected();
    let new_epoch = query.bind_connection();
    assert!(new_epoch > old_epoch);
    assert_eq!(
        query.apply_session_read_success(old_read, view("old", 1), committed(1, "checksum-old"),),
        QueryReadApplyResult::Retired
    );

    let new_read = query.begin_read().expect("new read should start");
    assert_eq!(new_read.connection_epoch(), new_epoch);
    assert_eq!(
        query.apply_session_read_success(new_read, view("new", 9), committed(4, "checksum-a"),),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(4)
    );
}

#[test]
fn committed_generation_regression_is_rejected_and_view_stays_stale() {
    let mut query = fresh_session();
    let refresh = query.begin_read().expect("refresh should start");
    assert_eq!(
        query.apply_session_read_success(
            refresh,
            view("regressed", 99),
            committed(3, "checksum-newer-domain"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
    assert_eq!(
        query.projection(),
        Some(&DurableSessionQueryProjection::Session(view("view-a", 9)))
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(4)
    );
}

#[test]
fn same_session_reattach_preserves_rollback_protection() {
    let mut query = fresh_session();
    let retired = query.begin_read().expect("read should start");

    query.attach_session("session-a");
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
    assert_eq!(
        query.projection(),
        Some(&DurableSessionQueryProjection::Session(view("view-a", 9)))
    );
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(4)
    );
    assert_eq!(
        query.apply_session_read_success(
            retired,
            view("retired", 10),
            committed(5, "checksum-retired"),
        ),
        QueryReadApplyResult::Retired
    );

    let reread = query.begin_read().expect("reattached read should start");
    assert_eq!(
        query.apply_session_read_success(
            reread,
            view("regressed", 10),
            committed(3, "checksum-regressed"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
}

#[test]
fn list_detour_preserves_session_generation_rollback_protection() {
    let mut query = fresh_session();
    query.attach_list(ListAttachment {
        archived: false,
        cursor: None,
    });
    assert_eq!(query.recent_session_attachment(), Some(&"session-a"));
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(4)
    );
    let list_read = query.begin_read().expect("list read should start");
    assert_eq!(
        query.apply_list_read_success(list_read, &["session-a"]),
        QueryReadApplyResult::Applied
    );

    query.attach_session("session-a");
    assert_eq!(query.projection(), None);
    let session_read = query.begin_read().expect("Session reread should start");
    assert_eq!(
        query.apply_session_read_success(
            session_read,
            view("regressed-after-list", 10),
            committed(3, "checksum-regressed"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
    assert_ne!(query.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn list_detour_preserves_same_generation_fingerprint_protection() {
    let mut query = fresh_session();
    query.attach_list(ListAttachment {
        archived: true,
        cursor: Some("archived-page"),
    });
    let list_read = query.begin_read().expect("list read should start");
    assert_eq!(
        query.apply_list_read_success(list_read, &["session-a"]),
        QueryReadApplyResult::Applied
    );
    query.attach_session("session-a");

    let session_read = query.begin_read().expect("Session reread should start");
    assert_eq!(
        query.apply_session_read_success(
            session_read,
            view("changed-after-list", 10),
            committed(4, "checksum-changed"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::SameGenerationChanged { generation: 4 }
        )
    );
    assert_ne!(query.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn different_session_starts_an_independent_committed_high_water() {
    let mut query = fresh_session();
    query.attach_list(ListAttachment {
        archived: false,
        cursor: None,
    });
    query.attach_session("session-b");

    assert_eq!(query.projection(), None);
    assert_eq!(query.committed_high_water(), None);
    assert_eq!(query.recent_session_attachment(), Some(&"session-b"));
    let read = query.begin_read().expect("new Session read should start");
    assert_eq!(
        query.apply_session_read_success(read, view("session-b", 1), committed(1, "checksum-b"),),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(1)
    );
}

#[test]
fn returning_to_an_earlier_session_restores_its_committed_high_water() {
    let mut query = fresh_session();
    query.attach_session("session-b");
    let session_b = query.begin_read().expect("Session B read should start");
    assert_eq!(
        query.apply_session_read_success(
            session_b,
            view("session-b", 1),
            committed(2, "checksum-b"),
        ),
        QueryReadApplyResult::Applied
    );

    query.attach_session("session-a");
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(4)
    );
    let regressed = query.begin_read().expect("Session A reread should start");
    assert_eq!(
        query.apply_session_read_success(
            regressed,
            view("regressed-session-a", 10),
            committed(3, "checksum-regressed"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
    assert_ne!(query.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn detach_does_not_erase_a_sessions_committed_high_water() {
    let mut query = fresh_session();
    query.detach();
    assert_eq!(query.committed_high_water(), None);

    query.attach_session("session-a");
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(4)
    );
    let regressed = query.begin_read().expect("reattached read should start");
    assert_eq!(
        query.apply_session_read_success(
            regressed,
            view("regressed-after-detach", 10),
            committed(3, "checksum-regressed"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
}

#[test]
fn same_generation_with_changed_committed_state_is_rejected() {
    let mut query = fresh_session();
    let refresh = query.begin_read().expect("refresh should start");
    assert_eq!(
        query.apply_session_read_success(
            refresh,
            view("changed", 10),
            committed(4, "checksum-changed"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::SameGenerationChanged { generation: 4 }
        )
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
}

#[test]
fn same_generation_with_equal_commit_fingerprint_can_refresh() {
    let mut query = fresh_session();
    let refresh = query.begin_read().expect("refresh should start");
    assert_eq!(
        query.apply_session_read_success(refresh, view("same", 9), committed(4, "checksum-a"),),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        query.projection(),
        Some(&DurableSessionQueryProjection::Session(view("same", 9)))
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Fresh);
}

#[test]
fn team_revision_does_not_substitute_for_commit_generation() {
    let mut query = fresh_session();
    let refresh = query.begin_read().expect("refresh should start");
    assert_eq!(
        query.apply_session_read_success(
            refresh,
            view("new-commit-lower-domain-revision", 1),
            committed(5, "checksum-b"),
        ),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(5)
    );
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::fingerprint),
        Some(&"checksum-b")
    );
}

#[test]
fn unavailable_view_replaces_whole_view_without_clearing_high_water() {
    let mut query = fresh_session();
    let unavailable = query.begin_read().expect("unavailable read should start");
    assert_eq!(
        query.apply_session_read_success(
            unavailable,
            view("typed-unavailable", 0),
            SessionCommittedRead::Unavailable,
        ),
        QueryReadApplyResult::Applied
    );
    assert_eq!(
        query.projection(),
        Some(&DurableSessionQueryProjection::Session(view(
            "typed-unavailable",
            0,
        )))
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Fresh);
    assert_eq!(
        query
            .committed_high_water()
            .map(CommittedProjection::generation),
        Some(4)
    );

    let regressed = query.begin_read().expect("regressed read should start");
    assert_eq!(
        query.apply_session_read_success(
            regressed,
            view("regressed", 10),
            committed(3, "checksum-c"),
        ),
        QueryReadApplyResult::RejectedCommittedProjection(
            CommittedProjectionConflict::GenerationRegressed {
                accepted_generation: 4,
                received_generation: 3,
            }
        )
    );
    assert_eq!(query.view_freshness(), QueryViewFreshness::Stale);
}
