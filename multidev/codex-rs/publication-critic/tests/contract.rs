#![allow(clippy::expect_used, clippy::unwrap_used)]

use codex_publication_critic::ActorRole;
use codex_publication_critic::ContextFreshness;
use codex_publication_critic::ContinuityContext;
use codex_publication_critic::ContinuityCoverage;
use codex_publication_critic::ContractFailure;
use codex_publication_critic::CriticFailure;
use codex_publication_critic::FactReferenceCountCoverage;
use codex_publication_critic::IdentityField;
use codex_publication_critic::LocalScope;
use codex_publication_critic::MAX_HANDOFF_BYTES;
use codex_publication_critic::MAX_HANDOFF_SCALARS;
use codex_publication_critic::MAX_PRIOR_PUBLICATIONS;
use codex_publication_critic::MAX_SUMMARY_BYTES;
use codex_publication_critic::MAX_SUMMARY_SCALARS;
use codex_publication_critic::MAX_TITLE_BYTES;
use codex_publication_critic::MAX_TITLE_SCALARS;
use codex_publication_critic::MAX_VISIBLE_FACT_REFERENCES;
use codex_publication_critic::PriorEvidence;
use codex_publication_critic::PriorPublication;
use codex_publication_critic::PublicationCandidate;
use codex_publication_critic::PublicationPacket;
use codex_publication_critic::TargetKind;
use codex_publication_critic::Verdict;
use codex_publication_critic::controlled_test_descriptor;
use codex_publication_critic::controlled_test_identity;
use codex_publication_critic::validate_expected_descriptor;
use pretty_assertions::assert_eq;

const BODY_SENTINEL: &str = "PUBLICATION_BODY_SENTINEL_055";

fn qualification() -> codex_publication_critic::QualificationIdentity {
    controlled_test_identity().qualification
}

fn prior_publication(summary: impl Into<String>) -> PriorPublication {
    PriorPublication::new(
        summary,
        PriorEvidence::present(
            /*visible_count*/ 2,
            FactReferenceCountCoverage::Complete,
        )
        .unwrap(),
    )
    .unwrap()
    .with_handoff("continue from the verified boundary")
    .unwrap()
}

#[test]
fn constructs_valid_new_and_existing_packets() {
    let new_packet = PublicationPacket::new(
        qualification(),
        ActorRole::Root,
        TargetKind::NewEvent,
        LocalScope::new("new publication").unwrap(),
        PublicationCandidate::new("new summary")
            .unwrap()
            .with_handoff("next action")
            .unwrap(),
        ContinuityContext::NotApplicable,
    )
    .unwrap();

    assert_eq!(new_packet.target_kind, TargetKind::NewEvent);
    assert_eq!(new_packet.candidate.summary(), "new summary");
    assert_eq!(new_packet.candidate.handoff(), Some("next action"));
    assert_eq!(new_packet.validate(), Ok(()));

    let existing_packet = PublicationPacket::new(
        qualification(),
        ActorRole::Member,
        TargetKind::ExistingEvent,
        LocalScope::new("existing publication").unwrap(),
        PublicationCandidate::new("updated summary").unwrap(),
        ContinuityContext::available(
            /*source_team_revision*/ 41,
            ContextFreshness::Current,
            ContinuityCoverage::Complete,
            vec![prior_publication("previous summary")],
        )
        .unwrap(),
    )
    .unwrap();

    assert_eq!(existing_packet.target_kind, TargetKind::ExistingEvent);
    assert_eq!(existing_packet.validate(), Ok(()));
}

#[test]
fn rejects_text_outside_scalar_and_byte_limits() {
    assert_eq!(
        LocalScope::new(" ").unwrap_err(),
        ContractFailure::InvalidPacket
    );
    assert_eq!(
        LocalScope::new("x".repeat(MAX_TITLE_SCALARS + 1)).unwrap_err(),
        ContractFailure::InvalidPacket
    );

    let scalars_with_too_many_bytes = "🦀".repeat(MAX_TITLE_BYTES / 4 + 1);
    assert!(scalars_with_too_many_bytes.chars().count() <= MAX_TITLE_SCALARS);
    assert!(scalars_with_too_many_bytes.len() > MAX_TITLE_BYTES);
    assert_eq!(
        LocalScope::new(scalars_with_too_many_bytes).unwrap_err(),
        ContractFailure::InvalidPacket
    );

    assert_eq!(
        PublicationCandidate::new("x".repeat(MAX_SUMMARY_SCALARS + 1)).unwrap_err(),
        ContractFailure::InvalidPacket
    );
    assert_eq!(
        PublicationCandidate::new("🦀".repeat(MAX_SUMMARY_BYTES / 4 + 1)).unwrap_err(),
        ContractFailure::InvalidPacket
    );
    assert_eq!(
        PublicationCandidate::new("summary")
            .unwrap()
            .with_handoff("x".repeat(MAX_HANDOFF_SCALARS + 1))
            .unwrap_err(),
        ContractFailure::InvalidPacket
    );
    assert_eq!(
        PublicationCandidate::new("summary")
            .unwrap()
            .with_handoff("🦀".repeat(MAX_HANDOFF_BYTES / 4 + 1))
            .unwrap_err(),
        ContractFailure::InvalidPacket
    );
}

