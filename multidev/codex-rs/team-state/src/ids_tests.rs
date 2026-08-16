use super::*;
use pretty_assertions::assert_eq;

#[test]
fn event_and_version_references_round_trip_through_their_printed_form() {
    let instance = TeamInstanceId::new();
    let event_id = EventId::new(instance.tag(), 7);
    let version_id = VersionId::new(instance.tag(), 7, 3);

    assert_eq!(event_id.to_string().parse(), Ok(event_id));
    assert_eq!(version_id.to_string().parse(), Ok(version_id));
    assert_eq!(version_id.event_id(), event_id);
}

#[test]
fn references_carry_the_instance_that_minted_them() {
    let first = TeamInstanceId::new();
    let second = TeamInstanceId::new();

    assert_ne!(EventId::new(first.tag(), 1), EventId::new(second.tag(), 1));
}

#[test]
fn a_reference_that_is_not_a_team_reference_is_rejected() {
    assert_eq!("evt-1".parse::<EventId>(), Err(ReferenceParseError));
    assert_eq!("evt-1-zzzz".parse::<EventId>(), Err(ReferenceParseError));
    assert_eq!(
        "ver-1-abcdef01".parse::<VersionId>(),
        Err(ReferenceParseError)
    );
    assert_eq!("nonsense".parse::<EventId>(), Err(ReferenceParseError));
}
