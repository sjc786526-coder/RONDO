"""Narrow Plan 068 CLI for the exact, read-only RunPod S3 handoff."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

from ...config import ConfigError, RepoPaths, load_allowlisted_secret_values
from .artifacts import (
    CANDIDATE_PAYLOAD_BYTES,
    CHECKPOINT_PAYLOAD_BYTES,
    KnownObject,
    exact_base_requirements,
    formal_manifest_requirements,
    parse_artifact_manifest,
)
from .handoff import (
    FORMAL_FREEZE_PREFIX,
    FORMAL_RUN_PREFIX,
    HANDOFF_ROOT,
    SOURCE_BUNDLE_PREFIX,
    VOLUME_ID,
    WINNER_LOCK_KEY,
    DownloadSpec,
    HandoffClient,
    HandoffError,
)


RUNPOD_S3_ENDPOINT = "https://s3api-us-ks-2.runpod.io/"
RUNPOD_S3_REGION = "us-ks-2"
S3_SECRET_NAMES = (
    "RUNPOD_S3_ACCESS_KEY_ID",
    "RUNPOD_S3_SECRET_ACCESS_KEY",
)
HANDOFF_DESTINATION_RELATIVE = Path(
    "eval-data/publication-critic/plan068/handoff"
)

BUNDLE_MANIFEST = KnownObject(
    SOURCE_BUNDLE_PREFIX + "bundle-manifest.json",
    "2970c693fa32d1118d3b8e949a04231970bf96dfc27f7c7d14a22f98a4ed2252",
    19_210,
)
DEPENDENCY_FREEZE = KnownObject(
    FORMAL_FREEZE_PREFIX + "dependency-freeze.txt",
    "891a81e9ac5217057d8348916504d67246b8c3edfd9404d9e47d0ddbf913c0bb",
    3_108,
)
DEPENDENCY_IDENTITY = KnownObject(
    FORMAL_FREEZE_PREFIX + "dependency-identity.json",
    "75c7f447ca47f0d78beb08120f3233b10b9b1b402b766906065f18e7132b2947",
    828,
)
FLASHOPTIM_WHEEL = KnownObject(
    "wheels/flashoptim-0.1.4-py3-none-any.whl",
    "8a4a3f2528fbda419d4f4dd0c9debb3de22bd0a45969bee2eb5a58185d3bd451",
    46_638,
)
FORMAL_START = KnownObject(
    FORMAL_RUN_PREFIX + "plan066-formal-start.json",
    "cdb9c9a41d054077ee6ae2455eab4d3fe3902b4cb5b99940ae6d06ebae19ccdd",
    21_388,
)
FORMAL_PENDING = KnownObject(
    FORMAL_RUN_PREFIX + "plan066-formal-pending.json",
    "e4b38b40270cf20947b4713fc2cc5c9dbca621b242ba1ccc965c7bef5aafc228",
    11_775,
)
WINNER_LOCK = KnownObject(
    WINNER_LOCK_KEY,
    "b8774c1776855efacf1e1fd284128a081da7d220450aefdbfc43e71e58590e57",
    753,
)


def fixed_requirements() -> tuple[KnownObject, ...]:
    """Return the tracked, exact objects that do not depend on a manifest body."""

    formal = formal_manifest_requirements(FORMAL_RUN_PREFIX)
    return (
        *exact_base_requirements(),
        *formal[:4],
        BUNDLE_MANIFEST,
        DEPENDENCY_FREEZE,
        DEPENDENCY_IDENTITY,
        FLASHOPTIM_WHEEL,
        FORMAL_START,
        FORMAL_PENDING,
        WINNER_LOCK,
    )


def create_handoff_client(
    paths: RepoPaths,
    *,
    client_factory: Callable[..., Any] | None = None,
) -> HandoffClient:
    """Load exactly two secrets and inject them only into the S3 client."""

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
        s3 = client_factory(
            endpoint_url=RUNPOD_S3_ENDPOINT,
            region_name=RUNPOD_S3_REGION,
            aws_access_key_id=values[S3_SECRET_NAMES[0]],
            aws_secret_access_key=values[S3_SECRET_NAMES[1]],
        )
    except Exception:
        raise HandoffError("handoff_client_create_failed") from None
    return HandoffClient(s3, bucket=VOLUME_ID, root=HANDOFF_ROOT)


def resolve_fixed_plan(client: HandoffClient) -> tuple[DownloadSpec, ...]:
    """HEAD every exact fixed object and bind provider size to tracked hash."""

    resolved: list[DownloadSpec] = []
    for known in fixed_requirements():
        remote = client.head(known.relative_key)
        if known.size is not None and remote.size != known.size:
            raise HandoffError("handoff_known_size_mismatch")
        resolved.append(DownloadSpec(known.relative_key, remote.size, known.sha256))
    return tuple(resolved)


def expand_verified_manifests(
    destination_root: Path,
    fixed: Iterable[DownloadSpec],
) -> tuple[DownloadSpec, ...]:
    """Expand only local manifests already verified by their fixed specs."""

    by_key = {item.relative_key: item for item in fixed}
    requirements = formal_manifest_requirements(FORMAL_RUN_PREFIX)[:4]
    requirements = (*requirements, BUNDLE_MANIFEST)
    expanded: list[DownloadSpec] = []
    for known in requirements:
        spec = by_key.get(known.relative_key)
        if spec is None:
            raise HandoffError("handoff_manifest_spec_missing")
        raw = _read_verified_existing(destination_root, spec)
        payload_bytes: int | None = None
        if "candidate-" in known.relative_key:
            payload_bytes = CANDIDATE_PAYLOAD_BYTES
        elif "/checkpoint-c3/" in known.relative_key:
            payload_bytes = CHECKPOINT_PAYLOAD_BYTES
        plan = parse_artifact_manifest(
            known.relative_key,
            raw,
            expected_sha256=known.sha256,
            expected_payload_bytes=payload_bytes,
        )
        expanded.extend(plan.files)
    return tuple(expanded)


def inventory(
    client: HandoffClient,
    destination_root: Path,
) -> tuple[dict[str, object], ...]:
    """HEAD exact objects and expand payloads only when manifests are local."""

    fixed = resolve_fixed_plan(client)
    manifest_specs = _manifest_specs(fixed)
    manifests_ready = all(
        _existing_status(destination_root, spec) == "verified_existing"
        for spec in manifest_specs
    )
    if manifests_ready:
        payload = expand_verified_manifests(destination_root, fixed)
        plan = _deduplicate((*fixed, *payload))
    else:
        plan = fixed
    return tuple(_record(spec, _existing_status(destination_root, spec)) for spec in plan)


def download(
    client: HandoffClient,
    destination_root: Path,
    *,
    emit: Callable[[dict[str, object]], None] | None = None,
) -> tuple[dict[str, object], ...]:
    """Download manifests first, then their exact payload trees and fixed objects."""

    sink = emit or (lambda _record: None)
    fixed = resolve_fixed_plan(client)
    manifest_specs = _manifest_specs(fixed)
    records: list[dict[str, object]] = []
    for spec in manifest_specs:
        record = _transfer_one(client, destination_root, spec)
        records.append(record)
        sink(record)
    payload = expand_verified_manifests(destination_root, fixed)
    remaining = _deduplicate(
        tuple(item for item in fixed if item not in manifest_specs) + payload
    )
    for spec in remaining:
        record = _transfer_one(client, destination_root, spec)
        records.append(record)
        sink(record)
    return tuple(records)


def _manifest_specs(fixed: Iterable[DownloadSpec]) -> tuple[DownloadSpec, ...]:
    return tuple(
        item
        for item in fixed
        if item.relative_key.endswith("candidate-manifest.json")
        or item.relative_key.endswith("checkpoint-manifest.json")
        or item.relative_key == BUNDLE_MANIFEST.relative_key
    )


def _transfer_one(
    client: HandoffClient,
    destination_root: Path,
    spec: DownloadSpec,
) -> dict[str, object]:
    status = _existing_status(destination_root, spec)
    if status == "verified_existing":
        return _record(spec, status)
    if status == "invalid_existing":
        raise HandoffError("download_existing_identity_mismatch")
    client.download(spec, destination_root)
    return _record(spec, "downloaded")


def _existing_status(destination_root: Path, spec: DownloadSpec) -> str:
    path = Path(destination_root).joinpath(*spec.relative_key.split("/"))
    path = path if path.is_absolute() else Path.cwd() / path
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
        if stat.S_ISREG(partial_info.st_mode) and not stat.S_ISLNK(partial_info.st_mode):
            return "partial"
        return "invalid_partial"
    except OSError:
        raise HandoffError("download_path_inspection_failed") from None
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return "invalid_existing"
    if stat.S_IMODE(info.st_mode) != 0o600:
        return "invalid_existing"
    if info.st_size != spec.size:
        return "invalid_existing"
    return "verified_existing" if _sha256(path) == spec.sha256 else "invalid_existing"


def _read_verified_existing(destination_root: Path, spec: DownloadSpec) -> bytes:
    if _existing_status(destination_root, spec) != "verified_existing":
        raise HandoffError("handoff_local_manifest_missing_or_invalid")
    path = Path(destination_root).joinpath(*spec.relative_key.split("/"))
    path = path if path.is_absolute() else Path.cwd() / path
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise HandoffError("handoff_local_manifest_unreadable") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size != spec.size:
            raise HandoffError("handoff_local_manifest_unreadable")
        chunks: list[bytes] = []
        remaining = spec.size
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                raise HandoffError("handoff_local_manifest_unreadable")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise HandoffError("handoff_local_manifest_unreadable")
        return b"".join(chunks)
    except HandoffError:
        raise
    except OSError:
        raise HandoffError("handoff_local_manifest_unreadable") from None
    finally:
        os.close(descriptor)


def _sha256(path: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise HandoffError("download_existing_hash_failed") from None
    digest = hashlib.sha256()
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


def _reject_symlink_chain(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            return
        except OSError:
            raise HandoffError("download_path_inspection_failed") from None
        if stat.S_ISLNK(info.st_mode):
            raise HandoffError("download_path_symlink_rejected")


def _deduplicate(specs: Iterable[DownloadSpec]) -> tuple[DownloadSpec, ...]:
    result: dict[str, DownloadSpec] = {}
    for spec in specs:
        previous = result.get(spec.relative_key)
        if previous is not None and previous != spec:
            raise HandoffError("handoff_plan_conflict")
        result.setdefault(spec.relative_key, spec)
    return tuple(result.values())


def _record(spec: DownloadSpec, status: str) -> dict[str, object]:
    return {
        "key": spec.relative_key,
        "size": spec.size,
        "hash": spec.sha256,
        "status": status,
    }


def _emit_json(record: dict[str, object]) -> None:
    print(json.dumps(record, sort_keys=True, separators=(",", ":")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="publication-critic-plan068-handoff")
    parser.add_argument("command", choices=("inventory", "download"))
    args = parser.parse_args(argv)
    try:
        paths = RepoPaths.discover(Path.cwd())
        destination = paths.common_root / HANDOFF_DESTINATION_RELATIVE
        client = create_handoff_client(paths)
        if args.command == "inventory":
            for record in inventory(client, destination):
                _emit_json(record)
        else:
            download(client, destination, emit=_emit_json)
    except (ConfigError, HandoffError) as exc:
        code = exc.code if isinstance(exc, HandoffError) else "handoff_config_invalid"
        _emit_json({"key": "", "size": 0, "hash": "", "status": f"error:{code}"})
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
