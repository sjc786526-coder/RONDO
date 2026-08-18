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
from .collect import collect_gate1_evidence, merge_jsonl_into_dump
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
from .gate1 import run_gate1_rehearsal
from .gate2 import ScriptedSlotExecutor, run_light_interleaved
from .ready import readiness_report
from .budget import HARD_CAP_USD, open_phase_b_ledger

__all__ = [
    "CollaborationVerdict",
    "HARD_CAP_USD",
    "LOCKS_DIR",
    "LOOPBACK_BEARER",
    "LOOPBACK_MODEL",
    "M5ContractError",
    "M5_ARCHIVE_SCHEMA_VERSION",
    "NondegradationContract",
    "RuntimeIdentity",
    "ScriptedSlotExecutor",
    "Slot",
    "TeamPublishFakeServer",
    "WorkflowContract",
    "archive_record",
    "base_slots",
    "collect_gate1_evidence",
    "collect_tool_names",
    "conditional_slots",
    "degradation_on_task",
    "evaluate_collaboration",
    "load_nondegradation_contract",
    "load_runtime_identity",
    "load_workflow_contract",
    "merge_jsonl_into_dump",
    "open_phase_b_ledger",
    "outcomes_by_task",
    "persist_archive_record",
    "readiness_report",
    "required_archive_fields",
    "run_frozen_multi_team_publish_loopback",
    "run_gate1_rehearsal",
    "run_light_interleaved",
]
