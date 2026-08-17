use super::super::TeamStore;
use crate::availability::AvailabilitySnapshot;
use crate::availability::ProducerAvailability;
use crate::ids::TeamRevision;
use crate::observe::DumpCursor;
use crate::observe::DumpEntry;
use crate::observe::ObserveQuery;
use crate::test_support::TeamFixture;
use crate::test_support::new_event;
use crate::test_support::register_member;
use crate::test_support::submission;
use codex_protocol::ThreadId;
use pretty_assertions::assert_eq;

fn all_unavailable(store: &TeamStore) -> AvailabilitySnapshot {
    AvailabilitySnapshot::from_entries(
        store
            .participants()
            .into_iter()
            .map(|participant| (participant.thread_id, ProducerAvailability::Unavailable))
            .collect(),
    )
}

#[test]
fn dump_pages_are_stable_and_refuse_a_stale_cursor() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let availability = all_unavailable(&store);
    let first = store
        .dump(
            root,
            &availability,
            /*wake_generation*/ 1,
            ObserveQuery {
                limit: Some(3),
                offset: None,
                after: None,
            },
            None,
        )
        .expect("root may dump");
    assert_eq!(first.wake_generation, 1);
    assert_eq!(first.entries.len(), 3);
    assert!(first.next_offset.is_some());
    let again = store
        .dump(
            root,
            &availability,
            1,
            ObserveQuery {
                limit: Some(3),
                offset: None,
                after: None,
            },
            None,
        )
        .expect("repeat dump");
    assert_eq!(first, again);

    let cursor = DumpCursor {
        revision: first.revision,
        availability_epoch: first.availability_epoch,
        observe_generation: first.observe_generation,
        offset: first.next_offset.expect("more pages"),
    };
    let second = store
        .dump(
            root,
            &availability,
            1,
            ObserveQuery {
                limit: Some(50),
                offset: None,
                after: None,
            },
            Some(cursor),
        )
        .expect("next page");
    assert!(
        second
            .entries
            .iter()
            .all(|entry| !first.entries.contains(entry))
    );

    store
        .publish(
            worker,
            &submission(store.revision(), "w2"),
            new_event("another", "new matter"),
        )
        .expect("second publish");
    let err = store
        .dump(
            root,
            &availability,
            1,
            ObserveQuery {
                limit: Some(3),
                offset: None,
                after: None,
            },
            Some(cursor),
        )
        .expect_err("cursor from an older revision");
    assert!(matches!(
        err,
        crate::mutation::TeamError::DumpCursorStale { .. }
    ));
}

#[test]
fn dump_pairs_visibility_and_activity_reasons_and_counts_zero_publishers() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let _idle = register_member(&mut store, "/root/idle");
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let availability = all_unavailable(&store);
    let page = store
        .dump(
            root,
            &availability,
            0,
            ObserveQuery {
                limit: Some(50),
                offset: None,
                after: None,
            },
            None,
        )
        .expect("dump");

    let idle_visibility = page
        .entries
        .iter()
        .find_map(|entry| match entry {
            DumpEntry::Visibility {
                participant,
                visible,
                reasons,
                ..
            } if participant == "/root/idle" => Some((*visible, reasons.clone())),
            _ => None,
        })
        .expect("idle visibility");
    assert!(!idle_visibility.0);
    assert_eq!(idle_visibility.1, vec!["no_visibility_grant".to_string()]);

    let idle_activity = page
        .entries
        .iter()
        .find_map(|entry| match entry {
            DumpEntry::Activity {
                participant,
                active,
                reasons,
                ..
            } if participant == "/root/idle" => Some((*active, reasons.clone())),
            _ => None,
        })
        .expect("idle activity");
    assert!(!idle_activity.0);
    assert_eq!(idle_activity.1, vec!["no_active_reason".to_string()]);

    let idle_stats = page
        .entries
        .iter()
        .find_map(|entry| match entry {
            DumpEntry::Publication {
                participant,
                version_count,
                authored_chars,
                fact_ref_count,
                ..
            } if participant == "/root/idle" => {
                Some((*version_count, *authored_chars, *fact_ref_count))
            }
            _ => None,
        })
        .expect("idle stats");
    assert_eq!(idle_stats, (0, 0, 0));
}

#[test]
fn change_log_skips_retries_and_stats_match_canonical_authored_fields() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let _published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("retry");
    let log = store
        .change_log(
            root,
            0,
            ObserveQuery {
                limit: Some(50),
                offset: None,
                after: None,
            },
        )
        .expect("root may read the log");
    assert_eq!(log.entries.len(), 1);
    assert_eq!(log.total_entries, 1);

    let stats = store
        .publication_stats(
            root,
            0,
            ObserveQuery {
                limit: Some(50),
                offset: None,
                after: None,
            },
        )
        .expect("stats");
    let stats = stats.entries;
    let worker_stats = stats
        .iter()
        .find(|row| row.participant == "/root/worker")
        .expect("worker stats");
    let expected_chars =
        "schema drift".chars().count() as u64 + "two columns were renamed".chars().count() as u64;
    assert_eq!(worker_stats.version_count, 1);
    assert_eq!(worker_stats.authored_chars, expected_chars);
    assert_eq!(worker_stats.fact_ref_count, 0);
}

