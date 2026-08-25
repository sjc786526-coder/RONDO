"""Frozen Plan 079 identities and the single-base quality decision contract."""

from __future__ import annotations

from collections.abc import Mapping
import math
from pathlib import Path
import re
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from ..selection.contract import publication_quality_floors


MODEL_REPOSITORY = "Skywork/Skywork-Reward-V2-Qwen3-4B"
MODEL_REVISION = "fd958fef475f323f4e6b195930e3dd918485c668"
RUN_SPEC_SCHEMA = "rondo-publication-critic-plan079-run-spec-v1"
RESULT_SCHEMA = "rondo-publication-critic-plan079-base-quality-result-v1"
SCORES_SCHEMA = "rondo-publication-critic-plan079-scores-v1"
MODES = ("commissioning", "formal")
GPU_MODELS = ("NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 3090", "NVIDIA RTX A5000")
RUN_ID = re.compile(
    r"plan079-(commissioning|formal)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z"
)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}\Z")

QUALITY_FLOORS = publication_quality_floors()

RUNTIME_CONTRACT = {
    "device": "cuda",
    "dtype": "bfloat16",
    "context_window": 16_384,
    "padding": "single_packet_right_padded_v1",
    "scalar": "logits[:,0]",
    "projection": "stable_sigmoid_v1",
    "direction": "higher_is_better",
    "warmup_items": 2,
}


