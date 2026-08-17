use crate::availability::AvailabilitySnapshot;
use crate::availability::ProducerAvailability;
use crate::ids::TeamRevision;
use crate::model::ProducerState;
use crate::model::RootState;
use crate::mutation::LifecycleChange;
use crate::mutation::LifecycleRequest;
use crate::mutation::LifecycleTarget;
use crate::mutation::RetireRequest;
use crate::mutation::RouteIntent;
use crate::mutation::TeamError;
use crate::test_support::TeamFixture;
use crate::test_support::new_event;
use crate::test_support::register_member;
use crate::test_support::route;
use crate::test_support::submission;
use pretty_assertions::assert_eq;

fn unavailable(thread: codex_protocol::ThreadId) -> AvailabilitySnapshot {
    AvailabilitySnapshot::from_entries(vec![(thread, ProducerAvailability::Unavailable)])
}

fn retire_request(
    version_id: crate::ids::VersionId,
    worker: codex_protocol::ThreadId,
    reason: &str,
) -> (RetireRequest, AvailabilitySnapshot) {
    let availability = unavailable(worker);
    (
        RetireRequest {
            version_id,
            expected_producer_state: ProducerState::Open,
            expected_root_state: RootState::Pending,
            expected_availability: ProducerAvailability::Unavailable,
            expected_availability_epoch: availability.epoch,
            reason: reason.to_string(),
        },
        availability,
    )
}

#[test]
fn root_retires_an_open_version_when_the_producer_is_unavailable() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let (request, availability) = retire_request(published.version_id, worker, "gone");

    let outcome = store
        .retire(
            root,
            &submission(published.revision, "r-retire"),
            request,
            &availability,
            availability.epoch,
        )
        .expect("root may retire");

    assert!(!outcome.deduplicated);
    let version = store
        .events
        .iter()
        .find_map(|event| event.version(published.version_id))
        .expect("version exists");
    assert_eq!(version.producer_state(), ProducerState::Open);
    assert_eq!(version.root_state(), RootState::Pending);
    assert!(version.is_retired());
    assert_eq!(version.retirement().unwrap().reason, "gone");
    assert!(!version.occupies_author_attention());
    let root_view = store.snapshot_for(root).expect("root view");
    assert!(
        root_view
            .events
            .iter()
            .any(|event| event.id == published.event_id),
        "root attention is unchanged, so the event stays in the root view"
    );
}

#[test]
fn recoverable_or_unknown_producers_cannot_be_retired() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    for class in [
        ProducerAvailability::Available,
        ProducerAvailability::RecoverableUnloaded,
        ProducerAvailability::Unknown,
    ] {
        let availability = AvailabilitySnapshot::from_entries(vec![(worker, class)]);
        let err = store
            .retire(
                root,
                &submission(published.revision, &format!("r-{class}")),
                RetireRequest {
                    version_id: published.version_id,
                    expected_producer_state: ProducerState::Open,
                    expected_root_state: RootState::Pending,
                    expected_availability: class,
                    expected_availability_epoch: availability.epoch,
                    reason: "try".to_string(),
                },
                &availability,
                availability.epoch,
            )
            .expect_err("only a truly unavailable producer may be retired");
        assert!(matches!(
            err,
            TeamError::ProducerNotUnavailable { availability: got, .. } if got == class
        ));
    }
}

#[test]
fn a_member_cannot_retire_and_a_stale_epoch_is_refused() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let (request, availability) = retire_request(published.version_id, worker, "gone");
    let err = store
        .retire(
            worker,
            &submission(published.revision, "w-retire"),
            request.clone(),
            &availability,
            availability.epoch,
        )
        .expect_err("members cannot retire");
    assert!(matches!(err, TeamError::NotPermitted { .. }));

    let mut stale = request;
    stale.expected_availability_epoch = crate::availability::AvailabilityEpoch::from_raw(1);
    let err = store
        .retire(
            root,
            &submission(published.revision, "r-stale"),
            stale,
            &availability,
            availability.epoch,
        )
        .expect_err("stale availability epoch is refused");
    assert!(matches!(err, TeamError::AvailabilityConflict { .. }));
}

#[test]
fn exact_retry_is_idempotent_and_a_second_independent_retire_is_refused() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let (request, availability) = retire_request(published.version_id, worker, "gone");
    let first = store
        .retire(
            root,
            &submission(published.revision, "r-retire"),
            request.clone(),
            &availability,
            availability.epoch,
        )
        .expect("first retire");
    let revision = store.revision();
    let retry = store
        .retire(
            root,
            &submission(published.revision, "r-retire"),
            request.clone(),
            &availability,
            availability.epoch,
        )
        .expect("exact retry");
    assert!(retry.deduplicated);
    assert_eq!(retry.revision, first.revision);
    assert_eq!(store.revision(), revision);
    assert_eq!(store.change_log.len(), 2); // publish + one retire

    let mut other = request;
    other.reason = "another reason".to_string();
    let err = store
        .retire(
            root,
            &submission(published.revision, "r-retire"),
            other,
            &availability,
            availability.epoch,
        )
        .expect_err("same identity, different reason");
    assert_eq!(err, TeamError::RetryIdentityReused);

    let (second, availability) = retire_request(published.version_id, worker, "again");
    let err = store
        .retire(
            root,
            &submission(first.revision, "r-retire-2"),
            second,
            &availability,
            availability.epoch,
        )
        .expect_err("already retired");
    assert!(matches!(err, TeamError::VersionRetired { .. }));
    let version = store
        .events
        .iter()
        .find_map(|event| event.version(published.version_id))
        .expect("version exists");
    assert_eq!(version.retirement().unwrap().reason, "gone");
}

