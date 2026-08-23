"""Plan 054 input identity and tokenizer-only asset verification for Plan 059."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..contract import (
    REPO_ROOT,
    PublicationCriticContractError,
    load_fixed_input_contract,
)
from ..identity import IdentityError, load_json, sha256_file
from ..runner import RunnerError, verify_measurement_freeze
from .contract import TrainingDataError


_MEASUREMENT_FREEZE_RELATIVE = Path(
    "eval/manifests/publication-critic/measurement-freeze-v4.json"
)
_MODEL_LOCK_RELATIVE = Path(
    "eval/model-locks/publication-critic/"
    "skywork-reward-v2-qwen3-1.7b-e51ea3e0.json"
)
TOKENIZER_ONLY_FILES = (
    "added_tokens.json",
    "chat_template.jinja",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)


@dataclass(frozen=True)
class Plan054TrainingInput:
    """The verified Plan 054 identity material needed by Plan 059."""

    input_identity: Mapping[str, Any]
    rubric: str
    tokenizer_file_sha256: Mapping[str, str]


def load_plan054_training_input(
    repo_root: Path | str = REPO_ROOT,
) -> Plan054TrainingInput:
    """Verify the tracked Plan 054 freeze and derive the exact Plan 059 input.

    This verifies only tracked contracts.  It intentionally does not inspect a
    model snapshot or read model weights; snapshot verification is a separate
    tokenizer-only operation below.
    """

    root = Path(repo_root)
    freeze_path = root / _MEASUREMENT_FREEZE_RELATIVE
    model_lock_path = root / _MODEL_LOCK_RELATIVE
    if (
        freeze_path.is_symlink()
        or not freeze_path.is_file()
        or model_lock_path.is_symlink()
        or not model_lock_path.is_file()
    ):
        raise TrainingDataError("Plan 054 tracked identity files are missing or unsafe")
    try:
        freeze = verify_measurement_freeze(
            freeze_path,
            root,
            model_lock_path,
        )
        fixed = load_fixed_input_contract(root)
        model_lock = load_json(model_lock_path)
    except (IdentityError, PublicationCriticContractError, RunnerError) as exc:
        raise TrainingDataError("Plan 054 frozen input identity is missing or drifted") from exc

    if not isinstance(model_lock, dict):
        raise TrainingDataError("Plan 054 model lock is not an object")
    files = model_lock.get("files")
    if not isinstance(files, dict):
        raise TrainingDataError("Plan 054 model lock file inventory is missing")
    tokenizer_files: dict[str, str] = {}
    for relative in TOKENIZER_ONLY_FILES:
        digest = files.get(relative)
        if not _is_sha256(digest):
            raise TrainingDataError(
                f"Plan 054 tokenizer asset identity is invalid: {relative}"
            )
        tokenizer_files[relative] = digest

    try:
        qualification = _mapping(freeze["qualification_identity"], "qualification identity")
        model_identity = _mapping(freeze["model_identity"], "model identity")
        tokenizer_identity = _mapping(model_identity["tokenizer"], "tokenizer identity")
        scoring = _mapping(freeze["scoring_identity"], "scoring identity")
        input_template = _mapping(scoring["input_template"], "input template identity")
        window = _mapping(freeze["window_facts"], "window facts")
        render_contract = fixed.render_contract
        input_identity = {
            "packet_schema": dict(_mapping(qualification["packet_schema"], "packet schema")),
            "qualification_rubric": dict(_mapping(qualification["rubric"], "rubric identity")),
            "plan054_freeze_sha256": sha256_file(freeze_path),
            "render_contract": f"{render_contract['name']}@{render_contract['revision']}",
            "input_template_revision": _text(input_template["revision"], "input template revision"),
            "tokenizer_name": _text(tokenizer_identity["name"], "tokenizer name"),
            "tokenizer_revision": _text(tokenizer_identity["revision"], "tokenizer revision"),
            "adopted_window_tokens": freeze["adopted_window_tokens"],
            "candidate_truncation": "forbidden",
            "continuity_overflow": _text(window["overflow_policy"], "continuity overflow"),
        }
    except (KeyError, TypeError) as exc:
        raise TrainingDataError("Plan 054 frozen input identity is incomplete") from exc

    if window.get("implicit_tokenizer_truncation") is not False:
        raise TrainingDataError("Plan 054 implicit tokenizer truncation is not forbidden")
    if not isinstance(input_identity["adopted_window_tokens"], int) or isinstance(
        input_identity["adopted_window_tokens"], bool
    ):
        raise TrainingDataError("Plan 054 adopted window identity is invalid")
    if not fixed.rubric.strip():
        raise TrainingDataError("Plan 054 fixed rubric is empty")
    return Plan054TrainingInput(
        input_identity=MappingProxyType(input_identity),
        rubric=fixed.rubric,
        tokenizer_file_sha256=MappingProxyType(tokenizer_files),
    )


def verify_plan054_tokenizer_snapshot(
    snapshot: Path,
    *,
    repo_root: Path | str = REPO_ROOT,
) -> Plan054TrainingInput:
    """Verify exactly the seven tokenizer assets without touching weights."""

    verified = load_plan054_training_input(repo_root)
    candidate = Path(snapshot)
    if candidate.is_symlink():
        raise TrainingDataError("exact tokenizer snapshot root must not be a symlink")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise TrainingDataError("exact tokenizer snapshot is missing") from exc
    expected_revision = verified.input_identity["tokenizer_revision"]
    if not resolved.is_dir() or resolved.name != expected_revision:
        raise TrainingDataError("exact tokenizer snapshot revision drifted")

    try:
        cache_root = resolved.parent.parent.resolve(strict=True)
    except OSError as exc:
        raise TrainingDataError("exact tokenizer cache root is missing") from exc
    for relative in TOKENIZER_ONLY_FILES:
        logical = resolved / relative
        try:
            asset = logical.resolve(strict=True)
        except OSError as exc:
            raise TrainingDataError(f"exact tokenizer asset is missing: {relative}") from exc
        if not asset.is_relative_to(cache_root) or not asset.is_file():
            raise TrainingDataError(f"exact tokenizer asset escapes its cache: {relative}")
        if sha256_file(asset) != verified.tokenizer_file_sha256[relative]:
            raise TrainingDataError(f"exact tokenizer asset identity drifted: {relative}")
    return verified


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TrainingDataError(f"Plan 054 {where} is not an object")
    return value


def _text(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise TrainingDataError(f"Plan 054 {where} is invalid")
    return value


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
