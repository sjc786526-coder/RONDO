//! Client-side synchronization state for the read-only Durable Session query UI.
//!
//! The generic state-machine core performs no I/O. It coordinates connection
//! replacement, list-page or Session attachment, and explicit authoritative
//! reads, while the formal protocol wrappers additionally validate canonical
//! Session/Root identity and committed Team continuity. A successful read
//! always replaces the whole visible projection; callers cannot append partial
//! pages through this API.

use codex_app_server_protocol::DurableSessionListParams;
use codex_app_server_protocol::DurableSessionListResponse;
use codex_app_server_protocol::DurableSessionReadParams;
use codex_app_server_protocol::DurableSessionReadResponse;
use codex_app_server_protocol::DurableSessionReadStatus;
use codex_app_server_protocol::DurableSessionTeamRole;
use std::collections::HashMap;
use std::hash::Hash;

/// Identifies one bound app-server connection.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct QueryConnectionEpoch(u64);

impl QueryConnectionEpoch {
    pub fn get(self) -> u64 {
        self.0
    }
}

/// Whether the projection for the current query attachment is current.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum QueryViewFreshness {
    /// No projection has been accepted for the current attachment.
    #[default]
    Absent,
    /// An explicit authoritative read is in flight.
    Refreshing,
    /// The whole projection came from the latest accepted authoritative read.
    Fresh,
    /// A retained projection is useful context but is no longer authoritative.
    Stale,
}

/// The target of a read-only Durable Session query.
///
/// A list attachment identifies one bounded page, including its cursor. A
/// single-Session attachment identifies one Session read. Keeping the variants
/// distinct prevents a list response from being installed as a Session view.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DurableSessionQueryAttachment<L, S> {
    List(L),
    Session(S),
}

/// The whole projection accepted for the current attachment.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DurableSessionQueryProjection<L, S> {
    List(L),
    Session(S),
}

/// Identifies one explicitly started authoritative query read.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct QueryReadTicket {
    connection_epoch: QueryConnectionEpoch,
    attachment_generation: u64,
    read_generation: u64,
}

impl QueryReadTicket {
    pub fn connection_epoch(self) -> QueryConnectionEpoch {
        self.connection_epoch
    }

    pub fn attachment_generation(self) -> u64 {
        self.attachment_generation
    }

    pub fn read_generation(self) -> u64 {
        self.read_generation
    }
}

/// Stable identity of a complete committed Team projection observed by a read.
///
/// `F` is the server-provided stable fingerprint of the complete committed
/// snapshot payload. The durable commit generation is intentionally separate:
/// request generations, bounded view equality, and Team revisions never
/// substitute for this pair.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CommittedProjection<F> {
    generation: u64,
    fingerprint: F,
}

impl<F> CommittedProjection<F> {
    pub fn new(generation: u64, fingerprint: F) -> Self {
        Self {
            generation,
            fingerprint,
        }
    }

    pub fn generation(&self) -> u64 {
        self.generation
    }

    pub fn fingerprint(&self) -> &F {
        &self.fingerprint
    }
}

/// Committed Team evidence carried by an authoritative Session response.
///
/// `Unavailable` means the response itself is authoritative but has no complete
/// committed Team projection. The protocol projection retains the typed reason.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum SessionCommittedRead<F> {
    Available(CommittedProjection<F>),
    Unavailable,
}

/// Why a complete committed projection was rejected.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CommittedProjectionConflict {
    GenerationRegressed {
        accepted_generation: u64,
        received_generation: u64,
    },
    SameGenerationChanged {
        generation: u64,
    },
}

/// Why a protocol list projection could not be treated as one authoritative page.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InvalidSessionListProjection {
    /// A complete committed Team projection lacked its canonical Root identity.
    MissingRootIdentity,
    /// The page repeated the same Session and Root identity.
    DuplicateSessionIdentity,
    /// The page associated one Session identity with different Root identities.
    ConflictingRootIdentity,
    /// A view claimed a complete read without carrying its committed Team projection.
    MissingCommittedProjection,
    /// A view carried a committed Team projection while declaring the read unavailable.
    UnexpectedCommittedProjection,
    /// The Team viewer was not the canonical Root named by the outer Session identity.
    InvalidTeamViewer,
}

