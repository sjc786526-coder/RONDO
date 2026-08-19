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

from ..api_budget_proxy import (
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    _UrllibTransport,
    exposure_summary,
    stop_reason_class,
)
from ..config import RepoPaths
from ..contracts import Product, Side
from .archive import archive_record, harness_identity
from .budget import (
    SMOKE_BATCH_ID,
    run_infra_taint,
    SMOKE_LOCK_ID,
    gate1_run_cap_usd,
    max_concurrent_main,
    phase_b_pricing,
    request_reservation_usd,
    require_frozen_provider,
    retry_backoff_seconds,
    run_stop_reason,
    smoke_run_cap_usd,
    usage_envelope,
)
from .capture import FORWARD_TIMEOUT_SECONDS, CaptureProxy
from .collect import EvidenceError, member_message_delivery
from .command import build_multi_exec_command
from .load import M5ContractError, load_runtime_identity, load_workflow_contract
from .loopback import LOOPBACK_BEARER, _require_executable
from .paid import PaidAuthorization
from .predicates import (
    REQUIRED_PREDICATE_IDS,
    CollaborationVerdict,
    evaluate_collaboration,
)
from .rehearsal import CollaborationStub
from .store import capture_dir, persist_archive_record, scratch_root
from .trace import TraceError, find_trace_bundle, load_rollout_trace

REHEARSAL_TIMEOUT_SECONDS = 180
# Root and its members call concurrently, so a rate-limited relay answers 429
# to whichever request arrives second. Retrying those five times with no delay
# just burns the attempt budget in milliseconds and surfaces as an upstream
# failure -- which is exactly how the first real smoke ended. The proxy scales
# this exponentially (2, 4, 8, 16s) and stops early if the forward deadline
# would pass, so the whole ladder fits inside one 180s forward window. The base
# now comes from the lock so gate 2 cannot retry on a different ladder.
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
    if provider_identity is not None and upstream_base_url.rstrip("/") != provider_identity[
        "provider_base_url"
    ].rstrip("/"):
        # The forwarded endpoint has to be the one that was just frozen, not a
        # second argument that quietly points somewhere else.
        raise Gate1Error("paid gate 1 upstream differs from the frozen provider endpoint")
    root = _common_root(common_root)
    run_cap = gate1_run_cap_usd()
    reservation = request_reservation_usd()
    envelope = usage_envelope()
    concurrent_main = max_concurrent_main()
    last: dict[str, Any] | None = None
    for attempt in range(1, workflow.max_attempts + 1):
        run_id = f"m5-g1-paid-a{attempt}"
        # `claim_run` rather than `ensure_run`: a re-invoked CLI must not be able
        # to spend a second time against an id that already paid, overwrite its
        # capture, or turn three attempts into six.
        ledger.claim_run(run_id, cap_usd=run_cap)
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
            retry_backoff_seconds=retry_backoff_seconds(),
            unbilled_retry_statuses=tuple(sorted({429, 500, 502, 503, 504})),
            request_reservation_usd=reservation,
            run_cap_usd=run_cap,
            timeout_seconds=FORWARD_TIMEOUT_SECONDS,
            # Root and its members are concurrent by design; the proxy's
            # single-main rule predates Multi. The limit is the frozen product's
            # own maximum, so a fifth caller is a config drift the harness stops
            # rather than a cost it silently absorbs.
            max_concurrent_main=concurrent_main,
            usage_envelope=envelope,
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
                taint_probe=lambda: run_infra_taint(ledger, run_id),
                exposure_probe=lambda: exposure_summary(ledger.snapshot(), run_id),
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
        if outcome == "completed":
            return result
        # The contract buys three independent attempts, and gate 1 is a
        # protocol demonstration: a model that fumbled the sequence once is
        # exactly the case those attempts exist for. Only a hard stop -- the
        # budget, an authorization, a capacity line -- ends the gate early,
        # because retrying those spends money on a decision already made.
        if outcome == "budget_stopped":
            return result
    assert last is not None
    return last


