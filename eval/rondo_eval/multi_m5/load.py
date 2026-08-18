"""Load and validate the frozen Multi M-5 contract files."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts import Product, Side, TEAM_CAPABILITY_MULTI_TOML


EVAL_ROOT = Path(__file__).resolve().parents[2]
WORKTREE_ROOT = EVAL_ROOT.parent
LOCKS_DIR = EVAL_ROOT / "locks"
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_TASK_IDS = (
    "terminal-bench/db-wal-recovery",
    "terminal-bench/extract-elf",
    "terminal-bench/filter-js-from-html",
    "terminal-bench/fix-git",
    "terminal-bench/headless-terminal",
    "terminal-bench/openssl-selfsigned-cert",
    "terminal-bench/polyglot-c-py",
    "terminal-bench/sanitize-git-repo",
    "terminal-bench/sqlite-db-truncate",
    "terminal-bench/vulnerable-secret",
)
_PREDICATE_IDS = (
    "spawn_member",
    "event_with_two_versions",
    "two_authors",
    "team_route",
    "team_evidence",
    "root_resolved",
)


class M5ContractError(ValueError):
    """Raised when an M-5 lock, fixture, or on-disk bundle is not the frozen contract."""


@dataclass(frozen=True)
class WorkflowContract:
    lock_id: str
    instruction_path: Path
    instruction_sha256: str
    fixture_dir: Path
    finding_line: str
    report_filename: str
    root_model: str
    member_model: str
    root_effort: str
    timeout_seconds: int
    max_attempts: int
    max_members: int
    docker: bool
    predicate_ids: tuple[str, ...]
    override_toml: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class NondegradationContract:
    lock_id: str
    catalog_path: Path
    catalog_sha256: str
    tasks: tuple[str, ...]
    base_order: tuple[dict[str, Any], ...]
    root_model: str
    member_model: str
    root_effort: str
    provider: str
    max_effective_runs: int
    max_slot_attempts: int
    max_infra_attempts_total: int
    max_requests_per_run: int
    hard_cap_usd: str
    point_estimate_usd: str
    worst_legal_usd: str
    price_date: str
    price_source_url: str
    docker_images: tuple[str, ...]
    raw: dict[str, Any]


@dataclass(frozen=True)
class RuntimeIdentity:
    lock_id: str
    status: str
    product: str
    source_commit: str
    bundle_dir_name: str
    bundle_relpath: str
    codex_sha256: str | None
    code_mode_host_sha256: str | None
    bwrap_sha256: str | None
    manifest_sha256: str | None
    baseline: dict[str, Any]
    raw: dict[str, Any]

    @property
    def frozen(self) -> bool:
        return self.status == "frozen" and all(
            isinstance(value, str) and _SHA256.fullmatch(value)
            for value in (
                self.codex_sha256,
                self.code_mode_host_sha256,
                self.bwrap_sha256,
                self.manifest_sha256,
            )
        )


def load_workflow_contract(path: Path | None = None) -> WorkflowContract:
    lock_path = path or LOCKS_DIR / "multi-m5-workflow-v1.json"
    raw = _read_json(lock_path)
    if raw.get("schema_version") != 1 or raw.get("lock_id") != "multi-m5-workflow-v1":
        raise M5ContractError("workflow lock identity differs")
    if raw.get("carrier") != "host_codex_exec" or raw.get("docker") is not False:
        raise M5ContractError("gate 1 must be host-side without Docker")
    if raw.get("orphan_retirement_required") is not False:
        raise M5ContractError("gate 1 must not require orphan retirement")
    if raw.get("product") != Product.RONDO_MULTI.value:
        raise M5ContractError("gate 1 product must be rondo-multi")
    instruction = WORKTREE_ROOT / _relative(raw.get("instruction_path"))
    fixture = WORKTREE_ROOT / _relative(raw.get("fixture_dir"))
    _require_sha(instruction, raw.get("instruction_sha256"), "instruction")
    notes = fixture / "NOTES.md"
    _require_sha(notes, raw.get("fixture_notes_sha256"), "fixture notes")
    finding = raw.get("finding_line")
    if not isinstance(finding, str) or finding not in notes.read_text("utf-8"):
        raise M5ContractError("finding line is missing from NOTES.md")
    predicates = raw.get("collaboration_predicates")
    if not isinstance(predicates, list) or len(predicates) != len(_PREDICATE_IDS):
        raise M5ContractError("collaboration predicates differ from the frozen set")
    ids = tuple(item.get("id") for item in predicates if isinstance(item, dict))
    if ids != _PREDICATE_IDS:
        raise M5ContractError("collaboration predicate ids differ")
    capability = raw.get("team_capability")
    if not isinstance(capability, dict):
        raise M5ContractError("team capability block is missing")
    override = capability.get("override_toml")
    if override != TEAM_CAPABILITY_MULTI_TOML:
        raise M5ContractError("team capability override differs from the adapter contract")
    timeout = raw.get("timeout_seconds")
    attempts = raw.get("max_attempts")
    members = raw.get("max_members")
    if timeout != 1800 or attempts != 3 or members != 1:
        raise M5ContractError("gate 1 timeout or attempt contract differs")
    report = raw.get("report_filename")
    if report != "TEAM_REPORT.md":
        raise M5ContractError("gate 1 report filename differs")
    return WorkflowContract(
        lock_id=raw["lock_id"],
        instruction_path=instruction,
        instruction_sha256=raw["instruction_sha256"],
        fixture_dir=fixture,
        finding_line=finding,
        report_filename=report,
        root_model=_model(raw.get("root_model")),
        member_model=_model(raw.get("member_model")),
        root_effort=_effort(raw.get("root_effort")),
        timeout_seconds=timeout,
        max_attempts=attempts,
        max_members=members,
        docker=False,
        predicate_ids=ids,
        override_toml=override,
        raw=raw,
    )


def load_nondegradation_contract(path: Path | None = None) -> NondegradationContract:
    lock_path = path or LOCKS_DIR / "multi-m5-nondegradation-v1.json"
    raw = _read_json(lock_path)
    if raw.get("schema_version") != 1 or raw.get("lock_id") != "multi-m5-nondegradation-v1":
        raise M5ContractError("non-degradation lock identity differs")
    if raw.get("runner") != "light_interleaved":
        raise M5ContractError("gate 2 must use the light interleaved runner")
    catalog = WORKTREE_ROOT / _relative(raw.get("catalog_path"))
    _require_sha(catalog, raw.get("catalog_sha256"), "canary catalog")
    catalog_doc = _read_json(catalog)
    if catalog_doc.get("taskset_sha256") != raw.get("taskset_sha256"):
        raise M5ContractError("catalog taskset digest differs")
    tasks = tuple(raw.get("tasks") or ())
    if tasks != _TASK_IDS:
        raise M5ContractError("gate 2 task list differs from v4 canary catalog")
    catalog_ids = tuple(item["task_id"] for item in catalog_doc["tasks"])
    if catalog_ids != tasks:
        raise M5ContractError("gate 2 task order differs from the catalog file")
    order = raw.get("base_order")
    if not isinstance(order, list) or len(order) != 20:
        raise M5ContractError("base order must be twenty interleaved slots")
    expected = []
    for task_id in tasks:
        expected.append({"task_id": task_id, "side": Side.CODEX.value, "product": None})
        expected.append(
            {
                "task_id": task_id,
                "side": Side.RONDO.value,
                "product": Product.RONDO_MULTI.value,
            }
        )
    if order != expected:
        raise M5ContractError("base order is not task-major Codex then Multi")
    images = tuple(raw.get("docker_images") or ())
    catalog_images = tuple(item["image_ref"] for item in catalog_doc["tasks"])
    if images != catalog_images:
        raise M5ContractError("Docker image list differs from the frozen catalog")
    infra = raw.get("infra")
    cost = raw.get("cost_forecast")
    price = raw.get("price_snapshot")
    if not isinstance(infra, dict) or not isinstance(cost, dict) or not isinstance(price, dict):
        raise M5ContractError("budget or infra block is missing")
    if (
        raw.get("max_effective_runs") != 60
        or infra.get("max_slot_attempts") != 3
        or infra.get("max_infra_attempts_total") != 12
        or raw.get("max_requests_per_run") != 80
        or cost.get("hard_cap_usd") != "120.00"
    ):
        raise M5ContractError("gate 2 attempt or dollar contract differs")
    if price.get("date") != "2026-08-17":
        raise M5ContractError("price snapshot date differs")
    if price.get("model_id") != "gpt-5.6-sol":
        raise M5ContractError("price snapshot model differs")
    trigger = (raw.get("conditional_rerun") or {}).get("trigger")
    if trigger != "codex_completed_multi_incomplete":
        raise M5ContractError("conditional rerun trigger differs")
    return NondegradationContract(
        lock_id=raw["lock_id"],
        catalog_path=catalog,
        catalog_sha256=raw["catalog_sha256"],
        tasks=tasks,
        base_order=tuple(order),
        root_model=_model(raw.get("root_model")),
        member_model=_model(raw.get("member_model")),
        root_effort=_effort(raw.get("root_effort")),
        provider=_provider(raw.get("provider")),
        max_effective_runs=60,
        max_slot_attempts=3,
        max_infra_attempts_total=12,
        max_requests_per_run=80,
        hard_cap_usd=cost["hard_cap_usd"],
        point_estimate_usd=str(cost["point_estimate_usd"]),
        worst_legal_usd=str(cost["worst_legal_usd"]),
        price_date=str(price["date"]),
        price_source_url=str(price["source_url"]),
        docker_images=images,
        raw=raw,
    )


def load_runtime_identity(
    path: Path | None = None,
    *,
    require_frozen: bool = False,
    common_root: Path | None = None,
) -> RuntimeIdentity:
    lock_path = path or LOCKS_DIR / "multi-m5-runtime-v1.json"
    raw = _read_json(lock_path)
    if raw.get("schema_version") != 1 or raw.get("lock_id") != "multi-m5-runtime-v1":
        raise M5ContractError("runtime lock identity differs")
    if raw.get("product") != Product.RONDO_MULTI.value:
        raise M5ContractError("runtime lock product differs")
    commit = raw.get("source_commit")
    if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
        raise M5ContractError("runtime source commit is invalid")
    bundle_name = raw.get("bundle_dir_name")
    relpath = raw.get("bundle_relpath")
    expected_name = f"{commit}-x86_64-unknown-linux-musl-runtime-bundle"
    expected_relpath = f"eval-data/bin/rondo-multi/{expected_name}"
    if bundle_name != expected_name or relpath != expected_relpath:
        raise M5ContractError("runtime bundle path differs from the source commit")
    status = raw.get("status")
    if status not in {"pending_freeze", "frozen"}:
        raise M5ContractError("runtime lock status is invalid")
    identity = RuntimeIdentity(
        lock_id=raw["lock_id"],
        status=status,
        product=raw["product"],
        source_commit=commit,
        bundle_dir_name=bundle_name,
        bundle_relpath=relpath,
        codex_sha256=_optional_sha(raw.get("codex_sha256")),
        code_mode_host_sha256=_optional_sha(raw.get("code_mode_host_sha256")),
        bwrap_sha256=_optional_sha(raw.get("bwrap_sha256")),
        manifest_sha256=_optional_sha(raw.get("manifest_sha256")),
        baseline=_baseline(raw.get("codex_baseline")),
        raw=raw,
    )
    if require_frozen:
        _require_on_disk_bundle(identity, common_root)
    return identity


def _require_on_disk_bundle(identity: RuntimeIdentity, common_root: Path | None) -> None:
    if not identity.frozen:
        raise M5ContractError("Multi runtime bundle is not frozen")
    if common_root is None:
        raise M5ContractError("common root is required to verify the frozen bundle")
    bundle = (common_root / identity.bundle_relpath).resolve()
    expected = (common_root / "eval-data" / "bin" / "rondo-multi").resolve()
    if not bundle.is_relative_to(expected):
        raise M5ContractError("runtime bundle is outside eval-data/bin/rondo-multi")
    manifest = bundle / "manifest.json"
    _require_sha(manifest, identity.manifest_sha256, "runtime manifest")
    files = {
        bundle / "codex": identity.codex_sha256,
        bundle / "codex-code-mode-host": identity.code_mode_host_sha256,
        bundle / "codex-resources" / "bwrap": identity.bwrap_sha256,
    }
    for path, digest in files.items():
        _require_sha(path, digest, path.name)
    document = _read_json(manifest)
    if (
        document.get("product") != Product.RONDO_MULTI.value
        or document.get("source_commit") != identity.source_commit
        or document.get("sha256") != identity.codex_sha256
        or document.get("code_mode_host_sha256") != identity.code_mode_host_sha256
        or document.get("bwrap_sha256") != identity.bwrap_sha256
        or document.get("source_dirty") is not False
    ):
        raise M5ContractError("runtime manifest identity differs from the lock")


def _baseline(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise M5ContractError("Codex baseline identity is missing")
    for key in (
        "source_commit",
        "bundle_dir_name",
        "bundle_relpath",
        "codex_sha256",
        "code_mode_host_sha256",
        "bwrap_sha256",
        "manifest_sha256",
    ):
        item = value.get(key)
        if not isinstance(item, str) or not item:
            raise M5ContractError("Codex baseline identity is incomplete")
    if not _COMMIT.fullmatch(str(value["source_commit"])):
        raise M5ContractError("Codex baseline commit is invalid")
    for key in (
        "codex_sha256",
        "code_mode_host_sha256",
        "bwrap_sha256",
        "manifest_sha256",
    ):
        if not _SHA256.fullmatch(str(value[key])):
            raise M5ContractError("Codex baseline digest is invalid")
    return dict(value)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise M5ContractError(f"{path.name} is not a regular file")
    try:
        value = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M5ContractError(f"{path.name} is unreadable") from exc
    if not isinstance(value, dict):
        raise M5ContractError(f"{path.name} is not an object")
    return value


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("eval/") or ".." in value:
        raise M5ContractError("lock path must stay under eval/")
    return value


def _require_sha(path: Path, digest: object, label: str) -> None:
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise M5ContractError(f"{label} digest is invalid")
    if path.is_symlink() or not path.is_file():
        raise M5ContractError(f"{label} is not a regular file")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != digest:
        raise M5ContractError(f"{label} digest differs")


def _optional_sha(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise M5ContractError("digest is invalid")
    return value


def _model(value: object) -> str:
    if value != "gpt-5.6-sol":
        raise M5ContractError("model must be gpt-5.6-sol")
    return value


def _effort(value: object) -> str:
    if value != "medium":
        raise M5ContractError("effort must be medium")
    return value


def _provider(value: object) -> str:
    if value != "relay":
        raise M5ContractError("provider must be relay")
    return value
