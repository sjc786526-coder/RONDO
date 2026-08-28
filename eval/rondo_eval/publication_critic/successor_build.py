"""Contract-native module validation and transactional successor release freeze."""

from __future__ import annotations

import copy
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Mapping, Sequence

from .identity import canonical_json_bytes, sha256_file
from .successor_data import (
    CANDIDATE_SCHEMA,
    MANIFEST_SCHEMA,
    PAIR_SCHEMA,
    SuccessorDataError,
    SuccessorRelease,
    validate_candidate_row,
    validate_split,
)
from .successor_task import (
    HARD_DIMENSIONS,
    TASK_NAME,
    TASK_VERSION,
    derive_verdict,
    task_content_sha256,
)
from .training_data.contract import TrainingDataError
from .training_data.dedup import find_near_duplicate_edges, reject_exact_duplicates


REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_ROOT = Path("eval/templates/publication-critic")
DESIGN_PATH = TEMPLATE_ROOT / "successor-data-design-v1.json"
CONFIG_PATH = TEMPLATE_ROOT / "successor-generation-config-v1.json"
MODULE_CONTRACT_PATH = TEMPLATE_ROOT / "successor-module-contract-v1.json"
DATASET_REVISION = "publication-critic-v9"
ACCEPTED_TASK_SHA256 = "3eb0539b16403ebe20e74ce1b1ea5114d2383c6118f61fef56c9c91426e6a560"
ACCEPTED_IMPLEMENTATION_COMMIT = "55342bdb11b09c11b589fd398717f7712fca012c"
ACCEPTED_IMPLEMENTATION_ALGORITHM = "sha256-canonical-component-list-v1"
ACCEPTED_IMPLEMENTATION_COMPONENT_PATHS = (
    "doc/rondo-multi-publication-critic-task-contract-v2.md",
    "doc/rondo-multi-publication-critic-product-contract.md",
    "eval/rondo_eval/publication_critic/contract.py",
    "eval/rondo_eval/publication_critic/render.py",
    "eval/rondo_eval/publication_critic/successor_task.py",
    "eval/rondo_eval/publication_critic/successor_data.py",
    "eval/templates/publication-critic/product-packet-limits-v1.json",
    "eval/templates/publication-critic/task-contract-v2.json",
    "eval/templates/publication-critic/input-contract-v3.md",
    "eval/templates/publication-critic/qualification-rubric-v2.md",
    "eval/templates/publication-critic/render-contract-v4.json",
    "eval/templates/publication-critic/successor-output-schema-v1.json",
    "eval/templates/publication-critic/successor-release-contract-v1.json",
)
ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256 = (
    "b0124de561f52fb464c223989d003af1e9f2a8a24eccd9ca349a4d769e3488d5"
)
ACCEPTED_TASK = {
    "name": TASK_NAME,
    "version": TASK_VERSION,
    "authority_path": "doc/rondo-multi-publication-critic-task-contract-v2.md",
    "content_sha256": ACCEPTED_TASK_SHA256,
    "accepted_implementation_commit": ACCEPTED_IMPLEMENTATION_COMMIT,
}
SPLITS = ("train", "validation", "test")
REVIEW_CHECKS = (
    "contract_alignment",
    "complete_absolute_labels",
    "visible_basis_sufficient",
    "boundary_closure",
    "soft_only_invariance",
    "split_grouping",
    "language_quality",
    "no_hidden_metadata",
)
COMBINATION_TAGS = {
    "hard_pass_soft_good",
    "hard_pass_soft_bad",
    "hard_fail_soft_good",
    "hard_fail_soft_bad",
}
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_MODEL_VISIBLE_FORBIDDEN = tuple(
    value.casefold()
    for value in (
        *HARD_DIMENSIONS,
        "completion_state",
        "public_state",
        "candidate_brief",
        "pair_direction",
        "model_visible_complete_claim",
        "model_visible_unfinished_or_not_closed",
    )
)


class SuccessorBuildError(ValueError):
    """A design, module, review, or formal release violates Plan 098."""


@dataclass(frozen=True)
class ValidatedModule:
    module_id: str
    owner_role: str
    source_sha256: str
    candidates: tuple[dict[str, Any], ...]
    pairs: tuple[dict[str, Any], ...]
    candidate_tags: Mapping[str, tuple[str, ...]]
    group_splits: Mapping[str, str]


@dataclass(frozen=True)
class BuildContracts:
    design: Mapping[str, Any]
    config: Mapping[str, Any]
    design_sha256: str
    config_sha256: str


def load_build_contracts(repo_root: Path | str = REPO_ROOT) -> BuildContracts:
    root = Path(repo_root)
    design_path = root / DESIGN_PATH
    config_path = root / CONFIG_PATH
    design = _load_json(design_path, "successor data design")
    config = _load_json(config_path, "successor generation config")
    module_contract = _load_json(
        root / MODULE_CONTRACT_PATH,
        "successor module contract",
    )
    design_sha256 = sha256_file(design_path)
    config_sha256 = sha256_file(config_path)
    _validate_design(design, root)
    _validate_module_contract(module_contract)
    _validate_config(config, design, design_sha256, root)
    return BuildContracts(
        design=design,
        config=config,
        design_sha256=design_sha256,
        config_sha256=config_sha256,
    )


def validate_module_file(
    path: Path | str,
    *,
    contracts: BuildContracts | None = None,
    repo_root: Path | str = REPO_ROOT,
) -> ValidatedModule:
    source_path = Path(path)
    source = _load_json(source_path, "module source")
    active = contracts or load_build_contracts(repo_root)
    return _validate_module_source(
        source,
        source_sha256=sha256_file(source_path),
        design=active.design,
        repo_root=Path(repo_root),
    )


def validate_review_file(
    path: Path | str,
    module: ValidatedModule,
    *,
    contracts: BuildContracts | None = None,
    repo_root: Path | str = REPO_ROOT,
) -> Mapping[str, Any]:
    review = _load_json(Path(path), "module review")
    active = contracts or load_build_contracts(repo_root)
    return _validate_review(review, module, active.design)


