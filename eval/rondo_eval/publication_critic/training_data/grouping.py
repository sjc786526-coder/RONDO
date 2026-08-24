"""Group closure, deterministic split search, coverage and shortcut checks."""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
import hashlib
from typing import Any

from .contract import SPLITS, TrainingDataError
from .dedup import NearDuplicateEdge


class _UnionFind:
    def __init__(self, values: Sequence[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        root = value
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[value] != value:
            value, self.parent[value] = self.parent[value], root
        return root

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            low, high = sorted((left_root, right_root))
            self.parent[high] = low


def build_group_components(
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    *,
    near_duplicate_edges: Sequence[NearDuplicateEdge] = (),
) -> dict[str, str]:
    candidate_ids = [str(row["candidate_id"]) for row in supervision_rows]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise TrainingDataError("duplicate candidate IDs while building group closure")
    union = _UnionFind(candidate_ids)
    candidates = set(candidate_ids)
    for field in ("source_group", "scenario_group", "template_group"):
        by_value: dict[str, list[str]] = defaultdict(list)
        for row in supervision_rows:
            by_value[str(row[field])].append(str(row["candidate_id"]))
        for members in by_value.values():
            for member in members[1:]:
                union.union(members[0], member)
    for pair in pair_rows:
        left = str(pair["preferred_candidate_id"])
        right = str(pair["dispreferred_candidate_id"])
        if left not in candidates or right not in candidates:
            raise TrainingDataError(f"pair {pair['pair_id']} has endpoint outside candidate registry")
        union.union(left, right)
    for edge in near_duplicate_edges:
        if edge.left_candidate_id not in candidates or edge.right_candidate_id not in candidates:
            raise TrainingDataError("near-duplicate edge references an unknown candidate")
        union.union(edge.left_candidate_id, edge.right_candidate_id)

    by_root: dict[str, list[str]] = defaultdict(list)
    for candidate_id in candidate_ids:
        by_root[union.find(candidate_id)].append(candidate_id)
    result: dict[str, str] = {}
    for members in by_root.values():
        digest = hashlib.sha256("\0".join(sorted(members)).encode("utf-8")).hexdigest()[:20]
        for member in members:
            result[member] = f"group-{digest}"
    return result


def validate_group_closure(
    components: Mapping[str, str],
    assignments: Mapping[str, str],
) -> None:
    if set(components) != set(assignments):
        raise TrainingDataError("split assignments do not match group component membership")
    group_splits: dict[str, set[str]] = defaultdict(set)
    for candidate_id, component in components.items():
        split = assignments[candidate_id]
        if split not in SPLITS:
            raise TrainingDataError(f"candidate {candidate_id} has invalid split {split!r}")
        group_splits[component].add(split)
    leaking = sorted(component for component, splits in group_splits.items() if len(splits) != 1)
    if leaking:
        raise TrainingDataError(f"group components cross splits: {leaking}")


def deterministic_grouped_stratified_split(
    components: Mapping[str, str],
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    design_lock: Mapping[str, Any],
) -> dict[str, str]:
    """Search deterministic hash-derived group assignments and fail closed."""

    rows = {str(row["candidate_id"]): row for row in supervision_rows}
    if set(rows) != set(components):
        raise TrainingDataError("split input rows do not match group components")
    contract = design_lock["split_contract"]
    ratios = contract["target_candidate_ratios"]
    split_names = tuple(contract["names"])
    if set(split_names) != SPLITS or abs(sum(float(ratios[name]) for name in split_names) - 1.0) > 1e-9:
        raise TrainingDataError("design lock split names or ratios are invalid")
    attempts = contract["search_attempts"]
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts <= 0:
        raise TrainingDataError("design lock search_attempts must be positive")
    seed = str(contract["seed"])
    groups: dict[str, list[str]] = defaultdict(list)
    for candidate_id, component in components.items():
        groups[component].append(candidate_id)
    for pair in pair_rows:
        left = str(pair["preferred_candidate_id"])
        right = str(pair["dispreferred_candidate_id"])
        if left not in components or right not in components or components[left] != components[right]:
            raise TrainingDataError(f"pair {pair['pair_id']} is not closed in one split group")

    best: tuple[float, tuple[tuple[str, str], ...], dict[str, str]] | None = None
    for attempt in range(attempts):
        assignment_by_group: dict[str, str] = {}
        for component in sorted(groups):
            digest = hashlib.sha256(f"{seed}\0{attempt}\0{component}".encode("utf-8")).digest()
            point = int.from_bytes(digest[:8], "big") / 2**64
            cumulative = 0.0
            selected = split_names[-1]
            for split in split_names:
                cumulative += float(ratios[split])
                if point < cumulative:
                    selected = split
                    break
            assignment_by_group[component] = selected
        assignments = {
            candidate_id: assignment_by_group[component]
            for candidate_id, component in components.items()
        }
        failures = coverage_failures(assignments, supervision_rows, pair_rows, design_lock)
        if failures:
            continue
        counts = Counter(assignments.values())
        total = len(assignments)
        score = sum((counts[name] - total * float(ratios[name])) ** 2 for name in split_names)
        identity = tuple(sorted(assignment_by_group.items()))
        candidate = (score, identity, assignments)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        raise TrainingDataError(
            f"no grouped split satisfies the design lock after {attempts} deterministic attempts"
        )
    validate_group_closure(components, best[2])
    return best[2]


def coverage_failures(
    assignments: Mapping[str, str],
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    design_lock: Mapping[str, Any],
) -> tuple[str, ...]:
    minimums = design_lock["coverage_minimums"]
    contract = design_lock["split_contract"]
    rows = {str(row["candidate_id"]): row for row in supervision_rows}
    failures: list[str] = []
    if set(assignments) != set(rows):
        raise TrainingDataError("coverage assignments do not exactly match candidate IDs")
    invalid_splits = sorted(set(assignments.values()) - SPLITS)
    if invalid_splits:
        raise TrainingDataError(f"coverage assignments contain invalid splits: {invalid_splits}")
    if len(rows) < int(minimums["formal_total_candidates"]):
        failures.append("formal_total_candidates")
    split_counts = Counter(assignments.values())
    total = len(rows)
    tolerance = float(contract["candidate_ratio_tolerance"])
    for split in SPLITS:
        if split_counts[split] < int(minimums["split_candidates"][split]):
            failures.append(f"split_candidates.{split}")
        target = float(contract["target_candidate_ratios"][split])
        if total and abs(split_counts[split] / total - target) > tolerance:
            failures.append(f"split_ratio.{split}")
        for label, required in minimums["split_binary_labels"][split].items():
            observed = sum(
                row["binary_label"] == label and assignments[candidate_id] == split
                for candidate_id, row in rows.items()
            )
            if observed < int(required):
                failures.append(f"split_binary_labels.{split}.{label}")

    class_rule = minimums["publication_classes"]
    for publication_class in class_rule["values"]:
        scenario_groups = {
            row["scenario_group"]
            for row in rows.values()
            if row["publication_class"] == publication_class
        }
        if len(scenario_groups) < int(class_rule["minimum_scenario_groups_per_value_global"]):
            failures.append(f"publication_class_global.{publication_class}")
        for split in SPLITS:
            split_groups = {
                row["scenario_group"]
                for candidate_id, row in rows.items()
                if row["publication_class"] == publication_class and assignments[candidate_id] == split
            }
            if len(split_groups) < int(class_rule["minimum_scenario_groups_per_value_per_split"]):
                failures.append(f"publication_class_split.{split}.{publication_class}")

    boundary_rule = minimums["boundary_hard_dimensions"]
    boundary_pairs = [pair for pair in pair_rows if pair["kind"] == "boundary"]
    for dimension in boundary_rule["values"]:
        matching = [pair for pair in boundary_pairs if pair["target_dimension"] == dimension]
        if len(matching) < int(boundary_rule["minimum_pairs_per_value_global"]):
            failures.append(f"boundary_global.{dimension}")
        for split in SPLITS:
            observed = sum(assignments[pair["preferred_candidate_id"]] == split for pair in matching)
            if observed < int(boundary_rule["minimum_pairs_per_value_per_split"]):
                failures.append(f"boundary_split.{split}.{dimension}")

    within_pairs = [pair for pair in pair_rows if pair["kind"] == "within_pass"]
    for split in SPLITS:
        observed = sum(assignments[pair["preferred_candidate_id"]] == split for pair in within_pairs)
        if observed < int(minimums["within_pass_pairs_per_split"]):
            failures.append(f"within_pass.{split}")
        mixed = sum(
            assignments[candidate_id] == split and "natural_mixed" in row["slices"]
            for candidate_id, row in rows.items()
        )
        if mixed < int(minimums["natural_mixed_binary_candidates_per_split"]):
            failures.append(f"natural_mixed.{split}")
        for role in minimums["roles_per_split"]:
            if not any(assignments[candidate_id] == split and row["actor_role"] == role for candidate_id, row in rows.items()):
                failures.append(f"role.{split}.{role}")
        for style in minimums["styles_per_split"]:
            if not any(assignments[candidate_id] == split and row["style"] == style for candidate_id, row in rows.items()):
                failures.append(f"style.{split}.{style}")
        long_count = sum(
            assignments[candidate_id] == split and row["length_bucket"] == "long"
            for candidate_id, row in rows.items()
        )
        if long_count < int(minimums["long_input_candidates_per_split"]):
            failures.append(f"long.{split}")
    unicode_groups = {row["scenario_group"] for row in rows.values() if row["unicode"]}
    if len(unicode_groups) < int(minimums["unicode_scenario_groups_global"]):
        failures.append("unicode_scenario_groups_global")
    priority = minimums.get("priority_slices", {})
    if priority:
        internal_rewrites = sum(
            row["binary_label"] == "REWRITE" and "internal_consistency" in row["defects"]
            for row in rows.values()
        )
        if internal_rewrites < int(priority["internal_consistency_rewrite"]):
            failures.append("priority.internal_consistency_rewrite")
        special_pairs = {
            "new_completed_useful_state_boundary_pairs": (
                "new_event_completed",
                "useful_state_transfer",
            ),
            "new_completed_scope_signal_boundary_pairs": (
                "new_event_completed",
                "scope_and_signal",
            ),
        }
        for key, (publication_class, dimension) in special_pairs.items():
            observed = sum(
                pair["target_dimension"] == dimension
                and rows[str(pair["preferred_candidate_id"])]["publication_class"] == publication_class
                for pair in boundary_pairs
            )
            if observed < int(priority[key]):
                failures.append(f"priority.{key}")
        threshold_pairs = sum(
            pair["target_dimension"] == "conditional_continuity"
            or "threshold_near_handoff" in rows[str(pair["preferred_candidate_id"])]["slices"]
            or "threshold_near_handoff" in rows[str(pair["dispreferred_candidate_id"])]["slices"]
            for pair in boundary_pairs
        )
        if threshold_pairs < int(priority["threshold_near_handoff_boundary_pairs"]):
            failures.append("priority.threshold_near_handoff_boundary_pairs")
        for key, required in priority.items():
            if not key.endswith("_label_each"):
                continue
            slice_name = {
                "continuity_known_stale": "freshness_known_stale",
            }.get(key.removesuffix("_label_each"), key.removesuffix("_label_each"))
            for label in ("PASS", "REWRITE"):
                observed = sum(
                    row["binary_label"] == label and slice_name in row["slices"]
                    for row in rows.values()
                )
                if observed < int(required):
                    failures.append(f"priority.{slice_name}.{label}")
    return tuple(sorted(set(failures)))


def shortcut_contingencies(
    supervision_rows: Sequence[Mapping[str, Any]],
    dimensions: Sequence[str],
) -> dict[str, dict[str, dict[str, int]]]:
    report: dict[str, dict[str, Counter[str]]] = {}
    for dimension in dimensions:
        if dimension == "binary_label":
            continue
        values: dict[str, Counter[str]] = defaultdict(Counter)
        for row in supervision_rows:
            value = _shortcut_value(row, dimension)
            values[str(value)][str(row["binary_label"])] += 1
        report[dimension] = values
    return {
        dimension: {value: dict(sorted(counts.items())) for value, counts in sorted(values.items())}
        for dimension, values in sorted(report.items())
    }


def reject_perfect_shortcuts(
    contingencies: Mapping[str, Mapping[str, Mapping[str, int]]],
    *,
    minimum_support: int = 4,
) -> None:
    findings = []
    for dimension, values in contingencies.items():
        for value, labels in values.items():
            support = sum(labels.values())
            if support >= minimum_support and len([count for count in labels.values() if count]) == 1:
                findings.append(f"{dimension}={value} support={support}")
    if findings:
        raise TrainingDataError(f"perfect Binary-label shortcuts detected: {sorted(findings)}")


def _shortcut_value(row: Mapping[str, Any], dimension: str) -> Any:
    if dimension == "split":
        return row.get("proposed_split")
    slices = set(row.get("slices", ()))
    if dimension == "continuity_state":
        matches = [
            name
            for name in ("continuity_available", "continuity_unavailable", "continuity_not_applicable")
            if name in slices
        ]
        if len(matches) != 1:
            raise TrainingDataError(
                f"candidate {row.get('candidate_id')} must declare one canonical continuity slice"
            )
        return matches[0].removeprefix("continuity_")
    if dimension == "evidence_appearance":
        for name in (
            "evidence_count_omitted",
            "evidence_present",
            "evidence_none",
            "evidence_not_applicable",
        ):
            if name in slices:
                return name.removeprefix("evidence_")
        raise TrainingDataError(
            f"candidate {row.get('candidate_id')} must declare a canonical evidence slice"
        )
    if dimension not in row:
        raise TrainingDataError(f"shortcut dimension has no canonical source: {dimension}")
    return row[dimension]
