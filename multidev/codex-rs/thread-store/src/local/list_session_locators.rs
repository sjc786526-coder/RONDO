use super::LocalThreadStore;
use crate::ListSessionLocatorsError;
use crate::ListSessionLocatorsParams;
use crate::SessionLocator;
use crate::SessionLocatorCursor;
use crate::SessionLocatorPage;
use crate::SessionLocatorStorage;

const MAX_SESSION_LOCATOR_PAGE_SIZE: usize = 100;

pub(super) async fn list_session_locators(
    store: &LocalThreadStore,
    params: ListSessionLocatorsParams,
) -> Result<SessionLocatorPage, ListSessionLocatorsError> {
    if !(1..=MAX_SESSION_LOCATOR_PAGE_SIZE).contains(&params.page_size) {
        return Err(ListSessionLocatorsError::InvalidRequest {
            message: format!("page_size must be between 1 and {MAX_SESSION_LOCATOR_PAGE_SIZE}"),
        });
    }
    if params
        .cursor
        .as_ref()
        .is_some_and(|cursor| cursor.storage != params.storage)
    {
        return Err(ListSessionLocatorsError::InvalidRequest {
            message: "cursor belongs to another storage collection".to_string(),
        });
    }
    let state_db = store
        .state_db()
        .await
        .ok_or(ListSessionLocatorsError::Unsupported {
            operation: "list_session_locators",
        })?;
    let cursor = params
        .cursor
        .as_ref()
        .map(|cursor| codex_state::ThreadLocatorCursor {
            storage: match cursor.storage {
                SessionLocatorStorage::Active => codex_state::ThreadLocatorStorage::Active,
                SessionLocatorStorage::Archived => codex_state::ThreadLocatorStorage::Archived,
            },
            created_at: cursor.created_at,
            thread_id: cursor.thread_id,
        });
    let storage = match params.storage {
        SessionLocatorStorage::Active => codex_state::ThreadLocatorStorage::Active,
        SessionLocatorStorage::Archived => codex_state::ThreadLocatorStorage::Archived,
    };
    let page = state_db
        .list_thread_locators(params.page_size, cursor.as_ref(), storage)
        .await
        .map_err(|error| match error {
            codex_state::ListThreadLocatorsError::InvalidRequest { message } => {
                ListSessionLocatorsError::InvalidRequest { message }
            }
            codex_state::ListThreadLocatorsError::Unavailable { message } => {
                ListSessionLocatorsError::Unavailable {
                    message: format!("failed to query state DB locators: {message}"),
                }
            }
            codex_state::ListThreadLocatorsError::Corrupt { message } => {
                ListSessionLocatorsError::Corrupt { message }
            }
        })?;
    Ok(SessionLocatorPage {
        items: page
            .items
            .into_iter()
            .map(|item| SessionLocator {
                thread_id: item.thread_id,
                created_at: item.created_at,
            })
            .collect(),
        next_cursor: page.next_cursor.map(|cursor| SessionLocatorCursor {
            storage: match cursor.storage {
                codex_state::ThreadLocatorStorage::Active => SessionLocatorStorage::Active,
                codex_state::ThreadLocatorStorage::Archived => SessionLocatorStorage::Archived,
            },
            created_at: cursor.created_at,
            thread_id: cursor.thread_id,
        }),
    })
}
