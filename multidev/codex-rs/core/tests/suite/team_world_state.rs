//! End-to-end coverage for the canonical team world state.
//!
//! These tests drive the real product path: real `Session`s, a real spawned sub-agent, the real
//! V2 wait, and the real sampling loop. Only the model provider is faked, and the fake reacts to
//! what it is actually shown, so an assertion about the projection is an assertion about what a
//! model would really have seen.

use anyhow::Result;
use codex_features::Feature;
use codex_team_state::TEAM_WORLD_STATE_OPEN_TAG;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call_with_namespace;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once_match;
use core_test_support::responses::mount_sse_once_match_with;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::TestCodex;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::path::Path;
use std::time::Duration;

const NAMESPACE: &str = "collaboration";
const ROOT_PROMPT: &str = "coordinate the migration review";
const CHILD_TASK: &str = "inspect the migration and report what the team must know";
const FOLLOWUP: &str = "anything further on the migration event";

// --- request inspection -------------------------------------------------------------------

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

/// The projection this request carried, if any.
fn projection(body: &Value) -> Option<String> {
    input_items(body)
        .iter()
        .filter_map(item_text)
        .find(|text| text.contains(TEAM_WORLD_STATE_OPEN_TAG))
        .map(str::to_string)
}

fn projection_of(request: &wiremock::Request) -> Option<String> {
    projection(&body(request))
}

/// How many input items of this request carry a projection, and whether it is the last item.
fn projection_placement(body: &Value) -> (usize, bool) {
    let items = input_items(body);
    let count = items
        .iter()
        .filter_map(item_text)
        .filter(|text| text.contains(TEAM_WORLD_STATE_OPEN_TAG))
        .count();
    let last_is_projection = items
        .last()
        .and_then(item_text)
        .is_some_and(|text| text.contains(TEAM_WORLD_STATE_OPEN_TAG));
    (count, last_is_projection)
}

/// The JSON a tool returned, read from the `function_call_output` that carries it.
///
/// Searching the whole request body instead would match text that merely travelled along in the
/// conversation history, which makes an assertion pass whether or not the tool returned anything.
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
    serde_json::from_str(&text).ok()
}

fn tool_output(request: &wiremock::Request, call_id: &str) -> Option<Value> {
    tool_output_in(&body(request), call_id)
}

/// Coarse token size of a chunk of model-visible text.
fn approx_tokens(text: &str) -> i64 {
    i64::try_from(text.len() / 4).unwrap_or(i64::MAX)
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

fn revision_of(projection: &str) -> u64 {
    projection
        .split_whitespace()
        .find_map(|token| token.strip_prefix("revision="))
        .and_then(|value| value.parse().ok())
        .unwrap_or_else(|| panic!("no revision in:\n{projection}"))
}

fn only_event_id(projection: &str) -> String {
    let ids = ids_with_prefix(projection, "evt-");
    assert_eq!(ids.len(), 1, "expected one event in:\n{projection}");
    ids[0].clone()
}

fn only_version_id(projection: &str) -> String {
    let ids = ids_with_prefix(projection, "ver-");
    assert_eq!(ids.len(), 1, "expected one version in:\n{projection}");
    ids[0].clone()
}

// --- fake model turns ---------------------------------------------------------------------

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

fn rollout_text(test: &TestCodex) -> String {
    fn collect(dir: &Path, out: &mut String) {
        let Ok(entries) = std::fs::read_dir(dir) else {
            return;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                collect(&path, out);
            } else if path.extension().is_some_and(|ext| ext == "jsonl") {
                out.push_str(&std::fs::read_to_string(&path).unwrap_or_default());
            }
        }
    }
    let mut out = String::new();
    collect(test.codex_home_path(), &mut out);
    out
}