def finalize_successor_release(
    workspace: Path | str,
    output: Path | str,
    *,
    repo_root: Path | str = REPO_ROOT,
    enforce_config_paths: bool = True,
) -> Mapping[str, Any]:
    """Validate reviewed modules and freeze one clean, physically split release."""

    root = Path(repo_root)
    active = load_build_contracts(root)
    work = Path(workspace)
    destination = Path(output)
    if enforce_config_paths:
        if work.resolve() != Path(active.config["ignored_namespace"]).resolve():
            raise SuccessorBuildError("formal workspace differs from the generation config")
        expected_output = root / active.config["formal_output"]
        if destination.resolve() != expected_output.resolve():
            raise SuccessorBuildError("formal output differs from the generation config")
    if not work.is_dir() or work.is_symlink():
        raise SuccessorBuildError("module workspace is missing or unsafe")
    if destination.exists() or destination.is_symlink():
        raise SuccessorBuildError("formal output already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{destination.name}.plan098-tmp"
    if temporary.exists() or temporary.is_symlink():
        raise SuccessorBuildError("transactional output path is not clean")

    modules: list[ValidatedModule] = []
    reviews: dict[str, Mapping[str, Any]] = {}
    for binding in active.config["modules"]:
        module_path = _safe_workspace_file(work, binding["source_file"])
        review_path = _safe_workspace_file(work, binding["review_file"])
        module = validate_module_file(
            module_path,
            contracts=active,
            repo_root=root,
        )
        if module.module_id != binding["module_id"]:
            raise SuccessorBuildError("module binding identity differs")
        review = validate_review_file(
            review_path,
            module,
            contracts=active,
            repo_root=root,
        )
        modules.append(module)
        reviews[module.module_id] = {
            **dict(review),
            "review_sha256": sha256_file(review_path),
        }

    candidates = tuple(
        row
        for module in modules
        for row in module.candidates
    )
    pairs = tuple(row for module in modules for row in module.pairs)
    candidate_tags = {
        candidate_id: tags
        for module in modules
        for candidate_id, tags in module.candidate_tags.items()
    }
    group_splits = {
        group_id: split
        for module in modules
        for group_id, split in module.group_splits.items()
    }
    coverage = _validate_formal_corpus(
        candidates,
        pairs,
        candidate_tags,
        group_splits,
        active.design,
        repo_root=root,
    )

    try:
        temporary.mkdir(parents=False)
        _copy_bytes(root / DESIGN_PATH, temporary / "design-lock.json")
        _copy_bytes(root / CONFIG_PATH, temporary / "generation-config.json")
        _write_json(temporary / "coverage.json", coverage)
        module_records = _write_module_records(
            temporary,
            modules,
            reviews,
        )
        split_bindings: dict[str, dict[str, Any]] = {}
        for split in SPLITS:
            split_candidates = sorted(
                (row for row in candidates if group_splits[row["group_id"]] == split),
                key=lambda row: row["candidate_id"],
            )
            split_pairs = sorted(
                (row for row in pairs if group_splits[row["group_id"]] == split),
                key=lambda row: row["pair_id"],
            )
            candidate_relative = f"splits/{split}/candidates.jsonl"
            pair_relative = f"splits/{split}/pairs.jsonl"
            candidate_path = temporary / candidate_relative
            pair_path = temporary / pair_relative
            _write_jsonl(candidate_path, split_candidates)
            _write_jsonl(pair_path, split_pairs)
            split_bindings[split] = {
                "candidates": _file_binding(candidate_path, candidate_relative),
                "pairs": _file_binding(pair_path, pair_relative),
            }
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "task_contract": {
                "name": TASK_NAME,
                "version": TASK_VERSION,
                "content_sha256": ACCEPTED_TASK_SHA256,
                "accepted_commit": ACCEPTED_IMPLEMENTATION_COMMIT,
            },
            "splits": split_bindings,
        }
        _write_json(temporary / "manifest.json", manifest)
        smoke_bundle = _train_only_smoke_bundle(candidates, pairs, group_splits)
        _write_json(temporary / "train-only-smoke-bundle.json", smoke_bundle)
        validate_split(
            "train",
            smoke_bundle["candidates"],
            smoke_bundle["pairs"],
            repo_root=root,
        )
        _write_text(temporary / "DATA_CARD.md", _data_card(coverage))
        release_identity = {
            "schema": "rondo-publication-critic-successor-release-identity@v1",
            "dataset_revision": DATASET_REVISION,
            "accepted_task": ACCEPTED_TASK,
            "accepted_implementation": copy.deepcopy(
                active.design["accepted_implementation"]
            ),
            "design_lock_sha256": active.design_sha256,
            "generation_config_sha256": active.config_sha256,
            "manifest_sha256": sha256_file(temporary / "manifest.json"),
            "coverage_sha256": sha256_file(temporary / "coverage.json"),
            "data_card_sha256": sha256_file(temporary / "DATA_CARD.md"),
            "train_only_smoke_sha256": sha256_file(
                temporary / "train-only-smoke-bundle.json"
            ),
            "module_records": module_records,
        }
        _write_json(temporary / "release-identity.json", release_identity)

        release = SuccessorRelease.open(
            temporary,
            expected_accepted_commit=ACCEPTED_IMPLEMENTATION_COMMIT,
            repo_root=root,
        )
        train = release.load_train()
        validation = release.load_validation()
        if hasattr(release, "load_test"):
            raise SuccessorBuildError("formal consumer unexpectedly exposes test")
        if len(train.candidates) != coverage["splits"]["train"]["candidates"]:
            raise SuccessorBuildError("train smoke candidate count differs")
        if len(validation.candidates) != coverage["splits"]["validation"]["candidates"]:
            raise SuccessorBuildError("validation smoke candidate count differs")
        if not train.model_inputs():
            raise SuccessorBuildError("train renderer smoke is empty")
        temporary.rename(destination)
    except Exception:
        if temporary.is_dir() and not temporary.is_symlink():
            shutil.rmtree(temporary)
        raise
    return coverage


