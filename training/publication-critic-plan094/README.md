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
single-task Pod seams.  `runpod-lifecycle-guard.py` is the matching host-only
stop-cost fallback: it detaches from the operator session, waits for one
creation-time absolute deadline, then reuses the Plan 087 terminal helper for
exact stop/delete and zero-Pod confirmation.  It does not create a Pod.  Stage
B commands fail closed unless `RONDO_PLAN094_STAGE_B_APPROVED=1`; the operator
may set it only after all current approval conditions are met.  The paid stage
is presently paused by the user, so Stage A technical acceptance does not
satisfy those conditions.  Bootstrap and every later paid command require a
fresh task-owned budget snapshot, verified compute/storage rates, a finite
timeout, and the same immutable lifecycle authorization.  Budget bounds include
worker kill grace and terminal-confirmation reserve as well as active runtime.

No model, checkpoint, cache, virtual environment, raw result, or secret belongs
in this tracked directory.  Large artifacts remain under the independent
`/workspace/rondo-plan094-*` root on volume `mwemzrn33y`; only small results and
receipts are returned.
