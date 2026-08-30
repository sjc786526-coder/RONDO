"""Narrow Plan 100 loader for the frozen v10 development validation release."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..identity import canonical_json_bytes
from ..successor_task import HARD_DIMENSIONS
from .contract import derive_verdict

REPO_ROOT = Path(__file__).resolve().parents[4]
RELEASE_ROOT = Path("training/publication-critic-v10")
MANIFEST_PATH = RELEASE_ROOT / "manifest.json"
CANDIDATES_PATH = RELEASE_ROOT / "splits/validation/candidates.jsonl"
PAIRS_PATH = RELEASE_ROOT / "splits/validation/pairs.jsonl"
MANIFEST_SHA256 = "61498f2f8580eab7dda59df0e2dba9bf5700c168e33f41bfec5cbdf3bd5041a4"
CANDIDATES_SHA256 = "20c545469a3c1972e90d4c587fc114845000a2c938c21bea95e42eeb94602508"
PAIRS_SHA256 = "4b0fe7c7f8148b5c5d9b12fdfe9e2055c6b46e4c9cdb30e2058be0d13224edfd"
CANDIDATE_ROWS = 27
PAIR_ROWS = 12
CANDIDATE_BYTES = 34370
PAIR_BYTES = 4544
SYNTHETIC_PATH = Path(
    "eval/fixtures/publication-critic/plan100-synthetic-packet-v1.json"
)
SYNTHETIC_SHA256 = "4e3da1240827cc290dde7e020dd4ad0849ad0af7a8d4bc2e32133f0fedd17c10"
SYNTHETIC_BYTES = 684
COMMISSIONING_PUBLIC_ITEMS = (
    {
        "selection": "minimum_canonical_packet_bytes_then_candidate_id",
        "candidate_id": "pcv9-hard-boundaries-validation-01-qminus",
        "packet_bytes": 486,
        "packet_sha256": "f3d11525367bc1400a7531b78d89c009812bf7bd42cec75f79a7d2e43c0bbdeb",
    },
    {
        "selection": "maximum_canonical_packet_bytes_then_candidate_id",
        "candidate_id": "pcv9-continuity-context-020-qplus",
        "packet_bytes": 1241,
        "packet_sha256": "6677a5c61e0043245c95af5201a43c5851021ae6b9e13b7dc7db71365f10e2a2",
    },
)


class ValidationReleaseError(ValueError):
    """The only development validation bytes allowed for Plan 100 have drifted."""


@dataclass(frozen=True)
class PublicItem:
    candidate_id: str
    packet: Mapping[str, Any]
    packet_bytes: bytes


@dataclass(frozen=True)
class CandidateSupervision:
    candidate_id: str
    group_id: str
    labels: Mapping[str, str]
    gold_verdict: str
    continuity_label_basis: Mapping[str, str]


@dataclass(frozen=True)
class PairSupervision:
    pair_id: str
    group_id: str
    kind: str
    left_candidate_id: str
    right_candidate_id: str
    target_dimension: str | None


@dataclass(frozen=True)
class ValidationRelease:
    public_items: tuple[PublicItem, ...]
    candidate_supervision: tuple[CandidateSupervision, ...]
    pair_supervision: tuple[PairSupervision, ...]
    manifest_sha256: str = MANIFEST_SHA256
    candidates_sha256: str = CANDIDATES_SHA256
    pairs_sha256: str = PAIRS_SHA256

    def public_by_id(self) -> Mapping[str, PublicItem]:
        return MappingProxyType({item.candidate_id: item for item in self.public_items})

    def supervision_by_id(self) -> Mapping[str, CandidateSupervision]:
        return MappingProxyType(
            {item.candidate_id: item for item in self.candidate_supervision}
        )

    def commissioning_public_items(self) -> tuple[PublicItem, PublicItem]:
        """Select the frozen min/max packets without consulting supervision."""

        ordered = sorted(
            self.public_items,
            key=lambda item: (len(item.packet_bytes), item.candidate_id),
        )
        selected = (ordered[0], ordered[-1])
        for item, expected in zip(selected, COMMISSIONING_PUBLIC_ITEMS, strict=True):
            if (
                item.candidate_id != expected["candidate_id"]
                or len(item.packet_bytes) != expected["packet_bytes"]
                or hashlib.sha256(item.packet_bytes).hexdigest()
                != expected["packet_sha256"]
            ):
                raise ValidationReleaseError(
                    "commissioning public packet identity differs"
                )
        return selected


def load_validation_release(repo_root: Path | str = REPO_ROOT) -> ValidationRelease:
    """Read only the manifest and its exact 27/12 validation files."""

    root = Path(repo_root)
    manifest_bytes = _read_exact(root, MANIFEST_PATH, MANIFEST_SHA256)
    manifest = _strict_json(manifest_bytes, "manifest")
    _validate_manifest(manifest)
    candidate_bytes = _read_exact(
        root,
        CANDIDATES_PATH,
        CANDIDATES_SHA256,
        expected_bytes=CANDIDATE_BYTES,
    )
    pair_bytes = _read_exact(
        root,
        PAIRS_PATH,
        PAIRS_SHA256,
        expected_bytes=PAIR_BYTES,
    )
    candidate_rows = _read_jsonl(
        candidate_bytes, CANDIDATE_ROWS, "validation candidates"
    )
    pair_rows = _read_jsonl(pair_bytes, PAIR_ROWS, "validation pairs")
    public, supervision = _split_candidates(candidate_rows)
    pairs = _parse_pairs(pair_rows, supervision)
    release = ValidationRelease(
        public_items=public,
        candidate_supervision=supervision,
        pair_supervision=pairs,
    )
    release.commissioning_public_items()
    return release


def load_commissioning_public_items(
    repo_root: Path | str = REPO_ROOT,
) -> tuple[PublicItem, PublicItem, PublicItem]:
    """Return one fixed synthetic packet followed by the frozen public min/max pair."""

    root = Path(repo_root)
    synthetic_bytes = _read_exact(
        root,
        SYNTHETIC_PATH,
        SYNTHETIC_SHA256,
        expected_bytes=SYNTHETIC_BYTES,
    )
    packet = _strict_json(synthetic_bytes, "synthetic commissioning packet")
    release = load_validation_release(root)
    low, high = release.commissioning_public_items()
    return (
        PublicItem(
            candidate_id="plan100-synthetic-commissioning-v1",
            packet=_freeze(packet),
            packet_bytes=canonical_json_bytes(packet),
        ),
        low,
        high,
    )


def _validate_manifest(manifest: Mapping[str, Any]) -> None:
    if (
        manifest.get("schema")
        != "rondo-publication-critic-development-release-manifest@v1"
    ):
        raise ValidationReleaseError("v10 manifest schema differs")
    if manifest.get("dataset_revision") != "publication-critic-v10":
        raise ValidationReleaseError("v10 manifest revision differs")
    if manifest.get("base_release", {}).get("development_splits_only") is not True:
        raise ValidationReleaseError("v10 manifest is not development-only")
    validation = manifest.get("splits", {}).get("validation", {})
    expected = {
        "candidates": {
            "bytes": CANDIDATE_BYTES,
            "path": "splits/validation/candidates.jsonl",
            "rows": CANDIDATE_ROWS,
            "sha256": CANDIDATES_SHA256,
        },
        "pairs": {
            "bytes": PAIR_BYTES,
            "path": "splits/validation/pairs.jsonl",
            "rows": PAIR_ROWS,
            "sha256": PAIRS_SHA256,
        },
    }
    if validation != expected:
        raise ValidationReleaseError("v10 validation binding differs")


def _split_candidates(
    rows: list[Mapping[str, Any]],
) -> tuple[tuple[PublicItem, ...], tuple[CandidateSupervision, ...]]:
    public: list[PublicItem] = []
    supervision: list[CandidateSupervision] = []
    seen: set[str] = set()
    expected_keys = {
        "schema",
        "candidate_id",
        "group_id",
        "packet",
        "labels",
        "continuity_label_basis",
    }
    for row in rows:
        if set(row) != expected_keys:
            raise ValidationReleaseError("validation candidate keys differ")
        candidate_id = _identifier(row["candidate_id"], "candidate_id")
        if candidate_id in seen:
            raise ValidationReleaseError(
                f"duplicate validation candidate: {candidate_id}"
            )
        seen.add(candidate_id)
        group_id = _identifier(row["group_id"], "group_id")
        packet = _mapping(row["packet"], "packet")
        labels = _labels(row["labels"])
        basis = _string_mapping(row["continuity_label_basis"], "continuity basis")
        public.append(
            PublicItem(
                candidate_id=candidate_id,
                packet=_freeze(packet),
                packet_bytes=canonical_json_bytes(packet),
            )
        )
        supervision.append(
            CandidateSupervision(
                candidate_id=candidate_id,
                group_id=group_id,
                labels=_freeze(labels),
                gold_verdict=derive_verdict(labels),
                continuity_label_basis=_freeze(basis),
            )
        )
    return tuple(public), tuple(supervision)


def _parse_pairs(
    rows: list[Mapping[str, Any]],
    candidates: tuple[CandidateSupervision, ...],
) -> tuple[PairSupervision, ...]:
    candidate_ids = {candidate.candidate_id for candidate in candidates}
    expected_keys = {
        "schema",
        "pair_id",
        "group_id",
        "kind",
        "left_candidate_id",
        "right_candidate_id",
        "target_dimension",
        "soft_change",
    }
    pairs: list[PairSupervision] = []
    seen: set[str] = set()
    for row in rows:
        if set(row) != expected_keys:
            raise ValidationReleaseError("validation pair keys differ")
        pair_id = _identifier(row["pair_id"], "pair_id")
        if pair_id in seen:
            raise ValidationReleaseError(f"duplicate validation pair: {pair_id}")
        seen.add(pair_id)
        left = _identifier(row["left_candidate_id"], "left_candidate_id")
        right = _identifier(row["right_candidate_id"], "right_candidate_id")
        if left not in candidate_ids or right not in candidate_ids or left == right:
            raise ValidationReleaseError(
                f"invalid validation pair endpoints: {pair_id}"
            )
        kind = row["kind"]
        target = row["target_dimension"]
        if kind == "boundary":
            if target not in HARD_DIMENSIONS or row["soft_change"] is not None:
                raise ValidationReleaseError(f"invalid boundary pair: {pair_id}")
        elif kind == "soft_only_invariance":
            if target is not None or not isinstance(row["soft_change"], str):
                raise ValidationReleaseError(f"invalid invariance pair: {pair_id}")
        else:
            raise ValidationReleaseError(f"invalid validation pair kind: {pair_id}")
        pairs.append(
            PairSupervision(
                pair_id=pair_id,
                group_id=_identifier(row["group_id"], "group_id"),
                kind=kind,
                left_candidate_id=left,
                right_candidate_id=right,
                target_dimension=target,
            )
        )
    return tuple(pairs)


def _read_exact(
    repo_root: Path,
    relative: Path,
    expected_sha256: str,
    *,
    expected_bytes: int | None = None,
) -> bytes:
    path = repo_root / relative
    if not path.is_file() or path.is_symlink():
        raise ValidationReleaseError(f"release input is missing or unsafe: {relative}")
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise ValidationReleaseError(f"cannot read release input: {relative}") from exc
    if expected_bytes is not None and len(content) != expected_bytes:
        raise ValidationReleaseError(f"release byte count differs: {relative}")
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValidationReleaseError(f"release SHA-256 differs: {relative}")
    return content


def _read_jsonl(
    content: bytes, expected_rows: int, where: str
) -> list[Mapping[str, Any]]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise ValidationReleaseError(f"{where} is not UTF-8") from exc
    if len(lines) != expected_rows or any(not line for line in lines):
        raise ValidationReleaseError(f"{where} line order/count binding differs")
    return [
        _strict_json(line.encode("utf-8"), f"{where}:{index}")
        for index, line in enumerate(lines, 1)
    ]


def _strict_json(content: bytes, where: str) -> Mapping[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValidationReleaseError(f"duplicate JSON key in {where}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise ValidationReleaseError(f"non-finite JSON value in {where}: {value}")

    try:
        value = json.loads(
            content,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ValidationReleaseError(f"invalid JSON in {where}") from exc
    return _mapping(value, where)


def _labels(value: Any) -> dict[str, str]:
    labels = _mapping(value, "labels")
    if set(labels) != set(HARD_DIMENSIONS):
        raise ValidationReleaseError("validation label keys differ")
    result: dict[str, str] = {}
    for dimension in HARD_DIMENSIONS:
        label = labels[dimension]
        allowed = (
            {"PASS", "FAIL", "N/A"}
            if dimension == "conditional_continuity"
            else {"PASS", "FAIL"}
        )
        if label not in allowed:
            raise ValidationReleaseError(f"invalid validation label: {dimension}")
        result[dimension] = label
    return result


def _string_mapping(value: Any, where: str) -> dict[str, str]:
    mapping = _mapping(value, where)
    if not all(
        isinstance(key, str) and isinstance(item, str) for key, item in mapping.items()
    ):
        raise ValidationReleaseError(f"{where} must contain strings")
    return dict(mapping)


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValidationReleaseError(f"{where} must be an object")
    return value


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValidationReleaseError(f"{where} must be a bounded identifier")
    if any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789._-"
        for character in value
    ):
        raise ValidationReleaseError(f"{where} contains invalid characters")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value
