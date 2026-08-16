use codex_protocol::models::ExecutedToolCall;
use codex_protocol::models::FunctionCallOutputBody;
use codex_protocol::models::FunctionCallOutputPayload;
use codex_protocol::models::ResponseItem;
use pretty_assertions::assert_ne;

use super::prompt_input_tokens;

fn tool_output() -> ResponseItem {
    ResponseItem::FunctionCallOutput {
        id: None,
        call_id: "call-1".to_string(),
        output: FunctionCallOutputPayload {
            body: FunctionCallOutputBody::Text("the index rebuild took nine minutes".to_string()),
            success: Some(true),
        },
        internal_chat_message_metadata_passthrough: None,
    }
}

/// Attempted-tool metadata is part of what the input costs.
///
/// This is why the sampling loop attaches it before the projection is measured: if the budget were
/// taken over the bare history, the request could still overrun once this arrived.
#[test]
fn attempted_tool_metadata_counts_against_the_request_budget() {
    let bare = vec![tool_output()];

    let mut with_metadata = tool_output();
    with_metadata.append_executed_tool_calls(vec![ExecutedToolCall::new(
        "team_publish".to_string(),
        serde_json::json!({
            "title": "index rebuild is slow",
            "summary": "rebuilding the orders index takes nine minutes on staging",
        }),
    )]);
    let with_metadata = vec![with_metadata];

    assert_ne!(
        prompt_input_tokens(&bare),
        prompt_input_tokens(&with_metadata),
        "the estimator must see the metadata, or freezing it before the budget buys nothing"
    );
    assert!(
        prompt_input_tokens(&with_metadata) > prompt_input_tokens(&bare),
        "metadata only ever adds to what the provider receives"
    );
}
