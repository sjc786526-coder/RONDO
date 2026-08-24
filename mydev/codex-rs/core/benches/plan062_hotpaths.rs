use codex_core::test_support::plan062_hotpaths::ToolSpecsWorkload;
use codex_core::test_support::plan062_hotpaths::UnifiedOutputWorkload;
use codex_core::test_support::plan062_hotpaths::normalize_history;
use codex_protocol::models::ContentItem;
use codex_protocol::models::FunctionCallOutputPayload;
use codex_protocol::models::ResponseItem;
use divan::Bencher;

const TOOL_SPEC_REPEATS: usize = 16;
const UNIFIED_EXEC_MAX_BYTES: usize = 1024 * 1024;

#[global_allocator]
static ALLOC: divan::AllocProfiler = divan::AllocProfiler::system();

fn main() {
    divan::main();
}

#[divan::bench(args = [8, 32, 128])]
fn history_turns(bencher: Bencher, turns: usize) {
    let fixture = history_fixture(turns);
    bencher
        .with_inputs(move || fixture.clone())
        .bench_local_values(normalize_history);
}

#[divan::bench(args = [8, 32, 64])]
fn tool_specs(bencher: Bencher, spec_count: usize) {
    let workload = ToolSpecsWorkload::new(spec_count);
    bencher.bench_local(|| workload.clone_repeated(TOOL_SPEC_REPEATS));
}

#[divan::bench(args = [4096, 262144, 1048576])]
fn unified_exec_bytes(bencher: Bencher, input_bytes: usize) {
    bencher
        .with_inputs(|| UnifiedOutputWorkload::new(input_bytes, UNIFIED_EXEC_MAX_BYTES))
        .bench_local_values(|workload| workload.snapshot());
}

fn history_fixture(turns: usize) -> Vec<ResponseItem> {
    let mut items = Vec::with_capacity(turns.saturating_mul(4));
    for turn in 0..turns {
        let call_id = format!("plan062-call-{turn}");
        items.push(ResponseItem::Message {
            id: None,
            role: "user".to_string(),
            content: vec![ContentItem::InputText {
                text: format!("deterministic Plan 062 turn {turn}"),
            }],
            phase: None,
            internal_chat_message_metadata_passthrough: None,
        });
        items.push(ResponseItem::FunctionCall {
            id: None,
            name: "plan062_tool".to_string(),
            namespace: None,
            arguments: format!(r#"{{"turn":{turn}}}"#),
            call_id: call_id.clone(),
            encrypted_function_args: None,
            internal_chat_message_metadata_passthrough: None,
        });
        items.push(ResponseItem::FunctionCallOutput {
            id: None,
            call_id,
            output: FunctionCallOutputPayload::from_text(format!("completed-{turn}")),
            internal_chat_message_metadata_passthrough: None,
        });
        items.push(ResponseItem::Message {
            id: None,
            role: "assistant".to_string(),
            content: vec![ContentItem::OutputText {
                text: format!("deterministic Plan 062 result {turn}"),
            }],
            phase: None,
            internal_chat_message_metadata_passthrough: None,
        });
    }
    items
}
