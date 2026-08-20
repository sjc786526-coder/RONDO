//! End-to-end coverage for M-4 coordination closure and observability.
//!
//! The fake model only drives real Session/spawn/wait/team tools. Unload and delete go through the
//! actual thread manager and thread store, so availability is derived from AgentControl facts
//! rather than injected into TeamState.

use anyhow::Result;
use codex_features::Feature;
use codex_protocol::ThreadId;
use codex_team_state::TEAM_WORLD_STATE_OPEN_TAG;
use codex_thread_store::ReadThreadParams;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call_with_namespace;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once_match;
use core_test_support::responses::mount_sse_once_match_with;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

const NAMESPACE: &str = "collaboration";
const ROOT_PROMPT: &str = "coordinate the leftover worker item";
const CHILD_TASK: &str = "inspect the leftover and publish what the team must know";
const AFTER_UNLOAD: &str = "the worker is no longer loaded; inspect and retire if it is truly gone";
const AFTER_DELETE: &str = "the worker cannot be restored; retire the open version and inspect";

fn clear_loopback_proxy() {
    for key in [
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ] {
        unsafe {
            std::env::remove_var(key);
        }
    }
    unsafe {
        std::env::set_var("NO_PROXY", "127.0.0.1,localhost");
        std::env::set_var("no_proxy", "127.0.0.1,localhost");
    }
}

fn body(request: &wiremock::Request) -> Value {
    serde_json::from_slice(&request.body).expect("request body is JSON")
}

fn body_contains(request: &wiremock::Request, text: &str) -> bool {
    serde_json::from_slice::<Value>(&request.body).is_ok_and(|body| body.to_string().contains(text))
}

fn has_output(request: &wiremock::Request, call_id: &str) -> bool {
    serde_json::from_slice::<Value>(&request.body).is_ok_and(|body| {
        body.get("input")
            .and_then(Value::as_array)
            .is_some_and(|items| {
                items.iter().any(|item| {
                    item.get("type").and_then(Value::as_str) == Some("function_call_output")
                        && item.get("call_id").and_then(Value::as_str) == Some(call_id)
                })
            })
    })
}

fn input_items(body: &Value) -> &[Value] {
    body.get("input")
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or_default()
}

fn item_text(item: &Value) -> Option<&str> {
    item.get("content")?
        .as_array()?
        .first()?
        .get("text")?
        .as_str()
}

fn projection(body: &Value) -> Option<String> {
    input_items(body)
        .iter()
        .filter_map(item_text)
        .find(|text| text.contains(TEAM_WORLD_STATE_OPEN_TAG))
        .map(str::to_string)
}

fn tool_output_in(body: &Value, call_id: &str) -> Option<Value> {
    let output = input_items(body).iter().find(|item| {
        item.get("type").and_then(Value::as_str) == Some("function_call_output")
            && item.get("call_id").and_then(Value::as_str) == Some(call_id)
    })?;
    let text = output
        .get("output")
        .and_then(Value::as_str)
        .map(str::to_string)
        .or_else(|| item_text(output).map(str::to_string))?;
    serde_json::from_str(&text)
        .ok()
        .or(Some(json!({ "text": text })))
}

fn tool_output(body: &Value, call_id: &str) -> Option<Value> {
    tool_output_in(body, call_id)
}

fn tool_output_text(body: &Value, call_id: &str) -> String {
    tool_output(body, call_id)
        .map(|value| value.to_string())
        .unwrap_or_default()
}

fn ids_with_prefix(projection: &str, prefix: &str) -> Vec<String> {
    projection
        .split_whitespace()
        .filter_map(|token| {
            let token = token.trim_matches(['[', ']']);
            token.starts_with(prefix).then(|| token.to_string())
        })
        .collect()
}

fn only_version_id(projection: &str) -> String {
    let ids = ids_with_prefix(projection, "ver-");
    assert_eq!(ids.len(), 1, "expected one version in:\n{projection}");
    ids[0].clone()
}

fn call(id: &str, tool: &str, args: Value) -> String {
    sse(vec![
        ev_response_created(id),
        ev_function_call_with_namespace(
            id,
            NAMESPACE,
            tool,
            &serde_json::to_string(&args).expect("arguments serialize"),
        ),
        ev_completed(id),
    ])
}

fn say(id: &str, message: &str) -> String {
    sse(vec![
        ev_response_created(id),
        ev_assistant_message(id, message),
        ev_completed(id),
    ])
}

