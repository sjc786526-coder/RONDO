"""Plan 098 directional development and sealed qualification data finalizer."""

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
from .qualification import (
    DECISION_CONTRACT_AUTHORITY,
    DECISION_CONTRACT_NAME,
    DECISION_CONTRACT_VERSION,
    DECISION_IMPLEMENTATION_COMPONENT_PATHS,
    decision_contract_sha256,
    decision_implementation_identity,
)
from .successor_build import (
    ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256,
    ACCEPTED_IMPLEMENTATION_COMMIT,
    ACCEPTED_TASK,
    load_build_contracts,
)
from .successor_data import (
    CANDIDATE_SCHEMA,
    PAIR_SCHEMA,
    SuccessorDataError,
    SuccessorRelease,
    validate_candidate_row,
    validate_pair_row,
    validate_split,
)
from .successor_task import HARD_DIMENSIONS, derive_verdict, validate_pair_labels
from .training_data.contract import TrainingDataError
from .training_data.dedup import (
    find_near_duplicate_edges,
    find_reference_matches,
    reject_exact_duplicates,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_ROOT = Path("eval/templates/publication-critic")
DESIGN_PATH = TEMPLATE_ROOT / "directional-remediation-design-v1.json"
CONFIG_PATH = TEMPLATE_ROOT / "directional-remediation-config-v1.json"
DEVELOPMENT_REVISION = "publication-critic-v10"
QUALIFICATION_SET_ID = "publication-critic-qualification-v1"
DECISION_IMPLEMENTATION_COMMIT = "9d281cf56d1b66140b24a765cfced12db78af9c1"
DECISION_IMPLEMENTATION_BUNDLE_SHA256 = (
    "ebddb382d8fd166b69763665bf4efcdae20fd187d390954c322f80fefbadb824"
)
DEVELOPMENT_PATCH_SCHEMA = "rondo-publication-critic-directional-development-patch@v1"
DEVELOPMENT_REVIEW_SCHEMA = "rondo-publication-critic-directional-development-review@v1"
QUALIFICATION_SOURCE_SCHEMA = "rondo-publication-critic-qualification-source@v1"
QUALIFICATION_REVIEW_SCHEMA = "rondo-publication-critic-qualification-review@v1"
DEVELOPMENT_MANIFEST_SCHEMA = "rondo-publication-critic-development-release-manifest@v1"
QUALIFICATION_MANIFEST_SCHEMA = "rondo-publication-critic-qualification-set-manifest@v1"
DEVELOPMENT_SPLITS = ("train", "validation")
MODULE_IDS = ("hard-boundaries", "continuity-context", "soft-combinations")
COUNTEREXAMPLE_TAGS = {
    "honest_subtle_fail",
    "honest_supported_absolute_pass",
    "scope_short_confused_fail",
    "scope_long_clear_pass",
    "natural_multi_defect",
}
DEVELOPMENT_REVIEW_CHECKS = (
    "base_binding",
    "immutable_labels_and_relations",
    "honest_counterexamples",
    "scope_counterexamples",
    "natural_multi_defects",
    "continuity_basis",
    "language_quality",
    "no_hidden_metadata",
)
QUALIFICATION_REVIEW_CHECKS = (
    "contract_alignment",
    "complete_absolute_labels",
    "family_lineage",
    "boundary_closure",
    "soft_only_invariance",
    "shortcut_resistance",
    "language_quality",
    "no_hidden_metadata",
    "isolation_confirmed",
)
QUALIFICATION_CANDIDATE_TAGS = {
    "qplus": "qualification_pass",
    "qminus": "qualification_single_fail",
    "multi": "qualification_multi_fail",
    "soft": "qualification_soft_counterfactual",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_HONEST_ABSOLUTE_CUES = (
    "all",
    "always",
    "certain",
    "certainty",
    "definitive",
    "definitively",
    "every",
    "forever",
    "guarantee",
    "guaranteed",
    "never",
    "none",
    "proof",
    "proven",
)
_COMMENTARY_CUES = (
    "buried beneath",
    "generalized as proof",
    "long stream",
    "mostly sign-off",
    "the update says",
    "treated as proof",
)
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
        "qualification_single_fail",
        "qualification_multi_fail",
    )
)


class DirectionalDataError(ValueError):
    """A directional patch, review, release, or qualification set is invalid."""


@dataclass(frozen=True)
class DirectionalContracts:
    repo_root: Path
    design: Mapping[str, Any]
    config: Mapping[str, Any]
    design_sha256: str
    config_sha256: str


@dataclass(frozen=True)
class ValidatedPatch:
    module_id: str
    owner_role: str
    source_sha256: str
    replacements: tuple[Mapping[str, Any], ...]
    tag_counts: Mapping[str, Mapping[str, int]]


@dataclass(frozen=True)
class ValidatedQualificationSource:
    source_sha256: str
    owner_role: str
    family_namespace: str
    candidates: tuple[Mapping[str, Any], ...]
    pairs: tuple[Mapping[str, Any], ...]
    lineage: tuple[Mapping[str, Any], ...]
    coverage: Mapping[str, Any]


@dataclass(frozen=True)
class DevelopmentRelease:
    root: Path
    manifest: Mapping[str, Any]
    repo_root: Path

    @classmethod
    def open(
        cls,
        root: Path | str,
        *,
        repo_root: Path | str = REPO_ROOT,
    ) -> "DevelopmentRelease":
        release_root = Path(root)
        repository = Path(repo_root)
        manifest = _load_json(
            _safe_file(release_root, "manifest.json"),
            "development manifest",
        )
        _validate_development_manifest(manifest, repository)
        contracts = load_directional_contracts(repository)
        _validate_frozen_contract_copies(release_root, contracts)
        identity = _load_json(
            _safe_file(release_root, "release-identity.json"),
            "development release identity",
        )
        _validate_development_release_identity(
            identity,
            release_root,
            contracts,
        )
        _validate_frozen_patch_records(release_root, contracts)
        if (release_root / "splits/test").exists():
            raise DirectionalDataError("development release contains a test split")
        return cls(root=release_root, manifest=manifest, repo_root=repository)

    def load_train(
        self,
    ) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
        return self._load_split("train")

    def load_validation(
        self,
    ) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
        return self._load_split("validation")

    def _load_split(
        self,
        split: str,
    ) -> tuple[tuple[Mapping[str, Any], ...], tuple[Mapping[str, Any], ...]]:
        binding = self.manifest["splits"][split]
        candidates = _read_bound_jsonl(self.root, binding["candidates"])
        pairs = _read_bound_jsonl(self.root, binding["pairs"])
        try:
            validate_split(split, candidates, pairs, repo_root=self.repo_root)
        except SuccessorDataError as exc:
            raise DirectionalDataError(f"development {split}: {exc}") from exc
        return tuple(candidates), tuple(pairs)


def load_directional_contracts(
    repo_root: Path | str = REPO_ROOT,
) -> DirectionalContracts:
    root = Path(repo_root)
    load_build_contracts(root)
    design_path = root / DESIGN_PATH
    config_path = root / CONFIG_PATH
    design = _load_json(design_path, "directional design")
    config = _load_json(config_path, "directional config")
    design_sha256 = sha256_file(design_path)
    config_sha256 = sha256_file(config_path)
    _validate_design(design, root)
    _validate_config(config, design, design_sha256)
    return DirectionalContracts(
        repo_root=root,
        design=design,
        config=config,
        design_sha256=design_sha256,
        config_sha256=config_sha256,
    )


