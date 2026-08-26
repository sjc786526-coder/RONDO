//! Durable framing and the storage-neutral Root writer capability.
//!
//! Team state remains a domain object. The concrete thread store owns files, locking, and process
//! liveness; this module only defines the narrow permit contract it consumes and the complete blob
//! that must be committed atomically while that permit is held.

use crate::store::TeamStore;
use codex_protocol::SessionId;
use codex_protocol::ThreadId;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use uuid::Uuid;

const SNAPSHOT_MAGIC: &[u8; 17] = b"RONDO-TEAM-STATE\0";
const SNAPSHOT_VERSION: u32 = 1;
const HEADER_LEN: usize = SNAPSHOT_MAGIC.len() + 4 + 8 + 32;
const MAX_SNAPSHOT_BYTES: usize = 64 * 1024 * 1024;
/// Maximum complete frame accepted by storage adapters before allocating its body.
pub const MAX_ENCODED_SNAPSHOT_BYTES: usize = HEADER_LEN + MAX_SNAPSHOT_BYTES;

/// A Team's durable lineage. It deliberately excludes the generated Team instance: the instance
/// is recovered from the committed state, while this identity is known before that state is read.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DurableTeamIdentity {
    session_id: SessionId,
    root_thread_id: ThreadId,
}

impl DurableTeamIdentity {
    pub fn new(session_id: SessionId, root_thread_id: ThreadId) -> Self {
        Self {
            session_id,
            root_thread_id,
        }
    }

    pub fn session_id(self) -> SessionId {
        self.session_id
    }

    pub fn root_thread_id(self) -> ThreadId {
        self.root_thread_id
    }
}

/// Stable identity of one fully validated committed snapshot payload.
///
/// The checksum is copied from the existing snapshot frame after checksum, version, lineage, and
/// domain validation succeeds. This value grants no writer authority and is not an authentication
/// token; read-side consumers can use it to reject different payloads reported at one generation.
#[derive(Clone, Copy, Debug, Eq, Hash, PartialEq)]
pub struct CommittedSnapshotToken {
    commit_generation: u64,
    payload_checksum: [u8; 32],
}

impl CommittedSnapshotToken {
    pub fn commit_generation(self) -> u64 {
        self.commit_generation
    }

    pub fn payload_checksum(self) -> [u8; 32] {
        self.payload_checksum
    }
}

/// Health and access mode of a durable handle's last reconciled committed snapshot.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TeamDurabilityStatus {
    InMemory,
    Writable {
        commit_generation: u64,
    },
    ReadOnly {
        commit_generation: u64,
    },
    /// A commit may or may not have reached the durable boundary; callers must reconcile before
    /// either reporting success or attempting another mutation.
    Unknown {
        expected_generation: u64,
    },
    Unavailable {
        last_known_generation: u64,
    },
}

/// A storage-neutral durability failure. Text is diagnostic only; callers branch on the variant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TeamDurabilityError {
    Unavailable { message: String },
    Conflict { message: String },
    Unknown { message: String },
    ReadOnly,
    Corrupt { message: String },
    UnsupportedVersion { found: u32, supported: u32 },
    IdentityMismatch,
    GenerationOverflow,
    Domain(crate::mutation::TeamError),
}

impl TeamDurabilityError {
    pub fn unavailable(message: impl Into<String>) -> Self {
        Self::Unavailable {
            message: message.into(),
        }
    }

    pub fn conflict(message: impl Into<String>) -> Self {
        Self::Conflict {
            message: message.into(),
        }
    }

    pub fn unknown(message: impl Into<String>) -> Self {
        Self::Unknown {
            message: message.into(),
        }
    }

    pub fn corrupt(message: impl Into<String>) -> Self {
        Self::Corrupt {
            message: message.into(),
        }
    }
}

impl From<crate::mutation::TeamError> for TeamDurabilityError {
    fn from(value: crate::mutation::TeamError) -> Self {
        Self::Domain(value)
    }
}

impl From<TeamDurabilityError> for crate::mutation::TeamError {
    fn from(value: TeamDurabilityError) -> Self {
        match value {
            TeamDurabilityError::Domain(error) => error,
            error => Self::Durability {
                reason: error.to_string(),
            },
        }
    }
}

impl fmt::Display for TeamDurabilityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unavailable { message } => write!(f, "Team durability is unavailable: {message}"),
            Self::Conflict { message } => write!(f, "Team writer conflict: {message}"),
            Self::Unknown { message } => write!(f, "Team commit result is unknown: {message}"),
            Self::ReadOnly => f.write_str("this Team handle is read-only"),
            Self::Corrupt { message } => write!(f, "durable Team snapshot is corrupt: {message}"),
            Self::UnsupportedVersion { found, supported } => write!(
                f,
                "durable Team snapshot version {found} is unsupported; this build supports {supported}"
            ),
            Self::IdentityMismatch => {
                f.write_str("durable Team snapshot belongs to a different session lineage")
            }
            Self::GenerationOverflow => f.write_str("durable Team commit generation is exhausted"),
            Self::Domain(error) => error.fmt(f),
        }
    }
}

impl std::error::Error for TeamDurabilityError {}