fn team_enabled_codex() -> core_test_support::test_codex::TestCodexBuilder {
    test_codex()
        .with_model("gpt-5.6-sol")
        .with_config(|config| {
            config
                .features
                .enable(Feature::Collab)
                .expect("test config allows feature updates");
            config
                .features
                .enable(Feature::MultiAgentV2)
                .expect("test config allows feature updates");
            config.multi_agent_v2.team_state_enabled = true;
            config.multi_agent_v2.max_concurrent_threads_per_session = 3;
        })
}

fn dump_worker_availability(dump: &Value) -> String {
    dump.get("entries")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .find_map(|entry| {
            if entry.get("entry").and_then(Value::as_str) == Some("participant")
                && entry.get("label").and_then(Value::as_str) == Some("/root/worker")
            {
                entry
                    .get("availability")
                    .and_then(Value::as_str)
                    .map(str::to_string)
            } else {
                None
            }
        })
        .unwrap_or_else(|| panic!("worker availability missing from dump:\n{dump}"))
}

fn dump_version_retired(dump: &Value, version_id: &str) -> bool {
    dump.get("entries")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .any(|entry| {
            entry.get("entry").and_then(Value::as_str) == Some("version")
                && entry.get("version_id").and_then(Value::as_str) == Some(version_id)
                && entry.get("retired").and_then(Value::as_bool) == Some(true)
        })
}

fn child_thread_id(root: ThreadId, ids: Vec<ThreadId>) -> ThreadId {
    ids.into_iter()
        .find(|id| *id != root)
        .expect("a spawned worker thread")
}

