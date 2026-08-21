"""One authorized, offline recovery generation for Plan 049's first paid slot."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from ..api_budget_proxy import load_validated_budget_ledger_state
from ..contracts import ProviderProjection
from ..team_lens.model import dump_team_view, validate_team_view
from ..team_lens.report import render_report
from ..terminal_bench.results import parse_single_task_result
from .aggregate import aggregate
from .contract import CampaignContract
from .formal import (
    FormalExecutionResult,
    FormalPaths,
    FormalStore,
    formal_identity,
    formal_paths,
    open_paid_ledger,
)
from .schedule import slots
from .store import assert_body_free
from .trace import select_proactive_root_bundle


RECOVERY_ID = "plan-049-paid-v1-recovery-v1"
RECOVERY_ACTION = "CREATE RONDO PLAN 049 PAID RECOVERY IDENTITY V1"
SOURCE_HARNESS_COMMIT = "2b30b8e5e2fdc819c5d49fc05c6adfaae48aac02"
SOURCE_RUN_ID = "plan049-paid-pilot-p01-codex-a01"
SOURCE_FORMAL_IDENTITY_SHA256 = (
    "9d5aa22f80a27b1aa4b9e43926e7561722f8771fc7f8b2526d010002698f87f6"
)
SOURCE_RECEIPT_SHA256 = (
    "63ed6879b5ffe3721b5844b8db11ed296acc6679d74e1463c01d425926ecf2b7"
)
SOURCE_LEDGER_SHA256 = (
    "18009611f9fc49941ff5ef81884816f46f93c953195f2e5e906d1a9311710d70"
)
SOURCE_RECORD_SHA256 = (
    "5fd5cb2e07fde766e344175ed41ead5c2d04d6c348f6b3b78c85a3c9acf62c11"
)
SOURCE_API_METADATA_SHA256 = (
    "0dd0cc02dce9387fca26d51ec74881fdfb03f399b2c5570e33b1dab069260459"
)
SOURCE_TB_RESULT_SHA256 = (
    "56a3e78f76e4b3da14f7d19c07f9d28f8d418b2f73e63fa0f4eaaa9bd939fba7"
)
SOURCE_PREFLIGHT_SHA256 = (
    "ab879113e17e09a7fd35c6b22147f8721a8c6474168f421679cb7ba32b5aa406"
)
SOURCE_ROOT_TREE_SHA256 = (
    "6d6927bc9a2ed601d891a2cb4efb0cc0409df4d55e2ee112fc5029fa87eb98d1"
)
SOURCE_TRACE_TREE_SHA256 = (
    "35b72b179dc2587f75ec0754f607541d9f68100a02fbebcab1c405b3754bacee"
)
SOURCE_COST_USD = Decimal("0.262759")
RECOVERY_REMAINING_USD = Decimal("99.737241")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


class RecoveryError(RuntimeError):
    """The historical paid sample cannot be carried forward unambiguously."""


@dataclass(frozen=True)
class RecoveryPaths:
    formal: FormalPaths
    binding: Path
    receipt: Path
    import_aggregate: Path


@dataclass(frozen=True)
class RecoveryContext:
    paths: RecoveryPaths
    identity: dict[str, Any]
    binding_sha256: str
    prior_spend_usd: Decimal
    remaining_usd: Decimal


@dataclass(frozen=True)
class _SourceEvidence:
    binding: dict[str, Any]
    binding_sha256: str
    root_view: dict[str, Any]
    ledger_bytes: bytes
    ledger_state: dict[str, Any]
    request_preflight_sha256: str


def recovery_paths(
    common_root: Path,
    contract: CampaignContract,
    *,
    recovery_id: str = RECOVERY_ID,
) -> RecoveryPaths:
    if recovery_id != RECOVERY_ID:
        raise RecoveryError("Plan 049 recovery identity is not authorized")
    source_namespace = str(contract.lock["budget"]["formal_namespace"])
    if source_namespace != "plan-049-paid-v1":
        raise RecoveryError("Plan 049 recovery source namespace drifted")
    root = (
        Path(common_root).resolve()
        / "eval-data"
        / "plan-049"
        / "paid"
        / recovery_id
    )
    formal = FormalPaths(
        root=root,
        receipt=root / "activation-receipt.json",
        ledger=root / "budget-ledger.json",
        archive=root / "records.jsonl",
        aggregate=root / "aggregate.json",
        runs=root / "runs",
    )
    return RecoveryPaths(
        formal=formal,
        binding=root / "recovery-binding.json",
        receipt=root / "recovery-receipt.json",
        import_aggregate=root / "recovery-import-aggregate.json",
    )


def prepare_recovery_prefix(
    contract: CampaignContract,
    *,
    common_root: Path,
    provider: ProviderProjection,
    recovery_harness_commit: str,
    recovery_action: str | None,
    recovery_id: str = RECOVERY_ID,
) -> dict[str, Any]:
    """Create the new prefix without provider, network, or Docker I/O."""

    if recovery_action != RECOVERY_ACTION:
        raise RecoveryError("Plan 049 recovery action is absent")
    if _COMMIT.fullmatch(recovery_harness_commit) is None:
        raise RecoveryError("Plan 049 recovery harness commit is invalid")
    evidence = _load_source_evidence(
        contract,
        common_root=common_root,
        provider=provider,
        recovery_harness_commit=recovery_harness_commit,
        recovery_id=recovery_id,
    )
    paths = recovery_paths(common_root, contract, recovery_id=recovery_id)
    _write_private_or_verify(
        paths.binding, _canonical(evidence.binding) + b"\n"
    )
    identity = recovery_formal_identity(
        contract,
        provider=provider,
        recovery_harness_commit=recovery_harness_commit,
        binding_sha256=evidence.binding_sha256,
        recovery_id=recovery_id,
    )
    store = FormalStore(paths.formal, identity)
    store.ensure_receipt()
    _write_private_or_verify(paths.formal.ledger, evidence.ledger_bytes)
    first = slots(contract)[0]
    if (
        first.slot_id != "pilot-p01-codex"
        or first.task_id != "terminal-bench/filter-js-from-html"
        or first.side != "codex"
    ):
        raise RecoveryError("Plan 049 first paid slot drifted")
    view = evidence.root_view
    validate_team_view(view)
    view_bytes = dump_team_view(view)
    report_bytes = render_report(view)
    run_root = store.run_root(SOURCE_RUN_ID)
    _write_private_or_verify(run_root / "team_view.json", view_bytes)
    _write_private_or_verify(run_root / "team_report.html", report_bytes)
    result = FormalExecutionResult(
        outcome="task_failed",
        trace_status="available",
        team_view_sha256=hashlib.sha256(view_bytes).hexdigest(),
        team_report_sha256=hashlib.sha256(report_bytes).hexdigest(),
        request_preflight_sha256=evidence.request_preflight_sha256,
        reason_code="task_native_verifier_failed",
    )
    store.write_execution(
        SOURCE_RUN_ID,
        slot=first,
        attempt=1,
        result=result,
    )
    with open_paid_ledger(paths.formal.ledger, contract) as ledger:
        snapshot = ledger.snapshot()
        _require_recovered_ledger(snapshot)
        row = _recovered_record(
            contract,
            store=store,
            result=result,
            slot=first,
            ledger_snapshot=snapshot,
        )
    store.publish(row)
    store.append(row)
    aggregate_value = aggregate(
        [row],
        {SOURCE_RUN_ID: view},
        lock_id=contract.lock_id,
        lock_sha256=contract.lock_sha256,
        policy_sha256=contract.policy_sha256,
        expected_slots={slot.slot_id: slot.pair_id for slot in slots(contract)},
        evidence_kind="real_api",
        identity_class="paid",
    )
    store.write_aggregate(aggregate_value)
    _write_private_or_verify(
        paths.import_aggregate, _canonical(aggregate_value) + b"\n"
    )
    receipt = _recovery_receipt(
        paths,
        store=store,
        binding_sha256=evidence.binding_sha256,
        row=row,
    )
    _write_private_or_verify(paths.receipt, _canonical(receipt) + b"\n")
    context = require_safe_recovery_prefix(
        contract,
        common_root=common_root,
        provider=provider,
        recovery_harness_commit=recovery_harness_commit,
        recovery_id=recovery_id,
    )
    return {
        "schema_version": 1,
        "identity_class": "paid_recovery",
        "recovery_id": recovery_id,
        "formal_identity_sha256": store.identity_sha256,
        "binding_sha256": context.binding_sha256,
        "source_run_id": SOURCE_RUN_ID,
        "source_outcome": "completed",
        "source_reward": "0.0",
        "recovered_outcome": "task_failed",
        "request_count": 15,
        "prior_spend_usd": _money_text(context.prior_spend_usd),
        "remaining_authorized_usd": _money_text(context.remaining_usd),
        "next_slot_id": "pilot-p01-rondo",
        "provider_requests": 0,
        "docker_runs": 0,
    }


def require_safe_recovery_prefix(
    contract: CampaignContract,
    *,
    common_root: Path,
    provider: ProviderProjection,
    recovery_harness_commit: str,
    recovery_id: str = RECOVERY_ID,
) -> RecoveryContext:
    """Purely read and verify both generations before paid resources exist."""

    evidence = _load_source_evidence(
        contract,
        common_root=common_root,
        provider=provider,
        recovery_harness_commit=recovery_harness_commit,
        recovery_id=recovery_id,
    )
    paths = recovery_paths(common_root, contract, recovery_id=recovery_id)
    binding = _read_private_json(paths.binding, "recovery binding")
    if binding != evidence.binding:
        raise RecoveryError("Plan 049 recovery binding differs")
    identity = recovery_formal_identity(
        contract,
        provider=provider,
        recovery_harness_commit=recovery_harness_commit,
        binding_sha256=evidence.binding_sha256,
        recovery_id=recovery_id,
    )
    store = FormalStore(paths.formal, identity, create=False)
    store.require_receipt()
    records = store.records()
    if not records:
        raise RecoveryError("Plan 049 recovery archive lacks its imported run")
    row = records[0]
    if not _is_recovered_record(row):
        raise RecoveryError("Plan 049 recovered paid record differs")
    marker = store.marker(SOURCE_RUN_ID)
    if marker != row:
        raise RecoveryError("Plan 049 recovery marker differs")
    recovered_run_root = store.run_root(SOURCE_RUN_ID)
    expected_recovered_artifacts = {
        "execution.json",
        "run.json",
        "team_report.html",
        "team_view.json",
    }
    try:
        recovered_artifacts = {
            child.name for child in recovered_run_root.iterdir()
        }
    except OSError as exc:
        raise RecoveryError("Plan 049 recovered run root is unreadable") from exc
    if recovered_artifacts != expected_recovered_artifacts or any(
        child.is_symlink()
        or not child.is_file()
        or stat.S_IMODE(child.stat().st_mode) != 0o600
        for child in recovered_run_root.iterdir()
    ):
        raise RecoveryError("Plan 049 recovered run contains unknown artifacts")
    first = slots(contract)[0]
    execution = store.execution(SOURCE_RUN_ID, slot=first, attempt=1)
    if (
        execution is None
        or execution.outcome != "task_failed"
        or execution.request_preflight_sha256 != SOURCE_PREFLIGHT_SHA256
    ):
        raise RecoveryError("Plan 049 recovered execution differs")
    budget = contract.lock["budget"]
    ledger = load_validated_budget_ledger_state(
        paths.formal.ledger,
        batch_id=str(budget["batch_id"]),
        total_cap_usd=str(budget["phase_b_hard_cap_usd"]),
        max_runs=int(budget["max_run_slots"]),
        default_run_cap_usd=str(budget["per_run_cap_usd"]),
    )
    _require_carried_ledger(ledger, evidence.ledger_state)
    expected_receipt = _recovery_receipt(
        paths,
        store=store,
        binding_sha256=evidence.binding_sha256,
        row=row,
    )
    if _read_private_json(paths.receipt, "recovery receipt") != expected_receipt:
        raise RecoveryError("Plan 049 recovery receipt differs")
    aggregate_value = _read_private_json(
        paths.import_aggregate, "recovery import aggregate"
    )
    recovered_view = _read_json(
        store.run_root(SOURCE_RUN_ID) / "team_view.json",
        "recovered Team View",
    )
    expected_aggregate = aggregate(
        [row],
        {SOURCE_RUN_ID: recovered_view},
        lock_id=contract.lock_id,
        lock_sha256=contract.lock_sha256,
        policy_sha256=contract.policy_sha256,
        expected_slots={slot.slot_id: slot.pair_id for slot in slots(contract)},
        evidence_kind="real_api",
        identity_class="paid",
    )
    if aggregate_value != expected_aggregate:
        raise RecoveryError("Plan 049 recovery aggregate differs")
    return RecoveryContext(
        paths=paths,
        identity=identity,
        binding_sha256=evidence.binding_sha256,
        prior_spend_usd=SOURCE_COST_USD,
        remaining_usd=RECOVERY_REMAINING_USD,
    )


def recovery_formal_identity(
    contract: CampaignContract,
    *,
    provider: ProviderProjection,
    recovery_harness_commit: str,
    binding_sha256: str,
    recovery_id: str = RECOVERY_ID,
) -> dict[str, Any]:
    if recovery_id != RECOVERY_ID or _SHA256.fullmatch(binding_sha256) is None:
        raise RecoveryError("Plan 049 recovery formal identity is invalid")
    identity = formal_identity(
        contract,
        provider=provider,
        harness_commit=recovery_harness_commit,
    )
    identity.update(
        {
            "campaign_generation": RECOVERY_ID,
            "recovery_binding_sha256": binding_sha256,
            "source_harness_commit": SOURCE_HARNESS_COMMIT,
            "prior_campaign_exposure_usd": _money_text(SOURCE_COST_USD),
            "remaining_authorized_usd_at_recovery": _money_text(
                RECOVERY_REMAINING_USD
            ),
            "operator_confirmed_balance_covers_remaining": True,
        }
    )
    assert_body_free(identity)
    return identity


def _load_source_evidence(
    contract: CampaignContract,
    *,
    common_root: Path,
    provider: ProviderProjection,
    recovery_harness_commit: str,
    recovery_id: str,
) -> _SourceEvidence:
    if recovery_id != RECOVERY_ID:
        raise RecoveryError("Plan 049 recovery identity is not authorized")
    source = formal_paths(common_root, contract)
    expected_source_identity = formal_identity(
        contract,
        provider=provider,
        harness_commit=SOURCE_HARNESS_COMMIT,
    )
    source_store = FormalStore(source, expected_source_identity, create=False)
    source_store.require_receipt()
    receipt_bytes = _read_regular_bytes(source.receipt, "source receipt")
    ledger_bytes = _read_regular_bytes(source.ledger, "source ledger")
    archive_bytes = _read_regular_bytes(source.archive, "source archive")
    _require_sha(receipt_bytes, SOURCE_RECEIPT_SHA256, "source receipt")
    _require_sha(ledger_bytes, SOURCE_LEDGER_SHA256, "source ledger")
    _require_sha(archive_bytes, SOURCE_RECORD_SHA256, "source archive")
    records = source_store.records()
    if len(records) != 1 or not _is_source_stop_record(records[0]):
        raise RecoveryError("Plan 049 recovery source record differs")
    run_root = source_store.run_root(SOURCE_RUN_ID)
    run_entries = list(source.runs.iterdir())
    if (
        run_root.is_symlink()
        or not run_root.is_dir()
        or len(run_entries) != 1
        or run_entries[0] != run_root
    ):
        raise RecoveryError("Plan 049 recovery source contains another attempt")
    marker_bytes = _read_regular_bytes(run_root / "run.json", "source run marker")
    _require_sha(marker_bytes, SOURCE_RECORD_SHA256, "source run marker")
    if source_store.marker(SOURCE_RUN_ID) != records[0]:
        raise RecoveryError("Plan 049 recovery source marker differs")
    budget = contract.lock["budget"]
    ledger = load_validated_budget_ledger_state(
        source.ledger,
        batch_id=str(budget["batch_id"]),
        total_cap_usd=str(budget["phase_b_hard_cap_usd"]),
        max_runs=int(budget["max_run_slots"]),
        default_run_cap_usd=str(budget["per_run_cap_usd"]),
    )
    _require_recovered_ledger(ledger)
    api_path = run_root / "api-metadata.json"
    api_bytes = _read_regular_bytes(api_path, "source API metadata")
    _require_sha(api_bytes, SOURCE_API_METADATA_SHA256, "source API metadata")
    metadata = _read_json(api_path, "source API metadata")
    request_preflight = _reconstruct_preflight(contract, metadata, ledger)
    if request_preflight != SOURCE_PREFLIGHT_SHA256:
        raise RecoveryError("Plan 049 source request preflight differs")
    trial_root = run_root / "staging" / "trials"
    trials = _safe_child_directories(trial_root, "source trials")
    if len(trials) != 1:
        raise RecoveryError("Plan 049 recovery source trial is ambiguous")
    trial = trials[0]
    result_path = trial / "result.json"
    result_bytes = _read_regular_bytes(result_path, "source Terminal-Bench result")
    _require_sha(result_bytes, SOURCE_TB_RESULT_SHA256, "source Terminal-Bench result")
    parsed = parse_single_task_result(
        trial,
        host_returncode=0,
        expected_task_id=slots(contract)[0].task_id,
    )
    if parsed.outcome.value != "completed" or parsed.reward != 0.0:
        raise RecoveryError("Plan 049 source task result is not the frozen failure")
    trace_root = trial / "agent" / "rollout-trace"
    selected = select_proactive_root_bundle(trace_root, product="codex")
    view = selected.root_view
    validate_team_view(view)
    if (
        selected.guardian_bundle_count != 1
        or view["source"]["product"] != "codex"
        or view["summary"]["inference_count"] != 15
        or view["summary"]["tool_count"] != 14
        or view["summary"]["agent_count"] != 1
        or view["team"] is not None
        or _peak_inference_concurrency(view) != 1
    ):
        raise RecoveryError("Plan 049 source Root trace projection differs")
    root_tree = _tree_projection(selected.root_bundle, "source Root bundle")
    trace_tree = _tree_projection(trace_root, "source trace root")
    if (
        root_tree["sha256"] != SOURCE_ROOT_TREE_SHA256
        or root_tree["file_count"] != 119
        or root_tree["size_bytes"] != 1_540_696
        or trace_tree["sha256"] != SOURCE_TRACE_TREE_SHA256
        or trace_tree["file_count"] != 128
        or trace_tree["size_bytes"] != 1_591_455
    ):
        raise RecoveryError("Plan 049 source trace tree differs")
    binding = {
        "schema_version": 1,
        "identity_class": "paid_recovery_binding",
        "recovery_id": recovery_id,
        "source_namespace": str(contract.lock["budget"]["formal_namespace"]),
        "target_namespace": recovery_id,
        "source_harness_commit": SOURCE_HARNESS_COMMIT,
        "recovery_harness_commit": recovery_harness_commit,
        "source_formal_identity_sha256": SOURCE_FORMAL_IDENTITY_SHA256,
        "source_artifacts": {
            "activation_receipt_sha256": SOURCE_RECEIPT_SHA256,
            "budget_ledger_sha256": SOURCE_LEDGER_SHA256,
            "records_sha256": SOURCE_RECORD_SHA256,
            "run_marker_sha256": SOURCE_RECORD_SHA256,
            "api_metadata_sha256": SOURCE_API_METADATA_SHA256,
            "terminal_bench_result_sha256": SOURCE_TB_RESULT_SHA256,
        },
        "source_run": {
            "run_id": SOURCE_RUN_ID,
            "slot_id": "pilot-p01-codex",
            "attempt": 1,
            "task_id": "terminal-bench/filter-js-from-html",
            "side": "codex",
            "formal_stop_outcome": "principled_stopped",
            "formal_stop_reason": "non_infra_terminal_missing_trace",
            "native_outcome": "completed",
            "native_reward": "0.0",
            "recovered_outcome": "task_failed",
            "recovered_reason": "task_native_verifier_failed",
            "request_count": 15,
            "request_preflight_sha256": request_preflight,
            "spent_usd": _money_text(SOURCE_COST_USD),
        },
        "source_trace": {
            "trace_root_relative": str(trace_root.relative_to(source.root)),
            "trace_root_tree_sha256": trace_tree["sha256"],
            "trace_root_file_count": trace_tree["file_count"],
            "trace_root_size_bytes": trace_tree["size_bytes"],
            "root_bundle_relative": str(selected.root_bundle.relative_to(source.root)),
            "root_bundle_tree_sha256": root_tree["sha256"],
            "root_bundle_file_count": root_tree["file_count"],
            "root_bundle_size_bytes": root_tree["size_bytes"],
            "root_trace_id": view["source"]["trace_id"],
            "root_rollout_id": view["source"]["rollout_id"],
            "root_thread_id": view["source"]["root_thread_id"],
            "guardian_bundle_count": selected.guardian_bundle_count,
            "team_lens_product": "codex",
            "guardian_excluded_from_product_metrics": True,
        },
        "budget_carry_forward": {
            "campaign_cap_usd": _money_text(Decimal("100.00")),
            "prior_spend_usd": _money_text(SOURCE_COST_USD),
            "remaining_authorized_usd": _money_text(RECOVERY_REMAINING_USD),
            "settled_request_count": 15,
            "unsettled_request_count": 0,
            "operator_confirmed_balance_covers_remaining": True,
        },
        "provider_requests_during_recovery": 0,
        "docker_runs_during_recovery": 0,
    }
    assert_body_free(binding)
    binding_sha = hashlib.sha256(_canonical(binding)).hexdigest()
    return _SourceEvidence(
        binding=binding,
        binding_sha256=binding_sha,
        root_view=view,
        ledger_bytes=ledger_bytes,
        ledger_state=ledger,
        request_preflight_sha256=request_preflight,
    )


def _reconstruct_preflight(
    contract: CampaignContract,
    metadata: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> str:
    if set(metadata) != {"schema_version", "requests"} or metadata.get(
        "schema_version"
    ) != 1:
        raise RecoveryError("Plan 049 source API metadata shape differs")
    requests = metadata.get("requests")
    if not isinstance(requests, list) or len(requests) != 15:
        raise RecoveryError("Plan 049 source API request count differs")
    ledger_requests = ledger["runs"][SOURCE_RUN_ID]["requests"]
    if not isinstance(ledger_requests, dict) or len(ledger_requests) != 15:
        raise RecoveryError("Plan 049 source ledger request count differs")
    observed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(requests, 1):
        if not isinstance(row, dict):
            raise RecoveryError("Plan 049 source API request is invalid")
        request_id = row.get("request_id")
        digest = row.get("canonical_body_sha256")
        ledger_row = ledger_requests.get(request_id)
        if (
            not isinstance(request_id, str)
            or request_id in seen
            or not isinstance(digest, str)
            or _SHA256.fullmatch(digest) is None
            or not isinstance(ledger_row, dict)
            or row.get("role") != "main"
            or row.get("declared_role") != "main"
            or row.get("inferred_role") != "main"
            or row.get("role_provenance") != "declared"
            or row.get("model") != contract.lock["provider"]["root_model"]
            or row.get("reasoning_effort")
            != contract.lock["provider"]["root_effort"]
            or row.get("contract_match") is not True
            or row.get("usage_valid") is not True
            or row.get("settlement_kind") != "usage_priced"
            or ledger_row.get("status") != "settled"
            or ledger_row.get("usage_valid") is not True
            or ledger_row.get("settlement_kind") != "usage_priced"
            or Decimal(str(row.get("charged_usd")))
            != Decimal(str(ledger_row.get("charged_usd")))
        ):
            raise RecoveryError("Plan 049 source API request evidence differs")
        seen.add(request_id)
        observed.append(
            {
                "sequence": index,
                "side": "codex",
                "task_id": "terminal-bench/filter-js-from-html",
                "role": "main",
                "full_request_sha256": digest,
                "policy_sha256": contract.policy_sha256,
            }
        )
    if seen != set(ledger_requests):
        raise RecoveryError("Plan 049 source API and ledger requests differ")
    value = {"schema_version": 1, "observed": observed}
    assert_body_free(value)
    return hashlib.sha256(_canonical(value)).hexdigest()


def _recovered_record(
    contract: CampaignContract,
    *,
    store: FormalStore,
    result: FormalExecutionResult,
    slot: Any,
    ledger_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    run = ledger_snapshot["runs"][SOURCE_RUN_ID]
    row = {
        "schema_version": 1,
        "evidence_kind": "real_api",
        "identity_class": "paid",
        "formal_identity_sha256": store.identity_sha256,
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "policy_sha256": contract.policy_sha256,
        "taskset_sha256": contract.taskset_sha256,
        "phase": slot.phase,
        "pair_id": slot.pair_id,
        "slot_id": slot.slot_id,
        "run_id": SOURCE_RUN_ID,
        "budget_run_id": SOURCE_RUN_ID,
        "attempt": 1,
        "task_id": slot.task_id,
        "side": slot.side,
        "product": None,
        "outcome": result.outcome,
        "terminal": True,
        "counts_as_effective": True,
        "cost_usd": str(run["spent_usd"]),
        "request_count": len(run["requests"]),
        "trace_status": result.trace_status,
        "team_view_sha256": result.team_view_sha256,
        "team_report_sha256": result.team_report_sha256,
        "request_preflight_sha256": result.request_preflight_sha256,
        "reason_code": result.reason_code,
    }
    store.validate_record(row)
    return row


def _is_source_stop_record(row: Mapping[str, Any]) -> bool:
    return (
        row.get("formal_identity_sha256") == SOURCE_FORMAL_IDENTITY_SHA256
        and row.get("run_id") == SOURCE_RUN_ID
        and row.get("slot_id") == "pilot-p01-codex"
        and row.get("attempt") == 1
        and row.get("outcome") == "principled_stopped"
        and row.get("reason_code") == "non_infra_terminal_missing_trace"
        and row.get("terminal") is False
        and row.get("counts_as_effective") is False
        and row.get("trace_status") == "missing"
        and Decimal(str(row.get("cost_usd"))) == SOURCE_COST_USD
        and row.get("request_count") == 15
    )


def _is_recovered_record(row: Mapping[str, Any]) -> bool:
    return (
        row.get("run_id") == SOURCE_RUN_ID
        and row.get("slot_id") == "pilot-p01-codex"
        and row.get("attempt") == 1
        and row.get("outcome") == "task_failed"
        and row.get("reason_code") == "task_native_verifier_failed"
        and row.get("terminal") is True
        and row.get("counts_as_effective") is True
        and row.get("trace_status") == "available"
        and row.get("request_preflight_sha256") == SOURCE_PREFLIGHT_SHA256
        and Decimal(str(row.get("cost_usd"))) == SOURCE_COST_USD
        and row.get("request_count") == 15
    )


def _require_recovered_ledger(ledger: Mapping[str, Any]) -> None:
    runs = ledger.get("runs")
    if not isinstance(runs, dict) or set(runs) != {SOURCE_RUN_ID}:
        raise RecoveryError("Plan 049 carried ledger run set differs")
    run = runs[SOURCE_RUN_ID]
    requests = run.get("requests") if isinstance(run, dict) else None
    if (
        Decimal(str(run.get("spent_usd"))) != SOURCE_COST_USD
        or run.get("stopped") is not False
        or run.get("stop_reason") is not None
        or run.get("infra_taint") is not None
        or not isinstance(requests, dict)
        or len(requests) != 15
        or any(
            request.get("status") != "settled"
            or request.get("settlement_kind") != "usage_priced"
            or request.get("usage_valid") is not True
            for request in requests.values()
        )
    ):
        raise RecoveryError("Plan 049 carried ledger accounting differs")
    remaining = Decimal(str(ledger["total_cap_usd"])) - SOURCE_COST_USD
    if remaining != RECOVERY_REMAINING_USD:
        raise RecoveryError("Plan 049 carried ledger remaining cap differs")


def _require_carried_ledger(
    ledger: Mapping[str, Any], source_ledger: Mapping[str, Any]
) -> None:
    runs = ledger.get("runs")
    source_runs = source_ledger.get("runs")
    if (
        not isinstance(runs, dict)
        or not isinstance(source_runs, dict)
        or runs.get(SOURCE_RUN_ID) != source_runs.get(SOURCE_RUN_ID)
    ):
        raise RecoveryError("Plan 049 carried source ledger run differs")
    total = Decimal(str(ledger.get("total_cap_usd")))
    spent = sum(
        Decimal(str(run["spent_usd"]))
        for run in runs.values()
        if isinstance(run, dict)
    )
    reserved = sum(
        Decimal(str(request["reserved_usd"]))
        for run in runs.values()
        if isinstance(run, dict)
        for request in run.get("requests", {}).values()
        if isinstance(request, dict) and request.get("status") == "reserved"
    )
    if spent < SOURCE_COST_USD or spent + reserved > total:
        raise RecoveryError("Plan 049 carried campaign exposure is invalid")


def _recovery_receipt(
    paths: RecoveryPaths,
    *,
    store: FormalStore,
    binding_sha256: str,
    row: Mapping[str, Any],
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "identity_class": "paid_recovery_receipt",
        "recovery_id": RECOVERY_ID,
        "formal_identity_sha256": store.identity_sha256,
        "recovery_binding_sha256": binding_sha256,
        "source_run_id": SOURCE_RUN_ID,
        "recovered_outcome": "task_failed",
        "request_count": 15,
        "prior_spend_usd": _money_text(SOURCE_COST_USD),
        "remaining_authorized_usd": _money_text(RECOVERY_REMAINING_USD),
        "imported_budget_ledger_sha256": SOURCE_LEDGER_SHA256,
        "record_sha256": hashlib.sha256(_canonical(dict(row)) + b"\n").hexdigest(),
        "team_view_sha256": row["team_view_sha256"],
        "team_report_sha256": row["team_report_sha256"],
        "aggregate_sha256": _file_sha256(
            paths.import_aggregate, "recovery import aggregate"
        ),
        "provider_requests_during_recovery": 0,
        "docker_runs_during_recovery": 0,
    }
    assert_body_free(value)
    return value


def _tree_projection(root: Path, label: str) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise RecoveryError(f"Plan 049 {label} is unsafe")
    rows: list[dict[str, Any]] = []
    size = 0
    try:
        entries = sorted(root.rglob("*"))
    except OSError as exc:
        raise RecoveryError(f"Plan 049 {label} is unreadable") from exc
    for entry in entries:
        try:
            mode = entry.lstat().st_mode
        except OSError as exc:
            raise RecoveryError(f"Plan 049 {label} is unreadable") from exc
        if stat.S_ISLNK(mode):
            raise RecoveryError(f"Plan 049 {label} contains a symlink")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise RecoveryError(f"Plan 049 {label} contains a non-regular file")
        payload = _read_regular_bytes(entry, label)
        size += len(payload)
        rows.append(
            {
                "path": entry.relative_to(root).as_posix(),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    if not rows:
        raise RecoveryError(f"Plan 049 {label} is empty")
    return {
        "sha256": hashlib.sha256(_canonical(rows)).hexdigest(),
        "file_count": len(rows),
        "size_bytes": size,
    }


def _peak_inference_concurrency(view: Mapping[str, Any]) -> int:
    events: list[tuple[int, int]] = []
    for row in view.get("inferences", []):
        start = row.get("started_at_unix_ms")
        end = row.get("ended_at_unix_ms")
        if (
            isinstance(start, bool)
            or not isinstance(start, int)
            or isinstance(end, bool)
            or not isinstance(end, int)
            or end < start
        ):
            raise RecoveryError("Plan 049 source inference timing is incomplete")
        events.append((start, 1))
        events.append((end, -1))
    current = 0
    peak = 0
    for _time, delta in sorted(events, key=lambda item: (item[0], item[1])):
        current += delta
        peak = max(peak, current)
    return peak


def _safe_child_directories(root: Path, label: str) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise RecoveryError(f"Plan 049 {label} is unsafe")
    try:
        children = sorted(root.iterdir())
    except OSError as exc:
        raise RecoveryError(f"Plan 049 {label} is unreadable") from exc
    if any(child.is_symlink() or not child.is_dir() for child in children):
        raise RecoveryError(f"Plan 049 {label} contains an unknown entry")
    return children


def _read_json(path: Path, label: str) -> dict[str, Any]:
    payload = _read_regular_bytes(path, label)
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"Plan 049 {label} is invalid") from exc
    if not isinstance(value, dict):
        raise RecoveryError(f"Plan 049 {label} is invalid")
    return value


def _read_private_json(path: Path, label: str) -> dict[str, Any]:
    value = _read_json(path, label)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise RecoveryError(f"Plan 049 {label} must have mode 0600")
    return value


def _read_regular_bytes(path: Path, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RecoveryError(f"Plan 049 {label} is unsafe") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RecoveryError(f"Plan 049 {label} is unsafe")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RecoveryError(f"Plan 049 {label} is unreadable") from exc


def _write_private_or_verify(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise RecoveryError("Plan 049 recovery artifact parent is unsafe")
    if path.exists() or path.is_symlink():
        existing = _read_regular_bytes(path, "recovery artifact")
        if existing != payload or stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise RecoveryError("Plan 049 recovery artifact differs")
        return
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise RecoveryError("Plan 049 recovery artifact could not be written") from exc


def _file_sha256(path: Path, label: str) -> str:
    return hashlib.sha256(_read_regular_bytes(path, label)).hexdigest()


def _require_sha(payload: bytes, expected: str, label: str) -> None:
    if hashlib.sha256(payload).hexdigest() != expected:
        raise RecoveryError(f"Plan 049 {label} digest differs")


def _money_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
