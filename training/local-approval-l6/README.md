# Plan 037 stage-1 L6 training scaffold

This is a candidate, not the final training recipe. It binds the official BF16
base/tokenizer revision and the separately frozen official chat template. The
candidate RunPod image is
`runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`; its preinstalled Torch 2.8.0
matches `dependencies-candidate-v1.txt`. The other exact pins remain candidates
until the authorized stage-2 optimizer smoke freezes the installed environment.

From the repository root with `PYTHONPATH=eval`:

```text
python3 -m rondo_eval.local_approval.l6_training mock-dry-run --repo .
python3 -m rondo_eval.local_approval.l6_training prepare-bundle --repo . --output <new-ignored-directory>/bundle
python3 -m rondo_eval.local_approval.l6_training verify-bundle --bundle <bundle>
python3 -m rondo_eval.local_approval.l6_training census --repo . --tokenizer-dir <frozen-tokenizer-directory> --sequence-limit 4096 --output <new-private-file>
```

The bundle's only body-bearing member is the fixed 470-row train projection.
Validation, holdout, seed reference, real `E_final`, unknown files, symlinks,
unlisted bodies, and any projection other than SHA-256
`0026cddd2a80771039c6644378120793d98310abdf66f01e7475416f23b2cc14`
are rejected. No truncation is implemented. The mock path loads no model and
performs zero optimizer steps; it does not stand in for the real 8B smoke.

## Authorized stage-2 lifecycle

The active controller must recheck price/capacity/balance, create no more than
one task Pod with a 100 GB Pod volume by default, record its ID/rate/deadline,
transfer only the verified bundle, and rerun `verify-bundle`. A network volume
is optional only when the selected GPU is in a supported data center (for
example an available L40S location) and it is separately named in stage-2
authorization; it is not the A40 default.

After dependency installation, invoke the entrypoint with
`RONDO_L6_RUN_KIND=smoke`. It forces exactly one optimizer step, writes only to
`<output>/smoke`, and reloads that adapter in a separate process. Stop there:
inspect the evidence, make the one permitted technical convergence, and freeze
an actual recipe (`candidate_status=stage2_final_frozen`) plus a dependency
identity matching the installed packages. A later, explicit invocation with
`RONDO_L6_RUN_KIND=formal` and both frozen file paths writes only to
`<output>/formal`. The script never chains smoke into formal.

The frozen dependency identity has exactly seven direct packages (`torch`,
`transformers`, `peft`, `trl`, `accelerate`, `bitsandbytes`, `safetensors`),
plus Python, CUDA and container-image identities. Formal mode rejects packing,
any quantization drift, and any installed-environment mismatch. If a Pod is
interrupted, `RONDO_L6_RESUME_CHECKPOINT` may name one existing
`<mode>/checkpoints/checkpoint-N` directory. Resume rejects paths outside that
output, symlinks, changed run/recipe/dependency contracts and already-finished
training; without this variable, an existing mode output is always rejected.

`runpod-stage2-entrypoint.sh` adds a three-hour default hard timeout. The
controller must also tail logs, Pod state and billing continuously. No progress,
repeated crash, OOM, identity/projection mismatch or budget drift is a stop
condition. `stop` is only a temporary cost brake while recovering checkpoint
data; after recovery and local hash verification, task-only Pod/template/
credential/temporary volume are deleted and final billing is checked.

Output remains on the 100 GB Pod volume while the controller is active unless
an optional network volume was explicitly authorized. Before Pod deletion,
adapter, necessary checkpoints, final recipe and
dependency identity, aggregate metrics and training receipt are persisted and
downloaded locally; every size/SHA-256 is rechecked. Only
`artifact-export-allowlist-v1.json` paths may enter an approved private HF model
repo. Dataset/projection bodies and per-sample outputs never enter that repo.

Training success first writes `training-pending.json`; it never writes a
completed receipt before adapter reload. The separate reload command writes a
mode-0600 `adapter-reload-receipt.json`. Only the active controller can finish
the state transition after it has the actual billed cost and a concrete
persistence revision:

```text
python3 <bundle>/bin/l6_training.py finalize-receipt --bundle <bundle> --output <mode-output> --actual-runpod-cost-usd <actual> --persistence-kind <pod_volume|network_volume|private_hf_repo|local_download> --persistence-revision <id-or-revision>
python3 <bundle>/bin/l6_training.py verify-artifacts --bundle <bundle> --output <downloaded-output>
```

Finalization rehashes the adapter, checkpoints, actual recipe and dependency
identity, validates the strict receipt schema, and creates a body-free artifact
manifest. The manifest covers every adapter/checkpoint/config/metric/receipt
file and lets a local download be checked file by file. A timeout or failed
reload leaves only pending evidence and logs, never `status=completed`.