def _validate_design(value: Mapping[str, Any], repo_root: Path) -> None:
    _exact_keys(
        value,
        {
            "schema",
            "dataset_revision",
            "accepted_task",
            "accepted_implementation",
            "source_policy",
            "module_contract",
            "allowed_candidate_tags",
            "split_contract",
            "coverage_minimums",
            "quality_checks",
            "stop_conditions",
            "formal_freeze",
        },
        "successor data design",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-successor-data-design@v1",
        "successor data design.schema",
    )
    _literal(value["dataset_revision"], DATASET_REVISION, "successor data revision")
    _validate_accepted_task(value["accepted_task"], repo_root)
    _validate_accepted_implementation(value["accepted_implementation"], repo_root)
    source_policy = _object(value["source_policy"], "source policy")
    _exact_keys(
        source_policy,
        {
            "mixed_v8_body_access",
            "safe_v8_projection",
            "formal_source_kinds",
            "real_shaped_anchors",
        },
        "source policy",
    )
    _literal(source_policy["mixed_v8_body_access"], "forbidden", "mixed v8 access")
    safe = _object(source_policy["safe_v8_projection"], "safe v8 projection")
    _exact_keys(
        safe,
        {"path", "sha256", "candidate_count", "direct_reuse_count", "decision"},
        "safe v8 projection",
    )
    safe_path = repo_root / str(safe["path"])
    if sha256_file(safe_path) != safe["sha256"]:
        raise SuccessorBuildError("safe v8 projection identity drifted")
    _literal(safe["direct_reuse_count"], 0, "safe v8 direct reuse count")
    _literal(safe["candidate_count"], 6, "safe v8 candidate count")
    if source_policy["formal_source_kinds"] != ["new_synthetic"]:
        raise SuccessorBuildError("formal source kinds differ")
    module_contract = _object(value["module_contract"], "module contract")
    _literal(
        module_contract["schema"],
        "rondo-publication-critic-successor-module-source@v1",
        "module contract.schema",
    )
    _literal(module_contract["candidate_count_per_group"], 3, "candidate group size")
    _literal(module_contract["groups_per_module"], 24, "module group count")
    _exact_keys(
        _object(module_contract["group_splits_per_module"], "module split counts"),
        set(SPLITS),
        "module split counts",
    )
    _literal(
        module_contract["group_splits_per_module"],
        {"train": 18, "validation": 3, "test": 3},
        "module split counts",
    )
    modules = module_contract["modules"]
    if not isinstance(modules, list) or len(modules) != 3:
        raise SuccessorBuildError("successor design must define three modules")
    module_ids: set[str] = set()
    for module in modules:
        spec = _object(module, "module specification")
        _exact_keys(
            spec,
            {
                "module_id",
                "owner_role",
                "reviewer_role",
                "pairs_per_group",
                "boundary_targets_by_split",
                "brief",
            },
            "module specification",
        )
        module_id = _identifier(spec["module_id"], "module_id")
        if module_id in module_ids:
            raise SuccessorBuildError("duplicate module_id")
        module_ids.add(module_id)
        for split in SPLITS:
            targets = spec["boundary_targets_by_split"][split]
            expected = module_contract["group_splits_per_module"][split]
            if not isinstance(targets, list) or len(targets) != expected:
                raise SuccessorBuildError(f"{module_id} boundary schedule differs")
            if any(target not in HARD_DIMENSIONS for target in targets):
                raise SuccessorBuildError(f"{module_id} boundary target is invalid")
    tags = value["allowed_candidate_tags"]
    if not isinstance(tags, list) or len(tags) != len(set(tags)):
        raise SuccessorBuildError("allowed candidate tags are invalid")
    if set(tags) != COMBINATION_TAGS | {
        "single_hard_failure",
        "multi_hard_failure",
        "real_shaped_anchor",
        "visible_conflict",
    }:
        raise SuccessorBuildError("allowed candidate tags differ")


def _validate_module_contract(value: Mapping[str, Any]) -> None:
    _exact_keys(
        value,
        {"kind", "name", "version", "runtime_validator", "module_source", "blind_review"},
        "successor module contract",
    )
    _literal(value["kind"], "rondo-contract-projection", "module contract.kind")
    _literal(
        value["name"],
        "rondo-publication-critic-successor-module",
        "module contract.name",
    )
    _literal(value["version"], "v1", "module contract.version")
    _literal(
        value["runtime_validator"],
        "eval/rondo_eval/publication_critic/successor_build.py",
        "module contract.runtime_validator",
    )
    source = _object(value["module_source"], "module contract source")
    _exact_keys(
        source,
        {
            "schema",
            "required",
            "group_required",
            "context_required",
            "candidate_required",
            "continuity_basis_required",
            "pair_required",
        },
        "module contract source",
    )
    _literal(
        source["schema"],
        "rondo-publication-critic-successor-module-source@v1",
        "module contract source.schema",
    )
    review = _object(value["blind_review"], "module contract review")
    _exact_keys(
        review,
        {"schema", "required", "checklist"},
        "module contract review",
    )
    _literal(
        review["schema"],
        "rondo-publication-critic-successor-module-review@v1",
        "module contract review.schema",
    )
    _literal(review["checklist"], list(REVIEW_CHECKS), "module review checklist")


