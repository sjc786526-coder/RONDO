//! End-to-end coverage for selective routing.
//!
//! These tests drive the real product path: real `Session`s, real spawned sub-agents, the real
//! inter-agent delivery path and the real V2 wait. Only the model provider is faked, and the fake
//! reacts to what it is actually shown, so an assertion about what the target could see is an
//! assertion about what a model would really have seen.

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
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::time::Duration;

const NAMESPACE: &str = "collaboration";
/// The opening words of a route notice, which is how the target's mail is told apart from its own
/// task and from anything the root's own history happens to mention.
const NOTICE_MARKER: &str = "Team route ";
const ROOT_PROMPT: &str = "coordinate the payments migration review";
const WORKER_TASK: &str = "stand by for review work";
const EVENT_TITLE: &str = "payments migration renames two columns";
const EVENT_SUMMARY: &str =
    "0042 renames orders.legacy_total and orders.legacy_tax without a backfill";
const ROUTE_NOTE: &str = "check the nightly report before we ship this";
const WORKER_SUMMARY: &str = "the nightly report joins on both columns, so it breaks";

// --- request inspection -------------------------------------------------------------------

fn body(request: &wiremock::Request) -> Value {
    serde_json::from_slice(&request.body).expect("request body is JSON")
}

fn body_contains(request: &wiremock::Request, text: &str) -> bool {
    serde_json::from_slice::<Value>(&request.body).is_ok_and(|body| body.to_string().contains(text))
}

fn has_output(request: &wiremock::Request, call_id: &str) -> bool {
    serde_json::from_slice::<Value>(&request.body).is_ok_and(|body| has_output_in(&body, call_id))
}

