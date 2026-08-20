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

/// A retained tool output whose item identity is fixed, so a test can name the same item a locator
/// would. Recording assigns one when it is missing; naming it here only removes the guesswork.
fn text_output(call_id: &str, text: &str, success: Option<bool>) -> ResponseItem {
    ResponseItem::FunctionCallOutput {
        id: Some(ResponseItemId::from_server(item_id(call_id))),
        call_id: call_id.to_string(),
        output: FunctionCallOutputPayload {
            body: FunctionCallOutputBody::Text(text.to_string()),
            success,
        },
        internal_chat_message_metadata_passthrough: None,
    }
}

fn item_id(call_id: &str) -> String {
    format!("fco_{call_id}")
}

#[test]
fn code_mode_evidence_survives_the_gap_between_yield_and_the_next_wait() {
    let recorder = CodeModeEvidenceRecorder::default();

    recorder.register_output("cell-1", "item-yield");
    recorder.seal_output("item-yield", CodeModeOutputBoundary::Yielded);
    assert!(!recorder.take_output_eligibility("item-yield"));

    // The nested call can finish while no model-visible wait item is registered. Its credit belongs
    // to the next response from this still-live cell rather than being dropped.
    recorder.mark_eligible("cell-1");
    recorder.register_output("cell-1", "item-result");
    recorder.seal_output("item-result", CodeModeOutputBoundary::Terminal);

    assert!(recorder.take_output_eligibility("item-result"));
}

#[test]
fn code_mode_evidence_completed_after_a_response_boundary_waits_for_the_next_output() {
    let recorder = CodeModeEvidenceRecorder::default();

    recorder.register_output("cell-1", "item-yield");
    recorder.seal_output("item-yield", CodeModeOutputBoundary::Yielded);
    recorder.mark_eligible("cell-1");

    assert!(
        !recorder.take_output_eligibility("item-yield"),
        "a nested result completed after sealing must not race into the older response"
    );
    recorder.register_output("cell-1", "item-result");
    recorder.seal_output("item-result", CodeModeOutputBoundary::Terminal);
    assert!(recorder.take_output_eligibility("item-result"));
}

#[test]
fn yielded_code_mode_output_discards_even_pre_boundary_credit() {
    let recorder = CodeModeEvidenceRecorder::default();

    recorder.register_output("cell-1", "item-yield");
    recorder.mark_eligible("cell-1");
    recorder.seal_output("item-yield", CodeModeOutputBoundary::Yielded);

    assert!(
        !recorder.take_output_eligibility("item-yield"),
        "the handler cannot prove a pending nested result was present in the remote yield snapshot"
    );
    recorder.register_output("cell-1", "item-result");
    recorder.seal_output("item-result", CodeModeOutputBoundary::Terminal);
    assert!(
        !recorder.take_output_eligibility("item-result"),
        "discarded yield credit must not be reassigned to unrelated terminal content"
    );
}

#[test]
fn code_mode_outputs_with_a_reused_model_call_id_keep_distinct_item_identity() {
    let recorder = CodeModeEvidenceRecorder::default();

    // Both outer calls may carry the same model-authored call id. The recorder never sees or keys
    // on it: harness-minted output item identity keeps the two runtime cells independent.
    recorder.register_output("cell-a", "item-a");
    recorder.register_output("cell-b", "item-b");
    recorder.mark_eligible("cell-a");
    recorder.seal_output("item-b", CodeModeOutputBoundary::Terminal);
    recorder.seal_output("item-a", CodeModeOutputBoundary::Terminal);

    assert!(!recorder.take_output_eligibility("item-b"));
    assert!(recorder.take_output_eligibility("item-a"));
}

#[test]
fn discarding_one_pending_code_mode_output_does_not_clear_another() {
    let recorder = CodeModeEvidenceRecorder::default();

    recorder.register_output("cell-1", "item-aborted");
    recorder.register_output("cell-1", "item-kept");
    recorder.mark_eligible("cell-1");
    recorder.seal_output("item-kept", CodeModeOutputBoundary::Terminal);
    recorder.discard_output("item-aborted");

    assert!(recorder.take_output_eligibility("item-kept"));
}

#[test]
fn discarding_the_last_cancelled_output_cleans_a_nonterminal_cell() {
    let recorder = CodeModeEvidenceRecorder::default();

    recorder.register_output("cell-cancelled", "item-cancelled");
    recorder.mark_eligible("cell-cancelled");
    recorder.discard_output("item-cancelled");

    let state = recorder
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert!(state.cells.is_empty());
    assert!(state.item_cells.is_empty());
    assert!(state.sealed_items.is_empty());
    assert!(state.terminal_cells.is_empty());
}

#[test]
fn terminal_code_mode_output_cleans_up_the_cell_after_its_last_item() {
    let recorder = CodeModeEvidenceRecorder::default();

    recorder.register_output("cell-1", "item-result");
    recorder.mark_eligible("cell-1");
    recorder.seal_output("item-result", CodeModeOutputBoundary::Terminal);
    assert!(recorder.take_output_eligibility("item-result"));

    let state = recorder
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert!(state.cells.is_empty());
    assert!(state.item_cells.is_empty());
    assert!(state.sealed_items.is_empty());
    assert!(state.terminal_cells.is_empty());
}

#[test]
fn unavailable_code_mode_output_never_uses_pending_credit_and_cleans_up() {
    let recorder = CodeModeEvidenceRecorder::default();

    recorder.register_output("missing-cell", "item-missing");
    recorder.mark_eligible("missing-cell");
    recorder.seal_output("item-missing", CodeModeOutputBoundary::Unavailable);

    assert!(
        !recorder.take_output_eligibility("item-missing"),
        "a generic missing-cell response has no proven provenance boundary"
    );
    let state = recorder
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert!(state.cells.is_empty());
    assert!(state.item_cells.is_empty());
    assert!(state.sealed_items.is_empty());
    assert!(state.terminal_cells.is_empty());
}