def _validate_config(
    value: Mapping[str, Any],
    design: Mapping[str, Any],
    design_sha256: str,
    repo_root: Path,
) -> None:
    _exact_keys(
        value,
        {
            "schema",
            "dataset_revision",
            "accepted_task",
            "accepted_implementation",
            "design_lock",
            "module_contract",
            "ignored_namespace",
            "modules",
            "serialization",
            "formal_output",
            "runtime",
        },
        "successor generation config",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-successor-generation-config@v1",
        "generation config.schema",
    )
    _literal(value["dataset_revision"], DATASET_REVISION, "generation revision")
    _literal(value["accepted_task"], ACCEPTED_TASK, "generation accepted task")
    _literal(
        value["accepted_implementation"],
        {
            "commit": design["accepted_implementation"]["commit"],
            "bundle_sha256": design["accepted_implementation"]["bundle_sha256"],
        },
        "generation accepted implementation",
    )
    design_binding = _object(value["design_lock"], "generation design binding")
    _exact_keys(design_binding, {"path", "sha256"}, "generation design binding")
    _literal(design_binding["path"], DESIGN_PATH.as_posix(), "generation design path")
    _literal(design_binding["sha256"], design_sha256, "generation design hash")
    module_binding = _object(value["module_contract"], "generation module contract")
    _exact_keys(module_binding, {"path", "sha256"}, "generation module contract")
    _literal(
        module_binding["path"],
        MODULE_CONTRACT_PATH.as_posix(),
        "generation module contract path",
    )
    _literal(
        module_binding["sha256"],
        sha256_file(repo_root / MODULE_CONTRACT_PATH),
        "generation module contract hash",
    )
    _literal(
        value["ignored_namespace"],
        "/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098",
        "ignored namespace",
    )
    if not isinstance(value["modules"], list) or len(value["modules"]) != 3:
        raise SuccessorBuildError("generation module bindings differ")
    expected_modules = [item["module_id"] for item in design["module_contract"]["modules"]]
    observed_modules = [item["module_id"] for item in value["modules"]]
    if observed_modules != expected_modules:
        raise SuccessorBuildError("generation module order differs from design")
    for binding in value["modules"]:
        _exact_keys(
            _object(binding, "generation module binding"),
            {"module_id", "source_file", "review_file"},
            "generation module binding",
        )
        _safe_relative(binding["source_file"], "generation source path")
        _safe_relative(binding["review_file"], "generation review path")
    _literal(
        value["serialization"],
        {
            "json": "utf8 sorted keys compact with trailing newline",
            "jsonl": "one canonical JSON object per line with trailing newline",
            "candidate_order": "split then module_id group_id candidate_id",
            "pair_order": "split then module_id group_id pair_id",
        },
        "generation serialization",
    )
    _literal(value["formal_output"], "training/publication-critic-v9", "formal output")
    _literal(
        value["runtime"],
        "eval/rondo_eval/publication_critic/successor_build.py",
        "generation runtime",
    )


