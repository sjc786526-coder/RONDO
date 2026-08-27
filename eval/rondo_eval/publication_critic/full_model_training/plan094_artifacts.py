"""Plan 094 checkpoint-backed evaluation overlays."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .contract import (
    FullModelTrainingError,
    pretty_json_bytes,
    read_json,
    safe_directory,
    write_exclusive,
)
from .plan081_artifacts import (
    _STAGING_NAME,
    _remove_owned_tree,
)
from .plan090_artifacts import Plan090ArtifactStore


EVALUATION_RESULT_SCHEMA = (
    "rondo-publication-critic-plan094-checkpoint-evaluation-v1"
)


class Plan094ArtifactStore(Plan090ArtifactStore):
    """Reuse full checkpoints and add a small atomic evaluation overlay."""

    def publish_evaluation_result(
        self,
        checkpoint_id: str,
        *,
        checkpoint_content_sha256: str,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._recover_evaluation_staging()
        parent = self.root / "evaluation-results"
        destination = parent / checkpoint_id
        if destination.exists() or destination.is_symlink():
            existing = self.read_evaluation_result(checkpoint_id)
            if existing != value:
                raise FullModelTrainingError(
                    "plan094_evaluation_result_conflict"
                )
            return self.verify_evaluation_result(checkpoint_id)
        return self._write_artifact(
            "evaluation-results",
            checkpoint_id,
            schema=EVALUATION_RESULT_SCHEMA,
            metadata={
                "checkpoint_content_sha256": checkpoint_content_sha256,
            },
            populate=lambda staging: write_exclusive(
                _created_payload(staging) / "evaluation.json",
                pretty_json_bytes(value),
            ),
        )

    def has_evaluation_result(self, checkpoint_id: str) -> bool:
        self._recover_evaluation_staging()
        parent = self.root / "evaluation-results"
        if not parent.exists():
            return False
        safe_directory(parent)
        path = parent / checkpoint_id
        if not path.exists() and not path.is_symlink():
            return False
        self.verify_evaluation_result(checkpoint_id)
        return True

    def read_evaluation_result(self, checkpoint_id: str) -> dict[str, Any]:
        self.verify_evaluation_result(checkpoint_id)
        value = read_json(
            self.root
            / "evaluation-results"
            / checkpoint_id
            / "payload"
            / "evaluation.json"
        )
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != EVALUATION_RESULT_SCHEMA
        ):
            raise FullModelTrainingError("plan094_evaluation_result_invalid")
        return json.loads(json.dumps(value))

    def verify_evaluation_result(self, checkpoint_id: str) -> dict[str, Any]:
        self._recover_evaluation_staging()
        artifact = self._verify_artifact(
            "evaluation-results",
            checkpoint_id,
            EVALUATION_RESULT_SCHEMA,
        )
        digest = artifact["metadata"].get("checkpoint_content_sha256")
        if not _sha256(digest):
            raise FullModelTrainingError("plan094_evaluation_result_invalid")
        path = safe_directory(
            self.root / "evaluation-results" / checkpoint_id
        ) / "payload" / "evaluation.json"
        value = read_json(path)
        if (
            not isinstance(value, Mapping)
            or value.get("schema") != EVALUATION_RESULT_SCHEMA
            or value.get("checkpoint", {}).get("checkpoint_id") != checkpoint_id
            or value.get("checkpoint", {}).get("content_sha256") != digest
        ):
            raise FullModelTrainingError("plan094_evaluation_result_invalid")
        return artifact

    def evaluation_result_ids(self) -> tuple[str, ...]:
        self._recover_evaluation_staging()
        identifiers = sorted(self._artifact_ids("evaluation-results"))
        for checkpoint_id in identifiers:
            self.verify_evaluation_result(checkpoint_id)
        return tuple(identifiers)

    def recover_incomplete_staging(self) -> list[str]:
        removed = super().recover_incomplete_staging()
        removed.extend(self._recover_evaluation_staging())
        return removed

    def _recover_evaluation_staging(self) -> list[str]:
        parent = self.root / "evaluation-results"
        if not parent.exists():
            return []
        safe_directory(parent)
        removed: list[str] = []
        for path in sorted(parent.iterdir()):
            if not path.name.startswith("."):
                continue
            if _STAGING_NAME.fullmatch(path.name) is None:
                raise FullModelTrainingError(
                    "plan094_unknown_hidden_evaluation_artifact"
                )
            safe_directory(path)
            _remove_owned_tree(path)
            removed.append(f"evaluation-results/{path.name}")
        return removed


def _created_payload(staging: Path) -> Path:
    payload = staging / "payload"
    payload.mkdir(mode=0o700)
    return payload


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "EVALUATION_RESULT_SCHEMA",
    "Plan094ArtifactStore",
]