/// Why a protocol Session projection did not match its authoritative read attachment.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum InvalidSessionReadProjection {
    /// The response described a different Session than the request attachment.
    SessionIdentityMismatch,
    /// The response described a different canonical Root than the request attachment.
    RootIdentityMismatch,
    /// This Session was previously authenticated against another canonical Root.
    ConflictingRootIdentity,
    /// A response claiming usable committed state omitted its canonical Root identity.
    MissingRootIdentity,
    /// A response claimed a complete read without carrying its committed Team projection.
    MissingCommittedProjection,
    /// A response carried a committed Team projection while declaring the read unavailable.
    UnexpectedCommittedProjection,
    /// The Team viewer was not the canonical Root named by the outer Session identity.
    InvalidTeamViewer,
}

/// Result of applying a query completion.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum QueryReadApplyResult {
    Applied,
    /// The response belongs to an old connection, attachment, or read.
    Retired,
    /// The response kind did not match the ticket's current attachment kind.
    AttachmentMismatch,
    /// Durable commit monotonicity or same-generation identity was violated.
    RejectedCommittedProjection(CommittedProjectionConflict),
    /// The list page did not contain a self-consistent set of Session identities.
    RejectedInvalidListProjection(InvalidSessionListProjection),
    /// The Session projection did not match its request attachment.
    RejectedInvalidSessionProjection(InvalidSessionReadProjection),
}

/// Synchronizes one read-only Durable Session query attachment.
///
/// `LA` and `SA` are list-page and Session attachment identities. `LP` and `SP`
/// are their complete protocol projections. `F` is the stable committed
/// fingerprint supplied by the server within list and Session responses. The machine
/// never mutates Sessions, retries requests, joins pages, or acts as a durable
/// source.
#[derive(Clone, Debug)]
pub struct DurableSessionQueryState<LA, SA, LP, SP, F> {
    connection_epoch: QueryConnectionEpoch,
    connected: bool,
    attachment_generation: u64,
    read_generation: u64,
    attachment: Option<DurableSessionQueryAttachment<LA, SA>>,
    projection: Option<DurableSessionQueryProjection<LP, SP>>,
    view_freshness: QueryViewFreshness,
    active_read: Option<QueryReadTicket>,
    recent_session_attachment: Option<SA>,
    committed_high_water_by_session: HashMap<SA, CommittedProjection<F>>,
    // Protocol-only identity axis, intentionally independent of committed Team availability.
    // Generic test states leave this empty; formal protocol wrappers update it atomically.
    canonical_root_by_session: HashMap<String, String>,
}

/// Protocol-typed state used by app-server clients and presentation surfaces.
///
/// Its committed high-water fingerprint is copied directly from the validated
/// snapshot fingerprint in `DurableSessionTeamProjection`; callers do not
/// derive it from the bounded Team view.
pub type DurableSessionQueryClientState = DurableSessionQueryState<
    DurableSessionListParams,
    DurableSessionReadParams,
    DurableSessionListResponse,
    DurableSessionReadResponse,
    String,
>;

impl<LA, SA, LP, SP, F> Default for DurableSessionQueryState<LA, SA, LP, SP, F> {
    fn default() -> Self {
        Self {
            connection_epoch: QueryConnectionEpoch::default(),
            connected: false,
            attachment_generation: 0,
            read_generation: 0,
            attachment: None,
            projection: None,
            view_freshness: QueryViewFreshness::Absent,
            active_read: None,
            recent_session_attachment: None,
            committed_high_water_by_session: HashMap::new(),
            canonical_root_by_session: HashMap::new(),
        }
    }
}

impl<LA, SA, LP, SP, F> DurableSessionQueryState<LA, SA, LP, SP, F> {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn connection_epoch(&self) -> QueryConnectionEpoch {
        self.connection_epoch
    }

    pub fn is_connected(&self) -> bool {
        self.connected
    }

    pub fn attachment(&self) -> Option<&DurableSessionQueryAttachment<LA, SA>> {
        self.attachment.as_ref()
    }

    pub fn projection(&self) -> Option<&DurableSessionQueryProjection<LP, SP>> {
        self.projection.as_ref()
    }

    pub fn view_freshness(&self) -> QueryViewFreshness {
        self.view_freshness
    }

    pub fn committed_high_water(&self) -> Option<&CommittedProjection<F>>
    where
        SA: Eq + Hash,
    {
        self.recent_session_attachment
            .as_ref()
            .and_then(|session| self.committed_high_water_by_session.get(session))
    }

