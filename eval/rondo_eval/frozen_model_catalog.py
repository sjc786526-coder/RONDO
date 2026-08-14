"""One shared model catalog artifact for both comparison sides.

The catalog is deliberately **not** bound to either binary's source commit.
Both sides must load the same bytes, so the artifact has its own identity --
a SHA-256 over the projected bytes -- and carries the provenance needed to
show that identity was derived from the right sources: the upstream and RONDO
commit/path/blob ID pair, the projection algorithm and schema version, the
main and Guardian model, and the entry that received the override.

The projection keeps every model in the frozen catalog.  Trimming it to the
selected models changes the picker-visible model list, which the agent's
``spawn_agent`` tool description enumerates, and that made the two sides'
prompts asymmetric.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .api_budget_proxy import _atomic_private_json
from .contracts import Product, product_layout
from .fair_comparison import CATALOG_PROJECTION_VERSION


_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_BLOB_ID = re.compile(r"[0-9a-f]{40}\Z")
_MAX_SOURCE_CATALOG_BYTES = 4 * 1024 * 1024

CATALOG_PROJECTION_ALGORITHM = "full_catalog_with_auto_review_override"
UPSTREAM_CATALOG_PATH = "codex-rs/models-manager/models.json"
# RONDO Local's path, kept as a module constant because every campaign frozen
# so far records it.  Use ``rondo_catalog_path`` for anything product-aware.
RONDO_CATALOG_PATH = product_layout(Product.RONDO_LOCAL).catalog_path


def rondo_catalog_path(product: Product | None) -> str:
    """Repository-relative built-in catalog blob for one RONDO product."""

    return product_layout(product).catalog_path


class FrozenModelCatalogError(ValueError):
    """Raised when the shared model catalog cannot be trusted."""


@dataclass(frozen=True)
class CatalogSource:
    """One side's origin for the catalog bytes."""

    side: str
    commit: str
    path: str
    blob_id: str

    def to_dict(self) -> dict[str, str]:
        return {
            "side": self.side,
            "commit": self.commit,
            "path": self.path,
            "blob_id": self.blob_id,
        }


@dataclass(frozen=True)
class LegacyFrozenModelCatalogProjection:
    """The pre-E-B8 Codex-only projection, kept only to replay v1--v6.

    It trimmed the catalog to the selected models, which is exactly the
    asymmetry E-B8 removes.  Nothing new may use it; it exists so frozen
    campaigns keep recomputing the digests their locks already record.
    """

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


@dataclass(frozen=True)
class FrozenModelCatalogProjection:
    sha256: str
    projection_algorithm: str
    projection_version: int
    main_model: str
    guardian_model: str
    override_target_slug: str
    model_slugs: tuple[str, ...]
    sources: tuple[CatalogSource, ...]
    _encoded: bytes

    def to_dict(self) -> dict[str, object]:
        value = json.loads(self._encoded)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise FrozenModelCatalogError("projected model catalog is invalid")
        return value

    def identity(self) -> dict[str, object]:
        """Return the mechanically checkable identity of this artifact."""

        return {
            "sha256": self.sha256,
            "projection_algorithm": self.projection_algorithm,
            "projection_version": self.projection_version,
            "main_model": self.main_model,
            "guardian_model": self.guardian_model,
            "override_target_slug": self.override_target_slug,
            "model_slugs": list(self.model_slugs),
            "sources": [item.to_dict() for item in self.sources],
        }

    def source_for(self, side: str) -> CatalogSource:
        matches = tuple(item for item in self.sources if item.side == side)
        if len(matches) != 1:
            raise FrozenModelCatalogError("catalog source provenance is ambiguous")
        return matches[0]

    def validate_identity(self, expected: object) -> None:
        """Fail closed when any recorded identity field drifted."""

        if expected != self.identity():
            raise FrozenModelCatalogError("model catalog identity drifted from the lock")

    def write_private(self, path: Path) -> None:
        if path.exists() or path.is_symlink():
            raise FrozenModelCatalogError("model catalog output already exists")
        _atomic_private_json(path, self.to_dict())
        path.chmod(0o400)
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.sha256:
            raise FrozenModelCatalogError("written model catalog digest differs")


def project_catalog_with_override(
    value: object,
    *,
    main_model: str,
    guardian_model: str,
) -> tuple[dict[str, object], str, tuple[str, ...]]:
    """Keep every frozen model and override only the target entry.

    Returns the projected catalog, the slug of the entry that received the
    override, and every slug in declaration order.
    """

    if not _MODEL_NAME.fullmatch(main_model) or not _MODEL_NAME.fullmatch(guardian_model):
        raise FrozenModelCatalogError("selected model name is invalid")
    models = value.get("models") if isinstance(value, dict) else None
    if not isinstance(models, list) or not models:
        raise FrozenModelCatalogError("frozen model catalog is invalid")
    projected = json.loads(json.dumps(value))
    entries = projected["models"]
    slugs: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("slug"), str):
            raise FrozenModelCatalogError("frozen model catalog entry is invalid")
        slugs.append(entry["slug"])
    if len(set(slugs)) != len(slugs):
        raise FrozenModelCatalogError("frozen model catalog has duplicate slugs")
    for slug in (main_model, guardian_model):
        if slugs.count(slug) != 1:
            raise FrozenModelCatalogError("selected model is absent from frozen catalog")
    target = next(entry for entry in entries if entry["slug"] == main_model)
    target["auto_review_model_override"] = guardian_model
    return projected, main_model, tuple(slugs)


