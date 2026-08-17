//! End-to-end coverage for evidence anchoring.
//!
//! These tests drive the real product path: real `Session`s, real spawned sub-agents, real
//! `shell_command` executions, the real retention boundary and the real team tools. Only the model
//! provider is faked, and the fake reacts to what it is actually shown, so an assertion about what a
//! participant could read is an assertion about what a model would really have read.
//!
//! Every observation carries a marker of its own. That is what turns "the drill-down returned the
//! text" into "the drill-down returned *only* the observation asked for": a leak of the neighbouring
//! tool result or of the surrounding conversation shows up as the wrong marker rather than as a
//! passing test.

use anyhow::Result;
use codex_features::Feature;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call;
use core_test_support::responses::ev_function_call_with_namespace;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::mount_sse_once_match;
use core_test_support::responses::mount_sse_once_match_with;
use core_test_support::responses::sse;
use core_test_support::responses::start_mock_server;
use core_test_support::skip_if_target_windows;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::time::Duration;

const NAMESPACE: &str = "collaboration";
const ROOT_PROMPT: &str = "check the migration and tell the team what you find";
const WORKER_TASK: &str = "stand by for review work";

/// One marker per observation, so a leak names itself.
const TARGET_MARKER: &str = "RONDO-EVIDENCE-TARGET";
const FAILING_MARKER: &str = "RONDO-EVIDENCE-FAILING";
const NEIGHBOUR_MARKER: &str = "RONDO-EVIDENCE-NEIGHBOUR";
const WORKER_MARKER: &str = "RONDO-EVIDENCE-WORKER";
const UNSHARED_MARKER: &str = "RONDO-EVIDENCE-UNSHARED";

// --- request inspection -------------------------------------------------------------------

fn body(request: &wiremock::Request) -> Value {
    serde_json::from_slice(&request.body).expect("request body is JSON")
}

