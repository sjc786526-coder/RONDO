# RONDO training assets

`training/` contains lightweight, tracked training contracts and datasets. It
is separate from both product source trees and does not participate in Rust
builds. Model weights and training outputs never belong here.

Tracked frozen datasets currently include `local-approval-synthetic-v1/`,
`publication-critic-v7/`, and `publication-critic-v8/`. Current stage and
handoff are defined only by `doc/WBS.md`.

Plan 037's stage-1 train-only bundle, model/tokenizer identity, candidate LoRA
recipe and RunPod lifecycle are in `local-approval-l6/`. They are preparation
contracts, not evidence that an 8B optimizer smoke or training run occurred.

Plan 059's `publication-critic-v7/` freezes 72 Publication Critic candidates,
36 preference pairs, three group-closed splits, cumulative C1/C2/C3 membership,
an exact-token census, and a train-only smoke bundle. It is a data handoff; it
is not evidence of model training, model quality, deployment, or product use.

Plan 064's `publication-critic-v8/` full-materializes 228 candidates and 104
pairs over an exact immutable-v7 membership projection plus reviewed additions.
Its manifest binds the approved prefreeze universe, input and implementation
contracts, split, token census, review evidence, and train-only smoke bundle.
The release does not establish training-budget suitability or authorize model
training.