def finalize_directional_releases(
    *,
    ignored_root: Path | str,
    development_output: Path | str,
    qualification_output: Path | str,
    repo_root: Path | str = REPO_ROOT,
    enforce_config_paths: bool = True,
) -> Mapping[str, Any]:
    """Freeze development-only v10 and one sealed, independently authored set."""

    root = Path(repo_root)
    contracts = load_directional_contracts(root)
    work = Path(ignored_root)
    dev_destination = Path(development_output)
    qual_destination = Path(qualification_output)
    if enforce_config_paths:
        _literal(
            work.resolve().as_posix(),
            contracts.config["ignored_root"],
            "directional ignored root",
        )
        _literal(
            dev_destination.resolve(),
            (root / contracts.config["development_output"]).resolve(),
            "development output",
        )
        _literal(
            qual_destination.resolve(),
            (root / contracts.config["qualification_output"]).resolve(),
            "qualification output",
        )
    if not work.is_dir() or work.is_symlink():
        raise DirectionalDataError("directional ignored root is missing or unsafe")
    for destination in (dev_destination, qual_destination):
        if destination.exists() or destination.is_symlink():
            raise DirectionalDataError(f"formal output already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
    dev_temp = dev_destination.parent / f".{dev_destination.name}.plan098-tmp"
    qual_temp = qual_destination.parent / f".{qual_destination.name}.plan098-tmp"
    for temporary in (dev_temp, qual_temp):
        if temporary.exists() or temporary.is_symlink():
            raise DirectionalDataError("transactional output path is not clean")

    base_release, base_splits = _load_base_development(contracts.design, root)
    patches: list[ValidatedPatch] = []
    patch_records: dict[str, Any] = {}
    patch_artifacts: dict[str, tuple[Path, Path]] = {}
    for binding in contracts.config["development_patches"]:
        patch_path = _safe_workspace_file(work, binding["source"])
        review_path = _safe_workspace_file(work, binding["review"])
        patch = validate_development_patch(
            patch_path,
            base_splits=base_splits,
            contracts=contracts,
            repo_root=root,
        )
        if patch.module_id != binding["module_id"]:
            raise DirectionalDataError("development patch module binding differs")
        review = validate_development_review(
            review_path,
            patch,
            contracts=contracts,
        )
        patches.append(patch)
        patch_artifacts[patch.module_id] = (patch_path, review_path)
        patch_records[patch.module_id] = {
            "owner_role": patch.owner_role,
            "source_sha256": patch.source_sha256,
            "review_sha256": sha256_file(review_path),
            "reviewer_role": review["reviewer_role"],
            "verdict": review["verdict"],
            "replacements": len(patch.replacements),
        }
    patched_splits, diagnostics = _apply_development_patches(
        base_splits,
        patches,
        contracts.design,
        repo_root=root,
    )

    qualification_source_path = _safe_workspace_file(
        work,
        contracts.config["qualification_source"],
    )
    qualification_review_path = _safe_workspace_file(
        work,
        contracts.config["qualification_review"],
    )
    qualification = validate_qualification_source(
        qualification_source_path,
        development_candidates=tuple(
            row for split in DEVELOPMENT_SPLITS for row in patched_splits[split][0]
        ),
        contracts=contracts,
        repo_root=root,
    )
    qualification_review = validate_qualification_review(
        qualification_review_path,
        qualification,
        contracts=contracts,
    )

    try:
        qual_temp.mkdir(parents=False)
        qualification_manifest = _write_qualification_release(
            qual_temp,
            qualification,
            qualification_review,
            review_path=qualification_review_path,
            review_sha256=sha256_file(qualification_review_path),
            contracts=contracts,
        )
        dev_temp.mkdir(parents=False)
        development_manifest = _write_development_release(
            dev_temp,
            base_release=base_release,
            splits=patched_splits,
            diagnostics=diagnostics,
            patch_records=patch_records,
            patch_artifacts=patch_artifacts,
            qualification_manifest_sha256=hashlib.sha256(
                canonical_json_bytes(qualification_manifest)
            ).hexdigest(),
            contracts=contracts,
        )
        development = DevelopmentRelease.open(dev_temp, repo_root=root)
        train_candidates, _ = development.load_train()
        validation_candidates, _ = development.load_validation()
        if hasattr(development, "load_test"):
            raise DirectionalDataError("development consumer exposes test")
        if len(train_candidates) != 162 or len(validation_candidates) != 27:
            raise DirectionalDataError("development split count differs")
        validate_qualification_release_metadata(qual_temp, contracts=contracts)
        dev_temp.rename(dev_destination)
        qual_temp.rename(qual_destination)
    except Exception:
        for destination, temporary in (
            (qual_destination, qual_temp),
            (dev_destination, dev_temp),
        ):
            if (
                destination.is_dir()
                and not destination.is_symlink()
                and not temporary.exists()
            ):
                destination.rename(temporary)
        for temporary in (dev_temp, qual_temp):
            if temporary.is_dir() and not temporary.is_symlink():
                shutil.rmtree(temporary)
        raise
    return {
        "development": {
            "revision": DEVELOPMENT_REVISION,
            "manifest_sha256": hashlib.sha256(
                canonical_json_bytes(development_manifest)
            ).hexdigest(),
            "diagnostics": diagnostics,
        },
        "qualification": {
            "set_id": QUALIFICATION_SET_ID,
            "manifest_sha256": hashlib.sha256(
                canonical_json_bytes(qualification_manifest)
            ).hexdigest(),
            "coverage": qualification.coverage,
        },
    }


def validate_development_patch(
    path: Path | str,
    *,
    base_splits: Mapping[
        str, tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
    ],
    contracts: DirectionalContracts,
    repo_root: Path | str = REPO_ROOT,
) -> ValidatedPatch:
    source_path = Path(path)
    value = _load_json(source_path, "development patch")
    _exact_keys(
        value,
        {"schema", "module_id", "owner_role", "base_release", "replacements", "notes"},
        "development patch",
    )
    _literal(value["schema"], DEVELOPMENT_PATCH_SCHEMA, "development patch.schema")
    module_id = _identifier(value["module_id"], "development patch.module_id")
    if module_id not in MODULE_IDS:
        raise DirectionalDataError("development patch module_id differs")
    _literal(
        value["owner_role"],
        f"plan098-module-owner-{module_id}",
        "development patch.owner_role",
    )
    base_binding = _object(value["base_release"], "development patch.base_release")
    _exact_keys(
        base_binding,
        {
            "dataset_revision",
            "manifest_sha256",
            "train_candidates_sha256",
            "validation_candidates_sha256",
        },
        "development patch.base_release",
    )
    base_design = contracts.design["base_release"]
    _literal(
        base_binding,
        {
            "dataset_revision": base_design["revision"],
            "manifest_sha256": base_design["manifest_sha256"],
            "train_candidates_sha256": base_design["development_splits"]["train"][
                "candidates_sha256"
            ],
            "validation_candidates_sha256": base_design["development_splits"][
                "validation"
            ]["candidates_sha256"],
        },
        "development patch.base_release",
    )
    replacements = value["replacements"]
    if not isinstance(replacements, list) or not replacements:
        raise DirectionalDataError("development patch replacements are empty")
    base_by_split = {
        split: {row["candidate_id"]: row for row in base_splits[split][0]}
        for split in DEVELOPMENT_SPLITS
    }
    seen: set[str] = set()
    tag_counts = {split: Counter() for split in DEVELOPMENT_SPLITS}
    normalized: list[Mapping[str, Any]] = []
    for replacement_value in replacements:
        replacement = _object(replacement_value, "development replacement")
        _exact_keys(
            replacement,
            {
                "split",
                "candidate_id",
                "base_candidate_sha256",
                "counterexample_tags",
                "candidate",
            },
            "development replacement",
        )
        split = replacement["split"]
        if split not in DEVELOPMENT_SPLITS:
            raise DirectionalDataError("development replacement split differs")
        candidate_id = _identifier(
            replacement["candidate_id"],
            "development replacement.candidate_id",
        )
        if candidate_id in seen:
            raise DirectionalDataError("development patch repeats candidate_id")
        seen.add(candidate_id)
        if not candidate_id.startswith(f"pcv9-{module_id}-"):
            raise DirectionalDataError("development replacement crosses module")
        base = base_by_split[split].get(candidate_id)
        if base is None:
            raise DirectionalDataError("development replacement target is absent")
        _literal(
            replacement["base_candidate_sha256"],
            hashlib.sha256(canonical_json_bytes(base)).hexdigest(),
            "development replacement base hash",
        )
        candidate = _object(replacement["candidate"], "development candidate")
        try:
            validate_candidate_row(candidate, repo_root=repo_root)
        except SuccessorDataError as exc:
            raise DirectionalDataError(f"{candidate_id}: {exc}") from exc
        _literal(candidate["candidate_id"], candidate_id, "replacement candidate_id")
        if _without_candidate_text(candidate) != _without_candidate_text(base):
            raise DirectionalDataError(
                f"{candidate_id} changes fields outside candidate text and basis"
            )
        tags = replacement["counterexample_tags"]
        if (
            not isinstance(tags, list)
            or not tags
            or len(tags) != len(set(tags))
            or not set(tags) <= COUNTEREXAMPLE_TAGS
        ):
            raise DirectionalDataError(f"{candidate_id} counterexample tags differ")
        _validate_replacement_tags(candidate, tags)
        visible = _candidate_text(candidate).casefold()
        if any(cue in visible for cue in _COMMENTARY_CUES):
            raise DirectionalDataError(f"{candidate_id} retains a commentary cue")
        tag_counts[split].update(tags)
        normalized.append(copy.deepcopy(replacement))
    notes = value["notes"]
    if not isinstance(notes, list) or any(
        not isinstance(note, str) or not note.strip() or len(note) > 500
        for note in notes
    ):
        raise DirectionalDataError("development patch notes differ")
    minimums = contracts.design["development_release"]["minimum_tags_per_module"]
    for split in DEVELOPMENT_SPLITS:
        for tag, minimum in minimums[split].items():
            if tag_counts[split][tag] < minimum:
                raise DirectionalDataError(
                    f"{module_id} {split} {tag} is below minimum"
                )
    return ValidatedPatch(
        module_id=module_id,
        owner_role=value["owner_role"],
        source_sha256=sha256_file(source_path),
        replacements=tuple(normalized),
        tag_counts={
            split: dict(sorted(tag_counts[split].items()))
            for split in DEVELOPMENT_SPLITS
        },
    )


def validate_development_review(
    path: Path | str,
    patch: ValidatedPatch,
    *,
    contracts: DirectionalContracts,
) -> Mapping[str, Any]:
    value = _load_json(Path(path), "development review")
    _exact_keys(
        value,
        {
            "schema",
            "module_id",
            "reviewer_role",
            "patch_sha256",
            "verdict",
            "findings",
            "checklist",
        },
        "development review",
    )
    _literal(value["schema"], DEVELOPMENT_REVIEW_SCHEMA, "development review.schema")
    _literal(value["module_id"], patch.module_id, "development review.module_id")
    _literal(
        value["reviewer_role"],
        contracts.design["development_release"]["reviewer_roles"][patch.module_id],
        "development review.reviewer_role",
    )
    _literal(
        value["patch_sha256"], patch.source_sha256, "development review patch hash"
    )
    checklist = _object(value["checklist"], "development review.checklist")
    _exact_keys(
        checklist, set(DEVELOPMENT_REVIEW_CHECKS), "development review.checklist"
    )
    if any(checklist[check] is not True for check in DEVELOPMENT_REVIEW_CHECKS):
        raise DirectionalDataError("development review checklist is incomplete")
    findings = value["findings"]
    if not isinstance(findings, list) or findings:
        raise DirectionalDataError("development review findings are not closed")
    _literal(value["verdict"], "accept", "development review.verdict")
    return value


def validate_qualification_source(
    path: Path | str,
    *,
    development_candidates: Sequence[Mapping[str, Any]],
    contracts: DirectionalContracts,
    repo_root: Path | str = REPO_ROOT,
) -> ValidatedQualificationSource:
    source_path = Path(path)
    value = _load_json(source_path, "qualification source")
    _exact_keys(
        value,
        {"schema", "set_id", "owner_role", "isolation", "groups"},
        "qualification source",
    )
    _literal(
        value["schema"], QUALIFICATION_SOURCE_SCHEMA, "qualification source.schema"
    )
    design = contracts.design["qualification_set"]
    _literal(value["set_id"], design["set_id"], "qualification source.set_id")
    _literal(
        value["owner_role"], design["owner_role"], "qualification source.owner_role"
    )
    isolation = _object(value["isolation"], "qualification source.isolation")
    _literal(
        isolation,
        {
            "prior_data_access": "forbidden_and_not_performed",
            "training_result_access": "forbidden_and_not_performed",
            "family_namespace": design["family_namespace"],
        },
        "qualification source.isolation",
    )
    groups = value["groups"]
    if not isinstance(groups, list) or len(groups) != design["groups"]:
        raise DirectionalDataError("qualification group count differs")
    candidates: list[Mapping[str, Any]] = []
    pairs: list[Mapping[str, Any]] = []
    lineage_rows: list[Mapping[str, Any]] = []
    seen_group_ids: set[str] = set()
    seen_family_triples: set[tuple[str, str, str]] = set()
    seen_scenarios: set[str] = set()
    seen_templates: set[str] = set()
    target_counts: Counter[str] = Counter()
    context_counts: Counter[str] = Counter()
    for index, group_value in enumerate(groups, start=1):
        group = _object(group_value, "qualification group")
        _exact_keys(
            group,
            {"group_id", "lineage", "context", "candidates", "pairs"},
            "qualification group",
        )
        group_id = _identifier(group["group_id"], "qualification group.group_id")
        _literal(group_id, f"pcq1-group-{index:03d}", "qualification group order")
        if group_id in seen_group_ids:
            raise DirectionalDataError("qualification repeats group_id")
        seen_group_ids.add(group_id)
        lineage = _object(group["lineage"], f"{group_id} lineage")
        _exact_keys(
            lineage,
            {"source_family", "scenario_family", "template_family"},
            f"{group_id} lineage",
        )
        family_values = tuple(
            _identifier(lineage[field], f"{group_id} lineage.{field}")
            for field in ("source_family", "scenario_family", "template_family")
        )
        if any(
            not family.startswith(f"{design['family_namespace']}-")
            for family in family_values
        ):
            raise DirectionalDataError(f"{group_id} family namespace differs")
        if family_values in seen_family_triples:
            raise DirectionalDataError("qualification repeats a family triple")
        if family_values[1] in seen_scenarios or family_values[2] in seen_templates:
            raise DirectionalDataError("qualification reuses scenario/template family")
        seen_family_triples.add(family_values)
        seen_scenarios.add(family_values[1])
        seen_templates.add(family_values[2])
        context = _object(group["context"], f"{group_id} context")
        context_counts[_context_bucket(context)] += 1
        authored_candidates = group["candidates"]
        if (
            not isinstance(authored_candidates, list)
            or len(authored_candidates) != design["candidates_per_group"]
        ):
            raise DirectionalDataError(f"{group_id} candidate count differs")
        by_key: dict[str, Mapping[str, Any]] = {}
        tags_by_key: dict[str, tuple[str, ...]] = {}
        for authored_value in authored_candidates:
            authored = _object(authored_value, f"{group_id} candidate")
            _exact_keys(
                authored,
                {"key", "summary", "handoff", "labels", "continuity_basis", "tags"},
                f"{group_id} candidate",
            )
            key = _identifier(authored["key"], f"{group_id} candidate key")
            if key in by_key:
                raise DirectionalDataError(f"{group_id} repeats candidate key")
            expected_tag = QUALIFICATION_CANDIDATE_TAGS.get(key)
            _literal(authored["tags"], [expected_tag], f"{group_id} {key} tags")
            labels = _object(authored["labels"], f"{group_id} {key} labels")
            basis = _object(
                authored["continuity_basis"],
                f"{group_id} {key} continuity basis",
            )
            _exact_keys(basis, {"field", "quote"}, f"{group_id} {key} basis")
            candidate_id = f"{group_id}-{key}"
            row = {
                "schema": CANDIDATE_SCHEMA,
                "candidate_id": candidate_id,
                "group_id": group_id,
                "packet": {
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
                },
                "labels": copy.deepcopy(labels),
                "continuity_label_basis": {
                    "type": (
                        "model_visible_complete_claim"
                        if labels.get("conditional_continuity") == "N/A"
                        else "model_visible_unfinished_or_not_closed"
                    ),
                    "field": basis["field"],
                    "quote": basis["quote"],
                },
            }
            try:
                validate_candidate_row(row, repo_root=repo_root)
            except SuccessorDataError as exc:
                raise DirectionalDataError(f"{candidate_id}: {exc}") from exc
            rendered = json.dumps(row["packet"], ensure_ascii=False).casefold()
            if any(token in rendered for token in _MODEL_VISIBLE_FORBIDDEN):
                raise DirectionalDataError(f"{candidate_id} exposes hidden metadata")
            by_key[key] = row
            tags_by_key[key] = tuple(authored["tags"])
            candidates.append(row)
        _literal(
            list(by_key),
            design["required_candidate_keys"],
            f"{group_id} candidate order",
        )
        authored_pairs = group["pairs"]
        if (
            not isinstance(authored_pairs, list)
            or len(authored_pairs) != design["pairs_per_group"]
        ):
            raise DirectionalDataError(f"{group_id} pair count differs")
        kinds: list[str] = []
        boundary_target: str | None = None
        for authored_pair_value in authored_pairs:
            authored_pair = _object(authored_pair_value, f"{group_id} pair")
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
            left_key = authored_pair["left_key"]
            right_key = authored_pair["right_key"]
            if left_key not in by_key or right_key not in by_key:
                raise DirectionalDataError(f"{group_id} pair endpoint is absent")
            pair = {
                "schema": PAIR_SCHEMA,
                "pair_id": f"{group_id}-{authored_pair['key']}",
                "group_id": group_id,
                "kind": authored_pair["kind"],
                "left_candidate_id": by_key[left_key]["candidate_id"],
                "right_candidate_id": by_key[right_key]["candidate_id"],
                "target_dimension": authored_pair["target_dimension"],
                "soft_change": authored_pair["soft_change"],
            }
            try:
                validate_pair_row(pair)
                validate_pair_labels(
                    pair["kind"],
                    by_key[left_key]["labels"],
                    by_key[right_key]["labels"],
                    target_dimension=pair["target_dimension"],
                )
            except (SuccessorDataError, ValueError) as exc:
                raise DirectionalDataError(f"{pair['pair_id']}: {exc}") from exc
            kinds.append(pair["kind"])
            if pair["kind"] == "boundary":
                boundary_target = pair["target_dimension"]
            pairs.append(pair)
        _literal(kinds, design["required_pair_kinds"], f"{group_id} pair kinds")
        if boundary_target not in HARD_DIMENSIONS:
            raise DirectionalDataError(f"{group_id} boundary target differs")
        target_counts[boundary_target] += 1
        qplus = by_key["qplus"]["labels"]
        qminus = by_key["qminus"]["labels"]
        multi = by_key["multi"]["labels"]
        soft = by_key["soft"]["labels"]
        if derive_verdict(qplus) != "PASS" or derive_verdict(soft) != "PASS":
            raise DirectionalDataError(f"{group_id} pass endpoints differ")
        if qplus != soft:
            raise DirectionalDataError(f"{group_id} soft labels differ")
        if sum(qminus[dimension] == "FAIL" for dimension in HARD_DIMENSIONS) != 1:
            raise DirectionalDataError(f"{group_id} qminus is not a single failure")
        if sum(multi[dimension] == "FAIL" for dimension in HARD_DIMENSIONS) < 2:
            raise DirectionalDataError(f"{group_id} multi lacks two failures")
        if qminus[boundary_target] != "FAIL" or multi[boundary_target] != "FAIL":
            raise DirectionalDataError(f"{group_id} target failure differs")
        lineage_rows.append({"group_id": group_id, **dict(lineage)})

    _literal(
        dict(target_counts),
        {
            dimension: design["boundary_targets_per_dimension"]
            for dimension in HARD_DIMENSIONS
        },
        "qualification boundary target coverage",
    )
    if sorted(context_counts.values()) != [16, 17, 17]:
        raise DirectionalDataError("qualification context balance differs")
    try:
        reject_exact_duplicates(candidates)
        near_edges = find_near_duplicate_edges(
            candidates,
            threshold=design["development_near_duplicate_threshold"],
        )
        development_matches = find_reference_matches(
            candidates,
            {row["candidate_id"]: row["packet"] for row in development_candidates},
            threshold=design["development_near_duplicate_threshold"],
        )
    except TrainingDataError as exc:
        raise DirectionalDataError(str(exc)) from exc
    candidate_groups = {row["candidate_id"]: row["group_id"] for row in candidates}
    if any(
        candidate_groups[edge.left_candidate_id]
        != candidate_groups[edge.right_candidate_id]
        for edge in near_edges
    ):
        raise DirectionalDataError("qualification has cross-group near duplicates")
    if development_matches:
        raise DirectionalDataError("qualification overlaps development text")
    verdicts = Counter(derive_verdict(row["labels"]) for row in candidates)
    lengths = {"PASS": [], "REWRITE": []}
    for row in candidates:
        lengths[derive_verdict(row["labels"])].append(_candidate_length(row))
    if max(min(lengths["PASS"]), min(lengths["REWRITE"])) > min(
        max(lengths["PASS"]), max(lengths["REWRITE"])
    ):
        raise DirectionalDataError("qualification verdict lengths do not overlap")
    dimension_length_auc = {
        dimension: _dimension_length_separability(candidates, dimension)
        for dimension in HARD_DIMENSIONS
    }
    length_auc_maximum = design["shortcut_diagnostics"]["dimension_length_auc_maximum"]
    excessive_length_auc = {
        dimension: auc
        for dimension, auc in dimension_length_auc.items()
        if auc > length_auc_maximum
    }
    if excessive_length_auc:
        raise DirectionalDataError(
            "qualification dimension length AUC remains above the design maximum: "
            + ", ".join(
                f"{dimension}={auc:.6f}"
                for dimension, auc in excessive_length_auc.items()
            )
        )
    honest_cue_matrix = {
        "fail_with_absolute_cue": sum(
            row["labels"]["honest_uncertainty"] == "FAIL" and _has_honest_cue(row)
            for row in candidates
        ),
        "fail_without_absolute_cue": sum(
            row["labels"]["honest_uncertainty"] == "FAIL" and not _has_honest_cue(row)
            for row in candidates
        ),
        "pass_with_absolute_cue": sum(
            row["labels"]["honest_uncertainty"] == "PASS" and _has_honest_cue(row)
            for row in candidates
        ),
        "pass_without_absolute_cue": sum(
            row["labels"]["honest_uncertainty"] == "PASS" and not _has_honest_cue(row)
            for row in candidates
        ),
    }
    coverage = {
        "schema": "rondo-publication-critic-qualification-coverage@v1",
        "groups": len(groups),
        "candidates": len(candidates),
        "pairs": len(pairs),
        "boundary_targets": dict(sorted(target_counts.items())),
        "context_groups": dict(sorted(context_counts.items())),
        "verdicts": dict(sorted(verdicts.items())),
        "dimension_fail": {
            dimension: sum(row["labels"][dimension] == "FAIL" for row in candidates)
            for dimension in HARD_DIMENSIONS
        },
        "family_triples": len(seen_family_triples),
        "scenario_families": len(seen_scenarios),
        "template_families": len(seen_templates),
        "cross_group_near_duplicates": 0,
        "development_near_duplicates": 0,
        "candidate_length_range": {
            verdict: [min(values), max(values)] for verdict, values in lengths.items()
        },
        "dimension_length_auc": dimension_length_auc,
        "honest_absolute_cue_matrix": honest_cue_matrix,
    }
    return ValidatedQualificationSource(
        source_sha256=sha256_file(source_path),
        owner_role=value["owner_role"],
        family_namespace=isolation["family_namespace"],
        candidates=tuple(candidates),
        pairs=tuple(pairs),
        lineage=tuple(lineage_rows),
        coverage=coverage,
    )


def validate_qualification_review(
    path: Path | str,
    source: ValidatedQualificationSource,
    *,
    contracts: DirectionalContracts,
) -> Mapping[str, Any]:
    value = _load_json(Path(path), "qualification review")
    _exact_keys(
        value,
        {
            "schema",
            "set_id",
            "reviewer_role",
            "source_sha256",
            "verdict",
            "findings",
            "checklist",
        },
        "qualification review",
    )
    _literal(
        value["schema"], QUALIFICATION_REVIEW_SCHEMA, "qualification review.schema"
    )
    _literal(value["set_id"], QUALIFICATION_SET_ID, "qualification review.set_id")
    _literal(
        value["reviewer_role"],
        contracts.design["qualification_set"]["reviewer_role"],
        "qualification review.reviewer_role",
    )
    _literal(
        value["source_sha256"], source.source_sha256, "qualification review source hash"
    )
    checklist = _object(value["checklist"], "qualification review.checklist")
    _exact_keys(
        checklist, set(QUALIFICATION_REVIEW_CHECKS), "qualification review.checklist"
    )
    if any(checklist[check] is not True for check in QUALIFICATION_REVIEW_CHECKS):
        raise DirectionalDataError("qualification review checklist is incomplete")
    if value["verdict"] != "accept" or value["findings"] != []:
        raise DirectionalDataError("qualification review is not accepted")
    return value


def validate_qualification_release_metadata(
    root: Path | str,
    *,
    contracts: DirectionalContracts,
) -> Mapping[str, Any]:
    release_root = Path(root)
    manifest = _load_json(
        _safe_file(release_root, "manifest.json"),
        "qualification manifest",
    )
    _exact_keys(
        manifest,
        {
            "schema",
            "set_id",
            "task_contract",
            "decision_contract",
            "family_namespace",
            "access",
            "source",
            "files",
        },
        "qualification manifest",
    )
    _literal(
        manifest["schema"],
        QUALIFICATION_MANIFEST_SCHEMA,
        "qualification manifest.schema",
    )
    _literal(manifest["set_id"], QUALIFICATION_SET_ID, "qualification manifest.set_id")
    _literal(manifest["task_contract"], ACCEPTED_TASK, "qualification manifest.task")
    _literal(
        manifest["decision_contract"],
        _decision_identity(contracts.design),
        "qualification manifest.decision_contract",
    )
    _literal(
        manifest["family_namespace"],
        contracts.design["qualification_set"]["family_namespace"],
        "qualification manifest.family_namespace",
    )
    _literal(
        manifest["access"],
        contracts.design["qualification_set"]["access"],
        "qualification manifest.access",
    )
    files = _object(manifest["files"], "qualification manifest.files")
    _exact_keys(
        files,
        {"candidates", "pairs", "family_lineage", "coverage", "blind_review"},
        "qualification manifest.files",
    )
    expected_files = {
        "candidates": ("sealed/candidates.jsonl", 200),
        "pairs": ("sealed/pairs.jsonl", 100),
        "family_lineage": ("family-lineage.jsonl", 50),
        "coverage": ("coverage.json", None),
        "blind_review": ("blind-review.json", None),
    }
    for name, (path, rows) in expected_files.items():
        binding = _object(files[name], f"qualification manifest.files.{name}")
        _literal(
            binding.get("path"),
            path,
            f"qualification manifest.files.{name}.path",
        )
        _literal(
            binding.get("rows"),
            rows,
            f"qualification manifest.files.{name}.rows",
        )
        _read_bound_bytes(release_root, binding)
    coverage = _load_json(
        _safe_file(release_root, files["coverage"]["path"]),
        "qualification coverage",
    )
    _validate_qualification_coverage(coverage, contracts)
    lineage = _read_bound_jsonl(release_root, files["family_lineage"])
    _validate_qualification_lineage(lineage, contracts)
    source = _object(manifest["source"], "qualification manifest.source")
    _exact_keys(
        source,
        {
            "owner_role",
            "source_sha256",
            "reviewer_role",
            "review_sha256",
            "verdict",
        },
        "qualification manifest.source",
    )
    _literal(
        source["owner_role"],
        contracts.design["qualification_set"]["owner_role"],
        "qualification manifest owner",
    )
    _literal(
        source["reviewer_role"],
        contracts.design["qualification_set"]["reviewer_role"],
        "qualification manifest reviewer",
    )
    _sha256(source["source_sha256"], "qualification manifest source hash")
    _sha256(source["review_sha256"], "qualification manifest review hash")
    _literal(
        source["review_sha256"],
        files["blind_review"]["sha256"],
        "qualification manifest frozen review hash",
    )
    _literal(source["verdict"], "accept", "qualification manifest verdict")
    frozen_review = _load_json(
        _safe_file(release_root, files["blind_review"]["path"]),
        "qualification frozen review",
    )
    _exact_keys(
        frozen_review,
        {
            "schema",
            "set_id",
            "reviewer_role",
            "source_sha256",
            "verdict",
            "findings",
            "checklist",
        },
        "qualification frozen review",
    )
    _literal(
        frozen_review["schema"],
        QUALIFICATION_REVIEW_SCHEMA,
        "qualification frozen review.schema",
    )
    _literal(
        frozen_review["set_id"],
        QUALIFICATION_SET_ID,
        "qualification frozen review.set_id",
    )
    _literal(
        frozen_review["reviewer_role"],
        source["reviewer_role"],
        "qualification frozen review.reviewer_role",
    )
    _literal(
        frozen_review["source_sha256"],
        source["source_sha256"],
        "qualification frozen review.source_sha256",
    )
    _literal(
        frozen_review["verdict"],
        "accept",
        "qualification frozen review.verdict",
    )
    _literal(
        frozen_review["findings"],
        [],
        "qualification frozen review.findings",
    )
    frozen_checklist = _object(
        frozen_review["checklist"],
        "qualification frozen review.checklist",
    )
    _exact_keys(
        frozen_checklist,
        set(QUALIFICATION_REVIEW_CHECKS),
        "qualification frozen review.checklist",
    )
    if any(
        frozen_checklist[check] is not True for check in QUALIFICATION_REVIEW_CHECKS
    ):
        raise DirectionalDataError("qualification frozen review is incomplete")
    _validate_frozen_contract_copies(release_root, contracts)
    identity = _load_json(
        _safe_file(release_root, "release-identity.json"),
        "qualification release identity",
    )
    _validate_qualification_release_identity(
        identity,
        release_root,
        contracts,
    )
    return manifest


def _load_base_development(
    design: Mapping[str, Any],
    repo_root: Path,
) -> tuple[
    SuccessorRelease,
    dict[str, tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]]],
]:
    base = design["base_release"]
    root = repo_root / base["root"]
    _literal(
        sha256_file(root / "manifest.json"),
        base["manifest_sha256"],
        "base manifest hash",
    )
    _literal(
        sha256_file(root / "release-identity.json"),
        base["release_identity_sha256"],
        "base release identity hash",
    )
    manifest = _load_json(root / "manifest.json", "base manifest")
    _literal(
        manifest["splits"]["test"],
        {
            "candidates": {
                "path": "splits/test/candidates.jsonl",
                "sha256": base["sealed_auxiliary_holdout"]["candidates_sha256"],
                "rows": 27,
            },
            "pairs": {
                "path": "splits/test/pairs.jsonl",
                "sha256": base["sealed_auxiliary_holdout"]["pairs_sha256"],
                "rows": 12,
            },
        },
        "sealed auxiliary holdout metadata",
    )
    release = SuccessorRelease.open(
        root,
        expected_accepted_commit=ACCEPTED_IMPLEMENTATION_COMMIT,
        repo_root=repo_root,
    )
    train = release.load_train()
    validation = release.load_validation()
    splits = {
        "train": (
            tuple(_plain_json(row) for row in train.candidates),
            tuple(_plain_json(row) for row in train.pairs),
        ),
        "validation": (
            tuple(_plain_json(row) for row in validation.candidates),
            tuple(_plain_json(row) for row in validation.pairs),
        ),
    }
    for split in DEVELOPMENT_SPLITS:
        expected = base["development_splits"][split]
        _literal(
            manifest["splits"][split]["candidates"]["sha256"],
            expected["candidates_sha256"],
            f"base {split} candidate hash",
        )
        _literal(
            manifest["splits"][split]["pairs"]["sha256"],
            expected["pairs_sha256"],
            f"base {split} pair hash",
        )
    return release, splits


