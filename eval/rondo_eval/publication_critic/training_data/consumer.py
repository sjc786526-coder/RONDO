"""Strict cumulative C1/C2/C3 consumer and train-only smoke bundle."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from ..contract import REPO_ROOT
from ..render import build_messages
from .contract import TrainingDataError, validate_dataset
from .freeze import verify_freeze_manifest
from .input_identity import Plan054TrainingInput, load_plan054_training_input


def build_memberships(
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    *,
    dataset_revision: str,
) -> dict[str, Any]:
    train_candidates = sorted(
        str(row["candidate_id"])
        for row in supervision_rows
        if row["proposed_split"] == "train"
    )
    split_by_candidate = {str(row["candidate_id"]): row["proposed_split"] for row in supervision_rows}
    for pair in pair_rows:
        preferred_split = split_by_candidate.get(str(pair["preferred_candidate_id"]))
        dispreferred_split = split_by_candidate.get(str(pair["dispreferred_candidate_id"]))
        if preferred_split is None or dispreferred_split is None:
            raise TrainingDataError(f"pair {pair['pair_id']} references a missing candidate")
        if preferred_split != dispreferred_split:
            raise TrainingDataError(f"pair {pair['pair_id']} crosses splits")
    boundary = sorted(
        str(pair["pair_id"])
        for pair in pair_rows
        if pair["kind"] == "boundary"
        and split_by_candidate.get(str(pair["preferred_candidate_id"])) == "train"
    )
    within = sorted(
        str(pair["pair_id"])
        for pair in pair_rows
        if pair["kind"] == "within_pass"
        and split_by_candidate.get(str(pair["preferred_candidate_id"])) == "train"
    )
    return {
        "schema_version": 1,
        "dataset_revision": dataset_revision,
        "stages": {
            "C1": {"candidate_ids": train_candidates, "pair_ids": []},
            "C2": {"candidate_ids": train_candidates, "pair_ids": boundary},
            "C3": {"candidate_ids": train_candidates, "pair_ids": [*boundary, *within]},
        },
    }


def validate_memberships(
    membership: Mapping[str, Any],
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
) -> None:
    if set(membership) != {"schema_version", "dataset_revision", "stages"} or membership["schema_version"] != 1:
        raise TrainingDataError("membership contract keys or version differ")
    stages = membership["stages"]
    if not isinstance(stages, Mapping) or set(stages) != {"C1", "C2", "C3"}:
        raise TrainingDataError("membership stages must be exactly C1/C2/C3")
    expected = build_memberships(
        supervision_rows,
        pair_rows,
        dataset_revision=str(membership["dataset_revision"]),
    )
    if membership != expected:
        raise TrainingDataError("C1/C2/C3 membership is not the required cumulative train-only set")


@dataclass(frozen=True, init=False)
class DatasetConsumer:
    packets: Mapping[str, Mapping[str, Any]]
    supervision: Mapping[str, Mapping[str, Any]]
    pairs: Mapping[str, Mapping[str, Any]]
    membership: Mapping[str, Any]
    _fixed_rubric: str = field(repr=False)
    allow_evaluation: bool = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise TypeError(
            "DatasetConsumer must be created by from_rows() or from_frozen_directory()"
        )

    @classmethod
    def from_rows(
        cls,
        packet_rows: Sequence[Mapping[str, Any]],
        supervision_rows: Sequence[Mapping[str, Any]],
        pair_rows: Sequence[Mapping[str, Any]],
        membership: Mapping[str, Any],
        *,
        repo_root: Path | str = REPO_ROOT,
        allow_evaluation: bool = False,
    ) -> "DatasetConsumer":
        verified_input = load_plan054_training_input(repo_root)
        return cls._from_rows_with_verified_input(
            packet_rows,
            supervision_rows,
            pair_rows,
            membership,
            verified_input=verified_input,
            repo_root=repo_root,
            allow_evaluation=allow_evaluation,
        )

    @classmethod
    def _from_rows_with_verified_input(
        cls,
        packet_rows: Sequence[Mapping[str, Any]],
        supervision_rows: Sequence[Mapping[str, Any]],
        pair_rows: Sequence[Mapping[str, Any]],
        membership: Mapping[str, Any],
        *,
        verified_input: Plan054TrainingInput,
        repo_root: Path | str,
        allow_evaluation: bool,
    ) -> "DatasetConsumer":
        validate_dataset(
            packet_rows,
            supervision_rows,
            pair_rows,
            repo_root=repo_root,
            final=True,
            require_review_records=False,
            require_omission_census=False,
        )
        validate_memberships(membership, supervision_rows, pair_rows)
        all_supervision = {
            str(row["candidate_id"]): row for row in supervision_rows
        }
        visible_ids = {
            candidate_id
            for candidate_id, row in all_supervision.items()
            if allow_evaluation or row["proposed_split"] == "train"
        }
        consumer = object.__new__(cls)
        object.__setattr__(
            consumer,
            "packets",
            {
                str(row["candidate_id"]): row
                for row in packet_rows
                if str(row["candidate_id"]) in visible_ids
            },
        )
        object.__setattr__(
            consumer,
            "supervision",
            {
                candidate_id: row
                for candidate_id, row in all_supervision.items()
                if candidate_id in visible_ids
            },
        )
        object.__setattr__(
            consumer,
            "pairs",
            {
                str(row["pair_id"]): row
                for row in pair_rows
                if str(row["preferred_candidate_id"]) in visible_ids
                and str(row["dispreferred_candidate_id"]) in visible_ids
            },
        )
        object.__setattr__(consumer, "membership", membership)
        object.__setattr__(consumer, "_fixed_rubric", verified_input.rubric)
        object.__setattr__(consumer, "allow_evaluation", allow_evaluation)
        return consumer

    @classmethod
    def from_frozen_directory(
        cls,
        root: Path,
        *,
        manifest_relative: str = "manifest.json",
        packets_relative: str = "packets.jsonl",
        supervision_relative: str = "supervision.jsonl",
        pairs_relative: str = "pairs.jsonl",
        membership_relative: str = "membership.json",
        repo_root: Path | str = REPO_ROOT,
        allow_evaluation: bool = False,
    ) -> "DatasetConsumer":
        verified_input = load_plan054_training_input(repo_root)
        manifest = _load_json_object(root, manifest_relative)
        verify_freeze_manifest(
            root,
            manifest,
            expected_input_identity=verified_input.input_identity,
        )
        required = {packets_relative, supervision_relative, pairs_relative, membership_relative}
        if not required <= set(manifest["files"]):
            raise TrainingDataError("freeze manifest does not bind every consumer input")
        consumer = cls._from_rows_with_verified_input(
            _load_jsonl(root, packets_relative),
            _load_jsonl(root, supervision_relative),
            _load_jsonl(root, pairs_relative),
            _load_json_object(root, membership_relative),
            verified_input=verified_input,
            repo_root=repo_root,
            allow_evaluation=allow_evaluation,
        )
        if consumer.membership["dataset_revision"] != manifest["dataset_revision"]:
            raise TrainingDataError("membership dataset revision differs from freeze manifest")
        return consumer

    def stage(self, name: str) -> dict[str, tuple[Mapping[str, Any], ...]]:
        if name not in {"C1", "C2", "C3"}:
            raise TrainingDataError("stage must be C1, C2, or C3")
        stage = self.membership["stages"][name]
        candidates = tuple(self.supervision[candidate_id] for candidate_id in stage["candidate_ids"])
        pairs = tuple(self.pairs[pair_id] for pair_id in stage["pair_ids"])
        if any(row["proposed_split"] != "train" for row in candidates):
            raise TrainingDataError("training stage reached a non-train candidate")
        return {"binary": candidates, "pairs": pairs}

    def model_inputs(self, name: str) -> tuple[dict[str, Any], ...]:
        stage = self.stage(name)
        return tuple(
            {
                "candidate_id": row["candidate_id"],
                "messages": build_messages(
                    self.packets[row["candidate_id"]]["packet"],
                    self._fixed_rubric,
                ),
            }
            for row in stage["binary"]
        )

    def evaluation_split(self, split: str) -> tuple[Mapping[str, Any], ...]:
        if not self.allow_evaluation:
            raise TrainingDataError("validation/unseen-test access requires explicit evaluation mode")
        if split not in {"validation", "unseen_test"}:
            raise TrainingDataError("evaluation split must be validation or unseen_test")
        return tuple(row for row in self.supervision.values() if row["proposed_split"] == split)


def build_train_only_smoke_bundle(
    packet_rows: Sequence[Mapping[str, Any]],
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    *,
    dataset_revision: str,
    source_hashes: Mapping[str, str],
) -> dict[str, Any]:
    supervision = {str(row["candidate_id"]): row for row in supervision_rows}
    packets = {str(row["candidate_id"]): row for row in packet_rows}
    train_pairs = [
        pair
        for pair in pair_rows
        if supervision[str(pair["preferred_candidate_id"])]["proposed_split"] == "train"
    ]
    boundary = next((pair for pair in train_pairs if pair["kind"] == "boundary"), None)
    within = next((pair for pair in train_pairs if pair["kind"] == "within_pass"), None)
    if boundary is None or within is None:
        raise TrainingDataError("smoke bundle requires one train boundary and one train within-pass pair")
    selected_ids = {
        str(boundary["preferred_candidate_id"]),
        str(boundary["dispreferred_candidate_id"]),
        str(within["preferred_candidate_id"]),
        str(within["dispreferred_candidate_id"]),
    }
    for label in ("PASS", "REWRITE"):
        candidate_id = next(
            (
                candidate_id
                for candidate_id, row in sorted(supervision.items())
                if row["proposed_split"] == "train" and row["binary_label"] == label
            ),
            None,
        )
        if candidate_id is None:
            raise TrainingDataError(f"smoke bundle lacks train {label} Binary supervision")
        selected_ids.add(candidate_id)
    selected_supervision = [supervision[candidate_id] for candidate_id in sorted(selected_ids)]
    selected_packets = [packets[candidate_id] for candidate_id in sorted(selected_ids)]
    selected_pairs = [boundary, within]
    membership = build_memberships(
        selected_supervision,
        selected_pairs,
        dataset_revision=dataset_revision,
    )
    if any(row["proposed_split"] != "train" for row in selected_supervision):
        raise TrainingDataError("smoke bundle contains a non-train candidate")
    bundle = {
        "schema_version": 1,
        "dataset_revision": dataset_revision,
        "source_hashes": dict(sorted(source_hashes.items())),
        "packets": selected_packets,
        "supervision": selected_supervision,
        "pairs": selected_pairs,
        "membership": membership,
    }
    validate_train_only_smoke_bundle(bundle)
    return bundle


def validate_train_only_smoke_bundle(
    bundle: Mapping[str, Any],
    *,
    repo_root: Path | str = REPO_ROOT,
) -> None:
    expected = {
        "schema_version",
        "dataset_revision",
        "source_hashes",
        "packets",
        "supervision",
        "pairs",
        "membership",
    }
    if set(bundle) != expected or bundle["schema_version"] != 1:
        raise TrainingDataError("train-only smoke bundle keys or version differ")
    hashes = bundle["source_hashes"]
    if not isinstance(hashes, Mapping) or not hashes:
        raise TrainingDataError("train-only smoke bundle requires source hashes")
    for name, digest in hashes.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise TrainingDataError("train-only smoke bundle source hash is invalid")
    consumer = DatasetConsumer.from_rows(
        bundle["packets"],
        bundle["supervision"],
        bundle["pairs"],
        bundle["membership"],
        repo_root=repo_root,
    )
    consumer.stage("C1")
    c2 = consumer.stage("C2")
    c3 = consumer.stage("C3")
    labels = {row["binary_label"] for row in bundle["supervision"]}
    kinds_c2 = {row["kind"] for row in c2["pairs"]}
    kinds_c3 = {row["kind"] for row in c3["pairs"]}
    if labels != {"PASS", "REWRITE"} or "boundary" not in kinds_c2 or "within_pass" not in kinds_c3:
        raise TrainingDataError("train-only smoke bundle does not cover Binary/Boundary/Within-PASS")


def _safe_relative_file(root: Path, relative: str) -> Path:
    if not root.is_dir() or root.is_symlink():
        raise TrainingDataError("consumer root is missing or unsafe")
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise TrainingDataError(f"consumer relative path is unsafe: {relative!r}")
    current = root.resolve()
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise TrainingDataError(f"consumer path contains a symlink: {relative}")
    if not current.is_file():
        raise TrainingDataError(f"consumer input is missing: {relative}")
    return current


def _load_json_object(root: Path, relative: str) -> Mapping[str, Any]:
    path = _safe_relative_file(root, relative)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingDataError(f"cannot read consumer JSON: {relative}") from exc
    if not isinstance(value, Mapping):
        raise TrainingDataError(f"consumer JSON must be an object: {relative}")
    return value


def _load_jsonl(root: Path, relative: str) -> list[Mapping[str, Any]]:
    path = _safe_relative_file(root, relative)
    rows: list[Mapping[str, Any]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                raise TrainingDataError(f"blank JSONL line: {relative}:{line_number}")
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise TrainingDataError(f"JSONL row must be an object: {relative}:{line_number}")
            rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingDataError(f"cannot read consumer JSONL: {relative}") from exc
    return rows
