"""Strict physically split release consumer for the Publication Critic successor task."""

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from .contract import PublicationCriticContractError
from .contract import _load_json
from .contract import _validate_no_supervision
from .contract import _validate_packet
from .contract import _validate_product_limits
from .render import build_messages
from .successor_task import HARD_DIMENSIONS
from .successor_task import SuccessorTaskError
from .successor_task import TASK_AUTHORITY
from .successor_task import TASK_NAME
from .successor_task import TASK_VERSION
from .successor_task import load_task_projection
from .successor_task import task_content_sha256
from .successor_task import validate_labels
from .successor_task import validate_pair_labels


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_SCHEMA = "rondo-publication-critic-successor-release-manifest@v1"
CANDIDATE_SCHEMA = "rondo-publication-critic-successor-candidate@v1"
PAIR_SCHEMA = "rondo-publication-critic-successor-pair@v1"
RUBRIC_PATH = Path("eval/templates/publication-critic/qualification-rubric-v2.md")
INPUT_CONTRACT_PATH = Path("eval/templates/publication-critic/input-contract-v3.md")
RENDER_CONTRACT_PATH = Path("eval/templates/publication-critic/render-contract-v4.json")
SPLITS = ("train", "validation", "test")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class SuccessorDataError(ValueError):
    """A successor release, candidate, pair, or access path is invalid."""


@dataclass(frozen=True)
class SuccessorSplit:
    name: str
    candidates: tuple[Mapping[str, Any], ...]
    pairs: tuple[Mapping[str, Any], ...]
    rubric: str

    def model_inputs(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "candidate_id": row["candidate_id"],
                "messages": build_messages(row["packet"], self.rubric),
            }
            for row in self.candidates
        )


@dataclass(frozen=True)
class SuccessorRelease:
    root: Path
    manifest: Mapping[str, Any]
    repo_root: Path
    rubric: str

    @classmethod
    def open(
        cls,
        root: Path | str,
        *,
        expected_accepted_commit: str,
        repo_root: Path | str = REPO_ROOT,
    ) -> "SuccessorRelease":
        release_root = Path(root)
        repository = Path(repo_root)
        manifest = _read_json_object(
            _safe_file(release_root, "manifest.json"),
            "manifest.json",
        )
        _validate_manifest(
            manifest,
            expected_accepted_commit=expected_accepted_commit,
            expected_content_sha256=task_content_sha256(repository),
        )
        rubric = _load_successor_input(repository)
        return cls(
            root=release_root,
            manifest=_freeze(manifest),
            repo_root=repository,
            rubric=rubric,
        )

    def load_train(self) -> SuccessorSplit:
        """Open and validate only the physically separate train assets."""

        return self._load_split("train")

    def load_validation(self) -> SuccessorSplit:
        """Open validation only through an explicit non-training entrypoint."""

        return self._load_split("validation")

    def _load_split(self, split: str) -> SuccessorSplit:
        binding = self.manifest["splits"][split]
        candidates = _read_bound_jsonl(self.root, binding["candidates"])
        pairs = _read_bound_jsonl(self.root, binding["pairs"])
        validate_split(
            split,
            candidates,
            pairs,
            repo_root=self.repo_root,
        )
        return SuccessorSplit(
            name=split,
            candidates=tuple(_freeze(row) for row in candidates),
            pairs=tuple(_freeze(row) for row in pairs),
            rubric=self.rubric,
        )


