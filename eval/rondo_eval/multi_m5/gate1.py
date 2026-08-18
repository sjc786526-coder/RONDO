"""Gate 1 host runner: frozen Multi binary + capture proxy + collaboration judge."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ..config import RepoPaths
from ..contracts import Product, Side
from .archive import archive_record
from .capture import CaptureProxy
from .command import build_multi_exec_command
from .load import M5ContractError, load_runtime_identity, load_workflow_contract
from .loopback import LOOPBACK_BEARER, _require_executable
from .predicates import evaluate_collaboration
from .rehearsal import CollaborationStub
from .store import capture_dir, persist_archive_record, scratch_root

REHEARSAL_TIMEOUT_SECONDS = 180


class Gate1Error(RuntimeError):
    """Gate 1 runner failed closed before a collaboration verdict."""


def run_gate1_rehearsal(
    *,
    common_root: Path | None = None,
    timeout_seconds: int = REHEARSAL_TIMEOUT_SECONDS,
    persist: bool = True,
) -> dict[str, Any]:
    """Offline full protocol. Not a paid gate 1 pass, even if predicates are green."""

    paths = RepoPaths.discover(Path.cwd()) if common_root is None else None
    root = common_root or paths.common_root
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

    run_id = "m5-g1-rehearsal"
    capture_root = capture_dir(root, run_id)
    capture_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    capture_path = capture_root / "requests.jsonl"
    if capture_path.exists():
        capture_path.unlink()

    stub = CollaborationStub(finding_line=workflow.finding_line)
    scratch = scratch_root(root)
    with tempfile.TemporaryDirectory(prefix="rondo-m5-gate1-", dir=scratch) as raw:
        home = Path(raw) / "codex-home"
        workspace = Path(raw) / "workspace"
        home.mkdir(mode=0o700)
        _copy_fixture(workflow.fixture_dir, workspace)
        (home / "auth.json").write_text(
            json.dumps({"OPENAI_API_KEY": LOOPBACK_BEARER}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(home / "auth.json", 0o600)
        with CaptureProxy(
            mode="stub",
            handler=stub,
            capture_path=capture_path,
        ) as proxy:
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
                "OPENAI_API_KEY": LOOPBACK_BEARER,
            }
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            jsonl = proxy.jsonl()
            request_count = len(proxy.bodies)
            if not jsonl.strip():
                raise Gate1Error(
                    "gate 1 capture is empty: "
                    f"rc={completed.returncode} stderr={_tail(completed.stderr)}"
                )
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

    outcome = "completed" if verdict.passed else "agent_failed"
    record = archive_record(
        evidence_kind="loopback",
        gate=1,
        lock_id=workflow.lock_id,
        side=Side.RONDO,
        product=Product.RONDO_MULTI,
        source_commit=runtime.source_commit,
        binary_sha256=binary_sha,
        outcome=outcome,
        counts_as_effective=False,
        extra={
            "rehearsal": True,
            "passed": verdict.passed,
            "predicates": dict(verdict.predicates),
            "reasons": list(verdict.reasons),
            "ignored_evidence": list(verdict.ignored_evidence),
            "event_id": verdict.event_id,
            "request_count": request_count,
            "stub_finished": stub.finished,
            "stub_errors": list(stub.errors),
            "returncode": completed.returncode,
            "report_present": bool(report_text),
            "tool_surface": "non_code_mode_only=false",
        },
    )
    archived = None
    if persist:
        archived = str(persist_archive_record(record, common_root=root))
    (capture_root / "verdict.json").write_text(
        json.dumps(
            {
                "passed": verdict.passed,
                "predicates": verdict.predicates,
                "reasons": verdict.reasons,
                "ignored_evidence": verdict.ignored_evidence,
                "event_id": verdict.event_id,
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
        "stub_errors": list(stub.errors),
        "stub_finished": stub.finished,
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
