use super::*;
use codex_app_server_protocol::DurableSessionControlOperationKind;
use codex_app_server_protocol::DurableSessionControlRejectionReason;

#[test]
fn parses_only_formal_control_commands() {
    assert_eq!(
        DurableSessionControlCommand::parse("archive"),
        Ok(DurableSessionControlCommand::Mutate(
            DurableSessionControlOperation::Archive
        ))
    );
    assert!(matches!(
        DurableSessionControlCommand::parse("track ver-a open tracking resolved"),
        Ok(DurableSessionControlCommand::Mutate(
            DurableSessionControlOperation::SetRootState { .. }
        ))
    ));
    assert_eq!(
        DurableSessionControlCommand::parse("read session-a root-a"),
        Ok(DurableSessionControlCommand::Read {
            session_id: "session-a".to_string(),
            root_thread_id: "root-a".to_string(),
        })
    );
    assert_eq!(
        DurableSessionControlCommand::parse("unarchive session-a"),
        Err(DURABLE_SESSION_CONTROL_USAGE)
    );
}

#[test]
fn formal_control_result_gallery() {
    let applied = render_completion(&DurableSessionControlResponse {
        outcome: DurableSessionControlOutcome::Applied {
            effect: DurableSessionControlEffect::Archived {
                affected_thread_ids: vec!["root-a".to_string(), "child-a".to_string()],
            },
        },
    });
    let rejected = render_completion(&DurableSessionControlResponse {
        outcome: DurableSessionControlOutcome::Rejected {
            operation: DurableSessionControlOperationKind::Delete,
            reason: DurableSessionControlRejectionReason::StalePrecondition,
            message: "the committed Team changed".to_string(),
        },
    });
    let unknown = render_transport_unknown("session/control timed out after submission");
    insta::assert_snapshot!(
        "durable_session_control_result_gallery",
        [applied, rejected, unknown].join("\n\n")
    );
}
