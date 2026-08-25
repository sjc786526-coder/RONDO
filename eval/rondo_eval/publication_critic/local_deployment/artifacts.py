"""Manifest-driven artifact plans for the Plan 068 local handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any

from .handoff import DownloadSpec, FORMAL_RUN_PREFIX, HandoffError


MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_FILES = 4096
MAX_MANIFEST_PAYLOAD_BYTES = 60 * 1024**3

EXACT_BASE_SHA256 = {
    "added_tokens.json": "c0284b582e14987fbd3d5a2cb2bd139084371ed9acbae488829a1c900833c680",
    "chat_template.jinja": "a55ee1b1660128b7098723e0abcd92caa0788061051c62d51cbe87d9cf1974d8",
    "config.json": "106d39725452746837071561f56464fd3f1d9a5a1e0ae926de02e6a0a4fa9b11",
    "merges.txt": "8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5",
    "model.safetensors": "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9",
    "special_tokens_map.json": "45dfef44807b97f5a7f20148bc9d55e593fbf6890393b1f8b7367fb36a2b853d",
    "tokenizer.json": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
    "tokenizer_config.json": "d3e08cbc53421cc90a07d40da21fbac9a912f5ffa3f08263afd04f06105b0e6f",
    "vocab.json": "ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910",
}
EXACT_BASE_WEIGHT_BYTES = 3_441_189_792
CANDIDATE_MANIFEST_SHA256 = {
    "C1": "157d93d65d18dba02800a233338789b719a58faf003d9cd7c3f5cd42f80d5a46",
    "C2": "5943d3004f5f04c90a60e01cf5f1c1c5ebd05aebd5eddea63cadc7d586975677",
    "C3": "3c0ff2ed90c69c0ad585c97fa89b61582d79850f26756097ad956eabb6fef602",
}
CANDIDATE_PAYLOAD_BYTES = 3_457_072_872
CHECKPOINT_MANIFEST_SHA256 = (
    "f0bc46612e12ecfa491129291d355ccb7f51c577905d084216b50a3533cd4aff"
)
CHECKPOINT_PAYLOAD_BYTES = 10_555_059_139
PLAN066_FORMAL_START_SHA256 = (
    "cdb9c9a41d054077ee6ae2455eab4d3fe3902b4cb5b99940ae6d06ebae19ccdd"
)


@dataclass(frozen=True)
class KnownObject:
    relative_key: str
    sha256: str
    size: int | None = None

    def __post_init__(self) -> None:
        _safe_object_key(self.relative_key)
        _require_sha256(self.sha256)
        if self.size is not None:
            _nonnegative_int(self.size)


@dataclass(frozen=True)
class ArtifactPlan:
    manifest_key: str
    manifest_sha256: str
    payload_bytes: int
    files: tuple[DownloadSpec, ...]


def exact_base_requirements() -> tuple[KnownObject, ...]:
    return tuple(
        KnownObject(
            f"model/{name}",
            digest,
            EXACT_BASE_WEIGHT_BYTES if name == "model.safetensors" else None,
        )
        for name, digest in EXACT_BASE_SHA256.items()
    )


def formal_manifest_requirements(formal_run_prefix: str) -> tuple[KnownObject, ...]:
    prefix = _safe_prefix(formal_run_prefix)
    return (
        KnownObject(
            prefix + "candidate-c1/candidate-manifest.json",
            CANDIDATE_MANIFEST_SHA256["C1"],
        ),
        KnownObject(
            prefix + "candidate-c2/candidate-manifest.json",
            CANDIDATE_MANIFEST_SHA256["C2"],
        ),
        KnownObject(
            prefix + "candidate-c3/candidate-manifest.json",
            CANDIDATE_MANIFEST_SHA256["C3"],
        ),
        KnownObject(
            prefix + "checkpoint-c3/checkpoint-manifest.json",
            CHECKPOINT_MANIFEST_SHA256,
        ),
        KnownObject(prefix + "plan066-formal-start.json", PLAN066_FORMAL_START_SHA256),
    )


def parse_artifact_manifest(
    manifest_key: str,
    raw: bytes,
    *,
    expected_sha256: str,
    expected_payload_bytes: int | None = None,
) -> ArtifactPlan:
    """Validate a known candidate/checkpoint/bundle manifest and plan its tree."""

    key = _safe_object_key(manifest_key)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_MANIFEST_BYTES:
        raise HandoffError("artifact_manifest_size_invalid")
    _require_sha256(expected_sha256)
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        raise HandoffError("artifact_manifest_hash_mismatch")
    value = _load_json(raw)
    if not isinstance(value, Mapping):
        raise HandoffError("artifact_manifest_invalid")
    schema = value.get("schema")
    metadata_keys: set[str]
    if schema == "rondo-publication-critic-plan066-candidate-v1":
        expected_keys = {
            "schema",
            "created_at",
            "stage",
            "global_step",
            "identity_sha256",
            "format",
            "files",
            "content_sha256",
        }
        metadata_keys = {"bytes", "sha256"}
    elif schema == "rondo-publication-critic-full-model-checkpoint-manifest-v1":
        expected_keys = {"schema", "files", "content_sha256"}
        metadata_keys = {"bytes", "sha256"}
    elif schema == "rondo-publication-critic-plan066-bundle-v1":
        expected_keys = {
            "schema",
            "created_at",
            "source",
            "boundaries",
            "files",
            "content_sha256",
        }
        metadata_keys = {
            "bytes",
            "sha256",
            "role",
            "contains_train_body",
            "contains_validation_body",
        }
    else:
        raise HandoffError("artifact_manifest_schema_not_allowed")
    if set(value) != expected_keys:
        raise HandoffError("artifact_manifest_invalid")
    core = {name: item for name, item in value.items() if name != "content_sha256"}
    if _canonical_sha256(core) != value.get("content_sha256"):
        raise HandoffError("artifact_manifest_content_mismatch")
    files = value.get("files")
    if not isinstance(files, Mapping) or not 1 <= len(files) <= MAX_MANIFEST_FILES:
        raise HandoffError("artifact_manifest_files_invalid")
    parent = key.rsplit("/", 1)[0] + "/"
    specs: list[DownloadSpec] = []
    total = 0
    for relative, metadata in files.items():
        name = _safe_object_key(relative)
        if not isinstance(metadata, Mapping) or set(metadata) != metadata_keys:
            raise HandoffError("artifact_manifest_file_invalid")
        size = _nonnegative_int(metadata.get("bytes"))
        digest = _require_sha256(metadata.get("sha256"))
        total += size
        if total > MAX_MANIFEST_PAYLOAD_BYTES:
            raise HandoffError("artifact_manifest_payload_too_large")
        specs.append(DownloadSpec(parent + name, size, digest))
    if expected_payload_bytes is not None and total != expected_payload_bytes:
        raise HandoffError("artifact_manifest_payload_size_mismatch")
    return ArtifactPlan(key, observed_sha256, total, tuple(specs))


def _load_json(raw: bytes) -> Any:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in pairs:
            if name in result:
                raise HandoffError("artifact_manifest_duplicate_key")
            result[name] = value
        return result

    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except HandoffError:
        raise
    except (UnicodeError, json.JSONDecodeError):
        raise HandoffError("artifact_manifest_json_invalid") from None


def _canonical_sha256(value: Any) -> str:
    try:
        raw = (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError):
        raise HandoffError("artifact_manifest_invalid") from None
    return hashlib.sha256(raw).hexdigest()


def _safe_prefix(value: str) -> str:
    if not isinstance(value, str) or not value.endswith("/"):
        raise HandoffError("artifact_prefix_invalid")
    _safe_object_key(value[:-1])
    if value != FORMAL_RUN_PREFIX:
        raise HandoffError("artifact_prefix_not_allowed")
    return value


def _safe_object_key(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.endswith("/")
        or "\\" in value
        or "//" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise HandoffError("artifact_relative_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HandoffError("artifact_relative_path_invalid")
    return value


def _require_sha256(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise HandoffError("artifact_sha256_invalid")
    return value


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HandoffError("artifact_file_size_invalid")
    return value
