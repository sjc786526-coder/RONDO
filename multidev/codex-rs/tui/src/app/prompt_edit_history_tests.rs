use super::*;
use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnError;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnStartedNotification;
use codex_app_server_protocol::UserInput;
use pretty_assertions::assert_eq;

fn turn(id: &str, status: TurnStatus, items: Vec<ThreadItem>) -> Turn {
    Turn {
        id: id.to_string(),
        items,
        items_view: TurnItemsView::Full,
        status,
        error: None,
        started_at: None,
        completed_at: None,
        duration_ms: None,
    }
}

fn user_message(id: &str, text: &str) -> ThreadItem {
    ThreadItem::UserMessage {
        id: id.to_string(),
        client_id: None,
        content: vec![UserInput::Text {
            text: text.to_string(),
            text_elements: Vec::new(),
        }],
    }
}

fn push_turn_started(store: &mut ThreadEventStore, turn: Turn) {
    store.push_notification(ServerNotification::TurnStarted(TurnStartedNotification {
        thread_id: "thread-1".to_string(),
        turn,
    }));
}

fn push_item_completed(store: &mut ThreadEventStore, turn_id: &str, item: ThreadItem) {
    store.push_notification(ServerNotification::ItemCompleted(
        ItemCompletedNotification {
            item,
            thread_id: "thread-1".to_string(),
            turn_id: turn_id.to_string(),
            completed_at_ms: 0,
        },
    ));
}

fn push_turn_completed(store: &mut ThreadEventStore, turn: Turn) {
    store.push_notification(ServerNotification::TurnCompleted(
        TurnCompletedNotification {
            thread_id: "thread-1".to_string(),
            turn,
        },
    ));
}

#[test]
fn reconstructs_buffered_prompt_turns_and_completion_metadata() {
    let retained = turn(
        "turn-1",
        TurnStatus::Completed,
        vec![user_message("user-1", "retained")],
    );
    let mut store = ThreadEventStore::new(/*capacity*/ 16);
    store.set_turns(vec![retained.clone()]);

    push_turn_started(
        &mut store,
        Turn {
            started_at: Some(10),
            ..turn("turn-2", TurnStatus::InProgress, Vec::new())
        },
    );
    let selected = user_message("user-2", "selected");
    push_item_completed(&mut store, "turn-2", selected.clone());
    push_item_completed(
        &mut store,
        "turn-2",
        ThreadItem::AgentMessage {
            id: "agent-2".to_string(),
            text: "not needed for prompt lookup".to_string(),
            phase: None,
            memory_citation: None,
        },
    );
    let review_boundary = ThreadItem::EnteredReviewMode {
        id: "review-2".to_string(),
        review: "changes".to_string(),
    };
    push_item_completed(&mut store, "turn-2", review_boundary.clone());
    push_item_completed(&mut store, "turn-2", selected.clone());
    let completion_error = TurnError {
        message: "interrupted".to_string(),
        codex_error_info: None,
        additional_details: None,
    };
    push_turn_completed(
        &mut store,
        Turn {
            error: Some(completion_error.clone()),
            started_at: Some(11),
            completed_at: Some(20),
            duration_ms: Some(9),
            ..turn("turn-2", TurnStatus::Interrupted, Vec::new())
        },
    );
    let completed = user_message("user-3", "completed");
    push_turn_started(
        &mut store,
        Turn {
            started_at: Some(21),
            ..turn("turn-3", TurnStatus::InProgress, Vec::new())
        },
    );
    push_item_completed(&mut store, "turn-3", completed.clone());
    push_turn_completed(
        &mut store,
        Turn {
            started_at: Some(21),
            completed_at: Some(30),
            duration_ms: Some(9),
            ..turn("turn-3", TurnStatus::Completed, Vec::new())
        },
    );

    assert_eq!(
        turns_for_prompt_edit(&store),
        vec![
            retained,
            Turn {
                items: vec![selected, review_boundary],
                error: Some(completion_error),
                started_at: Some(11),
                completed_at: Some(20),
                duration_ms: Some(9),
                ..turn("turn-2", TurnStatus::Interrupted, Vec::new())
            },
            Turn {
                items: vec![completed],
                started_at: Some(21),
                completed_at: Some(30),
                duration_ms: Some(9),
                ..turn("turn-3", TurnStatus::Completed, Vec::new())
            },
        ]
    );
}

#[test]
fn merges_snapshot_and_buffer_without_replacing_items_or_crossing_turns() {
    let original = user_message("user-1", "original");
    let retained = turn("turn-1", TurnStatus::InProgress, vec![original.clone()]);
    let mut store = ThreadEventStore::new(/*capacity*/ 16);
    store.set_turns(vec![retained]);

    push_turn_started(
        &mut store,
        turn("turn-1", TurnStatus::InProgress, Vec::new()),
    );
    push_item_completed(&mut store, "turn-1", user_message("user-1", "duplicate"));
    let review_boundary = ThreadItem::ExitedReviewMode {
        id: "review-1".to_string(),
        review: "done".to_string(),
    };
    push_item_completed(&mut store, "turn-1", review_boundary.clone());
    push_item_completed(
        &mut store,
        "missing-turn",
        user_message("orphan", "must not cross turns"),
    );
    push_turn_completed(
        &mut store,
        Turn {
            items: vec![user_message("replacement", "must not replace")],
            started_at: Some(1),
            completed_at: Some(2),
            duration_ms: Some(1),
            ..turn("turn-1", TurnStatus::Completed, Vec::new())
        },
    );

    assert_eq!(
        turns_for_prompt_edit(&store),
        vec![Turn {
            items: vec![original, review_boundary],
            started_at: Some(1),
            completed_at: Some(2),
            duration_ms: Some(1),
            ..turn("turn-1", TurnStatus::Completed, Vec::new())
        }]
    );
}