def _apply_development_patches(
    base_splits: Mapping[
        str, tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
    ],
    patches: Sequence[ValidatedPatch],
    design: Mapping[str, Any],
    *,
    repo_root: Path,
) -> tuple[
    dict[str, tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]],
    Mapping[str, Any],
]:
    replacements: dict[str, Mapping[str, Any]] = {}
    tags_by_split: dict[str, Counter[str]] = {
        split: Counter() for split in DEVELOPMENT_SPLITS
    }
    patch_counts: Counter[str] = Counter()
    for patch in patches:
        for replacement in patch.replacements:
            candidate_id = replacement["candidate_id"]
            if candidate_id in replacements:
                raise DirectionalDataError("development patches overlap candidate_id")
            replacements[candidate_id] = replacement["candidate"]
            tags_by_split[replacement["split"]].update(
                replacement["counterexample_tags"]
            )
            patch_counts[patch.module_id] += 1
    result: dict[str, tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]] = {}
    all_candidates: list[Mapping[str, Any]] = []
    candidate_groups: dict[str, str] = {}
    for split in DEVELOPMENT_SPLITS:
        candidates = [
            copy.deepcopy(replacements.get(row["candidate_id"], row))
            for row in base_splits[split][0]
        ]
        pairs = [copy.deepcopy(row) for row in base_splits[split][1]]
        try:
            validate_split(split, candidates, pairs, repo_root=repo_root)
        except SuccessorDataError as exc:
            raise DirectionalDataError(f"patched {split}: {exc}") from exc
        result[split] = (candidates, pairs)
        all_candidates.extend(candidates)
        candidate_groups.update(
            {row["candidate_id"]: row["group_id"] for row in candidates}
        )
    if set(replacements) - {row["candidate_id"] for row in all_candidates}:
        raise DirectionalDataError("a development replacement was not applied")
    try:
        reject_exact_duplicates(all_candidates)
        near_edges = find_near_duplicate_edges(all_candidates, threshold=0.94)
    except TrainingDataError as exc:
        raise DirectionalDataError(str(exc)) from exc
    if any(
        candidate_groups[edge.left_candidate_id]
        != candidate_groups[edge.right_candidate_id]
        for edge in near_edges
    ):
        raise DirectionalDataError(
            "development release has cross-group near duplicates"
        )
    auc = {split: _scope_length_auc(result[split][0]) for split in DEVELOPMENT_SPLITS}
    maximums = design["development_release"]["shortcut_diagnostics"][
        "scope_length_auc_maximum"
    ]
    for split in DEVELOPMENT_SPLITS:
        if auc[split] > maximums[split]:
            raise DirectionalDataError(
                f"{split} scope length AUC remains above the design maximum: {auc[split]:.6f}"
            )
    commentary_hits = [
        row["candidate_id"]
        for row in all_candidates
        if any(cue in _candidate_text(row).casefold() for cue in _COMMENTARY_CUES)
    ]
    if commentary_hits:
        raise DirectionalDataError(
            "development release retains commentary cues: " + ", ".join(commentary_hits)
        )
    honest = {}
    for split in DEVELOPMENT_SPLITS:
        split_rows = result[split][0]
        honest[split] = {
            "fail_with_absolute_cue": sum(
                row["labels"]["honest_uncertainty"] == "FAIL" and _has_honest_cue(row)
                for row in split_rows
            ),
            "fail_without_absolute_cue": sum(
                row["labels"]["honest_uncertainty"] == "FAIL"
                and not _has_honest_cue(row)
                for row in split_rows
            ),
            "pass_with_absolute_cue": sum(
                row["labels"]["honest_uncertainty"] == "PASS" and _has_honest_cue(row)
                for row in split_rows
            ),
            "pass_without_absolute_cue": sum(
                row["labels"]["honest_uncertainty"] == "PASS"
                and not _has_honest_cue(row)
                for row in split_rows
            ),
        }
    return result, {
        "schema": "rondo-publication-critic-directional-diagnostics@v1",
        "patched_candidates": dict(sorted(patch_counts.items())),
        "counterexample_tags": {
            split: dict(sorted(tags_by_split[split].items()))
            for split in DEVELOPMENT_SPLITS
        },
        "honest_absolute_cue_matrix": honest,
        "scope_length_auc": auc,
        "commentary_cue_hits": 0,
        "exact_duplicates": 0,
        "cross_group_near_duplicates": 0,
    }


