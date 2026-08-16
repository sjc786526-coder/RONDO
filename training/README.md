# RONDO training assets

`training/` contains lightweight, tracked training contracts and datasets. It
is separate from both product source trees and does not participate in Rust
builds. Model weights and training outputs never belong here.

The current frozen dataset is `local-approval-synthetic-v1/`. Current stage and
handoff are defined only by `doc/WBS.md`.

Plan 037's stage-1 train-only bundle, model/tokenizer identity, candidate LoRA
recipe and RunPod lifecycle are in `local-approval-l6/`. They are preparation
contracts, not evidence that an 8B optimizer smoke or training run occurred.