#[test]
fn enforces_target_and_continuity_relationships() {
    let available = ContinuityContext::available(
        /*source_team_revision*/ 7,
        ContextFreshness::Current,
        ContinuityCoverage::Complete,
        vec![],
    )
    .unwrap();
    assert_eq!(
        PublicationPacket::new(
            qualification(),
            ActorRole::Root,
            TargetKind::NewEvent,
            LocalScope::new("scope").unwrap(),
            PublicationCandidate::new("summary").unwrap(),
            available,
        )
        .unwrap_err(),
        ContractFailure::InvalidPacket
    );
    assert_eq!(
        PublicationPacket::new(
            qualification(),
            ActorRole::Root,
            TargetKind::ExistingEvent,
            LocalScope::new("scope").unwrap(),
            PublicationCandidate::new("summary").unwrap(),
            ContinuityContext::NotApplicable,
        )
        .unwrap_err(),
        ContractFailure::InvalidPacket
    );

    let too_many_prior_publications = (0..=MAX_PRIOR_PUBLICATIONS)
        .map(|index| prior_publication(format!("prior {index}")))
        .collect();
    assert_eq!(
        ContinuityContext::available(
            /*source_team_revision*/ 7,
            ContextFreshness::Current,
            ContinuityCoverage::Complete,
            too_many_prior_publications,
        )
        .unwrap_err(),
        ContractFailure::InvalidPacket
    );
    assert_eq!(
        ContinuityContext::available(
            /*source_team_revision*/ 7,
            ContextFreshness::Current,
            ContinuityCoverage::Partial {
                omitted_count: Some(0),
            },
            vec![],
        )
        .unwrap_err(),
        ContractFailure::InvalidPacket
    );

    assert_eq!(
        PublicationPacket::new(
            qualification(),
            ActorRole::Root,
            TargetKind::ExistingEvent,
            LocalScope::new("scope").unwrap(),
            PublicationCandidate::new("summary").unwrap(),
            ContinuityContext::unavailable(
                /*last_known_revision*/ None,
                ContextFreshness::Current,
            ),
        )
        .unwrap_err(),
        ContractFailure::InvalidPacket
    );
}

#[test]
fn enforces_prior_evidence_count_limits() {
    assert_eq!(
        PriorEvidence::present(
            /*visible_count*/ 0,
            FactReferenceCountCoverage::Complete
        )
        .unwrap_err(),
        ContractFailure::InvalidPacket
    );
    assert_eq!(
        PriorEvidence::present(
            MAX_VISIBLE_FACT_REFERENCES + 1,
            FactReferenceCountCoverage::Omitted,
        )
        .unwrap_err(),
        ContractFailure::InvalidPacket
    );
    assert!(
        PriorEvidence::present(
            /*visible_count*/ 1,
            FactReferenceCountCoverage::Complete
        )
        .is_ok()
    );
    assert!(
        PriorEvidence::present(
            MAX_VISIBLE_FACT_REFERENCES,
            FactReferenceCountCoverage::Omitted,
        )
        .is_ok()
    );
    assert_eq!(
        PriorPublication::new("prior summary", PriorEvidence::none())
            .unwrap()
            .evidence,
        PriorEvidence::none()
    );
}

#[test]
fn controlled_threshold_maps_rewrite_pass_and_equality() {
    let scoring = controlled_test_identity()
        .scoring
        .as_scalar()
        .expect("controlled test identity stays scalar")
        .clone();

    assert_eq!(scoring.threshold(), 0.5);
    assert_eq!(scoring.verdict_for_scores(&[0.25]), Ok(Verdict::Rewrite));
    assert_eq!(scoring.verdict_for_scores(&[0.5]), Ok(Verdict::Pass));
    assert_eq!(scoring.verdict_for_scores(&[0.75]), Ok(Verdict::Pass));
}

#[test]
fn expected_descriptor_rejects_identity_drift() {
    let expected =
        controlled_test_descriptor(codex_publication_critic::RuntimeLimits::production());
    let mut actual = expected.clone();
    actual.identity.model.model =
        codex_publication_critic::ComponentIdentity::new("different-model", "v1").unwrap();

    assert_eq!(
        validate_expected_descriptor(&expected, &actual),
        Err(ContractFailure::IdentityMismatch(IdentityField::Model))
    );
}

#[test]
fn debug_and_failure_display_do_not_expose_body_text() {
    let packet = PublicationPacket::new(
        qualification(),
        ActorRole::Member,
        TargetKind::ExistingEvent,
        LocalScope::new(format!("scope {BODY_SENTINEL}")).unwrap(),
        PublicationCandidate::new(format!("candidate {BODY_SENTINEL}"))
            .unwrap()
            .with_handoff(format!("handoff {BODY_SENTINEL}"))
            .unwrap(),
        ContinuityContext::available(
            /*source_team_revision*/ 9,
            ContextFreshness::Current,
            ContinuityCoverage::Complete,
            vec![prior_publication(format!("prior {BODY_SENTINEL}"))],
        )
        .unwrap(),
    )
    .unwrap();

    let packet_debug = format!("{packet:?}");
    assert!(!packet_debug.contains(BODY_SENTINEL), "{packet_debug}");

    let rejected_body = format!("{BODY_SENTINEL}{}", "x".repeat(MAX_SUMMARY_SCALARS));
    let failure = PublicationCandidate::new(rejected_body).unwrap_err();
    let failure_debug = format!("{failure:?}");
    let failure_display = failure.to_string();
    let critic_display = CriticFailure::Contract(failure).to_string();
    assert!(!failure_debug.contains(BODY_SENTINEL), "{failure_debug}");
    assert!(
        !failure_display.contains(BODY_SENTINEL),
        "{failure_display}"
    );
    assert!(!critic_display.contains(BODY_SENTINEL), "{critic_display}");
}
