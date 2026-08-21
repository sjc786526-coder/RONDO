"""Crash-safe Plan 051 task-wide budget envelope.

The per-campaign proxy remains responsible for individual request admission and
settlement.  This small sidecar records the one fact it cannot know: the
cumulative settled cost across immutable v7 identities.  It deliberately is
not a general ledger or scheduler.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterator, Mapping


TASK_BUDGET_ID = "plan-051-direction0-schema-v7-canary"
TASK_BUDGET_CAP_USD = Decimal("400.000000")
TASK_BUDGET_RELPATH = Path("eval-data/budgets/plan-051-task-envelope.json")
_SCHEMA_VERSION = 1
_MONEY_QUANTUM = Decimal("0.000001")
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_TERMINAL_STATUSES = frozenset({"passed", "failed", "blocked", "invalid"})


class TaskBudgetError(ValueError):
    """Raised when the cross-identity Plan 051 budget state is unsafe."""


def task_budget_path(common_root: Path) -> Path:
    """Return the one ignored, shared Plan 051 envelope location."""

    if not isinstance(common_root, Path) or common_root.is_symlink():
        raise TaskBudgetError("task budget common root is unsafe")
    return common_root / TASK_BUDGET_RELPATH


@dataclass(frozen=True)
class TaskBudgetIdentity:
    campaign_id: str
    batch_id: str

    def validate(self) -> None:
        for value, label in (
            (self.campaign_id, "campaign ID"),
            (self.batch_id, "batch ID"),
        ):
            if not isinstance(value, str) or _IDENTITY.fullmatch(value) is None:
                raise TaskBudgetError(f"task budget {label} is invalid")

    def to_dict(self, *, prior_settled_usd: Decimal) -> dict[str, str]:
        self.validate()
        return {
            "campaign_id": self.campaign_id,
            "batch_id": self.batch_id,
            "prior_settled_usd": _money_text(prior_settled_usd),
        }


def start_task_budget(path: Path, *, active: TaskBudgetIdentity) -> dict[str, object]:
    """Create the first schema-v7 identity at a zero prior exactly once."""

    active.validate()
    with _locked(path):
        if path.exists() or path.is_symlink():
            raise TaskBudgetError("task budget envelope already exists")
        state: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "task_budget_id": TASK_BUDGET_ID,
            "cap_usd": _money_text(TASK_BUDGET_CAP_USD),
            "prior_settled_usd": _money_text(Decimal(0)),
            "active_identity": active.to_dict(prior_settled_usd=Decimal(0)),
            "closed_identities": [],
            "hard_stop": False,
        }
        _validate_state(state)
        _atomic_write(path, state)
        return _clone(state)


def load_task_budget(path: Path) -> dict[str, object]:
    """Load and validate an existing envelope without taking a writer lock."""

    value = _read_json(path)
    _validate_state(value)
    return _clone(value)


def verify_active_identity(
    path: Path,
    *,
    active: TaskBudgetIdentity,
    prior_settled_usd: Decimal,
) -> dict[str, object]:
    """Fail closed unless the runtime identity and prior match the envelope."""

    active.validate()
    expected_prior = _require_money(prior_settled_usd, "runtime prior settled")
    state = load_task_budget(path)
    if state["hard_stop"]:
        raise TaskBudgetError("task budget has reached its hard stop")
    stored = _parse_active(state["active_identity"])
    prior = _parse_money(state["prior_settled_usd"], "prior settled")
    if stored != active or prior != expected_prior:
        raise TaskBudgetError("active task budget identity or prior differs")
    return task_budget_status(state)


def roll_forward_task_budget(
    path: Path,
    *,
    predecessor: TaskBudgetIdentity,
    predecessor_terminal_status: str,
    cumulative_settled_usd: Decimal,
    successor: TaskBudgetIdentity,
) -> dict[str, object]:
    """Atomically close the active terminal identity and activate its successor.

    ``cumulative_settled_usd`` is deliberately supplied by the campaign's
    mechanical settled-ledger calculation.  The envelope checks monotonicity,
    uniqueness and the task cap; it never recomputes a second billing model.
    """

    return _close_or_roll(
        path,
        predecessor=predecessor,
        predecessor_terminal_status=predecessor_terminal_status,
        cumulative_settled_usd=cumulative_settled_usd,
        successor=successor,
    )


def close_task_budget(
    path: Path,
    *,
    active: TaskBudgetIdentity,
    terminal_status: str,
    cumulative_settled_usd: Decimal,
) -> dict[str, object]:
    """Close the final identity, retaining all settled cost for reporting."""

    return _close_or_roll(
        path,
        predecessor=active,
        predecessor_terminal_status=terminal_status,
        cumulative_settled_usd=cumulative_settled_usd,
        successor=None,
    )


def task_budget_status(state: Mapping[str, object]) -> dict[str, object]:
    """Return the compact non-secret runtime/reporting projection."""

    _validate_state(state)
    prior = _parse_money(state["prior_settled_usd"], "prior settled")
    active = state["active_identity"]
    return {
        "task_budget_id": TASK_BUDGET_ID,
        "cap_usd": _money_text(TASK_BUDGET_CAP_USD),
        "prior_settled_usd": _money_text(prior),
        "remaining_usd": _money_text(TASK_BUDGET_CAP_USD - prior),
        "active_identity": _clone(active) if active is not None else None,
        "closed_identity_count": len(state["closed_identities"]),
        "hard_stop": state["hard_stop"],
        "status": (
            "hard_stopped" if state["hard_stop"] else ("active" if active else "closed")
        ),
    }


def _close_or_roll(
    path: Path,
    *,
    predecessor: TaskBudgetIdentity,
    predecessor_terminal_status: str,
    cumulative_settled_usd: Decimal,
    successor: TaskBudgetIdentity | None,
) -> dict[str, object]:
    predecessor.validate()
    if predecessor_terminal_status not in _TERMINAL_STATUSES:
        raise TaskBudgetError("predecessor identity is not terminal")
    total = _require_money(cumulative_settled_usd, "cumulative settled")
    if successor is not None:
        successor.validate()
        if successor == predecessor:
            raise TaskBudgetError("successor task budget identity duplicates predecessor")
    with _locked(path):
        state = _read_json(path)
        _validate_state(state)
        if state["hard_stop"]:
            raise TaskBudgetError("task budget has reached its hard stop")
        active = _parse_active(state["active_identity"])
        if active != predecessor:
            raise TaskBudgetError("predecessor is not the current active task budget identity")
        prior = _parse_money(state["prior_settled_usd"], "prior settled")
        if total < prior:
            raise TaskBudgetError("cumulative settled cost cannot decrease")
        if total > TASK_BUDGET_CAP_USD:
            raise TaskBudgetError("cumulative settled cost exceeds the task budget cap")
        closed = state["closed_identities"]
        assert isinstance(closed, list)
        known = {
            (row["campaign_id"], row["batch_id"])
            for row in closed
            if isinstance(row, dict)
        }
        if (predecessor.campaign_id, predecessor.batch_id) in known:
            raise TaskBudgetError("predecessor task budget identity is already closed")
        if successor is not None:
            if total >= TASK_BUDGET_CAP_USD:
                raise TaskBudgetError("task budget cap leaves no successor capacity")
            known_campaign_ids = {campaign_id for campaign_id, _ in known}
            known_batch_ids = {batch_id for _, batch_id in known}
            if (
                successor.campaign_id in known_campaign_ids
                or successor.batch_id in known_batch_ids
                or successor.campaign_id == predecessor.campaign_id
                or successor.batch_id == predecessor.batch_id
            ):
                raise TaskBudgetError("successor task budget identity was already used")
        closed.append(
            {
                "campaign_id": predecessor.campaign_id,
                "batch_id": predecessor.batch_id,
                "settled_usd": _money_text(total - prior),
                "cumulative_settled_usd": _money_text(total),
                "terminal_status": predecessor_terminal_status,
            }
        )
        state["prior_settled_usd"] = _money_text(total)
        state["active_identity"] = (
            successor.to_dict(prior_settled_usd=total) if successor is not None else None
        )
        state["hard_stop"] = total == TASK_BUDGET_CAP_USD
        _validate_state(state)
        _atomic_write(path, state)
        return _clone(state)


def _validate_state(value: Mapping[str, object]) -> None:
    required = {
        "schema_version",
        "task_budget_id",
        "cap_usd",
        "prior_settled_usd",
        "active_identity",
        "closed_identities",
        "hard_stop",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise TaskBudgetError("task budget envelope schema differs")
    if (
        value["schema_version"] != _SCHEMA_VERSION
        or value["task_budget_id"] != TASK_BUDGET_ID
    ):
        raise TaskBudgetError("task budget envelope identity differs")
    if _parse_money(value["cap_usd"], "cap") != TASK_BUDGET_CAP_USD:
        raise TaskBudgetError("task budget cap differs from the Plan 051 contract")
    prior = _parse_money(value["prior_settled_usd"], "prior settled")
    if prior > TASK_BUDGET_CAP_USD:
        raise TaskBudgetError("task budget prior exceeds the cap")
    if (
        not isinstance(value["hard_stop"], bool)
        or value["hard_stop"] != (prior == TASK_BUDGET_CAP_USD)
    ):
        raise TaskBudgetError("task budget hard-stop state is inconsistent")
    active_value = value["active_identity"]
    active = _parse_active(active_value) if active_value is not None else None
    if value["hard_stop"] and active is not None:
        raise TaskBudgetError("hard-stopped task budget cannot have an active identity")
    closed = value["closed_identities"]
    if not isinstance(closed, list):
        raise TaskBudgetError("task budget closed identities are invalid")
    known: set[tuple[str, str]] = set()
    campaign_ids: set[str] = set()
    batch_ids: set[str] = set()
    cumulative = Decimal(0)
    for row in closed:
        if not isinstance(row, dict) or set(row) != {
            "campaign_id",
            "batch_id",
            "settled_usd",
            "cumulative_settled_usd",
            "terminal_status",
        }:
            raise TaskBudgetError("closed task budget identity schema differs")
        identity = TaskBudgetIdentity(row["campaign_id"], row["batch_id"])
        identity.validate()
        pair = (identity.campaign_id, identity.batch_id)
        if (
            pair in known
            or identity.campaign_id in campaign_ids
            or identity.batch_id in batch_ids
        ):
            raise TaskBudgetError("closed task budget identity is duplicated")
        known.add(pair)
        campaign_ids.add(identity.campaign_id)
        batch_ids.add(identity.batch_id)
        settled = _parse_money(row["settled_usd"], "closed identity settled")
        cumulative += settled
        if (
            _parse_money(row["cumulative_settled_usd"], "closed cumulative settled")
            != cumulative
        ):
            raise TaskBudgetError("closed task budget cumulative cost is inconsistent")
        if row["terminal_status"] not in _TERMINAL_STATUSES:
            raise TaskBudgetError("closed task budget identity is not terminal")
    if cumulative != prior:
        raise TaskBudgetError("task budget prior differs from closed settled cost")
    if active is not None:
        if (
            (active.campaign_id, active.batch_id) in known
            or active.campaign_id in campaign_ids
            or active.batch_id in batch_ids
        ):
            raise TaskBudgetError("active task budget identity was already closed")
        active_mapping = active_value
        assert isinstance(active_mapping, Mapping)
        if (
            _parse_money(active_mapping["prior_settled_usd"], "active identity prior")
            != prior
        ):
            raise TaskBudgetError("active task budget prior differs from envelope")


def _parse_active(value: object) -> TaskBudgetIdentity:
    if not isinstance(value, Mapping) or set(value) != {
        "campaign_id",
        "batch_id",
        "prior_settled_usd",
    }:
        raise TaskBudgetError("active task budget identity schema differs")
    identity = TaskBudgetIdentity(value["campaign_id"], value["batch_id"])
    identity.validate()
    _parse_money(value["prior_settled_usd"], "active identity prior")
    return identity


def _require_money(value: Decimal, label: str) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise TaskBudgetError(f"{label} must be a non-negative Decimal")
    if value != value.quantize(_MONEY_QUANTUM):
        raise TaskBudgetError(f"{label} must have six decimal places")
    return value


def _parse_money(value: object, label: str) -> Decimal:
    if not isinstance(value, str):
        raise TaskBudgetError(f"{label} must be a decimal string")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise TaskBudgetError(f"{label} is invalid") from exc
    return _require_money(parsed, label)


def _money_text(value: Decimal) -> str:
    return f"{_require_money(value, 'money'):.6f}"


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.exists():
        raise TaskBudgetError("task budget envelope is missing or unsafe")
    descriptor = _open_regular(path, os.O_RDONLY)
    with os.fdopen(descriptor, "rb") as handle:
        raw = handle.read()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TaskBudgetError("task budget envelope is not valid JSON") from exc
    if not isinstance(value, dict):
        raise TaskBudgetError("task budget envelope is not an object")
    return value


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    _prepare_parent(path.parent)
    lock_path = path.with_suffix(path.suffix + ".lock")
    descriptor = _open_regular(
        lock_path, os.O_RDWR | os.O_CREAT, create=True
    )
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _prepare_parent(parent: Path) -> None:
    if parent.exists() or parent.is_symlink():
        if parent.is_symlink() or not parent.is_dir():
            raise TaskBudgetError("task budget parent directory is unsafe")
        return
    parent.mkdir(parents=True, mode=0o700)
    if parent.is_symlink() or not parent.is_dir():
        raise TaskBudgetError("task budget parent directory is unsafe")


def _open_regular(path: Path, flags: int, *, create: bool = False) -> int:
    if path.is_symlink():
        raise TaskBudgetError("task budget path is a symlink")
    open_flags = flags | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW
    descriptor = (
        os.open(path, open_flags, 0o600) if create else os.open(path, open_flags)
    )
    try:
        mode = os.fstat(descriptor).st_mode
        if not stat.S_ISREG(mode):
            raise TaskBudgetError("task budget path is not a regular file")
        if not create and stat.S_IMODE(mode) != 0o600:
            raise TaskBudgetError("task budget file permissions must be 0600")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _atomic_write(path: Path, value: Mapping[str, object]) -> None:
    _prepare_parent(path.parent)
    if path.exists() and path.is_symlink():
        raise TaskBudgetError("task budget envelope is a symlink")
    payload = (
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise TaskBudgetError("task budget temporary path already exists")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _clone(value: object) -> dict[str, object]:
    cloned = json.loads(json.dumps(value))
    assert isinstance(cloned, dict)
    return cloned