/// Real product path: a member publishes an open version, is unloaded but still restorable so
/// retirement is refused, then becomes unrestorable so Root retirement succeeds, and dump/log/stats
/// explain the before and after.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn root_sees_recoverable_then_unavailable_and_can_retire_only_when_gone() -> Result<()> {
    clear_loopback_proxy();
    let server = start_mock_server().await;

    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "spawn-1")
        },
        call(
            "spawn-1",
            "spawn_agent",
            json!({ "message": CHILD_TASK, "task_name": "worker" }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "spawn-1"),
        call("wait-1", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, CHILD_TASK) && !has_output(request, "child-publish-1")
        },
        call(
            "child-publish-1",
            "team_publish",
            json!({
                "title": "schema leftover",
                "summary": "the worker still holds an open finding",
            }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "child-publish-1"),
        say("child-idle", "published"),
    )
    .await;
    let root_after_wake = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-1"),
        say("root-noted", "the worker is still available"),
    )
    .await;

    let _dump_unloaded = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, AFTER_UNLOAD) && !has_output(request, "dump-unloaded")
        },
        call("dump-unloaded", "team_inspect", json!({ "action": "dump" })),
    )
    .await;
    let retire_unloaded = mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "dump-unloaded"),
        |request: &wiremock::Request| {
            let dump = tool_output(&body(request), "dump-unloaded").expect("dump answered");
            let projection = projection(&body(request)).expect("root still sees the open version");
            call(
                "retire-unloaded",
                "team_retire",
                json!({
                    "version_id": only_version_id(&projection),
                    "expect_producer_state": "open",
                    "expect_root_state": "pending",
                    "expect_availability": dump_worker_availability(&dump),
                    "expect_availability_epoch": dump.get("availability_epoch").and_then(Value::as_u64).expect("epoch"),
                    "reason": "worker is no longer loaded",
                }),
            )
        },
    )
    .await;
    let refused = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "retire-unloaded"),
        say("root-refused", "retirement was refused"),
    )
    .await;

    let _dump_gone = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, AFTER_DELETE) && !has_output(request, "dump-gone")
        },
        call("dump-gone", "team_inspect", json!({ "action": "dump" })),
    )
    .await;
    let retire_gone = mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "dump-gone"),
        |request: &wiremock::Request| {
            let dump = tool_output(&body(request), "dump-gone").expect("dump answered");
            let projection = projection(&body(request)).expect("open version still hangs");
            call(
                "retire-gone",
                "team_retire",
                json!({
                    "version_id": only_version_id(&projection),
                    "expect_producer_state": "open",
                    "expect_root_state": "pending",
                    "expect_availability": dump_worker_availability(&dump),
                    "expect_availability_epoch": dump.get("availability_epoch").and_then(Value::as_u64).expect("epoch"),
                    "reason": "worker cannot be restored in this team",
                }),
            )
        },
    )
    .await;
    let after_retire = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "retire-gone"),
        call("log-1", "team_inspect", json!({ "action": "log" })),
    )
    .await;
    let log_page = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "log-1"),
        call("stats-1", "team_inspect", json!({ "action": "stats" })),
    )
    .await;
    let stats_page = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "stats-1"),
        call("dump-retired", "team_inspect", json!({ "action": "dump" })),
    )
    .await;
    let retired_dump_page = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "dump-retired"),
        say("root-done", "retired and inspected"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;

    let woken = projection(&root_after_wake.single_request().body_json())
        .expect("root sees the published version while the worker is still loaded");
    assert!(
        woken.contains("producer_availability=available"),
        "a loaded producer must be available:\n{woken}"
    );
    let version_id = only_version_id(&woken);

    let child = child_thread_id(
        test.session_configured.thread_id,
        test.thread_manager.list_thread_ids().await,
    );
    assert!(
        test.thread_manager.remove_thread(&child).await.is_some(),
        "the worker must be unloaded through the real thread manager"
    );
    test.thread_manager
        .read_stored_thread(ReadThreadParams {
            thread_id: child,
            include_archived: true,
            include_history: false,
        })
        .await
        .expect("an unloaded worker with a stored thread is still recoverable");

    test.submit_text_turn(AFTER_UNLOAD).await?;

    let dump = tool_output(
        &retire_unloaded.single_request().body_json(),
        "dump-unloaded",
    )
    .expect("dump after unload");
    assert_eq!(dump_worker_availability(&dump), "recoverable_unloaded");
    let refused = tool_output_text(&refused.single_request().body_json(), "retire-unloaded");
    assert!(
        refused.contains("recoverable_unloaded") && refused.contains("unavailable"),
        "retirement must be refused while the worker is still restorable:\n{refused}"
    );

    test.thread_manager
        .delete_stored_thread(child)
        .await
        .expect("delete the stored worker thread");

    test.submit_text_turn(AFTER_DELETE).await?;

    let dump = tool_output(&retire_gone.single_request().body_json(), "dump-gone")
        .expect("dump after delete");
    assert_eq!(dump_worker_availability(&dump), "unavailable");
    let retired = tool_output(&after_retire.single_request().body_json(), "retire-gone")
        .expect("retirement succeeded");
    assert_eq!(
        retired.get("deduplicated").and_then(Value::as_bool),
        Some(false)
    );
    assert_eq!(
        retired.get("availability").and_then(Value::as_str),
        Some("unavailable")
    );

    let log =
        tool_output(&log_page.single_request().body_json(), "log-1").expect("change log answered");
    let log_text = log.to_string();
    assert_eq!(
        log.get("limit").and_then(Value::as_u64),
        Some(20),
        "the response must report the effective default page size"
    );
    assert!(
        log_text.contains("retire") && log_text.contains("root_does_not_self_wake"),
        "the log must record the retirement and that the root did not self-wake:\n{log_text}"
    );

    let stats =
        tool_output(&stats_page.single_request().body_json(), "stats-1").expect("stats answered");
    assert_eq!(
        stats.get("authored_chars_unit").and_then(Value::as_str),
        Some("unicode_scalar_values")
    );
    assert_eq!(stats.get("limit").and_then(Value::as_u64), Some(20));
    let worker_stats = stats
        .get("participants")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .find(|row| row.get("participant").and_then(Value::as_str) == Some("/root/worker"))
        .expect("worker stats");
    assert_eq!(
        worker_stats.get("version_count").and_then(Value::as_u64),
        Some(1)
    );

    let retired_dump = tool_output(
        &retired_dump_page.single_request().body_json(),
        "dump-retired",
    )
    .expect("dump after retirement");
    assert_eq!(retired_dump.get("limit").and_then(Value::as_u64), Some(20));
    assert!(
        dump_version_retired(&retired_dump, &version_id),
        "the dump must show the version as retired:\n{retired_dump}"
    );
    let hanging = projection(&stats_page.single_request().body_json())
        .expect("root attention still keeps the event");
    assert!(
        hanging.contains("retired=true") && hanging.contains("root=pending"),
        "retirement must not consume root attention:\n{hanging}"
    );

    Ok(())
}