    pub fn recent_session_attachment(&self) -> Option<&SA> {
        self.recent_session_attachment.as_ref()
    }

    /// Binds a new connection and retires every ticket from the old epoch.
    pub fn bind_connection(&mut self) -> QueryConnectionEpoch {
        self.retire_connection();
        self.connection_epoch = QueryConnectionEpoch(next_generation(self.connection_epoch.0));
        self.connected = true;
        self.connection_epoch
    }

    pub fn on_disconnected(&mut self) {
        self.retire_connection();
    }

    pub fn on_event_stream_closed(&mut self) {
        self.retire_connection();
    }

    /// Invalidates an in-flight read and marks any retained projection stale.
    pub fn on_lagged(&mut self) {
        self.active_read = None;
        self.mark_view_not_fresh();
    }

    /// Attaches to one bounded list page, replacing any prior attachment.
    ///
    /// The most recent Session identity and committed high-water mark survive
    /// list navigation, so returning to that Session cannot reset monotonicity.
    pub fn attach_list(&mut self, attachment: LA) {
        self.retire_attachment_work();
        self.attachment = Some(DurableSessionQueryAttachment::List(attachment));
        self.projection = None;
        self.view_freshness = QueryViewFreshness::Absent;
    }

    /// Attaches to one Session, replacing any prior attachment.
    ///
    /// Reattaching the same Session retires its outstanding ticket but retains
    /// its projection as stale context and preserves its committed high-water
    /// mark. A repeated `/sessions read` therefore cannot reset rollback or
    /// same-generation fingerprint protection. Each different Session has an
    /// independent high-water mark, and returning to an earlier Session restores
    /// its monotonic boundary. List navigation retains the most recent Session's
    /// high-water mark but not its visible projection.
    pub fn attach_session(&mut self, attachment: SA)
    where
        SA: Clone + PartialEq,
    {
        let same_current_session = matches!(
            self.attachment.as_ref(),
            Some(DurableSessionQueryAttachment::Session(current)) if current == &attachment
        );
        let same_recent_session = self.recent_session_attachment.as_ref() == Some(&attachment);

        self.retire_attachment_work();
        if !same_recent_session {
            self.recent_session_attachment = Some(attachment.clone());
        }
        self.attachment = Some(DurableSessionQueryAttachment::Session(attachment));

        if same_current_session {
            self.mark_view_not_fresh();
        } else {
            self.projection = None;
            self.view_freshness = QueryViewFreshness::Absent;
        }
    }

    /// Detaches without issuing any server request or lifecycle operation.
    pub fn detach(&mut self) {
        self.retire_attachment_work();
        self.attachment = None;
        self.projection = None;
        self.view_freshness = QueryViewFreshness::Absent;
        self.recent_session_attachment = None;
    }

    /// Starts an explicit authoritative read for the current attachment.
    pub fn begin_read(&mut self) -> Option<QueryReadTicket> {
        if !self.connected || self.attachment.is_none() {
            return None;
        }

        self.read_generation = next_generation(self.read_generation);
        let ticket = QueryReadTicket {
            connection_epoch: self.connection_epoch,
            attachment_generation: self.attachment_generation,
            read_generation: self.read_generation,
        };
        self.active_read = Some(ticket);
        self.view_freshness = QueryViewFreshness::Refreshing;
        Some(ticket)
    }

    /// Replaces the whole list page for the currently active list read.
    #[cfg(test)]
    pub(crate) fn apply_list_read_success(
        &mut self,
        ticket: QueryReadTicket,
        projection: LP,
    ) -> QueryReadApplyResult
    where
        F: Eq,
        SA: Eq + Hash,
    {
        self.apply_list_read_success_with_committed(ticket, projection, Ok(Vec::new()))
    }

