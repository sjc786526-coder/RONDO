//! Which tool-call sources may produce encrypted inter-agent communication.
//!
//! This is not a style question. A communication built with
//! `new_encrypted` puts its payload into the child's first request as
//! `AgentMessageInputContent::EncryptedContent`, and a provider rejects that
//! with `invalid_encrypted_content` when the bytes are not real ciphertext. In
//! the 2026-08-19 M-5 smoke every one of the member's eight turns failed that
//! way while root's twenty-two succeeded, because the code-mode `spawn_agent`
//! message -- plain text serialized from the model's own JS object -- was
//! wrapped as though it were encrypted. The member never completed a turn, so
//! no team tool could run and gate 1 could not be judged at all.

use super::communication_from_tool_message;
use crate::tools::context::ToolCallSource;
use codex_protocol::AgentPath;

const MESSAGE: &str = "Read NOTES.md and publish the finding as a team event.";

fn code_mode_source() -> ToolCallSource {
    ToolCallSource::CodeMode {
        cell_id: "cell-1".to_string(),
        runtime_tool_call_id: "rt-1".to_string(),
    }
}

fn paths() -> (AgentPath, AgentPath) {
    (
        AgentPath::root(),
        "/root/worker".parse().expect("member agent path"),
    )
}

#[test]
fn code_mode_messages_are_plaintext() {
    let (author, recipient) = paths();
    let communication = communication_from_tool_message(
        author,
        recipient,
        MESSAGE.to_string(),
        &code_mode_source(),
        /*trigger_turn*/ true,
    );
    assert!(
        communication.encrypted_content.is_none(),
        "a code-mode tool message is serialized from the model's JS object and is \
         never ciphertext, so it must not be carried as encrypted content"
    );
    assert!(
        communication.content.contains(MESSAGE),
        "the rendered plaintext must still carry the task the model sent"
    );
}

#[test]
fn code_mode_messages_reach_the_model_as_input_text() {
    // Guards the assembly layer as well as the handler: the failure observed in
    // production was visible only in the child's request body.
    let (author, recipient) = paths();
    let communication = communication_from_tool_message(
        author,
        recipient,
        MESSAGE.to_string(),
        &code_mode_source(),
        /*trigger_turn*/ true,
    );
    let rendered = serde_json::to_string(&communication.to_model_input_item())
        .expect("agent message serializes");
    assert!(
        !rendered.contains("encrypted_content"),
        "the child's first request must not contain an encrypted_content field: {rendered}"
    );
    assert!(rendered.contains(MESSAGE), "rendered item: {rendered}");
}

#[test]
fn code_mode_followup_and_send_message_share_the_rule() {
    // `send_message` and `followup_task` call the same helper with
    // `trigger_turn` false and true respectively.
    for trigger_turn in [false, true] {
        let (author, recipient) = paths();
        let communication = communication_from_tool_message(
            author,
            recipient,
            MESSAGE.to_string(),
            &code_mode_source(),
            trigger_turn,
        );
        assert!(
            communication.encrypted_content.is_none(),
            "trigger_turn={trigger_turn} must still be plaintext under code mode"
        );
    }
}

#[test]
fn direct_plaintext_messages_stay_plaintext() {
    let (author, recipient) = paths();
    let communication = communication_from_tool_message(
        author,
        recipient,
        MESSAGE.to_string(),
        &ToolCallSource::DirectPlaintextMessage,
        /*trigger_turn*/ true,
    );
    assert!(communication.encrypted_content.is_none());
    assert!(communication.content.contains(MESSAGE));
}

#[test]
fn direct_calls_keep_encrypted_arguments() {
    // The regression must not flatten every source to plaintext: a `Direct`
    // call may genuinely carry encrypted arguments, and `ToolCall::direct_source`
    // is what separates that from the plaintext case.
    let (author, recipient) = paths();
    let communication = communication_from_tool_message(
        author,
        recipient,
        MESSAGE.to_string(),
        &ToolCallSource::Direct,
        /*trigger_turn*/ true,
    );
    assert_eq!(
        communication.encrypted_content.as_deref(),
        Some(MESSAGE),
        "Direct keeps its existing encrypted-argument semantics"
    );
}
