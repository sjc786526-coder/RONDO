//! Route tool coverage over the real session, agent control and delivery path.
//!
//! Only the model is absent: the sessions, the agent registry, residency and the submission queue
//! are the product's own. That is what makes the delivery assertions here meaningful — a route
//! either put a real `Op::InterAgentCommunication` on a real thread or it did not.

use super::*;
use crate::StartThreadOptions;
use crate::ThreadManager;
use crate::session::step_context::StepContext;
use crate::session::tests::make_session_and_context;
use crate::session::turn_context::TurnContext;
use crate::tools::handlers::multi_agents_v2::SpawnAgentHandler as SpawnAgentHandlerV2;
use crate::tools::handlers::team_tools::TeamPublishHandler;
use crate::tools::handlers::team_tools::TeamRouteUpdateHandler;
use crate::turn_diff_tracker::TurnDiffTracker;
use codex_features::Feature;
use codex_login::CodexAuth;
use codex_model_provider_info::built_in_model_providers;
use codex_protocol::ThreadId;
use codex_protocol::models::FunctionCallOutputBody;
use codex_protocol::protocol::InterAgentCommunication;
use codex_protocol::protocol::Op;
use codex_team_state::ParticipantRole;
use codex_team_state::RouteDuty;
use codex_team_state::TeamStateHandle;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use std::sync::Arc;
use tokio::sync::Mutex;
use tokio_util::sync::CancellationToken;

const EVENT_TITLE: &str = "schema drift in the payments migration";
const EVENT_SUMMARY: &str = "two columns were renamed without a backfill";

fn thread_manager() -> ThreadManager {
    ThreadManager::with_models_provider_for_tests(
        CodexAuth::from_api_key("dummy"),
        built_in_model_providers(/*openai_base_url*/ None)["openai"].clone(),
    )
}

fn invocation(
    session: Arc<crate::session::session::Session>,
    turn: Arc<TurnContext>,
    tool_name: &str,
    args: Value,
) -> ToolInvocation {
    ToolInvocation {
        session,
        step_context: StepContext::for_test(Arc::clone(&turn)),
        turn,
        cancellation_token: CancellationToken::new(),
        tracker: Arc::new(Mutex::new(TurnDiffTracker::default())),
        call_id: format!("call-{tool_name}"),
        tool_name: codex_tools::ToolName::plain(tool_name),
        source: crate::tools::context::ToolCallSource::Direct,
        payload: ToolPayload::Function {
            arguments: args.to_string(),
        },
    }
}

fn output_json<T: ToolOutput + ?Sized>(output: Box<T>) -> Value {
    let response = output.to_response_item(
        "call-1",
        &ToolPayload::Function {
            arguments: "{}".to_string(),
        },
    );
    let ResponseInputItem::FunctionCallOutput { output, .. } = response else {
        panic!("expected a function output");
    };
    let FunctionCallOutputBody::Text(text) = output.body else {
        panic!("expected text output");
    };
    serde_json::from_str(&text).expect("tool output is JSON")
}

fn notice_body(communication: &InterAgentCommunication) -> &str {
    communication
        .encrypted_content
        .as_deref()
        .unwrap_or(&communication.content)
}

struct TeamHarness {
    manager: ThreadManager,
    session: Arc<crate::session::session::Session>,
    turn: Arc<TurnContext>,
    team: Arc<TeamStateHandle>,
    root: ThreadId,
}