    /// Atomically applies a list page and all committed projections carried by that page.
    ///
    /// Validation occurs against a page-local staging map. A later row cannot leave an earlier
    /// row's high-water mark partially committed when the whole page is rejected.
    fn apply_list_read_success_with_committed(
        &mut self,
        ticket: QueryReadTicket,
        projection: LP,
        committed: Result<Vec<(SA, CommittedProjection<F>)>, InvalidSessionListProjection>,
    ) -> QueryReadApplyResult
    where
        F: Eq,
        SA: Eq + Hash,
    {
        if !self.read_ticket_is_current(ticket) {
            return QueryReadApplyResult::Retired;
        }
        if !matches!(
            self.attachment.as_ref(),
            Some(DurableSessionQueryAttachment::List(_))
        ) {
            self.finish_invalid_read();
            return QueryReadApplyResult::AttachmentMismatch;
        }
        let committed = match committed {
            Ok(committed) => committed,
            Err(error) => {
                self.finish_invalid_read();
                return QueryReadApplyResult::RejectedInvalidListProjection(error);
            }
        };
        let mut staged = HashMap::new();
        for (session, received) in committed {
            let accepted = staged
                .get(&session)
                .or_else(|| self.committed_high_water_by_session.get(&session));
            if let Some(accepted) = accepted
                && let Err(conflict) = validate_committed_projection(accepted, &received)
            {
                self.finish_invalid_read();
                return QueryReadApplyResult::RejectedCommittedProjection(conflict);
            }
            staged.insert(session, received);
        }

        self.committed_high_water_by_session.extend(staged);
        self.active_read = None;
        self.projection = Some(DurableSessionQueryProjection::List(projection));
        self.view_freshness = QueryViewFreshness::Fresh;
        QueryReadApplyResult::Applied
    }

    /// Replaces the whole Session projection for the current authoritative read.
    ///
    /// A newer request cannot make an older committed generation fresh. Equal
    /// generations must have equal complete projection fingerprints. Responses
    /// without a committed projection may replace the view but never clear or
    /// lower the high-water mark.
    #[cfg(test)]
    pub(crate) fn apply_session_read_success(
        &mut self,
        ticket: QueryReadTicket,
        projection: SP,
        committed: SessionCommittedRead<F>,
    ) -> QueryReadApplyResult
    where
        F: Eq,
        SA: Clone + Eq + Hash,
    {
        self.apply_session_read_success_with_validation(ticket, projection, Ok(committed))
    }

    fn apply_session_read_success_with_validation(
        &mut self,
        ticket: QueryReadTicket,
        projection: SP,
        committed: Result<SessionCommittedRead<F>, InvalidSessionReadProjection>,
    ) -> QueryReadApplyResult
    where
        F: Eq,
        SA: Clone + Eq + Hash,
    {
        if !self.read_ticket_is_current(ticket) {
            return QueryReadApplyResult::Retired;
        }
        if !matches!(
            self.attachment.as_ref(),
            Some(DurableSessionQueryAttachment::Session(_))
        ) {
            self.finish_invalid_read();
            return QueryReadApplyResult::AttachmentMismatch;
        }
        let committed = match committed {
            Ok(committed) => committed,
            Err(error) => {
                self.finish_invalid_read();
                return QueryReadApplyResult::RejectedInvalidSessionProjection(error);
            }
        };
        if let SessionCommittedRead::Available(received) = committed
            && let Err(conflict) = self.advance_committed_high_water(received)
        {
            self.finish_invalid_read();
            return QueryReadApplyResult::RejectedCommittedProjection(conflict);
        }

        self.active_read = None;
        self.projection = Some(DurableSessionQueryProjection::Session(projection));
        self.view_freshness = QueryViewFreshness::Fresh;
        QueryReadApplyResult::Applied
    }

    /// Completes the active read without replacing the retained projection.
    pub fn apply_read_failure(&mut self, ticket: QueryReadTicket) -> bool {
        if !self.read_ticket_is_current(ticket) {
            return false;
        }

        self.finish_invalid_read();
        true
    }

    fn advance_committed_high_water(
        &mut self,
        received: CommittedProjection<F>,
    ) -> Result<(), CommittedProjectionConflict>
    where
        F: Eq,
        SA: Clone + Eq + Hash,
    {
        let Some(DurableSessionQueryAttachment::Session(session)) = self.attachment.as_ref() else {
            return Ok(());
        };
        let Some(accepted) = self.committed_high_water_by_session.get(session) else {
            self.committed_high_water_by_session
                .insert(session.clone(), received);
            return Ok(());
        };

        validate_committed_projection(accepted, &received)?;

        self.committed_high_water_by_session
            .insert(session.clone(), received);
        Ok(())
    }

    fn read_ticket_is_current(&self, ticket: QueryReadTicket) -> bool {
        self.connected
            && self.attachment.is_some()
            && self.active_read == Some(ticket)
            && ticket.connection_epoch == self.connection_epoch
            && ticket.attachment_generation == self.attachment_generation
            && ticket.read_generation == self.read_generation
    }

