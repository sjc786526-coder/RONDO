use super::*;
use crate::ActorRole;
use crate::ComponentIdentity;
use crate::ContinuityContext;
use crate::LocalScope;
use crate::PublicationCandidate;
use crate::QualificationIdentity;
use crate::TargetKind;
use pretty_assertions::assert_eq;

#[test]
fn strict_projection_accepts_only_one_finite_quality_number() {
    assert_eq!(parse_quality_scalar(r#"{"quality":0.83}"#), Some(0.83));
    assert_eq!(parse_quality_scalar("  {\"quality\": 0}\n"), Some(0.0));
    // A finite but out-of-domain observation stays a real observation; the service owns the
    // typed out-of-domain failure.
    assert_eq!(parse_quality_scalar(r#"{"quality":1.7}"#), Some(1.7));
}

#[test]
fn strict_projection_rejects_every_other_reply_shape() {
    let oversized = format!(
        r#"{{"quality":0.5,"pad":"{}"}}"#,
        "a".repeat(MAX_CONTENT_BYTES)
    );
    for content in [
        "",
        "0.83",
        "PASS",
        "```json\n{\"quality\":0.83}\n```",
        r#"{"quality":"0.83"}"#,
        r#"{"quality":null}"#,
        r#"{"quality":0.83,"reason":"ok"}"#,
        r#"{"score":0.83}"#,
        r#"{"quality":1e400}"#,
        r#"[{"quality":0.83}]"#,
        r#"{"quality":0.83}{"quality":0.2}"#,
        oversized.as_str(),
    ] {
        assert_eq!(
            parse_quality_scalar(content),
            None,
            "content must not project to a scalar"
        );
    }
}

#[test]
fn user_message_is_the_stable_packet_projection() {
    let qualification = QualificationIdentity::new(
        ComponentIdentity::new("rondo-publication-packet", "v1").expect("component is valid"),
        ComponentIdentity::new("rondo-publication-qualification", "v1")
            .expect("component is valid"),
    );
    let packet = PublicationPacket::new(
        qualification,
        ActorRole::Member,
        TargetKind::NewEvent,
        LocalScope::new("Cloud template projection").expect("title is valid"),
        PublicationCandidate::new("A candidate summary.").expect("candidate is valid"),
        ContinuityContext::NotApplicable,
    )
    .expect("packet is valid");

    let rendered = render_user_message(&packet).expect("packet projection must render");
    assert_eq!(
        serde_json::from_str::<PublicationPacket>(&rendered).expect("projection round-trips"),
        packet
    );
}