impl TeamHarness {
    /// A root session sharing one team instance with the thread manager it spawns members from.
    async fn new() -> Self {
        let (mut session, mut turn) = make_session_and_context().await;
        let manager = thread_manager();
        let mut config = turn.config.as_ref().clone();
        config
            .features
            .enable(Feature::Collab)
            .expect("test config allows feature updates");
        config
            .features
            .enable(Feature::MultiAgentV2)
            .expect("test config allows feature updates");
        config.multi_agent_v2.team_state_enabled = true;
        turn.multi_agent_version = config.multi_agent_version_from_features();
        turn.config = Arc::new(config);
        let root_thread = manager
            .start_thread(StartThreadOptions::new((*turn.config).clone()))
            .await
            .expect("root thread should start");
        root_thread.thread.session.new_default_turn().await;
        session.services.agent_control = manager.agent_control();
        session.thread_id = root_thread.thread_id;
        // The same registration the product does from the authoritative session source; the swap
        // above replaced the control handle the real constructor had already registered against.
        session
            .services
            .agent_control
            .register_team_participant(session.thread_id, &turn.session_source);

        let team = Arc::clone(session.services.agent_control.team());
        let root = session.thread_id;
        Self {
            manager,
            session: Arc::new(session),
            turn: Arc::new(turn),
            team,
            root,
        }
    }

    async fn spawn_worker(&self, task_name: &str) -> ThreadId {
        SpawnAgentHandlerV2::default()
            .handle(invocation(
                Arc::clone(&self.session),
                Arc::clone(&self.turn),
                "spawn_agent",
                json!({ "message": "boot worker", "task_name": task_name }),
            ))
            .await
            .expect("spawn worker");
        self.session
            .services
            .agent_control
            .resolve_agent_reference(self.root, &self.turn.session_source, task_name)
            .await
            .expect("worker should resolve")
    }

    /// A participant of the team whose agent thread the registry knows nothing about, which is how
    /// delivery is made to fail without weakening anything about the grant itself.
    fn register_unreachable_member(&self, label: &str) -> ThreadId {
        let thread_id = ThreadId::new();
        self.team
            .register_participant(thread_id, ParticipantRole::Member, label.to_string());
        thread_id
    }

    async fn publish_root_event(&self) -> String {
        let output = TeamPublishHandler
            .handle(invocation(
                Arc::clone(&self.session),
                Arc::clone(&self.turn),
                "team_publish",
                json!({ "title": EVENT_TITLE, "summary": EVENT_SUMMARY }),
            ))
            .await
            .expect("root may publish");
        output_json(output)["event_id"]
            .as_str()
            .expect("event id")
            .to_string()
    }

    async fn route_as(
        &self,
        actor: Arc<crate::session::session::Session>,
        args: Value,
    ) -> Result<Value, FunctionCallError> {
        match Handler
            .handle(invocation(
                actor,
                Arc::clone(&self.turn),
                "team_route",
                args,
            ))
            .await
        {
            Ok(output) => Ok(output_json(output)),
            Err(err) => Err(err),
        }
    }

    async fn route(&self, args: Value) -> Result<Value, FunctionCallError> {
        self.route_as(Arc::clone(&self.session), args).await
    }

    async fn route_update(&self, args: Value) -> Result<Value, FunctionCallError> {
        match TeamRouteUpdateHandler
            .handle(invocation(
                Arc::clone(&self.session),
                Arc::clone(&self.turn),
                "team_route_update",
                args,
            ))
            .await
        {
            Ok(output) => Ok(output_json(output)),
            Err(err) => Err(err),
        }
    }

    /// The real spawned member's own session, which is where its identity comes from.
    async fn member_session(&self, target: ThreadId) -> Arc<crate::session::session::Session> {
        Arc::clone(
            &self
                .manager
                .get_thread(target)
                .await
                .expect("member thread is loaded")
                .session,
        )
    }

    /// Route notices actually submitted to `target`, picked out of everything else that reaches a
    /// member's queue — a spawned agent's own task arrives the same way.
    fn notices_to(&self, target: ThreadId) -> Vec<InterAgentCommunication> {
        self.manager
            .captured_ops()
            .into_iter()
            .filter_map(|(id, op)| match op {
                Op::InterAgentCommunication { communication } if id == target => {
                    Some(communication)
                }
                _ => None,
            })
            .filter(|communication| notice_body(communication).starts_with("Team route "))
            .collect()
    }

