# Publication Critic training data v8

This is the full-materialized Plan 064 release over the exact design-locked
projection of the immutable v7 base and directly reviewed Plan 064 additions.

- Candidates: 228
- Splits: {"train": 128, "unseen_test": 45, "validation": 55}
- Pairs: {"boundary": 86, "within_pass": 18}
- Exact-token total: 178646
- Approved prefreeze universe: `3fdfc0ada4a67451e4f1fc7e66302067119172fea809802ff1d01576b3be40d9`

The default consumer physically exposes train rows only. Validation and unseen
test access requires explicit evaluation mode. Labels are synthetic teacher
references, not human-labelled ground truth. This data release does not itself
establish model quality or authorize training.