/// The whole M-1 chain over the real multi-agent runtime:
/// root spawns and waits, the child publishes, the root is woken and sees the team state at its
/// next sampling, the root ends its coordination, the child keeps its own unfinished item, the
/// child appends another version, and the root gets a fresh coordination opportunity with the
/// complete chain in view.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn root_and_child_share_one_canonical_team_state_across_wait_and_sampling() -> Result<()> {
    let server = start_mock_server().await;

    // --- root: spawn a worker, then wait for the team to change -------------------------
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

    // --- child: publish a first event ---------------------------------------------------
    let child_first = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, CHILD_TASK)
                && !has_output(request, "spawn-1")
                && !has_output(request, "child-publish-1")
        },
        call(
            "child-publish-1",
            "team_publish",
            json!({
                "title": "migration drops a column the report still reads",
                "summary": "the 0042 migration removes orders.legacy_total, which the nightly report selects",
                "handoff": "decide whether the report changes or the column stays",
            }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "child-publish-1"),
        say("child-idle", "published the finding"),
    )
    .await;

    // --- root: woken by the team change, ends its coordination on that version -----------
    let root_after_wake = mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-1"),
        |request: &wiremock::Request| {
            let projection = projection_of(request)
                .expect("the root must see the team state at the sampling after it was woken");
            call(
                "update-1",
                "team_update",
                json!({
                    "targets": [{
                        "version_id": only_version_id(&projection),
                        "expect_producer_state": "open",
                        "expect_root_state": "pending",
                        "set_root_state": "resolved",
                    }],
                }),
            )
        },
    )
    .await;

    // --- root: ask the worker for more, then wait again ---------------------------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "update-1"),
        call(
            "followup-1",
            "followup_task",
            json!({ "target": "/root/worker", "message": FOLLOWUP }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "followup-1"),
        call("wait-2", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;

    // --- child: still owns its item after the root resolved, and appends to it ----------
    let child_after_resolve = mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, FOLLOWUP)
                && !has_output(request, "followup-1")
                && !has_output(request, "child-publish-2")
        },
        |request: &wiremock::Request| {
            let projection = projection_of(request)
                .expect("the worker still has an unfinished item, so it still has a view");
            call(
                "child-publish-2",
                "team_publish",
                json!({
                    "event_id": only_event_id(&projection),
                    "summary": "the report also joins on that column, so dropping it breaks two queries",
                }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "child-publish-2"),
        say("child-idle-2", "appended the follow-up"),
    )
    .await;

    // --- root: woken again, now with the full chain -------------------------------------
    let root_after_second_wake = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-2"),
        say("root-done", "coordination complete"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;

    // The root saw the worker's finding, unprompted, at the sampling right after being woken.
    let woken_projection = projection(&root_after_wake.single_request().body_json())
        .expect("the root was woken and the projection was rebuilt for that sampling");
    assert!(
        woken_projection.contains("orders.legacy_total"),
        "the root must see the worker's finding without the worker restating it:\n{woken_projection}"
    );
    assert!(
        woken_projection.contains("root=pending"),
        "a member's version arrives as pending for the root:\n{woken_projection}"
    );

    // After the root resolved, the worker still has its own unfinished item.
    let child_projection = projection(&child_after_resolve.single_request().body_json())
        .expect("the worker keeps its own view");
    assert!(
        child_projection.contains("root=resolved") && child_projection.contains("producer=open"),
        "the root's resolve ends the root's attention, not the author's item:\n{child_projection}"
    );

    // The new version brought the event back to the root, with the whole chain visible.
    let final_projection = projection(&root_after_second_wake.single_request().body_json())
        .expect("a new version gives the root another coordination opportunity");
    assert_eq!(
        ids_with_prefix(&final_projection, "ver-").len(),
        2,
        "the root sees the complete version chain, not only the newest entry:\n{final_projection}"
    );
    assert!(
        final_projection.contains("breaks two queries"),
        "the newest version must be visible:\n{final_projection}"
    );

    // The worker's very first sampling had nothing active yet, so an idle team costs nothing.
    assert_eq!(
        projection(&child_first.single_request().body_json()),
        None,
        "a participant with no active items gets no projection"
    );

    Ok(())
}

/// The projection is request-only: it is appended once, at the very end of the request, and it
/// never lands in the conversation history or the rollout.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn the_projection_is_request_only_and_never_enters_history_or_rollout() -> Result<()> {
    let server = start_mock_server().await;

    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "publish-1")
        },
        call(
            "publish-1",
            "team_publish",
            json!({
                "title": "release blocker",
                "summary": "the staging deploy fails on the new index",
            }),
        ),
    )
    .await;
    let second = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "publish-1"),
        call(
            "publish-2",
            "team_publish",
            json!({
                "title": "second blocker",
                "summary": "the smoke test also times out",
            }),
        ),
    )
    .await;
    let third = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "publish-2"),
        say("done", "recorded both"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;

    // Turn two and three both carry a projection, and each carries exactly one, at the tail.
    for mock in [&second, &third] {
        let body = mock.single_request().body_json();
        let (count, last_is_projection) = projection_placement(&body);
        assert_eq!(
            (count, last_is_projection),
            (1, true),
            "the projection must appear exactly once, as the final input item:\n{body:#}"
        );
    }

    // Each sampling takes a fresh snapshot, so the revision moves with the state.
    let second_revision =
        revision_of(&projection(&second.single_request().body_json()).expect("projection"));
    let third_revision =
        revision_of(&projection(&third.single_request().body_json()).expect("projection"));
    assert!(
        third_revision > second_revision,
        "the next sampling must capture a new snapshot, not reuse the previous one          ({second_revision} -> {third_revision})"
    );

    // Nothing about it was persisted.
    let rollout = rollout_text(&test);
    assert!(
        !rollout.contains(TEAM_WORLD_STATE_OPEN_TAG),
        "the projection must not be written to the rollout"
    );

    Ok(())
}

