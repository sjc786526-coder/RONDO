"""Render tracked Plan 101 JSON/MD without packet or provider bodies."""

from __future__ import annotations

from collections.abc import Mapping


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
        "## Six units",
        "",
        "| unit | balanced accuracy | Wilson | False PASS | False REWRITE | pairs closed | consistency |",
        "|---|---:|---|---:|---:|---:|---:|",
    ]
    for condition in ("thinking_off", "thinking_on"):
        for arm in ("A", "B", "C"):
            key = f"{condition}:{arm}"
            unit = metrics.get(key, {})
            wilson = unit.get("balanced_accuracy_wilson") or {}
            lines.append(
                "| {key} | {ba:.6f} | [{lo:.4f}, {hi:.4f}] | {fp} | {fr} | {pairs} | {cons:.4f} |".format(
                    key=key,
                    ba=float(unit.get("balanced_accuracy") or 0),
                    lo=float(wilson.get("low") or 0),
                    hi=float(wilson.get("high") or 0),
                    fp=unit.get("false_pass"),
                    fr=unit.get("false_rewrite"),
                    pairs=unit.get("pairs_closed"),
                    cons=float(unit.get("repeat_consistency_rate") or 0),
                )
            )
    lines.extend(["", "## thinking_on − thinking_off", "", "| arm | Δ BA | Δ False PASS | Δ False REWRITE | Δ pairs |", "|---|---:|---:|---:|---:|"])
    thinking = differences.get("thinking_on_minus_off") or {}
    for arm in ("A", "B", "C"):
        row = thinking.get(arm) or {}
        lines.append(
            f"| {arm} | {row.get('balanced_accuracy')} | {row.get('false_pass')} | {row.get('false_rewrite')} | {row.get('pairs_closed')} |"
        )
    lines.extend(["", "## Output-expression differences", ""])
    expression = differences.get("expression") or {}
    for condition in ("thinking_off", "thinking_on"):
        lines.append(f"### {condition}")
        lines.append("")
        rows = expression.get(condition) or {}
        lines.append("| contrast | Δ BA | Δ False PASS | Δ False REWRITE |")
        lines.append("|---|---:|---:|---:|")
        for name in ("C_minus_B", "C_minus_A", "B_minus_A"):
            row = rows.get(name) or {}
            lines.append(
                f"| {name} | {row.get('balanced_accuracy')} | {row.get('false_pass')} | {row.get('false_rewrite')} |"
            )
        lines.append("")
    prereg = tracked.get("preregistered_tests") or []
    if prereg:
        lines.extend(["## Preregistered observations", ""])
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
                "## thinking_on versus thinking_off on A and C",
                "",
                "n=27 signal, not a causal conclusion. r4 commissioning had on worse than off on both arms.",
                "",
                "| arm | BA off | BA on | Δ on−off | direction | AUC Δ |",
                "|---|---:|---:|---:|---|---:|",
            ]
        )
        for arm in ("A", "C"):
            row = direction.get(arm) or {}
            lines.append(
                "| {arm} | {off} | {on} | {delta} | {direction} | {auc} |".format(
                    arm=arm,
                    off=row.get("balanced_accuracy_off"),
                    on=row.get("balanced_accuracy_on"),
                    delta=row.get("delta_on_minus_off"),
                    direction=row.get("direction"),
                    auc=row.get("auc_delta_on_minus_off"),
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
