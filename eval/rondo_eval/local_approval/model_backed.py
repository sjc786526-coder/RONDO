"""Versioned model-backed qualification evidence and its capability projection.

Plan 018 froze one CUDA runtime and one GGUF; Plan 030 froze the 12k serving
contract that qualification now binds.  This module is the single place that
spells those values out, so the production launcher, the restricted
qualification path, the evidence loader and the tests cannot drift apart.  The
frozen CUDA base lock stays a model-free build record; model-backed capability
comes only from the separate evidence written here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config import ConfigError, RuntimeConfig
from ..evidence import (
    STATIC_DECISION_SCHEMA,
    STATIC_INSTRUCTIONS,
    STATIC_PAYLOAD_SCHEMA_VERSION,
)


EVIDENCE_SCHEMA_VERSION = 2
EVIDENCE_RELATIVE_PATH = "eval/locks/local-approval-b10333-ministral-12k-v1.json"
GPU_MODEL_SERVING_CAPABILITY = "gpu_model_serving_validated"
MODEL_BACKED_VALIDATED = "structured_output_validated"
MODEL_BACKED_NOT_RUN = "not_run"
MODEL_BACKED_EVIDENCE_INVALID = "evidence_invalid"
MODEL_BACKED_IDENTITY_MISMATCH = "evidence_identity_mismatch"

CUDA_RUNTIME_RELATIVE_PATH = "eval-data/tools/llama-b10333-cuda-linux-x64"
CUDA_SERVER_RELATIVE_PATH = f"{CUDA_RUNTIME_RELATIVE_PATH}/llama-server"
# The exact source build reports `version: 1 (0865990)`; the upstream CPU
# release bundle reports `version: 10333 (08659901c)`.  llama.cpp renders
# `/props.build_info` as "b<build number>-<commit>".
CUDA_SERVICE_BUILD_INFO = "b1-0865990"
CPU_SERVICE_BUILD_INFO = "b10333-08659901c"

MODEL_RELATIVE_PATH = (
    "eval-data/models/mistralai_Ministral-3-8B-Instruct-2512-Q4_K_M.gguf"
)
MODEL_SIZE_BYTES = 5_198_387_456
MODEL_SHA256 = "7deb50ecb3afca928f0aa6dccdb87ed4ce4ab3991797e5fc0e0dedb92754802a"
# The frozen 12k serving profile.  `context_size` and `max_output_tokens` are
# route decisions and never move; the remaining values were explored on this
# 8GB machine during qualification and then frozen here, so the configuration,
# the launch fingerprint and the evidence identity must all agree exactly.
QUALIFIED_CONTEXT_SIZE = 12288
QUALIFIED_MAX_OUTPUT_TOKENS = 512
QUALIFIED_GPU_LAYERS: int | str = "auto"
QUALIFIED_FIT = "on"
QUALIFIED_BATCH_SIZE = 512
QUALIFIED_UBATCH_SIZE = 256
QUALIFIED_FLASH_ATTENTION = "on"
QUALIFIED_CACHE_TYPE_K = "f16"
QUALIFIED_CACHE_TYPE_V = "f16"

_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_EVIDENCE_BYTES = 65_536


def serving_contract() -> dict[str, Any]:
    """The exact serving values every path has to agree on, in one place."""

    return {
        "context_size": QUALIFIED_CONTEXT_SIZE,
        "gpu_layers": QUALIFIED_GPU_LAYERS,
        "fit": QUALIFIED_FIT,
        "batch_size": QUALIFIED_BATCH_SIZE,
        "ubatch_size": QUALIFIED_UBATCH_SIZE,
        "flash_attention": QUALIFIED_FLASH_ATTENTION,
        "cache_type_k": QUALIFIED_CACHE_TYPE_K,
        "cache_type_v": QUALIFIED_CACHE_TYPE_V,
    }


class QualificationContractError(ConfigError):
    """Raised when the configured identity is not the frozen 12k combination."""


class EvidenceLockError(ConfigError):
    """Raised when model-backed evidence exists but cannot be trusted."""


@dataclass(frozen=True)
class QualificationIdentity:
    """Stable identity that must keep matching for every later projection."""

    runtime_relative_path: str
    runtime_identity_sha256: str
    model_relative_path: str
    model_size_bytes: int
    model_sha256: str
    chat_template_sha256: str
    static_payload_schema_version: int
    context_size: int
    gpu_layers: int | str
    fit: str
    batch_size: int
    ubatch_size: int
    flash_attention: str
    cache_type_k: str
    cache_type_v: str
    serve_config_sha256: str
    request_contract_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelBackedEvidence:
    identity: QualificationIdentity
    observed: dict[str, Any]
    cleanup: dict[str, bool]
    qualified_on: str

    def matches(self, identity: QualificationIdentity) -> bool:
        return self.identity == identity


def request_contract_sha256(settings: Any) -> str:
    """Bind only what changes how a static decision is produced and checked.

    This covers both halves of the request contract: the input payload version
    that decides which bytes are sent, and the decision schema plus sampling
    that decide how the answer is produced and validated.  A later static
    payload version therefore invalidates this qualification automatically.

    `timeout_seconds` is deliberately excluded: it is client-side patience and
    does not change the model, the sampling or the validated schema.
    """

    canonical = {
        "schema_version": 2,
        "static_payload_schema_version": STATIC_PAYLOAD_SCHEMA_VERSION,
        "static_instructions": STATIC_INSTRUCTIONS,
        "static_decision_schema": STATIC_DECISION_SCHEMA,
        "request": {
            "stream": False,
            "structured_output": True,
            "max_retries": 0,
            "temperature": float(settings.temperature),
            "top_p": float(settings.top_p),
            "seed": int(settings.seed),
            "max_output_tokens": int(settings.max_output_tokens),
        },
    }
    raw = json.dumps(
        canonical, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def service_build_info(settings: Any) -> str:
    """Return the exact `/props.build_info` for the configured backend."""

    if settings.binary == CUDA_SERVER_RELATIVE_PATH:
        return CUDA_SERVICE_BUILD_INFO
    return CPU_SERVICE_BUILD_INFO


def qualified_model_path(config: RuntimeConfig) -> Path:
    return config.paths.common_root / MODEL_RELATIVE_PATH


def require_qualification_contract(
    config: RuntimeConfig, settings: Any
) -> None:
    """Reject anything that is not the frozen runtime, GGUF and 12k contract.

    This runs before any model process is started, in the restricted
    qualification path as well as in the evidence identity projection.
    """

    if settings.binary != CUDA_SERVER_RELATIVE_PATH:
        raise QualificationContractError(
            "qualification requires the frozen b10333 CUDA runtime"
        )
    contract = serving_contract()
    if {key: getattr(settings, key) for key in contract} != contract:
        raise QualificationContractError(
            "qualification requires the frozen 12k serving contract"
        )
    if settings.max_output_tokens != QUALIFIED_MAX_OUTPUT_TOKENS:
        raise QualificationContractError(
            "qualification requires the frozen 512-token output budget"
        )
    if settings.model_sha256 != MODEL_SHA256:
        raise QualificationContractError("qualification requires the frozen GGUF digest")
    expected = qualified_model_path(config)
    configured = Path(settings.model_path)
    if not configured.is_absolute():
        configured = config.paths.common_root / configured
    try:
        if configured.resolve(strict=True) != expected.resolve(strict=True):
            raise QualificationContractError(
                "qualification requires the frozen GGUF path"
            )
        info = os.lstat(expected)
    except OSError as exc:
        raise QualificationContractError(
            "the frozen GGUF is unavailable"
        ) from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or info.st_size != MODEL_SIZE_BYTES
    ):
        raise QualificationContractError(
            "the frozen GGUF must be a regular file of the exact frozen size"
        )


def build_identity(
    settings: Any,
    *,
    runtime_identity_sha256: str,
    serve_config_sha256: str,
) -> QualificationIdentity:
    return QualificationIdentity(
        runtime_relative_path=CUDA_RUNTIME_RELATIVE_PATH,
        runtime_identity_sha256=runtime_identity_sha256,
        model_relative_path=MODEL_RELATIVE_PATH,
        model_size_bytes=MODEL_SIZE_BYTES,
        model_sha256=settings.model_sha256,
        chat_template_sha256=settings.chat_template_sha256,
        static_payload_schema_version=STATIC_PAYLOAD_SCHEMA_VERSION,
        context_size=settings.context_size,
        gpu_layers=settings.gpu_layers,
        fit=settings.fit,
        batch_size=settings.batch_size,
        ubatch_size=settings.ubatch_size,
        flash_attention=settings.flash_attention,
        cache_type_k=settings.cache_type_k,
        cache_type_v=settings.cache_type_v,
        serve_config_sha256=serve_config_sha256,
        request_contract_sha256=request_contract_sha256(settings),
    )


def evidence_path(config: RuntimeConfig) -> Path:
    return config.paths.worktree_root / EVIDENCE_RELATIVE_PATH


def evidence_exists(config: RuntimeConfig) -> bool:
    path = evidence_path(config)
    return path.is_symlink() or path.exists()


def load_model_backed_evidence(config: RuntimeConfig) -> ModelBackedEvidence | None:
    """Return strictly validated evidence, or None when none is recorded."""

    path = evidence_path(config)
    if path.is_symlink():
        raise EvidenceLockError("model-backed evidence must not be a symlink")
    if not path.exists():
        return None
    if not path.is_file():
        raise EvidenceLockError("model-backed evidence is not a regular file")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceLockError("model-backed evidence is unreadable") from exc
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise EvidenceLockError("model-backed evidence is too large")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceLockError("model-backed evidence is not valid JSON") from exc
    return _parse_evidence(value)


def _parse_evidence(value: Any) -> ModelBackedEvidence:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "capability",
        "model_backed_structured_output",
        "qualified_on",
        "identity",
        "observed",
        "cleanup",
    }:
        raise EvidenceLockError("model-backed evidence schema differs")
    if (
        value["schema_version"] != EVIDENCE_SCHEMA_VERSION
        or isinstance(value["schema_version"], bool)
        or value["capability"] != GPU_MODEL_SERVING_CAPABILITY
        or value["model_backed_structured_output"] != MODEL_BACKED_VALIDATED
        or not isinstance(value["qualified_on"], str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["qualified_on"]) is None
    ):
        raise EvidenceLockError("model-backed evidence header is invalid")
    identity = _parse_identity(value["identity"])
    observed = _parse_observed(value["observed"])
    cleanup = _parse_cleanup(value["cleanup"])
    return ModelBackedEvidence(identity, observed, cleanup, value["qualified_on"])


def _parse_identity(value: Any) -> QualificationIdentity:
    fields = set(QualificationIdentity.__dataclass_fields__)
    if not isinstance(value, dict) or set(value) != fields:
        raise EvidenceLockError("model-backed evidence identity schema differs")
    contract = serving_contract()
    if any(isinstance(value[key], bool) for key in contract):
        # `True == 1` would otherwise satisfy an integer serving value.
        raise EvidenceLockError("model-backed evidence identity has a boolean value")
    if (
        value["runtime_relative_path"] != CUDA_RUNTIME_RELATIVE_PATH
        or value["model_relative_path"] != MODEL_RELATIVE_PATH
        or value["model_size_bytes"] != MODEL_SIZE_BYTES
        or value["model_sha256"] != MODEL_SHA256
        or value["static_payload_schema_version"] != STATIC_PAYLOAD_SCHEMA_VERSION
        or {key: value[key] for key in contract} != contract
    ):
        raise EvidenceLockError(
            "model-backed evidence identity is not the frozen 12k contract"
        )
    for key in (
        "runtime_identity_sha256",
        "chat_template_sha256",
        "serve_config_sha256",
        "request_contract_sha256",
    ):
        _require_sha256(value[key], key)
    return QualificationIdentity(**value)


def _parse_observed(value: Any) -> dict[str, Any]:
    expected = {
        "service_build_info",
        "model_loaded",
        "cuda_device",
        "gpu_offloaded_layers",
        "gpu_total_layers",
        "effective_context_size",
        "vram",
        "time_to_first_token_ms",
        "ttft_method",
        "total_decision_ms",
        "structured_response",
        "evidence_source",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise EvidenceLockError("model-backed evidence observations schema differs")
    if (
        value["service_build_info"] != CUDA_SERVICE_BUILD_INFO
        or value["model_loaded"] is not True
        or not isinstance(value["cuda_device"], str)
        or not value["cuda_device"]
        or not _positive_int(value["gpu_offloaded_layers"])
        or not _positive_int(value["gpu_total_layers"])
        or value["gpu_offloaded_layers"] > value["gpu_total_layers"]
        or value["effective_context_size"] != QUALIFIED_CONTEXT_SIZE
        or not isinstance(value["ttft_method"], str)
        or not value["ttft_method"]
        or not _positive_number(value["time_to_first_token_ms"])
        or not _positive_number(value["total_decision_ms"])
        or value["time_to_first_token_ms"] > value["total_decision_ms"]
    ):
        raise EvidenceLockError("model-backed evidence observations are invalid")
    _parse_vram(value["vram"])
    _parse_structured_response(value["structured_response"])
    _parse_evidence_source(value["evidence_source"])
    return dict(value)


def _parse_vram(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "baseline_bytes",
        "peak_bytes",
        "delta_bytes",
        "method",
    }:
        raise EvidenceLockError("model-backed evidence VRAM schema differs")
    if (
        not _positive_int(value["peak_bytes"])
        or not isinstance(value["baseline_bytes"], int)
        or isinstance(value["baseline_bytes"], bool)
        or value["baseline_bytes"] < 0
        or value["delta_bytes"] != value["peak_bytes"] - value["baseline_bytes"]
        or value["delta_bytes"] <= 0
        or not isinstance(value["method"], str)
        or not value["method"]
    ):
        raise EvidenceLockError("model-backed evidence VRAM sample is invalid")


def _parse_structured_response(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_name",
        "valid",
        "outcome_in_enum",
        "rationale_non_empty",
        "risk_tag_count",
        "response_sha256",
    }:
        raise EvidenceLockError("model-backed evidence response schema differs")
    if (
        value["schema_name"] != "rondo_static_approval_v1"
        or value["valid"] is not True
        or value["outcome_in_enum"] is not True
        or value["rationale_non_empty"] is not True
        or not isinstance(value["risk_tag_count"], int)
        or isinstance(value["risk_tag_count"], bool)
        or not 0 <= value["risk_tag_count"] <= 16
    ):
        raise EvidenceLockError("model-backed structured response is not compliant")
    _require_sha256(value["response_sha256"], "response digest")


def _parse_evidence_source(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "relative_path",
        "sha256",
        "meta_sha256",
        "review_id",
        "request_shape",
        "guardian_source_baseline",
        "guardian_source_commit",
    }:
        raise EvidenceLockError("model-backed evidence source schema differs")
    relative = value["relative_path"]
    if (
        not isinstance(relative, str)
        or not relative.startswith("eval-data/runs/")
        or not relative.endswith("/E_final.json")
        or ".." in Path(relative).parts
        or value["request_shape"] not in {"standard", "responses_lite"}
        or not isinstance(value["review_id"], str)
        or not value["review_id"]
        or not isinstance(value["guardian_source_baseline"], str)
        or not value["guardian_source_baseline"]
        or not isinstance(value["guardian_source_commit"], str)
        or re.fullmatch(r"[0-9a-f]{40}", value["guardian_source_commit"]) is None
    ):
        raise EvidenceLockError("model-backed evidence source is invalid")
    _require_sha256(value["sha256"], "E_final digest")
    _require_sha256(value["meta_sha256"], "E_final meta digest")


def _parse_cleanup(value: Any) -> dict[str, bool]:
    expected = {
        "server_stopped",
        "port_released",
        "receipt_cleared",
        "private_artifacts_removed",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise EvidenceLockError("model-backed evidence cleanup schema differs")
    if any(value[key] is not True for key in expected):
        raise EvidenceLockError("model-backed evidence records an incomplete cleanup")
    return dict(value)


def _require_sha256(value: Any, label: str) -> None:
    if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
        raise EvidenceLockError(f"model-backed evidence {label} is invalid")


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _positive_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
        and value == value
        and value not in {float("inf"), float("-inf")}
    )


def evidence_document(
    identity: QualificationIdentity,
    observed: Mapping[str, Any],
    cleanup: Mapping[str, bool],
    *,
    qualified_on: str,
) -> dict[str, Any]:
    """Build the tracked document and reject anything the loader would refuse."""

    document = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "capability": GPU_MODEL_SERVING_CAPABILITY,
        "model_backed_structured_output": MODEL_BACKED_VALIDATED,
        "qualified_on": qualified_on,
        "identity": identity.to_dict(),
        "observed": dict(observed),
        "cleanup": dict(cleanup),
    }
    parsed = _parse_evidence(json.loads(json.dumps(document, allow_nan=False)))
    if parsed.identity != identity:
        raise EvidenceLockError("model-backed evidence identity did not round-trip")
    return document


def write_evidence(config: RuntimeConfig, document: Mapping[str, Any]) -> Path:
    """Create the versioned evidence exactly once, never clobbering a version."""

    path = evidence_path(config)
    if path.is_symlink() or path.exists():
        raise EvidenceLockError("model-backed evidence already exists")
    raw = json.dumps(document, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
    raw += b"\n"
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("model-backed evidence write did not progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise EvidenceLockError("model-backed evidence could not be published") from exc
    finally:
        temporary.unlink(missing_ok=True)
    descriptor = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path
