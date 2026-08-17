use super::*;
use pretty_assertions::assert_eq;

#[test]
fn equal_entry_sets_share_an_epoch_regardless_of_insertion_order() {
    let first = ThreadId::new();
    let second = ThreadId::new();
    let forward = AvailabilitySnapshot::from_entries(vec![
        (first, ProducerAvailability::Available),
        (second, ProducerAvailability::RecoverableUnloaded),
    ]);
    let reverse = AvailabilitySnapshot::from_entries(vec![
        (second, ProducerAvailability::RecoverableUnloaded),
        (first, ProducerAvailability::Available),
    ]);

    assert_eq!(forward.epoch, reverse.epoch);
    assert_eq!(forward.entries(), reverse.entries());
}

#[test]
fn a_class_change_produces_a_different_epoch() {
    let thread = ThreadId::new();
    let available =
        AvailabilitySnapshot::from_entries(vec![(thread, ProducerAvailability::Available)]);
    let gone =
        AvailabilitySnapshot::from_entries(vec![(thread, ProducerAvailability::Unavailable)]);

    assert_ne!(available.epoch, gone.epoch);
}
