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
TASK_DEPLOYMENT="$TASK_ROOT/deployments/$TASK_ATTEMPT_ID/$TASK_ROUTE_ATTEMPT"
TASK_CONVERSION_PYTHON="$TASK_ROOT/conversion-venv/bin/python"

finish() {
  local status=$?
  if test "$status" -eq 0; then
    printf 'completed\n' >"$TASK_STATUS_FILE"
  else
    printf 'failed:%s\n' "$status" >"$TASK_STATUS_FILE"
  fi
}
trap finish EXIT

case "$TASK_ROUTE" in
  adapter_on_off | paired_gguf) ;;
  *) echo 'conversion_route_invalid' >&2; exit 2 ;;
esac
test -d "$TASK_DEPLOYMENT"
test -f "$TASK_DEPLOYMENT/conversion-operations.json"
test ! -e "$TASK_DEPLOYMENT/conversion-dependency-identity.json"
test ! -e "$TASK_DEPLOYMENT/conversion-files-manifest.json"
test ! -e "$TASK_DEPLOYMENT/conversion-receipt.json"

"$TASK_CONVERSION_PYTHON" - "$TASK_DEPLOYMENT" "$TASK_ROUTE" <<'PY'
import importlib.metadata as metadata
import json
import pathlib
import platform
import sys
import torch

output = pathlib.Path(sys.argv[1])
route = sys.argv[2]
names = ("numpy", "sentencepiece", "transformers", "protobuf",
         "huggingface-hub", "safetensors", "tqdm", "PyYAML", "requests")
value = {
    "schema_version": 1,
    "version": "rondo_local_approval_l6_conversion_dependency_identity_v1",
    "packages": {name: metadata.version(name) for name in names},
    "python": platform.python_version(),
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
    "container_image": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
    "route": route,
}
(output / "conversion-dependency-identity.json").write_text(
    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)
PY

"$TASK_CONVERSION_PYTHON" - "$TASK_DEPLOYMENT" "$TASK_CONVERSION_TOOLS" \
  "$TASK_ROUTE" "$TASK_FORMAL_OUTPUT/training-receipt.json" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

output = pathlib.Path(sys.argv[1])
tools = pathlib.Path(sys.argv[2])
route = sys.argv[3]
training_path = pathlib.Path(sys.argv[4])
contract_raw = (tools / "contracts/conversion-tool-contract-v1.json").read_bytes()
contract = json.loads(contract_raw)
allowed = set(contract["output_allowlists"][route])

def identity(path):
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SystemExit(f"non_regular_conversion_output:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    after = os.lstat(path)
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    ):
        raise SystemExit(f"changed_conversion_output:{path}")
    return {"size_bytes": info.st_size, "sha256": digest.hexdigest()}

observed = {
    path.relative_to(output).as_posix()
    for path in output.rglob("*") if not path.is_dir()
}
expected = allowed - {"conversion-files-manifest.json", "conversion-receipt.json"}
if observed != expected:
    raise SystemExit("conversion_output_allowlist_mismatch")
files = {name: identity(output / name) for name in sorted(observed)}
manifest = {
    "schema_version": 1,
    "version": "rondo_local_approval_l6_conversion_files_v1",
    "route": route,
    "files": files,
}
manifest_raw = (
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
).encode()
(output / "conversion-files-manifest.json").write_bytes(manifest_raw)
training_raw = training_path.read_bytes()
training = json.loads(training_raw)
receipt = {
    "schema_version": 1,
    "version": "rondo_local_approval_l6_conversion_receipt_v1",
    "status": "completed",
    "route": route,
    "base_model": contract["base_model"],
    "quantization": "Q4_K_M",
    "source_adapter_tree_sha256": training["artifacts"]["adapter"]["tree_sha256"],
    "training_receipt_sha256": hashlib.sha256(training_raw).hexdigest(),
    "conversion_contract_sha256": hashlib.sha256(contract_raw).hexdigest(),
    "tool_bundle_manifest_sha256": hashlib.sha256(
        (tools / "conversion-tool-bundle-manifest.json").read_bytes()
    ).hexdigest(),
    "dependency_identity_sha256": files["conversion-dependency-identity.json"]["sha256"],
    "operations_sha256": files["conversion-operations.json"]["sha256"],
    "files_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
    "deployed_outputs": {
        name: files[name] for name in sorted(files) if name.endswith(".gguf")
    },
    "temporary_f16_and_merged_hf_removed": True,
}
(output / "conversion-receipt.json").write_text(
    json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)
PY

chmod 600 "$TASK_DEPLOYMENT"/*.json "$TASK_DEPLOYMENT"/*.log \
  "$TASK_DEPLOYMENT"/*.gguf \
  "$TASK_DEPLOYMENT/tooling/convert_hf_to_gguf.py"
if test "$TASK_ROUTE" = adapter_on_off; then
  chmod 600 "$TASK_DEPLOYMENT/tooling/convert_lora_to_gguf.py"
else
  chmod 600 "$TASK_DEPLOYMENT/tooling/merge_adapter.py"
fi
chmod 700 "$TASK_DEPLOYMENT/tooling/llama-quantize"
"$TASK_CONVERSION_PYTHON" -B \
  "$TASK_CONVERSION_TOOLS/bin/conversion_tooling.py" verify-output \
  --contract "$TASK_CONVERSION_TOOLS/contracts/conversion-tool-contract-v1.json" \
  --tool-bundle "$TASK_CONVERSION_TOOLS" \
  --output "$TASK_DEPLOYMENT" \
  --training-receipt "$TASK_FORMAL_OUTPUT/training-receipt.json"