def validate_candidate_row(
    row: Mapping[str, Any],
    *,
    repo_root: Path | str = REPO_ROOT,
) -> None:
    candidate = _object(row, "candidate row")
    _exact_keys(
        candidate,
        {
            "schema",
            "candidate_id",
            "group_id",
            "packet",
            "labels",
            "continuity_label_basis",
        },
        "candidate row",
    )
    _literal(candidate["schema"], CANDIDATE_SCHEMA, "candidate row.schema")
    _identifier(candidate["candidate_id"], "candidate row.candidate_id")
    _identifier(candidate["group_id"], "candidate row.group_id")
    packet = _object(candidate["packet"], "candidate row.packet")
    qualification = _object(packet.get("qualification"), "candidate row.packet.qualification")
    _exact_keys(
        qualification,
        {"packet_schema", "rubric"},
        "candidate row.packet.qualification",
    )
    _named_revision(
        qualification["packet_schema"],
        name="rondo-publication-packet",
        revision="v1",
        where="candidate row.packet.qualification.packet_schema",
    )
    _named_revision(
        qualification["rubric"],
        name="rondo-publication-qualification",
        revision="v2",
        where="candidate row.packet.qualification.rubric",
    )
    compatibility_packet = copy.deepcopy(packet)
    compatibility_packet["qualification"]["rubric"]["revision"] = "v1"
    try:
        root = Path(repo_root)
        limits = _load_json(
            root / "eval/templates/publication-critic/product-packet-limits-v1.json"
        )
        _validate_product_limits(limits)
        _validate_no_supervision(compatibility_packet, "candidate row.packet")
        _validate_packet(
            compatibility_packet,
            "candidate row.packet",
            limits,
        )
    except PublicationCriticContractError as exc:
        raise SuccessorDataError(str(exc)) from exc
    labels = validate_labels(_object(candidate["labels"], "candidate row.labels"))
    basis = _object(candidate["continuity_label_basis"], "candidate row.continuity_label_basis")
    _exact_keys(
        basis,
        {"type", "field", "quote"},
        "candidate row.continuity_label_basis",
    )
    expected_type = (
        "model_visible_complete_claim"
        if labels["conditional_continuity"] == "N/A"
        else "model_visible_unfinished_or_not_closed"
    )
    _literal(basis["type"], expected_type, "candidate row.continuity_label_basis.type")
    field = basis["field"]
    if field not in {"candidate.summary", "candidate.handoff"}:
        raise SuccessorDataError("continuity basis field is not model-visible candidate text")
    candidate_field = field.removeprefix("candidate.")
    visible_text = packet["candidate"][candidate_field]
    quote = basis["quote"]
    if (
        not isinstance(quote, str)
        or not quote.strip()
        or quote != quote.strip()
        or len(quote) > 240
    ):
        raise SuccessorDataError("continuity basis quote must be bounded canonical text")
    if not isinstance(visible_text, str) or quote not in visible_text:
        raise SuccessorDataError("continuity basis quote is absent from its model-visible field")


def validate_pair_row(row: Mapping[str, Any]) -> None:
    pair = _object(row, "pair row")
    _exact_keys(
        pair,
        {
            "schema",
            "pair_id",
            "group_id",
            "kind",
            "left_candidate_id",
            "right_candidate_id",
            "target_dimension",
            "soft_change",
        },
        "pair row",
    )
    _literal(pair["schema"], PAIR_SCHEMA, "pair row.schema")
    for field in ("pair_id", "group_id", "left_candidate_id", "right_candidate_id"):
        _identifier(pair[field], f"pair row.{field}")
    if pair["left_candidate_id"] == pair["right_candidate_id"]:
        raise SuccessorDataError("pair endpoints must be distinct")
    kind = pair["kind"]
    if kind not in {"boundary", "soft_only_invariance"}:
        raise SuccessorDataError("pair row.kind is invalid")
    target = pair["target_dimension"]
    if kind == "boundary" and target not in HARD_DIMENSIONS:
        raise SuccessorDataError("boundary target dimension is invalid")
    if kind == "boundary" and pair["soft_change"] is not None:
        raise SuccessorDataError("boundary soft_change must be null")
    if kind == "soft_only_invariance" and target is not None:
        raise SuccessorDataError("soft-only invariance cannot name a target dimension")
    if kind == "soft_only_invariance":
        change = pair["soft_change"]
        if not isinstance(change, str) or not change.strip() or len(change) > 500:
            raise SuccessorDataError("soft-only invariance requires a bounded soft_change")


def validate_split(
    split: str,
    candidate_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    *,
    repo_root: Path | str = REPO_ROOT,
) -> None:
    if split not in SPLITS:
        raise SuccessorDataError("split is invalid")
    candidates: dict[str, Mapping[str, Any]] = {}
    for row in candidate_rows:
        validate_candidate_row(row, repo_root=repo_root)
        candidate_id = row["candidate_id"]
        if candidate_id in candidates:
            raise SuccessorDataError(f"duplicate candidate_id: {candidate_id}")
        candidates[candidate_id] = row
    pairs: set[str] = set()
    for row in pair_rows:
        validate_pair_row(row)
        pair_id = row["pair_id"]
        if pair_id in pairs:
            raise SuccessorDataError(f"duplicate pair_id: {pair_id}")
        pairs.add(pair_id)
        left = candidates.get(row["left_candidate_id"])
        right = candidates.get(row["right_candidate_id"])
        if left is None or right is None:
            raise SuccessorDataError(f"pair {pair_id} references a missing split endpoint")
        if left["group_id"] != right["group_id"] or row["group_id"] != left["group_id"]:
            raise SuccessorDataError(f"pair {pair_id} crosses group identity")
        left_context = {
            key: value for key, value in left["packet"].items() if key != "candidate"
        }
        right_context = {
            key: value for key, value in right["packet"].items() if key != "candidate"
        }
        if left_context != right_context:
            raise SuccessorDataError(f"pair {pair_id} changes non-candidate public context")
        if left["packet"]["candidate"] == right["packet"]["candidate"]:
            raise SuccessorDataError(f"pair {pair_id} endpoints have identical candidates")
        try:
            validate_pair_labels(
                row["kind"],
                left["labels"],
                right["labels"],
                target_dimension=row["target_dimension"],
            )
        except SuccessorTaskError as exc:
            raise SuccessorDataError(f"pair {pair_id}: {exc}") from exc