class BaseQualityError(RuntimeError):
    """A stable, body-free Plan 079 identity, run, or result failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def require_sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise BaseQualityError(code)
    return value


def require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise BaseQualityError(code)
    return value


def require_count(value: Any, code: str) -> int:
    if type(value) is not int or value < 0:
        raise BaseQualityError(code)
    return value


def require_number(value: Any, code: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise BaseQualityError(code)
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise BaseQualityError(code)
    return number


def run_spec_sha256(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(value)))


def _exact(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise BaseQualityError(code)
    return value


def validate_run_spec(value: Any) -> dict[str, Any]:
    spec = _exact(
        value,
        {
            "schema",
            "mode",
            "run_id",
            "source",
            "model",
            "input",
            "runtime",
            "cloud",
            "quality_floors",
        },
        "run_spec_fields_invalid",
    )
    match = (
        RUN_ID.fullmatch(spec.get("run_id", ""))
        if isinstance(spec.get("run_id"), str)
        else None
    )
    if (
        spec.get("schema") != RUN_SPEC_SCHEMA
        or spec.get("mode") not in MODES
        or match is None
        or match.group(1) != spec["mode"]
        or spec.get("quality_floors") != QUALITY_FLOORS
    ):
        raise BaseQualityError("run_spec_identity_invalid")

    source = _exact(
        spec["source"],
        {
            "git_commit",
            "tracked_source_clean",
            "source_archive_sha256",
            "environment_lock_path",
            "environment_lock_sha256",
        },
        "run_spec_source_fields_invalid",
    )
    if (
        not isinstance(source.get("git_commit"), str)
        or _GIT_COMMIT.fullmatch(source["git_commit"]) is None
    ):
        raise BaseQualityError("run_spec_source_commit_invalid")
    if type(source.get("tracked_source_clean")) is not bool:
        raise BaseQualityError("run_spec_source_clean_invalid")
    if spec["mode"] == "formal" and source["tracked_source_clean"] is not True:
        raise BaseQualityError("formal_source_not_clean")
    require_sha256(
        source.get("source_archive_sha256"), "run_spec_source_archive_invalid"
    )
    require_sha256(
        source.get("environment_lock_sha256"), "run_spec_environment_lock_invalid"
    )
    environment_path = require_text(
        source.get("environment_lock_path"), "run_spec_environment_path_invalid"
    )
    pure = Path(environment_path)
    if pure.is_absolute() or ".." in pure.parts or pure.name != "uv.lock":
        raise BaseQualityError("run_spec_environment_path_invalid")

    model = _exact(
        spec["model"],
        {
            "repository",
            "revision",
            "model_lock_sha256",
            "snapshot_receipt_sha256",
            "snapshot_content_sha256",
        },
        "run_spec_model_fields_invalid",
    )
    if (
        model.get("repository") != MODEL_REPOSITORY
        or model.get("revision") != MODEL_REVISION
    ):
        raise BaseQualityError("run_spec_model_identity_invalid")
    for name in (
        "model_lock_sha256",
        "snapshot_receipt_sha256",
        "snapshot_content_sha256",
    ):
        require_sha256(model.get(name), f"run_spec_{name}_invalid")

    input_value = _exact(
        spec["input"],
        {
            "dataset_revision",
            "bundle_manifest_sha256",
            "release_sha256",
            "candidate_count",
            "boundary_pair_count",
            "within_pass_pair_count",
            "unseen_test_rows_available",
        },
        "run_spec_input_fields_invalid",
    )
    if (
        input_value.get("dataset_revision") != "v8"
        or input_value.get("candidate_count") != 55
        or input_value.get("boundary_pair_count") != 19
        or input_value.get("within_pass_pair_count") != 7
        or input_value.get("unseen_test_rows_available") != 0
    ):
        raise BaseQualityError("run_spec_input_identity_invalid")
    require_sha256(input_value.get("bundle_manifest_sha256"), "run_spec_bundle_invalid")
    require_sha256(input_value.get("release_sha256"), "run_spec_release_invalid")

    runtime = _exact(
        spec["runtime"],
        set(RUNTIME_CONTRACT) | {"cpu_threads"},
        "run_spec_runtime_fields_invalid",
    )
    if any(
        runtime.get(name) != expected for name, expected in RUNTIME_CONTRACT.items()
    ):
        raise BaseQualityError("run_spec_runtime_identity_invalid")
    if type(runtime.get("cpu_threads")) is not int or runtime["cpu_threads"] <= 0:
        raise BaseQualityError("run_spec_cpu_threads_invalid")

    cloud = _exact(
        spec["cloud"],
        {
            "pod_id",
            "network_volume_id",
            "data_center_id",
            "gpu_model",
            "container_image",
            "cuda_host_version",
        },
        "run_spec_cloud_fields_invalid",
    )
    for name in (
        "pod_id",
        "network_volume_id",
        "data_center_id",
        "container_image",
        "cuda_host_version",
    ):
        require_text(cloud.get(name), f"run_spec_cloud_{name}_invalid")
    if cloud.get("gpu_model") not in GPU_MODELS:
        raise BaseQualityError("run_spec_gpu_model_invalid")
    return dict(spec)


def validate_runtime_facts(value: Any) -> dict[str, Any]:
    facts = _exact(
        value,
        {
            "load_seconds",
            "warm_p95_latency_ms",
            "wall_seconds",
            "peak_rss_bytes",
            "peak_vram_allocated_bytes",
            "peak_vram_reserved_bytes",
            "scored_count",
            "typed_failure_count",
            "torch_version",
            "transformers_version",
            "cuda_runtime_version",
            "gpu_name",
            "gpu_capability",
        },
        "runtime_facts_fields_invalid",
    )
    for name in (
        "load_seconds",
        "warm_p95_latency_ms",
        "wall_seconds",
        "peak_rss_bytes",
        "peak_vram_allocated_bytes",
        "peak_vram_reserved_bytes",
    ):
        require_number(facts.get(name), f"runtime_fact_{name}_invalid")
    for name in ("scored_count", "typed_failure_count"):
        require_count(facts.get(name), f"runtime_fact_{name}_invalid")
    for name in (
        "torch_version",
        "transformers_version",
        "cuda_runtime_version",
        "gpu_name",
        "gpu_capability",
    ):
        require_text(facts.get(name), f"runtime_fact_{name}_invalid")
    return dict(facts)
