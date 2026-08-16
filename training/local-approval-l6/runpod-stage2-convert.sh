#!/usr/bin/env bash
set -euo pipefail
umask 077
export PYTHONDONTWRITEBYTECODE=1

TASK_ROOT="${TASK_ROOT:-/workspace/rondo-l6}"
: "${TASK_ATTEMPT_ID:?TASK_ATTEMPT_ID is required}"
: "${TASK_ROUTE:?TASK_ROUTE is required}"
: "${TASK_ROUTE_ATTEMPT:?TASK_ROUTE_ATTEMPT is required}"
: "${TASK_STATUS_FILE:?TASK_STATUS_FILE is required}"

TASK_FORMAL_OUTPUT="$TASK_ROOT/runs/$TASK_ATTEMPT_ID/formal"
TASK_CONVERSION_TOOLS="$TASK_ROOT/conversion-tool-bundle"
TASK_CONVERTER_ROOT="$TASK_CONVERSION_TOOLS/tools/llama.cpp"
TASK_QUANTIZER_ROOT="$TASK_CONVERSION_TOOLS/tools/llama-b10333-cpu"
TASK_DEPLOYMENT="$TASK_ROOT/deployments/$TASK_ATTEMPT_ID/$TASK_ROUTE_ATTEMPT"
TASK_BASE_DIR="$TASK_ROOT/hf-home/hub/models--mistralai--Ministral-3-8B-Instruct-2512-BF16/snapshots/f6fae9795746f63c9be8344932f01275f3c63734"
TASK_CONVERSION_PYTHON="$TASK_ROOT/conversion-venv/bin/python"
TASK_TRAINING_PYTHON="$TASK_ROOT/venv/bin/python"

case "$TASK_ROUTE" in
  adapter_on_off) TASK_REQUIRED_FREE_GB=45 ;;
  paired_gguf) TASK_REQUIRED_FREE_GB=65 ;;
  *) echo 'conversion_route_invalid' >&2; exit 2 ;;
esac

finish() {
  local status=$?
  if test "$status" -eq 0; then
    printf 'completed\n' >"$TASK_STATUS_FILE"
  else
    printf 'failed:%s\n' "$status" >"$TASK_STATUS_FILE"
  fi
}
trap finish EXIT

test -f "$TASK_FORMAL_OUTPUT/training-receipt.json"
test "$(jq -r .status "$TASK_FORMAL_OUTPUT/training-receipt.json")" = completed
test ! -e "$TASK_DEPLOYMENT"
test -f "$TASK_BASE_DIR/model.safetensors.index.json"
TASK_AVAILABLE_BYTES="$(df -B1 --output=avail /workspace | tail -n1 | tr -d ' ')"
test "$TASK_AVAILABLE_BYTES" -ge "$((TASK_REQUIRED_FREE_GB * 1000 * 1000 * 1000))"

install -d -m 700 "$TASK_DEPLOYMENT/tooling" "$TASK_DEPLOYMENT/work"
install -m 600 "$TASK_CONVERTER_ROOT/convert_hf_to_gguf.py" \
  "$TASK_DEPLOYMENT/tooling/convert_hf_to_gguf.py"
install -m 700 "$TASK_QUANTIZER_ROOT/llama-quantize" \
  "$TASK_DEPLOYMENT/tooling/llama-quantize"
if test "$TASK_ROUTE" = adapter_on_off; then
  install -m 600 "$TASK_CONVERTER_ROOT/convert_lora_to_gguf.py" \
    "$TASK_DEPLOYMENT/tooling/convert_lora_to_gguf.py"
else
  install -m 600 "$TASK_CONVERSION_TOOLS/bin/merge_adapter.py" \
    "$TASK_DEPLOYMENT/tooling/merge_adapter.py"
fi

export HF_HOME="$TASK_ROOT/hf-home"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$TASK_CONVERTER_ROOT/gguf-py"

"$TASK_CONVERSION_PYTHON" -B "$TASK_CONVERTER_ROOT/convert_hf_to_gguf.py" \
  --outfile "$TASK_DEPLOYMENT/work/base-f16.gguf" --outtype f16 \
  --use-temp-file "$TASK_BASE_DIR" \
  2>&1 | tee "$TASK_DEPLOYMENT/base-convert.log"
"$TASK_QUANTIZER_ROOT/llama-quantize" \
  "$TASK_DEPLOYMENT/work/base-f16.gguf" \
  "$TASK_DEPLOYMENT/base-q4_k_m.gguf" Q4_K_M \
  2>&1 | tee "$TASK_DEPLOYMENT/base-quantize.log"
test -s "$TASK_DEPLOYMENT/base-q4_k_m.gguf"
rm -f -- "$TASK_DEPLOYMENT/work/base-f16.gguf"
test "$(df -B1 --output=avail /workspace | tail -n1 | tr -d ' ')" \
  -ge 20000000000