def _validate_module_source(
    value: Mapping[str, Any],
    *,
    source_sha256: str,
    design: Mapping[str, Any],
    repo_root: Path,
) -> ValidatedModule:
    _exact_keys(
        value,
        {"schema", "module_id", "owner_role", "accepted_task", "groups"},
        "module source",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-successor-module-source@v1",
        "module source.schema",
    )
    _literal(value["accepted_task"], ACCEPTED_TASK, "module accepted task")
    module_id = _identifier(value["module_id"], "module_id")
    spec = _module_spec(design, module_id)
    _literal(value["owner_role"], spec["owner_role"], "module owner role")
    groups = value["groups"]
    expected_groups = design["module_contract"]["groups_per_module"]
    if not isinstance(groups, list) or len(groups) != expected_groups:
        raise SuccessorBuildError(f"{module_id} group count differs")

    allowed_tags = set(design["allowed_candidate_tags"])
    candidates: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    candidate_tags: dict[str, tuple[str, ...]] = {}
    group_splits: dict[str, str] = {}
    split_groups: Counter[str] = Counter()
    split_sequence: list[str] = []
    boundary_targets: dict[str, list[str]] = {split: [] for split in SPLITS}
    candidate_ids: set[str] = set()
    pair_ids: set[str] = set()
    for group_value in groups:
        group = _object(group_value, f"{module_id} group")
        _exact_keys(
            group,
            {"group_id", "split", "source", "context", "candidates", "pairs"},
            f"{module_id} group",
        )
        group_id = _identifier(group["group_id"], f"{module_id} group_id")
        if not group_id.startswith(f"pcv9-{module_id}-"):
            raise SuccessorBuildError(f"{module_id} group_id lacks its module prefix")
        if group_id in group_splits:
            raise SuccessorBuildError(f"duplicate group_id: {group_id}")
        split = group["split"]
        if split not in SPLITS:
            raise SuccessorBuildError(f"{group_id} split is invalid")
        group_splits[group_id] = split
        split_groups[split] += 1
        split_sequence.append(split)
        source = _object(group["source"], f"{group_id} source")
        _exact_keys(source, {"kind", "reference"}, f"{group_id} source")
        _literal(source["kind"], "new_synthetic", f"{group_id} source.kind")
        _literal(source["reference"], None, f"{group_id} source.reference")
        context = _validate_context(group["context"], group_id)
        source_candidates = group["candidates"]
        if not isinstance(source_candidates, list) or len(source_candidates) != 3:
            raise SuccessorBuildError(f"{group_id} must contain exactly three candidates")
        candidate_by_key: dict[str, dict[str, Any]] = {}
        group_tags: dict[str, tuple[str, ...]] = {}
        for source_candidate in source_candidates:
            authored = _object(source_candidate, f"{group_id} candidate")
            _exact_keys(
                authored,
                {"key", "summary", "handoff", "labels", "continuity_basis", "tags"},
                f"{group_id} candidate",
            )
            key = _identifier(authored["key"], f"{group_id} candidate key")
            if key in candidate_by_key:
                raise SuccessorBuildError(f"{group_id} repeats candidate key {key}")
            candidate_id = f"{group_id}-{key}"
            if candidate_id in candidate_ids:
                raise SuccessorBuildError(f"duplicate candidate_id: {candidate_id}")
            candidate_ids.add(candidate_id)
            packet = {
                "qualification": {
                    "packet_schema": {
                        "name": "rondo-publication-packet",
                        "revision": "v1",
                    },
                    "rubric": {
                        "name": "rondo-publication-qualification",
                        "revision": "v2",
                    },
                },
                **copy.deepcopy(context),
                "candidate": {
                    "summary": authored["summary"],
                    "handoff": authored["handoff"],
                },
            }
            labels = _object(authored["labels"], f"{candidate_id} labels")
            basis_source = _object(
                authored["continuity_basis"],
                f"{candidate_id} continuity_basis",
            )
            _exact_keys(
                basis_source,
                {"field", "quote"},
                f"{candidate_id} continuity_basis",
            )
            basis = {
                "type": (
                    "model_visible_complete_claim"
                    if labels.get("conditional_continuity") == "N/A"
                    else "model_visible_unfinished_or_not_closed"
                ),
                "field": basis_source["field"],
                "quote": basis_source["quote"],
            }
            row = {
                "schema": CANDIDATE_SCHEMA,
                "candidate_id": candidate_id,
                "group_id": group_id,
                "packet": packet,
                "labels": dict(labels),
                "continuity_label_basis": basis,
            }
            try:
                validate_candidate_row(row, repo_root=repo_root)
            except SuccessorDataError as exc:
                raise SuccessorBuildError(f"{candidate_id}: {exc}") from exc
            tags = authored["tags"]
            if (
                not isinstance(tags, list)
                or not tags
                or len(tags) != len(set(tags))
                or not set(tags) <= allowed_tags
            ):
                raise SuccessorBuildError(f"{candidate_id} tags are invalid")
            _validate_candidate_tags(row["labels"], set(tags), candidate_id)
            candidate_by_key[key] = row
            group_tags[key] = tuple(tags)

        source_pairs = group["pairs"]
        expected_pairs = spec["pairs_per_group"]
        if not isinstance(source_pairs, list) or len(source_pairs) != sum(
            expected_pairs.values()
        ):
            raise SuccessorBuildError(f"{group_id} pair count differs")
        pair_kind_counts: Counter[str] = Counter()
        group_pairs: list[dict[str, Any]] = []
        for source_pair in source_pairs:
            authored_pair = _object(source_pair, f"{group_id} pair")
            _exact_keys(
                authored_pair,
                {
                    "key",
                    "kind",
                    "left_key",
                    "right_key",
                    "target_dimension",
                    "soft_change",
                },
                f"{group_id} pair",
            )
            key = _identifier(authored_pair["key"], f"{group_id} pair key")
            pair_id = f"{group_id}-{key}"
            if pair_id in pair_ids:
                raise SuccessorBuildError(f"duplicate pair_id: {pair_id}")
            pair_ids.add(pair_id)
            left_key = authored_pair["left_key"]
            right_key = authored_pair["right_key"]
            if left_key not in candidate_by_key or right_key not in candidate_by_key:
                raise SuccessorBuildError(f"{pair_id} references a missing local candidate")
            pair = {
                "schema": PAIR_SCHEMA,
                "pair_id": pair_id,
                "group_id": group_id,
                "kind": authored_pair["kind"],
                "left_candidate_id": candidate_by_key[left_key]["candidate_id"],
                "right_candidate_id": candidate_by_key[right_key]["candidate_id"],
                "target_dimension": authored_pair["target_dimension"],
                "soft_change": authored_pair["soft_change"],
            }
            pair_kind_counts[pair["kind"]] += 1
            if pair["kind"] == "boundary":
                boundary_targets[split].append(pair["target_dimension"])
            group_pairs.append(pair)
        if dict(pair_kind_counts) != {
            kind: count for kind, count in expected_pairs.items() if count
        }:
            raise SuccessorBuildError(f"{group_id} pair kinds differ")
        try:
            validate_split(
                split,
                list(candidate_by_key.values()),
                group_pairs,
                repo_root=repo_root,
            )
        except SuccessorDataError as exc:
            raise SuccessorBuildError(f"{group_id}: {exc}") from exc
        candidates.extend(candidate_by_key.values())
        pairs.extend(group_pairs)
        for key, row in candidate_by_key.items():
            candidate_tags[row["candidate_id"]] = group_tags[key]

    expected_split_groups = design["module_contract"]["group_splits_per_module"]
    if dict(split_groups) != expected_split_groups:
        raise SuccessorBuildError(f"{module_id} split group counts differ")
    expected_split_sequence = [
        split
        for split in SPLITS
        for _ in range(expected_split_groups[split])
    ]
    if split_sequence != expected_split_sequence:
        raise SuccessorBuildError(f"{module_id} group split order differs")
    for split in SPLITS:
        if boundary_targets[split] != spec["boundary_targets_by_split"][split]:
            raise SuccessorBuildError(f"{module_id} {split} boundary schedule differs")
    return ValidatedModule(
        module_id=module_id,
        owner_role=value["owner_role"],
        source_sha256=source_sha256,
        candidates=tuple(candidates),
        pairs=tuple(pairs),
        candidate_tags=candidate_tags,
        group_splits=group_splits,
    )


def _validate_context(value: Any, group_id: str) -> dict[str, Any]:
    context = _object(value, f"{group_id} context")
    _exact_keys(
        context,
        {"actor_role", "target_kind", "local_scope", "continuity", "evidence_v1"},
        f"{group_id} context",
    )
    return copy.deepcopy(dict(context))


