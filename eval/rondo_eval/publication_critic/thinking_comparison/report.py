"""Render tracked Plan 101 JSON/MD without packet or provider bodies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _fmt(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.6f}"


def _arm_a_operating_point_lines(metrics: Mapping[str, Any]) -> list[str]:
    """Arm A needs a threshold; B and C do not. Show both, and say which one is comparable."""

    lines = [
        "",
        "## Arm A operating point",
        "",
        "Arms B and C emit a verdict with no free parameter. A threshold fitted to these same 27",
        "gold rows would give A an advantage they never get, so the cross-arm table uses the",
        "pre-committed threshold and the fitted one is reported only as an upper bound.",
        "",
        "AUC is the threshold-free reading of how well A ranks candidates, so it is the fairest",
        "single number for the thinking comparison on this arm: it does not depend on where the",
        "operating point happens to sit.",
        "",
        "| unit | AUC | BA @ fixed 0.5 | BA @ oracle | oracle threshold |",
        "|---|---:|---:|---:|---:|",
    ]
    for condition in ("thinking_off", "thinking_on"):
        unit = metrics.get(f"{condition}:A", {}) or {}
        point = unit.get("operating_point") or {}
        fixed = point.get("fixed_threshold") or {}
        oracle = point.get("oracle_threshold") or {}
        lines.append(
            "| {key} | {auc} | {fixed} | {oracle} | {threshold} |".format(
                key=f"{condition}:A",
                auc=_fmt(unit.get("auc")),
                fixed=_fmt(fixed.get("balanced_accuracy")),
                oracle=_fmt(oracle.get("balanced_accuracy")),
                threshold=oracle.get("threshold"),
            )
        )
    lines.append("")
    return lines


def _limitations_lines() -> list[str]:
    return [
        "",
        "## Known limitations",
        "",
        "- **Per-arm prompt asymmetry.** Each arm carries the instruction its output channel needs,",
        "  but arm A also carries a calibration sentence (\"choose a boundary only when every",
        "  applicable hard requirement clearly fails or clearly holds\") that B and C have no",
        "  equivalent of. It was added during commissioning to satisfy a self-check that has since",
        "  been retired. A's spread of values is therefore partly induced by that instruction, and it",
        "  pushes against the confident boundary output a well-calibrated judge would give. This",
        "  affects the output-expression axis; the thinking axis is unaffected because both sides of",
        "  it share one prompt.",
        "- **Cohort size.** n=27 with 12 PASS and 15 REWRITE. Differences of a few points are inside",
        "  the noise; only the direction and the larger gaps are worth reading.",
        "- **One provider, one model revision.** `deepseek-v4-flash` serving is provider-managed and",
        "  not independently verifiable across the run.",
        "",
    ]


def markdown_report(result: Mapping[str, Any], tracked: Mapping[str, Any]) -> str:
    metrics = tracked.get("metrics") or {}
    differences = tracked.get("differences") or {}
    lines = [
        "# Plan 101 DeepSeek V4 Flash thinking × output-expression comparison",
        "",
        "This is a measurement report, not a qualification or route decision. "
        "No pass/fail terminal is attached.",
        "",
        f"- complete: `{tracked.get('complete')}`",
        f"- observations: `{tracked.get('terminal_observation_count')}/"
        f"{tracked.get('expected_terminal_observation_count')}`",
        f"- thinking_off repeats: `{tracked.get('thinking_off_repeats')}`",
        f"- thinking_on repeats: `{tracked.get('thinking_on_repeats')}`",
        f"- freeze SHA-256: `{tracked.get('freeze_sha256')}`",
        "",
        "## Six units, single call (primary)",
        "",
        "The product issues one call per candidate, so each repeat is scored on its own and the",
        "repeats are then summarised. This is the deployable number.",
        "",
        "| unit | BA mean | BA min | BA max | BA sd | repeats |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for condition in ("thinking_off", "thinking_on"):
        for arm in ("A", "B", "C"):
            key = f"{condition}:{arm}"
            single = (metrics.get(key, {}) or {}).get("single_call") or {}
            lines.append(
                "| {key} | {mean} | {lo} | {hi} | {sd} | {n} |".format(
                    key=key,
                    mean=_fmt(single.get("balanced_accuracy_mean")),
                    lo=_fmt(single.get("balanced_accuracy_min")),
                    hi=_fmt(single.get("balanced_accuracy_max")),
                    sd=_fmt(single.get("balanced_accuracy_sd")),
                    n=single.get("repeats"),
                )
            )
    lines.extend(
        [
            "",
            "## Six units, majority vote over repeats (secondary)",
            "",
            "A k-times-more-expensive ensemble, not what a single product call delivers. The band is",
            "the endpoint average of the two per-class Wilson recall intervals, which errs wide.",
            "",
            "| unit | balanced accuracy | band | False PASS | False REWRITE | pairs closed | consistency |",
            "|---|---:|---|---:|---:|---:|---:|",
        ]
    )
    for condition in ("thinking_off", "thinking_on"):
        for arm in ("A", "B", "C"):
            key = f"{condition}:{arm}"
            unit = metrics.get(key, {})
            band = unit.get("balanced_accuracy_band") or {}
            lines.append(
                "| {key} | {ba:.6f} | [{lo:.4f}, {hi:.4f}] | {fp} | {fr} | {pairs} | {cons:.4f} |".format(
                    key=key,
                    ba=float(unit.get("balanced_accuracy") or 0),
                    lo=float(band.get("low") or 0),
                    hi=float(band.get("high") or 0),
                    fp=unit.get("false_pass"),
                    fr=unit.get("false_rewrite"),
                    pairs=unit.get("pairs_closed"),
                    cons=float(unit.get("repeat_consistency_rate") or 0),
                )
            )
    lines.extend(_arm_a_operating_point_lines(metrics))
    lines.extend(_limitations_lines())
    lines.extend(
        [
            "",
            "## thinking_on − thinking_off",
            "",
            "Δ single call is the deployable comparison. Δ majority is the k-call ensemble and can",
            "disagree in sign when an arm is unstable across repeats.",
            "",
            "| arm | Δ single call | Δ majority | Δ False PASS | Δ False REWRITE | Δ pairs |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    thinking = differences.get("thinking_on_minus_off") or {}
    for arm in ("A", "B", "C"):
        row = thinking.get(arm) or {}
        lines.append(
            "| {arm} | {single} | {maj} | {fp} | {fr} | {pairs} |".format(
                arm=arm,
                single=_fmt(row.get("single_call_balanced_accuracy")),
                maj=_fmt(row.get("balanced_accuracy")),
                fp=row.get("false_pass"),
                fr=row.get("false_rewrite"),
                pairs=row.get("pairs_closed"),
            )
        )
    lines.extend(["", "## Output-expression differences", ""])
    expression = differences.get("expression") or {}
    for condition in ("thinking_off", "thinking_on"):
        lines.append(f"### {condition}")
        lines.append("")
        rows = expression.get(condition) or {}
        lines.append("| contrast | Δ single call | Δ majority | Δ False PASS | Δ False REWRITE |")
        lines.append("|---|---:|---:|---:|---:|")
        for name in ("C_minus_B", "C_minus_A", "B_minus_A"):
            row = rows.get(name) or {}
            lines.append(
                "| {name} | {single} | {maj} | {fp} | {fr} |".format(
                    name=name,
                    single=_fmt(row.get("single_call_balanced_accuracy")),
                    maj=_fmt(row.get("balanced_accuracy")),
                    fp=row.get("false_pass"),
                    fr=row.get("false_rewrite"),
                )
            )
        lines.append("")
    prereg = tracked.get("preregistered_tests") or []
    if prereg:
        lines.extend(
            [
                "## Preregistered observations",
                "",
                "Commissioning ran three packets. On those three, `thinking_off:B` returned the same",
                "verdict every time, including a PASS on the most blatant REWRITE in the triple (a",
                "candidate whose handoff is `null` and whose summary is one line saying the work is",
                "done). That looked like a dead 1-bit channel, and it was registered as a prediction",
                "before the formal matrix opened so it could be tested rather than assumed.",
                "",
                "It did not survive contact with 27 candidates. The lesson is about method, not about",
                "this arm: a three-packet preview cannot distinguish \"no discrimination\" from \"a mild",
                "class bias\", and a self-check that treats constancy on n=3 as a plumbing failure will",
                "block the very measurement that settles the question. The check was corrected to test",
                "packet reachability across arms instead.",
                "",
            ]
        )
        for row in prereg:
            validation = row.get("validation_27") or {}
            lines.append(f"- id: `{row.get('id')}`")
            lines.append(
                f"- validation-27 constant: `{validation.get('constant')}`"
            )
            lines.append(
                f"- distinct majority verdicts: `{validation.get('distinct_majority_verdicts')}`"
            )
            lines.append(
                f"- qminus majority: `{validation.get('qminus_majority')}`"
            )
            lines.append(
                f"- matches commissioning prediction: `{validation.get('matches_commissioning_prediction')}`"
            )
            lines.append("")
    direction = tracked.get("thinking_on_versus_off_direction") or {}
    if direction:
        lines.extend(
            [
                "## thinking_on versus thinking_off",
                "",
                "Direction is taken from the single-call mean, which is what one product call",
                "delivers. n=27 signal, not a causal conclusion.",
                "",
                "| arm | single-call off | single-call on | Δ on−off | direction | Δ majority |",
                "|---|---:|---:|---:|---|---:|",
            ]
        )
        for arm in ("A", "B", "C"):
            row = direction.get(arm) or {}
            lines.append(
                "| {arm} | {off} | {on} | {delta} | {direction} | {maj} |".format(
                    arm=arm,
                    off=_fmt(row.get("single_call_balanced_accuracy_off")),
                    on=_fmt(row.get("single_call_balanced_accuracy_on")),
                    delta=_fmt(row.get("single_call_delta_on_minus_off")),
                    direction=row.get("direction"),
                    maj=_fmt(row.get("delta_on_minus_off")),
                )
            )
        lines.append("")
    supplement = tracked.get("supplement_decision") or {}
    if supplement:
        lines.extend(
            [
                "## Supplement rounds (budget-only decision)",
                "",
                f"- looked at unit metrics: `{supplement.get('looked_at_unit_metrics')}`",
                f"- decision: `{supplement.get('decision')}`",
                f"- extend repeats to: `{supplement.get('extend_repeats_to')}`",
                f"- two-round cost: `{supplement.get('two_round_cost_rmb')} RMB`",
                f"- remaining unreserved at decision: `{supplement.get('remaining_unreserved_rmb')} RMB`",
                "",
            ]
        )
    rounds = tracked.get("disclosed_rounds") or []
    if rounds:
        lines.extend(["## Disclosed live rounds", "", "| run_id | status | calls | reason |", "|---|---|---:|---|"])
        for row in rounds:
            lines.append(
                f"| {row.get('run_id')} | {row.get('status')} | {row.get('real_api_calls')} | {row.get('reason')} |"
            )
        lines.append("")
    cost = tracked.get("usage_and_cost") or {}
    budget = tracked.get("task_budget") or {}
    lines.extend(
        [
            "## Cost",
            "",
            f"- attempts: `{cost.get('attempts')}`",
            f"- prompt tokens: `{cost.get('prompt_tokens')}`",
            f"- completion tokens: `{cost.get('completion_tokens')}`",
            f"- settled (this result): `{cost.get('settled_rmb')} RMB`",
            f"- task-wide settled: `{budget.get('settled_rmb')} RMB`",
            f"- remaining unreserved: `{budget.get('remaining_unreserved_rmb')} RMB`",
            "",
            "Raw receipts, response text and the budget ledger remain in the ignored",
            "`eval-data/publication-critic/plan101/` namespace.",
            "",
        ]
    )
    return "\n".join(lines)