def _validate_manifest(
    value: Mapping[str, Any],
    *,
    expected_accepted_commit: str,
    expected_content_sha256: str,
) -> None:
    manifest = _object(value, "manifest")
    _exact_keys(manifest, {"schema", "task_contract", "splits"}, "manifest")
    _literal(manifest["schema"], MANIFEST_SCHEMA, "manifest.schema")
    task = _object(manifest["task_contract"], "manifest.task_contract")
    _exact_keys(
        task,
        {"name", "version", "content_sha256", "accepted_commit"},
        "manifest.task_contract",
    )
    _literal(task["name"], TASK_NAME, "manifest.task_contract.name")
    _literal(task["version"], TASK_VERSION, "manifest.task_contract.version")
    _literal(
        task["content_sha256"],
        expected_content_sha256,
        "manifest.task_contract.content_sha256",
    )
    if not isinstance(expected_accepted_commit, str) or not _COMMIT.fullmatch(
        expected_accepted_commit
    ):
        raise SuccessorDataError("expected accepted commit must be a full lowercase Git commit")
    _literal(
        task["accepted_commit"],
        expected_accepted_commit,
        "manifest.task_contract.accepted_commit",
    )
    splits = _object(manifest["splits"], "manifest.splits")
    _exact_keys(splits, set(SPLITS), "manifest.splits")
    observed_paths: set[str] = set()
    for split in SPLITS:
        split_binding = _object(splits[split], f"manifest.splits.{split}")
        _exact_keys(split_binding, {"candidates", "pairs"}, f"manifest.splits.{split}")
        for kind in ("candidates", "pairs"):
            binding = _object(split_binding[kind], f"manifest.splits.{split}.{kind}")
            _exact_keys(binding, {"path", "sha256", "rows"}, f"manifest.splits.{split}.{kind}")
            path = _safe_relative(binding["path"], f"manifest.splits.{split}.{kind}.path")
            parts = Path(path).parts
            if len(parts) < 3 or parts[:2] != ("splits", split):
                raise SuccessorDataError(f"{split} {kind} path is outside its physical split")
            if path in observed_paths:
                raise SuccessorDataError("manifest reuses one file across split bindings")
            observed_paths.add(path)
            digest = binding["sha256"]
            if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
                raise SuccessorDataError(f"manifest {split} {kind} SHA-256 is invalid")
            rows = binding["rows"]
            if isinstance(rows, bool) or not isinstance(rows, int) or rows < 0:
                raise SuccessorDataError(f"manifest {split} {kind} rows is invalid")