#[test]
fn members_cannot_read_diagnostics() {
    let TeamFixture { store, worker, .. } = TeamFixture::new();
    let availability = all_unavailable(&store);
    let err = store
        .dump(
            worker,
            &availability,
            0,
            ObserveQuery {
                limit: None,
                offset: None,
                after: None,
            },
            None,
        )
        .expect_err("members cannot dump");
    assert!(matches!(
        err,
        crate::mutation::TeamError::NotPermitted { .. }
    ));
}

#[test]
fn confirming_a_fact_invalidates_an_open_dump_cursor() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let availability = all_unavailable(&store);
    let first = store
        .dump(
            root,
            &availability,
            0,
            ObserveQuery {
                limit: Some(3),
                offset: None,
                after: None,
            },
            None,
        )
        .expect("first page");
    let cursor = DumpCursor {
        revision: first.revision,
        availability_epoch: first.availability_epoch,
        observe_generation: first.observe_generation,
        offset: first.next_offset.expect("more pages"),
    };

    store.note_observation(
        worker,
        crate::evidence::NotedObservation {
            item_id: "fco_shell-1".to_string(),
            call_id: "shell-1".to_string(),
            category: crate::evidence::FactCategory::ToolResultSuccess,
            tool: "shell_command".to_string(),
        },
    );
    store
        .confirm_observation(worker, "fco_shell-1")
        .expect("fact is minted");

    let err = store
        .dump(
            root,
            &availability,
            0,
            ObserveQuery {
                limit: Some(3),
                offset: None,
                after: None,
            },
            Some(cursor),
        )
        .expect_err("a fact inserted between pages must not splice");
    assert!(matches!(
        err,
        crate::mutation::TeamError::DumpCursorStale { .. }
    ));
}

#[test]
fn dump_names_retirement_metadata_fact_ids_and_call_id() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    store.note_observation(
        worker,
        crate::evidence::NotedObservation {
            item_id: "fco_shell-1".to_string(),
            call_id: "call-shell-1".to_string(),
            category: crate::evidence::FactCategory::ToolResultSuccess,
            tool: "shell_command".to_string(),
        },
    );
    let fact_id = store
        .confirm_observation(worker, "fco_shell-1")
        .expect("fact");
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let availability = all_unavailable(&store);
    store
        .retire(
            root,
            &submission(published.revision, "r-retire"),
            crate::mutation::RetireRequest {
                version_id: published.version_id,
                expected_producer_state: crate::model::ProducerState::Open,
                expected_root_state: crate::model::RootState::Pending,
                expected_availability: ProducerAvailability::Unavailable,
                expected_availability_epoch: availability.epoch,
                reason: "gone for good".to_string(),
            },
            &availability,
            availability.epoch,
        )
        .expect("retire");

    let page = store
        .dump(
            root,
            &availability,
            0,
            ObserveQuery {
                limit: Some(50),
                offset: None,
                after: None,
            },
            None,
        )
        .expect("dump");
    let version = page
        .entries
        .iter()
        .find_map(|entry| match entry {
            DumpEntry::Version {
                version_id,
                retire_reason,
                retired_availability,
                fact_ref_count,
                author_thread_id,
                retired_by_thread_id,
                ..
            } if version_id == &published.version_id.to_string() => Some((
                retire_reason.clone(),
                *retired_availability,
                *fact_ref_count,
                author_thread_id.clone(),
                retired_by_thread_id.clone(),
            )),
            _ => None,
        })
        .expect("version row");
    assert_eq!(version.0.as_deref(), Some("gone for good"));
    assert_eq!(version.1, Some(ProducerAvailability::Unavailable));
    assert_eq!(version.2, 1);
    assert_eq!(version.3, worker.to_string());
    assert_eq!(version.4.as_deref(), Some(root.to_string().as_str()));

    let version_fact = page
        .entries
        .iter()
        .find_map(|entry| match entry {
            DumpEntry::VersionFact {
                version_id,
                fact_id: listed,
            } if version_id == &published.version_id.to_string() => Some(listed.clone()),
            _ => None,
        })
        .expect("version fact row");
    assert_eq!(version_fact, fact_id.to_string());

    let fact = page
        .entries
        .iter()
        .find_map(|entry| match entry {
            DumpEntry::Fact { call_id, .. } => Some(call_id.clone()),
            _ => None,
        })
        .expect("fact row");
    assert_eq!(fact, "call-shell-1");
}

