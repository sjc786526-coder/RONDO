//! The shared front door to a team instance.
//!
//! One handle exists per live root tree and is cloned into every member of that tree, which is
//! what makes the state canonical: there is no second copy to reconcile, and nothing about it
//! depends on which members happen to be loaded right now.

use crate::availability::AvailabilitySnapshot;
use crate::durable::DurableTeamIdentity;
use crate::durable::TeamClosePermit;
use crate::durable::TeamDurabilityError;
use crate::durable::TeamDurabilityStatus;
use crate::durable::TeamWriteAuthority;
use crate::durable::TeamWritePermit;
use crate::durable::decode_snapshot;
use crate::durable::encode_snapshot;
use crate::evidence::FactView;
use crate::evidence::NotedObservation;
use crate::ids::FactId;
use crate::ids::RouteId;
use crate::ids::TeamInstanceId;
use crate::ids::TeamRevision;
use crate::model::Participant;
use crate::model::ParticipantRole;
use crate::mutation::DeliveryOutcome;
use crate::mutation::DeliveryResult;
use crate::mutation::EndAssignmentOutcome;
use crate::mutation::LifecycleOutcome;
use crate::mutation::LifecycleRequest;
use crate::mutation::PublishOutcome;
use crate::mutation::PublishRequest;
use crate::mutation::RetireOutcome;
use crate::mutation::RetireRequest;
use crate::mutation::RouteDispatch;
use crate::mutation::RouteOutcome;
use crate::mutation::RouteRequest;
use crate::mutation::Submission;
use crate::mutation::TeamError;
use crate::observe::ChangeLogPage;
use crate::observe::DumpCursor;
use crate::observe::ObserveQuery;
use crate::observe::TeamDumpPage;
use crate::publish::PreparedPublishHistory;
use crate::publish::PublishPreparation;
use crate::store::TeamStore;
use crate::view::HistoryPage;
use crate::view::HistoryQuery;
use crate::view::TeamSnapshot;
use codex_protocol::ThreadId;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::RwLock;
use tokio::sync::watch;

pub struct TeamStateHandle {
    store: Mutex<TeamStore>,
    /// Bumped on every wake-worthy change so waiters re-check their own ledger entry. The value
    /// itself carries no meaning; the per-participant ledger inside the store does.
    change_tx: watch::Sender<u64>,
    durable: RwLock<Option<Arc<DurableRuntime>>>,
}

struct DurableRuntime {
    identity: DurableTeamIdentity,
    authority: Option<Arc<dyn TeamWriteAuthority>>,
    mutation_gate: Mutex<()>,
    status: Mutex<TeamDurabilityStatus>,
}

impl Default for TeamStateHandle {
    fn default() -> Self {
        Self {
            store: Mutex::new(TeamStore::new()),
            change_tx: watch::Sender::new(0),
            durable: RwLock::new(None),
        }
    }
}

impl TeamStateHandle {
    fn from_parts(store: TeamStore, durable: Option<DurableRuntime>) -> Self {
        Self {
            store: Mutex::new(store),
            change_tx: watch::Sender::new(0),
            durable: RwLock::new(durable.map(Arc::new)),
        }
    }