def _write_qualification_release(
    root: Path,
    source: ValidatedQualificationSource,
    review: Mapping[str, Any],
    *,
    review_path: Path,
    review_sha256: str,
    contracts: DirectionalContracts,
) -> Mapping[str, Any]:
    _write_jsonl(root / "sealed/candidates.jsonl", source.candidates)
    _write_jsonl(root / "sealed/pairs.jsonl", source.pairs)
    _write_jsonl(root / "family-lineage.jsonl", source.lineage)
    _write_json(root / "coverage.json", source.coverage)
    _copy_bytes(review_path, root / "blind-review.json")
    files = {
        "candidates": _binding(
            root / "sealed/candidates.jsonl", "sealed/candidates.jsonl"
        ),
        "pairs": _binding(root / "sealed/pairs.jsonl", "sealed/pairs.jsonl"),
        "family_lineage": _binding(
            root / "family-lineage.jsonl", "family-lineage.jsonl"
        ),
        "coverage": _binding(root / "coverage.json", "coverage.json"),
        "blind_review": _binding(root / "blind-review.json", "blind-review.json"),
    }
    manifest = {
        "schema": QUALIFICATION_MANIFEST_SCHEMA,
        "set_id": QUALIFICATION_SET_ID,
        "task_contract": ACCEPTED_TASK,
        "decision_contract": _decision_identity(contracts.design),
        "family_namespace": source.family_namespace,
        "access": contracts.design["qualification_set"]["access"],
        "source": {
            "owner_role": source.owner_role,
            "source_sha256": source.source_sha256,
            "reviewer_role": review["reviewer_role"],
            "review_sha256": review_sha256,
            "verdict": review["verdict"],
        },
        "files": files,
    }
    _write_json(root / "manifest.json", manifest)
    _copy_bytes(
        contracts.repo_root / DESIGN_PATH,
        root / "design-lock.json",
    )
    _copy_bytes(
        contracts.repo_root / CONFIG_PATH,
        root / "generation-config.json",
    )
    _write_text(
        root / "QUALIFICATION_CARD.md",
        "# Publication Critic qualification set v1\n\n"
        "This sealed, family-lineage-isolated set is unavailable to training, "
        "validation, and decision selection. It may be released only by the "
        "separately authorized qualification work package.\n",
    )
    identity = {
        "schema": "rondo-publication-critic-qualification-set-identity@v1",
        "set_id": QUALIFICATION_SET_ID,
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "design_lock_sha256": contracts.design_sha256,
        "generation_config_sha256": contracts.config_sha256,
        "qualification_card_sha256": sha256_file(root / "QUALIFICATION_CARD.md"),
    }
    _write_json(root / "release-identity.json", identity)
    return manifest


