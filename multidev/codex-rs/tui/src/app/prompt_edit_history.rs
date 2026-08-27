//! Temporary turn projection used to locate a prompt-edit fork point.
//!
//! Loaded snapshots can lag behind the live replay buffer. Prompt editing needs a consistent
//! lookup view of both sources, but that view must not become another history authority or mutate
//! the source thread.

use super::*;

pub(super) fn turns_for_prompt_edit(store: &ThreadEventStore) -> Vec<Turn> {
    let mut turns = store.turns.clone();

    for event in &store.buffer {
        let ThreadBufferedEvent::Notification(notification) = event else {
            continue;
        };
        match notification.as_ref() {
            ServerNotification::TurnStarted(notification)
                if !turns.iter().any(|turn| turn.id == notification.turn.id) =>
            {
                turns.push(notification.turn.clone());
            }
            ServerNotification::ItemCompleted(notification)
                if matches!(
                    notification.item,
                    ThreadItem::UserMessage { .. }
                        | ThreadItem::EnteredReviewMode { .. }
                        | ThreadItem::ExitedReviewMode { .. }
                ) =>
            {
                if let Some(turn) = turns
                    .iter_mut()
                    .find(|turn| turn.id == notification.turn_id)
                    && !turn
                        .items
                        .iter()
                        .any(|item| item.id() == notification.item.id())
                {
                    turn.items.push(notification.item.clone());
                }
            }
            ServerNotification::TurnCompleted(notification) => {
                if let Some(turn) = turns
                    .iter_mut()
                    .find(|turn| turn.id == notification.turn.id)
                {
                    turn.status = notification.turn.status.clone();
                    turn.error = notification.turn.error.clone();
                    turn.started_at = notification.turn.started_at;
                    turn.completed_at = notification.turn.completed_at;
                    turn.duration_ms = notification.turn.duration_ms;
                }
            }
            _ => {}
        }
    }

    turns
}

#[cfg(test)]
#[path = "prompt_edit_history_tests.rs"]
mod tests;
