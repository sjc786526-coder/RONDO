use super::*;
use crate::model::ParticipantRole;
use crate::mutation::LifecycleChange;
use crate::mutation::LifecycleTarget;
use crate::test_support::TeamFixture;
use crate::test_support::append;
use crate::test_support::new_event;
use crate::test_support::submission;
use pretty_assertions::assert_eq;

fn close_producer(version_id: VersionId, root_state: RootState) -> LifecycleTarget {
    LifecycleTarget {
        version_id,
        expected_producer_state: ProducerState::Open,
        expected_root_state: root_state,
        change: LifecycleChange::CloseProducer,
    }
}

fn set_root_state(
    version_id: VersionId,
    expected_root_state: RootState,
    state: RootState,
) -> LifecycleTarget {
    LifecycleTarget {
        version_id,
        expected_producer_state: ProducerState::Open,
        expected_root_state,
        change: LifecycleChange::SetRootState(state),
    }
}

#[test]
fn member_publication_is_pending_for_root_and_root_publication_is_tracking() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let from_worker = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "the migration renamed two columns"),
        )
        .expect("worker may publish");
    let from_root = store
        .publish(
            root,
            &submission(from_worker.revision, "r1"),
            new_event("release plan", "cut the branch after review"),
        )
        .expect("root may publish");

    let worker_version = store
        .events
        .iter()
        .find_map(|event| event.version(from_worker.version_id))
        .expect("worker version exists");
    let root_version = store
        .events
        .iter()
        .find_map(|event| event.version(from_root.version_id))
        .expect("root version exists");
    assert_eq!(worker_version.root_state(), RootState::Pending);
    assert_eq!(root_version.root_state(), RootState::Tracking);
}

#[test]
fn root_self_publication_does_not_wake_the_root_but_member_publication_does() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    store
        .publish(
            root,
            &submission(TeamRevision::INITIAL, "r1"),
            new_event("own note", "root's own reminder"),
        )
        .expect("root may publish");
    assert!(
        !store.has_pending_wake(root),
        "root must not wake itself for its own version"
    );

    store
        .publish(
            worker,
            &submission(store.revision(), "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");
    assert!(store.has_pending_wake(root));
}

#[test]
fn a_consumed_change_does_not_wake_the_root_again() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");

    assert!(store.consume_wake(root), "first consume takes the wake");
    assert!(
        !store.consume_wake(root),
        "an already consumed change must not wake the root again"
    );
}

#[test]
fn retrying_a_submission_returns_the_original_objects() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let first = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "retry-me"),
            new_event("finding", "worker found something"),
        )
        .expect("first attempt succeeds");
    let retry = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "retry-me"),
            new_event("finding", "worker found something"),
        )
        .expect("retry succeeds");

    assert_eq!(
        retry,
        PublishOutcome {
            deduplicated: true,
            ..first
        }
    );
    assert_eq!(store.events.len(), 1);
    assert_eq!(store.events[0].versions().len(), 1);
}

#[test]
fn appending_on_a_stale_view_is_committed_and_labelled() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "first look"),
        )
        .expect("worker may publish");
    let stale_base = opened.revision;
    // Someone else moves the event on before the stale append lands.
    store
        .publish(
            root,
            &submission(stale_base, "r1"),
            append(opened.event_id, "root adds context"),
        )
        .expect("root may append");

    let stale = store
        .publish(
            worker,
            &submission(stale_base, "w2"),
            append(
                opened.event_id,
                "worker's follow-up written against the old view",
            ),
        )
        .expect("a stale append is still committed");

    assert!(stale.authored_on_stale_view);
    assert!(
        !opened.authored_on_stale_view,
        "opening an event nobody has seen yet is never stale"
    );
    let version = store.events[0]
        .version(stale.version_id)
        .expect("stale version exists");
    assert_eq!(version.authored_on_stale_view(), Some(stale_base));
}

#[test]
fn a_lifecycle_change_whose_precondition_moved_is_rejected_with_the_current_state() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");
    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Tracking,
                )],
            },
        )
        .expect("root may take the pending item");

    let conflict = store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect_err("a moved precondition must be rejected");

    assert_eq!(
        conflict,
        TeamError::LifecycleConflict {
            current: LifecycleSnapshot {
                version_id: published.version_id,
                producer_state: ProducerState::Open,
                root_state: RootState::Tracking,
            }
        }
    );
}

