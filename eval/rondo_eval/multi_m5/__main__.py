"""CLI: Multi M-5 offline drills, rehearsal, fake gate 2, and readiness."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ..config import RepoPaths
from .budget import open_phase_b_ledger
from .gate1 import Gate1Error, run_gate1_rehearsal
from .gate2 import ScriptedSlotExecutor, run_light_interleaved
from .load import M5ContractError
from .loopback import LoopbackError, run_frozen_multi_team_publish_loopback
from .ready import readiness_report
from .store import StoreError, scratch_root


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "loopback"
    try:
        paths = RepoPaths.discover(Path.cwd())
        if command == "loopback":
            result = run_frozen_multi_team_publish_loopback(common_root=paths.common_root)
            print(json.dumps(result["record"], sort_keys=True, separators=(",", ":")))
            return 0
        if command == "rehearsal":
            result = run_gate1_rehearsal(common_root=paths.common_root)
            record = result["record"]
            print(json.dumps(record, sort_keys=True, separators=(",", ":")))
            return 0 if record.get("passed") else 1
        if command == "ready":
            report = readiness_report(common_root=paths.common_root)
            print(json.dumps(report, sort_keys=True, indent=2))
            return 0 if report["ready"] else 1
        if command == "gate2-fake":
            scratch = scratch_root(paths.common_root)
            ledger_path = scratch / "multi-m5-gate2-fake-ledger.json"
            if ledger_path.exists():
                ledger_path.unlink()
            lock_path = ledger_path.with_name(f".{ledger_path.name}.lock")
            if lock_path.exists():
                lock_path.unlink()
            archive_file = scratch / "multi-m5-gate2-fake-records.jsonl"
            if archive_file.exists():
                archive_file.unlink()
            with open_phase_b_ledger(ledger_path) as ledger:
                result = run_light_interleaved(
                    executor=ScriptedSlotExecutor(),
                    common_root=paths.common_root,
                    ledger=ledger,
                    persist=True,
                    archive_file=archive_file,
                    charge_fake_usage=True,
                )
            printable = {
                "effective_runs": result["effective_runs"],
                "infra_used": result["infra_used"],
                "conditional_slots": result["conditional_slots"],
                "stopped": result["stopped"],
                "verdicts": result["verdicts"],
                "record_count": len(result["records"]),
                "evidence_kind": "fake",
            }
            print(json.dumps(printable, sort_keys=True, indent=2))
            return 0 if not result["stopped"] else 1
        print("usage: python -m rondo_eval.multi_m5 [loopback|rehearsal|ready|gate2-fake]", file=sys.stderr)
        return 2
    except (LoopbackError, M5ContractError, Gate1Error, StoreError) as exc:
        print(f"rondo-multi-m5: {exc}", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