def _load_successor_input(repo_root: Path) -> str:
    try:
        projection = load_task_projection(repo_root)
    except SuccessorTaskError as exc:
        raise SuccessorDataError("successor task projection is invalid") from exc
    task_input = projection["input"]
    _literal(
        task_input["input_contract"],
        INPUT_CONTRACT_PATH.as_posix(),
        "successor input contract path",
    )
    _literal(
        task_input["rubric"],
        RUBRIC_PATH.as_posix(),
        "successor rubric path",
    )
    _literal(
        task_input["render_contract"],
        RENDER_CONTRACT_PATH.as_posix(),
        "successor render contract path",
    )
    try:
        input_contract = (repo_root / INPUT_CONTRACT_PATH).read_text(encoding="utf-8")
        rubric = (repo_root / RUBRIC_PATH).read_text(encoding="utf-8")
        render_contract = json.loads(
            (repo_root / RENDER_CONTRACT_PATH).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuccessorDataError("successor input projection is unavailable") from exc
    if not input_contract.strip() or not rubric.strip():
        raise SuccessorDataError("successor input projection is empty")
    _validate_successor_render_contract(render_contract)
    return rubric


def _validate_successor_render_contract(value: Any) -> None:
    contract = _object(value, "successor render contract")
    _exact_keys(
        contract,
        {
            "schema_version",
            "name",
            "revision",
            "authority",
            "mechanical_predecessor",
            "messages",
            "applicability",
            "dynamic_text_encoding",
            "candidate_truncation",
            "overflow",
            "identity_binding",
        },
        "successor render contract",
    )
    _literal(contract["schema_version"], 1, "successor render contract.schema_version")
    _literal(
        contract["name"],
        "rondo-publication-critic-render",
        "successor render contract.name",
    )
    _literal(contract["revision"], "v4", "successor render contract.revision")
    _literal(
        contract["authority"],
        f"{TASK_NAME}@{TASK_VERSION}",
        "successor render contract.authority",
    )
    _literal(
        contract["mechanical_predecessor"],
        "rondo-publication-critic-render@v3",
        "successor render contract.mechanical_predecessor",
    )
    messages = _object(contract["messages"], "successor render contract.messages")
    _exact_keys(
        messages,
        {"system", "count", "user_components", "assistant_components"},
        "successor render contract.messages",
    )
    _literal(messages["system"], "absent", "successor render contract.messages.system")
    _literal(messages["count"], 2, "successor render contract.messages.count")
    if messages["user_components"] != [
        "qualification_rubric",
        "packet",
        "continuity",
        "evidence_v1",
    ] or messages["assistant_components"] != [
        "candidate.summary",
        "candidate.handoff",
    ]:
        raise SuccessorDataError("successor render components differ from the contract")
    applicability = _object(
        contract["applicability"],
        "successor render contract.applicability",
    )
    if applicability != {
        "source": "model_visible_candidate_only",
        "hidden_completion_metadata": "forbidden",
    }:
        raise SuccessorDataError("successor render applicability differs from the contract")
    _literal(
        contract["candidate_truncation"],
        "forbidden",
        "successor render contract.candidate_truncation",
    )
    _literal(
        contract["dynamic_text_encoding"],
        "json_utf8_less_than_escaped_control_token_safe",
        "successor render contract.dynamic_text_encoding",
    )
    _literal(
        contract["overflow"],
        "drop_whole_oldest_publication_then_rerender_or_typed_failure",
        "successor render contract.overflow",
    )
    identity = _object(
        contract["identity_binding"],
        "successor render contract.identity_binding",
    )
    _exact_keys(
        identity,
        {"algorithm", "components"},
        "successor render contract.identity_binding",
    )
    _literal(
        identity["algorithm"],
        "sha256_canonical_json",
        "successor render contract.identity_binding.algorithm",
    )
    if identity["components"] != [
        TASK_AUTHORITY.as_posix(),
        INPUT_CONTRACT_PATH.as_posix(),
        RUBRIC_PATH.as_posix(),
        RENDER_CONTRACT_PATH.as_posix(),
        "eval/rondo_eval/publication_critic/render.py",
    ]:
        raise SuccessorDataError("successor render identity components differ")


def _read_bound_jsonl(root: Path, binding: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    relative = binding["path"]
    path = _safe_file(root, relative)
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise SuccessorDataError(f"cannot read bound split file: {relative}") from exc
    if hashlib.sha256(content).hexdigest() != binding["sha256"]:
        raise SuccessorDataError(f"bound split file SHA-256 differs: {relative}")
    try:
        text = content.decode("utf-8")
    except UnicodeError as exc:
        raise SuccessorDataError(f"bound split file is not UTF-8: {relative}") from exc
    rows: list[Mapping[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            raise SuccessorDataError(f"blank JSONL line: {relative}:{line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SuccessorDataError(f"invalid JSONL line: {relative}:{line_number}") from exc
        rows.append(_object(value, f"{relative}:{line_number}"))
    if len(rows) != binding["rows"]:
        raise SuccessorDataError(f"bound split row count differs: {relative}")
    return rows


def _safe_file(root: Path, relative: str) -> Path:
    if not root.is_dir() or root.is_symlink():
        raise SuccessorDataError("release root is missing or unsafe")
    safe = _safe_relative(relative, "consumer path")
    current = root.resolve()
    for part in Path(safe).parts:
        current = current / part
        if current.is_symlink():
            raise SuccessorDataError(f"consumer path contains a symlink: {relative}")
    if not current.is_file():
        raise SuccessorDataError(f"consumer input is missing: {relative}")
    return current


def _safe_relative(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise SuccessorDataError(f"{where} must be a relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SuccessorDataError(f"{where} is unsafe")
    return value


def _read_json_object(path: Path, relative: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuccessorDataError(f"cannot read consumer JSON: {relative}") from exc
    return _object(value, relative)


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SuccessorDataError(f"{where} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        raise SuccessorDataError(f"{where} keys differ from the contract")


def _literal(value: Any, expected: Any, where: str) -> None:
    if value != expected or isinstance(value, bool) != isinstance(expected, bool):
        raise SuccessorDataError(f"{where} differs from the contract")


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise SuccessorDataError(f"{where} is not a bounded identifier")
    return value


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(nested) for key, nested in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(nested) for nested in value)
    return value


def _named_revision(value: Any, *, name: str, revision: str, where: str) -> None:
    identity = _object(value, where)
    _exact_keys(identity, {"name", "revision"}, where)
    _literal(identity["name"], name, f"{where}.name")
    _literal(identity["revision"], revision, f"{where}.revision")
