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
)

__all__ = [
    "CollaborationVerdict",
    "LOCKS_DIR",
    "LOOPBACK_BEARER",
    "LOOPBACK_MODEL",
    "M5ContractError",
    "M5_ARCHIVE_SCHEMA_VERSION",
    "NondegradationContract",
    "RuntimeIdentity",
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
    "required_archive_fields",
    "run_frozen_multi_team_publish_loopback",
]