def _validate_candidate_tags(
    labels: Mapping[str, Any],
    tags: set[str],
    candidate_id: str,
) -> None:
    combination = tags & COMBINATION_TAGS
    if len(combination) != 1:
        raise SuccessorBuildError(f"{candidate_id} needs one hard/soft combination tag")
    verdict = derive_verdict(labels)
    combination_tag = next(iter(combination))
    if (combination_tag.startswith("hard_pass_")) != (verdict == "PASS"):
        raise SuccessorBuildError(f"{candidate_id} hard/soft tag disagrees with gate")
    failures = sum(label == "FAIL" for label in labels.values())
    if verdict == "PASS":
        if tags & {"single_hard_failure", "multi_hard_failure"}:
            raise SuccessorBuildError(f"{candidate_id} PASS has a failure-count tag")
    elif failures == 1:
        if "single_hard_failure" not in tags or "multi_hard_failure" in tags:
            raise SuccessorBuildError(f"{candidate_id} single failure tag differs")
    elif failures >= 2:
        if "multi_hard_failure" not in tags or "single_hard_failure" in tags:
            raise SuccessorBuildError(f"{candidate_id} multi failure tag differs")
    if "visible_conflict" in tags and (
        labels["internal_consistency"] != "FAIL"
        or labels["conditional_continuity"] == "N/A"
    ):
        raise SuccessorBuildError(f"{candidate_id} visible conflict labels differ")


def _validate_review(
    value: Mapping[str, Any],
    module: ValidatedModule,
    design: Mapping[str, Any],
) -> Mapping[str, Any]:
    _exact_keys(
        value,
        {
            "schema",
            "module_id",
            "reviewer_role",
            "accepted_task",
            "module_sha256",
            "verdict",
            "findings",
            "checklist",
        },
        "module review",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-successor-module-review@v1",
        "module review.schema",
    )
    _literal(value["module_id"], module.module_id, "review module_id")
    _literal(value["accepted_task"], ACCEPTED_TASK, "review accepted task")
    spec = _module_spec(design, module.module_id)
    _literal(value["reviewer_role"], spec["reviewer_role"], "reviewer role")
    _literal(value["module_sha256"], module.source_sha256, "review module hash")
    checklist = _object(value["checklist"], "review checklist")
    _exact_keys(checklist, set(REVIEW_CHECKS), "review checklist")
    if any(checklist[item] is not True for item in REVIEW_CHECKS):
        raise SuccessorBuildError(f"{module.module_id} review checklist is incomplete")
    findings = value["findings"]
    if not isinstance(findings, list) or any(
        not isinstance(item, str) or not item.strip() for item in findings
    ):
        raise SuccessorBuildError(f"{module.module_id} review findings are invalid")
    if value["verdict"] != "accept" or findings:
        raise SuccessorBuildError(f"{module.module_id} blind review is not accepted")
    return value


