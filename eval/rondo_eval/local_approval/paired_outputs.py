"""Plan 037 paired-output preparation with honest per-sample terminals.

The module is intentionally model-agnostic in stage one.  A later authorized
caller supplies one invocation callback; this runner fixes the side order,
performs no retries, and durably records each attempt before an honest decision
or non-decision terminal.  An interrupted tail attempt requires an explicit
infrastructure-failure resolution before the run may resume.  Artifact
identities are derived from regular files, frozen locks, or canonical manifests
rather than caller-supplied digest strings.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ..evidence import STATIC_INSTRUCTIONS
from . import cross_eval


IDENTITY_SOURCE_SCHEMA_VERSION = 1
IDENTITY_SOURCE_CONTRACT_VERSION = "rondo_l6_pair_identity_sources_v1"
IDENTITY_SOURCE_KINDS = ("regular_file", "frozen_lock", "canonical_manifest")
ARTIFACT_MANIFEST_SCHEMA_VERSION = 1
ARTIFACT_MANIFEST_CONTRACT_VERSION = "rondo_l6_canonical_artifact_manifest_v1"
JOURNAL_SCHEMA_VERSION = 1
JOURNAL_CONTRACT_VERSION = "rondo_l6_paired_output_journal_v1"
LOCAL_SIDE_ORDER = ("local-static", "local-ft-static")
FROZEN_BASE_REPO = "mistralai/Ministral-3-8B-Instruct-2512-BF16"
FROZEN_BASE_REVISION = "f6fae9795746f63c9be8344932f01275f3c63734"
FROZEN_CHAT_REVISION = "5b26027e7b19eeb4b7352e1fed3926375dd2cb4d"
FROZEN_CHAT_SHA256 = (
    "74eeb55fd3341286ec3fd44e902b7120721acc81cd394e96b431f85e93a1ea56"
)
FROZEN_MODEL_CONTRACT_SHA256 = (
    "964b071a1bf8fdc8bd81f0b8d1d8bd2262d829044ca24743efa619d1102a8481"
)
FROZEN_RUNTIME_LOCK_SHA256 = (
    "299440bb261f9dbc6641e81fa995ca88af84e4e05530978fe9c46a9716107b75"
)
FROZEN_PAIR_CONTRACT_SHA256 = (
    "ddf17fa1b0eadb1aa8fe6c090f656e3bd331bb529deb012655b063b2335a5514"
)
FROZEN_RUNTIME_COMMIT = "08659901c43b51de735740f1cf61bb82fbe0c4e4"
FROZEN_RUNTIME_SERVER_SHA256 = (
    "97a6b083ea34fea7e4e4440a0ddb734e1a2f6b775f4b31ef68ba5f998a9eeabd"
)
FROZEN_TRAIN_SHA256 = "1e66c06e9357a3b6e14aedd193c5405ad2c18924e57da6a3a209f079b80c110a"
FROZEN_DATASET_MANIFEST_SHA256 = (
    "dbf5fffe1f26d7746acf43fdcd092ff3e9cd64ea1f40046cd3b7219a15107190"
)
FROZEN_TRAIN_PROJECTION_SHA256 = (
    "0026cddd2a80771039c6644378120793d98310abdf66f01e7475416f23b2cc14"
)
FORMAL_SAMPLING_CONTRACT = {
    "context_size": 12288,
    "max_output_tokens": 512,
    "temperature": 0.0,
    "top_p": 1.0,
    "seed": 42,
}
FORMAL_ADAPTER_ARTIFACT_ID = "plan037-formal-adapter"
FROZEN_TOKENIZER_FILES = {
    "special_tokens_map.json": {
        "bytes": 147094,
        "sha256": "0a5c981e8c5c6f8886ee007a6d4543a0be6b221cb9ca32a8709384a4c6fc8cbb",
    },
    "tokenizer.json": {
        "bytes": 17078128,
        "sha256": "d5f6046775b112f0e2d456ee9dba450684ab964fe5c4e231599bdc6773028135",
    },
    "tokenizer_config.json": {
        "bytes": 198094,
        "sha256": "f59f7294e4f26383d0ea93840fe21cf197784be0842a8301a0343e8c34ed0d6d",
    },
}

_LOGICAL_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_MANIFEST_MAX_BYTES = 8 * 1024 * 1024


class PairedOutputError(RuntimeError):
    """Stable fail-closed error from the paired-output preparation boundary."""


class SampleTerminal(RuntimeError):
    """An explicit non-decision terminal emitted by the invocation adapter."""

    status: str

    def __init__(self, failure_code: str) -> None:
        terminal = _failure_terminal(self.status, failure_code)
        super().__init__(terminal["failure_code"])
        self.failure_code = terminal["failure_code"]


class StructuredOutputFailure(SampleTerminal):
    status = "structured_output_failure"


class ModelRefusal(SampleTerminal):
    status = "refusal"


class SampleTimeout(SampleTerminal):
    status = "timeout"


@dataclass(frozen=True)
class IdentitySource:
    """One actual object used to derive a receipt identity."""

    kind: str
    path: Path
    logical_name: str


@dataclass(frozen=True, init=False)
class BuiltPairReceipt:
    receipt: dict[str, Any]
    source_manifest: dict[str, Any]
    sources: tuple[tuple[str, IdentitySource], ...]

    def __new__(cls) -> BuiltPairReceipt:
        raise TypeError("BuiltPairReceipt must be created by build_pair_receipt")

    @classmethod
    def _from_inspected_sources(
        cls,
        receipt: Mapping[str, Any],
        source_manifest: Mapping[str, Any],
        sources: Mapping[str, IdentitySource],
    ) -> BuiltPairReceipt:
        instance = object.__new__(cls)
        object.__setattr__(instance, "receipt", copy.deepcopy(dict(receipt)))
        object.__setattr__(
            instance, "source_manifest", copy.deepcopy(dict(source_manifest))
        )
        object.__setattr__(instance, "sources", tuple(sources.items()))
        return instance


def _stable_file_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _component_relative_path(value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PairedOutputError("artifact_manifest_component_path_invalid")
    relative = Path(value)
    if (
        relative.is_absolute()
        or relative.parts in {(), (".",)}
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise PairedOutputError("artifact_manifest_component_path_invalid")
    return relative


def _validate_artifact_manifest(
    value: Any, *, manifest_path: Path
) -> list[dict[str, Any]]:
    fields = {"schema_version", "contract_version", "artifact_id", "components"}
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value.get("schema_version") != ARTIFACT_MANIFEST_SCHEMA_VERSION
        or value.get("contract_version") != ARTIFACT_MANIFEST_CONTRACT_VERSION
        or not isinstance(value.get("artifact_id"), str)
        or _LOGICAL_NAME.fullmatch(value["artifact_id"]) is None
        or not isinstance(value.get("components"), list)
        or not value["components"]
    ):
        raise PairedOutputError("artifact_manifest_invalid")
    accepted: list[dict[str, Any]] = []
    names: set[str] = set()
    paths: set[str] = set()
    for component in value["components"]:
        if not isinstance(component, dict) or set(component) != {
            "logical_name",
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PairedOutputError("artifact_manifest_component_invalid")
        name = component["logical_name"]
        relative = _component_relative_path(component["relative_path"])
        size = component["size_bytes"]
        digest = component["sha256"]
        if (
            not isinstance(name, str)
            or _LOGICAL_NAME.fullmatch(name) is None
            or name in names
            or relative.as_posix() in paths
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(digest, str)
            or cross_eval._HEX64.fullmatch(digest) is None
        ):
            raise PairedOutputError("artifact_manifest_component_invalid")
        names.add(name)
        paths.add(relative.as_posix())
        actual = inspect_identity_source(
            IdentitySource("regular_file", manifest_path.parent / relative, name)
        )
        if actual["size_bytes"] != size or actual["sha256"] != digest:
            raise PairedOutputError("artifact_manifest_component_drift")
        accepted.append(copy.deepcopy(component))
    if accepted != sorted(accepted, key=lambda item: item["logical_name"]):
        raise PairedOutputError("artifact_manifest_components_not_canonical")
    return accepted


def build_canonical_artifact_manifest(
    *,
    artifact_id: str,
    manifest_path: Path,
    components: Mapping[str, Path],
) -> dict[str, Any]:
    """Build a canonical manifest by hashing every declared actual component."""

    if (
        not isinstance(artifact_id, str)
        or _LOGICAL_NAME.fullmatch(artifact_id) is None
        or not isinstance(manifest_path, Path)
        or not isinstance(components, Mapping)
        or not components
    ):
        raise PairedOutputError("artifact_manifest_invalid")
    entries = []
    for logical_name, component_path in sorted(components.items()):
        if not isinstance(component_path, Path):
            raise PairedOutputError("artifact_manifest_component_invalid")
        try:
            relative = component_path.relative_to(manifest_path.parent)
        except ValueError as exc:
            raise PairedOutputError("artifact_manifest_component_path_invalid") from exc
        relative = _component_relative_path(relative.as_posix())
        inspected = inspect_identity_source(
            IdentitySource("regular_file", component_path, logical_name)
        )
        entries.append(
            {
                "logical_name": logical_name,
                "relative_path": relative.as_posix(),
                "size_bytes": inspected["size_bytes"],
                "sha256": inspected["sha256"],
            }
        )
    return {
        "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "contract_version": ARTIFACT_MANIFEST_CONTRACT_VERSION,
        "artifact_id": artifact_id,
        "components": entries,
    }


def inspect_identity_source(source: IdentitySource) -> dict[str, Any]:
    """Hash one non-symlink regular object and return body-free evidence."""

    if (
        not isinstance(source, IdentitySource)
        or source.kind not in IDENTITY_SOURCE_KINDS
        or not isinstance(source.path, Path)
        or not isinstance(source.logical_name, str)
        or _LOGICAL_NAME.fullmatch(source.logical_name) is None
    ):
        raise PairedOutputError("identity_source_invalid")
    try:
        before = os.lstat(source.path)
    except OSError as exc:
        raise PairedOutputError("identity_source_missing") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size <= 0
    ):
        raise PairedOutputError("identity_source_not_regular")
    if source.kind in {"frozen_lock", "canonical_manifest"} and before.st_size > _MANIFEST_MAX_BYTES:
        raise PairedOutputError("identity_source_manifest_too_large")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    digest = hashlib.sha256()
    canonical_raw: bytearray | None = (
        bytearray() if source.kind in {"frozen_lock", "canonical_manifest"} else None
    )
    try:
        descriptor = os.open(source.path, flags)
        try:
            opened = os.fstat(descriptor)
            if _stable_file_identity(opened) != _stable_file_identity(before):
                raise PairedOutputError("identity_source_changed")
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                if canonical_raw is not None:
                    canonical_raw.extend(chunk)
            after_fd = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after_path = os.lstat(source.path)
    except PairedOutputError:
        raise
    except OSError as exc:
        raise PairedOutputError("identity_source_read_failed") from exc
    identity = _stable_file_identity(before)
    if (
        _stable_file_identity(after_fd) != identity
        or _stable_file_identity(after_path) != identity
    ):
        raise PairedOutputError("identity_source_changed")
    components: list[dict[str, Any]] | None = None
    if canonical_raw is not None:
        try:
            value = json.loads(bytes(canonical_raw).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PairedOutputError("identity_source_json_invalid") from exc
        if (
            source.kind == "canonical_manifest"
            and bytes(canonical_raw) != cross_eval._json_file_bytes(value)
        ):
            raise PairedOutputError("identity_source_not_canonical")
        if source.kind == "canonical_manifest":
            components = _validate_artifact_manifest(
                value, manifest_path=source.path
            )
            try:
                final_manifest = os.lstat(source.path)
            except OSError as exc:
                raise PairedOutputError("identity_source_changed") from exc
            if _stable_file_identity(final_manifest) != identity:
                raise PairedOutputError("identity_source_changed")
    result = {
        "kind": source.kind,
        "logical_name": source.logical_name,
        "size_bytes": before.st_size,
        "sha256": digest.hexdigest(),
    }
    if components is not None:
        result["components"] = components
    return result


def _load_identity_source_json(
    source: IdentitySource,
    inspected: Mapping[str, Any],
    *,
    require_canonical: bool = False,
) -> dict[str, Any]:
    raw = cross_eval._safe_read(source.path, private=False)
    if hashlib.sha256(raw).hexdigest() != inspected.get("sha256"):
        raise PairedOutputError("identity_source_changed")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PairedOutputError("identity_source_json_invalid") from exc
    if not isinstance(value, dict) or (
        require_canonical and raw != cross_eval._json_file_bytes(value)
    ):
        raise PairedOutputError("identity_source_not_canonical")
    return value


def _validate_model_contract(
    value: Mapping[str, Any], *, identity: Mapping[str, Any]
) -> None:
    expected = {
        "schema_version": 1,
        "version": "rondo_local_approval_l6_model_contract_v1",
        "base": {"repo": FROZEN_BASE_REPO, "revision": FROZEN_BASE_REVISION},
        "tokenizer": {
            "repo": FROZEN_BASE_REPO,
            "revision": FROZEN_BASE_REVISION,
            "files": FROZEN_TOKENIZER_FILES,
        },
        "chat_template": {
            "repo": "mistralai/Ministral-3-8B-Instruct-2512",
            "revision": FROZEN_CHAT_REVISION,
            "source_file": "chat_template.jinja",
            "tracked_relative_path": (
                "eval/templates/local-approval/"
                "ministral-3-8b-instruct-2512-chat-template.jinja"
            ),
            "sha256": FROZEN_CHAT_SHA256,
        },
    }
    if identity.get("sha256") != FROZEN_MODEL_CONTRACT_SHA256 or value != expected:
        raise PairedOutputError("formal_model_contract_invalid")


def _validate_formal_training_receipt(
    receipt: Mapping[str, Any], *, model_contract: Mapping[str, Any]
) -> None:
    required = {
        "schema_version",
        "version",
        "status",
        "base",
        "train",
        "token_census",
        "recipe_sha256",
        "run_kind",
        "dependencies",
        "cost",
        "provider",
        "persistence",
        "reload_receipt_sha256",
        "hardware",
        "metrics",
        "output_paths",
        "artifacts",
        "bundle_manifest_sha256",
    }
    if (
        set(receipt) != required
        or receipt.get("schema_version") != 1
        or receipt.get("version")
        != "rondo_local_approval_l6_training_receipt_v1"
        or receipt.get("status") != "completed"
        or receipt.get("run_kind") != "formal"
        or receipt.get("base") != model_contract
    ):
        raise PairedOutputError("formal_training_receipt_invalid")
    train = receipt.get("train")
    if train != {
        "records": 470,
        "source_train_jsonl_sha256": FROZEN_TRAIN_SHA256,
        "source_dataset_manifest_sha256": FROZEN_DATASET_MANIFEST_SHA256,
        "projection_sha256": FROZEN_TRAIN_PROJECTION_SHA256,
        "completion_only": True,
    }:
        raise PairedOutputError("formal_training_receipt_train_invalid")
    census = receipt.get("token_census")
    sequence = census.get("sequence_tokens") if isinstance(census, dict) else None
    completion = census.get("completion_only") if isinstance(census, dict) else None
    census_fields = {
        "schema_version",
        "version",
        "status",
        "exact",
        "records",
        "projection_sha256",
        "tokenizer",
        "chat_template_applied",
        "truncation",
        "packing",
        "sequence_tokens",
        "completion_only",
    }
    sequence_fields = {"min", "p50", "p95", "max", "total", "limit", "over_limit"}
    completion_fields = {
        "prompt_tokens_total",
        "completion_tokens_total",
        "records_with_all_prompt_labels_masked",
        "records_with_unmasked_completion",
        "records_with_nonempty_completion",
    }
    if (
        not isinstance(census, dict)
        or set(census) != census_fields
        or census.get("schema_version") != 1
        or census.get("version") != "rondo_local_approval_l6_exact_token_census_v1"
        or census.get("status") != "complete"
        or census.get("exact") is not True
        or census.get("records") != 470
        or census.get("projection_sha256") != FROZEN_TRAIN_PROJECTION_SHA256
        or census.get("tokenizer")
        != {
            "repo": FROZEN_BASE_REPO,
            "revision": FROZEN_BASE_REVISION,
            "chat_template_sha256": FROZEN_CHAT_SHA256,
        }
        or census.get("chat_template_applied") is not True
        or census.get("truncation") is not False
        or census.get("packing") is not False
        or not isinstance(sequence, dict)
        or set(sequence) != sequence_fields
        or any(
            not isinstance(sequence.get(field), int)
            or isinstance(sequence[field], bool)
            for field in sequence_fields
        )
        or sequence["min"] <= 0
        or not (
            sequence["min"]
            <= sequence["p50"]
            <= sequence["p95"]
            <= sequence["max"]
            <= sequence["limit"]
        )
        or sequence["total"] < sequence["min"] * 470
        or sequence.get("over_limit") != 0
        or not isinstance(completion, dict)
        or set(completion) != completion_fields
        or completion.get("records_with_all_prompt_labels_masked") != 470
        or completion.get("records_with_unmasked_completion") != 470
        or completion.get("records_with_nonempty_completion") != 470
        or not isinstance(completion.get("prompt_tokens_total"), int)
        or completion["prompt_tokens_total"] <= 0
        or not isinstance(completion.get("completion_tokens_total"), int)
        or completion["completion_tokens_total"] <= 0
        or completion["prompt_tokens_total"] + completion["completion_tokens_total"]
        != sequence["total"]
    ):
        raise PairedOutputError("formal_training_receipt_census_invalid")
    dependencies = receipt.get("dependencies")
    provider = receipt.get("provider")
    hardware = receipt.get("hardware")
    persistence = receipt.get("persistence")
    metrics = receipt.get("metrics")
    artifacts = receipt.get("artifacts")
    output_paths = receipt.get("output_paths")
    if (
        not isinstance(receipt.get("recipe_sha256"), str)
        or cross_eval._HEX64.fullmatch(receipt["recipe_sha256"]) is None
        or not isinstance(dependencies, dict)
        or set(dependencies) != {"identity", "identity_sha256"}
        or not isinstance(dependencies.get("identity"), dict)
        or not dependencies["identity"]
        or not isinstance(dependencies.get("identity_sha256"), str)
        or cross_eval._HEX64.fullmatch(dependencies["identity_sha256"]) is None
        or not isinstance(provider, dict)
        or set(provider) != {"name", "job_id", "run_id"}
        or provider.get("name") != "runpod"
        or not isinstance(provider.get("job_id"), str)
        or not provider["job_id"]
        or not isinstance(provider.get("run_id"), str)
        or not provider["run_id"]
        or not isinstance(hardware, dict)
        or set(hardware) != {"name", "cuda"}
        or not isinstance(hardware.get("name"), str)
        or not hardware["name"]
        or not isinstance(hardware.get("cuda"), str)
        or not hardware["cuda"]
        or not isinstance(persistence, dict)
        or set(persistence) != {"kind", "revision"}
        or persistence.get("kind")
        not in {"pod_volume", "network_volume", "private_hf_repo", "local_download"}
        or not isinstance(persistence.get("revision"), str)
        or not persistence["revision"]
        or not isinstance(metrics, dict)
        or set(metrics)
        != {
            "trainer_metrics",
            "global_step",
            "actual_epochs",
            "train_loss",
            "lora_injection",
        }
        or not isinstance(metrics.get("trainer_metrics"), dict)
        or not metrics["trainer_metrics"]
        or not isinstance(metrics.get("global_step"), int)
        or isinstance(metrics["global_step"], bool)
        or metrics["global_step"] <= 0
        or not isinstance(metrics.get("actual_epochs"), (int, float))
        or isinstance(metrics["actual_epochs"], bool)
        or metrics["actual_epochs"] < 0
        or not isinstance(metrics.get("train_loss"), (int, float))
        or isinstance(metrics["train_loss"], bool)
        or not isinstance(metrics.get("lora_injection"), dict)
        or output_paths != {"adapter": "adapter-final", "checkpoints": "checkpoints"}
        or not isinstance(artifacts, dict)
        or set(artifacts) != {"adapter", "checkpoints"}
        or not isinstance(receipt.get("reload_receipt_sha256"), str)
        or cross_eval._HEX64.fullmatch(receipt["reload_receipt_sha256"]) is None
        or not isinstance(receipt.get("bundle_manifest_sha256"), str)
        or cross_eval._HEX64.fullmatch(receipt["bundle_manifest_sha256"]) is None
    ):
        raise PairedOutputError("formal_training_receipt_facts_invalid")
    injection = metrics["lora_injection"]
    if (
        set(injection)
        != {
            "target_pattern",
            "targeted_modules",
            "trainable_parameters",
            "vision_projector_lm_head_hits",
        }
        or not isinstance(injection.get("target_pattern"), str)
        or not injection["target_pattern"]
        or not isinstance(injection.get("targeted_modules"), int)
        or isinstance(injection["targeted_modules"], bool)
        or injection["targeted_modules"] <= 0
        or not isinstance(injection.get("trainable_parameters"), int)
        or isinstance(injection["trainable_parameters"], bool)
        or injection["trainable_parameters"] <= 0
        or injection.get("vision_projector_lm_head_hits") != 0
    ):
        raise PairedOutputError("formal_training_receipt_facts_invalid")
    for artifact_name, artifact in artifacts.items():
        if (
            not isinstance(artifact, dict)
            or set(artifact) != {"files", "tree_sha256"}
            or not isinstance(artifact["files"], dict)
            or (artifact_name == "adapter" and not artifact["files"])
            or not isinstance(artifact["tree_sha256"], str)
            or cross_eval._HEX64.fullmatch(artifact["tree_sha256"]) is None
            or artifact["tree_sha256"]
            != cross_eval._canonical_sha256(artifact["files"])
        ):
            raise PairedOutputError("formal_training_receipt_facts_invalid")
        for relative_path, file_identity in artifact["files"].items():
            if (
                not isinstance(relative_path, str)
                or not relative_path
                or relative_path.startswith("/")
                or ".." in Path(relative_path).parts
                or not isinstance(file_identity, dict)
                or set(file_identity) != {"bytes", "sha256"}
                or not isinstance(file_identity["bytes"], int)
                or isinstance(file_identity["bytes"], bool)
                or file_identity["bytes"] <= 0
                or not isinstance(file_identity["sha256"], str)
                or cross_eval._HEX64.fullmatch(file_identity["sha256"]) is None
            ):
                raise PairedOutputError("formal_training_receipt_facts_invalid")
    cost = receipt.get("cost")
    if (
        not isinstance(cost, dict)
        or set(cost) != {"provider", "actual_usd"}
        or cost.get("provider") != "runpod"
        or not isinstance(cost.get("actual_usd"), str)
        or not cost["actual_usd"]
    ):
        raise PairedOutputError("formal_training_receipt_cost_invalid")
    try:
        actual_cost = Decimal(cost["actual_usd"])
    except InvalidOperation as exc:
        raise PairedOutputError("formal_training_receipt_cost_invalid") from exc
    if (
        not actual_cost.is_finite()
        or actual_cost < 0
        or actual_cost > Decimal("25")
    ):
        raise PairedOutputError("formal_training_receipt_cost_invalid")


def _validate_adapter_artifact_binding(
    receipt: Mapping[str, Any],
    *,
    base_model: IdentitySource,
    local_static: IdentitySource,
    local_ft_static: IdentitySource,
    inspected: Mapping[str, Mapping[str, Any]],
) -> None:
    """Bind the adapter-on/off pair to the frozen base and formal receipt."""

    if (
        local_static.kind != "frozen_lock"
        or local_static.path != base_model.path
        or inspected["local-static"].get("sha256")
        != inspected["base-model"].get("sha256")
        or local_ft_static.kind != "canonical_manifest"
    ):
        raise PairedOutputError("formal_pair_artifact_binding_invalid")
    manifest = _load_identity_source_json(
        local_ft_static,
        inspected["local-ft-static"],
        require_canonical=True,
    )
    if manifest.get("artifact_id") != FORMAL_ADAPTER_ARTIFACT_ID:
        raise PairedOutputError("formal_pair_artifact_binding_invalid")
    components = inspected["local-ft-static"].get("components")
    if not isinstance(components, list):
        raise PairedOutputError("formal_pair_artifact_binding_invalid")
    actual_adapter_files = {
        component["relative_path"]: {
            "bytes": component["size_bytes"],
            "sha256": component["sha256"],
        }
        for component in components
    }
    expected_adapter_files = receipt.get("artifacts", {}).get("adapter", {}).get(
        "files"
    )
    if actual_adapter_files != expected_adapter_files:
        raise PairedOutputError("formal_pair_adapter_receipt_mismatch")


def _validate_pair_contract(
    value: Mapping[str, Any],
    *,
    runtime_value: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
    chat_identity: Mapping[str, Any],
) -> dict[str, Any]:
    request = {
        "schema_version": 1,
        "transport": "llama_cpp_b10333_responses_static_v3",
        "static_payload_schema_version": cross_eval.STATIC_PAYLOAD_SCHEMA_VERSION,
        "static_instructions_sha256": hashlib.sha256(
            STATIC_INSTRUCTIONS.encode("utf-8")
        ).hexdigest(),
        "static_decision_schema_name": cross_eval.STATIC_DECISION_SCHEMA_NAME,
        "static_decision_schema_sha256": cross_eval._canonical_sha256(
            cross_eval.STATIC_DECISION_SCHEMA
        ),
        "sampling": FORMAL_SAMPLING_CONTRACT,
    }
    expected = {
        "schema_version": 1,
        "version": "rondo_l6_local_pair_contract_v1",
        "runtime": {
            "lock_relative_path": "eval/locks/llama-cpp-b10333-cuda-linux-x64.json",
            "lock_sha256": FROZEN_RUNTIME_LOCK_SHA256,
            "release": "b10333",
        },
        "chat_template": {
            "relative_path": (
                "eval/templates/local-approval/"
                "ministral-3-8b-instruct-2512-chat-template.jinja"
            ),
            "revision": FROZEN_CHAT_REVISION,
            "sha256": FROZEN_CHAT_SHA256,
        },
        "request_contract": request,
        "output_contract": {
            "name": cross_eval.STATIC_DECISION_SCHEMA_NAME,
            "sha256": cross_eval._canonical_sha256(
                cross_eval.STATIC_DECISION_SCHEMA
            ),
        },
    }
    if (
        value != expected
        or runtime_identity.get("sha256") != FROZEN_RUNTIME_LOCK_SHA256
        or runtime_value.get("schema_version") != 1
        or runtime_value.get("release") != "b10333"
        or runtime_value.get("source", {}).get("commit") != FROZEN_RUNTIME_COMMIT
        or runtime_value.get("installed_runtime", {}).get("relative_path")
        != "eval-data/tools/llama-b10333-cuda-linux-x64"
        or runtime_value.get("installed_runtime", {})
        .get("regular_files", {})
        .get("llama-server")
        != FROZEN_RUNTIME_SERVER_SHA256
        or chat_identity.get("sha256") != FROZEN_CHAT_SHA256
    ):
        raise PairedOutputError("formal_pair_contract_invalid")
    return {
        "runtime_identity_sha256": runtime_identity["sha256"],
        "chat_template_sha256": chat_identity["sha256"],
        "request_contract_sha256": cross_eval._canonical_sha256(request),
        "sampling_contract": copy.deepcopy(FORMAL_SAMPLING_CONTRACT),
        "output_contract_sha256": cross_eval._canonical_sha256(
            cross_eval.STATIC_DECISION_SCHEMA
        ),
    }


def build_pair_receipt(
    *,
    pair_id: str,
    base_model: IdentitySource,
    local_static: IdentitySource,
    local_ft_static: IdentitySource,
    training_receipt: IdentitySource,
    runtime_lock: IdentitySource,
    chat_template: IdentitySource,
    pair_contract: IdentitySource,
    blind_identity_markers: Sequence[str],
) -> BuiltPairReceipt:
    """Build a formal v1 pair receipt exclusively from inspected Plan 037 facts."""

    actual_sources = {
        "base-model": base_model,
        "local-static": local_static,
        "local-ft-static": local_ft_static,
        "training-receipt": training_receipt,
        "runtime-lock": runtime_lock,
        "chat-template": chat_template,
        "pair-contract": pair_contract,
    }
    sources = {
        name: inspect_identity_source(source)
        for name, source in actual_sources.items()
    }
    if (
        base_model.kind != "frozen_lock"
        or training_receipt.kind != "frozen_lock"
        or runtime_lock.kind != "frozen_lock"
        or chat_template.kind != "regular_file"
        or pair_contract.kind != "frozen_lock"
        or local_static.kind != "frozen_lock"
        or local_ft_static.kind != "canonical_manifest"
    ):
        raise PairedOutputError("formal_pair_identity_source_kind_invalid")
    model_contract = _load_identity_source_json(base_model, sources["base-model"])
    _validate_model_contract(model_contract, identity=sources["base-model"])
    completed = _load_identity_source_json(
        training_receipt, sources["training-receipt"]
    )
    _validate_formal_training_receipt(completed, model_contract=model_contract)
    _validate_adapter_artifact_binding(
        completed,
        base_model=base_model,
        local_static=local_static,
        local_ft_static=local_ft_static,
        inspected=sources,
    )
    runtime_value = _load_identity_source_json(
        runtime_lock, sources["runtime-lock"]
    )
    pair_value = _load_identity_source_json(
        pair_contract, sources["pair-contract"], require_canonical=True
    )
    if sources["pair-contract"]["sha256"] != FROZEN_PAIR_CONTRACT_SHA256:
        raise PairedOutputError("formal_pair_contract_invalid")
    shared_contract = _validate_pair_contract(
        pair_value,
        runtime_value=runtime_value,
        runtime_identity=sources["runtime-lock"],
        chat_identity=sources["chat-template"],
    )
    receipt = {
        "schema_version": cross_eval.LOCAL_PAIR_RECEIPT_SCHEMA_VERSION,
        "contract_version": cross_eval.LOCAL_PAIR_RECEIPT_CONTRACT_VERSION,
        "source_work_package": "L6",
        "pair_id": pair_id,
        "base_model_identity_sha256": sources["base-model"]["sha256"],
        "shared_contract": shared_contract,
        "artifacts": {
            "local-static": {
                "provenance": "l6_paired_unfinetuned",
                "model_artifact_sha256": sources["local-static"]["sha256"],
                "training_receipt_sha256": None,
            },
            "local-ft-static": {
                "provenance": "l6_paired_finetuned",
                "model_artifact_sha256": sources["local-ft-static"]["sha256"],
                "training_receipt_sha256": sources["training-receipt"]["sha256"],
            },
        },
        "blind_identity_markers": list(blind_identity_markers),
    }
    normalized, receipt_sha256, _contracts = cross_eval.validate_l6_pair_receipt(
        receipt
    )
    source_manifest = {
        "schema_version": IDENTITY_SOURCE_SCHEMA_VERSION,
        "contract_version": IDENTITY_SOURCE_CONTRACT_VERSION,
        "pair_id": pair_id,
        "pair_receipt_sha256": receipt_sha256,
        "sources": sources,
    }
    return BuiltPairReceipt._from_inspected_sources(
        normalized, source_manifest, actual_sources
    )


def _revalidate_built_pair_receipt(
    value: BuiltPairReceipt,
) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    if not isinstance(value, BuiltPairReceipt) or not all(
        hasattr(value, field) for field in ("receipt", "source_manifest", "sources")
    ):
        raise PairedOutputError("built_pair_receipt_required")
    actual_sources = dict(value.sources)
    if set(actual_sources) != {
        "base-model",
        "local-static",
        "local-ft-static",
        "training-receipt",
        "runtime-lock",
        "chat-template",
        "pair-contract",
    } or any(not isinstance(source, IdentitySource) for source in actual_sources.values()):
        raise PairedOutputError("built_pair_receipt_sources_invalid")
    inspected = {
        name: inspect_identity_source(source)
        for name, source in actual_sources.items()
    }
    expected_manifest = value.source_manifest
    if (
        not isinstance(expected_manifest, dict)
        or expected_manifest.get("schema_version") != IDENTITY_SOURCE_SCHEMA_VERSION
        or expected_manifest.get("contract_version")
        != IDENTITY_SOURCE_CONTRACT_VERSION
        or expected_manifest.get("pair_id") != value.receipt.get("pair_id")
        or expected_manifest.get("sources") != inspected
    ):
        raise PairedOutputError("pair_receipt_source_manifest_mismatch")
    normalized, receipt_sha256, contracts = cross_eval.validate_l6_pair_receipt(
        value.receipt
    )
    model_contract = _load_identity_source_json(
        actual_sources["base-model"], inspected["base-model"]
    )
    _validate_model_contract(model_contract, identity=inspected["base-model"])
    completed = _load_identity_source_json(
        actual_sources["training-receipt"],
        inspected["training-receipt"],
    )
    _validate_formal_training_receipt(completed, model_contract=model_contract)
    _validate_adapter_artifact_binding(
        completed,
        base_model=actual_sources["base-model"],
        local_static=actual_sources["local-static"],
        local_ft_static=actual_sources["local-ft-static"],
        inspected=inspected,
    )
    runtime_value = _load_identity_source_json(
        actual_sources["runtime-lock"], inspected["runtime-lock"]
    )
    pair_value = _load_identity_source_json(
        actual_sources["pair-contract"],
        inspected["pair-contract"],
        require_canonical=True,
    )
    if inspected["pair-contract"]["sha256"] != FROZEN_PAIR_CONTRACT_SHA256:
        raise PairedOutputError("formal_pair_contract_invalid")
    shared_contract = _validate_pair_contract(
        pair_value,
        runtime_value=runtime_value,
        runtime_identity=inspected["runtime-lock"],
        chat_identity=inspected["chat-template"],
    )
    if (
        expected_manifest.get("pair_receipt_sha256") != receipt_sha256
        or normalized["base_model_identity_sha256"]
        != inspected["base-model"]["sha256"]
        or normalized["artifacts"]["local-static"]["model_artifact_sha256"]
        != inspected["local-static"]["sha256"]
        or normalized["artifacts"]["local-ft-static"]["model_artifact_sha256"]
        != inspected["local-ft-static"]["sha256"]
        or normalized["artifacts"]["local-ft-static"]["training_receipt_sha256"]
        != inspected["training-receipt"]["sha256"]
        or normalized["shared_contract"] != shared_contract
    ):
        raise PairedOutputError("pair_receipt_source_manifest_mismatch")
    return normalized, receipt_sha256, contracts


def _decision_terminal(decision: Mapping[str, Any]) -> dict[str, Any]:
    return cross_eval.validate_output_terminal(
        {
            "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
            "contract_version": cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION,
            "status": "decision",
            "decision": copy.deepcopy(dict(decision)),
        }
    )


def _failure_terminal(status: str, failure_code: str) -> dict[str, Any]:
    return cross_eval.validate_output_terminal(
        {
            "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
            "contract_version": cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION,
            "status": status,
            "failure_code": failure_code,
        }
    )


def _infrastructure_terminal(failure_code: str) -> dict[str, Any]:
    return cross_eval.validate_output_terminal(
        {
            "schema_version": cross_eval.INFRASTRUCTURE_TERMINAL_SCHEMA_VERSION,
            "contract_version": (
                cross_eval.INFRASTRUCTURE_TERMINAL_CONTRACT_VERSION
            ),
            "status": cross_eval.INFRASTRUCTURE_TERMINAL_STATUS,
            "failure_code": failure_code,
        }
    )


def _local_output_row(
    *,
    bundle: cross_eval.CohortBundle,
    cohort_item: Mapping[str, Any],
    source_row: Mapping[str, Any],
    side: str,
    run_contract: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": cross_eval.TERMINAL_IMPORT_SCHEMA_VERSION,
        "contract_version": cross_eval.TERMINAL_IMPORT_CONTRACT_VERSION,
        "partition": bundle.partition,
        "cohort_id": bundle.manifest["cohort_id"],
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "body_batch_id": cohort_item["body_batch_id"],
        "sample_id": source_row["sample_id"],
        "side": side,
        "approval_input": copy.deepcopy(source_row["input"]),
        "payload_sha256": source_row["payload_sha256"],
        "approval_prompt_sha256": cohort_item["approval_prompt_sha256"],
        "message_sequence_sha256": cohort_item["message_sequence_sha256"],
        "output_schema_sha256": cohort_item["output_schema_sha256"],
        "terminal": copy.deepcopy(dict(terminal)),
        "run_contract": copy.deepcopy(dict(run_contract)),
    }


def _require_run_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise PairedOutputError("paired_run_directory_missing") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PairedOutputError("paired_run_directory_invalid")


def _journal_header(
    bundle: cross_eval.CohortBundle,
    *,
    receipt: Mapping[str, Any],
    receipt_sha256: str,
    source_manifest: Mapping[str, Any],
    expected_keys: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "contract_version": JOURNAL_CONTRACT_VERSION,
        "record_type": "run",
        "cohort_id": bundle.manifest["cohort_id"],
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "pair_id": receipt["pair_id"],
        "pair_receipt_sha256": receipt_sha256,
        "pair_source_manifest_sha256": cross_eval._canonical_sha256(
            source_manifest
        ),
        "side_order": list(LOCAL_SIDE_ORDER),
        "sample_order_sha256": cross_eval._canonical_sha256(
            [sample_id for _side, sample_id in expected_keys]
        ),
        "expected_terminal_count": len(expected_keys),
    }


def _append_journal_record(path: Path, value: Mapping[str, Any]) -> None:
    raw = cross_eval._canonical_bytes(dict(value)) + b"\n"
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise PairedOutputError("paired_journal_missing") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        raise PairedOutputError("paired_journal_invalid")
    flags = os.O_WRONLY | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _stable_file_identity(opened) != _stable_file_identity(before):
                raise PairedOutputError("paired_journal_changed")
            written = os.write(descriptor, raw)
            if written != len(raw):
                raise PairedOutputError("paired_journal_partial_write")
            os.fsync(descriptor)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except PairedOutputError:
        raise
    except OSError as exc:
        raise PairedOutputError("paired_journal_write_failed") from exc
    if (
        after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size + len(raw)
    ):
        raise PairedOutputError("paired_journal_changed")


def _load_or_create_journal(
    *,
    run_dir: Path,
    header: Mapping[str, Any],
    bundle: cross_eval.CohortBundle,
    contracts: Mapping[str, Mapping[str, Any]],
    expected_keys: Sequence[tuple[str, str]],
    create: bool = True,
    allow_dangling: bool = False,
) -> tuple[Path, list[dict[str, Any]], dict[str, Any] | None]:
    _require_run_directory(run_dir)
    journal_path = run_dir / "paired-output-journal.jsonl"
    if not journal_path.exists() and not journal_path.is_symlink():
        if not create:
            raise PairedOutputError("paired_journal_missing")
        cross_eval._write_exclusive(
            journal_path,
            cross_eval._canonical_bytes(dict(header)) + b"\n",
            mode=0o600,
        )
    raw = cross_eval._safe_read(journal_path, private=True)
    if not raw.endswith(b"\n"):
        raise PairedOutputError("paired_journal_incomplete_write")
    lines = raw.splitlines()
    if not lines:
        raise PairedOutputError("paired_journal_invalid")
    values = []
    for line in lines:
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PairedOutputError("paired_journal_invalid") from exc
        if not isinstance(value, dict) or line != cross_eval._canonical_bytes(value):
            raise PairedOutputError("paired_journal_not_canonical")
        values.append(value)
    if values[0] != dict(header):
        raise PairedOutputError("paired_journal_binding_mismatch")

    records = values[1:]
    completed: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(records):
        sequence = len(completed)
        if sequence >= len(expected_keys):
            raise PairedOutputError("paired_journal_record_unexpected")
        side, sample_id = expected_keys[sequence]
        attempt = records[cursor]
        expected_attempt = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "contract_version": JOURNAL_CONTRACT_VERSION,
            "record_type": "attempt",
            "sequence": sequence,
            "side": side,
            "sample_id": sample_id,
        }
        if attempt != expected_attempt:
            raise PairedOutputError("paired_journal_attempt_invalid")
        cursor += 1
        if cursor == len(records):
            if allow_dangling:
                return journal_path, completed, copy.deepcopy(attempt)
            raise PairedOutputError("paired_journal_attempt_without_terminal")
        terminal_record = records[cursor]
        if (
            not isinstance(terminal_record, dict)
            or set(terminal_record) != {
                "schema_version",
                "contract_version",
                "record_type",
                "sequence",
                "side",
                "sample_id",
                "row",
            }
            or terminal_record.get("schema_version") != JOURNAL_SCHEMA_VERSION
            or terminal_record.get("contract_version") != JOURNAL_CONTRACT_VERSION
            or terminal_record.get("record_type") != "terminal"
            or terminal_record.get("sequence") != sequence
            or terminal_record.get("side") != side
            or terminal_record.get("sample_id") != sample_id
        ):
            raise PairedOutputError("paired_journal_terminal_invalid")
        item = next(
            value
            for value in bundle.manifest["items"]
            if value["sample_id"] == sample_id
        )
        accepted = cross_eval._validate_import_row(
            terminal_record["row"],
            bundle=bundle,
            cohort_item=item,
            source_row=bundle.source_rows[sample_id],
        )
        if (
            accepted != terminal_record["row"]
            or accepted["side"] != side
            or accepted["run_contract"] != contracts[side]
        ):
            raise PairedOutputError("paired_journal_terminal_invalid")
        completed.append(accepted)
        cursor += 1
    return journal_path, completed, None


def run_paired_outputs(
    bundle: cross_eval.CohortBundle,
    *,
    pair_receipt: BuiltPairReceipt,
    run_dir: Path,
    invoke: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
    max_new_terminals: int | None = None,
) -> list[dict[str, Any]]:
    """Run both local sides serially and record one honest terminal per sample.

    The callback is invoked for all ``local-static`` samples before any
    ``local-ft-static`` sample.  Only explicit ``SampleTerminal`` exceptions
    become sample records; unexpected/infrastructure exceptions abort the run.
    """

    cross_eval.validate_cohort_bundle(bundle)
    receipt, receipt_sha256, contracts = _revalidate_built_pair_receipt(
        pair_receipt
    )
    if not callable(invoke):
        raise PairedOutputError("paired_invoke_invalid")
    if (
        max_new_terminals is not None
        and (
            not isinstance(max_new_terminals, int)
            or isinstance(max_new_terminals, bool)
            or max_new_terminals < 0
        )
    ):
        raise PairedOutputError("paired_terminal_limit_invalid")
    items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    expected_keys = [
        (side, sample_id)
        for side in LOCAL_SIDE_ORDER
        for sample_id in sorted(items)
    ]
    header = _journal_header(
        bundle,
        receipt=receipt,
        receipt_sha256=receipt_sha256,
        source_manifest=pair_receipt.source_manifest,
        expected_keys=expected_keys,
    )
    journal_path, rows, _dangling = _load_or_create_journal(
        run_dir=run_dir,
        header=header,
        bundle=bundle,
        contracts=contracts,
        expected_keys=expected_keys,
    )
    new_terminals = 0
    for sequence, (side, sample_id) in enumerate(
        expected_keys[len(rows) :], start=len(rows)
    ):
        if max_new_terminals is not None and new_terminals >= max_new_terminals:
            break
        source = bundle.source_rows[sample_id]
        _append_journal_record(
            journal_path,
            {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "contract_version": JOURNAL_CONTRACT_VERSION,
                "record_type": "attempt",
                "sequence": sequence,
                "side": side,
                "sample_id": sample_id,
            },
        )
        try:
            terminal = _decision_terminal(
                invoke(side, copy.deepcopy(source["input"]))
            )
        except SampleTerminal as exc:
            terminal = _failure_terminal(exc.status, exc.failure_code)
        row = _local_output_row(
            bundle=bundle,
            cohort_item=items[sample_id],
            source_row=source,
            side=side,
            run_contract=contracts[side],
            terminal=terminal,
        )
        _append_journal_record(
            journal_path,
            {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "contract_version": JOURNAL_CONTRACT_VERSION,
                "record_type": "terminal",
                "sequence": sequence,
                "side": side,
                "sample_id": sample_id,
                "row": row,
            },
        )
        rows.append(row)
        new_terminals += 1
    return rows


def resolve_interrupted_attempt(
    bundle: cross_eval.CohortBundle,
    *,
    pair_receipt: BuiltPairReceipt,
    run_dir: Path,
    failure_code: str,
) -> dict[str, Any]:
    """Resolve exactly one tail attempt as a body-free infrastructure failure.

    This explicit operation never invokes the model.  It revalidates the
    cohort, every pair-receipt source, and the durable journal header before it
    appends the one terminal that makes a later resume safe.
    """

    cross_eval.validate_cohort_bundle(bundle)
    receipt, receipt_sha256, contracts = _revalidate_built_pair_receipt(
        pair_receipt
    )
    terminal = _infrastructure_terminal(failure_code)
    items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    expected_keys = [
        (side, sample_id)
        for side in LOCAL_SIDE_ORDER
        for sample_id in sorted(items)
    ]
    header = _journal_header(
        bundle,
        receipt=receipt,
        receipt_sha256=receipt_sha256,
        source_manifest=pair_receipt.source_manifest,
        expected_keys=expected_keys,
    )
    journal_path, rows, dangling = _load_or_create_journal(
        run_dir=run_dir,
        header=header,
        bundle=bundle,
        contracts=contracts,
        expected_keys=expected_keys,
        create=False,
        allow_dangling=True,
    )
    if dangling is None:
        raise PairedOutputError("paired_journal_no_interrupted_attempt")
    sequence = len(rows)
    side, sample_id = expected_keys[sequence]
    if (
        dangling.get("sequence") != sequence
        or dangling.get("side") != side
        or dangling.get("sample_id") != sample_id
    ):
        raise PairedOutputError("paired_journal_attempt_invalid")
    source = bundle.source_rows[sample_id]
    row = _local_output_row(
        bundle=bundle,
        cohort_item=items[sample_id],
        source_row=source,
        side=side,
        run_contract=contracts[side],
        terminal=terminal,
    )
    _append_journal_record(
        journal_path,
        {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "contract_version": JOURNAL_CONTRACT_VERSION,
            "record_type": "terminal",
            "sequence": sequence,
            "side": side,
            "sample_id": sample_id,
            "row": row,
        },
    )
    return row


def build_frozen_sol_rows(
    bundle: cross_eval.CohortBundle,
) -> list[dict[str, Any]]:
    """Project frozen Sol targets as unchanged v1 decision rows."""

    cross_eval.validate_cohort_bundle(bundle)
    items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    rows = []
    for sample_id in sorted(items):
        source = bundle.source_rows[sample_id]
        item = items[sample_id]
        source_cohort_sha256 = (
            bundle.manifest["source"]["validation_sha256"]
            if bundle.partition == "synthetic"
            else bundle.manifest["source"]["private_source_sha256"]
        )
        rows.append(
            {
                "schema_version": cross_eval.IMPORT_SCHEMA_VERSION,
                "contract_version": cross_eval.IMPORT_CONTRACT_VERSION,
                "partition": bundle.partition,
                "cohort_id": bundle.manifest["cohort_id"],
                "cohort_manifest_sha256": bundle.manifest_sha256,
                "body_batch_id": item["body_batch_id"],
                "sample_id": sample_id,
                "side": "sol-static",
                "approval_input": copy.deepcopy(source["input"]),
                "payload_sha256": source["payload_sha256"],
                "approval_prompt_sha256": item["approval_prompt_sha256"],
                "message_sequence_sha256": item["message_sequence_sha256"],
                "output_schema_sha256": item["output_schema_sha256"],
                "decision": copy.deepcopy(source["target"]),
                "run_contract": {
                    "contract_version": cross_eval.IMPORT_CONTRACT_VERSION,
                    "provenance": "frozen_validation_target",
                    "source_dataset_batch_id": source["batch_id"],
                    "source_generation_model": source["generator_model"],
                    "source_generated_date": source["generated_date"],
                    "source_generation_prompt_version": source["prompt_version"],
                    "source_generation_prompt_sha256": source["prompt_sha256"],
                    "source_cohort_sha256": source_cohort_sha256,
                },
            }
        )
    return rows


def assemble_three_side_outputs(
    bundle: cross_eval.CohortBundle,
    local_rows: Sequence[Mapping[str, Any]],
    *,
    pair_receipt: BuiltPairReceipt,
) -> list[dict[str, Any]]:
    """Combine frozen Sol v1 rows and local v2 rows through the formal importer."""

    evidence = formal_pair_evidence(pair_receipt)
    return cross_eval.validate_three_side_rows(
        bundle,
        [*build_frozen_sol_rows(bundle), *copy.deepcopy(list(local_rows))],
        l6_pair_receipt=evidence,
    )


def formal_pair_evidence(
    pair_receipt: BuiltPairReceipt,
) -> cross_eval.FormalL6PairEvidence:
    """Revalidate every actual source and return a formal-import capability."""

    receipt, _sha256, _contracts = _revalidate_built_pair_receipt(pair_receipt)
    return cross_eval.FormalL6PairEvidence._from_source_validation(receipt)
