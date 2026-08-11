"""Source-bound minimal model catalog projection for frozen Codex bundles."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .api_budget_proxy import _atomic_private_json


_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_MAX_SOURCE_CATALOG_BYTES = 4 * 1024 * 1024


class FrozenModelCatalogError(ValueError):
    """Raised when a frozen bundle cannot receive a trustworthy model catalog."""


@dataclass(frozen=True)
class FrozenModelCatalogProjection:
    source_commit: str
    main_model: str
    guardian_model: str
    sha256: str
    _encoded: bytes

    def to_dict(self) -> dict[str, object]:
        value = json.loads(self._encoded)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise FrozenModelCatalogError("projected frozen model catalog is invalid")
        return value

    def write_private(self, path: Path) -> None:
        if path.exists() or path.is_symlink():
            raise FrozenModelCatalogError("frozen model catalog output already exists")
        _atomic_private_json(path, self.to_dict())
        path.chmod(0o400)
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.sha256:
            raise FrozenModelCatalogError("written frozen model catalog digest differs")


def _catalog_with_auto_review_override(
    value: object,
    *,
    main_model: str,
    guardian_model: str,
) -> dict[str, object]:
    if not _MODEL_NAME.fullmatch(main_model) or not _MODEL_NAME.fullmatch(guardian_model):
        raise FrozenModelCatalogError("selected frozen model name is invalid")
    models = value.get("models") if isinstance(value, dict) else None
    if not isinstance(models, list):
        raise FrozenModelCatalogError("frozen model catalog is invalid")
    selected: list[dict[str, object]] = []
    for slug in dict.fromkeys((main_model, guardian_model)):
        matches = [
            model
            for model in models
            if isinstance(model, dict) and model.get("slug") == slug
        ]
        if len(matches) != 1:
            raise FrozenModelCatalogError("selected model is absent from frozen catalog")
        selected.append(json.loads(json.dumps(matches[0])))
    selected[0]["auto_review_model_override"] = guardian_model
    return {"models": selected}


def load_frozen_model_catalog(
    common_root: Path,
    *,
    source_commit: str,
    main_model: str,
    guardian_model: str,
    _run: Callable[..., Any] = subprocess.run,
) -> FrozenModelCatalogProjection:
    """Load exact frozen source metadata and project only the selected models."""

    if not isinstance(source_commit, str) or not _COMMIT.fullmatch(source_commit):
        raise FrozenModelCatalogError("frozen bundle source commit is invalid")
    source_root = common_root / "codex-source-code"
    if source_root.is_symlink() or not source_root.is_dir():
        raise FrozenModelCatalogError("frozen Codex source catalog is unavailable")
    try:
        completed = _run(
            ("git", "-C", str(source_root), "rev-parse", "HEAD"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrozenModelCatalogError(
            "frozen Codex source identity is unavailable"
        ) from exc
    if completed.returncode != 0 or completed.stdout.strip() != source_commit:
        raise FrozenModelCatalogError(
            "frozen Codex source differs from its binary manifest"
        )
    try:
        completed = _run(
            (
                "git",
                "-C",
                str(source_root),
                "show",
                f"{source_commit}:codex-rs/models-manager/models.json",
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        raw = completed.stdout
        if completed.returncode != 0 or not isinstance(raw, bytes):
            raise FrozenModelCatalogError("frozen model catalog blob is unavailable")
        if not raw or len(raw) > _MAX_SOURCE_CATALOG_BYTES:
            raise FrozenModelCatalogError("frozen model catalog exceeds the size limit")
        value = json.loads(raw)
    except (OSError, subprocess.TimeoutExpired, UnicodeError, json.JSONDecodeError) as exc:
        raise FrozenModelCatalogError("frozen model catalog is invalid") from exc
    catalog = _catalog_with_auto_review_override(
        value,
        main_model=main_model,
        guardian_model=guardian_model,
    )
    encoded = (
        json.dumps(catalog, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return FrozenModelCatalogProjection(
        source_commit=source_commit,
        main_model=main_model,
        guardian_model=guardian_model,
        sha256=hashlib.sha256(encoded).hexdigest(),
        _encoded=encoded,
    )