/// A member that is genuinely unloaded and reloaded inside the same live root tree rejoins the
/// same team instance and still sees everything it authored.
///
/// The unload is forced rather than hoped for: residency is capped at one sub-agent, so the second
/// worker can only start if the first one was evicted first. If it never ran, this test fails.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_reloaded_member_keeps_its_team_instance_and_its_own_items() -> Result<()> {
    const AUDIT_TASK: &str = "audit the deploy scripts";
    const SETTLE_MS: i64 = 1_500;

    let server = start_mock_server().await;

    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "spawn-worker")
        },
        call(
            "spawn-worker",
            "spawn_agent",
            json!({ "message": CHILD_TASK, "task_name": "worker" }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "spawn-worker"),
        call("wait-1", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;

    // The worker publishes and then finishes its turn, which is what makes it evictable.
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, CHILD_TASK)
                && !has_output(request, "spawn-worker")
                && !has_output(request, "child-publish-1")
        },
        call(
            "child-publish-1",
            "team_publish",
            json!({
                "title": "index rebuild is slower than expected",
                "summary": "rebuilding the orders index takes nine minutes on staging",
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

    // A short second wait lets the worker's turn finish before residency pressure is applied.
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-1"),
        call("wait-2", "wait_agent", json!({ "timeout_ms": SETTLE_MS })),
    )
    .await;

    // Residency holds one sub-agent, so this spawn can only succeed by unloading the worker.
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-2"),
        call(
            "spawn-auditor",
            "spawn_agent",
            json!({ "message": AUDIT_TASK, "task_name": "auditor" }),
        ),
    )
    .await;
    let auditor = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, AUDIT_TASK) && !has_output(request, "spawn-auditor")
        },
        say("auditor-done", "scripts look fine"),
    )
    .await;

    // Let the auditor finish too: at this capacity, reloading the worker has to evict the auditor,
    // which is only possible once the auditor's own turn is over.
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "spawn-auditor"),
        call("wait-3", "wait_agent", json!({ "timeout_ms": SETTLE_MS })),
    )
    .await;

    // Messaging the unloaded worker reloads it.
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-3"),
        call(
            "followup-1",
            "followup_task",
            json!({ "target": "/root/worker", "message": FOLLOWUP }),
        ),
    )
    .await;
    // Only the worker matches: the root's own request also mentions the follow-up, but it is the
    // only one of the two that carries the root's wait output. Without this the two requests race
    // for the same single-use mock.
    let reloaded_worker = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, FOLLOWUP)
                && !has_output(request, "wait-1")
                && !has_output(request, "followup-1")
        },
        say("worker-back", "still on it"),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "followup-1"),
        say("root-done", "done"),
    )
    .await;

    let test = test_codex()
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
            // One resident sub-agent, so a second spawn must evict the first.
            config.multi_agent_v2.max_concurrent_threads_per_session = 2;
            config.multi_agent_v2.min_wait_timeout_ms = SETTLE_MS;
        })
        .build(&server)
        .await?;
    test.submit_turn(ROOT_PROMPT).await?;

    // The auditor could only have run if the worker was unloaded to make room for it.
    assert!(
        !auditor.requests().is_empty(),
        "the second worker must have started, which at this capacity means the first was unloaded"
    );

    // The root's turn can finish before the reloaded worker gets to its own sampling, so wait for
    // the worker's request specifically rather than the root's, which also matched here.
    let reloaded_projection = tokio::time::timeout(Duration::from_secs(10), async {
        loop {
            if let Some(projection) = reloaded_worker
                .requests()
                .iter()
                .filter_map(|request| projection(&request.body_json()))
                .find(|projection| projection.contains("you=/root/worker"))
            {
                return projection;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    })
    .await
    .expect("the reloaded worker samples with its own view of the team");
    assert!(
        reloaded_projection.contains("nine minutes on staging"),
        "a reloaded member must still see what it authored:\n{reloaded_projection}"
    );
    assert!(
        reloaded_projection.contains("producer=open"),
        "and its own lifecycle state must survive the reload:\n{reloaded_projection}"
    );

    Ok(())
}

/// All provider retries of one logical sampling reuse the same immutable snapshot.
///
/// Paired with the revision assertion in the request-only test above, this pins both halves of the
/// contract: one snapshot per logical sampling, a new one at the next sampling.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn provider_retries_of_one_sampling_reuse_the_same_snapshot() -> Result<()> {
    let server = start_mock_server().await;

    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "publish-1")
        },
        call(
            "publish-1",
            "team_publish",
            json!({ "title": "flaky provider", "summary": "the stream dropped mid-response" }),
        ),
    )
    .await;

    // The first attempt of the second sampling fails in a retryable way.
    let failed_attempt = core_test_support::responses::mount_response_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "publish-1"),
        wiremock::ResponseTemplate::new(500)
            .insert_header("content-type", "application/json")
            .set_body_string(
                json!({ "error": { "type": "server_error", "message": "synthetic" } }).to_string(),
            ),
    )
    .await;
    let retried_attempt = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "publish-1"),
        say("done", "recorded"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;

    let first = projection(&failed_attempt.single_request().body_json())
        .expect("the failed attempt carried a projection");
    let retried = projection(&retried_attempt.single_request().body_json())
        .expect("the retry carried a projection");
    assert_eq!(
        retried, first,
        "a retry of the same logical sampling must see byte-identical team state"
    );

    Ok(())
}