/// Boxed futures keep the authority boundary object-safe without imposing an async-trait runtime.
pub type TeamDurabilityFuture<'a, T> =
    Pin<Box<dyn Future<Output = Result<T, TeamDurabilityError>> + Send + 'a>>;

/// Weak, storage-neutral capability derived from the live Root thread writer.
///
/// Merely retaining this object grants nothing. Every mutation must acquire a fresh write permit;
/// close obtains a distinct barrier permit so shutdown cannot race a Team commit.
pub trait TeamWriteAuthority: Send + Sync {
    fn identity(&self) -> DurableTeamIdentity;

    /// Identifies the exact live Root writer incarnation behind this capability.
    fn owner_incarnation_id(&self) -> Uuid;

    fn begin_write(&self) -> Result<Box<dyn TeamWritePermit>, TeamDurabilityError>;

    fn begin_close(&self) -> TeamDurabilityFuture<'_, Box<dyn TeamClosePermit>>;
}

/// Exclusive Root writer capability held continuously across read, CAS, and the mutation return.
pub trait TeamWritePermit: Send {
    /// Read the last complete committed blob, or `None` when this lineage has no Team snapshot yet.
    fn read_snapshot(&mut self) -> Result<Option<Vec<u8>>, TeamDurabilityError>;

    /// Atomically replace the committed blob when its generation still equals `expected_generation`.
    /// The blob itself carries `expected_generation + 1`; implementations must not expose a partial
    /// write and must report an indeterminate post-write result as [`TeamDurabilityError::Unknown`].
    fn compare_and_swap(
        &mut self,
        expected_generation: u64,
        snapshot: Vec<u8>,
    ) -> Result<(), TeamDurabilityError>;
}

