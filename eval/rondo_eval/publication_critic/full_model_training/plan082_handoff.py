"""Parameterized, manifest-driven zero-Pod handoff for Plan 082.

The non-secret receipt binds one live RunPod network-volume S3 namespace.
Credentials are still loaded only by the repository's strict allowlisted
loader and are injected directly into the S3 client factory.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any
from urllib.parse import urlsplit

from ...config import RepoPaths, load_allowlisted_secret_values
from ..local_deployment.handoff import (
    DownloadSpec,
    HandoffError,
    HandoffScope,
    ScopedHandoffClient,
)
from .contract import (
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    regular_file,
    sha256_bytes,
    sha256_file,
    write_exclusive,
)


HANDOFF_SCHEMA = "rondo-publication-critic-plan082-s3-handoff-v1"
BOOTSTRAP_SCHEMA = "rondo-publication-critic-plan082-bootstrap-manifest-v1"
S3_SECRET_NAMES = (
    "RUNPOD_S3_ACCESS_KEY_ID",
    "RUNPOD_S3_SECRET_ACCESS_KEY",
)
DESTINATION_PREFIX = PurePosixPath("eval-data/publication-critic/plan082/handoff")
MAX_OBJECTS = 512
MAX_TOTAL_BYTES = 64 * 1024 * 1024 * 1024
MAX_BOOTSTRAP_BYTES = 16 * 1024 * 1024
_REGION = re.compile(r"[a-z]{2}(?:-[a-z0-9]+)+\Z")
_RUN_ID = re.compile(r"plan082-[a-z0-9][a-z0-9._-]{0,95}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True)
class Plan082Handoff:
    freeze_sha256: str
    volume_id: str
    region: str
    endpoint: str
    task_root: str
    allowed_prefixes: tuple[str, ...]
    destination_relative: str
    bootstrap: DownloadSpec
    max_objects: int
    max_total_bytes: int

    @property
    def scope(self) -> HandoffScope:
        return HandoffScope(
            bucket=self.volume_id,
            root=self.task_root,
            allowed_prefixes=self.allowed_prefixes,
            allowed_objects=frozenset({self.bootstrap.relative_key}),
        )


def handoff_value(binding: Plan082Handoff) -> dict[str, Any]:
    """Return the complete non-secret binding for validation or persistence."""

    if not isinstance(binding, Plan082Handoff):
        raise HandoffError("plan082_handoff_invalid")
    return {
        "schema": HANDOFF_SCHEMA,
        "freeze_sha256": binding.freeze_sha256,
        "volume_id": binding.volume_id,
        "region": binding.region,
        "endpoint": binding.endpoint,
        "task_root": binding.task_root,
        "allowed_prefixes": list(binding.allowed_prefixes),
        "destination_relative": binding.destination_relative,
        "bootstrap_manifest": {
            "relative_key": binding.bootstrap.relative_key,
            "bytes": binding.bootstrap.size,
            "sha256": binding.bootstrap.sha256,
        },
        "limits": {
            "max_objects": binding.max_objects,
            "max_total_bytes": binding.max_total_bytes,
        },
    }


def load_handoff(path: Path) -> Plan082Handoff:
    return validate_handoff(read_json(Path(path)))


def validate_handoff(value: Any) -> Plan082Handoff:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "freeze_sha256",
        "volume_id",
        "region",
        "endpoint",
        "task_root",
        "allowed_prefixes",
        "destination_relative",
        "bootstrap_manifest",
        "limits",
    }:
        raise HandoffError("plan082_handoff_fields_invalid")
    if value.get("schema") != HANDOFF_SCHEMA:
        raise HandoffError("plan082_handoff_schema_invalid")
    freeze_sha256 = _require_sha256(value.get("freeze_sha256"))
    volume_id = value.get("volume_id")
    region = value.get("region")
    endpoint = value.get("endpoint")
    task_root = value.get("task_root")
    if (
        not isinstance(volume_id, str)
        or not volume_id
        or volume_id == "hi3iaz8rsr"
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
            for character in volume_id
        )
        or not isinstance(region, str)
        or _REGION.fullmatch(region) is None
        or not isinstance(endpoint, str)
        or endpoint != f"https://s3api-{region}.runpod.io/"
        or not _safe_endpoint(endpoint)
        or not isinstance(task_root, str)
        or not task_root.startswith("rondo-plan082-")
        or not task_root.endswith("/")
    ):
        raise HandoffError("plan082_handoff_provider_binding_invalid")
    _safe_prefix(task_root)

    prefixes_value = value.get("allowed_prefixes")
    if (
        not isinstance(prefixes_value, Sequence)
        or isinstance(prefixes_value, (str, bytes, bytearray))
        or not prefixes_value
        or any(not isinstance(item, str) for item in prefixes_value)
    ):
        raise HandoffError("plan082_handoff_prefixes_invalid")
    prefixes = tuple(prefixes_value)
    if len(set(prefixes)) != len(prefixes):
        raise HandoffError("plan082_handoff_prefixes_invalid")
    for prefix in prefixes:
        _safe_prefix(prefix)

    destination = value.get("destination_relative")
    if not isinstance(destination, str):
        raise HandoffError("plan082_handoff_destination_invalid")
    destination_path = _safe_relative(destination)
    if (
        destination_path == DESTINATION_PREFIX
        or not destination_path.is_relative_to(DESTINATION_PREFIX)
        or len(destination_path.parts) != len(DESTINATION_PREFIX.parts) + 1
        or _RUN_ID.fullmatch(destination_path.name) is None
    ):
        raise HandoffError("plan082_handoff_destination_invalid")

    bootstrap_value = value.get("bootstrap_manifest")
    if not isinstance(bootstrap_value, Mapping) or set(bootstrap_value) != {
        "relative_key",
        "bytes",
        "sha256",
    }:
        raise HandoffError("plan082_bootstrap_binding_invalid")
    bootstrap = DownloadSpec(
        relative_key=_safe_key(bootstrap_value.get("relative_key")),
        size=_nonnegative_int(bootstrap_value.get("bytes")),
        sha256=_require_sha256(bootstrap_value.get("sha256")),
    )
    if (
        bootstrap.size > MAX_BOOTSTRAP_BYTES
        or bootstrap.relative_key.endswith(".part")
        or any(bootstrap.relative_key.startswith(prefix) for prefix in prefixes)
    ):
        raise HandoffError("plan082_bootstrap_binding_invalid")

    limits = value.get("limits")
    if not isinstance(limits, Mapping) or set(limits) != {
        "max_objects",
        "max_total_bytes",
    }:
        raise HandoffError("plan082_handoff_limits_invalid")
    max_objects = _positive_int(limits.get("max_objects"))
    max_total_bytes = _positive_int(limits.get("max_total_bytes"))
    if max_objects > MAX_OBJECTS or max_total_bytes > MAX_TOTAL_BYTES:
        raise HandoffError("plan082_handoff_limits_invalid")
    return Plan082Handoff(
        freeze_sha256=freeze_sha256,
        volume_id=volume_id,
        region=region,
        endpoint=endpoint,
        task_root=task_root,
        allowed_prefixes=prefixes,
        destination_relative=destination,
        bootstrap=bootstrap,
        max_objects=max_objects,
        max_total_bytes=max_total_bytes,
    )


def create_bootstrap_manifest(
    destination: Path,
    *,
    freeze_sha256: str,
    objects: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    freeze = _require_sha256(freeze_sha256)
    if (
        not isinstance(objects, Sequence)
        or isinstance(objects, (str, bytes, bytearray))
        or not objects
        or len(objects) > MAX_OBJECTS
    ):
        raise HandoffError("plan082_bootstrap_objects_invalid")
    normalized: list[dict[str, Any]] = []
    total = 0
    for item in objects:
        if not isinstance(item, Mapping) or set(item) != {
            "relative_key",
            "bytes",
            "sha256",
            "roles",
        }:
            raise HandoffError("plan082_bootstrap_objects_invalid")
        key = _safe_key(item.get("relative_key"))
        roles = item.get("roles")
        if (
            key.endswith(".part")
            or not isinstance(roles, Sequence)
            or isinstance(roles, (str, bytes, bytearray))
            or not roles
            or any(not isinstance(role, str) or not role for role in roles)
        ):
            raise HandoffError("plan082_bootstrap_objects_invalid")
        size = _nonnegative_int(item.get("bytes"))
        total += size
        if total > MAX_TOTAL_BYTES:
            raise HandoffError("plan082_bootstrap_total_bytes_exceeded")
        normalized.append(
            {
                "relative_key": key,
                "bytes": size,
                "sha256": _require_sha256(item.get("sha256")),
                "roles": list(roles),
            }
        )
    _validate_local_destination_plan(tuple(row["relative_key"] for row in normalized))
    if len({row["relative_key"] for row in normalized}) != len(normalized):
        raise HandoffError("plan082_bootstrap_object_duplicate")
    core = {
        "schema": BOOTSTRAP_SCHEMA,
        "freeze_sha256": freeze,
        "objects": normalized,
    }
    value = {
        **core,
        "content_sha256": sha256_bytes(canonical_json_bytes(core)),
    }
    raw = pretty_json_bytes(value)
    write_exclusive(Path(destination), raw)
    return {
        "path": str(Path(destination)),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "content_sha256": value["content_sha256"],
        "object_count": len(normalized),
        "total_bytes": total,
    }


def create_handoff_binding(
    destination: Path,
    *,
    freeze_sha256: str,
    volume_id: str,
    region: str,
    task_root: str,
    allowed_prefixes: Sequence[str],
    run_id: str,
    bootstrap_key: str,
    bootstrap_path: Path,
    max_objects: int = MAX_OBJECTS,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> dict[str, Any]:
    bootstrap_file = regular_file(
        Path(bootstrap_path), maximum_bytes=MAX_BOOTSTRAP_BYTES
    )
    bootstrap_raw = bootstrap_file.read_bytes()
    value = {
        "schema": HANDOFF_SCHEMA,
        "freeze_sha256": freeze_sha256,
        "volume_id": volume_id,
        "region": region,
        "endpoint": f"https://s3api-{region}.runpod.io/",
        "task_root": task_root,
        "allowed_prefixes": list(allowed_prefixes),
        "destination_relative": f"{DESTINATION_PREFIX.as_posix()}/{run_id}",
        "bootstrap_manifest": {
            "relative_key": bootstrap_key,
            "bytes": bootstrap_file.stat().st_size,
            "sha256": sha256_file(bootstrap_file),
        },
        "limits": {
            "max_objects": max_objects,
            "max_total_bytes": max_total_bytes,
        },
    }
    binding = validate_handoff(value)
    bootstrap_manifest_specs(bootstrap_raw, binding=binding)
    raw = pretty_json_bytes(handoff_value(binding))
    write_exclusive(Path(destination), raw)
    return {
        "path": str(Path(destination)),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
        "binding": handoff_value(binding),
    }


def create_handoff_client(
    paths: RepoPaths,
    binding: Plan082Handoff,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> ScopedHandoffClient:
    binding = validate_handoff(handoff_value(binding))
    values = load_allowlisted_secret_values(paths, S3_SECRET_NAMES)
    if client_factory is None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError:
            raise HandoffError("handoff_boto3_unavailable") from None

        def client_factory(**kwargs: Any) -> Any:
            return boto3.client(
                "s3",
                config=Config(
                    signature_version="s3v4",
                    s3={"addressing_style": "path"},
                ),
                **kwargs,
            )

    try:
        client = client_factory(
            endpoint_url=binding.endpoint,
            region_name=binding.region,
            aws_access_key_id=values[S3_SECRET_NAMES[0]],
            aws_secret_access_key=values[S3_SECRET_NAMES[1]],
        )
    except Exception:
        raise HandoffError("handoff_client_create_failed") from None
    return ScopedHandoffClient(client, scope=binding.scope)


def bootstrap_manifest_specs(
    raw: bytes,
    *,
    binding: Plan082Handoff,
) -> tuple[DownloadSpec, ...]:
    if (
        sha256_bytes(raw) != binding.bootstrap.sha256
        or len(raw) != binding.bootstrap.size
    ):
        raise HandoffError("plan082_bootstrap_identity_mismatch")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise HandoffError("plan082_bootstrap_invalid") from None
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "freeze_sha256",
        "objects",
        "content_sha256",
    }:
        raise HandoffError("plan082_bootstrap_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    if (
        value.get("schema") != BOOTSTRAP_SCHEMA
        or value.get("freeze_sha256") != binding.freeze_sha256
        or value.get("content_sha256") != sha256_bytes(canonical_json_bytes(core))
    ):
        raise HandoffError("plan082_bootstrap_invalid")
    objects = value.get("objects")
    if (
        not isinstance(objects, Sequence)
        or isinstance(objects, (str, bytes, bytearray))
        or not objects
        or len(objects) > binding.max_objects
    ):
        raise HandoffError("plan082_bootstrap_objects_invalid")
    specs: dict[str, DownloadSpec] = {}
    total = 0
    for item in objects:
        if not isinstance(item, Mapping) or set(item) != {
            "relative_key",
            "bytes",
            "sha256",
            "roles",
        }:
            raise HandoffError("plan082_bootstrap_objects_invalid")
        key = _safe_key(item.get("relative_key"))
        roles = item.get("roles")
        if (
            key == binding.bootstrap.relative_key
            or key.endswith(".part")
            or not any(key.startswith(prefix) for prefix in binding.allowed_prefixes)
            or not isinstance(roles, Sequence)
            or isinstance(roles, (str, bytes, bytearray))
            or not roles
            or any(not isinstance(role, str) or not role for role in roles)
        ):
            raise HandoffError("plan082_bootstrap_objects_invalid")
        spec = DownloadSpec(
            relative_key=key,
            size=_nonnegative_int(item.get("bytes")),
            sha256=_require_sha256(item.get("sha256")),
        )
        if key in specs:
            raise HandoffError("plan082_bootstrap_object_duplicate")
        specs[key] = spec
        total += spec.size
        if total > binding.max_total_bytes:
            raise HandoffError("plan082_bootstrap_total_bytes_exceeded")
    _validate_local_destination_plan(
        (binding.bootstrap.relative_key, *specs),
    )
    return tuple(specs.values())


def inventory(
    client: ScopedHandoffClient,
    binding: Plan082Handoff,
    destination_root: Path,
) -> tuple[dict[str, object], ...]:
    bootstrap = _remote_exact_spec(client, binding.bootstrap)
    first = _transfer_one(client, destination_root, bootstrap)
    records = [first]
    raw = _read_verified_existing(destination_root, bootstrap)
    for spec in bootstrap_manifest_specs(raw, binding=binding):
        remote = _remote_exact_spec(client, spec)
        records.append(_record(remote, _existing_status(destination_root, remote)))
    return tuple(records)


def download(
    client: ScopedHandoffClient,
    binding: Plan082Handoff,
    destination_root: Path,
    *,
    emit: Callable[[dict[str, object]], None] | None = None,
) -> tuple[dict[str, object], ...]:
    sink = emit or (lambda _record: None)
    bootstrap = _remote_exact_spec(client, binding.bootstrap)
    first = _transfer_one(client, destination_root, bootstrap)
    sink(first)
    records = [first]
    raw = _read_verified_existing(destination_root, bootstrap)
    for spec in bootstrap_manifest_specs(raw, binding=binding):
        remote = _remote_exact_spec(client, spec)
        record = _transfer_one(client, destination_root, remote)
        sink(record)
        records.append(record)
    return tuple(records)


def _remote_exact_spec(
    client: ScopedHandoffClient, expected: DownloadSpec
) -> DownloadSpec:
    remote = client.head(expected.relative_key)
    if remote.size != expected.size:
        raise HandoffError("download_remote_size_mismatch")
    return expected


def _transfer_one(
    client: ScopedHandoffClient,
    destination_root: Path,
    spec: DownloadSpec,
) -> dict[str, object]:
    status = _existing_status(destination_root, spec)
    if status == "verified_existing":
        return _record(spec, status)
    if status not in {"missing", "partial"}:
        raise HandoffError("download_existing_identity_mismatch")
    client.download(spec, destination_root)
    return _record(spec, "downloaded")


def _existing_status(destination_root: Path, spec: DownloadSpec) -> str:
    path = Path(destination_root).joinpath(*PurePosixPath(spec.relative_key).parts)
    _reject_symlink_chain(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        partial = path.with_name(path.name + ".part")
        try:
            partial_info = os.lstat(partial)
        except FileNotFoundError:
            return "missing"
        except OSError:
            raise HandoffError("download_path_inspection_failed") from None
        if stat.S_ISREG(partial_info.st_mode) and not stat.S_ISLNK(
            partial_info.st_mode
        ):
            return "partial"
        return "invalid_partial"
    except OSError:
        raise HandoffError("download_path_inspection_failed") from None
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size != spec.size
    ):
        return "invalid_existing"
    return (
        "verified_existing"
        if _sha256_regular(path) == spec.sha256
        else "invalid_existing"
    )


def _read_verified_existing(destination_root: Path, spec: DownloadSpec) -> bytes:
    if _existing_status(destination_root, spec) != "verified_existing":
        raise HandoffError("handoff_local_manifest_missing_or_invalid")
    path = Path(destination_root).joinpath(*PurePosixPath(spec.relative_key).parts)
    try:
        return path.read_bytes()
    except OSError:
        raise HandoffError("handoff_local_manifest_unreadable") from None


def _reject_symlink_chain(path: Path) -> None:
    absolute = path if path.is_absolute() else Path.cwd() / path
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError:
            raise HandoffError("download_path_inspection_failed") from None
        if stat.S_ISLNK(info.st_mode):
            raise HandoffError("download_path_symlink_rejected")


def _sha256_regular(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise HandoffError("download_existing_hash_failed") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise HandoffError("download_existing_hash_failed")
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
    except HandoffError:
        raise
    except OSError:
        raise HandoffError("download_existing_hash_failed") from None
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _record(spec: DownloadSpec, status: str) -> dict[str, object]:
    return {
        "key": spec.relative_key,
        "size": spec.size,
        "sha256": spec.sha256,
        "status": status,
    }


def _safe_endpoint(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname.endswith(".runpod.io")
            and parsed.username is None
            and parsed.password is None
            and parsed.port is None
            and parsed.path == "/"
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _safe_relative(value: str) -> PurePosixPath:
    if not value or "\\" in value or "//" in value:
        raise HandoffError("plan082_handoff_relative_path_invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise HandoffError("plan082_handoff_relative_path_invalid")
    return path


def _safe_prefix(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("/"):
        raise HandoffError("plan082_handoff_prefix_invalid")
    _safe_relative(value[:-1])
    return value


def _safe_key(value: Any) -> str:
    if not isinstance(value, str) or not value or value.endswith("/"):
        raise HandoffError("plan082_handoff_key_invalid")
    _safe_relative(value)
    return value


def _validate_local_destination_plan(keys: Sequence[str]) -> None:
    """Reject file/directory and downloader ``.part`` path collisions."""

    destinations: list[PurePosixPath] = []
    for key in keys:
        path = _safe_relative(key)
        destinations.extend((path, path.with_name(path.name + ".part")))
    if len(set(destinations)) != len(destinations):
        raise HandoffError("plan082_bootstrap_path_collision")
    for index, path in enumerate(destinations):
        if any(
            path != other and path.is_relative_to(other)
            for other in destinations[index + 1 :]
        ) or any(
            path != other and other.is_relative_to(path)
            for other in destinations[index + 1 :]
        ):
            raise HandoffError("plan082_bootstrap_path_collision")


def _require_sha256(value: Any) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise HandoffError("sha256_invalid")
    return value


def _positive_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise HandoffError("plan082_positive_int_invalid")
    return value


def _nonnegative_int(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HandoffError("plan082_nonnegative_int_invalid")
    return value


def manifest_content_sha256(value: Mapping[str, Any]) -> str:
    """Small public helper used by the cloud finalizer and focused tests."""

    core = {key: item for key, item in value.items() if key != "content_sha256"}
    return sha256_bytes(canonical_json_bytes(core))
