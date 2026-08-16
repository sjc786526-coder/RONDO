#!/usr/bin/env bash
set -eu

# Run only inside a separately authorized stage-2 RunPod Pod. Credentials are
# injected by the Pod and are never read from a repository env file.
: "${RONDO_L6_BUNDLE:?set RONDO_L6_BUNDLE to the unpacked train-only bundle}"
: "${RONDO_L6_OUTPUT:?set RONDO_L6_OUTPUT to persistent task output}"
: "${RONDO_L6_RUN_ID:?set RONDO_L6_RUN_ID}"
: "${RONDO_L6_POD_ID:?set RONDO_L6_POD_ID}"
: "${RONDO_L6_GPU:?set RONDO_L6_GPU}"
: "${RONDO_L6_RUN_KIND:?set RONDO_L6_RUN_KIND to smoke or formal}"

RONDO_L6_MAX_SECONDS="${RONDO_L6_MAX_SECONDS:-10800}"
case "$RONDO_L6_MAX_SECONDS" in
  ''|*[!0-9]*) echo '{"status":"failed","code":"invalid_timeout"}' >&2; exit 2 ;;
esac

python3 "$RONDO_L6_BUNDLE/bin/l6_training.py" verify-bundle \
  --bundle "$RONDO_L6_BUNDLE"

case "$RONDO_L6_RUN_KIND" in
  smoke)
    RONDO_L6_RUN_OUTPUT="$RONDO_L6_OUTPUT/smoke"
    set --
    ;;
  formal)
    : "${RONDO_L6_FINAL_RECIPE:?formal requires RONDO_L6_FINAL_RECIPE}"
    : "${RONDO_L6_DEPENDENCY_IDENTITY:?formal requires RONDO_L6_DEPENDENCY_IDENTITY}"
    RONDO_L6_RUN_OUTPUT="$RONDO_L6_OUTPUT/formal"
    set -- --final-recipe "$RONDO_L6_FINAL_RECIPE" \
      --dependency-identity "$RONDO_L6_DEPENDENCY_IDENTITY"
    ;;
  *) echo '{"status":"failed","code":"invalid_run_kind"}' >&2; exit 2 ;;
esac

if [ -n "${RONDO_L6_RESUME_CHECKPOINT:-}" ]; then
  set -- "$@" --resume-from-checkpoint "$RONDO_L6_RESUME_CHECKPOINT"
fi

# This invocation performs exactly one selected mode. After smoke, the active
# controller must stop here for technical convergence and explicit final
# recipe/dependency freeze before invoking this script again with formal.
timeout --signal=TERM --kill-after=300 "${RONDO_L6_MAX_SECONDS}" \
  python3 "$RONDO_L6_BUNDLE/bin/l6_training.py" train \
    --bundle "$RONDO_L6_BUNDLE" \
    --output "$RONDO_L6_RUN_OUTPUT" \
    --run-kind "$RONDO_L6_RUN_KIND" \
    --run-id "$RONDO_L6_RUN_ID" \
    --provider-job-id "$RONDO_L6_POD_ID" \
    --hardware-name "$RONDO_L6_GPU" \
    "$@"

# Separate process: stage-2 smoke and formal training each use this to prove
# that the saved adapter can be rediscovered and loaded.
python3 "$RONDO_L6_BUNDLE/bin/l6_training.py" reload-adapter \
  --bundle "$RONDO_L6_BUNDLE" \
  --output "$RONDO_L6_RUN_OUTPUT"

# Successful training deliberately leaves training-pending.json plus an
# independent adapter-reload-receipt.json. The controller must supply actual
# RunPod cost and persisted-object identity to finalize-receipt; timeout or
# failure can therefore never masquerade as a completed training receipt.