    fn routes_of_first_event(&self) -> Vec<codex_team_state::RouteView> {
        self.team
            .snapshot_for(self.root)
            .expect("root view")
            .events
            .iter()
            .flat_map(|event| event.routes.clone())
            .collect()
    }
}

#[tokio::test]
async fn an_assignment_reaches_the_target_and_asks_it_to_start_or_continue() {
    let harness = TeamHarness::new().await;
    let event_id = harness.publish_root_event().await;
    let worker = harness.spawn_worker("worker").await;

    let routed = harness
        .route(json!({
            "event_id": event_id,
            "target": "worker",
            "intent": "assign",
            "note": "confirm the rename is backfilled",
        }))
        .await
        .expect("the root may route");

    assert_eq!(routed["duty"], json!("assigned"));
    assert_eq!(routed["delivery"], json!("delivered"));
    assert_eq!(routed["delivery_error"], Value::Null);
    assert_eq!(routed["deduplicated"], json!(false));

    let notices = harness.notices_to(worker);
    assert_eq!(notices.len(), 1, "exactly one notice for one route");
    assert!(
        notices[0].trigger_turn,
        "work asks the target to start or continue"
    );

    // And the assignment can be ended through the tool surface.
    let ended = harness
        .route_update(json!({ "route_id": routed["route_id"], "action": "end" }))
        .await
        .expect("the root may end what it assigned");
    assert_eq!(ended["duty"], json!("ended"));
    assert_eq!(
        harness.routes_of_first_event()[0].duty,
        RouteDuty::Ended,
        "the canonical route agrees with what the tool reported"
    );
}

#[tokio::test]
async fn an_informational_route_is_queued_without_asking_for_a_turn() {
    let harness = TeamHarness::new().await;
    let event_id = harness.publish_root_event().await;
    let worker = harness.spawn_worker("worker").await;

    let routed = harness
        .route(json!({
            "event_id": event_id,
            "target": "worker",
            "intent": "notify",
        }))
        .await
        .expect("the root may tell a member about an event");

    assert_eq!(routed["duty"], json!("notice"));
    assert_eq!(routed["delivery"], json!("delivered"));

    let notices = harness.notices_to(worker);
    assert_eq!(notices.len(), 1);
    assert!(
        !notices[0].trigger_turn,
        "being told something must not be dressed up as work"
    );
    assert!(
        harness
            .team
            .snapshot_for(worker)
            .expect("worker view")
            .is_empty(),
        "a notice does not put the event in the target's active view"
    );
}

#[tokio::test]
async fn the_notice_locates_the_event_without_carrying_any_of_its_content() {
    let harness = TeamHarness::new().await;
    let event_id = harness.publish_root_event().await;
    let worker = harness.spawn_worker("worker").await;
    let note = "check the payments backfill first";

    let routed = harness
        .route(json!({
            "event_id": event_id,
            "target": "worker",
            "intent": "assign",
            "note": note,
        }))
        .await
        .expect("routed");

    let notices = harness.notices_to(worker);
    let body = notice_body(&notices[0]);
    let route_id = routed["route_id"].as_str().expect("route id");
    assert!(body.contains(&event_id), "the notice says where to look");
    assert!(body.contains(route_id), "and which hand-over it is");
    assert!(body.contains("team_history"), "and how to read the event");
    assert!(body.contains(note), "the root's own instruction travels");
    assert!(
        !body.contains(EVENT_TITLE) && !body.contains(EVENT_SUMMARY),
        "but no part of the event itself is copied into it:\n{body}"
    );
}