def run_gate1_smoke(
    *,
    authorization: PaidAuthorization,
    api_key: str,
    upstream_base_url: str,
    ledger: PersistentBudgetLedger,
    provider,
    run_id: str,
    archive_path: Path,
    common_root: Path | None = None,
    persist: bool = True,
    transport: _UrllibTransport | None = None,
    process_runner: ProcessRunner = subprocess.run,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    """One real-API flow to prove the provider serves the frozen model.

    Separately authorized and deliberately outside the contract: a single
    attempt, its own ledger batch, its own archive file, and its own lock id.
    It answers "does a whole flow work end to end on this model" and nothing
    else -- passing predicates here is **not** a gate 1 pass, and failing here
    does not consume one of gate 1's three attempts.
    """

    authorization.require_api()
    if not isinstance(api_key, str) or not api_key or "\r" in api_key or "\n" in api_key:
        raise Gate1Error("the in-memory provider key is invalid")
    workflow = load_workflow_contract()
    pricing = phase_b_pricing()
    if pricing.model_id != workflow.root_model:
        raise Gate1Error("smoke model differs from the frozen price snapshot")
    identity = require_frozen_provider(provider, effort=workflow.root_effort)
    if upstream_base_url.rstrip("/") != identity["provider_base_url"].rstrip("/"):
        raise Gate1Error("smoke upstream differs from the frozen provider endpoint")
    root = _common_root(common_root)
    if not isinstance(run_id, str) or not run_id.startswith("m5-g1-smoke-"):
        # A fresh identity per smoke run. Reusing one made the second run's
        # ledger replace the first's and left the pair impossible to read apart.
        raise Gate1Error("smoke run id must be a fresh m5-g1-smoke-<label> id")
    run_cap = smoke_run_cap_usd()
    ledger.claim_run(run_id, cap_usd=run_cap)
    metadata_path = capture_dir(root, run_id) / "budget-metadata.json"
    if metadata_path.parent.exists() and any(metadata_path.parent.iterdir()):
        raise Gate1Error("smoke capture directory already holds artifacts")
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
        retry_backoff_seconds=retry_backoff_seconds(),
        unbilled_retry_statuses=tuple(sorted({429, 500, 502, 503, 504})),
        request_reservation_usd=request_reservation_usd(),
        run_cap_usd=run_cap,
        timeout_seconds=FORWARD_TIMEOUT_SECONDS,
        # Root and its members are concurrent by design; the proxy's
        # single-main rule predates Multi.
        max_concurrent_main=max_concurrent_main(),
        usage_envelope=usage_envelope(),
        _transport=transport,
    )
    with proxy:
        return _run_gate1_once(
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
            taint_probe=lambda: run_infra_taint(ledger, run_id),
            exposure_probe=lambda: exposure_summary(ledger.snapshot(), run_id),
            lock_id=SMOKE_LOCK_ID,
            archive_file=archive_path,
            extra={
                "rehearsal": False,
                "smoke_test": True,
                "contract_attempt": False,
                "budget_run_id": run_id,
                "budget_batch_id": SMOKE_BATCH_ID,
                "provider_identity": dict(identity),
                **harness_identity(RepoPaths.discover(Path.cwd()).worktree_root),
            },
        )


