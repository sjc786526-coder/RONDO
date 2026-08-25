use super::*;

type Control = ExperimentalSessionControl<&'static str, &'static str>;

fn fresh_control() -> Control {
    let mut control = Control::new();
    control.bind_connection();
    control.attach("session-a");
    let read = control.begin_read().expect("read should start");
    assert!(control.apply_read_success(read, "projection-a"));
    control
}

#[test]
fn authoritative_read_accepts_only_the_latest_ticket() {
    let mut control = Control::new();
    control.bind_connection();
    control.attach("session-a");
    let old = control.begin_read().expect("first read should start");
    let current = control.begin_read().expect("replacement read should start");
    assert!(!control.apply_read_success(old, "old"));
    assert!(control.apply_read_success(current, "current"));
    assert_eq!(control.projection(), Some(&"current"));
    assert_eq!(control.view_freshness(), ViewFreshness::Fresh);
}

#[test]
fn read_failure_preserves_old_projection_only_as_stale() {
    let mut control = fresh_control();
    let refresh = control.begin_read().expect("refresh should start");
    assert!(control.apply_read_failure(refresh));
    assert_eq!(control.projection(), Some(&"projection-a"));
    assert_eq!(control.view_freshness(), ViewFreshness::Stale);

    control.switch_attachment("session-b");
    let first_read = control.begin_read().expect("first read should start");
    assert!(control.apply_read_failure(first_read));
    assert_eq!(control.projection(), None);
    assert_eq!(control.view_freshness(), ViewFreshness::Absent);
}

#[test]
fn switch_and_detach_invalidate_old_read_tickets() {
    let mut control = Control::new();
    control.bind_connection();
    control.attach("session-a");
    let session_a_read = control.begin_read().expect("read should start");
    control.switch_attachment("session-b");
    assert!(!control.apply_read_success(session_a_read, "wrong-session"));
    assert_eq!(control.attachment(), Some(&"session-b"));
    assert_eq!(control.view_freshness(), ViewFreshness::Absent);

    let session_b_read = control.begin_read().expect("read should start");
    control.detach();
    assert!(!control.apply_read_success(session_b_read, "detached"));
    assert_eq!(control.attachment(), None);
    assert_eq!(control.projection(), None);
}

#[test]
fn detach_abandons_a_pending_mutation_as_unknown() {
    let mut control = fresh_control();
    let mutation = control.begin_mutation().expect("mutation should start");
    control.detach();
    assert_eq!(control.attachment(), None);
    assert_eq!(control.mutation_certainty(), MutationCertainty::Unknown);
    assert!(!control.apply_mutation_outcome(mutation, KnownMutationOutcome::Succeeded));
}

#[test]
fn lag_invalidates_the_read_but_not_a_pending_mutation_result() {
    let mut control = fresh_control();
    let mutation = control.begin_mutation().expect("mutation should start");
    control.on_lagged();
    assert_eq!(control.view_freshness(), ViewFreshness::Stale);
    assert_eq!(control.mutation_certainty(), MutationCertainty::Pending);
    assert!(control.apply_mutation_outcome(mutation, KnownMutationOutcome::Rejected));
    assert_eq!(
        control.mutation_certainty(),
        MutationCertainty::Known(KnownMutationOutcome::Rejected)
    );
    assert_eq!(control.view_freshness(), ViewFreshness::Stale);
}

#[test]
fn disconnect_makes_a_pending_mutation_unknown_and_retires_its_ticket() {
    let mut control = fresh_control();
    let old_epoch = control.connection_epoch();
    let mutation = control.begin_mutation().expect("mutation should start");
    control.on_disconnected();
    assert!(!control.is_connected());
    assert_eq!(control.mutation_certainty(), MutationCertainty::Unknown);
    assert_eq!(control.view_freshness(), ViewFreshness::Stale);
    assert!(!control.apply_mutation_outcome(mutation, KnownMutationOutcome::Succeeded));

    let new_epoch = control.bind_connection();
    assert!(new_epoch > old_epoch);
    assert_eq!(control.mutation_certainty(), MutationCertainty::Unknown);
    assert!(control.begin_mutation().is_none());
}

#[test]
fn event_stream_eof_has_disconnect_semantics() {
    let mut control = fresh_control();
    control.begin_mutation().expect("mutation should start");
    control.on_event_stream_closed();
    assert!(!control.is_connected());
    assert_eq!(control.mutation_certainty(), MutationCertainty::Unknown);
    assert_eq!(control.view_freshness(), ViewFreshness::Stale);
}

#[test]
fn response_loss_is_unknown_and_requires_an_explicit_reread() {
    let mut control = fresh_control();
    let mutation = control.begin_mutation().expect("mutation should start");
    assert!(control.apply_mutation_response_loss(mutation));
    assert_eq!(control.mutation_certainty(), MutationCertainty::Unknown);
    assert_eq!(control.view_freshness(), ViewFreshness::Stale);
    assert!(control.begin_mutation().is_none());

    let read = control
        .begin_read()
        .expect("manual reconciliation should start");
    assert!(control.apply_read_success(read, "reconciled"));
    assert_eq!(control.view_freshness(), ViewFreshness::Fresh);
    assert_eq!(control.mutation_certainty(), MutationCertainty::Unknown);
    assert!(
        !control.apply_mutation_outcome(mutation, KnownMutationOutcome::Succeeded),
        "a late response from the lost attempt must not overwrite reconciliation"
    );
    assert_eq!(control.projection(), Some(&"reconciled"));
    assert_eq!(control.view_freshness(), ViewFreshness::Fresh);
    assert_eq!(control.mutation_certainty(), MutationCertainty::Unknown);
    assert!(control.begin_mutation().is_some());
}

#[test]
fn known_success_invalidates_the_projection_until_reread() {
    let mut control = fresh_control();
    let mutation = control.begin_mutation().expect("mutation should start");
    assert!(control.apply_mutation_outcome(mutation, KnownMutationOutcome::Succeeded));
    assert_eq!(
        control.mutation_certainty(),
        MutationCertainty::Known(KnownMutationOutcome::Succeeded)
    );
    assert_eq!(control.view_freshness(), ViewFreshness::Stale);
    assert!(control.begin_mutation().is_none());
}

#[test]
fn only_side_effect_free_rejection_preserves_freshness() {
    for outcome in [
        KnownMutationOutcome::Succeeded,
        KnownMutationOutcome::Failed,
        KnownMutationOutcome::Partial,
    ] {
        let mut control = fresh_control();
        let mutation = control.begin_mutation().expect("mutation should start");
        assert!(control.apply_mutation_outcome(mutation, outcome));
        assert_eq!(control.view_freshness(), ViewFreshness::Stale);
    }
    let mut control = fresh_control();
    let mutation = control.begin_mutation().expect("mutation should start");
    assert!(control.apply_mutation_outcome(mutation, KnownMutationOutcome::Rejected));
    assert_eq!(control.view_freshness(), ViewFreshness::Fresh);
}

#[test]
fn reconnect_requires_a_new_read_and_ignores_old_connection_completion() {
    let mut control = Control::new();
    let old_epoch = control.bind_connection();
    control.attach("session-a");
    let old_read = control.begin_read().expect("read should start");
    control.on_disconnected();
    let new_epoch = control.bind_connection();
    assert!(new_epoch > old_epoch);
    assert!(!control.apply_read_success(old_read, "old-connection"));

    let new_read = control.begin_read().expect("new read should start");
    assert_eq!(new_read.connection_epoch(), new_epoch);
    assert!(control.apply_read_success(new_read, "new-connection"));
    assert_eq!(control.projection(), Some(&"new-connection"));
}