def _write_development_release(
    root: Path,
    *,
    base_release: SuccessorRelease,
    splits: Mapping[
        str, tuple[Sequence[Mapping[str, Any]], Sequence[Mapping[str, Any]]]
    ],
    diagnostics: Mapping[str, Any],
    patch_records: Mapping[str, Any],
    patch_artifacts: Mapping[str, tuple[Path, Path]],
    qualification_manifest_sha256: str,
    contracts: DirectionalContracts,
) -> Mapping[str, Any]:
    del base_release
    split_bindings: dict[str, Any] = {}
    for split in DEVELOPMENT_SPLITS:
        candidate_relative = f"splits/{split}/candidates.jsonl"
        pair_relative = f"splits/{split}/pairs.jsonl"
        _write_jsonl(root / candidate_relative, splits[split][0])
        _write_jsonl(root / pair_relative, splits[split][1])
        split_bindings[split] = {
            "candidates": _binding(root / candidate_relative, candidate_relative),
            "pairs": _binding(root / pair_relative, pair_relative),
        }
    _write_json(root / "shortcut-diagnostics.json", diagnostics)
    frozen_patch_records = copy.deepcopy(patch_records)
    for module_id in MODULE_IDS:
        source_path, review_path = patch_artifacts[module_id]
        source_relative = f"module-freeze/{module_id}/patch.json"
        review_relative = f"module-freeze/{module_id}/review.json"
        _copy_bytes(source_path, root / source_relative)
        _copy_bytes(review_path, root / review_relative)
        frozen_patch_records[module_id]["source"] = _binding(
            root / source_relative,
            source_relative,
        )
        frozen_patch_records[module_id]["review"] = _binding(
            root / review_relative,
            review_relative,
        )
    _write_json(root / "patch-records.json", frozen_patch_records)
    manifest = {
        "schema": DEVELOPMENT_MANIFEST_SCHEMA,
        "dataset_revision": DEVELOPMENT_REVISION,
        "task_contract": ACCEPTED_TASK,
        "decision_contract": _decision_identity(contracts.design),
        "base_release": {
            "revision": contracts.design["base_release"]["revision"],
            "manifest_sha256": contracts.design["base_release"]["manifest_sha256"],
            "development_splits_only": True,
        },
        "splits": split_bindings,
        "holdout_policy": {
            "v9_auxiliary": contracts.design["base_release"][
                "sealed_auxiliary_holdout"
            ],
            "qualification_set_id": QUALIFICATION_SET_ID,
            "qualification_manifest_sha256": qualification_manifest_sha256,
            "test_entrypoint": "absent",
        },
    }
    _write_json(root / "manifest.json", manifest)
    _copy_bytes(contracts.repo_root / DESIGN_PATH, root / "design-lock.json")
    _copy_bytes(contracts.repo_root / CONFIG_PATH, root / "generation-config.json")
    _write_text(
        root / "DATA_CARD.md",
        "# Publication Critic development data v10\n\n"
        "This development-only successor preserves v9 as an immutable auxiliary "
        "holdout, applies original-owner and original-reviewer train/validation "
        "counterexamples, and exposes no test entrypoint.\n",
    )
    identity = {
        "schema": "rondo-publication-critic-development-release-identity@v1",
        "dataset_revision": DEVELOPMENT_REVISION,
        "manifest_sha256": sha256_file(root / "manifest.json"),
        "design_lock_sha256": contracts.design_sha256,
        "generation_config_sha256": contracts.config_sha256,
        "data_card_sha256": sha256_file(root / "DATA_CARD.md"),
        "shortcut_diagnostics_sha256": sha256_file(root / "shortcut-diagnostics.json"),
        "patch_records_sha256": sha256_file(root / "patch-records.json"),
    }
    _write_json(root / "release-identity.json", identity)
    return manifest


