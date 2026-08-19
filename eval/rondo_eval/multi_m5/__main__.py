"""CLI: Multi M-5 offline drills, rehearsal, fake gate 2, readiness, and locked paid entries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import re

from ..config import RepoPaths, load_provider_secret, load_runtime_config
from ..api_budget_proxy import ApiBudgetProxyError, exposure_summary
from ..provider_probe import ProviderProbeError, run_provider_probes
from .budget import open_phase_b_ledger, open_smoke_ledger, require_frozen_provider
from .gate1 import Gate1Error, run_gate1_paid, run_gate1_rehearsal, run_gate1_smoke
from .gate2 import Gate2Error, ScriptedSlotExecutor, run_gate2_real, run_light_interleaved
from .load import M5ContractError, load_workflow_contract
from .loopback import LoopbackError, run_frozen_multi_team_publish_loopback
from .paid import PaidAuthError, authorization_from_phrases
from .ready import readiness_report
from .store import (
    StoreError,
    budget_ledger_path,
    scratch_root,
    smoke_archive_path,
    smoke_ledger_path,
)

_SAFE_LABEL = re.compile(r"[a-z0-9][a-z0-9-]{0,31}\Z")

_USAGE = (
    "usage: python -m rondo_eval.multi_m5 "
    "[loopback|rehearsal|ready|gate2-fake|smoke --label <id>|gate1-paid|gate2-real]"
)


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
                "diagnostic_slots": result["diagnostic_slots"],
                "diagnostics": result["diagnostics"],
                "stopped": result["stopped"],
                "verdicts": result["verdicts"],
                "passed": result["passed"],
                "record_count": len(result["records"]),
                "evidence_kind": "fake",
            }
            print(json.dumps(printable, sort_keys=True, indent=2))
            return 0 if result["passed"] else 1
        if command == "gate1-paid":
            auth = authorization_from_phrases(api_phrase=_option(args, "--authorize-paid-api"))
            config = load_runtime_config(paths)
            _name, api_key = load_provider_secret(config)
            # Pinned by the gate 1 lock rather than the host-wide alias, so the
            # frozen sol campaigns on this machine keep their provider identity.
            provider = config.paid_provider_projection(
                model_id=load_workflow_contract().root_model
            )
            with open_phase_b_ledger(budget_ledger_path(paths.common_root)) as ledger:
                result = run_gate1_paid(
                    authorization=auth,
                    api_key=api_key,
                    upstream_base_url=provider.base_url,
                    ledger=ledger,
                    common_root=paths.common_root,
                    provider=provider,
                )
            print(json.dumps(result["record"], sort_keys=True, separators=(",", ":")))
            return 0 if result["record"].get("passed") else 1
        if command == "smoke":
            # Separately authorized pre-contract check: does the provider serve
            # the frozen model, and does one whole code-mode flow produce
            # readable trace evidence. Own ledger, own archive, own lock id;
            # never a gate 1 attempt. Each invocation needs its own --label so
            # two runs can never share a run id, a ledger row or a capture.
            # The label is checked first: a run without a fresh identity is
            # refused before authorization, secrets, or sockets are considered.
            label = _option(args, "--label")
            if not label or not _SAFE_LABEL.fullmatch(label):
                print(
                    "smoke requires --label <fresh-alphanumeric-id>",
                    file=sys.stderr,
                )
                return 2
            auth = authorization_from_phrases(api_phrase=_option(args, "--authorize-paid-api"))
            config = load_runtime_config(paths)
            _name, api_key = load_provider_secret(config)
            workflow = load_workflow_contract()
            model_id = workflow.root_model
            provider = config.paid_provider_projection(model_id=model_id)
            # Freeze-check the endpoint, model and rates *before* anything is
            # sent. The probe used to run first, which meant the first real
            # request left the process before the contract was verified and put
            # its spend outside the cap the smoke test claimed to enforce.
            identity = require_frozen_provider(provider, effort=workflow.root_effort)
            run_id = f"m5-g1-smoke-{label}"
            with open_smoke_ledger(smoke_ledger_path(paths.common_root)) as ledger:
                try:
                    probe = run_provider_probes(
                        config,
                        api_key,
                        output_root=(
                            scratch_root(paths.common_root) / f"multi-m5-probe-{label}"
                        ),
                        model_id=model_id,
                    )
                except (ApiBudgetProxyError, ProviderProbeError, OSError, ValueError) as exc:
                    print(
                        json.dumps(
                            {
                                "stage": "probe",
                                "model": model_id,
                                "probe_ok": False,
                                "error": type(exc).__name__,
                                "detail": str(exc)[:400],
                            },
                            sort_keys=True,
                            indent=2,
                        )
                    )
                    return 1
                if probe.get("status") != "completed":
                    print(
                        json.dumps(
                            {"stage": "probe", "model": model_id, "probe_ok": False, "probe": probe},
                            sort_keys=True,
                            indent=2,
                            default=str,
                        )
                    )
                    return 1
                result = run_gate1_smoke(
                    authorization=auth,
                    api_key=api_key,
                    upstream_base_url=identity["provider_base_url"],
                    ledger=ledger,
                    provider=provider,
                    run_id=run_id,
                    archive_path=smoke_archive_path(paths.common_root),
                    common_root=paths.common_root,
                )
                spend = ledger.snapshot()
                exposure = exposure_summary(spend)
            record = result["record"]
            print(
                json.dumps(
                    {
                        "stage": "flow",
                        "model": model_id,
                        "run_id": run_id,
                        "probe_ok": True,
                        "outcome": record.get("outcome"),
                        "flow_completed": record.get("passed"),
                        "predicates": record.get("predicates"),
                        "reasons": record.get("reasons"),
                        "trace_error": record.get("trace_error"),
                        "request_count": record.get("request_count"),
                        "returncode": record.get("returncode"),
                        "batch_id": spend.get("batch_id"),
                        "charged_usd": spend.get("spent_usd"),
                        # Priced spend and conservatively debited reservations,
                        # kept apart so a usage-less failure is not read as money
                        # the provider actually took.
                        "budget_exposure": exposure,
                        "remaining_uncommitted_usd": spend.get(
                            "remaining_uncommitted_usd"
                        ),
                        "note": "smoke only; not a gate 1 pass and not a gate 1 attempt",
                    },
                    sort_keys=True,
                    indent=2,
                )
            )
            return 0 if record.get("outcome") == "completed" else 1
        if command == "gate2-real":
            auth = authorization_from_phrases(
                api_phrase=_option(args, "--authorize-paid-api"),
                docker_phrase=_option(args, "--authorize-docker"),
            )
            auth.require_api_and_docker()
            from ..docker_supervisor import HeavyLockLease
            from ..runtime_bridge import (
                DockerCliCounter,
                PowerShellDockerDesktopHostProbe,
                lease_from_watchdog,
            )

            config = load_runtime_config(paths)
            _name, api_key = load_provider_secret(config)
            proof = lease_from_watchdog()
            counter = DockerCliCounter(
                host_data_root=paths.common_root / "eval-data" / "docker-host",
                desktop_host_probe=PowerShellDockerDesktopHostProbe(),
            )
            with open_phase_b_ledger(budget_ledger_path(paths.common_root)) as ledger:
                result = run_gate2_real(
                    authorization=auth,
                    api_key=api_key,
                    ledger=ledger,
                    common_root=paths.common_root,
                    config=config,
                    counter=counter,
                    lock_guard=proof.guard,
                    lease=HeavyLockLease(proof.lease.token, proof.lease.held),
                )
            printable = {
                "effective_runs": result["effective_runs"],
                "infra_used": result["infra_used"],
                "stopped": result["stopped"],
                "stop_reason": result["stop_reason"],
                # Attribution evidence for any degraded task. Present only when a
                # degradation was actually found; it never changes the verdict.
                "diagnostic_slots": result["diagnostic_slots"],
                "diagnostics": result["diagnostics"],
                # A degradation verdict or incomplete evidence is an M-5 failure,
                # so it must not leave the shell with a success status.
                "verdicts": result["verdicts"],
                "passed": result["passed"],
                "record_count": len(result["records"]),
                "evidence_kind": "real_api",
            }
            print(json.dumps(printable, sort_keys=True, indent=2))
            return 0 if result["passed"] else 1
        print(_USAGE, file=sys.stderr)
        return 2
    except (LoopbackError, M5ContractError, Gate1Error, Gate2Error, StoreError, PaidAuthError) as exc:
        print(f"rondo-multi-m5: {exc}", file=sys.stderr)
        return 78


def _option(args: list[str], name: str) -> str | None:
    if name not in args:
        return None
    index = args.index(name)
    if index + 1 >= len(args):
        return None
    return args[index + 1]


if __name__ == "__main__":
    raise SystemExit(main())
