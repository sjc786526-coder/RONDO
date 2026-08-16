# Plan 037 L6 training and paired-deployment scaffold

The operator-ready A-J command sequence is in
[`stage2-runbook.md`](stage2-runbook.md). Local stage-2A conversion preparation
is allowed; Pod creation, transfer, model download, training, conversion/model
loading and every remote mutation remain forbidden until separately authorized.

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

LoRA injection is fixed to the Transformers 5.14.1 runtime language-module
names through one PEFT string regex. After injection, every targeted module and
every trainable LoRA parameter is checked against that regex; any vision,
projector or `lm_head` hit fails the run.

`runpod-stage2-entrypoint.sh` adds a three-hour default hard timeout. The
controller must also tail logs, Pod state and billing continuously. A first
ordinary technical failure such as OOM triggers diagnosis and one evidenced
recovery or permitted convergence; blind repetition without progress is
forbidden. Budget, identity, data-boundary or projection drift stops the run
immediately. `stop` is only a temporary cost brake while recovering checkpoint
data; after recovery and local hash verification, task-only Pod/template/
credential/temporary volume are deleted and final billing is checked.

Output remains on the 100 GB Pod volume while the controller is active unless
an optional network volume was explicitly authorized. Before Pod deletion,
adapter, necessary checkpoints, final recipe and dependency identity,
aggregate metrics and training receipt are persisted and downloaded locally;
every size/SHA-256 is rechecked. The owner confirms the personal HF account's
included 100 GB is unused and authorizes zero-incremental-cost HF features as a
contingency; local SCP remains the default, and any private mirror first needs
an exact staging verifier. HF compute, paid features, dataset/projection bodies
and per-sample outputs remain outside this route.

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
If the controller stops after writing the manifest but before the completed
receipt, rerunning finalization accepts only a byte-identical orphan manifest.

## Conversion and paired deployment

`conversion-tool-contract-v1.json` binds the actual b10333 converter source,
the tracked `merge_adapter.py`, minimal CPU `llama-quantize` closure, local
qualified CUDA `llama-server`, conversion-only dependency pins and exact output
allowlists.
`conversion_tooling.py prepare` creates a body-free upload bundle; its manifest
cannot authorize an unknown file, missing file, changed converter tree or extra
symlink. `write-operations` records canonical route-specific argv and every
executed tool identity in `conversion-operations.json`; the conversion receipt
binds its SHA-256. `verify-output` requires the exact tool bundle, streams every
deployment hash, rejects smoke/non-frozen training evidence, verifies pinned
conversion Python/package/Torch/CUDA/image identity, and binds the route receipt
to the completed training receipt and source adapter tree.

Conversion starts only after the completed formal training output has first
been downloaded and verified. It writes to a separate deployment directory,
never below formal output. Both candidate routes are implemented in the
runbook: `adapter_on_off` uses the same Q4_K_M base for both sides and adds one
F16 LoRA GGUF to the fine-tuned side; `paired_gguf` derives two distinct
Q4_K_M files from that same source base and adapter. Neither route changes the
training receipt if conversion fails.

After a separately authorized conversion, the deployment is downloaded and
verified, then the same Pod is stopped with its volume retained while the local
b10333 glue builds canonical deployment manifests and runs a two-sample
structural smoke. Any legal terminal union passes this compatibility/lifecycle
gate; decision counts are diagnostic and cannot select a route. A proven
adapter conversion/load incompatibility continues or restarts that same Pod
and uses an independent paired-GGUF attempt without retraining.
Once either route passes smoke, the Pod is deleted before 130 inputs per side
run serially, the 390 three-side rows are assembled and formally re-imported.
Typed sample failures remain typed; an unexpected dangling infrastructure
attempt requires the explicit `resolve-interrupted` command. Both manifests
use the shared `conversion-operations.json` as converter identity and the real quantizer
binary as quantizer identity. Train, validation and holdout bodies and
per-sample outputs never enter the conversion tool bundle or any future
separately authorized HF mirror.
