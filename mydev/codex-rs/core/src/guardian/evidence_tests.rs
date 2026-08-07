use std::fs;
use std::path::Path;

use codex_analytics::CompactionImplementation;
use codex_analytics::CompactionPhase;
use codex_analytics::CompactionReason;
use codex_analytics::CompactionTrigger;
use codex_api::Reasoning;
use codex_api::ResponsesApiRequest;
use codex_protocol::ResponseItemId;
use codex_protocol::models::ContentItem;
use codex_protocol::models::FunctionCallOutputBody;
use codex_protocol::models::FunctionCallOutputPayload;
use codex_protocol::models::ResponseItem;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use tempfile::TempDir;

use super::GuardianEvidenceRound;
use super::GuardianReviewAnalyticsResult;
use super::STRIPPED_REQUEST_FIELDS;
use super::capture_final_request;
use super::normalize_request;
use crate::responses_metadata::CodexResponsesMetadata;
use crate::responses_metadata::CodexResponsesRequestKind;
use crate::responses_metadata::CompactionTurnMetadata;

fn request_with_tool_call_pair() -> ResponsesApiRequest {
    ResponsesApiRequest {
        model: "codex-auto-review".to_string(),
        instructions: "guardian policy".to_string(),
        input: vec![
            ResponseItem::Message {
                id: Some(ResponseItemId::new("msg_volatile")),
                role: "user".to_string(),
                content: vec![ContentItem::InputText {
                    text: "review this action".to_string(),
                }],
                phase: None,
                internal_chat_message_metadata_passthrough: None,
            },
            ResponseItem::FunctionCall {
                id: Some(ResponseItemId::new("fc_volatile")),
                name: "shell".to_string(),
                namespace: None,
                arguments: "{}".to_string(),
                call_id: "call_7f3a".to_string(),
                internal_chat_message_metadata_passthrough: None,
            },
            ResponseItem::FunctionCallOutput {
                id: Some(ResponseItemId::new("fco_volatile")),
                call_id: "call_7f3a".to_string(),
                output: FunctionCallOutputPayload {
                    body: FunctionCallOutputBody::Text("ok".to_string()),
                    success: Some(true),
                },
                internal_chat_message_metadata_passthrough: None,
            },
        ],
        tools: None,
        tool_choice: "auto".to_string(),
        parallel_tool_calls: false,
        reasoning: Some(Reasoning {
            effort: None,
            summary: None,
            context: None,
        }),
        store: false,
        stream: true,
        stream_options: None,
        include: vec!["reasoning.encrypted_content".to_string()],
        service_tier: None,
        prompt_cache_key: Some("guardian-cache-key".to_string()),
        text: None,
        client_metadata: Some(
            [("thread_id".to_string(), "thread-abc".to_string())]
                .into_iter()
                .collect(),
        ),
    }
}

#[test]
fn normalize_request_strips_structural_fields_and_volatile_ids() {
    let normalized =
        normalize_request(&request_with_tool_call_pair()).expect("request should normalize");

    let object = normalized
        .as_object()
        .expect("normalized request is an object");
    let stripped: Vec<&str> = STRIPPED_REQUEST_FIELDS
        .iter()
        .copied()
        .filter(|field| object.contains_key(*field))
        .collect();
    assert_eq!(stripped, Vec::<&str>::new());
    assert_eq!(
        normalized["input"],
        json!([
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "review this action"}],
            },
            {
                "type": "function_call",
                "name": "shell",
                "arguments": "{}",
                "call_id": "call_0",
            },
            {
                "type": "function_call_output",
                "call_id": "call_0",
                "output": "ok",
            },
        ])
    );
}

#[test]
fn normalize_request_is_idempotent_and_keeps_distinct_calls_apart() {
    let mut request = request_with_tool_call_pair();
    request.input.push(ResponseItem::FunctionCall {
        id: None,
        name: "shell".to_string(),
        namespace: None,
        arguments: "{}".to_string(),
        call_id: "call_91bd".to_string(),
        internal_chat_message_metadata_passthrough: None,
    });

    let first = normalize_request(&request).expect("request should normalize");
    let second = normalize_request(&request).expect("request should normalize");
    assert_eq!(
        serde_json::to_vec(&first).expect("serialize"),
        serde_json::to_vec(&second).expect("serialize")
    );

    let call_ids: Vec<&str> = first["input"]
        .as_array()
        .expect("input array")
        .iter()
        .filter_map(|item| item["call_id"].as_str())
        .collect();
    assert_eq!(call_ids, vec!["call_0", "call_0", "call_1"]);
}

#[test]
fn normalize_request_is_a_fixed_point_for_already_canonical_call_ids() {
    let mut request = request_with_tool_call_pair();
    for item in &mut request.input {
        if let ResponseItem::FunctionCall { call_id, .. }
        | ResponseItem::FunctionCallOutput { call_id, .. } = item
        {
            *call_id = "call_0".to_string();
        }
    }

    assert_eq!(
        normalize_request(&request).expect("request should normalize"),
        normalize_request(&request_with_tool_call_pair()).expect("request should normalize")
    );
}

fn turn_request_metadata(thread_id: &str) -> CodexResponsesMetadata {
    CodexResponsesMetadata {
        request_kind: Some(CodexResponsesRequestKind::Turn),
        ..CodexResponsesMetadata::new(
            "installation".to_string(),
            "session".to_string(),
            thread_id.to_string(),
            "window".to_string(),
        )
    }
}