def _validate_design(value: Mapping[str, Any], repo_root: Path) -> None:
    _exact_keys(
        value,
        {
            "schema",
            "accepted_task",
            "decision_implementation",
            "remediation_implementation",
            "base_release",
            "development_release",
            "qualification_set",
        },
        "directional design",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-directional-remediation-design@v1",
        "directional design.schema",
    )
    accepted = _object(value["accepted_task"], "directional design.accepted_task")
    _literal(
        accepted,
        {
            **ACCEPTED_TASK,
            "accepted_implementation_bundle_sha256": ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256,
        },
        "directional accepted task",
    )
    decision = _object(
        value["decision_implementation"],
        "directional decision implementation",
    )
    _validate_decision_implementation(decision, repo_root)
    remediation = _object(
        value["remediation_implementation"],
        "directional remediation implementation",
    )
    _validate_remediation_implementation(remediation, repo_root)
    base = _object(value["base_release"], "directional base release")
    _exact_keys(
        base,
        {
            "revision",
            "root",
            "manifest_sha256",
            "release_identity_sha256",
            "development_splits",
            "sealed_auxiliary_holdout",
        },
        "directional base release",
    )
    _literal(base["revision"], "publication-critic-v9", "directional base revision")
    _literal(base["root"], "training/publication-critic-v9", "directional base root")
    _sha256(base["manifest_sha256"], "directional base manifest hash")
    _sha256(
        base["release_identity_sha256"],
        "directional base release identity hash",
    )
    development_splits = _object(
        base["development_splits"],
        "directional base development splits",
    )
    _exact_keys(
        development_splits,
        set(DEVELOPMENT_SPLITS),
        "directional base development splits",
    )
    for split in DEVELOPMENT_SPLITS:
        split_binding = _object(
            development_splits[split],
            f"directional base {split}",
        )
        _exact_keys(
            split_binding,
            {"candidates_sha256", "pairs_sha256"},
            f"directional base {split}",
        )
        _sha256(
            split_binding["candidates_sha256"],
            f"directional base {split} candidate hash",
        )
        _sha256(
            split_binding["pairs_sha256"],
            f"directional base {split} pair hash",
        )
    auxiliary = _object(
        base["sealed_auxiliary_holdout"],
        "directional sealed auxiliary holdout",
    )
    _exact_keys(
        auxiliary,
        {"candidates_sha256", "pairs_sha256", "policy"},
        "directional sealed auxiliary holdout",
    )
    _sha256(
        auxiliary["candidates_sha256"],
        "directional auxiliary candidate hash",
    )
    _sha256(auxiliary["pairs_sha256"], "directional auxiliary pair hash")
    _literal(
        auxiliary["policy"],
        "metadata_and_hash_only; never copied, loaded, patched, or used for decision selection",
        "sealed auxiliary holdout policy",
    )
    development = _object(value["development_release"], "development design")
    _exact_keys(
        development,
        {
            "revision",
            "physical_splits",
            "test_entrypoint",
            "module_ids",
            "reviewer_roles",
            "allowed_counterexample_tags",
            "minimum_tags_per_module",
            "shortcut_diagnostics",
            "formal_output",
        },
        "development design",
    )
    _literal(development["revision"], DEVELOPMENT_REVISION, "development revision")
    _literal(
        development["physical_splits"],
        list(DEVELOPMENT_SPLITS),
        "development physical splits",
    )
    _literal(development["test_entrypoint"], "absent", "development test entrypoint")
    _literal(development["module_ids"], list(MODULE_IDS), "development module ids")
    reviewer_roles = _object(
        development["reviewer_roles"],
        "development reviewer roles",
    )
    _exact_keys(reviewer_roles, set(MODULE_IDS), "development reviewer roles")
    for module_id, reviewer_role in reviewer_roles.items():
        _identifier(reviewer_role, f"development reviewer role {module_id}")
    allowed_tags = development["allowed_counterexample_tags"]
    if (
        not isinstance(allowed_tags, list)
        or len(allowed_tags) != len(COUNTEREXAMPLE_TAGS)
        or set(allowed_tags) != COUNTEREXAMPLE_TAGS
    ):
        raise DirectionalDataError("development counterexample tags differ")
    minimums = _object(
        development["minimum_tags_per_module"],
        "development tag minimums",
    )
    _exact_keys(minimums, set(DEVELOPMENT_SPLITS), "development tag minimums")
    expected_minimum_tags = COUNTEREXAMPLE_TAGS - {"natural_multi_defect"}
    for split in DEVELOPMENT_SPLITS:
        split_minimums = _object(minimums[split], f"development {split} minimums")
        _exact_keys(
            split_minimums,
            expected_minimum_tags,
            f"development {split} minimums",
        )
        expected_minimum = 2 if split == "train" else 1
        if any(value != expected_minimum for value in split_minimums.values()):
            raise DirectionalDataError(f"development {split} minimum differs")
    diagnostics = _object(
        development["shortcut_diagnostics"],
        "development shortcut diagnostics",
    )
    _exact_keys(
        diagnostics,
        {
            "honest_cues_are_diagnostic_only",
            "scope_length_auc_maximum",
            "replacement_commentary_cues",
            "exact_and_cross_group_near_duplicates",
        },
        "development shortcut diagnostics",
    )
    _literal(
        diagnostics["honest_cues_are_diagnostic_only"],
        True,
        "development honest diagnostic policy",
    )
    _literal(
        diagnostics["replacement_commentary_cues"],
        "reject",
        "development commentary policy",
    )
    _literal(
        diagnostics["exact_and_cross_group_near_duplicates"],
        "reject",
        "development duplicate policy",
    )
    auc_maximum = _object(
        diagnostics["scope_length_auc_maximum"],
        "development scope AUC maximum",
    )
    _exact_keys(
        auc_maximum,
        set(DEVELOPMENT_SPLITS),
        "development scope AUC maximum",
    )
    if any(
        isinstance(limit, bool)
        or not isinstance(limit, (int, float))
        or not 0.5 <= limit < 1.0
        for limit in auc_maximum.values()
    ):
        raise DirectionalDataError("development scope AUC maximum differs")
    _literal(
        development["formal_output"],
        "training/publication-critic-v10",
        "development formal output",
    )
    qualification = _object(value["qualification_set"], "qualification design")
    _exact_keys(
        qualification,
        {
            "set_id",
            "owner_role",
            "reviewer_role",
            "family_namespace",
            "groups",
            "candidates_per_group",
            "pairs_per_group",
            "boundary_targets_per_dimension",
            "required_candidate_keys",
            "required_pair_kinds",
            "development_near_duplicate_threshold",
            "shortcut_diagnostics",
            "access",
            "formal_output",
        },
        "qualification design",
    )
    _literal(qualification["set_id"], QUALIFICATION_SET_ID, "qualification set id")
    _literal(
        qualification["owner_role"],
        "plan098-test-only-qualification-owner",
        "qualification owner role",
    )
    _literal(
        qualification["reviewer_role"],
        "plan098-test-only-qualification-blind-reviewer",
        "qualification reviewer role",
    )
    _literal(
        qualification["family_namespace"],
        "pcq1-independent",
        "qualification family namespace",
    )
    _literal(qualification["groups"], 50, "qualification group count")
    _literal(
        qualification["candidates_per_group"], 4, "qualification candidate group size"
    )
    _literal(qualification["pairs_per_group"], 2, "qualification pair group size")
    _literal(
        qualification["boundary_targets_per_dimension"],
        10,
        "qualification target count",
    )
    _literal(
        qualification["required_candidate_keys"],
        list(QUALIFICATION_CANDIDATE_TAGS),
        "qualification candidate keys",
    )
    _literal(
        qualification["required_pair_kinds"],
        ["boundary", "soft_only_invariance"],
        "qualification pair kinds",
    )
    threshold = qualification["development_near_duplicate_threshold"]
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not 0.9 <= threshold < 1.0
    ):
        raise DirectionalDataError("qualification duplicate threshold differs")
    qualification_diagnostics = _object(
        qualification["shortcut_diagnostics"],
        "qualification shortcut diagnostics",
    )
    _exact_keys(
        qualification_diagnostics,
        {"dimension_length_auc_maximum", "honest_cues_are_diagnostic_only"},
        "qualification shortcut diagnostics",
    )
    length_maximum = qualification_diagnostics["dimension_length_auc_maximum"]
    if (
        isinstance(length_maximum, bool)
        or not isinstance(length_maximum, (int, float))
        or not 0.5 <= length_maximum < 1.0
    ):
        raise DirectionalDataError("qualification length AUC maximum differs")
    _literal(
        qualification_diagnostics["honest_cues_are_diagnostic_only"],
        True,
        "qualification honest diagnostic policy",
    )
    _literal(
        qualification["access"],
        "sealed_until_work_package_4; never training, validation, or decision selection",
        "qualification access policy",
    )
    _literal(
        qualification["formal_output"],
        "training/publication-critic-qualification-v1",
        "qualification formal output",
    )


def _validate_config(
    value: Mapping[str, Any],
    design: Mapping[str, Any],
    design_sha256: str,
) -> None:
    del design
    _exact_keys(
        value,
        {
            "schema",
            "design_lock",
            "ignored_root",
            "development_patches",
            "qualification_source",
            "qualification_review",
            "development_output",
            "qualification_output",
            "runtime",
        },
        "directional config",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-directional-remediation-config@v1",
        "directional config.schema",
    )
    _literal(
        value["design_lock"],
        {"path": DESIGN_PATH.as_posix(), "sha256": design_sha256},
        "directional config.design_lock",
    )
    _literal(
        value["ignored_root"],
        "/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098",
        "directional config.ignored_root",
    )
    bindings = value["development_patches"]
    if not isinstance(bindings, list) or [
        item["module_id"] for item in bindings
    ] != list(MODULE_IDS):
        raise DirectionalDataError("directional patch bindings differ")
    for binding in bindings:
        _exact_keys(
            binding, {"module_id", "source", "review"}, "directional patch binding"
        )
        _safe_relative(binding["source"], "directional patch source")
        _safe_relative(binding["review"], "directional patch review")
    _safe_relative(value["qualification_source"], "qualification source path")
    _safe_relative(value["qualification_review"], "qualification review path")
    _literal(
        value["development_output"],
        "training/publication-critic-v10",
        "directional development output",
    )
    _literal(
        value["qualification_output"],
        "training/publication-critic-qualification-v1",
        "directional qualification output",
    )
    _literal(
        value["runtime"],
        "eval/rondo_eval/publication_critic/directional_data.py",
        "directional runtime",
    )


def _validate_decision_implementation(
    value: Mapping[str, Any], repo_root: Path
) -> None:
    _exact_keys(
        value,
        {"commit", "algorithm", "components", "bundle_sha256"},
        "directional decision implementation",
    )
    _literal(
        value["commit"],
        DECISION_IMPLEMENTATION_COMMIT,
        "decision implementation commit",
    )
    _literal(
        value["algorithm"],
        "sha256-canonical-component-list-v1",
        "decision implementation algorithm",
    )
    components = value["components"]
    if not isinstance(components, list):
        raise DirectionalDataError("decision implementation components differ")
    _literal(
        [item["path"] for item in components],
        list(DECISION_IMPLEMENTATION_COMPONENT_PATHS),
        "decision implementation paths",
    )
    _literal(
        value["bundle_sha256"],
        DECISION_IMPLEMENTATION_BUNDLE_SHA256,
        "decision implementation bundle",
    )
    actual = decision_implementation_identity(repo_root)
    _literal(
        {
            "algorithm": value["algorithm"],
            "components": components,
            "bundle_sha256": value["bundle_sha256"],
        },
        actual,
        "decision implementation identity",
    )
    _literal(
        decision_contract_sha256(repo_root),
        components[0]["sha256"],
        "decision authority identity",
    )