#[test]
fn a_batch_only_touches_the_versions_it_names() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let named = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("first", "first finding"),
        )
        .expect("worker may publish");
    let untouched = store
        .publish(
            worker,
            &submission(store.revision(), "w2"),
            new_event("second", "second finding"),
        )
        .expect("worker may publish");

    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    named.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect("root may resolve the named version");

    let untouched_version = store
        .events
        .iter()
        .find_map(|event| event.version(untouched.version_id))
        .expect("untouched version exists");
    assert_eq!(untouched_version.root_state(), RootState::Pending);
}

#[test]
fn authored_content_survives_every_lifecycle_change() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            PublishRequest {
                target: PublishTarget::NewEvent {
                    title: "finding".to_string(),
                },
                summary: "the migration renamed two columns".to_string(),
                handoff: Some("verify the downstream view".to_string()),
            },
        )
        .expect("worker may publish");
    let authored_before = store.events[0]
        .version(published.version_id)
        .expect("version exists")
        .authored()
        .clone();

    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect("root may resolve");
    store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![close_producer(published.version_id, RootState::Resolved)],
            },
        )
        .expect("author may close");

    let authored_after = store.events[0]
        .version(published.version_id)
        .expect("version exists")
        .authored()
        .clone();
    assert_eq!(authored_after, authored_before);
}

#[test]
fn a_closed_version_cannot_be_reopened_in_place() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");
    store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![close_producer(published.version_id, RootState::Pending)],
            },
        )
        .expect("author may close");

    let reopened = store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![LifecycleTarget {
                    version_id: published.version_id,
                    expected_producer_state: ProducerState::Closed,
                    expected_root_state: RootState::Pending,
                    change: LifecycleChange::CloseProducer,
                }],
            },
        )
        .expect_err("a closed version is terminal");
    assert_eq!(
        reopened,
        TeamError::VersionClosed {
            version_id: published.version_id
        }
    );
}

#[test]
fn only_the_author_closes_and_only_the_root_sets_root_state() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");

    let root_closing = store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![close_producer(published.version_id, RootState::Pending)],
            },
        )
        .expect_err("the root does not close someone else's item");
    assert_eq!(
        root_closing,
        TeamError::NotPermitted {
            reason: "only the author of a version may close it"
        }
    );

    let member_resolving = store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect_err("a member does not own root attention");
    assert_eq!(
        member_resolving,
        TeamError::NotPermitted {
            reason: "only the root may change root attention state"
        }
    );
}

#[test]
fn closing_wakes_the_root_only_while_it_still_owes_attention() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let still_pending = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("first", "first finding"),
        )
        .expect("worker may publish");
    let already_resolved = store
        .publish(
            worker,
            &submission(store.revision(), "w2"),
            new_event("second", "second finding"),
        )
        .expect("worker may publish");
    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    already_resolved.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect("root may resolve");
    store.consume_wake(root);

    store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![close_producer(
                    already_resolved.version_id,
                    RootState::Resolved,
                )],
            },
        )
        .expect("author may close");
    assert!(
        !store.has_pending_wake(root),
        "closing an item the root already resolved must not reclaim its attention"
    );

    store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![close_producer(still_pending.version_id, RootState::Pending)],
            },
        )
        .expect("author may close");
    assert!(
        store.has_pending_wake(root),
        "closing an item the root still owes attention gives it another chance to coordinate"
    );
}

#[test]
fn resolving_keeps_the_item_in_the_authors_own_active_view() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");
    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect("root may resolve");

    let root_view = store.snapshot_for(root).expect("root is a participant");
    let worker_view = store.snapshot_for(worker).expect("worker is a participant");
    assert!(
        root_view.is_empty(),
        "the root's coordination is finished, so it leaves the root's active view"
    );
    assert_eq!(
        worker_view
            .events
            .iter()
            .map(|event| event.id)
            .collect::<Vec<_>>(),
        vec![published.event_id],
        "the author still has an open item, so it stays in the author's active view"
    );
}