fn request_with_instructions(instructions: &str) -> ResponsesApiRequest {
    ResponsesApiRequest {
        instructions: instructions.to_string(),
        ..request_with_tool_call_pair()
    }
}

fn read_bundle(dir: &Path, file_name: &str) -> Value {
    let contents = fs::read_to_string(dir.join(file_name))
        .unwrap_or_else(|err| panic!("read {}: {err}", dir.join(file_name).display()));
    serde_json::from_str(&contents).expect("bundle should be valid json")
}

#[test]
fn concurrent_rounds_keep_their_own_final_request() {
    let evidence_dir = TempDir::new().expect("temp dir");
    let first = GuardianEvidenceRound::new(evidence_dir.path().join("review-1"), "review-1");
    let second = GuardianEvidenceRound::new(evidence_dir.path().join("review-2"), "review-2");
    let first_binding = first.bind("concurrent-thread-1".to_string());
    let second_binding = second.bind("concurrent-thread-2".to_string());

    // Interleaved, and the first round retries: the last request for a session wins.
    capture_final_request(
        &turn_request_metadata("concurrent-thread-1"),
        &request_with_instructions("first round, attempt 1"),
    );
    capture_final_request(
        &turn_request_metadata("concurrent-thread-2"),
        &request_with_instructions("second round"),
    );
    capture_final_request(
        &turn_request_metadata("concurrent-thread-1"),
        &request_with_instructions("first round, attempt 2"),
    );

    drop(first_binding);
    drop(second_binding);
    let analytics = GuardianReviewAnalyticsResult::without_session();
    first.finalize(&analytics, /*duration_ms*/ 11);
    second.finalize(&analytics, /*duration_ms*/ 22);

    let first_dir = evidence_dir.path().join("review-1");
    let second_dir = evidence_dir.path().join("review-2");
    assert_eq!(
        (
            read_bundle(&first_dir, "E_final.json")["instructions"].clone(),
            read_bundle(&second_dir, "E_final.json")["instructions"].clone(),
        ),
        (json!("first round, attempt 2"), json!("second round"))
    );
    assert_eq!(
        (
            read_bundle(&first_dir, "meta.json")["review_id"].clone(),
            read_bundle(&first_dir, "meta.json")["evidence"].clone(),
            read_bundle(&first_dir, "meta.json")["duration_ms"].clone(),
        ),
        (json!("review-1"), json!("e_final"), json!(11))
    );
}

#[cfg(unix)]
#[test]
fn evidence_bundle_is_written_with_private_permissions() {
    use std::os::unix::fs::PermissionsExt;

    let evidence_dir = TempDir::new().expect("temp dir");
    let round = GuardianEvidenceRound::new(evidence_dir.path().join("review-perm"), "review-perm");
    let binding = round.bind("permission-thread".to_string());
    capture_final_request(
        &turn_request_metadata("permission-thread"),
        &request_with_instructions("permissions"),
    );
    drop(binding);
    round.finalize(
        &GuardianReviewAnalyticsResult::without_session(),
        /*duration_ms*/ 1,
    );

    let bundle_dir = evidence_dir.path().join("review-perm");
    let mode = |path: &Path| {
        fs::metadata(path)
            .unwrap_or_else(|err| panic!("stat {}: {err}", path.display()))
            .permissions()
            .mode()
            & 0o777
    };
    assert_eq!(
        (
            mode(&bundle_dir),
            mode(&bundle_dir.join("E_final.json")),
            mode(&bundle_dir.join("meta.json")),
        ),
        (0o700, 0o600, 0o600)
    );
}

#[test]
fn only_turn_requests_from_a_bound_session_are_captured() {
    let evidence_dir = TempDir::new().expect("temp dir");
    let round =
        GuardianEvidenceRound::new(evidence_dir.path().join("review-filter"), "review-filter");
    let binding = round.bind("filtered-thread".to_string());

    for request_kind in [
        None,
        Some(CodexResponsesRequestKind::Prewarm),
        Some(CodexResponsesRequestKind::Memory),
        Some(CodexResponsesRequestKind::Compaction(
            CompactionTurnMetadata::new(
                CompactionTrigger::Auto,
                CompactionReason::ContextLimit,
                CompactionImplementation::Responses,
                CompactionPhase::MidTurn,
            ),
        )),
    ] {
        capture_final_request(
            &CodexResponsesMetadata {
                request_kind,
                ..turn_request_metadata("filtered-thread")
            },
            &request_with_instructions("must not be captured"),
        );
    }
    // A `turn` request from a session that is not serving this round.
    capture_final_request(
        &turn_request_metadata("unbound-thread"),
        &request_with_instructions("must not be captured"),
    );
    // A `turn` request that arrives after the round released the session.
    drop(binding);
    capture_final_request(
        &turn_request_metadata("filtered-thread"),
        &request_with_instructions("must not be captured"),
    );

    round.finalize(
        &GuardianReviewAnalyticsResult::without_session(),
        /*duration_ms*/ 5,
    );

    let bundle_dir = evidence_dir.path().join("review-filter");
    assert!(!bundle_dir.join("E_final.json").exists());
    assert_eq!(
        read_bundle(&bundle_dir, "meta.json")["evidence"],
        json!("none")
    );
}