def _validate_formal_corpus(
    candidates: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    candidate_tags: Mapping[str, Sequence[str]],
    group_splits: Mapping[str, str],
    design: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    candidate_ids = [row["candidate_id"] for row in candidates]
    pair_ids = [row["pair_id"] for row in pairs]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise SuccessorBuildError("formal corpus repeats candidate_id")
    if len(pair_ids) != len(set(pair_ids)):
        raise SuccessorBuildError("formal corpus repeats pair_id")
    if set(candidate_tags) != set(candidate_ids):
        raise SuccessorBuildError("formal candidate tags do not close")
    for split in SPLITS:
        split_candidates = [
            row for row in candidates if group_splits.get(row["group_id"]) == split
        ]
        split_pairs = [row for row in pairs if group_splits.get(row["group_id"]) == split]
        try:
            validate_split(split, split_candidates, split_pairs, repo_root=repo_root)
        except SuccessorDataError as exc:
            raise SuccessorBuildError(f"formal {split}: {exc}") from exc
    try:
        reject_exact_duplicates(candidates)
        near_edges = find_near_duplicate_edges(
            candidates,
            threshold=design["quality_checks"]["cross_group_near_duplicate_threshold"],
        )
    except TrainingDataError as exc:
        raise SuccessorBuildError(str(exc)) from exc
    candidate_groups = {row["candidate_id"]: row["group_id"] for row in candidates}
    cross_group_edges = [
        edge
        for edge in near_edges
        if candidate_groups[edge.left_candidate_id]
        != candidate_groups[edge.right_candidate_id]
    ]
    if cross_group_edges:
        raise SuccessorBuildError("formal corpus has cross-group near duplicates")
    for row in candidates:
        rendered = json.dumps(row["packet"], ensure_ascii=False).casefold()
        if any(token in rendered for token in _MODEL_VISIBLE_FORBIDDEN):
            raise SuccessorBuildError(
                f"{row['candidate_id']} exposes a label or generation shortcut token"
            )

    minimums = design["coverage_minimums"]
    verdicts = Counter(derive_verdict(row["labels"]) for row in candidates)
    dimension_fail = {
        dimension: sum(row["labels"][dimension] == "FAIL" for row in candidates)
        for dimension in HARD_DIMENSIONS
    }
    continuity_labels = Counter(
        row["labels"]["conditional_continuity"] for row in candidates
    )
    tag_counts = Counter(tag for tags in candidate_tags.values() for tag in tags)
    context_counts = Counter(_context_bucket(row["packet"]) for row in candidates)
    boundary_pairs = [row for row in pairs if row["kind"] == "boundary"]
    boundary_counts = Counter(row["target_dimension"] for row in boundary_pairs)
    boundary_by_split = {
        split: Counter(
            row["target_dimension"]
            for row in boundary_pairs
            if group_splits[row["group_id"]] == split
        )
        for split in SPLITS
    }
    invariance_by_split = {
        split: sum(
            row["kind"] == "soft_only_invariance"
            and group_splits[row["group_id"]] == split
            for row in pairs
        )
        for split in SPLITS
    }
    split_stats: dict[str, dict[str, Any]] = {}
    for split in SPLITS:
        rows = [row for row in candidates if group_splits[row["group_id"]] == split]
        split_verdicts = Counter(derive_verdict(row["labels"]) for row in rows)
        lengths: dict[str, list[int]] = {"PASS": [], "REWRITE": []}
        for row in rows:
            lengths[derive_verdict(row["labels"])].append(_candidate_length(row["packet"]))
        if not lengths["PASS"] or not lengths["REWRITE"]:
            raise SuccessorBuildError(f"{split} lacks both verdict length populations")
        overlap_low = max(min(lengths["PASS"]), min(lengths["REWRITE"]))
        overlap_high = min(max(lengths["PASS"]), max(lengths["REWRITE"]))
        if overlap_low > overlap_high:
            raise SuccessorBuildError(f"{split} verdict length ranges do not overlap")
        split_stats[split] = {
            "candidates": len(rows),
            "pairs": sum(group_splits[row["group_id"]] == split for row in pairs),
            "verdicts": dict(sorted(split_verdicts.items())),
            "candidate_length_range": {
                verdict: [min(values), max(values)]
                for verdict, values in lengths.items()
            },
        }

    _minimum(len(candidates), minimums["total_candidates"], "total_candidates")
    _minimum(len(pairs), minimums["total_pairs"], "total_pairs")
    _minimum_mapping(verdicts, minimums["verdicts"], "verdicts")
    _minimum_mapping(dimension_fail, minimums["dimension_fail"], "dimension_fail")
    _minimum_mapping(
        continuity_labels,
        minimums["continuity_labels"],
        "continuity_labels",
    )
    _minimum_mapping(boundary_counts, minimums["boundary_pairs_per_dimension"], "boundary")
    _minimum_mapping(context_counts, minimums["context_candidates"], "context")
    _minimum_mapping(tag_counts, minimums["candidate_tags"], "candidate_tags")
    for split in SPLITS:
        _literal(
            split_stats[split]["candidates"],
            design["split_contract"]["candidate_counts"][split],
            f"{split} candidate count",
        )
        _minimum_mapping(
            split_stats[split]["verdicts"],
            minimums["split_verdicts"][split],
            f"{split} verdicts",
        )
        _minimum(
            invariance_by_split[split],
            minimums["invariance_pairs_per_split"][split],
            f"{split} invariance pairs",
        )
        for dimension in HARD_DIMENSIONS:
            _minimum(
                boundary_by_split[split][dimension],
                minimums["boundary_pairs_per_dimension_per_split"],
                f"{split} boundary {dimension}",
            )
    return {
        "schema": "rondo-publication-critic-successor-coverage@v1",
        "dataset_revision": DATASET_REVISION,
        "accepted_task": ACCEPTED_TASK,
        "total_candidates": len(candidates),
        "total_pairs": len(pairs),
        "splits": split_stats,
        "verdicts": dict(sorted(verdicts.items())),
        "dimension_fail": dimension_fail,
        "continuity_labels": dict(sorted(continuity_labels.items())),
        "boundary_pairs_per_dimension": dict(sorted(boundary_counts.items())),
        "invariance_pairs_per_split": invariance_by_split,
        "context_candidates": dict(sorted(context_counts.items())),
        "candidate_tags": dict(sorted(tag_counts.items())),
        "duplicate_check": {
            "exact_duplicates": 0,
            "cross_group_near_duplicates": 0,
            "within_group_near_duplicate_edges": len(near_edges),
            "threshold": design["quality_checks"]["cross_group_near_duplicate_threshold"],
        },
        "shortcut_check": {
            "model_visible_metadata_tokens": 0,
            "verdict_length_ranges_overlap_in_every_split": True,
        },
    }


def _write_module_records(
    root: Path,
    modules: Sequence[ValidatedModule],
    reviews: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for module in modules:
        review = reviews[module.module_id]
        record = {
            "schema": "rondo-publication-critic-successor-module-freeze@v1",
            "module_id": module.module_id,
            "owner_role": module.owner_role,
            "source_sha256": module.source_sha256,
            "reviewer_role": review["reviewer_role"],
            "review_sha256": review["review_sha256"],
            "review_verdict": review["verdict"],
            "finding_count": len(review["findings"]),
            "groups": len(module.group_splits),
            "candidates": len(module.candidates),
            "pairs": len(module.pairs),
            "split_groups": dict(sorted(Counter(module.group_splits.values()).items())),
        }
        relative = f"modules/{module.module_id}.json"
        path = root / relative
        _write_json(path, record)
        result[module.module_id] = {
            "path": relative,
            "sha256": sha256_file(path),
        }
    return result


def _train_only_smoke_bundle(
    candidates: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    group_splits: Mapping[str, str],
) -> dict[str, Any]:
    train_groups_by_module: dict[str, str] = {}
    for group_id, split in sorted(group_splits.items()):
        if split != "train":
            continue
        for module_id in ("hard-boundaries", "continuity-context", "soft-combinations"):
            if group_id.startswith(f"pcv9-{module_id}-"):
                train_groups_by_module.setdefault(module_id, group_id)
    if set(train_groups_by_module) != {
        "hard-boundaries",
        "continuity-context",
        "soft-combinations",
    }:
        raise SuccessorBuildError("train-only smoke cannot cover every module")
    selected_groups = set(train_groups_by_module.values())
    smoke_candidates = sorted(
        (copy.deepcopy(row) for row in candidates if row["group_id"] in selected_groups),
        key=lambda row: row["candidate_id"],
    )
    smoke_pairs = sorted(
        (copy.deepcopy(row) for row in pairs if row["group_id"] in selected_groups),
        key=lambda row: row["pair_id"],
    )
    return {
        "schema": "rondo-publication-critic-successor-train-only-smoke@v1",
        "dataset_revision": DATASET_REVISION,
        "accepted_task": ACCEPTED_TASK,
        "split": "train",
        "candidates": smoke_candidates,
        "pairs": smoke_pairs,
    }


def _data_card(coverage: Mapping[str, Any]) -> str:
    lines = [
        "# Publication Critic successor data v9",
        "",
        "This is the contract-native Plan 098 successor release for "
        "`rondo-publication-critic-task@v2`.",
        "",
        "- Accepted implementation: " f"`{ACCEPTED_IMPLEMENTATION_COMMIT}`",
        "- Accepted implementation bundle SHA-256: "
        f"`{ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256}`",
        "- Accepted task SHA-256: " f"`{ACCEPTED_TASK_SHA256}`",
        "- Candidates: " f"{coverage['total_candidates']}",
        "- Pairs: " f"{coverage['total_pairs']}",
        "- Source: new synthetic, product-shaped public packets; direct v8 reuse is zero "
        "after inspecting only its train-only safe projection.",
        "- Splits: physically separate train, validation, and test files. The public "
        "consumer exposes train and explicit validation only; no test loader exists.",
        "- Smoke: a bounded train-only bundle covers one closed group from each module.",
        "- Reviews: three independently authored modules, each accepted by its paired "
        "blind reviewer; tracked module records bind source and review hashes.",
        "",
        "This release is training data, not model-quality, product-value, default-enable, "
        "or production evidence.",
        "",
    ]
    return "\n".join(lines)


def _context_bucket(packet: Mapping[str, Any]) -> str:
    if packet["target_kind"] == "new_event":
        return "new_event"
    return f"existing_event_{packet['continuity']['state']}"


def _candidate_length(packet: Mapping[str, Any]) -> int:
    candidate = packet["candidate"]
    return len(packet["local_scope"]["title"]) + len(candidate["summary"]) + len(
        candidate["handoff"] or ""
    )


def _module_spec(design: Mapping[str, Any], module_id: str) -> Mapping[str, Any]:
    for spec in design["module_contract"]["modules"]:
        if spec["module_id"] == module_id:
            return spec
    raise SuccessorBuildError(f"unknown module_id: {module_id}")


def _validate_accepted_task(value: Any, repo_root: Path) -> None:
    _literal(value, ACCEPTED_TASK, "accepted task identity")
    if task_content_sha256(repo_root) != ACCEPTED_TASK_SHA256:
        raise SuccessorBuildError("accepted task authority bytes drifted")


def _validate_accepted_implementation(value: Any, repo_root: Path) -> None:
    identity = _object(value, "accepted implementation identity")
    _exact_keys(
        identity,
        {"commit", "algorithm", "components", "bundle_sha256"},
        "accepted implementation identity",
    )
    _literal(
        identity["commit"],
        ACCEPTED_IMPLEMENTATION_COMMIT,
        "accepted implementation commit",
    )
    _literal(
        identity["algorithm"],
        ACCEPTED_IMPLEMENTATION_ALGORITHM,
        "accepted implementation algorithm",
    )
    _literal(
        identity["bundle_sha256"],
        ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256,
        "accepted implementation bundle",
    )
    components = identity["components"]
    if not isinstance(components, list):
        raise SuccessorBuildError("accepted implementation components differ")
    paths: list[str] = []
    for value in components:
        component = _object(value, "accepted implementation component")
        _exact_keys(
            component,
            {"path", "sha256"},
            "accepted implementation component",
        )
        paths.append(component["path"])
        if not isinstance(component["sha256"], str) or not re.fullmatch(
            r"[0-9a-f]{64}", component["sha256"]
        ):
            raise SuccessorBuildError("accepted implementation component hash differs")
    _literal(
        paths,
        list(ACCEPTED_IMPLEMENTATION_COMPONENT_PATHS),
        "accepted implementation component paths",
    )
    bundle_sha256 = hashlib.sha256(
        canonical_json_bytes(components)
    ).hexdigest()
    if bundle_sha256 != ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256:
        raise SuccessorBuildError("accepted implementation bundle differs")
    for component in components:
        relative = component["path"]
        path = _safe_repo_component_file(repo_root, relative)
        if sha256_file(path) != component["sha256"]:
            raise SuccessorBuildError(
                f"accepted implementation component drifted: {relative}"
            )


def _minimum(observed: int, required: int, where: str) -> None:
    if observed < required:
        raise SuccessorBuildError(f"{where} is below minimum: {observed} < {required}")


def _minimum_mapping(
    observed: Mapping[str, int],
    required: Mapping[str, int],
    where: str,
) -> None:
    for key, minimum in required.items():
        _minimum(int(observed.get(key, 0)), int(minimum), f"{where}.{key}")


def _file_binding(path: Path, relative: str) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        rows = sum(1 for _ in handle)
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "rows": rows,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _copy_bytes(source: Path, destination: Path) -> None:
    if not source.is_file() or source.is_symlink():
        raise SuccessorBuildError(f"frozen source is missing or unsafe: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def _load_json(path: Path, where: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SuccessorBuildError(f"{where} is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuccessorBuildError(f"{where} is invalid JSON") from exc
    return _object(value, where)


def _safe_workspace_file(root: Path, relative: str) -> Path:
    safe = _safe_relative(relative, "workspace path")
    resolved_root = root.resolve()
    current = resolved_root
    for part in Path(safe).parts:
        current = current / part
        if current.is_symlink():
            raise SuccessorBuildError(f"workspace path contains a symlink: {relative}")
    if not current.is_file():
        raise SuccessorBuildError(f"workspace input is missing: {relative}")
    return current


def _safe_repo_component_file(root: Path, relative: str) -> Path:
    safe = _safe_relative(relative, "accepted implementation component path")
    resolved_root = root.resolve()
    current = resolved_root
    for part in Path(safe).parts:
        current = current / part
        if current.is_symlink():
            raise SuccessorBuildError(
                f"accepted implementation component is unsafe: {relative}"
            )
    if not current.is_file():
        raise SuccessorBuildError(
            f"accepted implementation component is missing: {relative}"
        )
    return current


def _safe_relative(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise SuccessorBuildError(f"{where} must be a relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SuccessorBuildError(f"{where} is unsafe")
    return value


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SuccessorBuildError(f"{where} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        raise SuccessorBuildError(f"{where} keys differ")


def _literal(value: Any, expected: Any, where: str) -> None:
    if value != expected or isinstance(value, bool) != isinstance(expected, bool):
        raise SuccessorBuildError(f"{where} differs")


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise SuccessorBuildError(f"{where} is not a bounded identifier")
    return value