/// Barrier that prevents new writes and waits for an already-started write before close proceeds.
///
/// A failed shutdown calls `abort`; a successful durable Team close calls `complete`. Dropping an
/// unfinished implementation must be equivalent to aborting, so cancellation cannot strand the
/// live writer in a closing state.
pub trait TeamClosePermit: Send {
    fn abort(self: Box<Self>) -> TeamDurabilityFuture<'static, ()>;
    fn complete(self: Box<Self>) -> TeamDurabilityFuture<'static, ()>;
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct SnapshotPayload {
    identity: DurableTeamIdentity,
    commit_generation: u64,
    store: TeamStore,
}

pub(crate) struct HydratedTeamSnapshot {
    pub(crate) commit_generation: u64,
    payload_checksum: [u8; 32],
    pub(crate) store: TeamStore,
}

/// Encode one complete checksummed snapshot. Atomic replacement is the permit's responsibility;
/// giving it one self-contained byte vector prevents a medium from publishing half a domain state.
pub(crate) fn encode_snapshot(
    identity: DurableTeamIdentity,
    commit_generation: u64,
    store: &TeamStore,
) -> Result<Vec<u8>, TeamDurabilityError> {
    if commit_generation == 0 {
        return Err(TeamDurabilityError::corrupt(
            "generation zero is reserved for an absent snapshot",
        ));
    }
    store.validate_durable(identity)?;
    let payload = serde_json::to_vec(&SnapshotPayload {
        identity,
        commit_generation,
        store: store.clone(),
    })
    .map_err(|error| TeamDurabilityError::corrupt(format!("cannot encode snapshot: {error}")))?;
    if payload.len() > MAX_SNAPSHOT_BYTES {
        return Err(TeamDurabilityError::corrupt(
            "snapshot exceeds the size limit",
        ));
    }

    let payload_len = u64::try_from(payload.len())
        .map_err(|_| TeamDurabilityError::corrupt("snapshot length does not fit u64"))?;
    let checksum = Sha256::digest(&payload);
    let mut encoded = Vec::with_capacity(HEADER_LEN + payload.len());
    encoded.extend_from_slice(SNAPSHOT_MAGIC);
    encoded.extend_from_slice(&SNAPSHOT_VERSION.to_be_bytes());
    encoded.extend_from_slice(&payload_len.to_be_bytes());
    encoded.extend_from_slice(&checksum);
    encoded.extend_from_slice(&payload);
    Ok(encoded)
}

pub(crate) fn decode_snapshot(
    expected_identity: DurableTeamIdentity,
    encoded: &[u8],
) -> Result<HydratedTeamSnapshot, TeamDurabilityError> {
    if encoded.len() < HEADER_LEN {
        return Err(TeamDurabilityError::corrupt("snapshot header is truncated"));
    }
    if &encoded[..SNAPSHOT_MAGIC.len()] != SNAPSHOT_MAGIC {
        return Err(TeamDurabilityError::corrupt("snapshot magic is invalid"));
    }

    let version_offset = SNAPSHOT_MAGIC.len();
    let version_bytes = encoded[version_offset..version_offset + 4]
        .try_into()
        .map_err(|_| TeamDurabilityError::corrupt("snapshot version is truncated"))?;
    let version = u32::from_be_bytes(version_bytes);
    if version != SNAPSHOT_VERSION {
        return Err(TeamDurabilityError::UnsupportedVersion {
            found: version,
            supported: SNAPSHOT_VERSION,
        });
    }

    let length_offset = version_offset + 4;
    let length_bytes = encoded[length_offset..length_offset + 8]
        .try_into()
        .map_err(|_| TeamDurabilityError::corrupt("snapshot length is truncated"))?;
    let payload_len = u64::from_be_bytes(length_bytes);
    let payload_len = usize::try_from(payload_len)
        .map_err(|_| TeamDurabilityError::corrupt("snapshot length does not fit usize"))?;
    if payload_len > MAX_SNAPSHOT_BYTES {
        return Err(TeamDurabilityError::corrupt(
            "snapshot exceeds the size limit",
        ));
    }
    let expected_len = HEADER_LEN
        .checked_add(payload_len)
        .ok_or_else(|| TeamDurabilityError::corrupt("snapshot length overflows"))?;
    if encoded.len() != expected_len {
        return Err(TeamDurabilityError::corrupt(
            "snapshot length does not match its frame",
        ));
    }

    let checksum_offset = length_offset + 8;
    let payload_offset = checksum_offset + 32;
    let expected_checksum = &encoded[checksum_offset..payload_offset];
    let payload = &encoded[payload_offset..];
    if Sha256::digest(payload).as_slice() != expected_checksum {
        return Err(TeamDurabilityError::corrupt(
            "snapshot checksum does not match",
        ));
    }
    let mut payload_checksum = [0; 32];
    payload_checksum.copy_from_slice(expected_checksum);

    let payload: SnapshotPayload = serde_json::from_slice(payload).map_err(|error| {
        TeamDurabilityError::corrupt(format!("invalid snapshot payload: {error}"))
    })?;
    if payload.identity != expected_identity {
        return Err(TeamDurabilityError::IdentityMismatch);
    }
    if payload.commit_generation == 0 {
        return Err(TeamDurabilityError::corrupt(
            "committed snapshot has the reserved generation zero",
        ));
    }
    payload.store.validate_durable(expected_identity)?;
    Ok(HydratedTeamSnapshot {
        commit_generation: payload.commit_generation,
        payload_checksum,
        store: payload.store,
    })
}

/// Validate one complete committed snapshot and return its stable read-side identity.
pub fn committed_snapshot_token(
    expected_identity: DurableTeamIdentity,
    encoded: &[u8],
) -> Result<CommittedSnapshotToken, TeamDurabilityError> {
    let hydrated = decode_snapshot(expected_identity, encoded)?;
    Ok(CommittedSnapshotToken {
        commit_generation: hydrated.commit_generation,
        payload_checksum: hydrated.payload_checksum,
    })
}

/// Validate a committed snapshot against its lineage and return its commit generation.
///
/// Concrete durable media use this at their compare-and-swap boundary so an intact but stale
/// snapshot cannot be overwritten merely because a file exists at the expected path.
pub fn committed_snapshot_generation(
    expected_identity: DurableTeamIdentity,
    encoded: &[u8],
) -> Result<u64, TeamDurabilityError> {
    Ok(committed_snapshot_token(expected_identity, encoded)?.commit_generation())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::availability::AvailabilitySnapshot;
    use crate::availability::ProducerAvailability;
    use crate::evidence::FactCategory;
    use crate::evidence::NotedObservation;
    use crate::handle::TeamMutationPrecondition;
    use crate::handle::TeamStateHandle;
    use crate::ids::TeamRevision;
    use crate::model::ParticipantRole;
    use crate::model::ProducerState;
    use crate::model::RootState;
    use crate::mutation::LifecycleChange;
    use crate::mutation::LifecycleRequest;
    use crate::mutation::LifecycleTarget;
    use crate::mutation::PublishRequest;
    use crate::mutation::PublishTarget;
    use crate::mutation::RetireRequest;
    use crate::mutation::Submission;
    use crate::mutation::TeamError;
    use std::sync::Arc;
    use std::sync::Mutex;

    #[derive(Clone)]
    struct FakeAuthority {
        identity: DurableTeamIdentity,
        owner_incarnation_id: Uuid,
        snapshot: Arc<Mutex<Option<Vec<u8>>>>,
        fail_next_commit: Arc<Mutex<Option<InjectedCommitFailure>>>,
        fail_next_read: Arc<Mutex<Option<TeamDurabilityError>>>,
    }

    #[derive(Clone)]
    enum InjectedCommitFailure {
        BeforeWrite(TeamDurabilityError),
        AfterWrite(TeamDurabilityError),
    }

    impl FakeAuthority {
        fn new(identity: DurableTeamIdentity) -> Self {
            Self {
                identity,
                owner_incarnation_id: Uuid::new_v4(),
                snapshot: Arc::new(Mutex::new(None)),
                fail_next_commit: Arc::new(Mutex::new(None)),
                fail_next_read: Arc::new(Mutex::new(None)),
            }
        }

        fn committed(&self) -> Option<Vec<u8>> {
            self.snapshot
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .clone()
        }

        fn replace_committed(&self, snapshot: Option<Vec<u8>>) {
            *self
                .snapshot
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) = snapshot;
        }

        fn fail_next_commit(&self, error: TeamDurabilityError) {
            *self
                .fail_next_commit
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) =
                Some(InjectedCommitFailure::BeforeWrite(error));
        }

