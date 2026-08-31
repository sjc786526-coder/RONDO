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