def _no_evidence_verdict(reason: str | None) -> CollaborationVerdict:
    """Every predicate false, with the reason the evidence could not be read.

    Deliberately not an exception: a run whose trace is unusable still produced
    a real, archivable attempt, and the archive should say the evidence failed
    rather than lose the run.
    """

    return CollaborationVerdict(
        passed=False,
        predicates={name: False for name in REQUIRED_PREDICATE_IDS},
        reasons=(f"evidence:{reason or 'rollout trace unavailable'}",),
        event_id=None,
        ignored_evidence=(),
    )


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
    taint_probe: Callable[[], dict | None] | None = None,
    exposure_probe: Callable[[], dict[str, Any]] | None = None,
    lock_id: str | None = None,
    archive_file: Path | None = None,
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

    trace_root = capture_root / "rollout-trace"
    if trace_root.exists():
        shutil.rmtree(trace_root)
    trace_root.mkdir(parents=True, mode=0o700)

    scratch = scratch_root(root)
    completed: subprocess.CompletedProcess[bytes] | None = None
    timed_out = False
    jsonl = ""
    request_count = 0
    trace_error: str | None = None
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
                member_model=workflow.member_model,
                member_effort=workflow.raw["member_effort"],
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
                # Gate 1's evidence source. The frozen binary writes its own
                # tool-dispatch record here; under code mode that is the only
                # place the team tools it actually ran are visible. Spawned
                # members share the root's writer, so one bundle covers the team.
                "CODEX_ROLLOUT_TRACE_ROOT": str(trace_root),
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
            # No trace means no evidence. Judging the run on the Responses
            # capture alone would be judging text the model wrote about its own
            # tool calls, which is exactly what this gate must not do.
            try:
                rollout = load_rollout_trace(find_trace_bundle(trace_root))
            except TraceError as exc:
                rollout = None
                trace_error = str(exc)
            try:
                verdict = evaluate_collaboration(
                    {},
                    workspace=workspace,
                    finding_line=workflow.finding_line,
                    report_filename=workflow.report_filename,
                    max_members=workflow.max_members,
                    jsonl=jsonl,
                    trace=rollout,
                ) if rollout is not None else _no_evidence_verdict(trace_error)
            except EvidenceError as exc:
                trace_error = str(exc)
                verdict = _no_evidence_verdict(trace_error)
            report = workspace / workflow.report_filename
            report_text = (
                report.read_text("utf-8")
                if report.is_file() and not report.is_symlink()
                else ""
            )

    if completed is None:
        raise Gate1Error("gate 1 process did not start")
    stop_reason = budget_probe() if budget_probe is not None else None
    taint = taint_probe() if taint_probe is not None else None
    # Keep whatever the judge saw so a timeout after tool calls is auditable.
    predicates = dict(verdict.predicates)
    ignored = list(verdict.ignored_evidence)
    event_id = verdict.event_id
    stop_class = stop_reason_class(stop_reason)
    if stop_class == "unknown":
        # Never guess. An unrecognised stop reason means the run ended for a
        # cause this classifier does not model, and filing it as either a budget
        # stop or a product failure would be an invented fact.
        raise Gate1Error(f"unclassified budget stop reason: {stop_reason}")
    # Stop lines are decided first, before any success branch. A run whose
    # ledger stopped -- capacity exhausted, upstream terminal failure, usage
    # never reported -- did not finish under the frozen contract, even if the
    # predicates had already been satisfied by the time it stopped. Judging the
    # evidence first would let a stopped run archive as `completed/passed=true`
    # and let gate 1 pass after a stop line actually fired. The predicates are
    # still recorded on the row, so a near-miss stays diagnosable.
    if taint is not None:
        # The upstream failed at least once during this run. Whether the run was
        # allowed to keep going is a spending question; it cannot be a statement
        # about the product either way. Filing it as `agent_failed` would record
        # a model verdict the run never earned -- cm4 absorbed eight upstream
        # terminal errors and was archived exactly that way.
        passed = False
        outcome = "infra_failed"
        reasons = [f"infra_taint:{taint['first_reason']}x{taint['count']}"]
    elif stop_class == "budget":
        # The proxy answered 429 and the model never got the chance to finish.
        # Not retried: that would only spend more against a decision made.
        passed = False
        outcome = "budget_stopped"
        reasons = [stop_reason]
    elif stop_class == "infra":
        # The upstream failed, usage never arrived, or a deadline expired. The
        # ledger still debited the reservation, but no money ran out: calling
        # this `budget_stopped` would send someone looking at the wrong thing,
        # and it is a retryable attempt rather than a hard stop.
        passed = False
        outcome = "infra_failed"
        reasons = [stop_reason]
    elif not timed_out and jsonl.strip() and verdict.passed and completed.returncode == 0:
        passed = True
        outcome = "completed"
        reasons = list(verdict.reasons)
    elif timed_out or not jsonl.strip() or trace_error is not None:
        # An unreadable trace is the evidence pipeline failing, not the team
        # failing. Filing it as `agent_failed` would spend an attempt and record
        # a product verdict this run never actually produced.
        outcome = "infra_failed"
        passed = False
        if timed_out:
            reasons = ["timeout"]
        elif not jsonl.strip():
            reasons = [f"empty capture rc={completed.returncode}"]
        else:
            reasons = [f"evidence:{trace_error}"]
    else:
        passed = False
        outcome = "agent_failed"
        reasons = list(verdict.reasons)
        # A crashed run cannot be a pass even when the judge saw every predicate.
        if completed.returncode != 0 and verdict.passed:
            reasons = [f"nonzero exit rc={completed.returncode}"]

    extra_fields = {
        "stop_reason": stop_reason,
        "stop_reason_class": stop_class,
        # Present whenever the upstream failed during the run, with or without a
        # stop. A row carrying this is never product evidence.
        "infra_taint": taint,
        "evidence_source": "code_mode_rollout_trace",
        "trace_error": trace_error,
        # Whether the member ever received a readable task at all. A run that
        # fails with every `agent_message` labelled encrypted says nothing about
        # the model's protocol compliance, so the distinction is recorded rather
        # than left to be spotted in the capture.
        "member_message_delivery": member_message_delivery(jsonl),
        # What the provider's token counts justify, kept apart from what the
        # ledger debited without them. A reservation held against a response
        # that never reported usage is exposure, not measured spend.
        **(
            {"budget_exposure": exposure_probe()}
            if exposure_probe is not None
            else {}
        ),
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
        lock_id=lock_id or workflow.lock_id,
        side=Side.RONDO,
        product=Product.RONDO_MULTI,
        source_commit=runtime.source_commit,
        binary_sha256=binary_sha,
        outcome=outcome,
        counts_as_effective=False,
        # What the command line actually pinned, from this gate's own lock.
        subagent_model=workflow.member_model,
        subagent_effort=str(workflow.raw["member_effort"]),
        extra=extra_fields,
    )
    archived = None
    if persist:
        archived = str(
            persist_archive_record(record, common_root=root, path=archive_file)
        )
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
