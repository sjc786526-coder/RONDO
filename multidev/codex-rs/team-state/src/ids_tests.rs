use super::*;
use pretty_assertions::assert_eq;

#[test]
fn event_version_route_and_fact_references_round_trip_through_their_printed_form() {
    let instance = TeamInstanceId::new();
    let event_id = EventId::new(instance.tag(), 7);
    let version_id = VersionId::new(instance.tag(), 7, 3);
    let route_id = RouteId::new(instance.tag(), 7, 2);
    let fact_id = FactId::new(instance.tag(), 5);

    assert_eq!(event_id.to_string().parse(), Ok(event_id));
    assert_eq!(version_id.to_string().parse(), Ok(version_id));
    assert_eq!(route_id.to_string().parse(), Ok(route_id));
    assert_eq!(fact_id.to_string().parse(), Ok(fact_id));
    assert_eq!(version_id.event_id(), event_id);
    assert_eq!(route_id.event_id(), event_id);
    assert_eq!(TeamInstanceId::from_tag(instance.tag()), Ok(instance));
    assert_eq!(instance.to_string().parse(), Ok(instance));
}

#[test]
fn a_route_reference_is_not_mistaken_for_a_version_of_the_same_event() {
    let instance = TeamInstanceId::new();
    let route_id = RouteId::new(instance.tag(), 4, 1);

    assert_eq!(
        route_id.to_string().parse::<VersionId>(),
        Err(ReferenceParseError)
    );
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
    assert_eq!("fct-1".parse::<FactId>(), Err(ReferenceParseError));
    assert_eq!("nonsense".parse::<EventId>(), Err(ReferenceParseError));
}
