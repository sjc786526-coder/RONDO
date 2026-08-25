"""Write-once observations and separated Plan 081 training artifacts."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import Any
import uuid

from ..write_once import WriteOnceError, WriteOnceNamespace
from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    read_json,
    safe_directory,
    sha256_bytes,
    sha256_file,
    write_exclusive,
)
from .plan081_observation import OBSERVATION_SCHEMA


SNAPSHOT_SCHEMA = "rondo-publication-critic-plan081-evaluation-snapshot-v1"
CHECKPOINT_SCHEMA = "rondo-publication-critic-plan081-recovery-checkpoint-v1"
MANIFEST_NAME = "artifact-manifest.json"
_ARTIFACT_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}\Z")
_STAGING_NAME = re.compile(
    r"\.(?P<artifact>[a-z0-9][a-z0-9-]{0,79})\.tmp-[0-9a-f]{32}\Z"
)
_ATTEMPT_ARTIFACT_ID = re.compile(
    r"(?:observation|snapshot|checkpoint)-attempt-(?P<generation>[0-9]+)-step-[0-9]+\Z"
)
_ATTEMPT_RESERVATION = re.compile(r"attempt-(?P<generation>[0-9]+)\Z")


class Plan081ArtifactStore:
    """A task-owned root with permanent observations and prunable large artifacts."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise FullModelTrainingError("plan081_artifact_root_unsafe")

    def write_observation(self, observation_id: str, value: Mapping[str, Any]) -> dict[str, Any]:
        _require_artifact_id(observation_id)
        if value.get("schema") != OBSERVATION_SCHEMA:
            raise FullModelTrainingError("plan081_observation_schema_invalid")
        namespace = WriteOnceNamespace(
            self.root / "observations",
            observation_id,
            validate_run_id=lambda candidate: bool(_ARTIFACT_ID.fullmatch(candidate)),
        )
        try:
            path = namespace.create().write_bytes("observation.json", pretty_json_bytes(value))
        except WriteOnceError as exc:
            raise FullModelTrainingError("plan081_observation_write_failed") from exc
        return {
            "observation_id": observation_id,
            "relative": f"observations/{observation_id}/observation.json",
            "sha256": sha256_file(path),
        }

    def read_observation(self, observation_id: str) -> dict[str, Any]:
        self.verify_observation(observation_id)
        path = self.root / "observations" / observation_id / "observation.json"
        return dict(read_json(path))

    def verify_observation(self, observation_id: str) -> dict[str, Any]:
        _require_artifact_id(observation_id)
        path = self.root / "observations" / observation_id / "observation.json"
        value = read_json(path)
        if not isinstance(value, Mapping) or value.get("schema") != OBSERVATION_SCHEMA:
            raise FullModelTrainingError("plan081_observation_invalid")
        return {
            "observation_id": observation_id,
            "relative": f"observations/{observation_id}/observation.json",
            "sha256": sha256_file(path),
        }

    def save_snapshot(
        self,
        artifact_id: str,
        *,
        model_saver: Callable[[Path], None],
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._write_artifact(
            "model-snapshots",
            artifact_id,
            schema=SNAPSHOT_SCHEMA,
            metadata=metadata,
            populate=lambda staging: model_saver(_created_payload(staging)),
        )

    def save_checkpoint(
        self,
        artifact_id: str,
        *,
        model_saver: Callable[[Path], None],
        training_state: Mapping[str, Any],
        controller_state: Mapping[str, Any],
        metadata: Mapping[str, Any],
        state_writer: Callable[[Path, Mapping[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        def populate(staging: Path) -> None:
            model_saver(_created_payload(staging))
            writer = state_writer or _write_json_state
            writer(staging / "training-state", training_state)
            write_exclusive(
                staging / "controller-state.json", pretty_json_bytes(controller_state)
            )

        return self._write_artifact(
            "recovery-checkpoints",
            artifact_id,
            schema=CHECKPOINT_SCHEMA,
            metadata=metadata,
            populate=populate,
        )

    def verify_snapshot(self, artifact_id: str) -> dict[str, Any]:
        return self._verify_artifact("model-snapshots", artifact_id, SNAPSHOT_SCHEMA)

    def verify_checkpoint(self, artifact_id: str) -> dict[str, Any]:
        return self._verify_artifact(
            "recovery-checkpoints", artifact_id, CHECKPOINT_SCHEMA
        )

    def load_checkpoint(
        self,
        artifact_id: str,
        *,
        model_loader: Callable[[Path], None],
        state_reader: Callable[[Path], Mapping[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], Mapping[str, Any]]:
        controller, training, payload = self.read_checkpoint(
            artifact_id, state_reader=state_reader
        )
        model_loader(payload)
        return controller, training

    def read_checkpoint(
        self,
        artifact_id: str,
        *,
        state_reader: Callable[[Path], Mapping[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], Mapping[str, Any], Path]:
        """Verify and decode state without mutating a runtime adapter."""

        self.verify_checkpoint(artifact_id)
        root = self.root / "recovery-checkpoints" / artifact_id
        controller = read_json(root / "controller-state.json")
        reader = state_reader or _read_json_state
        training = reader(root / "training-state")
        if not isinstance(controller, Mapping) or not isinstance(training, Mapping):
            raise FullModelTrainingError("plan081_checkpoint_state_invalid")
        return dict(controller), training, safe_directory(root / "payload")

    def prune(
        self,
        *,
        keep_snapshot_ids: set[str],
        keep_checkpoint_ids: set[str],
        prune_checkpoints: bool = True,
    ) -> dict[str, list[str]]:
        """Prune only verified task-owned artifacts; observations are untouched."""

        for artifact_id in keep_snapshot_ids | keep_checkpoint_ids:
            _require_artifact_id(artifact_id)
        snapshots = self._artifact_ids("model-snapshots")
        checkpoints = self._artifact_ids("recovery-checkpoints")
        effective_checkpoint_ids = (
            keep_checkpoint_ids if prune_checkpoints else checkpoints
        )
        missing_snapshots = keep_snapshot_ids - snapshots
        missing_checkpoints = effective_checkpoint_ids - checkpoints
        if missing_snapshots or missing_checkpoints:
            raise FullModelTrainingError("plan081_retained_artifact_missing")
        if checkpoints and not effective_checkpoint_ids:
            raise FullModelTrainingError("plan081_unique_recovery_point_required")

        # Verify every replacement before any superseded recovery point is removed.
        for artifact_id in sorted(keep_snapshot_ids):
            self.verify_snapshot(artifact_id)
        for artifact_id in sorted(effective_checkpoint_ids):
            self.verify_checkpoint(artifact_id)

        removed_snapshots: list[str] = []
        for artifact_id in sorted(snapshots - keep_snapshot_ids):
            self.verify_snapshot(artifact_id)
            _remove_owned_tree(self.root / "model-snapshots" / artifact_id)
            removed_snapshots.append(artifact_id)
        removed_checkpoints: list[str] = []
        for artifact_id in sorted(checkpoints - effective_checkpoint_ids):
            self.verify_checkpoint(artifact_id)
            _remove_owned_tree(self.root / "recovery-checkpoints" / artifact_id)
            removed_checkpoints.append(artifact_id)
        return {
            "removed_snapshots": removed_snapshots,
            "removed_checkpoints": removed_checkpoints,
        }

    def recover_incomplete_staging(self) -> list[str]:
        """Remove only exact task-owned staging trees left before atomic publish."""

        removed: list[str] = []
        for kind in ("model-snapshots", "recovery-checkpoints"):
            parent = self.root / kind
            if not parent.exists():
                continue
            safe_directory(parent)
            for path in sorted(parent.iterdir()):
                if not path.name.startswith("."):
                    continue
                if _STAGING_NAME.fullmatch(path.name) is None:
                    raise FullModelTrainingError("plan081_unknown_hidden_artifact")
                safe_directory(path)
                _remove_owned_tree(path)
                removed.append(f"{kind}/{path.name}")
        return removed

    def reserve_artifact_generation(self, *, after_generation: int) -> int:
        """Permanently reserve a fresh attempt generation, including across crashes."""

        if (
            not isinstance(after_generation, int)
            or isinstance(after_generation, bool)
            or after_generation < 0
        ):
            raise FullModelTrainingError("plan081_artifact_generation_invalid")
        used = {after_generation}
        for kind in ("observations", "model-snapshots", "recovery-checkpoints"):
            for artifact_id in self._artifact_ids(kind):
                match = _ATTEMPT_ARTIFACT_ID.fullmatch(artifact_id)
                if match is not None:
                    used.add(int(match.group("generation")))

        reservations = self.root / "attempt-reservations"
        reservations.mkdir(mode=0o700, exist_ok=True)
        if reservations.is_symlink() or not reservations.is_dir():
            raise FullModelTrainingError("plan081_attempt_reservations_unsafe")
        for path in reservations.iterdir():
            match = _ATTEMPT_RESERVATION.fullmatch(path.name)
            info = os.lstat(path)
            if match is None or not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise FullModelTrainingError("plan081_attempt_reservation_invalid")
            used.add(int(match.group("generation")))

        generation = max(used) + 1
        while True:
            destination = reservations / f"attempt-{generation:06d}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            try:
                descriptor = os.open(destination, flags, 0o600)
            except FileExistsError:
                generation += 1
                continue
            try:
                raw = f"artifact_generation={generation}\n".encode("ascii")
                view = memoryview(raw)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("attempt reservation write did not progress")
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return generation

    def _write_artifact(
        self,
        kind: str,
        artifact_id: str,
        *,
        schema: str,
        metadata: Mapping[str, Any],
        populate: Callable[[Path], None],
    ) -> dict[str, Any]:
        _require_artifact_id(artifact_id)
        parent = self.root / kind
        parent.mkdir(mode=0o700, exist_ok=True)
        if parent.is_symlink() or not parent.is_dir():
            raise FullModelTrainingError("plan081_artifact_parent_unsafe")
        destination = parent / artifact_id
        if destination.exists() or destination.is_symlink():
            raise FullModelTrainingError("plan081_artifact_exists")
        staging = parent / f".{artifact_id}.tmp-{uuid.uuid4().hex}"
        staging.mkdir(mode=0o700)
        try:
            populate(staging)
            files = _tree_manifest(staging, exclude={MANIFEST_NAME})
            if not files or not any(name.startswith("payload/") for name in files):
                raise FullModelTrainingError("plan081_artifact_payload_empty")
            core = {
                "schema": schema,
                "artifact_id": artifact_id,
                "kind": kind,
                "metadata": json.loads(json.dumps(metadata)),
                "files": files,
            }
            manifest = {
                **core,
                "content_sha256": sha256_bytes(canonical_json_bytes(core)),
            }
            write_exclusive(staging / MANIFEST_NAME, pretty_json_bytes(manifest))
            os.replace(staging, destination)
        except BaseException:
            if staging.exists() and not staging.is_symlink():
                shutil.rmtree(staging)
            raise
        return self._verify_artifact(kind, artifact_id, schema)

    def _verify_artifact(self, kind: str, artifact_id: str, schema: str) -> dict[str, Any]:
        _require_artifact_id(artifact_id)
        root = safe_directory(self.root / kind / artifact_id)
        manifest_path = root / MANIFEST_NAME
        manifest = read_json(manifest_path)
        expected = {
            "schema",
            "artifact_id",
            "kind",
            "metadata",
            "files",
            "content_sha256",
        }
        if (
            not isinstance(manifest, Mapping)
            or set(manifest) != expected
            or manifest.get("schema") != schema
            or manifest.get("artifact_id") != artifact_id
            or manifest.get("kind") != kind
            or not isinstance(manifest.get("metadata"), Mapping)
            or not isinstance(manifest.get("files"), Mapping)
        ):
            raise FullModelTrainingError("plan081_artifact_manifest_invalid")
        core = {key: value for key, value in manifest.items() if key != "content_sha256"}
        if sha256_bytes(canonical_json_bytes(core)) != manifest.get("content_sha256"):
            raise FullModelTrainingError("plan081_artifact_manifest_mismatch")
        actual = _tree_manifest(root, exclude={MANIFEST_NAME})
        if actual != manifest["files"]:
            raise FullModelTrainingError("plan081_artifact_tree_mismatch")
        return {
            "schema": schema,
            "artifact_id": artifact_id,
            "kind": kind,
            "manifest_sha256": sha256_file(manifest_path),
            "content_sha256": manifest["content_sha256"],
            "bytes": sum(int(item["bytes"]) for item in actual.values()),
            "file_count": len(actual) + 1,
            "metadata": dict(manifest["metadata"]),
        }

    def _artifact_ids(self, kind: str) -> set[str]:
        parent = self.root / kind
        if not parent.exists():
            return set()
        safe_directory(parent)
        result: set[str] = set()
        for path in parent.iterdir():
            if path.name.startswith("."):
                raise FullModelTrainingError("plan081_staging_artifact_present")
            _require_artifact_id(path.name)
            safe_directory(path)
            result.add(path.name)
        return result


def _require_artifact_id(value: str) -> str:
    if not isinstance(value, str) or not _ARTIFACT_ID.fullmatch(value):
        raise FullModelTrainingError("plan081_artifact_id_invalid")
    return value


def _created_payload(staging: Path) -> Path:
    payload = staging / "payload"
    payload.mkdir(mode=0o700)
    return payload


def _write_json_state(path: Path, value: Mapping[str, Any]) -> None:
    write_exclusive(path, pretty_json_bytes(value))


def _read_json_state(path: Path) -> Mapping[str, Any]:
    value = read_json(path)
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan081_training_state_invalid")
    return value


def _tree_manifest(root: Path, *, exclude: set[str]) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        info = os.lstat(path)
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise FullModelTrainingError("plan081_artifact_non_regular_entry")
        if relative in exclude:
            continue
        files[relative] = {"bytes": info.st_size, "sha256": sha256_file(path)}
    return files


def _remove_owned_tree(path: Path) -> None:
    root = safe_directory(path)
    try:
        shutil.rmtree(root)
    except OSError as exc:
        raise FullModelTrainingError("plan081_artifact_prune_failed") from exc
