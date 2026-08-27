"""Plan 090 artifact-store profile adding train diagnostic observations."""

from __future__ import annotations

from .plan081_artifacts import Plan081ArtifactStore
from .plan081_observation import OBSERVATION_SCHEMA, TRAINING_OBSERVATION_SCHEMA


class Plan090ArtifactStore(Plan081ArtifactStore):
    """Reuse Plan 081 lifecycle mechanics with one additional small schema."""

    observation_schemas = frozenset({OBSERVATION_SCHEMA, TRAINING_OBSERVATION_SCHEMA})


__all__ = ["Plan090ArtifactStore"]