#[test]
fn retirement_does_not_end_routes_or_other_versions() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let other = register_member(&mut store, "/root/other");
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    store
        .route(
            root,
            &submission(published.revision, "r-route"),
            route(published.event_id, other, RouteIntent::Assign),
        )
        .expect("root may assign");
    let other_version = store
        .publish(
            other,
            &submission(store.revision(), "o1"),
            crate::test_support::append(published.event_id, "other is still working"),
        )
        .expect("assignee may append");
    let (request, availability) = retire_request(published.version_id, worker, "gone");
    store
        .retire(
            root,
            &submission(store.revision(), "r-retire"),
            request,
            &availability,
            availability.epoch,
        )
        .expect("retire worker version");

    let event = store
        .events
        .iter()
        .find(|event| event.id() == published.event_id)
        .expect("event exists");
    assert!(event.assignment_in_progress_for(other).is_some());
    let other_entry = event
        .version(other_version.version_id)
        .expect("other version exists");
    assert_eq!(other_entry.producer_state(), ProducerState::Open);
    assert!(!other_entry.is_retired());
    assert!(event.is_active_for(other, crate::model::ParticipantRole::Member));
}

#[test]
fn a_closed_version_cannot_be_retired_and_a_retired_version_cannot_be_closed() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![LifecycleTarget {
                    version_id: published.version_id,
                    expected_producer_state: ProducerState::Open,
                    expected_root_state: RootState::Pending,
                    change: LifecycleChange::CloseProducer,
                }],
            },
        )
        .expect("author may close");
    let (request, availability) = retire_request(published.version_id, worker, "gone");
    let err = store
        .retire(
            root,
            &submission(store.revision(), "r-retire"),
            request,
            &availability,
            availability.epoch,
        )
        .expect_err("closed versions are already producer-terminal");
    assert!(matches!(
        err,
        TeamError::LifecycleConflict { .. } | TeamError::VersionClosed { .. }
    ));

    let open = store
        .publish(
            worker,
            &submission(store.revision(), "w2"),
            new_event("second matter", "still open"),
        )
        .expect("worker may publish again");
    let (request, availability) = retire_request(open.version_id, worker, "gone");
    store
        .retire(
            root,
            &submission(open.revision, "r-retire-open"),
            request,
            &availability,
            availability.epoch,
        )
        .expect("retire the open one");
    let err = store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![LifecycleTarget {
                    version_id: open.version_id,
                    expected_producer_state: ProducerState::Open,
                    expected_root_state: RootState::Pending,
                    change: LifecycleChange::CloseProducer,
                }],
            },
        )
        .expect_err("retired versions cannot be rewritten as producer closed");
    assert!(matches!(err, TeamError::VersionRetired { .. }));
}

#[test]
fn an_aba_unavailable_snapshot_does_not_reuse_the_original_epoch() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let stale = AvailabilitySnapshot::from_entries_at(
        crate::availability::AvailabilityEpoch::from_raw(1),
        vec![(worker, ProducerAvailability::Unavailable)],
    );
    let current = AvailabilitySnapshot::from_entries_at(
        crate::availability::AvailabilityEpoch::from_raw(3),
        vec![(worker, ProducerAvailability::Unavailable)],
    );
    let err = store
        .retire(
            root,
            &submission(published.revision, "r-aba"),
            RetireRequest {
                version_id: published.version_id,
                expected_producer_state: ProducerState::Open,
                expected_root_state: RootState::Pending,
                expected_availability: ProducerAvailability::Unavailable,
                expected_availability_epoch: stale.epoch,
                reason: "gone".to_string(),
            },
            &current,
            current.epoch,
        )
        .expect_err("a later unavailable picture is not the original epoch");
    assert!(matches!(err, TeamError::AvailabilityConflict { .. }));
}

#[test]
fn a_live_epoch_that_moved_during_commit_is_refused() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let snapshot = AvailabilitySnapshot::from_entries_at(
        crate::availability::AvailabilityEpoch::from_raw(4),
        vec![(worker, ProducerAvailability::Unavailable)],
    );
    let err = store
        .retire(
            root,
            &submission(published.revision, "r-race"),
            RetireRequest {
                version_id: published.version_id,
                expected_producer_state: ProducerState::Open,
                expected_root_state: RootState::Pending,
                expected_availability: ProducerAvailability::Unavailable,
                expected_availability_epoch: snapshot.epoch,
                reason: "gone".to_string(),
            },
            &snapshot,
            crate::availability::AvailabilityEpoch::from_raw(5),
        )
        .expect_err("restore between snapshot and commit must refuse");
    assert!(matches!(
        err,
        TeamError::AvailabilityConflict {
            availability: ProducerAvailability::Unknown,
            ..
        }
    ));
}
