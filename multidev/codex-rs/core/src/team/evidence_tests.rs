use super::*;
use codex_protocol::ThreadId;
use codex_protocol::models::ContentItem;
use codex_protocol::models::FunctionCallOutputContentItem;
use codex_protocol::models::FunctionCallOutputPayload;
use codex_team_state::ParticipantRole;
use codex_team_state::TeamStateHandle;
use pretty_assertions::assert_eq;

const TARGET_MARKER: &str = "TARGET-OBSERVATION-MARKER";
const NEIGHBOUR_MARKER: &str = "NEIGHBOUR-OBSERVATION-MARKER";
const MESSAGE_MARKER: &str = "ASSISTANT-MESSAGE-MARKER";

fn text_output(call_id: &str, text: &str, success: Option<bool>) -> ResponseItem {
    ResponseItem::FunctionCallOutput {
        id: None,
        call_id: call_id.to_string(),
        output: FunctionCallOutputPayload {
            body: FunctionCallOutputBody::Text(text.to_string()),
            success,
        },
        internal_chat_message_metadata_passthrough: None,
    }
}

fn assistant_message(text: &str) -> ResponseItem {
    ResponseItem::Message {
        id: None,
        role: "assistant".to_string(),
        content: vec![ContentItem::OutputText {
            text: text.to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    }
}

/// A real fact, minted through the domain, pointing at one of `producer`'s own tool results.
///
/// Built the way the capture layer builds it rather than assembled by hand, so a locator that the
/// domain would not have produced cannot pass these tests.
fn fact_for(producer: codex_protocol::ThreadId, call_id: &str) -> FactView {
    let handle = TeamStateHandle::default();
    handle.register_participant(producer, ParticipantRole::Root, "/root".to_string());
    handle.note_observation(
        producer,
        FactCategory::ToolResultSuccess,
        ObservationLocator {
            call_id: call_id.to_string(),
            output_kind: RetainedOutputKind::FunctionCallOutput,
            tool: "shell_command".to_string(),
        },
    );
    let fact_id = handle
        .confirm_observation(producer, call_id)
        .expect("a noted observation mints a fact once retention is confirmed");
    handle
        .read_fact(producer, fact_id)
        .expect("a producer reads its own evidence")
}

#[test]
fn the_support_set_is_completed_text_tool_results_and_nothing_else() {
    let supported = |item: &ResponseItem| {
        supported_observation(item)
            .map(|observation| (observation.call_id.to_string(), observation.category))
    };

    assert_eq!(
        supported(&text_output("call-ok", "output", Some(true))),
        Some(("call-ok".to_string(), FactCategory::ToolResultSuccess))
    );
    assert_eq!(
        supported(&text_output("call-fail", "output", Some(false))),
        Some(("call-fail".to_string(), FactCategory::ToolResultFailure))
    );
    assert_eq!(
        supported(&text_output("call-unclassified", "output", None)),
        Some((
            "call-unclassified".to_string(),
            FactCategory::ToolResultSuccess
        )),
        "a tool that did not classify itself is read the same way every other surface reads it"
    );
    assert_eq!(
        supported(&ResponseItem::CustomToolCallOutput {
            id: None,
            call_id: "call-custom".to_string(),
            name: None,
            output: FunctionCallOutputPayload {
                body: FunctionCallOutputBody::Text("output".to_string()),
                success: Some(true),
            },
            internal_chat_message_metadata_passthrough: None,
        }),
        Some(("call-custom".to_string(), FactCategory::ToolResultSuccess))
    );

    // Everything outside the first version's support set.
    assert_eq!(
        supported(&ResponseItem::FunctionCallOutput {
            id: None,
            call_id: "call-media".to_string(),
            output: FunctionCallOutputPayload {
                body: FunctionCallOutputBody::ContentItems(vec![
                    FunctionCallOutputContentItem::InputText {
                        text: "described".to_string(),
                    },
                ]),
                success: Some(true),
            },
            internal_chat_message_metadata_passthrough: None,
        }),
        None,
        "the content-item shape is what carries media, so it is excluded whole"
    );
    assert_eq!(supported(&assistant_message("what I think")), None);
    assert_eq!(
        supported(&ResponseItem::ToolSearchOutput {
            id: None,
            call_id: Some("call-search".to_string()),
            status: "completed".to_string(),
            execution: "client".to_string(),
            tools: Vec::new(),
            internal_chat_message_metadata_passthrough: None,
        }),
        None
    );
    assert_eq!(
        supported(&text_output("", "output", Some(true))),
        None,
        "a result the harness could not tie to a call is not locatable"
    );
}

#[tokio::test]
async fn resolution_returns_the_target_observation_and_nothing_around_it() {
    let (session, turn_context) = crate::session::tests::make_session_and_context().await;
    session
        .record_conversation_items(
            &turn_context,
            &[
                text_output("call-target", TARGET_MARKER, Some(true)),
                assistant_message(MESSAGE_MARKER),
                text_output("call-neighbour", NEIGHBOUR_MARKER, Some(true)),
            ],
        )
        .await;

    let fact = fact_for(session.thread_id, "call-target");
    let ObservationRead::Retained { text, total_chars } = read_observation(&session, &fact).await
    else {
        panic!("the target observation is still retained");
    };

    assert_eq!(text, TARGET_MARKER);
    assert_eq!(total_chars, TARGET_MARKER.chars().count());
}

#[tokio::test]
async fn an_observation_dropped_from_history_reports_that_it_cannot_be_read_back() {
    let (session, turn_context) = crate::session::tests::make_session_and_context().await;
    session
        .record_conversation_items(
            &turn_context,
            &[text_output("call-1", TARGET_MARKER, Some(true))],
        )
        .await;
    let fact = fact_for(session.thread_id, "call-1");
    assert!(matches!(
        read_observation(&session, &fact).await,
        ObservationRead::Retained { .. }
    ));

    // The replacement compaction performs: the window is rebuilt without the tool results.
    session.replace_history(Vec::new(), None).await;

    let read = read_observation(&session, &fact).await;
    assert!(
        matches!(read, ObservationRead::NotInProducerHistory),
        "a reference the producer can no longer read back reports the absence rather than the \
         nearest item"
    );
    assert_eq!(read.availability(), "unavailable");
    assert_eq!(read.observation(), None);
    assert_eq!(read.total_chars(), None);
    assert!(!read.truncated());
    assert!(
        read.unavailable_reason()
            .is_some_and(|reason| reason.contains("cannot read it back now")),
        "and says what the harness actually established, not that it is gone for good"
    );
}

/// Design clause 11's distinction, at the read that has to make it: a member that is not loaded
/// right now is a different answer from one whose observation cannot be read back, and neither
/// writes the reference off.
#[tokio::test]
async fn a_fact_from_an_unloaded_producer_reports_that_rather_than_a_missing_observation() {
    let (session, _turn_context) = crate::session::tests::make_session_and_context().await;
    let fact = fact_for(ThreadId::new(), "call-1");

    let read = read_observation(&session, &fact).await;

    assert!(matches!(read, ObservationRead::ProducerNotLoaded));
    assert_eq!(read.availability(), "unavailable");
    assert_eq!(read.observation(), None);
    assert!(
        read.unavailable_reason()
            .is_some_and(|reason| reason.contains("not loaded")),
        "the reason has to name the producer's residency, not the observation"
    );
}

#[tokio::test]
async fn an_oversized_observation_is_clamped_and_reports_how_long_it_really_was() {
    let (session, turn_context) = crate::session::tests::make_session_and_context().await;
    let long = "x".repeat(MAX_OBSERVATION_CHARS * 2);
    session
        .record_conversation_items(&turn_context, &[text_output("call-1", &long, Some(true))])
        .await;

    let fact = fact_for(session.thread_id, "call-1");
    let ObservationRead::Retained { text, total_chars } = read_observation(&session, &fact).await
    else {
        panic!("the observation is retained");
    };

    assert_eq!(text.chars().count(), MAX_OBSERVATION_CHARS);
    assert_eq!(total_chars, long.chars().count());

    let read = read_observation(&session, &fact).await;
    assert!(read.truncated(), "a clamped read has to say it was clamped");
    assert_eq!(read.total_chars(), Some(long.chars().count()));
    assert_eq!(read.availability(), "available");
}
