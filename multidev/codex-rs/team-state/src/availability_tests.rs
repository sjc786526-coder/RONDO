use super::*;
use pretty_assertions::assert_eq;

#[test]
fn equal_entry_sets_share_order_regardless_of_insertion() {
    let first = ThreadId::new();
    let second = ThreadId::new();
    let epoch = AvailabilityEpoch::from_raw(7);
    let forward = AvailabilitySnapshot::from_entries_at(
        epoch,
        vec![
            (first, ProducerAvailability::Available),
            (second, ProducerAvailability::RecoverableUnloaded),
        ],
    );
    let reverse = AvailabilitySnapshot::from_entries_at(
        epoch,
        vec![
            (second, ProducerAvailability::RecoverableUnloaded),
            (first, ProducerAvailability::Available),
        ],
    );

    assert_eq!(forward.epoch, reverse.epoch);
    assert_eq!(forward.entries(), reverse.entries());
}

#[test]
fn an_aba_cycle_does_not_reuse_an_earlier_epoch() {
    let thread = ThreadId::new();
    let first_gone = AvailabilitySnapshot::from_entries_at(
        AvailabilityEpoch::from_raw(1),
        vec![(thread, ProducerAvailability::Unavailable)],
    );
    let restored = AvailabilitySnapshot::from_entries_at(
        AvailabilityEpoch::from_raw(2),
        vec![(thread, ProducerAvailability::Available)],
    );
    let gone_again = AvailabilitySnapshot::from_entries_at(
        AvailabilityEpoch::from_raw(3),
        vec![(thread, ProducerAvailability::Unavailable)],
    );

    assert_eq!(first_gone.class_of(thread), gone_again.class_of(thread));
    assert_ne!(first_gone.epoch, gone_again.epoch);
    assert_ne!(restored.epoch, gone_again.epoch);
}