    fn retire_connection(&mut self) {
        self.connected = false;
        self.active_read = None;
        self.mark_view_not_fresh();
    }

    fn retire_attachment_work(&mut self) {
        self.attachment_generation = next_generation(self.attachment_generation);
        self.read_generation = next_generation(self.read_generation);
        self.active_read = None;
    }

    fn finish_invalid_read(&mut self) {
        self.active_read = None;
        self.mark_view_not_fresh();
    }

    fn mark_view_not_fresh(&mut self) {
        self.view_freshness = if self.projection.is_some() {
            QueryViewFreshness::Stale
        } else {
            QueryViewFreshness::Absent
        };
    }
}

impl DurableSessionQueryClientState {
    /// Applies one typed `session/list` response while sharing the per-Session committed
    /// generation and snapshot-fingerprint high-water marks used by `session/read`.
    pub fn apply_protocol_list_read_success(
        &mut self,
        ticket: QueryReadTicket,
        response: DurableSessionListResponse,
    ) -> QueryReadApplyResult {
        let evidence = protocol_list_evidence(&response, &self.canonical_root_by_session);
        let (committed, canonical_roots) = match evidence {
            Ok(evidence) => (Ok(evidence.committed), evidence.canonical_roots),
            Err(error) => (Err(error), HashMap::new()),
        };
        let result = self.apply_list_read_success_with_committed(ticket, response, committed);
        if result == QueryReadApplyResult::Applied {
            self.canonical_root_by_session.extend(canonical_roots);
        }
        result
    }

    /// Applies one typed `session/read` response using its canonical commit
    /// generation and stable complete-snapshot fingerprint.
    pub fn apply_protocol_session_read_success(
        &mut self,
        ticket: QueryReadTicket,
        response: DurableSessionReadResponse,
    ) -> QueryReadApplyResult {
        let expected = match self.attachment.as_ref() {
            Some(DurableSessionQueryAttachment::Session(expected)) => Some(expected),
            _ => None,
        };
        let canonical_root = response
            .session
            .identity
            .root_thread_id
            .as_ref()
            .map(|root| (response.session.identity.session_id.clone(), root.clone()));
        let committed = protocol_session_committed_projection(
            expected,
            &response,
            &self.canonical_root_by_session,
        );
        let result = self.apply_session_read_success_with_validation(ticket, response, committed);
        if result == QueryReadApplyResult::Applied
            && let Some((session_id, root_thread_id)) = canonical_root
        {
            self.canonical_root_by_session
                .insert(session_id, root_thread_id);
        }
        result
    }
}

struct ProtocolListEvidence {
    committed: Vec<(DurableSessionReadParams, CommittedProjection<String>)>,
    canonical_roots: HashMap<String, String>,
}

fn protocol_list_evidence(
    response: &DurableSessionListResponse,
    known_roots: &HashMap<String, String>,
) -> Result<ProtocolListEvidence, InvalidSessionListProjection> {
    let mut roots_by_session = HashMap::new();
    let mut committed = Vec::new();
    for view in &response.data {
        let session_id = view.identity.session_id.clone();
        let root_thread_id = view.identity.root_thread_id.clone();
        if matches!(&view.read_status, DurableSessionReadStatus::Available) && view.team.is_none() {
            return Err(InvalidSessionListProjection::MissingCommittedProjection);
        }
        if !matches!(&view.read_status, DurableSessionReadStatus::Available) && view.team.is_some()
        {
            return Err(InvalidSessionListProjection::UnexpectedCommittedProjection);
        }
        if root_thread_id.is_none() && view.team.is_some() {
            return Err(InvalidSessionListProjection::MissingRootIdentity);
        }
        if let (Some(root_thread_id), Some(team)) = (root_thread_id.as_deref(), view.team.as_ref())
            && (team.viewer.thread_id.as_str() != root_thread_id
                || team.viewer.role != DurableSessionTeamRole::Root)
        {
            return Err(InvalidSessionListProjection::InvalidTeamViewer);
        }
        if let Some(root_thread_id) = root_thread_id.as_deref()
            && known_roots
                .get(session_id.as_str())
                .is_some_and(|accepted| accepted != root_thread_id)
        {
            return Err(InvalidSessionListProjection::ConflictingRootIdentity);
        }
        if let Some(previous_root) =
            roots_by_session.insert(session_id.clone(), root_thread_id.clone())
        {
            return Err(if previous_root == root_thread_id {
                InvalidSessionListProjection::DuplicateSessionIdentity
            } else {
                InvalidSessionListProjection::ConflictingRootIdentity
            });
        }
        let Some(team) = view.team.as_ref() else {
            continue;
        };
        let Some(root_thread_id) = root_thread_id else {
            return Err(InvalidSessionListProjection::MissingRootIdentity);
        };
        committed.push((
            DurableSessionReadParams {
                session_id,
                root_thread_id,
            },
            CommittedProjection::new(team.commit_generation, team.commit_fingerprint.clone()),
        ));
    }
    let canonical_roots = roots_by_session
        .into_iter()
        .filter_map(|(session_id, root_thread_id)| {
            root_thread_id.map(|root_thread_id| (session_id, root_thread_id))
        })
        .collect();
    Ok(ProtocolListEvidence {
        committed,
        canonical_roots,
    })
}

