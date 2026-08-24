# Plan 060 Publication Critic training qualification

This directory contains only the small, tracked contracts and launch material
for the Plan 060 H100 qualification smoke. Model weights, dependency caches,
checkpoints, remote logs, billing facts, and recovered receipts remain in the
task-only ignored `eval-data/publication-critic/plan060/` namespace.

The candidate recipe is allowed to converge during commissioning. The formal
run is valid only after the actual source archive, complete dependency freeze,
image/runtime facts, model revision, data bundle, and final recipe are frozen
in the task run identity. Commissioning output never counts as formal evidence.

The only training route is BF16, single-GPU, full-parameter
`flashoptim.FlashAdamW` on one Secure 80 GB H100. The two eligible hardware
candidates are `NVIDIA H100 PCIe` and `NVIDIA H100 80GB HBM3`. Capacity is
ranked mechanically as High, then Medium, then Low, with PCIe preferred only
when both candidates have the same stock grade. The first candidate to reach
RUNNING and pass exact provider/hardware checks becomes the immutable winner.
There is no AdamW, PEFT, model quantization, offload, concurrently running
second GPU, or cross-model fallback. A compute replacement after winner lock is
allowed only for the same exact GPU model and reuses the winner's network
volume.

The commissioning candidate uses FlashAdamW's 32-bit effective master-weight
correction. Its pinned Adam numerics heuristic treats `0.1 * learning_rate` as
the minimum effective step and checks every parameter tensor in order. The
real H100 gate first rejected `1e-4` at a `1.557e-5` resolution, then rejected
`2e-4` at a later tensor's `3.114e-5` resolution. The candidate therefore uses
the smallest next simple bounded increase, `4e-4`, whose predicted `4e-5` step
crosses the latest measured gate while preserving `check_numerics=true`. This
is the same fused, quantized-state FlashAdamW route, not an optimizer fallback
or FP32 model copy. The recipe is formal-frozen only after commissioning and
fresh-process recovery pass.

Before every commissioning/formal start or resume update, the runner calls the
pinned optimizer's own `recompute_param_stats()` and per-parameter numerics
checker across the complete optimizer coverage. A passing receipt records the
full checked tensor count. If the configured LR fails anywhere, no update is
attempted and the failure reports the smallest passing power-of-two candidate
found with the same pinned checker, avoiding one paid restart per tensor range.

`model-contract-v1.json` and `model-download-sha256.txt` lock the public model
and exact tokenizer files. `recipe-candidate-v1.json` and
`dependencies-candidate-v1.txt` begin commissioning; their formal identities
are frozen only after the working Pod environment is measured.
`cloud-candidate-v1.json` holds the dual-candidate selection, single-running-GPU
and storage lifecycle contract. The existing stopped local-volume Pod is only a
pre-selection asset source; it is not winner-eligible. The controller may
create at most two task-only 60 GB Standard network volumes. It locks the
winner before training, retains the verified winner volume for reuse, deletes
the loser or superseded volumes, and terminates every compute Pod at task
close. The ignored runtime budget policy is the only adjustable hard-cap
source; controllers derive action cutoffs from fixed cleanup reserves and
reload it before every decision. Live prices, the effective budget value, Pod
IDs/names and data centers are refreshed provider evidence, not frozen training
identity and not reasons to rebuild the training bundle.
`runpod-bootstrap.sh` verifies the unpacked bundle, creates a task-local virtual
environment over the image-provided Torch, installs/verifies the exact
FlashOptim wheel, downloads the exact anonymous Hugging Face revision, and
writes the observed dependency identity. `runpod-training-entrypoint.sh`
executes exactly one commissioning/formal start or resume process with a bounded
timeout. `runpod-launch.sh` supplies the one task-scoped detached PID/log/status
seam for bootstrap and all phases. `runbook.md` owns the operator lifecycle,
the runtime budget/resource gates, winner selection, replacement and cleanup
boundaries.