#[test]
fn stats_key_by_thread_id_and_page() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let twin = ThreadId::new();
    store.register_participant(
        twin,
        crate::model::ParticipantRole::Member,
        "/root/worker".to_string(),
    );
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("first worker publishes");
    store
        .publish(
            twin,
            &submission(store.revision(), "t1"),
            new_event("another leftover", "a later agent reused the label"),
        )
        .expect("twin publishes under the same label");

    let page = store
        .publication_stats(
            root,
            0,
            ObserveQuery {
                limit: Some(2),
                offset: None,
                after: None,
            },
        )
        .expect("stats page");
    assert_eq!(page.total_entries, 3);
    assert_eq!(page.entries.len(), 2);
    assert_eq!(page.next_offset, Some(2));
    let counted: Vec<_> = page
        .entries
        .iter()
        .chain(
            store
                .publication_stats(
                    root,
                    0,
                    ObserveQuery {
                        limit: Some(2),
                        offset: page.next_offset,
                        after: None,
                    },
                )
                .expect("rest of stats")
                .entries
                .iter(),
        )
        .filter(|row| row.participant == "/root/worker")
        .map(|row| (row.thread_id.clone(), row.version_count))
        .collect();
    assert_eq!(counted.len(), 2);
    assert!(
        counted.iter().all(|(_, count)| *count == 1),
        "each agent keeps its own count even when labels collide: {counted:?}"
    );
}

#[test]
fn dump_rejects_a_raw_offset_without_a_cursor() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let err = store
        .dump(
            root,
            &all_unavailable(&store),
            0,
            ObserveQuery {
                limit: Some(3),
                offset: Some(3),
                after: None,
            },
            None,
        )
        .expect_err("raw offset is not a dump continuation");
    assert!(matches!(
        err,
        crate::mutation::TeamError::InvalidRequest { .. }
    ));
}

#[test]
fn dump_pages_version_facts_and_keeps_each_row_bounded() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    for index in 0..8 {
        store.note_observation(
            worker,
            crate::evidence::NotedObservation {
                item_id: format!("fco-{index}"),
                call_id: format!("call-{index}"),
                category: crate::evidence::FactCategory::ToolResultSuccess,
                tool: "shell_command".to_string(),
            },
        );
        store
            .confirm_observation(worker, &format!("fco-{index}"))
            .expect("fact");
    }
    let published = store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("worker may publish");
    let availability = all_unavailable(&store);
    let first = store
        .dump(
            root,
            &availability,
            0,
            ObserveQuery {
                limit: Some(1),
                offset: None,
                after: None,
            },
            None,
        )
        .expect("first page");
    assert_eq!(first.entries.len(), 1);

    let mut offset = 0;
    let mut version_facts = Vec::new();
    loop {
        let page = store
            .dump(
                root,
                &availability,
                0,
                ObserveQuery {
                    limit: Some(1),
                    offset: None,
                    after: None,
                },
                Some(DumpCursor {
                    revision: first.revision,
                    availability_epoch: first.availability_epoch,
                    observe_generation: first.observe_generation,
                    offset,
                }),
            )
            .expect("page");
        assert!(page.entries.len() <= 1);
        if let Some(DumpEntry::VersionFact {
            version_id,
            fact_id,
        }) = page.entries.first()
            && version_id == &published.version_id.to_string()
        {
            version_facts.push(fact_id.clone());
        }
        match page.next_offset {
            Some(next) => offset = next,
            None => break,
        }
    }
    assert_eq!(version_facts.len(), 8);
}

#[test]
fn dump_and_log_disambiguate_duplicate_labels_with_thread_ids() {
    let TeamFixture {
        mut store,
        root,
        worker,
    } = TeamFixture::new();
    let twin = register_member(&mut store, "/root/worker");
    store
        .publish(
            worker,
            &submission(TeamRevision::INITIAL, "w1"),
            new_event("schema drift", "two columns were renamed"),
        )
        .expect("first worker publishes");
    store
        .publish(
            twin,
            &submission(store.revision(), "t1"),
            new_event("another leftover", "a later agent reused the label"),
        )
        .expect("twin publishes");
    let page = store
        .dump(
            root,
            &all_unavailable(&store),
            0,
            ObserveQuery {
                limit: Some(50),
                offset: None,
                after: None,
            },
            None,
        )
        .expect("dump");
    let authors: Vec<_> = page
        .entries
        .iter()
        .filter_map(|entry| match entry {
            DumpEntry::Version {
                author,
                author_thread_id,
                ..
            } => Some((author.clone(), author_thread_id.clone())),
            _ => None,
        })
        .collect();
    assert_eq!(authors.len(), 2);
    assert!(authors.iter().all(|(label, _)| label == "/root/worker"));
    let thread_ids: std::collections::HashSet<_> = authors
        .into_iter()
        .map(|(_, thread_id)| thread_id)
        .collect();
    assert_eq!(thread_ids.len(), 2);

    let visibility_ids: std::collections::HashSet<_> = page
        .entries
        .iter()
        .filter_map(|entry| match entry {
            DumpEntry::Visibility {
                participant,
                participant_thread_id,
                ..
            } if participant == "/root/worker" => Some(participant_thread_id.clone()),
            _ => None,
        })
        .collect();
    assert_eq!(visibility_ids.len(), 2);

    let log = store
        .change_log(
            root,
            0,
            ObserveQuery {
                limit: Some(50),
                offset: None,
                after: None,
            },
        )
        .expect("log");
    let log_actors: std::collections::HashSet<_> = log
        .entries
        .iter()
        .map(|entry| entry.actor_thread_id.clone())
        .collect();
    assert!(log_actors.contains(&worker.to_string()));
    assert!(log_actors.contains(&twin.to_string()));
}
