use super::*;
use crate::session::tests::make_session_and_context;
use codex_publication_critic::RuntimeLimits;
use codex_publication_critic::controlled_test_descriptor;
use codex_team_state::TeamRevision;
use pretty_assertions::assert_eq;
use std::time::Duration;

fn request(title: &str, summary: &str) -> PublishRequest {
    PublishRequest {
        target: PublishTarget::NewEvent {
            title: title.to_string(),
        },
        summary: summary.to_string(),
        handoff: None,
    }
}

fn submission(request_id: &str) -> Submission {
    Submission {
        based_on: TeamRevision::INITIAL,
        request_id: request_id.to_string(),
    }
}

fn config() -> PublicationCriticConfig {
    PublicationCriticConfig::new(
        "127.0.0.1:43119".parse().unwrap(),
        controlled_test_descriptor(RuntimeLimits::production()),
        Duration::from_secs(1),
        Duration::from_secs(1),
    )
    .unwrap()
}

#[tokio::test]
async fn unrelated_committed_replay_and_refusal_preserve_active_rewrite_cycle() {
    let (_session, turn) = make_session_and_context().await;
    let handle = TeamStateHandle::default();
    let actor = ThreadId::new();
    handle.register_participant(actor, ParticipantRole::Root, "/root".to_string());

    let committed_request = request("already committed", "committed body");
    let committed_submission = submission("committed-request");
    handle
        .publish(actor, &committed_submission, committed_request.clone())
        .unwrap();

    let first_candidate = request("active candidate", "first draft");
    let reviews = turn
        .extension_data
        .get_or_init(TurnPublicationReviews::default);
    let active_continuation = {
        let mut state = reviews.state.lock().await;
        let first = state
            .begin_attempt(handle.instance(), actor, &first_candidate, None)
            .unwrap();
        state.advance_after_blocking_rewrite(&first, 1).unwrap()
    };

    let replay = review_and_publish(
        &turn,
        &CancellationToken::new(),
        &config(),
        &handle,
        ReviewedPublishAttempt {
            actor,
            submission: committed_submission,
            request: committed_request,
            continuation: None,
        },
    )
    .await
    .unwrap();
    assert!(matches!(replay, ReviewPublishResult::Committed { .. }));

    let refusal = review_and_publish(
        &turn,
        &CancellationToken::new(),
        &config(),
        &handle,
        ReviewedPublishAttempt {
            actor,
            submission: submission("unrelated-refusal"),
            request: request("unrelated", "   "),
            continuation: None,
        },
    )
    .await;
    assert!(matches!(
        refusal,
        Err(ReviewPublishError::Team(TeamError::InvalidRequest { .. }))
    ));

    let unrelated_ready = review_and_publish(
        &turn,
        &CancellationToken::new(),
        &config(),
        &handle,
        ReviewedPublishAttempt {
            actor,
            submission: submission("unrelated-ready"),
            request: request("unrelated", "valid but not a continuation"),
            continuation: None,
        },
    )
    .await;
    assert!(matches!(unrelated_ready, Err(ReviewPublishError::Cycle(_))));

    let mut state = reviews.state.lock().await;
    let active = state
        .active
        .as_ref()
        .expect("the rewrite cycle stays active");
    assert_eq!(active.id, active_continuation);
    assert_eq!(active.next_review_index, 1);
    assert_eq!(active.blocking_rewrite_count, 1);
    let continued = state
        .begin_attempt(
            handle.instance(),
            actor,
            &request("revised candidate", "second draft"),
            Some(&active_continuation),
        )
        .expect("the original continuation still advances exactly one stage");
    assert_eq!(continued.review_index, 1);
    assert_eq!(continued.blocking_rewrite_count, 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn concurrent_candidates_cannot_share_a_stale_continuation() {
    let mut state = ReviewState::default();
    let instance = TeamInstanceId::new();
    let actor = ThreadId::new();

    let first = state
        .begin_attempt(instance, actor, &request("first", "draft one"), None)
        .unwrap();
    let stage_two = state.advance_after_blocking_rewrite(&first, 1).unwrap();
    let state = Arc::new(Mutex::new(state));
    let barrier = Arc::new(tokio::sync::Barrier::new(3));
    let mut tasks = Vec::new();
    for (title, summary) in [
        ("candidate-a", "draft two a"),
        ("candidate-b", "draft two b"),
    ] {
        let state = Arc::clone(&state);
        let barrier = Arc::clone(&barrier);
        let continuation = stage_two.clone();
        let candidate = request(title, summary);
        tasks.push(tokio::spawn(async move {
            barrier.wait().await;
            let mut state = state.lock().await;
            let attempt = state.begin_attempt(instance, actor, &candidate, Some(&continuation))?;
            state.advance_after_blocking_rewrite(&attempt, 2)
        }));
    }
    barrier.wait().await;

    let mut stage_three = None;
    let mut stale_rejections = 0;
    for task in tasks {
        match task.await.unwrap() {
            Ok(continuation) => stage_three = Some(continuation),
            Err(ReviewPublishError::Cycle(_)) => stale_rejections += 1,
            Err(error) => panic!("unexpected concurrent result: {error:?}"),
        }
    }
    let stage_three = stage_three.expect("one candidate advances to the next stage");
    assert_ne!(stage_two, stage_three);
    assert_eq!(stale_rejections, 1);

    let mut state = state.lock().await;
    let final_attempt = state
        .begin_attempt(
            instance,
            actor,
            &request("final", "draft three"),
            Some(&stage_three),
        )
        .expect("only the continuation returned by the latest feedback remains valid");
    assert_eq!(final_attempt.review_index, 2);
    assert_eq!(final_attempt.blocking_rewrite_count, 2);
}
