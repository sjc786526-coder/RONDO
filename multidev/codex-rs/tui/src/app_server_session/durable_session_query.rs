//! Query-only synchronization owned by [`AppServerSession`].

use super::AppServerSession;
use codex_app_server_client::DurableSessionQueryAttachment;
use codex_app_server_client::DurableSessionQueryClientState;
use codex_app_server_client::DurableSessionQueryProjection;
use codex_app_server_client::QueryReadApplyResult;
use codex_app_server_client::QueryReadTicket;
use codex_app_server_client::QueryViewFreshness;
use codex_app_server_protocol::DurableSessionListParams;
use codex_app_server_protocol::DurableSessionListResponse;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use std::sync::MutexGuard;

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum DurableSessionQueryRequest {
    List {
        ticket: QueryReadTicket,
        params: DurableSessionListParams,
    },
    Session {
        ticket: QueryReadTicket,
        params: DurableSessionReadParams,
    },
}

impl AppServerSession {
    pub(crate) fn durable_session_begin_list(
        &self,
        params: DurableSessionListParams,
    ) -> Result<DurableSessionQueryRequest, &'static str> {
        let mut query = self.durable_session_query();
        self.durable_session_control_retire_for_attachment_change(&mut query);
        query.attach_list(params.clone());
        let ticket = query
            .begin_read()
            .ok_or("Durable Session query is disconnected")?;
        Ok(DurableSessionQueryRequest::List { ticket, params })
    }

    pub(crate) fn durable_session_begin_read(
        &self,
        params: DurableSessionReadParams,
    ) -> Result<DurableSessionQueryRequest, &'static str> {
        let mut query = self.durable_session_query();
        self.durable_session_control_retire_for_attachment_change(&mut query);
        query.attach_session(params.clone());
        let ticket = query
            .begin_read()
            .ok_or("Durable Session query is disconnected")?;
        Ok(DurableSessionQueryRequest::Session { ticket, params })
    }

    pub(crate) fn durable_session_begin_next(
        &self,
    ) -> Result<DurableSessionQueryRequest, &'static str> {
        let mut query = self.durable_session_query();
        if query.view_freshness() != QueryViewFreshness::Fresh {
            return Err("next requires a fresh Durable Session list page");
        }
        let (params, next_cursor) = match (query.attachment(), query.projection()) {
            (
                Some(DurableSessionQueryAttachment::List(params)),
                Some(DurableSessionQueryProjection::List(response)),
            ) => (params.clone(), response.next_cursor.clone()),
            _ => return Err("next requires a fresh Durable Session list page"),
        };
        let next_cursor = next_cursor.ok_or("the current Durable Session page has no next page")?;
        let params = DurableSessionListParams {
            cursor: Some(next_cursor),
            ..params
        };
        self.durable_session_control_retire_for_attachment_change(&mut query);
        query.attach_list(params.clone());
        let ticket = query
            .begin_read()
            .ok_or("Durable Session query is disconnected")?;
        Ok(DurableSessionQueryRequest::List { ticket, params })
    }

    pub(crate) fn durable_session_begin_refresh(
        &self,
    ) -> Result<DurableSessionQueryRequest, &'static str> {
        let mut query = self.durable_session_query();
        let attachment = query
            .attachment()
            .cloned()
            .ok_or("refresh requires an existing Durable Session list or read")?;
        let ticket = query
            .begin_read()
            .ok_or("Durable Session query is disconnected")?;
        match attachment {
            DurableSessionQueryAttachment::List(params) => {
                Ok(DurableSessionQueryRequest::List { ticket, params })
            }
            DurableSessionQueryAttachment::Session(params) => {
                Ok(DurableSessionQueryRequest::Session { ticket, params })
            }
        }
    }

    pub(crate) fn durable_session_apply_list(
        &self,
        ticket: QueryReadTicket,
        response: DurableSessionListResponse,
    ) -> QueryReadApplyResult {
        self.durable_session_query()
            .apply_protocol_list_read_success(ticket, response)
    }

    pub(crate) fn durable_session_apply_read(
        &self,
        ticket: QueryReadTicket,
        response: DurableSessionReadResponse,
    ) -> QueryReadApplyResult {
        self.durable_session_query()
            .apply_protocol_session_read_success(ticket, response)
    }

    pub(crate) fn durable_session_apply_failure(&self, ticket: QueryReadTicket) -> bool {
        self.durable_session_query().apply_read_failure(ticket)
    }

    pub(crate) fn durable_session_on_lagged(&self) -> bool {
        self.durable_session_control_on_lagged()
    }

    pub(crate) fn durable_session_on_disconnected(&self) -> bool {
        self.durable_session_control_on_disconnected()
    }

    pub(crate) fn durable_session_on_event_stream_closed(&self) -> bool {
        self.durable_session_control_on_event_stream_closed()
    }

    pub(crate) fn durable_session_detach(&self) -> bool {
        self.durable_session_control_detach()
    }

    pub(crate) fn durable_session_attachment(
        &self,
    ) -> Option<DurableSessionQueryAttachment<DurableSessionListParams, DurableSessionReadParams>>
    {
        self.durable_session_query().attachment().cloned()
    }

    pub(crate) fn durable_session_projection(
        &self,
    ) -> Option<DurableSessionQueryProjection<DurableSessionListResponse, DurableSessionReadResponse>>
    {
        self.durable_session_query().projection().cloned()
    }

    pub(crate) fn durable_session_view_freshness(&self) -> QueryViewFreshness {
        self.durable_session_query().view_freshness()
    }

    pub(super) fn durable_session_query(&self) -> MutexGuard<'_, DurableSessionQueryClientState> {
        self.durable_session_query
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }
}

#[cfg(test)]
#[path = "durable_session_query_tests.rs"]
mod tests;
