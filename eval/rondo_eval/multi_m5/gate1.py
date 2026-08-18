"""Gate 1 host runner: frozen Multi binary + capture proxy + collaboration judge.

Rehearsal stubs the model. The paid entry forwards every captured body through
the loopback budget proxy. Both paths share argv construction and capture.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..api_budget_proxy import LoopbackResponsesProxy, PersistentBudgetLedger, _UrllibTransport
from ..config import RepoPaths
from ..contracts import Product, Side
from .archive import archive_record, harness_identity
from .budget import (
    GATE1_REQUEST_RESERVATION_USD,
    GATE1_RUN_CAP_USD,
    phase_b_pricing,
    require_frozen_provider,
    run_stop_reason,
)
from .capture import FORWARD_TIMEOUT_SECONDS, CaptureProxy
from .command import build_multi_exec_command
from .load import M5ContractError, load_runtime_identity, load_workflow_contract
from .loopback import LOOPBACK_BEARER, _require_executable
from .paid import PaidAuthorization
from .predicates import evaluate_collaboration
from .rehearsal import CollaborationStub
from .store import capture_dir, persist_archive_record, scratch_root

REHEARSAL_TIMEOUT_SECONDS = 180
ProcessRunner = Callable[..., subprocess.CompletedProcess[bytes]]


class Gate1Error(RuntimeError):
    """Gate 1 runner failed closed before a collaboration verdict."""


def run_gate1_rehearsal(
    *,
    common_root: Path | None = None,
    timeout_seconds: int = REHEARSAL_TIMEOUT_SECONDS,
    persist: bool = True,
    process_runner: ProcessRunner = subprocess.run,
) -> dict[str, Any]:
    """Offline full protocol. Not a paid gate 1 pass, even if predicates are green."""

    stub = CollaborationStub(finding_line=_workflow_finding())
    return _run_gate1_once(
        common_root=common_root,
        run_id="m5-g1-rehearsal",
        timeout_seconds=timeout_seconds,
        persist=persist,
        evidence_kind="loopback",
        capture_mode="stub",
        stub=stub,
        process_runner=process_runner,
        extra={"rehearsal": True, "stub_finished": False},
    )


def run_gate1_paid(
    *,
    authorization: PaidAuthorization,
    api_key: str,
    upstream_base_url: str,
    ledger: PersistentBudgetLedger,
    common_root: Path | None = None,
    persist: bool = True,
    transport: _UrllibTransport | None = None,
    process_runner: ProcessRunner = subprocess.run,
    timeout_seconds: int | None = None,
    provider=None,
) -> dict[str, Any]:
    """Paid gate 1. Capture forwards to the budget proxy. Spends money if transport is real."""

    authorization.require_api()
    if not isinstance(api_key, str) or not api_key or "\r" in api_key or "\n" in api_key:
        raise Gate1Error("the in-memory provider key is invalid")
    workflow = load_workflow_contract()
    pricing = phase_b_pricing()
    if pricing.model_id != workflow.root_model:
        raise Gate1Error("paid gate 1 model differs from the frozen price snapshot")
    provider_identity = (
        None
        if provider is None
        else require_frozen_provider(provider, effort=workflow.root_effort)
    )
    root = _common_root(common_root)
    last: dict[str, Any] | None = None
    for attempt in range(1, workflow.max_attempts + 1):
        run_id = f"m5-g1-paid-a{attempt}"
        ledger.ensure_run(run_id, cap_usd=GATE1_RUN_CAP_USD)
        metadata_path = capture_dir(root, run_id) / "budget-metadata.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        proxy = LoopbackResponsesProxy(
            upstream_base_url=upstream_base_url,
            api_key=api_key,
            ledger=ledger,
            run_id=run_id,
            metadata_path=metadata_path,
            main_model=workflow.root_model,
            main_effort=workflow.root_effort,
            main_pricing=pricing,
            guardian_model=workflow.root_model,
            guardian_pricing=pricing,
            guardian_effort=workflow.root_effort,
            max_attempts=5,
            retry_backoff_seconds=0.0,
            unbilled_retry_statuses=tuple(sorted({429, 500, 502, 503, 504})),
            request_reservation_usd=GATE1_REQUEST_RESERVATION_USD,
            run_cap_usd=GATE1_RUN_CAP_USD,
            timeout_seconds=FORWARD_TIMEOUT_SECONDS,
            _transport=transport,
        )
        with proxy:
            result = _run_gate1_once(
                common_root=root,
                run_id=run_id,
                timeout_seconds=timeout_seconds or workflow.timeout_seconds,
                persist=persist,
                evidence_kind="real_api",
                capture_mode="forward",
                stub=None,
                process_runner=process_runner,
                capture_upstream=proxy.base_url,
                capture_bearer=proxy.downstream_api_key,
                budget_probe=lambda: run_stop_reason(ledger, run_id),
                extra={
                    "rehearsal": False,
                    "attempt": attempt,
                    "budget_run_id": run_id,
                    **(
                        {"provider_identity": dict(provider_identity)}
                        if provider_identity is not None
                        else {}
                    ),
                    **harness_identity(RepoPaths.discover(Path.cwd()).worktree_root),
                },
            )
        last = result
        outcome = str(result["record"].get("outcome"))
        if outcome != "infra_failed":
            return result
    assert last is not None
    return last


def _workflow_finding() -> str:
    return load_workflow_contract().finding_line


def _common_root(common_root: Path | None) -> Path:
    if common_root is not None:
        return common_root
    return RepoPaths.discover(Path.cwd()).common_root


def _run_gate1_once(
    *,
    common_root: Path | None,
    run_id: str,
    timeout_seconds: int,
    persist: bool,
    evidence_kind: str,
    capture_mode: str,
    stub: CollaborationStub | None,
    process_runner: ProcessRunner,
    capture_upstream: str | None = None,
    capture_bearer: str = LOOPBACK_BEARER,
    budget_probe: Callable[[], str | None] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = _common_root(common_root)
    workflow = load_workflow_contract()
    runtime = load_runtime_identity(require_frozen=True, common_root=root)
    instruction = workflow.instruction_path.read_text("utf-8")
    digest = hashlib.sha256(instruction.encode("utf-8")).hexdigest()
    if digest != workflow.instruction_sha256:
        raise M5ContractError("instruction digest differs from the workflow lock")
    binary = (root / runtime.bundle_relpath / "codex").resolve()
    _require_executable(binary)
    binary_sha = hashlib.sha256(binary.read_bytes()).hexdigest()
    if binary_sha != runtime.codex_sha256:
        raise Gate1Error("frozen Multi binary digest differs from the runtime lock")
    if evidence_kind == "real_api" and capture_mode != "forward":
        raise Gate1Error("paid gate 1 must capture through forward mode")
    if evidence_kind != "real_api" and capture_mode == "forward":
        raise Gate1Error("forward capture is reserved for the paid gate 1 path")

    capture_root = capture_dir(root, run_id)
    capture_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    capture_path = capture_root / "requests.jsonl"
    if capture_path.exists():
        capture_path.unlink()

    scratch = scratch_root(root)
    completed: subprocess.CompletedProcess[bytes] | None = None
    timed_out = False
    jsonl = ""
    request_count = 0
    with tempfile.TemporaryDirectory(prefix="rondo-m5-gate1-", dir=scratch) as raw:
        home = Path(raw) / "codex-home"
        workspace = Path(raw) / "workspace"
        home.mkdir(mode=0o700)
        _copy_fixture(workflow.fixture_dir, workspace)
        (home / "auth.json").write_text(
            json.dumps({"OPENAI_API_KEY": capture_bearer}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(home / "auth.json", 0o600)
        capture_kwargs: dict[str, Any] = {
            "mode": capture_mode,
            "capture_path": capture_path,
            "bearer": capture_bearer,
            "model": workflow.root_model,
        }
        if capture_mode == "stub":
            if stub is None:
                raise Gate1Error("stub capture requires a collaboration stub")
            capture_kwargs["handler"] = stub
        else:
            capture_kwargs["upstream_base_url"] = capture_upstream
            capture_kwargs["forward_timeout_seconds"] = FORWARD_TIMEOUT_SECONDS
        with CaptureProxy(**capture_kwargs) as proxy:
            command = build_multi_exec_command(
                binary,
                base_url=proxy.base_url,
                instruction=instruction,
                model=workflow.root_model,
                effort=workflow.root_effort,
            )
            env = {
                "CODEX_HOME": str(home),
                "HOME": str(home),
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
                "OPENAI_API_KEY": capture_bearer,
            }
            try:
                completed = process_runner(
                    command,
                    cwd=workspace,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                stderr = exc.stderr if isinstance(exc.stderr, bytes) else b""
                stdout = exc.stdout if isinstance(exc.stdout, bytes) else b""
                completed = subprocess.CompletedProcess(
                    args=exc.cmd,
                    returncode=-1,
                    stdout=stdout,
                    stderr=stderr,
                )
            jsonl = proxy.jsonl()
            request_count = len(proxy.bodies)
            verdict = evaluate_collaboration(
                {},
                workspace=workspace,
                finding_line=workflow.finding_line,
                report_filename=workflow.report_filename,
                max_members=workflow.max_members,
                jsonl=jsonl,
            )
            report = workspace / workflow.report_filename
            report_text = (
                report.read_text("utf-8")
                if report.is_file() and not report.is_symlink()
                else ""
            )

    if completed is None:
        raise Gate1Error("gate 1 process did not start")
    stop_reason = budget_probe() if budget_probe is not None else None
    # Keep whatever the judge saw so a timeout after tool calls is auditable.
    predicates = dict(verdict.predicates)
    ignored = list(verdict.ignored_evidence)
    event_id = verdict.event_id
    if not timed_out and jsonl.strip() and verdict.passed and completed.returncode == 0:
        # Evidence is already complete; a late budget stop does not unmake it.
        passed = True
        outcome = "completed"
        reasons = list(verdict.reasons)
    elif stop_reason is not None:
        # Not an agent failure: the proxy answered 429 and the model never got
        # the chance to finish. It is also not retried, that would only spend more.
        passed = False
        outcome = "budget_stopped"
        reasons = [stop_reason]
    elif timed_out or not jsonl.strip():
        outcome = "infra_failed"
        passed = False
        reasons = (
            ["timeout"] if timed_out else [f"empty capture rc={completed.returncode}"]
        )
    else:
        passed = False
        outcome = "agent_failed"
        reasons = list(verdict.reasons)
        # A crashed run cannot be a pass even when the judge saw every predicate.
        if completed.returncode != 0 and verdict.passed:
            reasons = [f"nonzero exit rc={completed.returncode}"]

    extra_fields = {
        "stop_reason": stop_reason,
        "passed": passed,
        "predicates": predicates,
        "reasons": reasons,
        "ignored_evidence": ignored,
        "event_id": event_id,
        "request_count": request_count,
        "returncode": completed.returncode,
        "report_present": bool(report_text),
        "tool_surface": "non_code_mode_only=false",
        "timed_out": timed_out,
        **dict(extra or {}),
    }
    if stub is not None:
        extra_fields["stub_finished"] = stub.finished
        extra_fields["stub_errors"] = list(stub.errors)
        extra_fields["rehearsal"] = True
    record = archive_record(
        evidence_kind=evidence_kind,
        gate=1,
        lock_id=workflow.lock_id,
        side=Side.RONDO,
        product=Product.RONDO_MULTI,
        source_commit=runtime.source_commit,
        binary_sha256=binary_sha,
        outcome=outcome,
        counts_as_effective=False,
        extra=extra_fields,
    )
    archived = None
    if persist:
        archived = str(persist_archive_record(record, common_root=root))
    (capture_root / "verdict.json").write_text(
        json.dumps(
            {
                "passed": passed,
                "predicates": predicates,
                "reasons": reasons,
                "ignored_evidence": ignored,
                "event_id": event_id,
                "timed_out": timed_out,
            },
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(capture_root / "verdict.json", 0o600)
    return {
        "record": record,
        "verdict": verdict,
        "request_count": request_count,
        "returncode": completed.returncode,
        "stderr_tail": _tail(completed.stderr),
        "capture_path": str(capture_path),
        "archive_path": archived,
        "report_text": report_text,
        "stub_errors": list(stub.errors) if stub is not None else [],
        "stub_finished": stub.finished if stub is not None else False,
        "timed_out": timed_out,
    }


def _copy_fixture(source: Path, workspace: Path) -> None:
    if source.is_symlink() or not source.is_dir():
        raise Gate1Error("gate 1 fixture is not a regular directory")
    workspace.mkdir(mode=0o700)
    for item in source.iterdir():
        if item.is_symlink() or not item.is_file():
            continue
        if item.name == "TEAM_REPORT.md":
            continue
        target = workspace / item.name
        shutil.copy2(item, target)
        mode = stat.S_IMODE(item.stat().st_mode)
        os.chmod(target, mode if mode else 0o600)


def _tail(blob: bytes, limit: int = 4000) -> str:
    return blob.decode("utf-8", "replace")[-limit:]