if test "$TASK_ROUTE" = adapter_on_off; then
  TASK_SOURCE_ADAPTER_BYTES="$(jq -er \
    '[.artifacts.adapter.files[].bytes] | add | select(type == "number" and . > 0)' \
    "$TASK_FORMAL_OUTPUT/training-receipt.json")"
  TASK_ADAPTER_MAX_BYTES="$((TASK_SOURCE_ADAPTER_BYTES * 8 + 64000000))"
  TASK_ADAPTER_LOG="$TASK_DEPLOYMENT/adapter-convert.log"
  "$TASK_CONVERSION_PYTHON" -B "$TASK_CONVERTER_ROOT/convert_lora_to_gguf.py" \
    --base "$TASK_BASE_DIR" \
    --outfile "$TASK_DEPLOYMENT/adapter-f16.gguf" --outtype f16 \
    "$TASK_FORMAL_OUTPUT/adapter-final" \
    >"$TASK_ADAPTER_LOG" 2>&1 &
  TASK_ADAPTER_PID="$!"
  TASK_ADAPTER_POLL=0
  while kill -0 "$TASK_ADAPTER_PID" 2>/dev/null; do
    if test -f "$TASK_DEPLOYMENT/adapter-f16.gguf"; then
      TASK_ADAPTER_BYTES="$(stat -c '%s' \
        "$TASK_DEPLOYMENT/adapter-f16.gguf")"
      if test "$TASK_ADAPTER_BYTES" -gt "$TASK_ADAPTER_MAX_BYTES"; then
        kill "$TASK_ADAPTER_PID" 2>/dev/null || true
        wait "$TASK_ADAPTER_PID" || true
        tail -n 50 "$TASK_ADAPTER_LOG"
        printf 'adapter_conversion_size_guard_exceeded:%s:%s\n' \
          "$TASK_ADAPTER_BYTES" "$TASK_ADAPTER_MAX_BYTES" >&2
        exit 24
      fi
      if test "$((TASK_ADAPTER_POLL % 5))" -eq 0; then
        printf 'adapter_conversion_bytes=%s max_bytes=%s\n' \
          "$TASK_ADAPTER_BYTES" "$TASK_ADAPTER_MAX_BYTES"
      fi
    fi
    TASK_ADAPTER_POLL="$((TASK_ADAPTER_POLL + 1))"
    sleep 2
  done
  if ! wait "$TASK_ADAPTER_PID"; then
    tail -n 50 "$TASK_ADAPTER_LOG"
    exit 1
  fi
  cat "$TASK_ADAPTER_LOG"
  test -s "$TASK_DEPLOYMENT/adapter-f16.gguf"
  test "$(stat -c '%s' "$TASK_DEPLOYMENT/adapter-f16.gguf")" \
    -le "$TASK_ADAPTER_MAX_BYTES"
else
  "$TASK_TRAINING_PYTHON" -B "$TASK_DEPLOYMENT/tooling/merge_adapter.py" \
    --base "$TASK_BASE_DIR" \
    --adapter "$TASK_FORMAL_OUTPUT/adapter-final" \
    --output "$TASK_DEPLOYMENT/work/merged-hf" \
    2>&1 | tee "$TASK_DEPLOYMENT/merge.log"
  cmp "$TASK_BASE_DIR/tokenizer.json" \
    "$TASK_DEPLOYMENT/work/merged-hf/tokenizer.json"
  cmp "$TASK_BASE_DIR/tokenizer_config.json" \
    "$TASK_DEPLOYMENT/work/merged-hf/tokenizer_config.json"
  "$TASK_CONVERSION_PYTHON" -B "$TASK_CONVERTER_ROOT/convert_hf_to_gguf.py" \
    --outfile "$TASK_DEPLOYMENT/work/finetuned-f16.gguf" --outtype f16 \
    --use-temp-file "$TASK_DEPLOYMENT/work/merged-hf" \
    2>&1 | tee "$TASK_DEPLOYMENT/finetuned-convert.log"
  "$TASK_QUANTIZER_ROOT/llama-quantize" \
    "$TASK_DEPLOYMENT/work/finetuned-f16.gguf" \
    "$TASK_DEPLOYMENT/finetuned-q4_k_m.gguf" Q4_K_M \
    2>&1 | tee "$TASK_DEPLOYMENT/finetuned-quantize.log"
  test -s "$TASK_DEPLOYMENT/finetuned-q4_k_m.gguf"
  rm -rf -- "$TASK_DEPLOYMENT/work/merged-hf"
  rm -f -- "$TASK_DEPLOYMENT/work/finetuned-f16.gguf"
fi
rmdir "$TASK_DEPLOYMENT/work"

"$TASK_CONVERSION_PYTHON" -B \
  "$TASK_CONVERSION_TOOLS/bin/conversion_tooling.py" write-operations \
  --contract "$TASK_CONVERSION_TOOLS/contracts/conversion-tool-contract-v1.json" \
  --tool-bundle "$TASK_CONVERSION_TOOLS" \
  --output "$TASK_DEPLOYMENT" \
  --training-receipt "$TASK_FORMAL_OUTPUT/training-receipt.json" \
  --route "$TASK_ROUTE" \
  --base-snapshot "$TASK_BASE_DIR" \
  --formal-output "$TASK_FORMAL_OUTPUT" \
  --conversion-python "$TASK_CONVERSION_PYTHON" \
  --training-python "$TASK_TRAINING_PYTHON"