#[test]
fn retryable_wait_error_keeps_only_a_previously_known_live_cell() {
    let recorder = CodeModeEvidenceRecorder::default();

    assert!(!recorder.register_output("cell-live", "item-yield"));
    recorder.seal_output("item-yield", CodeModeOutputBoundary::Yielded);
    assert!(!recorder.take_output_eligibility("item-yield"));
    assert!(recorder.register_output("cell-live", "item-retry-error"));
    // The dispatch failure is retained by the host and consumes this unsealed item. The known cell
    // remains so a later successful wait can still receive new nested provenance.
    assert!(!recorder.take_output_eligibility("item-retry-error"));

    assert!(!recorder.register_output("cell-unknown", "item-unknown-error"));
    recorder.seal_output("item-unknown-error", CodeModeOutputBoundary::Unavailable);
    assert!(!recorder.take_output_eligibility("item-unknown-error"));

    let state = recorder
        .state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert!(state.cells.contains_key("cell-live"));
    assert!(!state.cells.contains_key("cell-unknown"));
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
        NotedObservation {
            item_id: item_id(call_id),
            call_id: call_id.to_string(),
            category: FactCategory::ToolResultSuccess,
            tool: "shell_command".to_string(),
        },
    );
    let fact_id = handle
        .confirm_observation(producer, &item_id(call_id))
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

    let code_mode_text = ResponseItem::CustomToolCallOutput {
        id: None,
        call_id: "call-code-mode".to_string(),
        name: Some("exec".to_string()),
        output: FunctionCallOutputPayload {
            body: FunctionCallOutputBody::ContentItems(vec![
                FunctionCallOutputContentItem::InputText {
                    text: "Script completed".to_string(),
                },
                FunctionCallOutputContentItem::InputText {
                    text: "finding".to_string(),
                },
            ]),
            success: Some(true),
        },
        internal_chat_message_metadata_passthrough: None,
    };
    let observation =
        supported_observation(&code_mode_text).expect("an all-text code-mode result is evidence");
    assert_eq!(observation.call_id, "call-code-mode");
    assert_eq!(observation.category, FactCategory::ToolResultSuccess);
    assert_eq!(observation.text, "Script completed\nfinding");

    assert_eq!(
        supported(&ResponseItem::CustomToolCallOutput {
            id: None,
            call_id: "call-encrypted".to_string(),
            name: Some("exec".to_string()),
            output: FunctionCallOutputPayload {
                body: FunctionCallOutputBody::ContentItems(vec![
                    FunctionCallOutputContentItem::InputText {
                        text: "Script completed".to_string(),
                    },
                    FunctionCallOutputContentItem::EncryptedContent {
                        encrypted_content: "opaque".to_string(),
                    },
                ]),
                success: Some(true),
            },
            internal_chat_message_metadata_passthrough: None,
        }),
        None,
        "an encrypted content part keeps the complete cell outside the evidence support set"
    );

    // Mixed content is outside the support set: discarding its non-text part would make the evidence
    // read differ from what the model actually saw.
    assert_eq!(
        supported(&ResponseItem::FunctionCallOutput {
            id: None,
            call_id: "call-media".to_string(),
            output: FunctionCallOutputPayload {
                body: FunctionCallOutputBody::ContentItems(vec![
                    FunctionCallOutputContentItem::InputText {
                        text: "described".to_string(),
                    },
                    FunctionCallOutputContentItem::InputImage {
                        image_url: "data:image/png;base64,AA==".to_string(),
                        detail: None,
                    },
                ]),
                success: Some(true),
            },
            internal_chat_message_metadata_passthrough: None,
        }),
        None,
        "a mixed text-and-media observation is excluded whole"
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

/// Two calls sharing one id must not answer for each other.
///
/// The locator names the retained item, not the call, so each reference resolves to its own text even
/// though nothing else distinguishes them.
#[tokio::test]
async fn a_reused_call_id_does_not_let_one_reference_answer_with_the_others_text() {
    let (session, turn_context) = crate::session::tests::make_session_and_context().await;
    let first = ResponseItem::FunctionCallOutput {
        id: Some(ResponseItemId::from_server("fco_first".to_string())),
        call_id: "call-1".to_string(),
        output: FunctionCallOutputPayload {
            body: FunctionCallOutputBody::Text(TARGET_MARKER.to_string()),
            success: Some(true),
        },
        internal_chat_message_metadata_passthrough: None,
    };
    let second = ResponseItem::FunctionCallOutput {
        id: Some(ResponseItemId::from_server("fco_second".to_string())),
        call_id: "call-1".to_string(),
        output: FunctionCallOutputPayload {
            body: FunctionCallOutputBody::Text(NEIGHBOUR_MARKER.to_string()),
            success: Some(true),
        },
        internal_chat_message_metadata_passthrough: None,
    };
    session
        .record_conversation_items(&turn_context, &[first, second])
        .await;

    let mut earlier = fact_for(session.thread_id, "call-1");
    earlier.locator.item_id = "fco_first".to_string();
    let mut later = fact_for(session.thread_id, "call-1");
    later.locator.item_id = "fco_second".to_string();

    assert_eq!(
        read_observation(&session, &earlier).await.observation(),
        Some(TARGET_MARKER)
    );
    assert_eq!(
        read_observation(&session, &later).await.observation(),
        Some(NEIGHBOUR_MARKER)
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
