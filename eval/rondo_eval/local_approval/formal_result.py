"""Project the formal Local M4 review into one tracked, body-free result.

The private execution directories keep every per-sample input, model output,
blinding seed, mapping, judge rationale and unblinded record.  This module only
projects counts, identities and the human decision.  Synthetic body and holdout
anchor facts are carried side by side and can never be summed: the holdout side
is reduced through the existing batch-only projection.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config import ConfigError
from . import cross_eval


FORMAL_RESULT_SCHEMA_VERSION = 1
FORMAL_RESULT_CONTRACT_VERSION = "rondo_local_m4_formal_result_v1"
RESULT_RELATIVE_PATH = "eval/locks/local-approval-m4-formal-review-v1.json"
L4_METRIC_CONTRACT_RELATIVE_PATH = (
    "eval/templates/local-approval/l4-metric-contract-v1.json"
)
L4_METRIC_NAME = "rondo_l4_local_static_v1"
JUDGE_ENTRY = "claude_code_subscription_session_human_present"
DECISIONS = ("adopt", "keep_as_experiment", "stop")
LOCAL_SIDES = ("local-static", "local-ft-static")
TERMINAL_STATUSES = (
    *cross_eval.OUTPUT_TERMINAL_STATUSES,
    cross_eval.INFRASTRUCTURE_TERMINAL_STATUS,
)


class FormalResultError(RuntimeError):
    """Body-free, stable failure from the tracked M4 result boundary."""

    def __init__(self, code: str, facts: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.facts = dict(facts or {})


def side_terminal_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Count honest terminal states per side without reading any body."""

    counts = {
        side: {status: 0 for status in TERMINAL_STATUSES} for side in cross_eval.SIDES
    }
    for row in rows:
        side = row.get("side")
        if side not in counts:
            raise FormalResultError("formal_result_side_unknown")
        terminal = cross_eval._row_terminal(row)
        counts[side][terminal["status"]] += 1
    return counts


