"""Plan 044 / Multi M-5 contracts: workflow, non-degradation, runtime identity."""

from __future__ import annotations

from .archive import (
    M5_ARCHIVE_SCHEMA_VERSION,
    archive_record,
    required_archive_fields,
)
from .load import (
    LOCKS_DIR,
    M5ContractError,
    NondegradationContract,
    RuntimeIdentity,
    WorkflowContract,
    load_nondegradation_contract,
    load_runtime_identity,
    load_workflow_contract,
)
from .loopback import (
    LOOPBACK_BEARER,
    LOOPBACK_MODEL,
    TeamPublishFakeServer,
    collect_tool_names,
    run_frozen_multi_team_publish_loopback,
)
from .collect import EvidenceError, collect_gate1_evidence
from .predicates import (
    CollaborationVerdict,
    evaluate_collaboration,
)
from .schedule import (
    Slot,
    base_slots,
    conditional_slots,
    degradation_on_task,
    outcomes_by_task,
)
from .store import persist_archive_record
from .trace import TraceError, find_trace_bundle, load_rollout_trace
from .gate1 import run_gate1_paid, run_gate1_rehearsal
from .gate2 import ScriptedSlotExecutor, TerminalBenchSlotExecutor, run_gate2_real, run_light_interleaved
from .ready import readiness_report
from .budget import (
    HARD_CAP_USD,
    default_run_cap_usd,
    open_phase_b_ledger,
    request_reservation_usd,
    usage_envelope,
)
from .paid import PaidAuthorization, authorization_from_phrases

__all__ = [
    "CollaborationVerdict",
    "HARD_CAP_USD",
    "LOCKS_DIR",
    "LOOPBACK_BEARER",
    "LOOPBACK_MODEL",
    "EvidenceError",
    "M5ContractError",
    "M5_ARCHIVE_SCHEMA_VERSION",
    "NondegradationContract",
    "PaidAuthorization",
    "RuntimeIdentity",
    "ScriptedSlotExecutor",
    "Slot",
    "TeamPublishFakeServer",
    "TraceError",
    "TerminalBenchSlotExecutor",
    "WorkflowContract",
    "archive_record",
    "authorization_from_phrases",
    "base_slots",
    "collect_gate1_evidence",
    "collect_tool_names",
    "conditional_slots",
    "default_run_cap_usd",
    "degradation_on_task",
    "evaluate_collaboration",
    "find_trace_bundle",
    "load_nondegradation_contract",
    "load_rollout_trace",
    "load_runtime_identity",
    "load_workflow_contract",
    "open_phase_b_ledger",
    "outcomes_by_task",
    "persist_archive_record",
    "readiness_report",
    "request_reservation_usd",
    "required_archive_fields",
    "run_frozen_multi_team_publish_loopback",
    "run_gate1_paid",
    "run_gate1_rehearsal",
    "run_gate2_real",
    "run_light_interleaved",
    "usage_envelope",
]