fn body_contains(request: &wiremock::Request, text: &str) -> bool {
    serde_json::from_slice::<Value>(&request.body).is_ok_and(|body| body.to_string().contains(text))
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

fn has_output_in(body: &Value, call_id: &str) -> bool {
    input_items(body).iter().any(|item| {
        item.get("type").and_then(Value::as_str) == Some("function_call_output")
            && item.get("call_id").and_then(Value::as_str) == Some(call_id)
    })
}

fn has_output(request: &wiremock::Request, call_id: &str) -> bool {
    serde_json::from_slice::<Value>(&request.body).is_ok_and(|body| has_output_in(&body, call_id))
}

/// The raw text a tool returned, read off the `function_call_output` that carries it.
fn output_text_in(body: &Value, call_id: &str) -> Option<String> {
    let output = input_items(body).iter().find(|item| {
        item.get("type").and_then(Value::as_str) == Some("function_call_output")
            && item.get("call_id").and_then(Value::as_str) == Some(call_id)
    })?;
    output
        .get("output")
        .and_then(Value::as_str)
        .map(str::to_string)
        .or_else(|| item_text(output).map(str::to_string))
}

/// The JSON a team tool returned.
fn tool_output_in(body: &Value, call_id: &str) -> Option<Value> {
    serde_json::from_str(&output_text_in(body, call_id)?).ok()
}

fn tool_output(request: &wiremock::Request, call_id: &str) -> Option<Value> {
    tool_output_in(&body(request), call_id)
}

fn evidence_refs(published: &Value) -> Vec<String> {
    published["evidence_refs"]
        .as_array()
        .expect("a publish reports the evidence it attached")
        .iter()
        .map(|reference| {
            reference
                .as_str()
                .expect("evidence references are strings")
                .to_string()
        })
        .collect()
}

fn projection(body: &Value) -> Option<String> {
    input_items(body)
        .iter()
        .filter_map(item_text)
        .find(|text| text.contains(codex_team_state::TEAM_WORLD_STATE_OPEN_TAG))
        .map(str::to_string)
}

fn ids_with_prefix(projection: &str, prefix: &str) -> Vec<String> {
    projection
        .split_whitespace()
        .filter_map(|token| {
            let token = token.trim_matches(['[', ']', ',']);
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

async fn request_log(server: &wiremock::MockServer) -> Vec<Value> {
    server
        .received_requests()
        .await
        .expect("the mock server records requests")
        .iter()
        .map(body)
        .collect()
}

fn first_where<'a>(log: &'a [Value], label: &str, predicate: impl Fn(&Value) -> bool) -> &'a Value {
    log.iter()
        .find(|body| predicate(body))
        .unwrap_or_else(|| panic!("no request {label}"))
}

/// Wait for the model to see a request satisfying `predicate`, then return it.
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

// --- fake model turns ---------------------------------------------------------------------

fn team_call(id: &str, tool: &str, args: Value) -> String {
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

/// A real shell execution whose output carries `marker`. `exit_code` makes the same tool produce a
/// success or a failure result without changing anything else about the call.
fn shell(id: &str, marker: &str, exit_code: u8) -> String {
    let args = json!({
        "command": format!("echo {marker}; exit {exit_code}"),
        "timeout_ms": 10_000,
    });
    sse(vec![
        ev_response_created(id),
        ev_function_call(
            id,
            "shell_command",
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

/// The whole single-agent chain over the real runtime: two real tool results — one that succeeded and
/// one that failed — become evidence, a publish attaches them mechanically, and the author reads each
/// one back. The reads themselves, and the team tools around them, leave no evidence of their own.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_published_version_carries_the_tool_results_behind_it_and_reads_them_back() -> Result<()>
{
    skip_if_target_windows!(Ok(()), "uses a POSIX shell command fixture");
    let server = start_mock_server().await;

    // --- three real observations, in a known retention order ------------------------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "sh-target")
        },
        shell("sh-target", TARGET_MARKER, /*exit_code*/ 0),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "sh-target"),
        shell("sh-failing", FAILING_MARKER, /*exit_code*/ 3),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "sh-failing"),
        shell("sh-neighbour", NEIGHBOUR_MARKER, /*exit_code*/ 0),
    )
    .await;

    // --- publish, which attaches all three without being asked to ------------------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "sh-neighbour"),
        team_call(
            "pub-1",
            "team_publish",
            json!({
                "title": "the migration drops a column the report reads",
                "summary": "checked the schema and the report; one of the checks failed",
            }),
        ),
    )
    .await;

    // --- read the successful observation, then the failed one ----------------------------
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "pub-1"),
        |request: &wiremock::Request| {
            let published = tool_output(request, "pub-1").expect("team_publish answered");
            team_call(
                "ev-1",
                "team_evidence",
                json!({ "fact_id": evidence_refs(&published)[0] }),
            )
        },
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "ev-1"),
        |request: &wiremock::Request| {
            let published = tool_output(request, "pub-1").expect("team_publish answered");
            team_call(
                "ev-2",
                "team_evidence",
                json!({ "fact_id": evidence_refs(&published)[1] }),
            )
        },
    )
    .await;

    // --- publish again: the team tools and the reads produced nothing to attach ----------
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "ev-2"),
        |request: &wiremock::Request| {
            let published = tool_output(request, "pub-1").expect("team_publish answered");
            team_call(
                "pub-2",
                "team_publish",
                json!({
                    "event_id": published["event_id"],
                    "summary": "read the evidence back and it still says what it said",
                    "based_on_revision": published["revision"],
                }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "pub-2"),
        say("done", "reported the finding"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;

    let log = request_log(&server).await;
    let published = tool_output_in(
        first_where(&log, "carrying the publish result", |body| {
            has_output_in(body, "pub-1")
        }),
        "pub-1",
    )
    .expect("team_publish answered");

    // Three real tool results, three references, numbered in the order Codex retained them — which
    // for this trajectory is the order the model asked for them.
    let refs = evidence_refs(&published);
    assert_eq!(
        refs.len(),
        3,
        "every supported result observed since joining is attached: {refs:?}"
    );
    assert_eq!(
        refs.iter()
            .map(|reference| fact_ordinal(reference))
            .collect::<Vec<_>>(),
        vec![1, 2, 3],
        "references are numbered in retention order: {refs:?}"
    );
    assert_eq!(
        published["evidence_refs_omitted"],
        json!(0),
        "nothing was dropped from a window this small"
    );

    // The successful observation reads back, and only it.
    let target = tool_output_in(
        first_where(&log, "carrying the first evidence read", |body| {
            has_output_in(body, "ev-1")
        }),
        "ev-1",
    )
    .expect("team_evidence answered");
    assert_eq!(target["fact_id"], json!(refs[0]));
    assert_eq!(target["category"], json!("tool_result_success"));
    assert_eq!(target["availability"], json!("available"));
    assert_eq!(target["tool"], json!("shell_command"));
    assert_eq!(target["truncated"], json!(false));
    let observation = target["observation"]
        .as_str()
        .expect("a retained observation reads back");
    assert!(
        observation.contains(TARGET_MARKER),
        "the drill-down returns the observation it was asked for:\n{observation}"
    );
    assert!(
        !observation.contains(FAILING_MARKER)
            && !observation.contains(NEIGHBOUR_MARKER)
            && !observation.contains(ROOT_PROMPT),
        "and nothing that merely sat next to it:\n{observation}"
    );

    // The failed observation is evidence too, classified as such, and just as readable.
    let failing = tool_output_in(
        first_where(&log, "carrying the second evidence read", |body| {
            has_output_in(body, "ev-2")
        }),
        "ev-2",
    )
    .expect("team_evidence answered");
    assert_eq!(failing["fact_id"], json!(refs[1]));
    assert_eq!(failing["category"], json!("tool_result_failure"));
    assert_eq!(failing["availability"], json!("available"));
    let failing_observation = failing["observation"]
        .as_str()
        .expect("a failed result is still a retained observation");
    assert!(
        failing_observation.contains(FAILING_MARKER)
            && !failing_observation.contains(TARGET_MARKER),
        "the failing observation reads back on its own:\n{failing_observation}"
    );

    // Publishing, reading history and drilling into evidence are moves within the team state, so the
    // second publish has nothing of its own to attach.
    let appended = tool_output_in(
        first_where(&log, "carrying the second publish result", |body| {
            has_output_in(body, "pub-2")
        }),
        "pub-2",
    )
    .expect("team_publish answered");
    assert_eq!(
        evidence_refs(&appended),
        Vec::<String>::new(),
        "team tools and evidence reads do not recursively produce evidence"
    );

    Ok(())
}

/// The M-2 chain extended with evidence: the root publishes something backed by its own observation
/// and routes it, the target reads exactly the evidence that event references, adds a version that
/// automatically carries its own new observation, and the root reads that one back. A sibling
/// observation the root never published stays closed to the target even when it is named directly.
#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn a_routed_event_opens_the_evidence_it_references_and_nothing_else() -> Result<()> {
    skip_if_target_windows!(Ok(()), "uses a POSIX shell command fixture");
    let server = start_mock_server().await;

    // --- root: spawn a worker and let it go idle -----------------------------------------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, ROOT_PROMPT) && !has_output(request, "spawn-1")
        },
        team_call(
            "spawn-1",
            "spawn_agent",
            json!({ "message": WORKER_TASK, "task_name": "worker" }),
        ),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "spawn-1"),
        team_call("wait-0", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, WORKER_TASK)
                && !has_output(request, "spawn-1")
                && !body_contains(request, "rte-")
        },
        say("worker-idle", "standing by"),
    )
    .await;

    // --- root: one observation it will share, one it will not, then publish and route ----
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-0"),
        shell("sh-shared", TARGET_MARKER, /*exit_code*/ 0),
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "sh-shared"),
        team_call(
            "pub-1",
            "team_publish",
            json!({
                "title": "the migration renames two columns",
                "summary": "confirmed the rename against the schema",
            }),
        ),
    )
    .await;
    // Recorded after the publish, so it is nobody's evidence yet and no version references it.
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "pub-1"),
        shell("sh-unshared", UNSHARED_MARKER, /*exit_code*/ 0),
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "sh-unshared"),
        |request: &wiremock::Request| {
            let published = tool_output(request, "pub-1").expect("team_publish answered");
            team_call(
                "route-1",
                "team_route",
                json!({
                    "event_id": published["event_id"],
                    "target": "worker",
                    "intent": "assign",
                    "note": "confirm this against the nightly report",
                    "based_on_revision": published["revision"],
                }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "route-1"),
        team_call("wait-1", "wait_agent", json!({ "timeout_ms": 30_000 })),
    )
    .await;

    // --- worker: read the chain it was handed, then the evidence that chain references ---
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| {
            body_contains(request, WORKER_TASK)
                && body_contains(request, "rte-")
                && !has_output(request, "w-history")
        },
        |request: &wiremock::Request| {
            let projection = projection(&body(request))
                .expect("an assignment puts the event in the target's active view");
            team_call(
                "w-history",
                "team_history",
                json!({ "event_id": only_id(&projection, "evt-") }),
            )
        },
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "w-history"),
        |request: &wiremock::Request| {
            let history = tool_output(request, "w-history").expect("team_history answered");
            team_call(
                "w-shared",
                "team_evidence",
                json!({ "fact_id": shared_observation_ref(&history) }),
            )
        },
    )
    .await;
    // The root's other observation, named directly. Fact references are an instance tag and a small
    // ordinal, so this is exactly the guess a member could make from what it has already seen.
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "w-shared"),
        |request: &wiremock::Request| {
            let history = tool_output(request, "w-history").expect("team_history answered");
            team_call(
                "w-guess",
                "team_evidence",
                json!({ "fact_id": guess_next_fact(&shared_observation_ref(&history)) }),
            )
        },
    )
    .await;

    // --- worker: its own observation, then a version that carries it automatically -------
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "w-guess"),
        shell("sh-worker", WORKER_MARKER, /*exit_code*/ 0),
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "sh-worker"),
        |request: &wiremock::Request| {
            let projection =
                projection(&body(request)).expect("the worker still has its assignment");
            team_call(
                "w-pub",
                "team_publish",
                json!({
                    "event_id": only_id(&projection, "evt-"),
                    "summary": "the nightly report joins on both columns, so it breaks",
                }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "w-pub"),
        say("worker-done", "added my findings"),
    )
    .await;

    // --- root: woken, reads the worker's evidence off the multi-author chain -------------
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "wait-1"),
        |request: &wiremock::Request| {
            let projection = projection(&body(request))
                .expect("the root sees the team state at the sampling after it was woken");
            team_call(
                "r-history",
                "team_history",
                json!({ "event_id": only_id(&projection, "evt-") }),
            )
        },
    )
    .await;
    mount_sse_once_match_with(
        &server,
        |request: &wiremock::Request| has_output(request, "r-history"),
        |request: &wiremock::Request| {
            let history = tool_output(request, "r-history").expect("team_history answered");
            team_call(
                "r-evidence",
                "team_evidence",
                json!({ "fact_id": history["events"][0]["versions"][1]["evidence_refs"][0] }),
            )
        },
    )
    .await;
    mount_sse_once_match(
        &server,
        |request: &wiremock::Request| has_output(request, "r-evidence"),
        say("root-done", "coordination complete"),
    )
    .await;

    let test = team_enabled_codex().build(&server).await?;
    test.submit_turn(ROOT_PROMPT).await?;
    wait_for_request(&server, "carrying the root's evidence read", |body| {
        has_output_in(body, "r-evidence")
    })
    .await;
    let log = request_log(&server).await;

    // The routed member could read the observation its event points at, across agents.
    let shared = tool_output_in(
        first_where(&log, "carrying the worker's evidence read", |body| {
            has_output_in(body, "w-shared")
        }),
        "w-shared",
    )
    .expect("team_evidence answered the routed member");
    assert_eq!(shared["producer"], json!("/root"));
    assert_eq!(shared["availability"], json!("available"));
    let shared_observation = shared["observation"]
        .as_str()
        .expect("the routed member reads what the event references");
    assert!(
        shared_observation.contains(TARGET_MARKER) && !shared_observation.contains(UNSHARED_MARKER),
        "only the referenced observation is opened:\n{shared_observation}"
    );

    // The root's other observation stayed closed, even named directly.
    let guessed = output_text_in(
        first_where(&log, "carrying the guessed evidence read", |body| {
            has_output_in(body, "w-guess")
        }),
        "w-guess",
    )
    .expect("the guess was answered");
    assert!(
        !guessed.contains(UNSHARED_MARKER),
        "a named but unreferenced observation must not be readable:\n{guessed}"
    );
    assert!(
        guessed.contains("not permitted"),
        "and the refusal has to be explicit rather than an empty result:\n{guessed}"
    );

    // The worker's own version carried its own new observation, without asking for it.
    let root_history = tool_output_in(
        first_where(&log, "carrying the root's history read", |body| {
            has_output_in(body, "r-history")
        }),
        "r-history",
    )
    .expect("team_history answered the root");
    let chain = root_history["events"][0]["versions"]
        .as_array()
        .expect("the event has a chain");
    assert_eq!(chain.len(), 2, "one event, two authors");
    assert_eq!(chain[0]["author"], json!("/root"));
    assert_eq!(chain[1]["author"], json!("/root/worker"));
    assert_eq!(
        chain[1]["evidence_refs"]
            .as_array()
            .expect("the worker's version reports its evidence")
            .len(),
        1,
        "the worker's version carries its own new observation, and nobody else's"
    );
    assert!(
        !chain[1]["evidence_refs"]
            .as_array()
            .expect("the worker's version reports its evidence")
            .contains(&json!(shared_observation_ref(&root_history))),
        "the root's observation stays the root's, even under a shared event: {:?}",
        chain[1]["evidence_refs"]
    );

    // And the root can read the worker's observation off that chain.
    let worker_evidence = tool_output_in(
        first_where(&log, "carrying the root's evidence read", |body| {
            has_output_in(body, "r-evidence")
        }),
        "r-evidence",
    )
    .expect("team_evidence answered the root");
    assert_eq!(worker_evidence["producer"], json!("/root/worker"));
    let worker_observation = worker_evidence["observation"]
        .as_str()
        .expect("the root reads its team's evidence");
    assert!(
        worker_observation.contains(WORKER_MARKER) && !worker_observation.contains(TARGET_MARKER),
        "the root reads the worker's own observation:\n{worker_observation}"
    );

    Ok(())
}

/// The shell observation the root's version references.
///
/// A publication window holds everything its author observed since it last published, so the root's
/// first version also references the results of the `spawn_agent` and `wait_agent` calls it made on
/// the way here. The shell result is the newest of them.
fn shared_observation_ref(history: &Value) -> String {
    history["events"][0]["versions"][0]["evidence_refs"]
        .as_array()
        .expect("the routed version reports its evidence")
        .last()
        .and_then(Value::as_str)
        .expect("the root's newest observation before publishing was the shell result")
        .to_string()
}

fn fact_parts(reference: &str) -> (u32, &str) {
    let (ordinal, instance) = reference
        .strip_prefix("fct-")
        .and_then(|rest| rest.split_once('-'))
        .expect("a fact reference is an ordinal and an instance tag");
    (ordinal.parse().expect("ordinals are numbers"), instance)
}

fn fact_ordinal(reference: &str) -> u32 {
    fact_parts(reference).0
}

/// The next fact reference in the same instance, which is what a member could guess from one it has
/// legitimately seen.
fn guess_next_fact(reference: &str) -> String {
    let (ordinal, instance) = fact_parts(reference);
    let next = ordinal + 1;
    format!("fct-{next}-{instance}")
}