    fn durable_runtime(&self) -> Option<Arc<DurableRuntime>> {
        self.durable
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    /// Replace the initial in-memory placeholder with a proven durable Team while preserving the
    /// stable handle shared by every control clone. Root activation calls this before admitting any
    /// child, so no runtime can observe a half-installed Team.
    pub fn install_durable(&self, replacement: Self) -> Result<(), TeamDurabilityError> {
        let replacement_runtime = replacement
            .durable
            .into_inner()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .ok_or_else(|| {
                TeamDurabilityError::conflict("cannot install an in-memory Team as durable")
            })?;
        let replacement_store = replacement
            .store
            .into_inner()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let mut runtime = self
            .durable
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if runtime.is_some() {
            return Err(TeamDurabilityError::conflict(
                "a durable Team is already installed for this root tree",
            ));
        }
        self.with_store(|store| *store = replacement_store);
        *runtime = Some(replacement_runtime);
        Ok(())
    }

    fn with_store<R>(&self, f: impl FnOnce(&mut TeamStore) -> R) -> R {
        // A poisoned team mutex means a previous mutation panicked mid-commit. Recovering the
        // guard is still the right call here: the store's mutations validate before they write,
        // so the state a panicking caller leaves behind is the pre-mutation state.
        let mut store = self.store.lock().unwrap_or_else(|poisoned| {
            tracing::error!("team state mutex was poisoned; continuing with recovered state");
            poisoned.into_inner()
        });
        f(&mut store)
    }

    /// Open a fresh durable Team without publishing a marker yet.
    pub fn create_durable(
        authority: Arc<dyn TeamWriteAuthority>,
    ) -> Result<Self, TeamDurabilityError> {
        let identity = authority.identity();
        let mut permit = authority.begin_write()?;
        if permit.read_snapshot()?.is_some() {
            return Err(TeamDurabilityError::conflict(
                "a committed Team snapshot already exists for this lineage",
            ));
        }
        // Initialization after this point may still fail. Generation zero intentionally has no
        // marker: the authoritative Root registration commits the first snapshot only at the
        // caller's final successful activation boundary.
        let store = TeamStore::new();
        let runtime = DurableRuntime {
            identity,
            authority: Some(authority),
            mutation_gate: Mutex::new(()),
            status: Mutex::new(TeamDurabilityStatus::Writable {
                commit_generation: 0,
            }),
        };
        Ok(Self::from_parts(store, Some(runtime)))
    }

    /// Resume the last complete committed Team while holding current Root writer authority.
    pub fn resume_durable(
        authority: Arc<dyn TeamWriteAuthority>,
    ) -> Result<Self, TeamDurabilityError> {
        let identity = authority.identity();
        let mut permit = authority.begin_write()?;
        let encoded = permit.read_snapshot()?.ok_or_else(|| {
            TeamDurabilityError::unavailable("no committed Team snapshot exists for this lineage")
        })?;
        let hydrated = decode_snapshot(identity, &encoded)?;
        let runtime = DurableRuntime {
            identity,
            authority: Some(authority),
            mutation_gate: Mutex::new(()),
            status: Mutex::new(TeamDurabilityStatus::Writable {
                commit_generation: hydrated.commit_generation,
            }),
        };
        Ok(Self::from_parts(hydrated.store, Some(runtime)))
    }

    /// Hydrate the canonical committed blob without acquiring mutation authority.
    ///
    /// This is the only non-owner constructor: it always returns a read-only handle and validates
    /// the same checksum, lineage, graph, counters, and retry/wake invariants as owner resume.
    pub fn from_committed_snapshot(
        identity: DurableTeamIdentity,
        encoded: &[u8],
    ) -> Result<Self, TeamDurabilityError> {
        let hydrated = decode_snapshot(identity, encoded)?;
        let runtime = DurableRuntime {
            identity,
            authority: None,
            mutation_gate: Mutex::new(()),
            status: Mutex::new(TeamDurabilityStatus::ReadOnly {
                commit_generation: hydrated.commit_generation,
            }),
        };
        Ok(Self::from_parts(hydrated.store, Some(runtime)))
    }

    /// Replace a non-owner view with a newer blob read from the same canonical snapshot medium.
    pub fn refresh_from_committed_snapshot(
        &self,
        encoded: &[u8],
    ) -> Result<(), TeamDurabilityError> {
        let runtime = self
            .durable_runtime()
            .ok_or(TeamDurabilityError::ReadOnly)?;
        if runtime.authority.is_some() {
            return Err(TeamDurabilityError::conflict(
                "owner handles reconcile through their write permit",
            ));
        }
        let _gate = runtime
            .mutation_gate
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let hydrated = decode_snapshot(runtime.identity, encoded)?;
        let current_generation = match self.durability_status() {
            TeamDurabilityStatus::ReadOnly { commit_generation } => commit_generation,
            _ => 0,
        };
        if hydrated.commit_generation < current_generation {
            return Err(TeamDurabilityError::conflict(
                "committed Team snapshot generation moved backwards",
            ));
        }
        if hydrated.commit_generation == current_generation {
            let same_state = self.with_store(|store| store.same_durable_state(&hydrated.store));
            if !same_state {
                return Err(TeamDurabilityError::conflict(
                    "durable Team state changed without advancing its generation",
                ));
            }
            return Ok(());
        }
        self.with_store(|store| *store = hydrated.store);
        *runtime
            .status
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = TeamDurabilityStatus::ReadOnly {
            commit_generation: hydrated.commit_generation,
        };
        Ok(())
    }

    /// Reconcile an owner after an unavailable or indeterminate commit by reading under a fresh
    /// Root write permit. No mutation is accepted until this succeeds.
    pub fn reconcile_durable(&self) -> Result<(), TeamDurabilityError> {
        let runtime = self.durable_runtime().ok_or_else(|| {
            TeamDurabilityError::conflict("an in-memory Team has no durable snapshot")
        })?;
        let authority = runtime
            .authority
            .as_ref()
            .ok_or(TeamDurabilityError::ReadOnly)?;
        let _gate = runtime
            .mutation_gate
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        // Capture the state only after serializing with mutations and other reconciliation. A
        // caller that observed Unknown outside this gate may arrive after another caller has
        // already reconciled and continued; using that stale generation would reject valid state.
        let previous_status = *runtime
            .status
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let last_known_generation = match previous_status {
            TeamDurabilityStatus::Writable { commit_generation }
            | TeamDurabilityStatus::ReadOnly { commit_generation } => commit_generation,
            TeamDurabilityStatus::Unknown {
                expected_generation,
            } => expected_generation,
            TeamDurabilityStatus::Unavailable {
                last_known_generation,
            } => last_known_generation,
            TeamDurabilityStatus::InMemory => unreachable!("durable runtime has durable status"),
        };
        let mut permit = match authority.begin_write() {
            Ok(permit) => permit,
            Err(error) => {
                Self::mark_durability_failure(&runtime, last_known_generation, &error);
                return Err(error);
            }
        };
        let reconciled = (|| {
            let Some(encoded) = permit.read_snapshot()? else {
                if last_known_generation == 0
                    && matches!(
                        previous_status,
                        TeamDurabilityStatus::Unknown { .. }
                            | TeamDurabilityStatus::Unavailable { .. }
                            | TeamDurabilityStatus::Writable { .. }
                    )
                {
                    return Ok(None);
                }
                return Err(TeamDurabilityError::unavailable(
                    "the committed Team snapshot disappeared",
                ));
            };
            let hydrated = decode_snapshot(runtime.identity, &encoded)?;
            let generation_is_allowed = match previous_status {
                TeamDurabilityStatus::Unknown {
                    expected_generation,
                } => {
                    hydrated.commit_generation == expected_generation
                        || expected_generation
                            .checked_add(1)
                            .is_some_and(|next| hydrated.commit_generation == next)
                }
                TeamDurabilityStatus::Writable { commit_generation }
                | TeamDurabilityStatus::ReadOnly { commit_generation } => {
                    hydrated.commit_generation == commit_generation
                }
                TeamDurabilityStatus::Unavailable {
                    last_known_generation,
                } => hydrated.commit_generation == last_known_generation,
                TeamDurabilityStatus::InMemory => {
                    unreachable!("durable runtime has durable status")
                }
            };
            if !generation_is_allowed {
                return Err(TeamDurabilityError::conflict(format!(
                    "durable Team reconciliation found unexpected generation {} after {}",
                    hydrated.commit_generation, last_known_generation
                )));
            }
            if hydrated.commit_generation == last_known_generation {
                let same_state = self.with_store(|store| store.same_durable_state(&hydrated.store));
                if !same_state {
                    return Err(TeamDurabilityError::conflict(
                        "durable Team state changed without advancing its generation",
                    ));
                }
            }
            Ok(Some(hydrated))
        })();
        let hydrated = match reconciled {
            Ok(hydrated) => hydrated,
            Err(error) => {
                Self::mark_durability_failure(&runtime, last_known_generation, &error);
                return Err(error);
            }
        };
        if let Some(hydrated) = hydrated {
            self.with_store(|store| {
                if hydrated.commit_generation != last_known_generation {
                    let mut committed = hydrated.store;
                    committed.restore_uncommitted_observations_from(store);
                    *store = committed;
                }
            });
            *runtime
                .status
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) =
                TeamDurabilityStatus::Writable {
                    commit_generation: hydrated.commit_generation,
                };
        } else {
            *runtime
                .status
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner) =
                TeamDurabilityStatus::Writable {
                    commit_generation: 0,
                };
        }
        Ok(())
    }

    pub fn durability_status(&self) -> TeamDurabilityStatus {
        let Some(runtime) = self.durable_runtime() else {
            return TeamDurabilityStatus::InMemory;
        };
        *runtime
            .status
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    pub fn durable_identity(&self) -> Option<DurableTeamIdentity> {
        self.durable_runtime().map(|runtime| runtime.identity)
    }

    /// Gate every product read that claims to represent committed Team state.
    pub fn ensure_readable(&self) -> Result<(), TeamDurabilityError> {
        match self.durability_status() {
            TeamDurabilityStatus::InMemory
            | TeamDurabilityStatus::Writable { .. }
            | TeamDurabilityStatus::ReadOnly { .. } => Ok(()),
            TeamDurabilityStatus::Unknown { .. } => Err(TeamDurabilityError::unknown(
                "the last Team commit must be reconciled before reading",
            )),
            TeamDurabilityStatus::Unavailable { .. } => Err(TeamDurabilityError::unavailable(
                "Team durability must be reconciled before reading",
            )),
        }
    }

    /// Restore a live owner's committed view after a transient or indeterminate storage failure,
    /// then prove that reads are safe. Read-only handles never enter reconciliation because they
    /// carry no writer authority; they remain limited to their validated committed snapshot.
    pub fn ensure_readable_or_reconcile(&self) -> Result<(), TeamDurabilityError> {
        if matches!(
            self.durability_status(),
            TeamDurabilityStatus::Unknown { .. } | TeamDurabilityStatus::Unavailable { .. }
        ) {
            self.reconcile_durable()?;
        }
        if matches!(
            self.durability_status(),
            TeamDurabilityStatus::Writable { .. }
        ) {
            let runtime = self.durable_runtime().ok_or_else(|| {
                TeamDurabilityError::conflict("writable Team has no durable runtime")
            })?;
            let _gate = runtime
                .mutation_gate
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner);
            let TeamDurabilityStatus::Writable { commit_generation } = self.durability_status()
            else {
                return self.ensure_readable();
            };
            let authority = runtime
                .authority
                .as_ref()
                .ok_or(TeamDurabilityError::ReadOnly)?;
            let mut permit = authority.begin_write().inspect_err(|error| {
                Self::mark_durability_failure(&runtime, commit_generation, error);
            })?;
            let current = self.with_store(|store| store.clone());
            if let Err(error) =
                Self::verify_committed_state(&runtime, permit.as_mut(), commit_generation, &current)
            {
                Self::mark_durability_failure(&runtime, commit_generation, &error);
                return Err(error);
            }
        }
        self.ensure_readable()
    }

    /// Enter the minimal close barrier. The returned permit remains the caller's responsibility:
    /// abort it if shutdown fails, or complete it after the final durable Team flush and thread
    /// writer close have succeeded.
    pub async fn begin_close(&self) -> Result<Box<dyn TeamClosePermit>, TeamDurabilityError> {
        self.ensure_readable_or_reconcile()?;
        let runtime = self.durable_runtime().ok_or_else(|| {
            TeamDurabilityError::conflict("an in-memory Team has no durable close barrier")
        })?;
        let authority = runtime
            .authority
            .as_ref()
            .ok_or(TeamDurabilityError::ReadOnly)?;
        match self.durability_status() {
            TeamDurabilityStatus::Writable { .. } => authority.begin_close().await,
            TeamDurabilityStatus::ReadOnly { .. } => Err(TeamDurabilityError::ReadOnly),
            TeamDurabilityStatus::Unknown { .. } => Err(TeamDurabilityError::unknown(
                "reconcile the last Team commit before close",
            )),
            TeamDurabilityStatus::Unavailable { .. } => Err(TeamDurabilityError::unavailable(
                "reconcile Team durability before close",
            )),
            TeamDurabilityStatus::InMemory => unreachable!("durable runtime has durable status"),
        }
    }

    fn mark_durability_failure(
        runtime: &DurableRuntime,
        expected_generation: u64,
        error: &TeamDurabilityError,
    ) {
        let mut status = runtime
            .status
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let next = match (*status, error) {
            // No failed read can answer whether the earlier unknown CAS committed generation
            // N+1. That includes a temporarily mismatched or unsupported typed Root marker: until
            // a snapshot is successfully read and judged, preserve the N/N+1 recovery window.
            (
                TeamDurabilityStatus::Unknown {
                    expected_generation,
                },
                _,
            ) => TeamDurabilityStatus::Unknown {
                expected_generation,
            },
            (_, TeamDurabilityError::Unknown { .. }) => TeamDurabilityStatus::Unknown {
                expected_generation,
            },
            (_, TeamDurabilityError::ReadOnly) => TeamDurabilityStatus::ReadOnly {
                commit_generation: expected_generation,
            },
            _ => TeamDurabilityStatus::Unavailable {
                last_known_generation: expected_generation,
            },
        };
        *status = next;
    }

    fn verify_committed_state(
        runtime: &DurableRuntime,
        permit: &mut dyn TeamWritePermit,
        expected_generation: u64,
        expected_store: &TeamStore,
    ) -> Result<(), TeamDurabilityError> {
        let committed = permit.read_snapshot()?;
        if expected_generation == 0 {
            return if committed.is_none() {
                Ok(())
            } else {
                Err(TeamDurabilityError::conflict(
                    "durable Team marker appeared before the initial commit",
                ))
            };
        }
        let encoded = committed.ok_or_else(|| {
            TeamDurabilityError::unavailable("the committed Team snapshot disappeared")
        })?;
        let hydrated = decode_snapshot(runtime.identity, &encoded)?;
        if hydrated.commit_generation != expected_generation {
            return Err(TeamDurabilityError::conflict(format!(
                "durable Team generation changed: expected {expected_generation}, found {}",
                hydrated.commit_generation
            )));
        }
        if !hydrated.store.same_durable_state(expected_store) {
            return Err(TeamDurabilityError::conflict(
                "durable Team state changed without advancing its generation",
            ));
        }
        Ok(())
    }

    fn durable_mutate<R>(
        &self,
        notify: bool,
        mutate: impl FnOnce(&mut TeamStore) -> Result<R, TeamDurabilityError>,
    ) -> Result<R, TeamDurabilityError> {
        let runtime = self.durable_runtime().ok_or_else(|| {
            TeamDurabilityError::conflict("this Team uses the in-memory mutation path")
        })?;
        let authority = runtime
            .authority
            .as_ref()
            .ok_or(TeamDurabilityError::ReadOnly)?;
        let _gate = runtime
            .mutation_gate
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let expected_generation = match self.durability_status() {
            TeamDurabilityStatus::Writable { commit_generation } => commit_generation,
            TeamDurabilityStatus::ReadOnly { .. } => return Err(TeamDurabilityError::ReadOnly),
            TeamDurabilityStatus::Unknown { .. } => {
                return Err(TeamDurabilityError::unknown(
                    "the previous Team commit must be reconciled",
                ));
            }
            TeamDurabilityStatus::Unavailable { .. } => {
                return Err(TeamDurabilityError::unavailable(
                    "Team durability must be reconciled",
                ));
            }
            TeamDurabilityStatus::InMemory => unreachable!("durable runtime has durable status"),
        };

        // Root authority begins before the candidate is cloned or mutated and remains in this
        // stack frame through install, notification, and construction of the success result.
        let mut permit = match authority.begin_write() {
            Ok(permit) => permit,
            Err(error) => {
                Self::mark_durability_failure(&runtime, expected_generation, &error);
                return Err(error);
            }
        };

        let current = self.with_store(|store| store.clone());
        let revision_before = current.revision();
        let mut candidate = current.clone();
        let result = mutate(&mut candidate)?;
        if current.same_durable_state(&candidate) {
            if let Err(error) = Self::verify_committed_state(
                &runtime,
                permit.as_mut(),
                expected_generation,
                &current,
            ) {
                Self::mark_durability_failure(&runtime, expected_generation, &error);
                return Err(error);
            }
            return Ok(result);
        }

        let next_generation = expected_generation
            .checked_add(1)
            .ok_or(TeamDurabilityError::GenerationOverflow)?;
        let snapshot = encode_snapshot(runtime.identity, next_generation, &candidate)?;
        if let Err(error) = permit.compare_and_swap(expected_generation, snapshot) {
            if !matches!(error, TeamDurabilityError::Unknown { .. }) {
                Self::mark_durability_failure(&runtime, expected_generation, &error);
                return Err(error);
            }
            let read_back = permit.read_snapshot();
            match read_back {
                Ok(Some(encoded)) => {
                    let hydrated = match decode_snapshot(runtime.identity, &encoded) {
                        Ok(hydrated) => hydrated,
                        Err(read_error) => {
                            Self::mark_durability_failure(
                                &runtime,
                                expected_generation,
                                &read_error,
                            );
                            return Err(read_error);
                        }
                    };
                    if hydrated.commit_generation == next_generation
                        && hydrated.store.same_durable_state(&candidate)
                    {
                        let revision_changed = candidate.revision() != revision_before;
                        self.with_store(|store| *store = candidate);
                        *runtime
                            .status
                            .lock()
                            .unwrap_or_else(std::sync::PoisonError::into_inner) =
                            TeamDurabilityStatus::Writable {
                                commit_generation: next_generation,
                            };
                        if notify && revision_changed {
                            self.notify_change();
                        }
                        return Ok(result);
                    }
                    if hydrated.commit_generation == expected_generation
                        && hydrated.store.same_durable_state(&current)
                    {
                        *runtime
                            .status
                            .lock()
                            .unwrap_or_else(std::sync::PoisonError::into_inner) =
                            TeamDurabilityStatus::Writable {
                                commit_generation: expected_generation,
                            };
                        return Err(error);
                    }
                    let conflict = TeamDurabilityError::conflict(
                        "indeterminate Team commit read back an unexpected generation or state",
                    );
                    Self::mark_durability_failure(&runtime, expected_generation, &conflict);
                    return Err(conflict);
                }
                Ok(None) if expected_generation == 0 => {
                    *runtime
                        .status
                        .lock()
                        .unwrap_or_else(std::sync::PoisonError::into_inner) =
                        TeamDurabilityStatus::Writable {
                            commit_generation: 0,
                        };
                    return Err(error);
                }
                Ok(None) | Err(_) => {
                    Self::mark_durability_failure(&runtime, expected_generation, &error);
                    return Err(error);
                }
            }
        }

        let revision_changed = candidate.revision() != revision_before;
        self.with_store(|store| *store = candidate);
        *runtime
            .status
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner) = TeamDurabilityStatus::Writable {
            commit_generation: next_generation,
        };
        if notify && revision_changed {
            self.notify_change();
        }
        // `permit` is deliberately still live here. It drops only as this function returns the
        // success, preserving one continuous Root authority interval for the whole mutation.
        Ok(result)
    }

    pub fn instance(&self) -> TeamInstanceId {
        self.with_store(|store| store.instance())
    }

    pub fn revision(&self) -> TeamRevision {
        self.with_store(|store| store.revision())
    }

    /// Register a participant derived from authoritative session identity.
    ///
    /// Idempotent, so a member that is unloaded and reloaded in the same live root tree keeps its
    /// instance, role and everything it authored.
    pub fn register_participant(
        &self,
        thread_id: ThreadId,
        role: ParticipantRole,
        label: String,
    ) -> bool {
        if self.durable_runtime().is_some() {
            match self.register_durable_participant(thread_id, role, label) {
                Ok(created) => created,
                Err(error) => {
                    tracing::error!(%error, "durable Team participant registration failed");
                    false
                }
            }
        } else {
            self.with_store(|store| store.register_participant(thread_id, role, label))
        }
    }

    /// Domain-facing registration API. Lifecycle callers that must preserve the durability error
    /// class use [`Self::register_durable_participant_checked`] instead.
    pub fn register_durable_participant(
        &self,
        thread_id: ThreadId,
        role: ParticipantRole,
        label: String,
    ) -> Result<bool, TeamError> {
        self.register_durable_participant_checked(thread_id, role, label)
            .map_err(TeamError::from)
    }

    /// Typed registration boundary for lifecycle callers that must distinguish a retryable
    /// durability outage from a definitive domain or lineage failure.
    pub fn register_durable_participant_checked(
        &self,
        thread_id: ThreadId,
        role: ParticipantRole,
        label: String,
    ) -> Result<bool, TeamDurabilityError> {
        if self.durable_runtime().is_none() {
            return Ok(self.with_store(|store| store.register_participant(thread_id, role, label)));
        }
        let identity = self.durable_identity().ok_or_else(|| {
            TeamDurabilityError::conflict("durable registration has no durable identity")
        })?;
        self.durable_mutate(false, move |store| {
            store.register_durable_participant(identity, thread_id, role, label)
        })
    }

    pub fn participant(&self, thread_id: ThreadId) -> Option<Participant> {
        self.with_store(|store| store.participant(thread_id).cloned())
    }

    pub fn participants(&self) -> Vec<Participant> {
        self.with_store(|store| store.participants())
    }

    /// The generation waiters observe. It only advances when a mutation actually changed canonical
    /// state, so a stable retry cannot look like new work.
    pub fn wake_generation(&self) -> u64 {
        *self.change_tx.borrow()
    }

    pub fn publish(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: PublishRequest,
    ) -> Result<PublishOutcome, TeamError> {
        if self.durable_runtime().is_some() {
            return self
                .durable_mutate(true, |store| {
                    store
                        .publish(actor, submission, request)
                        .map_err(Into::into)
                })
                .map_err(TeamError::from);
        }
        self.with_store(|store| {
            let outcome = store.publish(actor, submission, request)?;
            if !outcome.deduplicated {
                self.notify_change();
            }
            Ok(outcome)
        })
    }

    /// Check a publish request and copy its canonical authored fields without changing team state.
    ///
    /// Already-committed retries are answered from the same raw-request ledger as [`Self::publish`].
    /// A ready result is only a preparation view: callers must still pass the original
    /// [`PublishRequest`] to [`Self::publish`] for the final atomic validation and commit.
    pub fn prepare_publish(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: &PublishRequest,
    ) -> Result<PublishPreparation, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| store.prepare_publish(actor, submission, request))
    }

    /// Prepare a publish and capture its bounded existing-Event continuity under the same lock.
    pub fn prepare_publish_with_history(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: &PublishRequest,
        history_limit: usize,
    ) -> Result<(PublishPreparation, Option<PreparedPublishHistory>), TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| {
            store.prepare_publish_with_history(actor, submission, request, history_limit)
        })
    }

    pub fn update_lifecycle(
        &self,
        actor: ThreadId,
        request: LifecycleRequest,
    ) -> Result<LifecycleOutcome, TeamError> {
        if self.durable_runtime().is_some() {
            return self
                .durable_mutate(true, |store| {
                    store.update_lifecycle(actor, request).map_err(Into::into)
                })
                .map_err(TeamError::from);
        }
        self.with_store(|store| {
            let outcome = store.update_lifecycle(actor, request)?;
            if outcome.changed {
                self.notify_change();
            }
            Ok(outcome)
        })
    }

    /// Commit a route: the visibility grant, and the assignment when work is intended.
    ///
    /// The notice is the caller's job and happens strictly after this returns, which is the whole
    /// ordering guarantee: nothing can be delivered about a grant that does not exist yet.
    pub fn route(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: RouteRequest,
    ) -> Result<RouteOutcome, TeamError> {
        if self.durable_runtime().is_some() {
            return self
                .durable_mutate(true, |store| {
                    store.route(actor, submission, request).map_err(Into::into)
                })
                .map_err(TeamError::from);
        }
        self.with_store(|store| {
            let outcome = store.route(actor, submission, request)?;
            if !outcome.deduplicated {
                self.notify_change();
            }
            Ok(outcome)
        })
    }

    pub fn record_delivery(
        &self,
        actor: ThreadId,
        route_id: RouteId,
        result: DeliveryResult,
    ) -> Result<DeliveryOutcome, TeamError> {
        if self.durable_runtime().is_some() {
            return self
                .durable_mutate(true, |store| {
                    store
                        .record_delivery(actor, route_id, result)
                        .map_err(Into::into)
                })
                .map_err(TeamError::from);
        }
        self.with_store(|store| {
            let outcome = store.record_delivery(actor, route_id, result)?;
            if outcome.changed {
                self.notify_change();
            }
            Ok(outcome)
        })
    }

    pub fn end_assignment(
        &self,
        actor: ThreadId,
        route_id: RouteId,
    ) -> Result<EndAssignmentOutcome, TeamError> {
        if self.durable_runtime().is_some() {
            return self
                .durable_mutate(true, |store| {
                    store.end_assignment(actor, route_id).map_err(Into::into)
                })
                .map_err(TeamError::from);
        }
        self.with_store(|store| {
            let outcome = store.end_assignment(actor, route_id)?;
            self.notify_change();
            Ok(outcome)
        })
    }

    pub fn retire(
        &self,
        actor: ThreadId,
        submission: &Submission,
        request: RetireRequest,
        availability: &AvailabilitySnapshot,
        live_epoch: impl FnOnce() -> crate::availability::AvailabilityEpoch,
    ) -> Result<RetireOutcome, TeamError> {
        if self.durable_runtime().is_some() {
            return self
                .durable_mutate(true, |store| {
                    store
                        .retire(actor, submission, request, availability, live_epoch())
                        .map_err(Into::into)
                })
                .map_err(TeamError::from);
        }
        self.with_store(|store| {
            let outcome = store.retire(actor, submission, request, availability, live_epoch())?;
            if !outcome.deduplicated {
                self.notify_change();
            }
            Ok(outcome)
        })
    }

    pub fn dump(
        &self,
        actor: ThreadId,
        availability: &AvailabilitySnapshot,
        query: ObserveQuery,
        cursor: Option<DumpCursor>,
    ) -> Result<TeamDumpPage, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| {
            let wake_generation = *self.change_tx.borrow();
            store.dump(actor, availability, wake_generation, query, cursor)
        })
    }

    pub fn change_log(
        &self,
        actor: ThreadId,
        query: ObserveQuery,
    ) -> Result<ChangeLogPage, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| {
            let wake_generation = *self.change_tx.borrow();
            store.change_log(actor, wake_generation, query)
        })
    }

    pub fn publication_stats(
        &self,
        actor: ThreadId,
        query: ObserveQuery,
    ) -> Result<crate::observe::PublicationStatsPage, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| {
            let wake_generation = *self.change_tx.borrow();
            store.publication_stats(actor, wake_generation, query)
        })
    }

    pub fn route_dispatch(
        &self,
        actor: ThreadId,
        route_id: RouteId,
    ) -> Result<RouteDispatch, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| store.route_dispatch(actor, route_id))
    }

    /// Note a completed, supported tool result whose retention is not confirmed yet.
    pub fn note_observation(&self, producer: ThreadId, noted: NotedObservation) {
        if self.durable_runtime().is_some() {
            if let Err(error) = self.note_durable_observation(producer, noted) {
                tracing::error!(%error, "durable Team observation note failed");
            }
            return;
        }
        self.with_store(|store| store.note_observation(producer, noted));
    }

    pub fn note_durable_observation(
        &self,
        producer: ThreadId,
        noted: NotedObservation,
    ) -> Result<(), TeamError> {
        let Some(runtime) = self.durable_runtime() else {
            self.with_store(|store| store.note_observation(producer, noted));
            return Ok(());
        };
        if runtime.authority.is_none() {
            return Err(TeamError::from(TeamDurabilityError::ReadOnly));
        }
        let _gate = runtime
            .mutation_gate
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        self.ensure_readable().map_err(TeamError::from)?;
        self.with_store(|store| store.note_observation(producer, noted));
        Ok(())
    }

    /// Mint the fact for an observation the caller has confirmed Codex retained.
    ///
    /// No change notification follows: recording evidence is not itself a team event, and nothing in
    /// anyone's active view moves until an author decides to publish.
    pub fn confirm_observation(&self, producer: ThreadId, item_id: &str) -> Option<FactId> {
        if self.durable_runtime().is_some() {
            match self.confirm_durable_observation(producer, item_id) {
                Ok(fact_id) => fact_id,
                Err(error) => {
                    tracing::error!(%error, "durable Team evidence confirmation failed");
                    None
                }
            }
        } else {
            self.with_store(|store| store.confirm_observation(producer, item_id))
        }
    }

    pub fn confirm_durable_observation(
        &self,
        producer: ThreadId,
        item_id: &str,
    ) -> Result<Option<FactId>, TeamError> {
        if self.durable_runtime().is_none() {
            return Ok(self.with_store(|store| store.confirm_observation(producer, item_id)));
        }
        self.durable_mutate(false, |store| {
            Ok(store.confirm_observation(producer, item_id))
        })
        .map_err(TeamError::from)
    }

    /// Drop a note whose result the harness ended up throwing away.
    pub fn discard_observation(&self, producer: ThreadId, item_id: &str) {
        if self.durable_runtime().is_some() {
            if let Err(error) = self.discard_durable_observation(producer, item_id) {
                tracing::error!(%error, "durable Team observation discard failed");
            }
            return;
        }
        self.with_store(|store| store.discard_observation(producer, item_id));
    }

    pub fn discard_durable_observation(
        &self,
        producer: ThreadId,
        item_id: &str,
    ) -> Result<(), TeamError> {
        let Some(runtime) = self.durable_runtime() else {
            self.with_store(|store| store.discard_observation(producer, item_id));
            return Ok(());
        };
        if runtime.authority.is_none() {
            return Err(TeamError::from(TeamDurabilityError::ReadOnly));
        }
        let _gate = runtime
            .mutation_gate
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        self.ensure_readable().map_err(TeamError::from)?;
        self.with_store(|store| store.discard_observation(producer, item_id));
        Ok(())
    }

    pub fn read_fact(&self, actor: ThreadId, fact_id: FactId) -> Result<FactView, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| store.read_fact(actor, fact_id))
    }

    pub fn snapshot_for(&self, viewer: ThreadId) -> Result<TeamSnapshot, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| store.snapshot_for(viewer))
    }

    pub fn history(
        &self,
        viewer: ThreadId,
        query: &HistoryQuery,
    ) -> Result<HistoryPage, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        self.with_store(|store| store.history(viewer, query))
    }

    pub fn has_pending_wake(&self, participant: ThreadId) -> bool {
        self.with_store(|store| store.has_pending_wake(participant))
    }

    pub fn has_pending_durable_wake(&self, participant: ThreadId) -> Result<bool, TeamError> {
        self.ensure_readable_or_reconcile()
            .map_err(TeamError::from)?;
        Ok(self.with_store(|store| store.has_pending_wake(participant)))
    }

    pub fn consume_wake(&self, participant: ThreadId) -> bool {
        if self.durable_runtime().is_some() {
            match self.consume_durable_wake(participant) {
                Ok(consumed) => consumed,
                Err(error) => {
                    tracing::error!(%error, "durable Team wake consumption failed");
                    false
                }
            }
        } else {
            self.with_store(|store| store.consume_wake(participant))
        }
    }

    pub fn consume_durable_wake(&self, participant: ThreadId) -> Result<bool, TeamError> {
        if self.durable_runtime().is_none() {
            return Ok(self.with_store(|store| store.consume_wake(participant)));
        }
        self.durable_mutate(false, |store| Ok(store.consume_wake(participant)))
            .map_err(TeamError::from)
    }

    fn notify_change(&self) {
        self.change_tx.send_modify(|value| {
            *value = value.wrapping_add(1);
        });
    }

    /// Start listening for team changes addressed to `participant`.
    ///
    /// The subscription is taken before the first check, so a change published between the two
    /// cannot be lost: it either shows up in the check or in the watch channel.
    pub fn wake_waiter(self: &Arc<Self>, participant: ThreadId) -> TeamWakeWaiter {
        let change_rx = self.change_tx.subscribe();
        TeamWakeWaiter {
            handle: Arc::clone(self),
            participant,
            change_rx,
        }
    }
}

/// A pending wait for team activity. Resolving it consumes the wake.
pub struct TeamWakeWaiter {
    handle: Arc<TeamStateHandle>,
    participant: ThreadId,
    change_rx: watch::Receiver<u64>,
}

impl TeamWakeWaiter {
    /// Resolve as soon as this participant has an unconsumed team change, consuming it so the same
    /// change cannot wake it a second time.
    pub async fn wait(mut self) -> Result<(), TeamError> {
        loop {
            if self.handle.consume_durable_wake(self.participant)? {
                return Ok(());
            }
            if self.change_rx.changed().await.is_err() {
                // The sender lives inside the handle this waiter holds, so this is unreachable in
                // practice; park rather than reporting a wake that did not happen.
                std::future::pending::<()>().await;
            }
        }
    }
}

#[cfg(test)]
#[path = "handle_tests.rs"]
mod tests;
