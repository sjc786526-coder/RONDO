use super::*;

#[test]
fn event_stream_lag_marks_observation_incomplete() {
    let mut collector = RondoLocalObservationCollector::default();

    collector.note_event_stream_lag();

    assert!(!collector.snapshot().event_stream_complete);
}