fn protocol_session_committed_projection(
    expected: Option<&DurableSessionReadParams>,
    response: &DurableSessionReadResponse,
    known_roots: &HashMap<String, String>,
) -> Result<SessionCommittedRead<String>, InvalidSessionReadProjection> {
    let Some(expected) = expected else {
        // The apply boundary retains responsibility for reporting attachment-kind mismatch after
        // it has established that the ticket is current.
        return Ok(SessionCommittedRead::Unavailable);
    };
    let session = &response.session;
    if session.identity.session_id != expected.session_id {
        return Err(InvalidSessionReadProjection::SessionIdentityMismatch);
    }
    if known_roots
        .get(expected.session_id.as_str())
        .is_some_and(|accepted| accepted != &expected.root_thread_id)
    {
        return Err(InvalidSessionReadProjection::ConflictingRootIdentity);
    }
    if matches!(&session.read_status, DurableSessionReadStatus::Available) && session.team.is_none()
    {
        return Err(InvalidSessionReadProjection::MissingCommittedProjection);
    }
    if !matches!(&session.read_status, DurableSessionReadStatus::Available)
        && session.team.is_some()
    {
        return Err(InvalidSessionReadProjection::UnexpectedCommittedProjection);
    }
    match session.identity.root_thread_id.as_deref() {
        Some(root_thread_id) if root_thread_id != expected.root_thread_id.as_str() => {
            return Err(InvalidSessionReadProjection::RootIdentityMismatch);
        }
        Some(root_thread_id)
            if known_roots
                .get(session.identity.session_id.as_str())
                .is_some_and(|accepted| accepted != root_thread_id) =>
        {
            return Err(InvalidSessionReadProjection::ConflictingRootIdentity);
        }
        Some(root_thread_id) => {
            if let Some(team) = session.team.as_ref()
                && (team.viewer.thread_id.as_str() != root_thread_id
                    || team.viewer.role != DurableSessionTeamRole::Root)
            {
                return Err(InvalidSessionReadProjection::InvalidTeamViewer);
            }
        }
        None if session.team.is_some() => {
            return Err(InvalidSessionReadProjection::MissingRootIdentity);
        }
        None => return Ok(SessionCommittedRead::Unavailable),
    }
    Ok(match session.team.as_ref() {
        Some(team) => SessionCommittedRead::Available(CommittedProjection::new(
            team.commit_generation,
            team.commit_fingerprint.clone(),
        )),
        None => SessionCommittedRead::Unavailable,
    })
}

fn validate_committed_projection<F: Eq>(
    accepted: &CommittedProjection<F>,
    received: &CommittedProjection<F>,
) -> Result<(), CommittedProjectionConflict> {
    if received.generation < accepted.generation {
        return Err(CommittedProjectionConflict::GenerationRegressed {
            accepted_generation: accepted.generation,
            received_generation: received.generation,
        });
    }
    if received.generation == accepted.generation && received.fingerprint != accepted.fingerprint {
        return Err(CommittedProjectionConflict::SameGenerationChanged {
            generation: received.generation,
        });
    }
    Ok(())
}

fn next_generation(current: u64) -> u64 {
    current.wrapping_add(1)
}

#[cfg(test)]
#[path = "durable_session_query_tests.rs"]
mod tests;