#[test]
fn a_new_version_brings_the_event_back_into_the_roots_active_view() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");
    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect("root may resolve");
    store.consume_wake(root);
    assert!(store.snapshot_for(root).expect("root view").is_empty());

    store
        .publish(
            worker,
            &submission(store.revision(), "w2"),
            append(published.event_id, "it got worse"),
        )
        .expect("worker may append");

    let root_view = store.snapshot_for(root).expect("root view");
    assert_eq!(
        root_view
            .events
            .iter()
            .map(|event| event.versions.len())
            .collect::<Vec<_>>(),
        vec![2],
        "the root sees the whole chain again, not only the new entry"
    );
    assert!(store.has_pending_wake(root));
}

#[test]
fn history_returns_items_that_left_every_active_view() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();

    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");
    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect("root may resolve");
    store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![close_producer(published.version_id, RootState::Resolved)],
            },
        )
        .expect("author may close");

    assert!(store.snapshot_for(root).expect("root view").is_empty());
    assert!(store.snapshot_for(worker).expect("worker view").is_empty());

    let page = store
        .history(root, &HistoryQuery::default())
        .expect("root may read team history");
    assert_eq!(
        page.events
            .iter()
            .map(|entry| entry.event.id)
            .collect::<Vec<_>>(),
        vec![published.event_id]
    );
}

#[test]
fn history_is_bounded_and_scoped_to_what_the_caller_may_read() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let outsider = ThreadId::new();
    let bystander = ThreadId::new();
    store.register_participant(
        bystander,
        ParticipantRole::Member,
        "/root/other".to_string(),
    );

    let root_only = store
        .publish(
            root,
            &submission(TeamRevision::INITIAL, "r1"),
            new_event("root note", "root's own note"),
        )
        .expect("root may publish");
    store
        .publish(
            worker,
            &submission(store.revision(), "w1"),
            new_event("worker note", "worker's note"),
        )
        .expect("worker may publish");

    let bystander_page = store
        .history(bystander, &HistoryQuery::default())
        .expect("a registered member may query");
    assert!(
        bystander_page.events.is_empty(),
        "a member with nothing of its own under any event reads nothing"
    );

    let denied = store
        .history(
            bystander,
            &HistoryQuery {
                event_id: Some(root_only.event_id),
                limit: None,
                before: None,
            },
        )
        .expect_err("reading someone else's event is refused");
    assert_eq!(
        denied,
        TeamError::NotPermitted {
            reason: "this event is not visible to you"
        }
    );

    let unknown = store
        .history(outsider, &HistoryQuery::default())
        .expect_err("an unregistered session has no team capability at all");
    assert_eq!(unknown, TeamError::UnknownParticipant);

    let capped = store
        .history(
            root,
            &HistoryQuery {
                event_id: None,
                limit: Some(MAX_HISTORY_LIMIT * 10),
                before: None,
            },
        )
        .expect("root may query");
    assert!(capped.events.len() <= MAX_HISTORY_LIMIT);
}

#[test]
fn history_of_a_long_chain_reports_what_it_left_out() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();

    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w0"),
            new_event("finding", "entry 0"),
        )
        .expect("worker may publish");
    for index in 1..6 {
        store
            .publish(
                worker,
                &submission(store.revision(), &format!("w{index}")),
                append(opened.event_id, &format!("entry {index}")),
            )
            .expect("worker may append");
    }

    let page = store
        .history(
            worker,
            &HistoryQuery {
                event_id: Some(opened.event_id),
                limit: Some(2),
                before: None,
            },
        )
        .expect("worker may read its own event");
    let entry = page.events.first().expect("one event");
    assert_eq!(entry.total_versions, 6);
    assert_eq!(entry.omitted_versions, 4);
    assert_eq!(entry.event.versions.len(), 2);
}

#[test]
fn a_reference_from_another_instance_is_reported_as_a_reset() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");

    // A fresh instance stands in for a root team that could not find its previous state.
    let mut restarted = TeamStore::new();
    restarted.register_participant(worker, ParticipantRole::Member, "/root/worker".to_string());

    let error = restarted
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w2"),
            append(published.event_id, "still relevant"),
        )
        .expect_err("an old reference must not resolve against a new instance");
    assert_eq!(
        error,
        TeamError::InstanceReset {
            referenced_instance: published.event_id.instance(),
            current_instance: restarted.instance().tag(),
        }
    );
}

