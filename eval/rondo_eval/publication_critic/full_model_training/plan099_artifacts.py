"""Checkpoint-backed, write-once Plan 099 evaluation artifacts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .contract import (
    FullModelTrainingError,
    pretty_json_bytes,
    read_json,
    write_exclusive,
)
from .plan094_artifacts import Plan094ArtifactStore, _created_payload, _sha256


EVALUATION_RESULT_SCHEMA = "rondo-publication-critic-plan099-checkpoint-evaluation-v1"
RUN_RESULT_SCHEMA = "rondo-publication-critic-plan099-run-result-v1"


class Plan099ArtifactStore(Plan094ArtifactStore):
    observation_schemas = frozenset({RUN_RESULT_SCHEMA})

    def publish_evaluation_result(
        self,
        checkpoint_id: str,
        *,
        checkpoint_content_sha256: str,
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._recover_evaluation_staging()
        destination = self.root / "evaluation-results" / checkpoint_id
        if destination.exists() or destination.is_symlink():
            existing = self.read_evaluation_result(checkpoint_id)
            if existing != value:
                raise FullModelTrainingError("plan099_evaluation_result_conflict")
            return self.verify_evaluation_result(checkpoint_id)
        return self._write_artifact(
            "evaluation-results",
            checkpoint_id,
            schema=EVALUATION_RESULT_SCHEMA,
            metadata={"checkpoint_content_sha256": checkpoint_content_sha256},
            populate=lambda staging: write_exclusive(
                _created_payload(staging) / "evaluation.json",
                pretty_json_bytes(value),
            ),
        )

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
            raise FullModelTrainingError("plan099_evaluation_result_invalid")
        return json.loads(json.dumps(value))

    def verify_evaluation_result(self, checkpoint_id: str) -> dict[str, Any]:
        self._recover_evaluation_staging()
        artifact = self._verify_artifact(
            "evaluation-results", checkpoint_id, EVALUATION_RESULT_SCHEMA
        )
        digest = artifact["metadata"].get("checkpoint_content_sha256")
        if not _sha256(digest):
            raise FullModelTrainingError("plan099_evaluation_result_invalid")
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
            or value.get("checkpoint", {}).get("checkpoint_id") != checkpoint_id
            or value.get("checkpoint", {}).get("content_sha256") != digest
        ):
            raise FullModelTrainingError("plan099_evaluation_result_invalid")
        return artifact


__all__ = ["EVALUATION_RESULT_SCHEMA", "RUN_RESULT_SCHEMA", "Plan099ArtifactStore"]
