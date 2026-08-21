"""Deterministic Plan 049 schedule and rehearsal identity projection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from ..contracts import Product, Side, common_multi_agent_v2_override_items
from .contract import CampaignContract


@dataclass(frozen=True)
class Slot:
    phase: str
    pair_id: str
    task_id: str
    side: str
    ordinal: int
    run_prefix: str = "plan049"

    @property
    def slot_id(self) -> str:
        return f"{self.phase}-{self.pair_id.lower()}-{self.side}"

    def run_id(self, attempt: int = 1) -> str:
        return f"{self.run_prefix}-rehearsal-{self.slot_id}-a{attempt:02d}"


def slots(
    contract: CampaignContract,
    phases: Iterable[str] | None = None,
) -> tuple[Slot, ...]:
    result: list[Slot] = []
    ordinal = 0
    available = (
        ("case",)
        if "case_pairs" in contract.taskset
        else ("pilot", "formal")
    )
    selected = tuple(available if phases is None else phases)
    run_prefix = f"plan{contract.lock['plan']}"
    for phase in selected:
        if phase not in available:
            raise ValueError("unsupported campaign phase")
        for pair in contract.taskset[f"{phase}_pairs"]:
            for side in pair["side_order"]:
                ordinal += 1
                result.append(
                    Slot(
                        phase=phase,
                        pair_id=pair["pair_id"],
                        task_id=pair["task_id"],
                        side=side,
                        ordinal=ordinal,
                        run_prefix=run_prefix,
                    )
                )
    return tuple(result)


def dry_run_projection(
    contract: CampaignContract,
    *,
    common_root: Path,
    namespace: str = "phase-a-final",
) -> dict[str, Any]:
    root = (
        Path(common_root).resolve()
        / str(contract.lock["artifacts"]["ignored_root"])
        / "rehearsal"
        / namespace
    )
    rows = []
    catalog = {item["task_id"]: item for item in contract.catalog["tasks"]}
    for slot in slots(contract):
        run_root = root / "runs" / slot.run_id()
        task = catalog[slot.task_id]
        rows.append(
            {
                "ordinal": slot.ordinal,
                "phase": slot.phase,
                "pair_id": slot.pair_id,
                "task_id": slot.task_id,
                "side": slot.side,
                "product": None if slot.side == "codex" else "rondo-multi",
                "identity_class": "rehearsal",
                "slot_id": slot.slot_id,
                "run_id": slot.run_id(),
                "attempt_id": f"{slot.run_id()}-request-001",
                "task_contract": {
                    "instruction": "terminal_bench_native_unmodified",
                    "source_digest": task["source_digest"],
                    "image_ref": task["image_ref"],
                    "timeout_seconds": task["timeout_seconds"],
                    "agent_timeout_seconds": task["agent_timeout_seconds"],
                    "verifier_timeout_seconds": task["verifier_timeout_seconds"],
                },
                "expected": {
                    "trace": str(run_root / "rollout-trace"),
                    "team_view": str(run_root / "team_view.json"),
                    "team_report": str(run_root / "team_report.html"),
                    "run_record": str(run_root / "run.json"),
                },
            }
        )
    return {
        "schema_version": 1,
        "evidence_kind": "rehearsal",
        "identity_class": "rehearsal",
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "policy_sha256": contract.policy_sha256,
        "namespace": namespace,
        "ledger": str(root / "rehearsal-ledger.json"),
        "archive": str(root / "records.jsonl"),
        "aggregate": str(root / "aggregate.json"),
        "execution_contract": {
            "slot_concurrency": contract.lock["execution"][
                "terminal_bench_slot_concurrency"
            ],
            "provider_request_concurrency": contract.lock["execution"][
                "provider_request_concurrency"
            ],
            "request_limit_per_run": contract.lock["provider"][
                "request_limit_per_run"
            ],
            "request_attempt_limit": contract.lock["provider"][
                "request_attempt_limit"
            ],
            "retry_backoff_seconds": contract.lock["provider"][
                "retry_backoff_seconds"
            ],
            "retry_statuses": contract.lock["provider"]["retry_statuses"],
        },
        "side_command_contract": {
            "codex": {
                "config_overrides": list(
                    common_multi_agent_v2_override_items(
                        Side.CODEX,
                        None,
                        subagent_model=contract.lock["provider"]["member_model"],
                        subagent_effort=contract.lock["provider"]["member_effort"],
                        max_concurrency=contract.lock["execution"][
                            "max_concurrent_threads_per_session"
                        ],
                    )
                ),
                "developer_instructions_sha256": contract.policy_sha256,
                "rollout_trace_root": contract.lock["execution"]["rollout_trace_root"],
                "team_state": None,
            },
            "rondo": {
                "config_overrides": list(
                    common_multi_agent_v2_override_items(
                        Side.RONDO,
                        Product.RONDO_MULTI,
                        subagent_model=contract.lock["provider"]["member_model"],
                        subagent_effort=contract.lock["provider"]["member_effort"],
                        max_concurrency=contract.lock["execution"][
                            "max_concurrent_threads_per_session"
                        ],
                    )
                ),
                "developer_instructions_sha256": contract.policy_sha256,
                "rollout_trace_root": contract.lock["execution"]["rollout_trace_root"],
                "team_state": True,
            },
        },
        "slots": rows,
    }