#[test]
fn reregistering_a_reloaded_member_keeps_its_identity_and_state() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();
    let instance_before = store.instance();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");

    // The member is unloaded and reloaded inside the same live root tree.
    let created =
        store.register_participant(worker, ParticipantRole::Member, "/root/worker".to_string());

    assert!(!created, "a reload rejoins rather than re-registers");
    assert_eq!(store.instance(), instance_before);
    let view = store.snapshot_for(worker).expect("worker is a participant");
    assert_eq!(
        view.events.iter().map(|event| event.id).collect::<Vec<_>>(),
        vec![published.event_id],
        "the reloaded member still sees its own unfinished item"
    );
}

#[test]
fn an_unregistered_session_gets_no_team_capability() {
    let TeamFixture { mut store, .. } = TeamFixture::new();
    let outsider = ThreadId::new();

    assert_eq!(
        store
            .publish(
                outsider,
                &submission(TeamRevision::INITIAL, "x1"),
                new_event("finding", "should not land"),
            )
            .expect_err("fail closed"),
        TeamError::UnknownParticipant
    );
    assert_eq!(
        store.snapshot_for(outsider).expect_err("fail closed"),
        TeamError::UnknownParticipant
    );
    assert!(store.events.is_empty());
}

#[test]
fn a_member_cannot_write_into_an_event_it_cannot_see() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let outsider = ThreadId::new();
    store.register_participant(outsider, ParticipantRole::Member, "/root/other".to_string());

    let private = store
        .publish(
            root,
            &submission(TeamRevision::INITIAL, "r1"),
            new_event("root only", "something the root is tracking"),
        )
        .expect("root may publish");

    // Identifiers are guessable by construction, so the guard has to be the visibility check
    // rather than the obscurity of the reference.
    let denied = store
        .publish(
            outsider,
            &submission(store.revision(), "o1"),
            append(private.event_id, "sneaking in"),
        )
        .expect_err("writing into an invisible event is refused");
    assert_eq!(
        denied,
        TeamError::NotPermitted {
            reason: "this event is not visible to you, so you cannot add to it"
        }
    );

    // And the refusal did not hand out read access as a side effect.
    let still_denied = store
        .history(
            outsider,
            &HistoryQuery {
                event_id: Some(private.event_id),
                limit: None,
                before: None,
            },
        )
        .expect_err("still not readable");
    assert_eq!(
        still_denied,
        TeamError::NotPermitted {
            reason: "this event is not visible to you"
        }
    );
    let _ = worker;
}

#[test]
fn root_attention_does_not_reopen_once_resolved() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");
    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect("root may resolve");

    let reopened = store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Resolved,
                    RootState::Pending,
                )],
            },
        )
        .expect_err("resolved coordination is terminal");
    assert_eq!(
        reopened,
        TeamError::RootAttentionResolved {
            version_id: published.version_id
        }
    );
}

#[test]
fn history_pages_all_the_way_back_to_the_oldest_entry() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();
    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w0"),
            new_event("finding", "entry 0"),
        )
        .expect("worker may publish");
    for index in 1..12 {
        store
            .publish(
                worker,
                &submission(store.revision(), &format!("w{index}")),
                append(opened.event_id, &format!("entry {index}")),
            )
            .expect("worker may append");
    }

    // Walk backwards three at a time until the cursor runs out, and confirm every entry was
    // reachable. Reporting what was omitted is only half the contract; getting it back is the
    // other half.
    let mut seen = Vec::new();
    let mut before = None;
    loop {
        let page = store
            .history(
                worker,
                &HistoryQuery {
                    event_id: Some(opened.event_id),
                    limit: Some(3),
                    before,
                },
            )
            .expect("worker may read its own event");
        let entry = page.events.first().expect("one event");
        assert!(entry.event.versions.len() <= 3, "the page stayed bounded");
        for version in &entry.event.versions {
            seen.push(version.summary.clone());
        }
        match page.next_before {
            Some(next) => before = Some(next),
            None => break,
        }
    }
    seen.sort();
    let mut expected: Vec<String> = (0..12).map(|index| format!("entry {index}")).collect();
    expected.sort();
    assert_eq!(seen, expected);
}