/// After compaction the projection is rebuilt from the canonical state, and neither the rewritten
/// history nor the summarization request ever contained it.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn compaction_rebuilds_the_projection_and_leaves_no_residue() -> Result<()> {
    use codex_model_provider_info::built_in_model_providers;
    use codex_protocol::protocol::EventMsg;
    use codex_protocol::protocol::Op;
    use codex_protocol::user_input::UserInput;
    use core_test_support::responses::ev_completed_with_tokens;
    use core_test_support::responses::mount_sse_sequence;
    use core_test_support::wait_for_event;

    const FINDING: &str = "the connection pool leaks under retry storms";
    let server = start_mock_server().await;

    // Turn one publishes a finding, then reports usage that blows past the compaction limit.
    let publish_turn = sse(vec![
        ev_response_created("r1"),
        ev_function_call_with_namespace(
            "publish-1",
            NAMESPACE,
            "team_publish",
            &serde_json::to_string(&json!({ "title": "pool leak", "summary": FINDING }))?,
        ),
        ev_completed_with_tokens("r1", /*total_tokens*/ 70_000),
    ]);
    let acknowledge_turn = sse(vec![
        ev_response_created("r2"),
        ev_assistant_message("m2", "recorded the leak"),
        ev_completed_with_tokens("r2", /*total_tokens*/ 330_000),
    ]);
    let summarization = sse(vec![
        ev_response_created("r3"),
        ev_assistant_message("m3", "summary of the session so far"),
        ev_completed_with_tokens("r3", /*total_tokens*/ 200),
    ]);
    let post_compaction = sse(vec![
        ev_response_created("r4"),
        ev_assistant_message("m4", "continuing after compaction"),
        ev_completed_with_tokens("r4", /*total_tokens*/ 120),
    ]);
    let requests = mount_sse_sequence(
        &server,
        vec![
            publish_turn,
            acknowledge_turn,
            summarization,
            post_compaction,
        ],
    )
    .await;

    let mut provider = built_in_model_providers(/*openai_base_url*/ None)["openai"].clone();
    provider.name = "OpenAI (test)".into();
    provider.base_url = Some(format!("{}/v1", server.uri()));
    provider.supports_websockets = false;

    let test = team_enabled_codex()
        .with_config(move |config| {
            config.model_provider = provider;
            config.model_auto_compact_token_limit = Some(200_000);
        })
        .build(&server)
        .await?;
    test.submit_turn(ROOT_PROMPT).await?;

    test.codex
        .submit(Op::UserInput {
            items: vec![UserInput::Text {
                text: "carry on".into(),
                text_elements: Vec::new(),
            }],
            final_output_json_schema: None,
            responsesapi_client_metadata: None,
            additional_context: Default::default(),
            thread_settings: Default::default(),
        })
        .await?;
    wait_for_event(&test.codex, |ev| matches!(ev, EventMsg::TurnComplete(_))).await;

    let captured = requests.requests();
    assert_eq!(captured.len(), 4, "expected four samplings");

    // The summarization request never sees the projection, so it cannot fold it into the summary.
    let summarization_body = captured[2].body_json();
    assert_eq!(
        projection(&summarization_body),
        None,
        "compaction must not be shown the projection"
    );

    // The sampling after compaction has it back, rebuilt from canonical state, still at the tail.
    let after_body = captured[3].body_json();
    let after = projection(&after_body).expect("the projection is rebuilt after compaction");
    assert!(
        after.contains(FINDING),
        "the finding survives compaction because the harness owns it, not the transcript:\n{after}"
    );
    assert_eq!(
        projection_placement(&after_body),
        (1, true),
        "still exactly one projection, still the final item:\n{after_body:#}"
    );

    assert!(
        !rollout_text(&test).contains(TEAM_WORLD_STATE_OPEN_TAG),
        "the projection must not be written to the rollout"
    );

    Ok(())
}