def _legacy_catalog_with_auto_review_override(
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
) -> LegacyFrozenModelCatalogProjection:
    """Replay the pre-E-B8 Codex-only projection for frozen v1--v6 campaigns."""

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
                f"{source_commit}:{UPSTREAM_CATALOG_PATH}",
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
    catalog = _legacy_catalog_with_auto_review_override(
        value,
        main_model=main_model,
        guardian_model=guardian_model,
    )
    encoded = (
        json.dumps(catalog, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return LegacyFrozenModelCatalogProjection(
        source_commit=source_commit,
        main_model=main_model,
        guardian_model=guardian_model,
        sha256=hashlib.sha256(encoded).hexdigest(),
        _encoded=encoded,
    )


def _git_text(
    repo: Path,
    args: tuple[str, ...],
    *,
    failure: str,
    _run: Callable[..., Any],
) -> str:
    try:
        completed = _run(
            ("git", "-C", str(repo), *args),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrozenModelCatalogError(failure) from exc
    if completed.returncode != 0 or not isinstance(completed.stdout, str):
        raise FrozenModelCatalogError(failure)
    return completed.stdout.strip()


def _git_blob(
    repo: Path,
    spec: str,
    *,
    failure: str,
    _run: Callable[..., Any],
) -> bytes:
    try:
        completed = _run(
            ("git", "-C", str(repo), "show", spec),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FrozenModelCatalogError(failure) from exc
    raw = completed.stdout
    if completed.returncode != 0 or not isinstance(raw, bytes):
        raise FrozenModelCatalogError(failure)
    if not raw or len(raw) > _MAX_SOURCE_CATALOG_BYTES:
        raise FrozenModelCatalogError("frozen model catalog exceeds the size limit")
    return raw


def _read_source(
    repo: Path,
    *,
    side: str,
    commit: str,
    path: str,
    _run: Callable[..., Any],
) -> tuple[CatalogSource, bytes]:
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise FrozenModelCatalogError(f"{side} catalog source commit is invalid")
    if repo.is_symlink() or not repo.is_dir():
        raise FrozenModelCatalogError(f"{side} catalog source tree is unavailable")
    resolved = _git_text(
        repo,
        ("rev-parse", f"{commit}^{{commit}}"),
        failure=f"{side} catalog source commit is unavailable",
        _run=_run,
    )
    if resolved != commit:
        raise FrozenModelCatalogError(f"{side} catalog source commit is unavailable")
    blob_id = _git_text(
        repo,
        ("rev-parse", f"{commit}:{path}"),
        failure=f"{side} catalog blob is unavailable",
        _run=_run,
    )
    if not _BLOB_ID.fullmatch(blob_id):
        raise FrozenModelCatalogError(f"{side} catalog blob id is invalid")
    raw = _git_blob(
        repo,
        f"{commit}:{path}",
        failure=f"{side} catalog blob is unavailable",
        _run=_run,
    )
    return CatalogSource(side=side, commit=commit, path=path, blob_id=blob_id), raw


def load_shared_model_catalog(
    common_root: Path,
    *,
    upstream_source_commit: str,
    rondo_source_commit: str,
    main_model: str,
    guardian_model: str,
    product: Product | None = None,
    _run: Callable[..., Any] = subprocess.run,
) -> FrozenModelCatalogProjection:
    """Project one catalog artifact that both sides load byte for byte.

    Both sources are read at their own binary's source commit and must resolve
    to the same blob.  If they ever diverge there is no single artifact that is
    faithful to both built-in catalogs, so the comparison is refused rather
    than silently favouring one side.
    """

    upstream_source, upstream_raw = _read_source(
        common_root / "codex-source-code",
        side="upstream",
        commit=upstream_source_commit,
        path=UPSTREAM_CATALOG_PATH,
        _run=_run,
    )
    rondo_source, rondo_raw = _read_source(
        common_root,
        side="rondo",
        commit=rondo_source_commit,
        path=rondo_catalog_path(product),
        _run=_run,
    )
    if upstream_source.blob_id != rondo_source.blob_id or upstream_raw != rondo_raw:
        raise FrozenModelCatalogError(
            "upstream and RONDO model catalogs differ; no shared artifact exists"
        )
    try:
        value = json.loads(upstream_raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FrozenModelCatalogError("frozen model catalog is invalid") from exc
    catalog, override_target_slug, slugs = project_catalog_with_override(
        value,
        main_model=main_model,
        guardian_model=guardian_model,
    )
    encoded = (
        json.dumps(catalog, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return FrozenModelCatalogProjection(
        sha256=hashlib.sha256(encoded).hexdigest(),
        projection_algorithm=CATALOG_PROJECTION_ALGORITHM,
        projection_version=CATALOG_PROJECTION_VERSION,
        main_model=main_model,
        guardian_model=guardian_model,
        override_target_slug=override_target_slug,
        model_slugs=slugs,
        sources=(upstream_source, rondo_source),
        _encoded=encoded,
    )
