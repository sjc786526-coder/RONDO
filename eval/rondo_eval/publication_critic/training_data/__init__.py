"""Plan 059 Publication Critic training-data contracts and consumers."""

from .consumer import (
    DatasetConsumer,
    build_memberships,
    build_train_only_smoke_bundle,
    validate_train_only_smoke_bundle,
)
from .contract import (
    HARD_DIMENSIONS,
    SPLITS,
    TrainingDataError,
    validate_candidate_review,
    validate_dataset,
    validate_generation_batch,
    validate_packet_row,
    validate_pair_review,
    validate_pair_row,
    validate_scenario_row,
    validate_supervision_row,
)
from .dedup import (
    exact_packet_digest,
    find_near_duplicate_edges,
    find_reference_matches,
    reject_exact_duplicates,
    variable_text_similarity,
)
from .freeze import build_freeze_manifest, verify_freeze_manifest
from .grouping import (
    build_group_components,
    deterministic_grouped_stratified_split,
    coverage_failures,
    reject_perfect_shortcuts,
    shortcut_contingencies,
    validate_group_closure,
)
from .token_census import census_packets
from .shortcuts import (
    model_visible_text_shortcut_findings,
    reject_model_visible_text_shortcuts,
)

__all__ = [
    "DatasetConsumer",
    "HARD_DIMENSIONS",
    "SPLITS",
    "TrainingDataError",
    "build_freeze_manifest",
    "build_group_components",
    "build_memberships",
    "build_train_only_smoke_bundle",
    "census_packets",
    "coverage_failures",
    "deterministic_grouped_stratified_split",
    "exact_packet_digest",
    "find_near_duplicate_edges",
    "find_reference_matches",
    "model_visible_text_shortcut_findings",
    "reject_exact_duplicates",
    "reject_model_visible_text_shortcuts",
    "reject_perfect_shortcuts",
    "shortcut_contingencies",
    "validate_candidate_review",
    "validate_dataset",
    "validate_generation_batch",
    "validate_group_closure",
    "validate_packet_row",
    "validate_pair_review",
    "validate_pair_row",
    "validate_scenario_row",
    "validate_supervision_row",
    "validate_train_only_smoke_bundle",
    "variable_text_similarity",
    "verify_freeze_manifest",
]