/// When the team holds more than the projection's cap allows, the projection sheds content, says
/// so, and the model can page the dropped material back through the real `team_history` tool.
///
/// Reporting an omission is only half of the contract; this covers the other half over the product
/// path. The squeeze comes from the volume of team content rather than a shrunken window, so it
/// does not depend on how large this build's instructions or tool schemas happen to be.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn omitted_projection_content_is_retrievable_with_team_history() -> Result<()> {
    use codex_team_state::MAX_PROJECTION_TOKENS;

    const EVENT_COUNT: usize = 10;
    let server = start_mock_server().await;

    // One response opening many substantial events, so the whole chain cannot fit the cap.
    let publishes: Vec<Value> = (0..EVENT_COUNT)
        .map(|index| {
            let summary = format!(
                "finding {index}: {}",
                "the migration drops a column the nightly report still reads. ".repeat(30)
            );
            json!({ "title": format!("risk {index}"), "summary": summary })
        })
        .collect();
    let mut events = vec![ev_response_created("publish-all")];
    for (index, args) in publishes.iter().enumerate() {
        events.push(ev_function_call_with_namespace(
            &format!("publish-{index}"),
            NAMESPACE,
            "team_publish",
            &serde_json::to_string(args)?,
        ));
    }
    events.push(ev_completed("publish-all"));
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "publish-0")
        },
        sse(events),
    )
    .await;

    // The projection cannot show everything; the model pages the rest back, one entry at a time so
    // the cursor has to be used.
    let squeezed = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "publish-0"),
        call("history-1", "team_history", json!({ "limit": 1 })),
    )
    .await;
    let after_first_page = mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "history-1"),
        |request: &wiremock::Request| {
            let page = tool_output(request, "history-1").expect("the first page came back");
            let next_before = page["next_before"]
                .as_u64()
                .expect("a one-wide page over ten events must offer a cursor");
            call(
                "history-2",
                "team_history",
                json!({ "limit": 1, "before": next_before }),
            )
        },
    )
    .await;
    let after_second_page = mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "history-2"),
        say("done", "recovered the dropped entries"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;

    // The projection shed content, said so, and still named events so the pointer is actionable.
    let squeezed_projection = projection(&squeezed.single_request().body_json())
        .expect("an active team never renders as nothing");
    assert!(
        squeezed_projection.contains("Omitted") && squeezed_projection.contains("team_history"),
        "a squeezed projection must name what it dropped and where to get it:\n{squeezed_projection}"
    );
    assert!(
        !ids_with_prefix(&squeezed_projection, "evt-").is_empty(),
        "and it must still name events, or the pointer is not actionable:\n{squeezed_projection}"
    );
    assert!(
        approx_tokens(&squeezed_projection) <= MAX_PROJECTION_TOKENS,
        "the projection must respect its cap, got ~{} tokens",
        approx_tokens(&squeezed_projection)
    );

    // Paging through the real tool reaches events the projection could not show.
    let first_page = tool_output_in(&after_first_page.single_request().body_json(), "history-1")
        .expect("the first page came back");
    let second_page = tool_output_in(&after_second_page.single_request().body_json(), "history-2")
        .expect("the second page came back");
    let paged_events: Vec<String> = [&first_page, &second_page]
        .iter()
        .filter_map(|page| page["events"][0]["event_id"].as_str().map(str::to_string))
        .collect();
    assert_eq!(paged_events.len(), 2, "both pages returned an event");
    assert_ne!(
        paged_events[0], paged_events[1],
        "the cursor must actually move: {paged_events:?}"
    );
    assert_eq!(
        first_page["total_events"].as_u64(),
        Some(EVENT_COUNT as u64),
        "the page reports how much there is in total"
    );

    Ok(())
}