def teacher_agreement(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compare each local side against the frozen Sol target, decisions only.

    Only samples where the Sol side and that local side both reached a decision
    terminal are comparable, exactly as the frozen L4 contract requires.  A
    difference is teacher disagreement, never a false allow or false deny.
    """

    terminals: dict[tuple[str, str], dict[str, Any]] = {}
    sample_ids: set[str] = set()
    for row in rows:
        side = row.get("side")
        sample_id = row.get("sample_id")
        if side not in cross_eval.SIDES or not isinstance(sample_id, str):
            raise FormalResultError("formal_result_side_unknown")
        key = (sample_id, side)
        if key in terminals:
            raise FormalResultError("formal_result_row_duplicate")
        terminals[key] = cross_eval._row_terminal(row)
        sample_ids.add(sample_id)
    if len(terminals) != len(sample_ids) * len(cross_eval.SIDES):
        raise FormalResultError("formal_result_row_set_incomplete")

    result: dict[str, dict[str, Any]] = {}
    for side in LOCAL_SIDES:
        counts: Counter[str] = Counter()
        comparable = 0
        for sample_id in sorted(sample_ids):
            teacher = terminals[(sample_id, "sol-static")]
            local = terminals[(sample_id, side)]
            if teacher["status"] != "decision":
                raise FormalResultError("formal_result_teacher_terminal_invalid")
            if local["status"] != "decision":
                continue
            comparable += 1
            teacher_outcome = teacher["decision"]["outcome"]
            local_outcome = local["decision"]["outcome"]
            if teacher_outcome == local_outcome:
                counts["agree"] += 1
            elif teacher_outcome == "deny":
                counts["teacher_deny_side_allow"] += 1
            else:
                counts["teacher_allow_side_deny"] += 1
        result[side] = {
            "sample_count": len(sample_ids),
            "comparable_decision_count": comparable,
            "agree": counts["agree"],
            "teacher_deny_side_allow": counts["teacher_deny_side_allow"],
            "teacher_allow_side_deny": counts["teacher_allow_side_deny"],
            "teacher_agreement_rate": (
                round(counts["agree"] / comparable, 6) if comparable else None
            ),
        }
    return result


def _validate_aggregate(value: Any, *, partition: str) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != cross_eval.AGGREGATE_SCHEMA_VERSION
        or value.get("contract_version") != cross_eval.AGGREGATE_CONTRACT_VERSION
        or value.get("partition") != partition
        or value.get("decision") is not None
        or value.get("thresholds") is not None
        or value.get("synthetic_holdout_combined") is not False
    ):
        raise FormalResultError("formal_result_aggregate_invalid")
    return copy.deepcopy(dict(value))


def _opus_relative(aggregate: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    facts: dict[str, dict[str, Any]] = {}
    for side in cross_eval.SIDES:
        side_facts = aggregate["sides"][side]
        outcomes = dict(side_facts["candidate_outcomes"])
        no_decision = int(outcomes.pop(cross_eval.NO_DECISION_JUDGMENT, 0))
        facts[side] = {
            "comparable_decision_count": sum(outcomes.values()),
            "no_decision_count": no_decision,
            "judge_outcome_agreement": side_facts["judge_outcome_agreement"],
            "missed_deny_judge_deny_side_allow": side_facts["judge_deny_side_allow"],
            "over_block_judge_allow_side_deny": side_facts["judge_allow_side_deny"],
            "sole_preferred": side_facts["sole_preferred"],
            "tied_preferred": side_facts["tied_preferred"],
            "not_preferred": side_facts["not_preferred"],
            "all_candidates_inadequate": side_facts["all_candidates_inadequate"],
            "approval_judgments": dict(sorted(side_facts["approval_judgments"].items())),
            "reason_quality": dict(sorted(side_facts["reason_quality"].items())),
            "candidate_outcomes": dict(sorted(outcomes.items())),
        }
    return facts


def _finetune_delta(facts: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    """Direct fine-tuned minus unfine-tuned differences on identical counts."""

    base = facts["local-static"]
    tuned = facts["local-ft-static"]
    return {
        key: tuned[key] - base[key]
        for key in (
            "judge_outcome_agreement",
            "missed_deny_judge_deny_side_allow",
            "over_block_judge_allow_side_deny",
            "sole_preferred",
            "tied_preferred",
            "not_preferred",
        )
    }


def _validate_judge_contract(value: Any) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value)
        != {
            "prompt_version",
            "prompt_sha256",
            "result_schema_version",
            "result_schema_sha256",
        }
        or not isinstance(value["prompt_version"], str)
        or not value["prompt_version"].strip()
        or cross_eval._HEX64.fullmatch(str(value["prompt_sha256"])) is None
        or cross_eval._HEX64.fullmatch(str(value["result_schema_sha256"])) is None
        or not isinstance(value["result_schema_version"], int)
        or isinstance(value["result_schema_version"], bool)
    ):
        raise FormalResultError("formal_result_judge_contract_invalid")
    return dict(value)


def build_formal_result(
    *,
    review_id: str,
    judge_model: str,
    synthetic_judge_contract: Mapping[str, Any],
    holdout_judge_contract: Mapping[str, Any],
    synthetic_aggregate: Mapping[str, Any],
    synthetic_rows: Sequence[Mapping[str, Any]],
    holdout_aggregate: Mapping[str, Any],
    holdout_rows: Sequence[Mapping[str, Any]],
    decision: str,
    decision_date: str,
    decision_rationale: str,
    private_artifacts: Mapping[str, str],
    limitations: Sequence[str],
) -> dict[str, Any]:
    if not isinstance(review_id, str) or cross_eval._ID.fullmatch(review_id) is None:
        raise FormalResultError("formal_result_review_id_invalid")
    if decision not in DECISIONS:
        raise FormalResultError("formal_result_decision_invalid")
    cross_eval._validate_date(decision_date)
    if not isinstance(decision_rationale, str) or not decision_rationale.strip():
        raise FormalResultError("formal_result_decision_rationale_invalid")
    if not isinstance(judge_model, str) or not judge_model.strip():
        raise FormalResultError("formal_result_judge_identity_invalid")
    if (
        not isinstance(limitations, Sequence)
        or isinstance(limitations, (str, bytes))
        or not limitations
        or any(not isinstance(item, str) or not item.strip() for item in limitations)
    ):
        raise FormalResultError("formal_result_limitations_invalid")
    if not isinstance(private_artifacts, Mapping) or not private_artifacts:
        raise FormalResultError("formal_result_private_artifacts_invalid")
    for name, value in private_artifacts.items():
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(value, str)
            or cross_eval._HEX64.fullmatch(value) is None
        ):
            raise FormalResultError("formal_result_private_artifacts_invalid")

    synthetic_contract = _validate_judge_contract(synthetic_judge_contract)
    holdout_contract = _validate_judge_contract(holdout_judge_contract)
    if synthetic_contract["prompt_version"] != cross_eval.JUDGE_PROMPT_VERSION:
        raise FormalResultError("formal_result_synthetic_contract_not_frozen_v1")
    synthetic = _validate_aggregate(synthetic_aggregate, partition="synthetic")
    holdout = _validate_aggregate(holdout_aggregate, partition="holdout")
    if synthetic["cohort_manifest_sha256"] == holdout["cohort_manifest_sha256"]:
        raise FormalResultError("formal_result_partition_cohorts_not_distinct")
    judge_models = sorted(set(synthetic["judge_models"]) | set(holdout["judge_models"]))
    if judge_models != [judge_model]:
        raise FormalResultError("formal_result_judge_identity_mixed")
    judged_dates = sorted(set(synthetic["judged_dates"]) | set(holdout["judged_dates"]))

    synthetic_opus = _opus_relative(synthetic)
    holdout_projection = cross_eval.public_holdout_summary(holdout)
    holdout_opus = _opus_relative(holdout)
    return {
        "schema_version": FORMAL_RESULT_SCHEMA_VERSION,
        "contract_version": FORMAL_RESULT_CONTRACT_VERSION,
        "review_id": review_id,
        "status": "complete",
        "milestone": "local_m4_human_decision",
        "metric_contract_name": L4_METRIC_NAME,
        "judge": {
            "model": judge_model,
            "judged_dates": judged_dates,
            "entry": JUDGE_ENTRY,
            "point_in_time_only": True,
            "programmatic_provider_used": False,
        },
        "partitions": {
            "synthetic": {
                "role": "formal_body",
                "judge_contract": synthetic_contract,
                "cohort_manifest_sha256": synthetic["cohort_manifest_sha256"],
                "body_batch_ids": list(synthetic["body_batch_ids"]),
                "sample_count": synthetic["sample_count"],
                "judge_outcomes": dict(sorted(synthetic["judge_outcomes"].items())),
                "teacher_agreement": teacher_agreement(synthetic_rows),
                "terminal_states": side_terminal_counts(synthetic_rows),
                "relative_to_judge": synthetic_opus,
                "finetune_delta_relative_to_judge": _finetune_delta(synthetic_opus),
            },
            "holdout": {
                "role": "real_distribution_sanity_anchor",
                "judge_contract": holdout_contract,
                "batch_summary": holdout_projection,
                "teacher_agreement": teacher_agreement(holdout_rows),
                "terminal_states": side_terminal_counts(holdout_rows),
                "relative_to_judge": holdout_opus,
                "finetune_delta_relative_to_judge": _finetune_delta(holdout_opus),
                "three_way_ranking_claimed": False,
            },
        },
        "decision": {
            "choice": decision,
            "made_by": "user",
            "decided_date": decision_date,
            "rationale": decision_rationale,
            "production_default_changed": False,
            "provider_or_launcher_changed": False,
            "deployment_started": False,
        },
        "private_artifacts": dict(sorted(private_artifacts.items())),
        "limitations": list(limitations),
        "boundaries": {
            "body_free": True,
            "synthetic_holdout_combined": False,
            "thresholds": None,
            "runs_jsonl_modified": False,
            "holdout_per_sample_published": False,
        },
    }


def write_formal_result(worktree_root: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    path = worktree_root / RESULT_RELATIVE_PATH
    raw = cross_eval._json_file_bytes(value)
    if path.exists() or path.is_symlink():
        if cross_eval._safe_read(path, private=False) != raw:
            raise FormalResultError("formal_result_drift")
    else:
        cross_eval._write_exclusive(path, raw, mode=0o644)
    return {
        "status": "published",
        "relative_path": RESULT_RELATIVE_PATH,
        "sha256": cross_eval._sha256(raw),
        "decision": value["decision"]["choice"],
    }


def _print_result(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.local_approval.formal_result"
    )
    parser.add_argument("--worktree-root", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        request, _raw = cross_eval._load_json(args.request, private=True)
        if not isinstance(request, dict):
            raise FormalResultError("formal_result_request_invalid")
        value = build_formal_result(**request)
        result = write_formal_result(args.worktree_root, value)
        _print_result(result)
        return 0
    except FormalResultError as exc:
        report: dict[str, Any] = {"status": "not_ready", "blocker": exc.code}
        if exc.facts:
            report["facts"] = exc.facts
        _print_result(report)
        return 2
    except (cross_eval.CrossEvalError, TypeError) as exc:
        code = getattr(exc, "code", "formal_result_request_invalid")
        _print_result({"status": "not_ready", "blocker": code})
        return 2
    except (ConfigError, OSError):
        _print_result({"status": "not_ready", "blocker": "filesystem_error"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
