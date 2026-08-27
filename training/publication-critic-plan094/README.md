# Publication Critic Plan 094

This directory is the tracked, weight-free operator surface for the exact 1.7B
Route O continuous-training task.  The authoritative task contract is
`plan/094-publication-critic-route-o-continuous-training-execplan.md`; the
machine-readable pre-result contract is `continuous-freeze-v1.json`.

The Python entry point is:

```bash
PYTHONPATH=eval python3 -B -m \
  rondo_eval.publication_critic.full_model_training.plan094_cli --help
```

`runpod-bootstrap.sh`, `runpod-launch.sh`, and `runpod-worker.sh` are narrow
single-task seams.  They do not create or release a Pod.  Stage B commands
fail closed unless `RONDO_PLAN094_STAGE_B_APPROVED=1`; the operator may set it
only after the reviewer sends the exact approval required by the ExecPlan.

No model, checkpoint, cache, virtual environment, raw result, or secret belongs
in this tracked directory.  Large artifacts remain under the independent
`/workspace/rondo-plan094-*` root on volume `mwemzrn33y`; only small results and
receipts are returned.