/// When the request has no room for the active view, compaction runs *before* the provider is
/// called and the view is re-rendered against the smaller prompt.
///
/// The ordering is the whole point: a sampling that went out first and compacted afterwards would
/// have let the model decide while being shown an idle team.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn no_room_compacts_before_sampling_instead_of_sending_a_projectionless_request() -> Result<()>
{
    use codex_model_provider_info::built_in_model_providers;
    use core_test_support::responses::mount_sse_sequence_without_request_count_expectation;
    use core_test_support::responses::received_responses_request_count;

    const COMPACT_PROMPT: &str = "SUMMARIZE_THE_SESSION_NOW";
    let server = start_mock_server().await;

    // Turn one fills the team with more than a small window can carry alongside the conversation.
    let bulky = "the migration drops a column the nightly report still reads. ".repeat(30);
    let mut publish_events = vec![ev_response_created("publish-all")];
    for index in 0..6 {
        publish_events.push(ev_function_call_with_namespace(
            &format!("publish-{index}"),
            NAMESPACE,
            "team_publish",
            &serde_json::to_string(&json!({
                "title": format!("risk {index}"),
                "summary": format!("finding {index}: {bulky}"),
            }))?,
        ));
    }
    publish_events.push(ev_completed("publish-all"));

    let requests = mount_sse_sequence_without_request_count_expectation(
        &server,
        vec![
            sse(publish_events),
            // Whatever comes next is either the compaction summarization or the next sampling.
            sse(vec![
                ev_response_created("r2"),
                ev_assistant_message("m2", "a summary of the session"),
                ev_completed("r2"),
            ]),
            sse(vec![
                ev_response_created("r3"),
                ev_assistant_message("m3", "done"),
                ev_completed("r3"),
            ]),
            sse(vec![
                ev_response_created("r4"),
                ev_assistant_message("m4", "done"),
                ev_completed("r4"),
            ]),
        ],
    )
    .await;

    let mut provider = built_in_model_providers(/*openai_base_url*/ None)["openai"].clone();
    provider.name = "OpenAI (test)".into();
    provider.base_url = Some(format!("{}/v1", server.uri()));
    provider.supports_websockets = false;

    let test = team_enabled_codex()
        .with_model_info_override("gpt-5.6-sol", |model_info| {
            // Small enough that the team content cannot ride along with the conversation.
            model_info.context_window = Some(14_000);
        })
        .with_config(move |config| {
            config.model_provider = provider;
            config.compact_prompt = Some(COMPACT_PROMPT.to_string());
        })
        .build(&server)
        .await?;
    test.submit_turn(ROOT_PROMPT).await?;

    let captured = requests.requests();
    assert!(
        received_responses_request_count(&server).await? >= 2,
        "the turn must have sampled at least twice"
    );

    // The scenario has to actually reach the no-room path, or the ordering below proves nothing.
    let compaction_index = captured
        .iter()
        .position(|request| request.body_json().to_string().contains(COMPACT_PROMPT))
        .expect("the team content must have left no room, forcing a compaction");
    let projection_index = captured
        .iter()
        .position(|request| projection(&request.body_json()).is_some())
        .expect("and the view must appear once there is room for it");
    assert!(
        compaction_index < projection_index,
        "compaction has to come first: compaction at #{compaction_index}, view at #{projection_index}"
    );

    // Every ordinary sampling issued after the team had active items carries the view. A request
    // that compacts is exempt: it is the mechanism that makes room, not a turn of reasoning.
    for (index, request) in captured.iter().enumerate().skip(1) {
        let body = request.body_json();
        let is_compaction = body.to_string().contains(COMPACT_PROMPT);
        if is_compaction {
            continue;
        }
        assert!(
            projection(&body).is_some(),
            "sampling #{index} reasoned without the active team view:\n{body:#}"
        );
    }

    Ok(())
}