fn has_output_in(body: &Value, call_id: &str) -> bool {
    input_items(body).iter().any(|item| {
        item.get("type").and_then(Value::as_str) == Some("function_call_output")
            && item.get("call_id").and_then(Value::as_str) == Some(call_id)
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

fn projection_of(request: &wiremock::Request) -> Option<String> {
    projection(&body(request))
}

/// Every model-visible string an input item carries.
///
/// An inter-agent message keeps its body in `encrypted_content` beside the rendered header, so
/// reading only the first text part would miss the notice entirely.
fn item_strings(item: &Value) -> Vec<&str> {
    item.get("content")
        .and_then(Value::as_array)
        .map(|parts| {
            parts
                .iter()
                .filter_map(|part| {
                    part.get("text")
                        .or_else(|| part.get("encrypted_content"))
                        .and_then(Value::as_str)
                })
                .collect()
        })
        .unwrap_or_default()
}

/// The route notice this request carried, if any.
fn notice(body: &Value) -> Option<String> {
    input_items(body)
        .iter()
        .flat_map(item_strings)
        .find(|text| text.contains(NOTICE_MARKER))
        .map(str::to_string)
}

fn tool_output(request: &wiremock::Request, call_id: &str) -> Option<Value> {
    tool_output_in(&body(request), call_id)
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
    serde_json::from_str(&text).ok()
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

fn only_id(projection: &str, prefix: &str) -> String {
    let ids = ids_with_prefix(projection, prefix);
    assert_eq!(
        ids.len(),
        1,
        "expected exactly one {prefix} in:\n{projection}"
    );
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

/// Every request the model provider actually received, in order.
///
/// Assertions read from this rather than from a mock's own capture: a mock records a request while
/// it is being matched, including ones it goes on to reject, so its capture answers "was this mock
/// consulted" rather than "did the model see this".
async fn request_log(server: &wiremock::MockServer) -> Vec<Value> {
    server
        .received_requests()
        .await
        .expect("the mock server records requests")
        .iter()
        .map(body)
        .collect()
}

/// Wait for the model to see a request satisfying `predicate`, then return it.
///
/// Needed whenever the request under assertion belongs to another agent's turn: submitting the
/// root's turn only waits for the root, so reading the log once can race a target that is still
/// working.
async fn wait_for_request(
    server: &wiremock::MockServer,
    label: &str,
    predicate: impl Fn(&Value) -> bool,
) -> Value {
    let deadline = std::time::Instant::now() + Duration::from_secs(10);
    loop {
        if let Some(body) = request_log(server).await.into_iter().find(&predicate) {
            return body;
        }
        assert!(
            std::time::Instant::now() < deadline,
            "timed out waiting for a request {label}"
        );
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

/// The first request the model saw that satisfies `predicate`.
fn first_where<'a>(log: &'a [Value], label: &str, predicate: impl Fn(&Value) -> bool) -> &'a Value {
    log.iter()
        .find(|body| predicate(body))
        .unwrap_or_else(|| panic!("no request {label}"))
}

/// The turn this request belongs to, which is how a folded-in message is told apart from one that
/// started a turn of its own.
fn turn_id(body: &Value) -> &str {
    body.pointer("/client_metadata/turn_id")
        .and_then(Value::as_str)
        .unwrap_or_else(|| panic!("request carries no turn id:\n{body}"))
}

/// A request the spawned worker made, judged from the body alone.
fn is_worker(body: &Value) -> bool {
    body.to_string().contains(WORKER_TASK) && !has_output_in(body, "spawn-1")
}

/// A request from the spawned worker rather than the root: the root's requests all carry the
/// output of its own spawn call, and the worker's never do.
fn from_worker(request: &wiremock::Request) -> bool {
    body_contains(request, WORKER_TASK) && !has_output(request, "spawn-1")
}

/// The whole M-2 chain over the real multi-agent runtime:
/// the root publishes something the worker has never seen, routes that one event to it as work,
/// the worker is asked to start, reads the full chain from the canonical state, adds its own
/// version to the same event, the root is woken with the two-author chain in view, and the root
/// ends the assignment.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_routed_event_reaches_the_target_and_comes_back_as_a_multi_author_chain() -> Result<()> {
    let server = start_mock_server().await;

    // --- root: spawn a worker and let it finish, so the hand-over lands on an idle target --
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "spawn-1")
        },
        call(
            "spawn-1",
            "spawn_agent",
            json!({ "message": WORKER_TASK, "task_name": "worker" }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "spawn-1"),
        call("wait-0", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;

    // --- root: publish something the worker has never seen, then hand it over -------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-0"),
        call(
            "pub-1",
            "team_publish",
            json!({ "title": EVENT_TITLE, "summary": EVENT_SUMMARY }),
        ),
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "pub-1"),
        |request: &wiremock::Request| {
            let published = tool_output(request, "pub-1").expect("team_publish returned an event");
            call(
                "route-1",
                "team_route",
                json!({
                    "event_id": published["event_id"],
                    "target": "worker",
                    "intent": "assign",
                    "note": ROUTE_NOTE,
                    "based_on_revision": published["revision"],
                }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "route-1"),
        call("wait-1", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;

    // --- worker: runs the turn it was spawned for, then goes idle ------------------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| from_worker(request) && !body_contains(request, "rte-"),
        say("worker-idle", "standing by"),
    )
    .await;

    // --- worker: asked to start, reads the chain it was given, adds to the same event ----
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| {
            from_worker(request)
                && body_contains(request, "rte-")
                && !has_output(request, "history-1")
        },
        |request: &wiremock::Request| {
            let projection = projection_of(request)
                .expect("an assignment puts the event in the target's active view");
            call(
                "history-1",
                "team_history",
                json!({ "event_id": only_id(&projection, "evt-") }),
            )
        },
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "history-1"),
        |request: &wiremock::Request| {
            let projection = projection_of(request).expect("the worker still has the assignment");
            call(
                "worker-pub-1",
                "team_publish",
                json!({
                    "event_id": only_id(&projection, "evt-"),
                    "summary": WORKER_SUMMARY,
                }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "worker-pub-1"),
        say("worker-done", "added my findings"),
    )
    .await;

    // --- root: woken by the worker's entry, ends the assignment --------------------------
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-1"),
        |request: &wiremock::Request| {
            let projection = projection_of(request)
                .expect("the root must see the team state at the sampling after it was woken");
            call(
                "end-1",
                "team_route_update",
                json!({ "route_id": only_id(&projection, "rte-"), "action": "end" }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "end-1"),
        say("root-done", "coordination complete"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;

    let log = request_log(&server).await;

    // The worker's first turn had nothing: it could not see the root's event at all.
    let first = first_where(&log, "from the worker before the route", |body| {
        is_worker(body) && notice(body).is_none()
    });
    assert_eq!(
        projection(first),
        None,
        "before the route the worker has no active items"
    );
    assert!(
        !first.to_string().contains(EVENT_SUMMARY),
        "and no way to have seen the event"
    );

    // The route arrived as a compact notice: locators and the root's instruction, no event body.
    let routed_request = first_where(&log, "carrying the route notice", |body| {
        is_worker(body) && notice(body).is_some()
    });
    let notice = notice(routed_request).expect("the worker was told where to look");
    assert!(notice.contains(ROUTE_NOTE), "the note travels:\n{notice}");
    assert!(
        !notice.contains(EVENT_TITLE) && !notice.contains(EVENT_SUMMARY),
        "but the notice must not carry the event itself:\n{notice}"
    );

    // By the time it was notified the grant was already in force: the same request carries the
    // whole chain, so there is no window in which the notice has arrived and the event has not.
    let routed_projection =
        projection(routed_request).expect("the assignment is in the worker's active view");
    assert!(
        routed_projection.contains(EVENT_SUMMARY) && routed_projection.contains("duty=assigned"),
        "the target must be able to read what it was handed:\n{routed_projection}"
    );

    // And it read the canonical chain rather than working from the notice.
    let history = tool_output_in(
        first_where(&log, "carrying the history result", |body| {
            has_output_in(body, "history-1")
        }),
        "history-1",
    )
    .expect("team_history answered the target");
    assert_eq!(history["events"][0]["total_versions"], json!(1));
    assert_eq!(
        history["events"][0]["versions"][0]["author"],
        json!("/root")
    );

    // The worker's entry landed under the same event and gave the root a fresh opportunity.
    let woken = projection(first_where(&log, "where the root was woken", |body| {
        has_output_in(body, "wait-1") && !is_worker(body)
    }))
    .expect("a new version wakes the root");
    assert_eq!(
        ids_with_prefix(&woken, "evt-").len(),
        1,
        "one canonical event, not a copy per participant:\n{woken}"
    );
    assert_eq!(
        ids_with_prefix(&woken, "ver-").len(),
        2,
        "the root sees the complete two-author chain:\n{woken}"
    );
    assert!(
        woken.contains(WORKER_SUMMARY) && woken.contains("/root/worker"),
        "including what the routed participant contributed:\n{woken}"
    );

    // Ending the assignment is a real state change, reported from the canonical state.
    let ended = tool_output_in(
        first_where(&log, "carrying the end result", |body| {
            has_output_in(body, "end-1")
        }),
        "end-1",
    )
    .expect("the assignment ended");
    assert_eq!(ended["duty"], json!("ended"));

    // The route reported one fresh assignment whose notice was delivered.
    let routed = tool_output_in(
        first_where(&log, "carrying the route result", |body| {
            has_output_in(body, "route-1")
        }),
        "route-1",
    )
    .expect("team_route answered");
    assert_eq!(routed["duty"], json!("assigned"));
    assert_eq!(routed["delivery"], json!("delivered"));
    assert_eq!(routed["deduplicated"], json!(false));

    Ok(())
}

/// An informational route hands over access without asking for anything: the target is told, but
/// nothing pulls it into a turn.
///
/// The root waits for the worker to finish before routing, so the target is provably idle when the
/// notice is queued and "it did not run" cannot be an accident of timing.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn an_informational_route_does_not_wake_an_idle_target() -> Result<()> {
    let server = start_mock_server().await;

    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "spawn-1")
        },
        call(
            "spawn-1",
            "spawn_agent",
            json!({ "message": WORKER_TASK, "task_name": "worker" }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "spawn-1"),
        call("wait-1", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;

    // --- worker: runs once for the task it was spawned with, then goes idle --------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| from_worker(request),
        say("worker-idle", "standing by"),
    )
    .await;

    // --- root: publishes and tells the worker about it, asking for nothing ---------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-1"),
        call(
            "pub-1",
            "team_publish",
            json!({ "title": EVENT_TITLE, "summary": EVENT_SUMMARY }),
        ),
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "pub-1"),
        |request: &wiremock::Request| {
            let published = tool_output(request, "pub-1").expect("team_publish returned an event");
            call(
                "route-1",
                "team_route",
                json!({
                    "event_id": published["event_id"],
                    "target": "worker",
                    "intent": "notify",
                    "based_on_revision": published["revision"],
                }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "route-1"),
        say("root-done", "told the worker"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;
    // Give a turn that should not start every chance to start before counting.
    tokio::time::sleep(Duration::from_millis(500)).await;

    let log = request_log(&server).await;
    let routed = tool_output_in(
        first_where(&log, "carrying the route result", |body| {
            has_output_in(body, "route-1")
        }),
        "route-1",
    )
    .expect("the route committed");
    assert_eq!(routed["duty"], json!("notice"));
    assert_eq!(
        routed["delivery"],
        json!("delivered"),
        "queue-only is still a delivery"
    );

    // Counted off the server rather than a mock, so a worker turn that should not exist shows up
    // as a failed count instead of an unanswered request.
    let requests = server
        .received_requests()
        .await
        .expect("the mock server records requests");
    assert_eq!(
        requests
            .iter()
            .filter(|request| from_worker(request))
            .count(),
        1,
        "the worker ran only the turn it was spawned for"
    );
    assert_eq!(
        requests
            .iter()
            .filter(|request| notice(&body(request)).is_some())
            .count(),
        0,
        "the notice stays queued: an informational route never starts a turn to deliver itself"
    );

    Ok(())
}

/// The third delivery intent: a target that is already running is not started again.
///
/// The worker publishes (which wakes the root) and then parks inside its own turn, so its turn is
/// provably still active when the assignment lands. The notice therefore has to join that turn
/// rather than begin a second one.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_route_to_a_running_target_joins_the_turn_it_is_already_in() -> Result<()> {
    let server = start_mock_server().await;

    // --- root: spawn a worker and wait for it to say something --------------------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "spawn-1")
        },
        call(
            "spawn-1",
            "spawn_agent",
            json!({ "message": WORKER_TASK, "task_name": "worker" }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "spawn-1"),
        call("wait-1", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;

    // --- worker: publish, then park without ending its turn ------------------------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| from_worker(request) && !has_output(request, "worker-pub-0"),
        call(
            "worker-pub-0",
            "team_publish",
            json!({ "title": "worker is on shift", "summary": "starting the review" }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "worker-pub-0"),
        call("worker-wait", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;

    // --- root: woken, publishes and hands the new event to the busy worker ---------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-1") && !from_worker(request),
        call(
            "pub-1",
            "team_publish",
            json!({ "title": EVENT_TITLE, "summary": EVENT_SUMMARY }),
        ),
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "pub-1"),
        |request: &wiremock::Request| {
            let published = tool_output(request, "pub-1").expect("team_publish returned an event");
            call(
                "route-1",
                "team_route",
                json!({
                    "event_id": published["event_id"],
                    "target": "worker",
                    "intent": "assign",
                    "note": ROUTE_NOTE,
                    "based_on_revision": published["revision"],
                }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "route-1"),
        say("root-done", "handed it over"),
    )
    .await;

    // --- worker: the notice reaches it inside the turn it was already running ------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "worker-wait"),
        say("worker-done", "picked it up"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;
    let notified = wait_for_request(&server, "carrying the route notice", |body| {
        is_worker(body) && notice(body).is_some()
    })
    .await;
    let log = request_log(&server).await;
    let started = first_where(&log, "starting the worker's turn", |body| {
        is_worker(body) && !has_output_in(body, "worker-pub-0")
    });

    assert_eq!(
        turn_id(&notified),
        turn_id(started),
        "a running target is not started again; the notice joins the turn already in progress"
    );
    let projection =
        projection(&notified).expect("the assignment is in the running target's active view");
    assert!(
        projection.contains(EVENT_SUMMARY) && projection.contains("duty=assigned"),
        "and it can read what it was handed as soon as it is told:\n{projection}"
    );

    Ok(())
}