        fn fail_next_commit_after_write(&self, error: TeamDurabilityError) {
            *self
                .fail_next_commit
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) =
                Some(InjectedCommitFailure::AfterWrite(error));
        }

        fn fail_next_read(&self, error: TeamDurabilityError) {
            *self
                .fail_next_read
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) = Some(error);
        }
    }

    impl TeamWriteAuthority for FakeAuthority {
        fn identity(&self) -> DurableTeamIdentity {
            self.identity
        }

        fn owner_incarnation_id(&self) -> Uuid {
            self.owner_incarnation_id
        }

        fn begin_write(&self) -> Result<Box<dyn TeamWritePermit>, TeamDurabilityError> {
            Ok(Box::new(FakeWritePermit {
                identity: self.identity,
                snapshot: Arc::clone(&self.snapshot),
                fail_next_commit: Arc::clone(&self.fail_next_commit),
                fail_next_read: Arc::clone(&self.fail_next_read),
            }))
        }

        fn begin_close(&self) -> TeamDurabilityFuture<'_, Box<dyn TeamClosePermit>> {
            Box::pin(async { Ok(Box::new(FakeClosePermit) as Box<dyn TeamClosePermit>) })
        }
    }

    struct FakeWritePermit {
        identity: DurableTeamIdentity,
        snapshot: Arc<Mutex<Option<Vec<u8>>>>,
        fail_next_commit: Arc<Mutex<Option<InjectedCommitFailure>>>,
        fail_next_read: Arc<Mutex<Option<TeamDurabilityError>>>,
    }

    impl TeamWritePermit for FakeWritePermit {
        fn read_snapshot(&mut self) -> Result<Option<Vec<u8>>, TeamDurabilityError> {
            if let Some(error) = self
                .fail_next_read
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take()
            {
                return Err(error);
            }
            Ok(self
                .snapshot
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .clone())
        }

        fn compare_and_swap(
            &mut self,
            expected_generation: u64,
            snapshot: Vec<u8>,
        ) -> Result<(), TeamDurabilityError> {
            let fail_after_write = match self
                .fail_next_commit
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .take()
            {
                Some(InjectedCommitFailure::BeforeWrite(error)) => return Err(error),
                Some(InjectedCommitFailure::AfterWrite(error)) => Some(error),
                None => None,
            };
            let mut committed = self
                .snapshot
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let current_generation = committed
                .as_deref()
                .map(|bytes| decode_snapshot(self.identity, bytes))
                .transpose()?
                .map(|hydrated| hydrated.commit_generation)
                .unwrap_or(0);
            if current_generation != expected_generation {
                return Err(TeamDurabilityError::conflict("test CAS mismatch"));
            }
            let next = decode_snapshot(self.identity, &snapshot)?;
            if next.commit_generation != expected_generation + 1 {
                return Err(TeamDurabilityError::corrupt(
                    "test snapshot generation does not advance by one",
                ));
            }
            *committed = Some(snapshot);
            if let Some(error) = fail_after_write {
                return Err(error);
            }
            Ok(())
        }
    }

    struct FakeClosePermit;

    impl TeamClosePermit for FakeClosePermit {
        fn abort(self: Box<Self>) -> TeamDurabilityFuture<'static, ()> {
            Box::pin(async { Ok(()) })
        }

        fn complete(self: Box<Self>) -> TeamDurabilityFuture<'static, ()> {
            Box::pin(async { Ok(()) })
        }
    }

    fn snapshot_fixture() -> (DurableTeamIdentity, TeamStore) {
        let root = ThreadId::default();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let mut store = TeamStore::new();
        assert!(store.register_participant(root, ParticipantRole::Root, "root".to_string()));
        (identity, store)
    }

    #[test]
    fn snapshot_round_trip_checks_identity_and_generation() {
        let (identity, store) = snapshot_fixture();
        let encoded = encode_snapshot(identity, 7, &store).expect("encode snapshot");
        let hydrated = decode_snapshot(identity, &encoded).expect("decode snapshot");

        assert_eq!(hydrated.commit_generation, 7);
        assert_eq!(hydrated.store.instance(), store.instance());
        assert_eq!(hydrated.store.participants(), store.participants());
    }

    #[test]
    fn committed_snapshot_token_is_stable_and_distinguishes_same_generation_payloads() {
        let (identity, mut store) = snapshot_fixture();
        let encoded = encode_snapshot(identity, 7, &store).expect("encode snapshot");
        let token = committed_snapshot_token(identity, &encoded).expect("validate snapshot");

        assert_eq!(token.commit_generation(), 7);
        assert_eq!(
            committed_snapshot_token(identity, &encoded).expect("validate the same snapshot"),
            token
        );

        assert!(store.register_participant(
            ThreadId::new(),
            ParticipantRole::Member,
            "member".to_string(),
        ));
        let different = encode_snapshot(identity, 7, &store).expect("encode different snapshot");
        let different_token =
            committed_snapshot_token(identity, &different).expect("validate different snapshot");

        assert_eq!(
            different_token.commit_generation(),
            token.commit_generation()
        );
        assert_ne!(different_token.payload_checksum(), token.payload_checksum());
    }

    #[test]
    fn committed_snapshot_token_fails_closed_before_returning_a_value() {
        let (identity, store) = snapshot_fixture();
        let mut corrupt = encode_snapshot(identity, 1, &store).expect("encode snapshot");
        let last = corrupt.last_mut().expect("payload byte");
        *last ^= 1;
        assert!(matches!(
            committed_snapshot_token(identity, &corrupt),
            Err(TeamDurabilityError::Corrupt { .. })
        ));

        let encoded = encode_snapshot(identity, 1, &store).expect("encode snapshot");
        let other_root = ThreadId::new();
        let other = DurableTeamIdentity::new(SessionId::from(other_root), other_root);
        assert_eq!(
            committed_snapshot_token(other, &encoded).err(),
            Some(TeamDurabilityError::IdentityMismatch)
        );
    }

    #[test]
    fn durable_state_comparison_ignores_map_order_and_pending_observations() {
        let (identity, mut store) = snapshot_fixture();
        let encoded = encode_snapshot(identity, 1, &store).expect("encode snapshot");
        let independently_hydrated = decode_snapshot(identity, &encoded)
            .expect("decode snapshot")
            .store;
        store.note_observation(
            identity.root_thread_id(),
            NotedObservation {
                item_id: "transient-item".to_string(),
                call_id: "transient-call".to_string(),
                category: FactCategory::ToolResultSuccess,
                tool: "test".to_string(),
            },
        );

        assert!(store.same_durable_state(&independently_hydrated));
    }

    #[test]
    fn read_only_refresh_rejects_different_state_at_same_generation() {
        let (identity, mut store) = snapshot_fixture();
        let committed = encode_snapshot(identity, 1, &store).expect("encode snapshot");
        let read_only = TeamStateHandle::from_committed_snapshot(identity, &committed)
            .expect("hydrate read-only Team");
        store.register_participant(
            ThreadId::new(),
            ParticipantRole::Member,
            "member".to_string(),
        );
        let conflicting = encode_snapshot(identity, 1, &store).expect("encode conflicting state");

        assert!(matches!(
            read_only.refresh_from_committed_snapshot(&conflicting),
            Err(TeamDurabilityError::Conflict { .. })
        ));
    }

    #[test]
    fn checksum_corruption_fails_closed() {
        let (identity, store) = snapshot_fixture();
        let mut encoded = encode_snapshot(identity, 1, &store).expect("encode snapshot");
        let last = encoded.last_mut().expect("payload byte");
        *last ^= 1;

        assert!(matches!(
            decode_snapshot(identity, &encoded),
            Err(TeamDurabilityError::Corrupt { .. })
        ));
    }

    #[test]
    fn wrong_lineage_fails_closed() {
        let (identity, store) = snapshot_fixture();
        let encoded = encode_snapshot(identity, 1, &store).expect("encode snapshot");
        let other_root = ThreadId::new();
        let other = DurableTeamIdentity::new(SessionId::from(other_root), other_root);

        assert_eq!(
            decode_snapshot(other, &encoded).err(),
            Some(TeamDurabilityError::IdentityMismatch)
        );
    }

    #[test]
    fn fresh_team_has_no_marker_until_root_registration() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");

        assert!(authority.committed().is_none());
        assert_eq!(
            handle.durability_status(),
            TeamDurabilityStatus::Writable {
                commit_generation: 0
            }
        );
        assert!(
            handle
                .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
                .expect("commit Root")
        );
        assert!(authority.committed().is_some());
        assert_eq!(
            handle.durability_status(),
            TeamDurabilityStatus::Writable {
                commit_generation: 1
            }
        );
    }

    #[test]
    fn lifecycle_at_snapshot_accepts_exact_proof_and_rejects_the_consumed_snapshot() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let published = handle
            .publish(
                root,
                &Submission {
                    based_on: handle.revision(),
                    request_id: "snapshot-lifecycle".to_string(),
                },
                PublishRequest {
                    target: PublishTarget::NewEvent {
                        title: "snapshot lifecycle".to_string(),
                    },
                    summary: "state before formal mutation".to_string(),
                    handoff: None,
                },
            )
            .expect("publish version");
        let precondition = TeamMutationPrecondition {
            instance: handle.instance(),
            revision: handle.revision(),
            commit_generation: 2,
        };
        let request = LifecycleRequest {
            targets: vec![LifecycleTarget {
                version_id: published.version_id,
                expected_producer_state: ProducerState::Open,
                expected_root_state: RootState::Tracking,
                change: LifecycleChange::SetRootState(RootState::Resolved),
            }],
        };

        let outcome = handle
            .update_lifecycle_at_snapshot_for_owner(
                root,
                authority.owner_incarnation_id(),
                precondition,
                request.clone(),
            )
            .expect("exact committed snapshot should mutate");
        assert!(outcome.changed);
        assert!(matches!(
            handle.update_lifecycle_at_snapshot(root, precondition, request),
            Err(TeamError::SnapshotConflict { .. })
        ));
    }

    #[test]
    fn lifecycle_at_snapshot_rejects_a_replaced_owner_incarnation() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let published = handle
            .publish(
                root,
                &Submission {
                    based_on: handle.revision(),
                    request_id: "owner-bound-lifecycle".to_string(),
                },
                PublishRequest {
                    target: PublishTarget::NewEvent {
                        title: "owner-bound lifecycle".to_string(),
                    },
                    summary: "reject replacement owner".to_string(),
                    handoff: None,
                },
            )
            .expect("publish version");
        let precondition = TeamMutationPrecondition {
            instance: handle.instance(),
            revision: handle.revision(),
            commit_generation: 2,
        };
        let request = LifecycleRequest {
            targets: vec![LifecycleTarget {
                version_id: published.version_id,
                expected_producer_state: ProducerState::Open,
                expected_root_state: RootState::Pending,
                change: LifecycleChange::SetRootState(RootState::Tracking),
            }],
        };

        assert_eq!(
            handle.update_lifecycle_at_snapshot_for_owner(
                root,
                Uuid::new_v4(),
                precondition,
                request,
            ),
            Err(TeamError::OwnerIncarnationConflict)
        );
    }

    #[tokio::test]
    async fn close_at_snapshot_rejects_a_commit_that_won_after_the_proof() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let precondition = TeamMutationPrecondition {
            instance: handle.instance(),
            revision: handle.revision(),
            commit_generation: 1,
        };
        handle
            .publish(
                root,
                &Submission {
                    based_on: handle.revision(),
                    request_id: "commit-before-close".to_string(),
                },
                PublishRequest {
                    target: PublishTarget::NewEvent {
                        title: "new fact".to_string(),
                    },
                    summary: "must survive stale close".to_string(),
                    handoff: None,
                },
            )
            .expect("new Team commit wins");

        assert!(matches!(
            handle
                .begin_close_at_snapshot(authority.owner_incarnation_id(), precondition)
                .await,
            Err(TeamDurabilityError::Domain(
                TeamError::SnapshotConflict { .. }
            ))
        ));
        handle
            .publish(
                root,
                &Submission {
                    based_on: handle.revision(),
                    request_id: "after-aborted-close".to_string(),
                },
                PublishRequest {
                    target: PublishTarget::NewEvent {
                        title: "retryable".to_string(),
                    },
                    summary: "owner remains writable".to_string(),
                    handoff: None,
                },
            )
            .expect("rejected close must leave the owner writable");
    }

    #[tokio::test]
    async fn close_at_snapshot_rejects_a_replaced_owner_incarnation() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let precondition = TeamMutationPrecondition {
            instance: handle.instance(),
            revision: handle.revision(),
            commit_generation: 1,
        };

        assert_eq!(
            handle
                .begin_close_at_snapshot(Uuid::new_v4(), precondition)
                .await
                .err(),
            Some(TeamDurabilityError::Domain(
                TeamError::OwnerIncarnationConflict
            ))
        );
    }

    #[test]
    fn durable_install_preserves_the_shared_handle() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let shared = TeamStateHandle::default();
        let original_instance = shared.instance();
        let replacement =
            TeamStateHandle::create_durable(authority.clone()).expect("create durable Team");
        let durable_instance = replacement.instance();

        shared
            .install_durable(replacement)
            .expect("install durable Team");
        assert_ne!(shared.instance(), original_instance);
        assert_eq!(shared.instance(), durable_instance);
        assert!(
            shared
                .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
                .expect("commit through installed Team")
        );
        assert!(authority.committed().is_some());
    }

    #[test]
    fn after_write_unknown_readback_commits_without_exposing_old_state() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        authority
            .fail_next_commit_after_write(TeamDurabilityError::unknown("injected after write"));

        assert!(
            handle
                .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
                .expect("read-back proves the candidate committed")
        );
        assert!(handle.participant(root).is_some());
        assert_eq!(
            handle.durability_status(),
            TeamDurabilityStatus::Writable {
                commit_generation: 1
            }
        );
        handle
            .ensure_readable()
            .expect("committed Team is readable");
    }

    #[test]
    fn before_write_unknown_readback_allows_exact_retry_from_generation_zero() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        authority.fail_next_commit(TeamDurabilityError::unknown("injected before write"));

        assert!(matches!(
            handle.register_durable_participant(root, ParticipantRole::Root, "root".to_string()),
            Err(TeamError::Durability { .. })
        ));
        assert_eq!(
            handle.durability_status(),
            TeamDurabilityStatus::Writable {
                commit_generation: 0
            }
        );
        assert!(
            handle
                .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
                .expect("retry initial registration")
        );
    }

    #[test]
    fn indeterminate_initial_commit_keeps_the_owner_handle_reconcilable() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        authority
            .fail_next_commit_after_write(TeamDurabilityError::unknown("injected after write"));
        authority.fail_next_read(TeamDurabilityError::unavailable(
            "injected read-back failure",
        ));

        assert!(matches!(
            handle.register_durable_participant(root, ParticipantRole::Root, "root".to_string()),
            Err(TeamError::Durability { .. })
        ));
        assert!(matches!(
            handle.durability_status(),
            TeamDurabilityStatus::Unknown {
                expected_generation: 0
            }
        ));
        authority.fail_next_read(TeamDurabilityError::unavailable(
            "injected first reconcile failure",
        ));
        assert!(matches!(
            handle.ensure_readable_or_reconcile(),
            Err(TeamDurabilityError::Unavailable { .. })
        ));
        assert!(matches!(
            handle.durability_status(),
            TeamDurabilityStatus::Unknown {
                expected_generation: 0
            }
        ));
        authority.fail_next_read(TeamDurabilityError::IdentityMismatch);
        assert!(matches!(
            handle.ensure_readable_or_reconcile(),
            Err(TeamDurabilityError::IdentityMismatch)
        ));
        assert!(matches!(
            handle.durability_status(),
            TeamDurabilityStatus::Unknown {
                expected_generation: 0
            }
        ));
        handle
            .ensure_readable_or_reconcile()
            .expect("same owner reconciles once the typed marker is restored");
        assert_eq!(
            handle.durability_status(),
            TeamDurabilityStatus::Writable {
                commit_generation: 1
            }
        );
        assert!(
            !handle
                .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
                .expect("exact retry deduplicates after reconciliation")
        );
    }

    #[test]
    fn product_retry_reconciles_a_transient_failure_and_commits() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let submission = Submission {
            based_on: handle.revision(),
            request_id: "retry-after-unavailable".to_string(),
        };
        let request = PublishRequest {
            target: PublishTarget::NewEvent {
                title: "transient failure".to_string(),
            },
            summary: "commit on retry".to_string(),
            handoff: None,
        };
        authority.fail_next_commit(TeamDurabilityError::unavailable("injected before write"));

        assert!(matches!(
            handle.publish(root, &submission, request.clone()),
            Err(TeamError::Durability { .. })
        ));
        assert!(matches!(
            handle.durability_status(),
            TeamDurabilityStatus::Unavailable {
                last_known_generation: 1
            }
        ));

        handle
            .ensure_readable_or_reconcile()
            .expect("restored medium should reconcile the original owner");
        let outcome = handle
            .publish(root, &submission, request)
            .expect("original owner should commit after reconciliation");
        assert!(!outcome.deduplicated);
        assert_eq!(handle.snapshot_for(root).expect("snapshot").events.len(), 1);
    }

    #[test]
    fn product_retry_reconciles_an_indeterminate_success_and_deduplicates() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let submission = Submission {
            based_on: handle.revision(),
            request_id: "retry-after-unknown".to_string(),
        };
        let request = PublishRequest {
            target: PublishTarget::NewEvent {
                title: "unknown result".to_string(),
            },
            summary: "already committed".to_string(),
            handoff: None,
        };
        authority
            .fail_next_commit_after_write(TeamDurabilityError::unknown("injected after write"));

        let first = handle
            .publish(root, &submission, request.clone())
            .expect("read-back proves the publish committed");
        assert!(!first.deduplicated);
        assert_eq!(
            handle.durability_status(),
            TeamDurabilityStatus::Writable {
                commit_generation: 2
            }
        );
        let outcome = handle
            .publish(root, &submission, request)
            .expect("same product retry should return the committed outcome");
        assert!(outcome.deduplicated);
        assert_eq!(handle.snapshot_for(root).expect("snapshot").events.len(), 1);
    }

    #[test]
    fn reconciliation_preserves_unrelated_pending_observations() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        for item in ["item-a", "item-b"] {
            handle
                .note_durable_observation(
                    root,
                    NotedObservation {
                        item_id: item.to_string(),
                        call_id: format!("call-{item}"),
                        category: FactCategory::ToolResultSuccess,
                        tool: "test".to_string(),
                    },
                )
                .expect("note observation");
        }
        authority
            .fail_next_commit_after_write(TeamDurabilityError::unknown("injected after write"));
        authority.fail_next_read(TeamDurabilityError::unavailable(
            "injected read-back failure",
        ));

        assert!(matches!(
            handle.confirm_durable_observation(root, "item-a"),
            Err(TeamError::Durability { .. })
        ));
        handle
            .reconcile_durable()
            .expect("reconcile committed confirmation");
        assert_eq!(
            handle
                .confirm_durable_observation(root, "item-a")
                .expect("recheck committed observation"),
            None,
            "the committed observation must not be resurrected"
        );
        assert!(
            handle
                .confirm_durable_observation(root, "item-b")
                .expect("confirm unrelated pending observation")
                .is_some(),
            "an unrelated pending observation must survive reconciliation"
        );
    }

    #[test]
    fn before_write_reconciliation_keeps_all_pending_observations_retryable() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        for item in ["item-a", "item-b"] {
            handle
                .note_durable_observation(
                    root,
                    NotedObservation {
                        item_id: item.to_string(),
                        call_id: format!("call-{item}"),
                        category: FactCategory::ToolResultSuccess,
                        tool: "test".to_string(),
                    },
                )
                .expect("note observation");
        }
        authority.fail_next_commit(TeamDurabilityError::unavailable("injected before write"));

        assert!(matches!(
            handle.confirm_durable_observation(root, "item-a"),
            Err(TeamError::Durability { .. })
        ));
        handle
            .ensure_readable_or_reconcile()
            .expect("reconcile unchanged committed generation");
        assert!(
            handle
                .confirm_durable_observation(root, "item-a")
                .expect("retry first pending observation")
                .is_some()
        );
        assert!(
            handle
                .confirm_durable_observation(root, "item-b")
                .expect("confirm unrelated pending observation")
                .is_some()
        );
    }

    #[test]
    fn retirement_retry_survives_later_root_state_changes() {
        let root = ThreadId::new();
        let member = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        handle
            .register_durable_participant(member, ParticipantRole::Member, "member".to_string())
            .expect("register member");
        let published = handle
            .publish(
                member,
                &Submission {
                    based_on: TeamRevision::INITIAL,
                    request_id: "member-publish".to_string(),
                },
                PublishRequest {
                    target: PublishTarget::NewEvent {
                        title: "retire me".to_string(),
                    },
                    summary: "member became unavailable".to_string(),
                    handoff: None,
                },
            )
            .expect("publish member version");
        let availability =
            AvailabilitySnapshot::from_entries(vec![(member, ProducerAvailability::Unavailable)]);
        let request = RetireRequest {
            version_id: published.version_id,
            expected_producer_state: ProducerState::Open,
            expected_root_state: RootState::Pending,
            expected_availability: ProducerAvailability::Unavailable,
            expected_availability_epoch: availability.epoch,
            reason: "member is gone".to_string(),
        };
        let submission = Submission {
            based_on: published.revision,
            request_id: "root-retire".to_string(),
        };
        let retired = handle
            .retire(root, &submission, request.clone(), &availability, || {
                availability.epoch
            })
            .expect("retire member version");
        handle
            .update_lifecycle(
                root,
                LifecycleRequest {
                    targets: vec![LifecycleTarget {
                        version_id: published.version_id,
                        expected_producer_state: ProducerState::Open,
                        expected_root_state: RootState::Pending,
                        change: LifecycleChange::SetRootState(RootState::Resolved),
                    }],
                },
            )
            .expect("resolve retired version");

        let resumed = TeamStateHandle::resume_durable(authority).expect("resume durable Team");
        let retry = resumed
            .retire(root, &submission, request, &availability, || {
                availability.epoch
            })
            .expect("retry retirement after root-state change");
        assert!(retry.deduplicated);
        assert_eq!(retry.revision, retired.revision);
    }

    #[test]
    fn committed_publish_hydrates_for_owner_and_read_only_consumers() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let outcome = handle
            .publish(
                root,
                &Submission {
                    based_on: TeamRevision::INITIAL,
                    request_id: "publish-1".to_string(),
                },
                PublishRequest {
                    target: PublishTarget::NewEvent {
                        title: "durable event".to_string(),
                    },
                    summary: "committed".to_string(),
                    handoff: None,
                },
            )
            .expect("publish durably");

        let resumed = TeamStateHandle::resume_durable(authority.clone()).expect("resume owner");
        assert_eq!(
            resumed
                .snapshot_for(root)
                .expect("owner snapshot")
                .events
                .len(),
            1
        );
        let encoded = authority.committed().expect("committed snapshot");
        let read_only = TeamStateHandle::from_committed_snapshot(identity, &encoded)
            .expect("hydrate read-only");
        assert_eq!(
            read_only
                .history(
                    root,
                    &crate::view::HistoryQuery {
                        event_id: Some(outcome.event_id),
                        before: None,
                        limit: None,
                    },
                )
                .expect("read history")
                .events
                .len(),
            1
        );
        assert!(matches!(
            read_only.register_durable_participant(
                ThreadId::new(),
                ParticipantRole::Member,
                "member".to_string(),
            ),
            Err(TeamError::Durability { .. })
        ));
    }

    #[test]
    fn resumed_root_registration_is_strictly_idempotent() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let resumed = TeamStateHandle::resume_durable(authority).expect("resume Team");

        assert!(
            !resumed
                .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
                .expect("same registration is a no-op")
        );
        assert!(matches!(
            resumed.register_durable_participant(
                root,
                ParticipantRole::Root,
                "renamed".to_string(),
            ),
            Err(TeamError::Durability { .. })
        ));
    }

    #[test]
    fn an_idempotent_success_revalidates_the_committed_snapshot() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let submission = Submission {
            based_on: handle.revision(),
            request_id: "stable-publish".to_string(),
        };
        let request = PublishRequest {
            target: PublishTarget::NewEvent {
                title: "stable".to_string(),
            },
            summary: "committed".to_string(),
            handoff: None,
        };
        handle
            .publish(root, &submission, request.clone())
            .expect("first publish");
        authority.replace_committed(None);

        assert!(matches!(
            handle.publish(root, &submission, request),
            Err(TeamError::Durability { .. })
        ));
        assert!(matches!(
            handle.durability_status(),
            TeamDurabilityStatus::Unavailable { .. }
        ));
    }

    #[test]
    fn reconciliation_accepts_only_the_known_generation_or_one_indeterminate_commit() {
        let root = ThreadId::new();
        let identity = DurableTeamIdentity::new(SessionId::from(root), root);
        let authority = Arc::new(FakeAuthority::new(identity));
        let handle = TeamStateHandle::create_durable(authority.clone()).expect("create Team");
        handle
            .register_durable_participant(root, ParticipantRole::Root, "root".to_string())
            .expect("register Root");
        let committed = authority.committed().expect("committed Root snapshot");
        let hydrated = decode_snapshot(identity, &committed).expect("decode Root snapshot");
        authority.replace_committed(Some(
            encode_snapshot(identity, 3, &hydrated.store).expect("encode jumped generation"),
        ));

        let error = handle
            .reconcile_durable()
            .expect_err("an unexplained generation jump must fail closed");
        assert!(matches!(error, TeamDurabilityError::Conflict { .. }));
        assert!(matches!(
            handle.durability_status(),
            TeamDurabilityStatus::Unavailable {
                last_known_generation: 1
            }
        ));
    }
}