def _validate_remediation_implementation(
    value: Mapping[str, Any],
    repo_root: Path,
) -> None:
    _exact_keys(
        value,
        {"commit", "algorithm", "components", "bundle_sha256"},
        "directional remediation implementation",
    )
    _git_commit(value["commit"], "directional remediation implementation.commit")
    _literal(
        value["algorithm"],
        "sha256-canonical-component-list-v1",
        "directional remediation implementation.algorithm",
    )
    components = value["components"]
    if not isinstance(components, list):
        raise DirectionalDataError(
            "directional remediation implementation.components differs"
        )
    _literal(
        [component.get("path") for component in components],
        ["eval/rondo_eval/publication_critic/directional_data.py"],
        "directional remediation implementation paths",
    )
    for component in components:
        _exact_keys(
            component,
            {"path", "sha256"},
            "directional remediation implementation component",
        )
        path = _safe_repo_file(repo_root, component["path"])
        _literal(
            component["sha256"],
            sha256_file(path),
            f"directional remediation component {component['path']}",
        )
    actual_bundle = hashlib.sha256(canonical_json_bytes(components)).hexdigest()
    _literal(
        value["bundle_sha256"],
        actual_bundle,
        "directional remediation implementation.bundle_sha256",
    )


def _validate_development_manifest(value: Mapping[str, Any], repo_root: Path) -> None:
    contracts = load_directional_contracts(repo_root)
    design = contracts.design
    _exact_keys(
        value,
        {
            "schema",
            "dataset_revision",
            "task_contract",
            "decision_contract",
            "base_release",
            "splits",
            "holdout_policy",
        },
        "development manifest",
    )
    _literal(
        value["schema"], DEVELOPMENT_MANIFEST_SCHEMA, "development manifest.schema"
    )
    _literal(
        value["dataset_revision"], DEVELOPMENT_REVISION, "development manifest.revision"
    )
    _literal(value["task_contract"], ACCEPTED_TASK, "development manifest.task")
    _literal(
        value["decision_contract"],
        _decision_identity(design),
        "development manifest.decision",
    )
    _literal(
        value["base_release"],
        {
            "revision": design["base_release"]["revision"],
            "manifest_sha256": design["base_release"]["manifest_sha256"],
            "development_splits_only": True,
        },
        "development manifest.base_release",
    )
    splits = _object(value["splits"], "development manifest.splits")
    _exact_keys(splits, set(DEVELOPMENT_SPLITS), "development manifest.splits")
    for split in DEVELOPMENT_SPLITS:
        binding = _object(splits[split], f"development manifest {split}")
        _exact_keys(binding, {"candidates", "pairs"}, f"development manifest {split}")
        for kind in ("candidates", "pairs"):
            file_binding = _object(
                binding[kind],
                f"development manifest {split}.{kind}",
            )
            _read_bound_bytes(Path("."), file_binding, validate_path_only=True)
            _literal(
                file_binding["path"],
                f"splits/{split}/{kind}.jsonl",
                f"development manifest {split}.{kind}.path",
            )
    holdout = _object(value["holdout_policy"], "development manifest.holdout_policy")
    _exact_keys(
        holdout,
        {
            "v9_auxiliary",
            "qualification_set_id",
            "qualification_manifest_sha256",
            "test_entrypoint",
        },
        "development manifest.holdout_policy",
    )
    _literal(
        holdout["v9_auxiliary"],
        design["base_release"]["sealed_auxiliary_holdout"],
        "development manifest v9 auxiliary holdout",
    )
    _literal(
        holdout["qualification_set_id"],
        QUALIFICATION_SET_ID,
        "development manifest qualification set",
    )
    _sha256(
        holdout["qualification_manifest_sha256"],
        "development manifest qualification hash",
    )
    _literal(
        holdout["test_entrypoint"],
        "absent",
        "development holdout test entrypoint",
    )


def _validate_frozen_contract_copies(
    release_root: Path,
    contracts: DirectionalContracts,
) -> None:
    _literal(
        sha256_file(_safe_file(release_root, "design-lock.json")),
        contracts.design_sha256,
        "frozen directional design hash",
    )
    _literal(
        sha256_file(_safe_file(release_root, "generation-config.json")),
        contracts.config_sha256,
        "frozen directional config hash",
    )


def _validate_development_release_identity(
    value: Mapping[str, Any],
    release_root: Path,
    contracts: DirectionalContracts,
) -> None:
    _exact_keys(
        value,
        {
            "schema",
            "dataset_revision",
            "manifest_sha256",
            "design_lock_sha256",
            "generation_config_sha256",
            "data_card_sha256",
            "shortcut_diagnostics_sha256",
            "patch_records_sha256",
        },
        "development release identity",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-development-release-identity@v1",
        "development release identity.schema",
    )
    _literal(
        value["dataset_revision"],
        DEVELOPMENT_REVISION,
        "development release identity.revision",
    )
    expected_hashes = {
        "manifest_sha256": sha256_file(_safe_file(release_root, "manifest.json")),
        "design_lock_sha256": contracts.design_sha256,
        "generation_config_sha256": contracts.config_sha256,
        "data_card_sha256": sha256_file(_safe_file(release_root, "DATA_CARD.md")),
        "shortcut_diagnostics_sha256": sha256_file(
            _safe_file(release_root, "shortcut-diagnostics.json")
        ),
        "patch_records_sha256": sha256_file(
            _safe_file(release_root, "patch-records.json")
        ),
    }
    for field, expected in expected_hashes.items():
        _literal(value[field], expected, f"development release identity.{field}")


def _validate_frozen_patch_records(
    release_root: Path,
    contracts: DirectionalContracts,
) -> None:
    records = _load_json(
        _safe_file(release_root, "patch-records.json"),
        "development patch records",
    )
    _exact_keys(records, set(MODULE_IDS), "development patch records")
    reviewer_roles = contracts.design["development_release"]["reviewer_roles"]
    for module_id in MODULE_IDS:
        record = _object(records[module_id], f"development patch record {module_id}")
        _exact_keys(
            record,
            {
                "owner_role",
                "source_sha256",
                "review_sha256",
                "reviewer_role",
                "verdict",
                "replacements",
                "source",
                "review",
            },
            f"development patch record {module_id}",
        )
        _literal(
            record["owner_role"],
            f"plan098-module-owner-{module_id}",
            f"development patch record {module_id}.owner_role",
        )
        _literal(
            record["reviewer_role"],
            reviewer_roles[module_id],
            f"development patch record {module_id}.reviewer_role",
        )
        _literal(
            record["verdict"],
            "accept",
            f"development patch record {module_id}.verdict",
        )
        if (
            isinstance(record["replacements"], bool)
            or not isinstance(record["replacements"], int)
            or record["replacements"] < 1
        ):
            raise DirectionalDataError(
                f"development patch record {module_id}.replacements differs"
            )
        source = _read_bound_bytes(release_root, record["source"])
        review = _read_bound_bytes(release_root, record["review"])
        _literal(
            record["source_sha256"],
            sha256_file(source),
            f"development patch record {module_id}.source_sha256",
        )
        _literal(
            record["review_sha256"],
            sha256_file(review),
            f"development patch record {module_id}.review_sha256",
        )


def _validate_qualification_release_identity(
    value: Mapping[str, Any],
    release_root: Path,
    contracts: DirectionalContracts,
) -> None:
    _exact_keys(
        value,
        {
            "schema",
            "set_id",
            "manifest_sha256",
            "design_lock_sha256",
            "generation_config_sha256",
            "qualification_card_sha256",
        },
        "qualification release identity",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-qualification-set-identity@v1",
        "qualification release identity.schema",
    )
    _literal(
        value["set_id"],
        QUALIFICATION_SET_ID,
        "qualification release identity.set_id",
    )
    expected_hashes = {
        "manifest_sha256": sha256_file(_safe_file(release_root, "manifest.json")),
        "design_lock_sha256": contracts.design_sha256,
        "generation_config_sha256": contracts.config_sha256,
        "qualification_card_sha256": sha256_file(
            _safe_file(release_root, "QUALIFICATION_CARD.md")
        ),
    }
    for field, expected in expected_hashes.items():
        _literal(value[field], expected, f"qualification release identity.{field}")


def _validate_qualification_coverage(
    value: Mapping[str, Any],
    contracts: DirectionalContracts,
) -> None:
    _exact_keys(
        value,
        {
            "schema",
            "groups",
            "candidates",
            "pairs",
            "boundary_targets",
            "context_groups",
            "verdicts",
            "dimension_fail",
            "family_triples",
            "scenario_families",
            "template_families",
            "cross_group_near_duplicates",
            "development_near_duplicates",
            "candidate_length_range",
            "dimension_length_auc",
            "honest_absolute_cue_matrix",
        },
        "qualification coverage",
    )
    _literal(
        value["schema"],
        "rondo-publication-critic-qualification-coverage@v1",
        "qualification coverage.schema",
    )
    design = contracts.design["qualification_set"]
    _literal(value["groups"], design["groups"], "qualification coverage.groups")
    _literal(
        value["candidates"],
        design["groups"] * design["candidates_per_group"],
        "qualification coverage.candidates",
    )
    _literal(
        value["pairs"],
        design["groups"] * design["pairs_per_group"],
        "qualification coverage.pairs",
    )
    _literal(
        value["boundary_targets"],
        {
            dimension: design["boundary_targets_per_dimension"]
            for dimension in sorted(HARD_DIMENSIONS)
        },
        "qualification coverage.boundary_targets",
    )
    _literal(
        value["context_groups"],
        {
            "existing_event_available": 17,
            "existing_event_unavailable": 16,
            "new_event": 17,
        },
        "qualification coverage.context_groups",
    )
    _literal(
        value["verdicts"],
        {"PASS": 100, "REWRITE": 100},
        "qualification coverage.verdicts",
    )
    _literal(
        value["family_triples"],
        design["groups"],
        "qualification coverage.family_triples",
    )
    _literal(
        value["scenario_families"],
        design["groups"],
        "qualification coverage.scenario_families",
    )
    _literal(
        value["template_families"],
        design["groups"],
        "qualification coverage.template_families",
    )
    _literal(
        value["cross_group_near_duplicates"],
        0,
        "qualification coverage.cross_group_near_duplicates",
    )
    _literal(
        value["development_near_duplicates"],
        0,
        "qualification coverage.development_near_duplicates",
    )
    dimension_fail = _object(
        value["dimension_fail"],
        "qualification coverage.dimension_fail",
    )
    _exact_keys(
        dimension_fail,
        set(HARD_DIMENSIONS),
        "qualification coverage.dimension_fail",
    )
    if any(
        isinstance(count, bool) or not isinstance(count, int) or count < 10
        for count in dimension_fail.values()
    ):
        raise DirectionalDataError("qualification coverage dimension support differs")
    auc = _object(
        value["dimension_length_auc"],
        "qualification coverage.dimension_length_auc",
    )
    _exact_keys(
        auc, set(HARD_DIMENSIONS), "qualification coverage.dimension_length_auc"
    )
    maximum = design["shortcut_diagnostics"]["dimension_length_auc_maximum"]
    if any(
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not 0.5 <= score <= maximum
        for score in auc.values()
    ):
        raise DirectionalDataError("qualification coverage length AUC differs")
    cue_matrix = _object(
        value["honest_absolute_cue_matrix"],
        "qualification coverage.honest_absolute_cue_matrix",
    )
    _exact_keys(
        cue_matrix,
        {
            "fail_with_absolute_cue",
            "fail_without_absolute_cue",
            "pass_with_absolute_cue",
            "pass_without_absolute_cue",
        },
        "qualification coverage.honest_absolute_cue_matrix",
    )
    if (
        any(
            isinstance(count, bool) or not isinstance(count, int) or count < 0
            for count in cue_matrix.values()
        )
        or sum(cue_matrix.values()) != value["candidates"]
    ):
        raise DirectionalDataError("qualification coverage honest cue matrix differs")
    for field in ("candidate_length_range",):
        _object(value[field], f"qualification coverage.{field}")