#[test]
fn listing_events_previews_them_instead_of_returning_every_version() {
    let TeamFixture {
        mut store, worker, ..
    } = TeamFixture::new();
    let opened = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w0"),
            new_event("finding", "entry 0"),
        )
        .expect("worker may publish");
    for index in 1..20 {
        store
            .publish(
                worker,
                &submission(store.revision(), &format!("w{index}")),
                append(opened.event_id, &format!("entry {index}")),
            )
            .expect("worker may append");
    }

    let page = store
        .history(worker, &HistoryQuery::default())
        .expect("worker may list");
    let entry = page.events.first().expect("one event");
    assert_eq!(entry.total_versions, 20);
    assert!(
        entry.event.versions.len() < 20,
        "a list of events must not drag in every version the team ever wrote"
    );
    assert_eq!(
        entry.omitted_versions,
        20 - entry.event.versions.len(),
        "and it has to say how much it held back"
    );
}

/// A batch cannot step around a terminal state by naming the same axis twice: both halves would
/// validate against the state as it stood before the batch, and then apply in order.
#[test]
fn one_batch_cannot_change_the_same_lifecycle_axis_twice() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");

    let sneaky = store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![
                    set_root_state(
                        published.version_id,
                        RootState::Pending,
                        RootState::Resolved,
                    ),
                    set_root_state(
                        published.version_id,
                        RootState::Pending,
                        RootState::Tracking,
                    ),
                ],
            },
        )
        .expect_err("naming one axis twice in a batch is refused");
    assert_eq!(
        sneaky,
        TeamError::ConflictingTargets {
            version_id: published.version_id
        }
    );

    // Nothing was written: the batch is still all-or-nothing.
    let snapshot = store.snapshot_for(root).expect("root view");
    assert_eq!(
        snapshot.events[0].versions[0].root_state,
        RootState::Pending
    );
}

/// The two axes are independent, so one batch may still touch both on the same version.
#[test]
fn one_batch_may_still_change_both_axes_of_a_version() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            root,
            &submission(TeamRevision::INITIAL, "r1"),
            new_event("root item", "the root's own note"),
        )
        .expect("root may publish");

    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![
                    close_producer(published.version_id, RootState::Tracking),
                    set_root_state(
                        published.version_id,
                        RootState::Tracking,
                        RootState::Resolved,
                    ),
                ],
            },
        )
        .expect("producer and root state are independent axes");
    let _ = worker;
}

/// A caller whose picture of a version is out of date learns the current state, even when the
/// change it asked for would also have been rejected as a terminal transition.
#[test]
fn a_stale_call_against_a_terminal_state_gets_the_current_state_back() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("finding", "worker found something"),
        )
        .expect("worker may publish");
    // The root resolves it and the author closes it; a caller still holding the original view now
    // has both fields wrong.
    store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Resolved,
                )],
            },
        )
        .expect("root may resolve");
    store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![close_producer(published.version_id, RootState::Resolved)],
            },
        )
        .expect("author may close");

    let stale_root = store
        .update_lifecycle(
            root,
            LifecycleRequest {
                targets: vec![set_root_state(
                    published.version_id,
                    RootState::Pending,
                    RootState::Tracking,
                )],
            },
        )
        .expect_err("a stale lifecycle change is refused");
    assert_eq!(
        stale_root,
        TeamError::LifecycleConflict {
            current: LifecycleSnapshot {
                version_id: published.version_id,
                producer_state: ProducerState::Closed,
                root_state: RootState::Resolved,
            }
        },
        "the refusal has to carry the whole current state, not just the rule that was broken"
    );

    let stale_author = store
        .update_lifecycle(
            worker,
            LifecycleRequest {
                targets: vec![close_producer(published.version_id, RootState::Pending)],
            },
        )
        .expect_err("a stale close is refused");
    assert_eq!(
        stale_author,
        TeamError::LifecycleConflict {
            current: LifecycleSnapshot {
                version_id: published.version_id,
                producer_state: ProducerState::Closed,
                root_state: RootState::Resolved,
            }
        }
    );
}