#[tokio::test]
async fn a_member_cannot_route_and_nothing_is_committed_or_sent() {
    let harness = TeamHarness::new().await;
    let event_id = harness.publish_root_event().await;
    let worker = harness.spawn_worker("worker").await;
    let other = harness.spawn_worker("other").await;
    // Act as the member itself. Nothing in the payload says who is calling; the store reads it from
    // the session, so a member naming a perfectly valid target still gets nowhere.
    let member = harness.member_session(worker).await;

    let Err(refused) = harness
        .route_as(
            member,
            json!({ "event_id": event_id, "target": "other", "intent": "assign" }),
        )
        .await
    else {
        panic!("a member cannot hand work around");
    };
    let FunctionCallError::RespondToModel(message) = refused else {
        panic!("team refusals are reported to the model");
    };
    assert!(message.contains("only the root routes events"), "{message}");
    assert!(harness.routes_of_first_event().is_empty());
    assert!(harness.notices_to(other).is_empty());
}

#[tokio::test]
async fn a_target_that_cannot_be_named_is_refused_before_anything_is_committed() {
    let harness = TeamHarness::new().await;
    let event_id = harness.publish_root_event().await;
    harness.spawn_worker("worker").await;

    let Err(refused) = harness
        .route(json!({
            "event_id": event_id,
            "target": "ghost",
            "intent": "assign",
        }))
        .await
    else {
        panic!("an agent that does not exist cannot be routed to");
    };
    let FunctionCallError::RespondToModel(message) = refused else {
        panic!("expected a model-facing refusal");
    };
    assert!(message.contains("ghost"), "{message}");
    assert!(
        harness.routes_of_first_event().is_empty(),
        "a refused route grants nothing"
    );
}

#[tokio::test]
async fn a_notice_that_cannot_be_delivered_leaves_the_grant_standing_and_stays_retryable() {
    let harness = TeamHarness::new().await;
    let event_id = harness.publish_root_event().await;
    let unreachable = harness.register_unreachable_member("/root/unreachable");

    let routed = harness
        .route(json!({
            "event_id": event_id,
            "target": unreachable.to_string(),
            "intent": "assign",
        }))
        .await
        .expect("the route itself is not a delivery");

    assert_eq!(routed["duty"], json!("assigned"));
    assert_eq!(routed["delivery"], json!("failed"));
    assert!(
        routed["delivery_error"].is_string(),
        "the failure is named, not hidden"
    );
    assert!(harness.notices_to(unreachable).is_empty());

    // The grant is real: the target can read the event it was never told about.
    assert!(
        harness
            .team
            .history(
                unreachable,
                &codex_team_state::HistoryQuery {
                    event_id: Some(event_id.parse().expect("event id")),
                    limit: None,
                    before: None,
                },
            )
            .is_ok()
    );
    let routes = harness.routes_of_first_event();
    assert_eq!(routes.len(), 1);
    assert_eq!(routes[0].duty, RouteDuty::Assigned);

    // Retrying re-attempts the same notice without minting a second hand-over.
    let retried = harness
        .route_update(json!({ "route_id": routed["route_id"], "action": "retry_notice" }))
        .await
        .expect("a retry is a normal operation");
    assert_eq!(retried["delivery"], json!("failed"));
    assert_eq!(retried["route_id"], routed["route_id"]);
    assert_eq!(harness.routes_of_first_event().len(), 1);
}

#[tokio::test]
async fn asking_twice_for_the_same_hand_over_does_not_notify_twice() {
    let harness = TeamHarness::new().await;
    let event_id = harness.publish_root_event().await;
    let worker = harness.spawn_worker("worker").await;
    let args = json!({
        "event_id": event_id,
        "target": "worker",
        "intent": "assign",
    });

    let first = harness.route(args.clone()).await.expect("routed");
    let second = harness.route(args).await.expect("routed again");

    assert_eq!(second["route_id"], first["route_id"]);
    assert_eq!(second["deduplicated"], json!(true));
    assert_eq!(harness.routes_of_first_event().len(), 1);
    assert_eq!(
        harness.notices_to(worker).len(),
        1,
        "a repeat must not send a second notice"
    );
}
