"""Frozen execution generation layered over the unchanged M-5 v6 contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .load import (
    LOCKS_DIR,
    NONDEGRADATION_LOCK_ID,
    RUNTIME_LOCK_ID,
    WORKFLOW_LOCK_ID,
    M5ContractError,
)


CAMPAIGN_GENERATION = "multi-m5-v6-c2"
BATCH_ID = "multi-m5-phase-b-v6-c2"
GATE1_RUN_PREFIX = "m5-g1-v6-c2-paid-a"
GATE2_RUN_PREFIX = "m5-g2-v6-c2-"
ARCHIVE_RELPATH = "eval-data/multi-m5/archives/phase-b-v6-c2-records.jsonl"
BUDGET_RELPATH = "eval-data/budgets/multi-m5-phase-b-v6-c2.json"
RECEIPT_RELPATH = "eval-data/budgets/multi-m5-phase-b-v6-c2-identity.json"
SHARED_HARD_CAP_USD = Decimal("120.000000")
PRIOR_EXPOSURE_USD = Decimal("13.320000")
CAMPAIGN_CAP_USD = Decimal("106.680000")


@dataclass(frozen=True)
class CampaignGeneration:
    generation: str
    batch_id: str
    archive_relpath: str
    budget_relpath: str
    receipt_relpath: str
    gate1_run_prefix: str
    gate2_run_prefix: str
    shared_hard_cap_usd: Decimal
    prior_exposure_usd: Decimal
    campaign_cap_usd: Decimal
    raw: dict[str, Any]


def load_campaign_generation(path: Path | None = None) -> CampaignGeneration:
    lock_path = path or LOCKS_DIR / "multi-m5-campaign-v6-c2.json"
    try:
        raw = json.loads(lock_path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise M5ContractError("campaign generation lock is unreadable") from exc
    exact = {
        "schema_version": 1,
        "campaign_generation": CAMPAIGN_GENERATION,
        "workflow_lock_id": WORKFLOW_LOCK_ID,
        "runtime_lock_id": RUNTIME_LOCK_ID,
        "nondegradation_lock_id": NONDEGRADATION_LOCK_ID,
        "budget_batch_id": BATCH_ID,
        "archive_relpath": ARCHIVE_RELPATH,
        "budget_relpath": BUDGET_RELPATH,
        "receipt_relpath": RECEIPT_RELPATH,
        "gate1_run_prefix": GATE1_RUN_PREFIX,
        "gate2_run_prefix": GATE2_RUN_PREFIX,
        "shared_hard_cap_usd": str(SHARED_HARD_CAP_USD),
        "prior_conservative_exposure_usd": str(PRIOR_EXPOSURE_USD),
        "campaign_cap_usd": str(CAMPAIGN_CAP_USD),
    }
    for name, expected in exact.items():
        if raw.get(name) != expected:
            raise M5ContractError(f"campaign generation field {name} differs")
    for lock_id, field, expected in (
        (
            WORKFLOW_LOCK_ID,
            "workflow_lock_sha256",
            "e89ebe5d4a7e660daba3315f35023502e3f4c0538b345b0b02b91a11c61fb36e",
        ),
        (
            RUNTIME_LOCK_ID,
            "runtime_lock_sha256",
            "7763dc4e29077576465187aed81c8231afac73a9cf22c6b67d5cc9266bd8f02c",
        ),
        (
            NONDEGRADATION_LOCK_ID,
            "nondegradation_lock_sha256",
            "53f6b5b341d424167f0520375745ea9835e17f0370d52bb7ac90984fe10bddff",
        ),
    ):
        lock_file = LOCKS_DIR / f"{lock_id}.json"
        digest = hashlib.sha256(lock_file.read_bytes()).hexdigest()
        if raw.get(field) != expected or digest != expected:
            raise M5ContractError(f"campaign generation {field} differs")
    if SHARED_HARD_CAP_USD - PRIOR_EXPOSURE_USD != CAMPAIGN_CAP_USD:
        raise M5ContractError("campaign generation cap arithmetic differs")
    if raw.get("formal_identity_fields") != [
        "campaign_generation",
        "budget_batch_id",
        "workflow_lock_id",
        "nondegradation_lock_id",
        "runtime_lock_id",
        "provider_identity",
        "harness_commit",
        "harness_dirty",
        "prior_campaign_conservative_exposure_usd",
        "campaign_cap_usd",
    ]:
        raise M5ContractError("campaign generation identity fields differ")
    if raw.get("connectivity_preflight") != {
        "kind": "unauthenticated_http_reachability",
        "method": "GET",
        "phase": "before_secret_receipt_ledger_claim_capture_or_docker",
        "accepted_outcome": "any_http_response",
        "network_error_effect": "refuse_without_formal_state",
        "authorization_header": False,
        "request_body": False,
        "proxy": "disabled",
        "redirects": "disabled",
        "timeout_seconds": 15,
        "max_attempts": 1,
        "failure_consumes_gate_attempt": False,
    }:
        raise M5ContractError("campaign connectivity preflight differs")
    prior = raw.get("prior_generation")
    expected_prior = {
        "campaign_generation": "multi-m5-v6-c1",
        "archive_relpath": "eval-data/multi-m5/archives/phase-b-v6-records.jsonl",
        "archive_sha256": "bd2a11d2ef01a88440bdf46f9337d4482a5d893700a496abd8db2ec12334aaed",
        "archive_rows": 6,
        "budget_relpath": "eval-data/budgets/multi-m5-phase-b-v6.json",
        "budget_sha256": "20986906bde068cc42402ad44b3b93b2252d67e302cb1e8b176ae91ef1ff9f44",
        "receipt_relpath": "eval-data/budgets/multi-m5-phase-b-v6-identity.json",
        "receipt_sha256": "51e340cae59c7e0324db053a7b36c590f0c7308f4106ed9b522efec7845383a5",
        "provider_priced_usd": "0.000000",
        "relay_billed_usd": "0.000000",
        "relay_billed_source": "operator_confirmed",
        "budget_treatment": "retain_conservative_exposure_in_shared_cap",
    }
    if prior != expected_prior:
        raise M5ContractError("prior campaign generation differs")
    return CampaignGeneration(
        generation=CAMPAIGN_GENERATION,
        batch_id=BATCH_ID,
        archive_relpath=exact["archive_relpath"],
        budget_relpath=exact["budget_relpath"],
        receipt_relpath=exact["receipt_relpath"],
        gate1_run_prefix=GATE1_RUN_PREFIX,
        gate2_run_prefix=GATE2_RUN_PREFIX,
        shared_hard_cap_usd=SHARED_HARD_CAP_USD,
        prior_exposure_usd=PRIOR_EXPOSURE_USD,
        campaign_cap_usd=CAMPAIGN_CAP_USD,
        raw=raw,
    )


def require_prior_generation(common_root: Path, campaign: CampaignGeneration) -> None:
    """Pin the terminal c1 evidence before c2 may create any formal state."""

    prior = campaign.raw["prior_generation"]
    for kind in ("archive", "budget", "receipt"):
        path = common_root / str(prior[f"{kind}_relpath"])
        if path.is_symlink() or not path.is_file():
            raise M5ContractError(f"prior campaign {kind} is unsafe")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != prior[f"{kind}_sha256"]:
            raise M5ContractError(f"prior campaign {kind} digest differs")
    archive = common_root / str(prior["archive_relpath"])
    rows = [
        json.loads(line)
        for line in archive.read_text("utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != 6:
        raise M5ContractError("prior campaign archive row count differs")
    for attempt, row in enumerate(rows, start=1):
        if (
            row.get("gate") != 1
            or row.get("attempt") != attempt
            or row.get("budget_run_id") != f"m5-g1-v6-paid-a{attempt}"
            or row.get("outcome") != "infra_failed"
            or row.get("passed") is not False
            or row.get("counts_as_effective") is not False
            or row.get("stop_reason") != "upstream_unavailable"
            or row.get("workflow_lock_id") != WORKFLOW_LOCK_ID
            or row.get("nondegradation_lock_id") != NONDEGRADATION_LOCK_ID
            or row.get("runtime_lock_id") != RUNTIME_LOCK_ID
            or row.get("budget_exposure", {}).get("priced_usd") != "0.000000"
            or row.get("budget_exposure", {}).get("conservative_exposure_usd")
            != "2.220000"
        ):
            raise M5ContractError("prior campaign archive semantics differ")
    ledger_path = common_root / str(prior["budget_relpath"])
    ledger = json.loads(ledger_path.read_text("utf-8"))
    if (
        ledger.get("batch_id") != "multi-m5-phase-b-v6"
        or ledger.get("total_cap_usd") != "120.000000"
        or set(ledger.get("runs", {}))
        != {f"m5-g1-v6-paid-a{attempt}" for attempt in range(1, 7)}
    ):
        raise M5ContractError("prior campaign ledger identity differs")
    total = Decimal("0")
    for run in ledger["runs"].values():
        requests = run.get("requests")
        request_rows = list(requests.values()) if isinstance(requests, dict) else []
        if (
            run.get("spent_usd") != "2.220000"
            or run.get("stopped") is not True
            or run.get("stop_reason") != "upstream_unavailable"
            or len(request_rows) != 1
            or request_rows[0].get("status") != "settled"
            or request_rows[0].get("usage_valid") is not False
            or request_rows[0].get("settlement_kind") != "conservative_reservation"
            or request_rows[0].get("charged_usd") != "2.220000"
            or request_rows[0].get("attempt_count") != 1
        ):
            raise M5ContractError("prior campaign ledger semantics differ")
        total += Decimal(run["spent_usd"])
    if total != campaign.prior_exposure_usd:
        raise M5ContractError("prior campaign conservative exposure differs")
    receipt_path = common_root / str(prior["receipt_relpath"])
    receipt = json.loads(receipt_path.read_text("utf-8"))
    if (
        receipt.get("budget_batch_id") != "multi-m5-phase-b-v6"
        or receipt.get("workflow_lock_id") != WORKFLOW_LOCK_ID
        or receipt.get("nondegradation_lock_id") != NONDEGRADATION_LOCK_ID
        or receipt.get("runtime_lock_id") != RUNTIME_LOCK_ID
    ):
        raise M5ContractError("prior campaign receipt semantics differ")
