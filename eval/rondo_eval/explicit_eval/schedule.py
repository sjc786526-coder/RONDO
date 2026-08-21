"""Deterministic Plan 050 case schedule and identity projection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..contracts import Product, Side, common_multi_agent_v2_override_items
from .contract import CampaignContract, ContractError


_NAMESPACE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")


@dataclass(frozen=True)
class Slot:
    phase: str
    sequence_id: str
    pair_id: str
    task_id: str
    side: str
    ordinal: int

    @property
    def slot_id(self) -> str:
        return f"case-{self.pair_id.lower()}-{self.side}"

    def run_id(self, *, identity_class: str = "rehearsal", attempt: int = 1) -> str:
        if identity_class not in {"rehearsal", "paid"}:
            raise ValueError("unsupported Plan 050 run identity class")
        if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
            raise ValueError("Plan 050 attempt ordinal is invalid")
        return f"plan050-{identity_class}-{self.slot_id}-a{attempt:02d}"

    def rehearsal_run_id(self, attempt: int = 1) -> str:
        return self.run_id(identity_class="rehearsal", attempt=attempt)

    def paid_run_id(self, attempt: int = 1) -> str:
        return self.run_id(identity_class="paid", attempt=attempt)

    def attempt_id(
        self,
        *,
        identity_class: str = "rehearsal",
        attempt: int = 1,
        request_ordinal: int = 1,
    ) -> str:
        if (
            not isinstance(request_ordinal, int)
            or isinstance(request_ordinal, bool)
            or request_ordinal < 1
        ):
            raise ValueError("Plan 050 request ordinal is invalid")
        return (
            f"{self.run_id(identity_class=identity_class, attempt=attempt)}"
            f"-request-{request_ordinal:03d}"
        )


def slots(contract: CampaignContract) -> tuple[Slot, ...]:
    pairs = contract.taskset.get("case_pairs")
    if not isinstance(pairs, list):
        raise ContractError("Plan 050 case schedule is absent")
    result: list[Slot] = []
    ordinal = 0
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ContractError("Plan 050 case pair is invalid")
        side_order = pair.get("side_order")
        if not isinstance(side_order, list):
            raise ContractError("Plan 050 case side order is invalid")
        for side in side_order:
            ordinal += 1
            result.append(
                Slot(
                    phase="case",
                    sequence_id=f"S{ordinal:02d}",
                    pair_id=str(pair["pair_id"]),
                    task_id=str(pair["task_id"]),
                    side=str(side),
                    ordinal=ordinal,
                )
            )
    if (
        len(result) != 6
        or [slot.sequence_id for slot in result]
        != ["S01", "S02", "S03", "S04", "S05", "S06"]
        or any(slot.phase != "case" for slot in result)
    ):
        raise ContractError("Plan 050 six-slot schedule differs")
    return tuple(result)


def dry_run_projection(
    contract: CampaignContract,
    *,
    common_root: Path,
    namespace: str = "phase-a-final",
) -> dict[str, Any]:
    if _NAMESPACE.fullmatch(namespace) is None:
        raise ValueError("Plan 050 rehearsal namespace is invalid")
    ignored_root = Path(common_root).resolve() / contract.lock["artifacts"][
        "ignored_root"
    ]
    root = ignored_root / "rehearsal" / namespace
    if not root.is_relative_to(Path(common_root).resolve() / "eval-data" / "plan-050"):
        raise ContractError("Plan 050 rehearsal path escaped its ignored root")

    rows: list[dict[str, Any]] = []
    for slot in slots(contract):
        run_id = slot.rehearsal_run_id()
        run_root = root / "runs" / run_id
        task = contract.task_contract(slot.task_id)
        rows.append(
            {
                "ordinal": slot.ordinal,
                "sequence_id": slot.sequence_id,
                "phase": slot.phase,
                "pair_id": slot.pair_id,
                "task_id": slot.task_id,
                "side": slot.side,
                "product": None if slot.side == "codex" else "rondo-multi",
                "identity_class": "rehearsal",
                "slot_id": slot.slot_id,
                "run_id": run_id,
                "attempt_id": slot.attempt_id(),
                "task_contract": {
                    "instruction": "terminal_bench_native_unmodified",
                    "source_digest": task["source_digest"],
                    "image_ref": task["image_ref"],
                    "workdir": task["workdir"],
                    "memory_mb": task["memory_mb"],
                    "pids_limit": task["pids_limit"],
                    "timeout_seconds": task["timeout_seconds"],
                    "agent_timeout_seconds": task["agent_timeout_seconds"],
                    "verifier_timeout_seconds": task["verifier_timeout_seconds"],
                    "build_timeout_seconds": task["build_timeout_seconds"],
                    "requires_existing_git_repo": task[
                        "requires_existing_git_repo"
                    ],
                },
                "expected": {
                    "trace": str(run_root / "rollout-trace"),
                    "settled": str(run_root / "settled.json"),
                    "execution": str(run_root / "execution.json"),
                    "api_metadata": str(run_root / "api-metadata.json"),
                    "team_view": str(run_root / "team_view.json"),
                    "team_report": str(run_root / "team_report.html"),
                    "run_record": str(run_root / "run.json"),
                },
            }
        )

    provider = contract.lock["provider"]
    execution = contract.lock["execution"]
    budget = contract.lock["budget"]
    return {
        "schema_version": 1,
        "evidence_kind": "rehearsal",
        "identity_class": "rehearsal",
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "taskset_sha256": contract.taskset_sha256,
        "policy_sha256": contract.policy_sha256,
        "namespace": namespace,
        "identity_contract": {
            "phase": "case",
            "sequence_ids": [f"S{ordinal:02d}" for ordinal in range(1, 7)],
            "rehearsal_run_prefix": "plan050-rehearsal-case-",
            "paid_run_prefix": "plan050-paid-case-",
            "attempt_suffix": "-aNN",
            "request_suffix": "-request-NNN",
            "rehearsal_namespace": budget["rehearsal_namespace"],
            "formal_namespace": budget["formal_namespace"],
            "batch_id": budget["batch_id"],
        },
        "ledger": str(root / "rehearsal-ledger.json"),
        "archive": str(root / "records.jsonl"),
        "aggregate": str(root / contract.lock["artifacts"]["aggregate"]),
        "case_reports": {
            pair["pair_id"]: str(
                root
                / contract.lock["artifacts"]["case_directory"]
                / contract.lock["artifacts"]["case_file_pattern"].format(
                    pair_id=pair["pair_id"]
                )
            )
            for pair in contract.taskset["case_pairs"]
        },
        "overview": str(root / contract.lock["artifacts"]["overview"]),
        "budget_contract": {
            "maximum_authorizable_cap_usd": budget[
                "maximum_authorizable_cap_usd"
            ],
            "actual_cap_usd": budget["actual_cap_usd"],
            "actual_cap_binding": budget["actual_cap_binding"],
            "rehearsal_cost_usd": "0.00",
        },
        "execution_contract": {
            "slot_concurrency": execution["terminal_bench_slot_concurrency"],
            "provider_request_concurrency": execution[
                "provider_request_concurrency"
            ],
            "max_concurrent_threads_per_session": execution[
                "max_concurrent_threads_per_session"
            ],
            "request_limit_per_run": provider["request_limit_per_run"],
            "request_attempt_limit": provider["request_attempt_limit"],
            "retry_backoff_seconds": provider["retry_backoff_seconds"],
            "retry_statuses": provider["retry_statuses"],
            "root": {
                "model": provider["root_model"],
                "effort": provider["root_effort"],
            },
            "member": {
                "model": provider["member_model"],
                "effort": provider["member_effort"],
            },
            "guardian": {
                "model": provider["guardian_model"],
                "effort": provider["guardian_effort"],
            },
        },
        "side_command_contract": {
            "codex": _side_command_contract(contract, Side.CODEX),
            "rondo": _side_command_contract(contract, Side.RONDO),
        },
        "slots": rows,
    }


def _side_command_contract(
    contract: CampaignContract, side: Side
) -> dict[str, Any]:
    provider = contract.lock["provider"]
    execution = contract.lock["execution"]
    product = None if side is Side.CODEX else Product.RONDO_MULTI
    return {
        "config_overrides": list(
            common_multi_agent_v2_override_items(
                side,
                product,
                subagent_model=provider["member_model"],
                subagent_effort=provider["member_effort"],
                max_concurrency=execution[
                    "max_concurrent_threads_per_session"
                ],
            )
        ),
        "root_model": provider["root_model"],
        "root_effort": provider["root_effort"],
        "member_model": provider["member_model"],
        "member_effort": provider["member_effort"],
        "guardian_model": provider["guardian_model"],
        "guardian_effort": provider["guardian_effort"],
        "developer_instructions_sha256": contract.policy_sha256,
        "rollout_trace_root": execution["rollout_trace_root"],
        "team_state": None if side is Side.CODEX else True,
    }