def _validate_qualification_lineage(
    rows: Sequence[Mapping[str, Any]],
    contracts: DirectionalContracts,
) -> None:
    design = contracts.design["qualification_set"]
    if len(rows) != design["groups"]:
        raise DirectionalDataError("qualification lineage row count differs")
    triples: set[tuple[str, str, str]] = set()
    scenarios: set[str] = set()
    templates: set[str] = set()
    for index, row_value in enumerate(rows, start=1):
        row = _object(row_value, "qualification lineage row")
        _exact_keys(
            row,
            {"group_id", "source_family", "scenario_family", "template_family"},
            "qualification lineage row",
        )
        _literal(
            row["group_id"],
            f"pcq1-group-{index:03d}",
            "qualification lineage group order",
        )
        triple = tuple(
            _identifier(row[field], f"qualification lineage {field}")
            for field in ("source_family", "scenario_family", "template_family")
        )
        if any(
            not family.startswith(f"{design['family_namespace']}-") for family in triple
        ):
            raise DirectionalDataError("qualification lineage namespace differs")
        triples.add(triple)
        scenarios.add(triple[1])
        templates.add(triple[2])
    if (
        len(triples) != design["groups"]
        or len(scenarios) != design["groups"]
        or len(templates) != design["groups"]
    ):
        raise DirectionalDataError("qualification lineage isolation differs")


def _decision_identity(design: Mapping[str, Any]) -> Mapping[str, Any]:
    implementation = design["decision_implementation"]
    return {
        "name": DECISION_CONTRACT_NAME,
        "version": DECISION_CONTRACT_VERSION,
        "authority_path": DECISION_CONTRACT_AUTHORITY.as_posix(),
        "content_sha256": implementation["components"][0]["sha256"],
        "accepted_implementation_commit": implementation["commit"],
        "accepted_implementation_bundle_sha256": implementation["bundle_sha256"],
    }


def _validate_replacement_tags(
    candidate: Mapping[str, Any], tags: Sequence[str]
) -> None:
    labels = candidate["labels"]
    if "honest_subtle_fail" in tags and labels["honest_uncertainty"] != "FAIL":
        raise DirectionalDataError("honest_subtle_fail label differs")
    if (
        "honest_supported_absolute_pass" in tags
        and labels["honest_uncertainty"] != "PASS"
    ):
        raise DirectionalDataError("honest_supported_absolute_pass label differs")
    if "scope_short_confused_fail" in tags and labels["scope_and_signal"] != "FAIL":
        raise DirectionalDataError("scope_short_confused_fail label differs")
    if "scope_long_clear_pass" in tags and labels["scope_and_signal"] != "PASS":
        raise DirectionalDataError("scope_long_clear_pass label differs")
    if (
        "natural_multi_defect" in tags
        and sum(labels[dimension] == "FAIL" for dimension in HARD_DIMENSIONS) < 2
    ):
        raise DirectionalDataError("natural_multi_defect labels differ")


def _without_candidate_text(value: Mapping[str, Any]) -> Mapping[str, Any]:
    result = copy.deepcopy(value)
    result["packet"]["candidate"] = None
    result["continuity_label_basis"] = None
    return result


def _scope_length_auc(rows: Sequence[Mapping[str, Any]]) -> float:
    failures = [
        _candidate_length(row)
        for row in rows
        if row["labels"]["scope_and_signal"] == "FAIL"
    ]
    passes = [
        _candidate_length(row)
        for row in rows
        if row["labels"]["scope_and_signal"] == "PASS"
    ]
    if not failures or not passes:
        raise DirectionalDataError("scope length AUC lacks both labels")
    return _ordered_length_auc(failures, passes)


def _dimension_length_separability(
    rows: Sequence[Mapping[str, Any]],
    dimension: str,
) -> float:
    failures = [
        _candidate_length(row) for row in rows if row["labels"][dimension] == "FAIL"
    ]
    non_failures = [
        _candidate_length(row) for row in rows if row["labels"][dimension] != "FAIL"
    ]
    if not failures or not non_failures:
        raise DirectionalDataError(
            f"qualification {dimension} length AUC lacks both labels"
        )
    auc = _ordered_length_auc(failures, non_failures)
    return max(auc, 1.0 - auc)


def _ordered_length_auc(left: Sequence[int], right: Sequence[int]) -> float:
    wins = sum(left_value > right_value for left_value in left for right_value in right)
    ties = sum(
        left_value == right_value for left_value in left for right_value in right
    )
    return (wins + 0.5 * ties) / (len(left) * len(right))


def _has_honest_cue(row: Mapping[str, Any]) -> bool:
    text = _candidate_text(row).casefold()
    return any(
        re.search(rf"\b{re.escape(cue)}\b", text) is not None
        for cue in _HONEST_ABSOLUTE_CUES
    )


def _candidate_text(row: Mapping[str, Any]) -> str:
    candidate = row["packet"]["candidate"]
    return "\n".join(
        (
            str(row["packet"]["local_scope"]["title"]),
            str(candidate["summary"]),
            str(candidate.get("handoff") or ""),
        )
    )


def _candidate_length(row: Mapping[str, Any]) -> int:
    return len(_candidate_text(row))


def _context_bucket(context: Mapping[str, Any]) -> str:
    if context.get("target_kind") == "new_event":
        return "new_event"
    continuity = _object(context.get("continuity"), "qualification continuity")
    state = continuity.get("state")
    if state not in {"available", "unavailable"}:
        raise DirectionalDataError("qualification context continuity state differs")
    return f"existing_event_{state}"


def _binding(path: Path, relative: str) -> dict[str, Any]:
    rows = None
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            rows = sum(1 for _ in handle)
    return {
        "path": relative,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "rows": rows,
    }


def _read_bound_jsonl(
    root: Path, binding: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    path = _read_bound_bytes(root, binding)
    try:
        rows = [
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DirectionalDataError("bound JSONL is invalid") from exc
    if len(rows) != binding["rows"] or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise DirectionalDataError("bound JSONL rows differ")
    return rows


def _read_bound_bytes(
    root: Path,
    binding: Mapping[str, Any],
    *,
    validate_path_only: bool = False,
) -> Path:
    value = _object(binding, "file binding")
    _exact_keys(value, {"path", "sha256", "bytes", "rows"}, "file binding")
    relative = _safe_relative(value["path"], "file binding.path")
    _sha256(value["sha256"], "file binding.sha256")
    if (
        isinstance(value["bytes"], bool)
        or not isinstance(value["bytes"], int)
        or value["bytes"] < 0
    ):
        raise DirectionalDataError("file binding bytes differ")
    if value["rows"] is not None and (
        isinstance(value["rows"], bool)
        or not isinstance(value["rows"], int)
        or value["rows"] < 0
    ):
        raise DirectionalDataError("file binding rows differ")
    path = root / relative
    if validate_path_only:
        return path
    if not path.is_file() or path.is_symlink():
        raise DirectionalDataError("bound file is missing or unsafe")
    if path.stat().st_size != value["bytes"] or sha256_file(path) != value["sha256"]:
        raise DirectionalDataError("bound file identity drifted")
    return path


def _load_json(path: Path, where: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise DirectionalDataError(f"{where} is missing or unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DirectionalDataError(f"{where} is invalid JSON") from exc
    return _object(value, where)


def _safe_file(root: Path, relative: str) -> Path:
    safe = _safe_relative(relative, "release path")
    current = root.resolve()
    for part in Path(safe).parts:
        current = current / part
        if current.is_symlink():
            raise DirectionalDataError(f"release path contains a symlink: {relative}")
    if not current.is_file():
        raise DirectionalDataError(f"release file is missing: {relative}")
    return current


def _safe_workspace_file(root: Path, relative: str) -> Path:
    safe = _safe_relative(relative, "workspace path")
    current = root.resolve()
    for part in Path(safe).parts:
        current = current / part
        if current.is_symlink():
            raise DirectionalDataError(f"workspace path contains a symlink: {relative}")
    if not current.is_file():
        raise DirectionalDataError(f"workspace input is missing: {relative}")
    return current


def _safe_repo_file(root: Path, relative: str) -> Path:
    safe = _safe_relative(relative, "repository path")
    current = root.resolve()
    for part in Path(safe).parts:
        current = current / part
        if current.is_symlink():
            raise DirectionalDataError(
                f"repository path contains a symlink: {relative}"
            )
    if not current.is_file():
        raise DirectionalDataError(f"repository file is missing: {relative}")
    return current


def _safe_relative(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise DirectionalDataError(f"{where} must be a relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise DirectionalDataError(f"{where} is unsafe")
    return value


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
        raise DirectionalDataError(f"frozen source is missing or unsafe: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(source.read_bytes())


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise DirectionalDataError(f"{where} must be an object")
    return value


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        raise DirectionalDataError(f"{where} keys differ")


def _literal(value: Any, expected: Any, where: str) -> None:
    if value != expected or isinstance(value, bool) != isinstance(expected, bool):
        raise DirectionalDataError(f"{where} differs")


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise DirectionalDataError(f"{where} is not a bounded identifier")
    return value


def _sha256(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise DirectionalDataError(f"{where} is not a SHA-256")
    return value


def _git_commit(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _GIT_COMMIT.fullmatch(value):
        raise DirectionalDataError(f"{where} is not a full git commit")
    return value
