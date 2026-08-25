from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.consumer import (  # noqa: E402
    DatasetConsumer,
)
from rondo_eval.publication_critic.identity import (  # noqa: E402
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from rondo_eval.publication_critic.selection.archive import SelectionArchive  # noqa: E402
from rondo_eval.publication_critic.selection.contract import (  # noqa: E402
    CANDIDATES,
    EXPECTED_JUDGE_IDENTITY,
    FREEZE_SCHEMA,
    SELECTION_METHOD,
    SelectionError,
    default_protocol,
    default_runtime,
    freeze_sha256,
    validate_freeze,
)
from rondo_eval.publication_critic.selection.decision import (  # noqa: E402
    VALIDATION_SCHEMA,
    build_selection_lock,
    evaluate_unseen_confirmation,
    evaluate_validation,
    validate_unseen_confirmation,
    validate_validation_result,
)
from rondo_eval.publication_critic.selection import judge as judge_module  # noqa: E402
from rondo_eval.publication_critic.selection.judge import (  # noqa: E402
    BATCH_SCHEMA,
    aggregate_batches,
    build_judge_package,
    model_agreement,
    reference_agreement,
)
from rondo_eval.publication_critic.selection.lock import (  # noqa: E402
    lock_sha256,
    validate_lock,
)
from rondo_eval.publication_critic.selection.metrics import (  # noqa: E402
    build_labeled_rows,
    candidate_metrics,
    operating_points,
    select_threshold,
)
from rondo_eval.publication_critic.selection.dataset_source import (  # noqa: E402
    load_split,
)
from rondo_eval.publication_critic.selection.release import (  # noqa: E402
    SCHEMA as RELEASE_SCHEMA,
)
from rondo_eval.publication_critic.selection.release import (  # noqa: E402
    build_split_release,
    release_sha256,
    validate_release,
)

V8_ROOT = REPO_ROOT / "training" / "publication-critic-v8"
# The Plan 066 train+validation bundle is a local ignored asset in the main
# physical root; the mixed v8 tree is tracked and always present.
BUNDLE_ROOT = (
    Path("/home/sjc/desktop/RONDO/eval-data/publication-critic/plan068/handoff")
    / "bundle-plan066-final-01"
)
MIXED_V8_BODY_FILES = tuple(
    V8_ROOT / name
    for name in ("packets.jsonl", "supervision.jsonl", "pairs.jsonl", "token-census.jsonl")
)
MANIFEST_SHA256 = sha256_file(V8_ROOT / "manifest.json")
ARTIFACTS = {"base": "a" * 64, "c1": "b" * 64, "c3": "c" * 64}


def _packet(title: str) -> dict[str, object]:
    return {
        "qualification": {"packet_schema": "v1", "rubric": "v1"},
        "actor_role": "member",
        "target_kind": "new_event",
        "local_scope": {"title": title},
        "continuity": {"state": "not_applicable"},
        "evidence_v1": {"state": "not_applicable"},
        "candidate": {"summary": f"summary {title}", "handoff": f"handoff {title}"},
    }


def _release(
    split: str,
    labels: list[str],
    *,
    pairs: list[tuple[str, str, str]] | None = None,
    lock_sha: str | None = None,
) -> dict[str, object]:
    """A schema-valid synthetic release; never the real unseen bodies."""

    identifiers = [f"s{index:02d}" for index in range(len(labels))]
    return validate_release(
        {
            "schema": RELEASE_SCHEMA,
            "split": split,
            "dataset_revision": "v8",
            "dataset_manifest_sha256": MANIFEST_SHA256,
            "authorization": (
                {"kind": "selection_lock", "selection_lock_sha256": lock_sha}
                if split == "unseen_test"
                else {"kind": "frozen_protocol_split", "selection_lock_sha256": None}
            ),
            "items": [
                {
                    "candidate_id": candidate_id,
                    "packet": _packet(candidate_id),
                    "dropped_oldest_publications": 0,
                }
                for candidate_id in identifiers
            ],
            "supervision": [
                {
                    "candidate_id": candidate_id,
                    "binary_label": label,
                    "publication_class": "new_event_completed",
                    "completion_state": "completed",
                    "actor_role": "member",
                    "hard_focus": None,
                    "length_bucket": "medium",
                    "style": "formal",
                    "unicode": False,
                    "scenario_id": candidate_id,
                    "scenario_group": candidate_id,
                    "slices": ["synthetic"],
                }
                for candidate_id, label in zip(identifiers, labels)
            ],
            "pairs": [
                {
                    "pair_id": pair_id,
                    "kind": "boundary",
                    "preferred_candidate_id": preferred,
                    "dispreferred_candidate_id": dispreferred,
                    "target_dimension": "synthetic",
                }
                for pair_id, preferred, dispreferred in sorted(pairs or [])
            ],
        }
    )


def _separable(release: dict[str, object], *, flips: int = 0) -> dict[str, dict[str, float]]:
    """Scores that respect the labels, optionally flipping the first N rows."""

    scores: dict[str, dict[str, float]] = {}
    flipped = 0
    for row in release["supervision"]:
        wants_pass = row["binary_label"] == "PASS"
        if flipped < flips:
            wants_pass = not wants_pass
            flipped += 1
        raw = 3.0 if wants_pass else -3.0
        scores[row["candidate_id"]] = {
            "score": 0.95 if wants_pass else 0.05,
            "raw_logit": raw,
        }
    return scores


def _runtime_facts(count: int, **overrides: object) -> dict[str, object]:
    facts = {
        "load_seconds": 4.0,
        "warm_p95_latency_ms": 90.0,
        "peak_rss_bytes": 4_300_000_000,
        "peak_vram_bytes": 3_500_000_000,
        "typed_failure_count": 0,
        "scored_count": count,
    }
    facts.update(overrides)
    return facts


def _freeze(mode: str = "formal") -> dict[str, object]:
    return validate_freeze(
        {
            "schema": FREEZE_SCHEMA,
            "mode": mode,
            "run_id": f"plan073-{mode}-20260825T120000Z-test",
            "candidates": list(CANDIDATES),
            "dataset": {
                "revision": "v8",
                "root": "training/publication-critic-v8",
                "manifest_sha256": MANIFEST_SHA256,
                "unseen_test_sealed_at_freeze": True,
            },
            "artifacts": {
                candidate: {
                    "deployment_artifact_sha256": ARTIFACTS[candidate],
                    "lineage": f"test-{candidate}",
                }
                for candidate in CANDIDATES
            },
            "runtime": default_runtime(),
            "protocol": default_protocol(),
            "source": {
                "git_commit": "0" * 40,
                "tracked_source_clean": True,
                "environment_lock_path": "eval/environments/publication-critic-plan068/uv.lock",
                "environment_lock_sha256": "e" * 64,
            },
        }
    )


_PACKAGES: dict[str, dict[str, object]] = {}


def _evaluate(freeze, release, observations, aggregate=None):
    """Evaluate with the Judge package that matches the aggregate."""

    package = None if aggregate is None else _PACKAGES[aggregate["package_id"]]
    return evaluate_validation(freeze, release, observations, aggregate, package)


def _lock(result, freeze, release, observations, aggregate, **overrides):
    arguments = {
        "release_value": release,
        "observations": observations,
        "judge_aggregate": aggregate,
        "judge_package": _PACKAGES[aggregate["package_id"]],
        "dataset_root": V8_ROOT,
        "bundle_root": BUNDLE_ROOT,
    }
    arguments.update(overrides)
    return build_selection_lock(result, freeze, **arguments)


def _judge(
    release: dict[str, object],
    *,
    package_id: str = "plan073-case",
    reference_flips: int = 0,
    model_identities: list[str] | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    package, mapping = build_judge_package(
        release,
        "rubric body",
        salt="s" * 32,
        package_id=package_id,
        batch_size=4,
    )
    _PACKAGES[package["package_id"]] = package
    labels = {
        row["candidate_id"]: row["binary_label"] for row in release["supervision"]
    }
    flipped = 0
    responses = []
    for index, batch in enumerate(package["batches"]):
        verdicts = []
        for item in batch["items"]:
            label = labels[mapping["mapping"][item["item_id"]]]
            if flipped < reference_flips:
                label = "PASS" if label == "REWRITE" else "REWRITE"
                flipped += 1
            verdicts.append(
                {
                    "item_id": item["item_id"],
                    "verdict": label,
                    "confidence": "medium",
                    "reason": "test",
                }
            )
        identities = model_identities or [EXPECTED_JUDGE_IDENTITY]
        responses.append(
            {
                "schema": BATCH_SCHEMA,
                "package_id": package["package_id"],
                "batch_id": batch["batch_id"],
                "model_identity": identities[min(index, len(identities) - 1)],
                "judged_at": "2026-08-25",
                "verdicts": verdicts,
            }
        )
    return package, mapping, responses


@unittest.skipUnless(
    (BUNDLE_ROOT / "bundle-manifest.json").is_file(),
    "the Plan 066 train+validation bundle is not present locally",
)
class SplitReleaseTest(unittest.TestCase):
    def test_validation_release_of_the_frozen_dataset_is_open(self) -> None:
        release = build_split_release(
            V8_ROOT, "validation", repo_root=REPO_ROOT, bundle_root=BUNDLE_ROOT
        )
        self.assertEqual(release["split"], "validation")
        self.assertEqual(len(release["items"]), 55)
        self.assertEqual(
            release["authorization"],
            {"kind": "frozen_protocol_split", "selection_lock_sha256": None},
        )
        labels = {row["binary_label"] for row in release["supervision"]}
        self.assertEqual(labels, {"PASS", "REWRITE"})

    def test_unseen_release_without_a_lock_is_refused(self) -> None:
        with self.assertRaises(SelectionError):
            build_split_release(V8_ROOT, "unseen_test", repo_root=REPO_ROOT)

    def test_unseen_release_refuses_an_unsealed_lock_document(self) -> None:
        broken = {"schema": "not-a-lock", "terminal": "SELECTED"}
        with self.assertRaises(SelectionError):
            build_split_release(
                V8_ROOT, "unseen_test", repo_root=REPO_ROOT, selection_lock=broken
            )

    def test_validation_release_refuses_a_lock(self) -> None:
        with self.assertRaises(SelectionError):
            build_split_release(
                V8_ROOT,
                "validation",
                repo_root=REPO_ROOT,
                bundle_root=BUNDLE_ROOT,
                selection_lock=_locked(_freeze()),
            )

    def test_release_authorization_must_match_its_split(self) -> None:
        release = _release("validation", ["PASS", "REWRITE"])
        release["authorization"] = {
            "kind": "selection_lock",
            "selection_lock_sha256": "d" * 64,
        }
        with self.assertRaises(SelectionError):
            validate_release(release)


@unittest.skipUnless(
    (BUNDLE_ROOT / "bundle-manifest.json").is_file(),
    "the Plan 066 train+validation bundle is not present locally",
)
class UnseenContainmentTest(unittest.TestCase):
    """Validation must be read from an asset that holds no unseen row at all."""

    def setUp(self) -> None:
        supervision = [
            json.loads(line)
            for line in (V8_ROOT / "supervision.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        self.unseen_ids = {
            str(row["candidate_id"])
            for row in supervision
            if row["proposed_split"] == "unseen_test"
        }
        self.assertTrue(self.unseen_ids)

    def _recorded_reads(self, run) -> tuple[set[str], object]:
        """Run something while recording every file path it opens."""

        opened: set[str] = set()

        def spy(method):
            def wrapper(self, *args, **kwargs):
                opened.add(str(self))
                return method(self, *args, **kwargs)

            return wrapper

        with mock.patch.object(Path, "open", spy(Path.open)), mock.patch.object(
            Path, "read_text", spy(Path.read_text)
        ), mock.patch.object(Path, "read_bytes", spy(Path.read_bytes)):
            result = run()
        return opened, result

    def test_validation_never_opens_a_mixed_dataset_body_file(self) -> None:
        opened, release = self._recorded_reads(
            lambda: build_split_release(
                V8_ROOT, "validation", repo_root=REPO_ROOT, bundle_root=BUNDLE_ROOT
            )
        )
        touched = {Path(path).resolve() for path in opened}
        mixed = {path.resolve() for path in MIXED_V8_BODY_FILES}
        self.assertEqual(touched & mixed, set())
        self.assertEqual(len(release["items"]), 55)

    def test_validation_source_holds_no_unseen_identifier(self) -> None:
        source = load_split(
            V8_ROOT, "validation", repo_root=REPO_ROOT, bundle_root=BUNDLE_ROOT
        )
        held = set(source.packets) | set(source.supervision) | set(
            source.dropped_oldest_publications
        )
        for row in source.pairs:
            held.add(str(row["preferred_candidate_id"]))
            held.add(str(row["dispreferred_candidate_id"]))
        self.assertEqual(held & self.unseen_ids, set())
        self.assertEqual(source.origin, "plan066-train-validation-bundle-v1")

    def test_validation_without_the_unseen_free_bundle_is_refused(self) -> None:
        with self.assertRaises(SelectionError):
            load_split(V8_ROOT, "validation", repo_root=REPO_ROOT)

    def test_split_source_gate_matches_the_release_gate(self) -> None:
        with self.assertRaises(SelectionError):
            load_split(V8_ROOT, "unseen_test", repo_root=REPO_ROOT)
        with self.assertRaises(SelectionError):
            load_split(
                V8_ROOT,
                "validation",
                repo_root=REPO_ROOT,
                bundle_root=BUNDLE_ROOT,
                selection_lock=_locked(_freeze()),
            )


class ThresholdSearchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.floors = default_protocol()["quality_floors"]

    def test_search_space_covers_endpoints_and_adjacent_midpoints(self) -> None:
        release = _release("validation", ["PASS", "REWRITE"])
        rows = build_labeled_rows(release, _separable(release))
        points = operating_points(rows)
        self.assertEqual(points, (0.0, 0.05, 0.5, 0.95, 1.0))

    def test_perfectly_separable_candidate_is_feasible(self) -> None:
        release = _release("validation", ["PASS"] * 4 + ["REWRITE"] * 4)
        rows = build_labeled_rows(release, _separable(release))
        search = select_threshold(rows, self.floors)
        self.assertTrue(search["feasible"])
        self.assertEqual(search["operating_point"]["confusion"]["false_pass"], 0)
        # Ties on balanced accuracy resolve to the most conservative threshold.
        self.assertEqual(search["threshold"], 0.95)

    def test_candidate_without_an_admissible_point_is_reported_not_hidden(self) -> None:
        release = _release("validation", ["PASS"] * 4 + ["REWRITE"] * 4)
        rows = build_labeled_rows(release, _separable(release, flips=4))
        search = select_threshold(rows, self.floors)
        self.assertFalse(search["feasible"])
        self.assertEqual(search["feasible_point_count"], 0)
        self.assertIsNotNone(search["threshold"])
        self.assertEqual(search["rule"], SELECTION_METHOD["threshold_rule"])

    def test_metrics_keep_error_types_and_pairs_separate(self) -> None:
        release = _release(
            "validation",
            ["PASS", "REWRITE", "PASS", "REWRITE"],
            pairs=[("p1", "s00", "s01"), ("p2", "s02", "s03")],
        )
        rows = build_labeled_rows(release, _separable(release, flips=1))
        metrics = candidate_metrics(release, rows, 0.5)
        confusion = metrics["overall"]["confusion"]
        self.assertEqual(confusion["false_rewrite"], 1)
        self.assertEqual(confusion["false_pass"], 0)
        self.assertEqual(metrics["errors"]["false_rewrite_candidate_ids"], ["s00"])
        self.assertEqual(metrics["boundary_pairs"]["count"], 2)
        self.assertEqual(metrics["boundary_pairs"]["strict_wins"], 1)
        self.assertIn("synthetic", metrics["by_slice"])
        self.assertEqual(metrics["by_slice"]["synthetic"]["count"], 4)


class JudgeExchangeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.release = _release(
            "validation",
            ["PASS", "REWRITE"] * 4,
            pairs=[("p1", "s00", "s01")],
        )

    def test_package_hides_labels_pair_direction_and_dataset_identity(self) -> None:
        package, mapping, _ = _judge(self.release)
        # The package declares the answer vocabulary once; nothing per item may
        # carry supervision, split, pair or dataset identity.
        bodies = json.dumps(package["batches"], ensure_ascii=False)
        for leak in (
            "binary_label",
            "PASS",
            "REWRITE",
            "proposed_split",
            "validation",
            "pair_id",
            "preferred",
            "slices",
            "scenario_group",
        ):
            self.assertNotIn(leak, bodies, msg=leak)
        self.assertEqual(package["item_count"], len(self.release["items"]))
        self.assertEqual(
            sorted(mapping["mapping"].values()),
            sorted(row["candidate_id"] for row in self.release["supervision"]),
        )

    @unittest.skipUnless(
        (BUNDLE_ROOT / "bundle-manifest.json").is_file(),
        "the Plan 066 train+validation bundle is not present locally",
    )
    def test_real_validation_package_carries_no_dataset_identifier(self) -> None:
        release = build_split_release(
            V8_ROOT, "validation", repo_root=REPO_ROOT, bundle_root=BUNDLE_ROOT
        )
        package, mapping, _ = _judge(release, package_id="plan073-live")
        bodies = json.dumps(package, ensure_ascii=False)
        # v8 candidate ids encode the pair direction (``-qplus`` / ``-qminus``).
        for leak in ("qplus", "qminus", "pc059-", "candidate_id", "binary_label"):
            self.assertNotIn(leak, bodies, msg=leak)
        for candidate_id in mapping["mapping"].values():
            self.assertNotIn(candidate_id, bodies)

    def test_blinded_order_is_not_the_dataset_order(self) -> None:
        package, mapping, _ = _judge(self.release)
        blinded = [
            mapping["mapping"][item["item_id"]]
            for batch in package["batches"]
            for item in batch["items"]
        ]
        self.assertNotEqual(blinded, sorted(blinded))
        self.assertEqual(sorted(blinded), sorted(blinded))

    def test_per_batch_documents_carry_only_their_own_items(self) -> None:
        package, _, _ = _judge(self.release)
        documents = judge_module.batch_documents(package)
        self.assertEqual(
            sorted(documents), sorted(batch["batch_id"] for batch in package["batches"])
        )
        for batch in package["batches"]:
            document = documents[batch["batch_id"]]
            self.assertEqual(document["items"], batch["items"])
            self.assertEqual(document["task"], package["task"])
            self.assertNotIn("batches", document)

    def test_aggregate_requires_every_batch_exactly_once(self) -> None:
        package, mapping, responses = _judge(self.release)
        with self.assertRaises(SelectionError):
            aggregate_batches(package, mapping, responses[:-1])
        with self.assertRaises(SelectionError):
            aggregate_batches(package, mapping, [*responses, responses[0]])

    def test_aggregate_refuses_mixed_judging_model_identities(self) -> None:
        package, mapping, responses = _judge(
            self.release, model_identities=[EXPECTED_JUDGE_IDENTITY, "claude-sonnet-5"]
        )
        with self.assertRaises(SelectionError):
            aggregate_batches(package, mapping, responses)

    def test_response_must_cover_its_own_batch(self) -> None:
        package, mapping, responses = _judge(self.release)
        broken = copy.deepcopy(responses)
        broken[0]["verdicts"][0]["item_id"] = broken[1]["verdicts"][0]["item_id"]
        with self.assertRaises(SelectionError):
            aggregate_batches(package, mapping, broken)

    def test_aggregate_deblinds_and_reports_reference_agreement(self) -> None:
        package, mapping, responses = _judge(self.release, reference_flips=2)
        aggregate = aggregate_batches(package, mapping, responses)
        self.assertEqual(set(aggregate["verdicts"]), {
            row["candidate_id"] for row in self.release["supervision"]
        })
        agreement = reference_agreement(self.release, aggregate)
        self.assertEqual(agreement["agreements"], 6)
        self.assertEqual(len(agreement["disagreement_candidate_ids"]), 2)

    def test_model_agreement_requires_the_same_cohort(self) -> None:
        package, mapping, responses = _judge(self.release)
        aggregate = aggregate_batches(package, mapping, responses)
        with self.assertRaises(SelectionError):
            model_agreement(aggregate, {"s00": "PASS"})


def _observations(
    release: dict[str, object],
    flips: dict[str, int],
    **runtime: object,
) -> dict[str, dict[str, object]]:
    return {
        candidate: {
            "deployment_artifact_sha256": ARTIFACTS[candidate],
            "scores": _separable(release, flips=flips[candidate]),
            "runtime": _runtime_facts(
                len(release["items"]), **runtime.get(candidate, {})
            ),
        }
        for candidate in CANDIDATES
    }


def _validation_release() -> dict[str, object]:
    labels = ["PASS"] * 12 + ["REWRITE"] * 12
    return _release(
        "validation",
        labels,
        pairs=[(f"p{index}", f"s{index:02d}", f"s{index + 12:02d}") for index in range(12)],
    )


def _frozen_validation_release() -> dict[str, object]:
    return build_split_release(
        V8_ROOT, "validation", repo_root=REPO_ROOT, bundle_root=BUNDLE_ROOT
    )


def _locked(freeze: dict[str, object]) -> dict[str, object]:
    """A real lock: the release is the one the frozen dataset produces."""

    release = _frozen_validation_release()
    package, mapping, responses = _judge(release, package_id="plan073-anchor")
    aggregate = aggregate_batches(package, mapping, responses)
    observations = _observations(release, {"base": 0, "c1": 0, "c3": 0})
    result = _evaluate(freeze, release, observations, aggregate)
    return _lock(result, freeze, release, observations, aggregate)


class ValidationSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.freeze = _freeze()
        self.release = _validation_release()
        package, mapping, responses = _judge(self.release, package_id="plan073-lead")
        self.aggregate = aggregate_batches(package, mapping, responses)

    def test_lower_false_pass_wins_before_any_other_key(self) -> None:
        result = _evaluate(
            self.freeze,
            self.release,
            _observations(self.release, {"base": 3, "c1": 1, "c3": 0}),
            self.aggregate,
        )
        self.assertEqual(result["terminal"], "SELECTED")
        self.assertEqual(result["selected"], "c3")
        self.assertEqual(result["runner_up"], "c1")
        self.assertEqual(result["ranking"], ["c3", "c1", "base"])
        self.assertEqual(result["schema"], VALIDATION_SCHEMA)

    def test_equal_evidence_prefers_the_earlier_lineage_stage(self) -> None:
        result = _evaluate(
            self.freeze,
            self.release,
            _observations(self.release, {"base": 0, "c1": 0, "c3": 0}),
            self.aggregate,
        )
        self.assertEqual(result["selected"], "base")
        self.assertEqual(result["ranking"], ["base", "c1", "c3"])

    def test_no_admissible_candidate_is_a_no_go_and_keeps_unseen_sealed(self) -> None:
        result = _evaluate(
            self.freeze,
            self.release,
            _observations(self.release, {"base": 9, "c1": 9, "c3": 9}),
            self.aggregate,
        )
        self.assertEqual(result["terminal"], "NO_GO")
        self.assertIsNone(result["selected"])
        with self.assertRaises(SelectionError):
            _lock(
                result,
                self.freeze,
                self.release,
                _observations(self.release, {"base": 9, "c1": 9, "c3": 9}),
                self.aggregate,
            )

    def test_runtime_gate_failure_removes_a_candidate_without_ranking_it(self) -> None:
        result = _evaluate(
            self.freeze,
            self.release,
            _observations(
                self.release,
                {"base": 3, "c1": 1, "c3": 0},
                c3={"peak_vram_bytes": 9_000_000_000},
            ),
            self.aggregate,
        )
        self.assertEqual(
            result["candidates"]["c3"]["admission"]["failed_gates"],
            ["peak_vram_gate_failed"],
        )
        self.assertEqual(result["selected"], "c1")

    def test_missing_judge_evidence_is_inconclusive(self) -> None:
        result = _evaluate(
            self.freeze,
            self.release,
            _observations(self.release, {"base": 3, "c1": 1, "c3": 0}),
            None,
        )
        self.assertEqual(result["terminal"], "INCONCLUSIVE")
        self.assertEqual(result["reasons"], ["judge_evidence_absent"])

    def test_judge_gate_activates_only_when_it_tracks_the_reference(self) -> None:
        package, mapping, responses = _judge(
            self.release, package_id="plan073-noisy", reference_flips=16
        )
        noisy = aggregate_batches(package, mapping, responses)
        result = _evaluate(
            self.freeze,
            self.release,
            _observations(self.release, {"base": 3, "c1": 1, "c3": 0}),
            noisy,
        )
        self.assertFalse(result["judge"]["gate_applicable"])
        self.assertEqual(result["terminal"], "SELECTED")
        self.assertIn(
            "judge_sanity_gate_not_applicable_reference_agreement_too_low",
            result["reasons"],
        )

    def test_judge_disagreement_with_the_leader_is_inconclusive_not_go(self) -> None:
        # The Judge still tracks the frozen reference closely enough for its
        # gate to activate (17/24), yet it and the leading model disagree on
        # 10 of 24 rows because their errors fall on disjoint candidates.
        aggregate = copy.deepcopy(self.aggregate)
        model_errors = {f"s{index:02d}" for index in range(3)}
        judge_errors = [f"s{index:02d}" for index in range(3, 10)]
        self.assertFalse(model_errors & set(judge_errors))
        for candidate_id in judge_errors:
            row = aggregate["verdicts"][candidate_id]
            row["verdict"] = "REWRITE" if row["verdict"] == "PASS" else "PASS"
        result = _evaluate(
            self.freeze,
            self.release,
            _observations(self.release, {"base": 3, "c1": 3, "c3": 3}),
            aggregate,
        )
        self.assertTrue(result["judge"]["gate_applicable"])
        self.assertAlmostEqual(
            result["judge"]["reference_agreement"]["agreement_rate"], 17 / 24
        )
        self.assertEqual(result["terminal"], "INCONCLUSIVE")
        self.assertIsNone(result["selected"])

    def test_unexpected_judging_model_is_inconclusive(self) -> None:
        package, mapping, responses = _judge(
            self.release,
            package_id="plan073-other-model",
            model_identities=["claude-sonnet-5"],
        )
        foreign = aggregate_batches(package, mapping, responses)
        result = _evaluate(
            self.freeze,
            self.release,
            _observations(self.release, {"base": 3, "c1": 1, "c3": 0}),
            foreign,
        )
        self.assertEqual(result["terminal"], "INCONCLUSIVE")
        self.assertEqual(
            result["reasons"], ["judge_model_identity_is_not_the_authorised_model"]
        )

    def test_judge_aggregate_must_bind_to_the_package_it_came_from(self) -> None:
        package, mapping, responses = _judge(self.release, package_id="plan073-bound")
        aggregate = aggregate_batches(package, mapping, responses)
        observations = _observations(self.release, {"base": 3, "c1": 1, "c3": 0})
        evaluate_validation(
            self.freeze, self.release, observations, aggregate, package
        )
        other, _other_mapping, _other_responses = _judge(
            self.release, package_id="plan073-elsewhere"
        )
        self.assertNotEqual(other["package_id"], package["package_id"])
        with self.assertRaises(SelectionError):
            evaluate_validation(
                self.freeze, self.release, observations, aggregate, other
            )
        # An aggregate with no package at all is refused as well.
        with self.assertRaises(SelectionError):
            evaluate_validation(self.freeze, self.release, observations, aggregate)

    def test_incomplete_scoring_is_refused_rather_than_ranked(self) -> None:
        observations = _observations(self.release, {"base": 0, "c1": 0, "c3": 0})
        observations["c1"]["runtime"]["typed_failure_count"] = 1
        with self.assertRaises(SelectionError):
            _evaluate(
                self.freeze, self.release, observations, self.aggregate
            )

    def test_candidate_artifact_drift_is_refused(self) -> None:
        observations = _observations(self.release, {"base": 0, "c1": 0, "c3": 0})
        observations["c1"]["deployment_artifact_sha256"] = "9" * 64
        with self.assertRaises(SelectionError):
            _evaluate(
                self.freeze, self.release, observations, self.aggregate
            )

    def test_validation_requires_the_validation_split(self) -> None:
        unseen = _release("unseen_test", ["PASS", "REWRITE"], lock_sha="d" * 64)
        with self.assertRaises(SelectionError):
            _evaluate(
                self.freeze, unseen, _observations(unseen, {c: 0 for c in CANDIDATES}), self.aggregate
            )


class SelectionLockTest(unittest.TestCase):
    def setUp(self) -> None:
        self.freeze = _freeze()
        self.lock = _locked(self.freeze)

    def test_lock_names_one_indivisible_combination(self) -> None:
        validate_lock(self.lock)
        # All three are equally admissible here, so the frozen final tie-break
        # picks the earliest lineage stage.
        self.assertEqual(self.lock["selected"]["candidate"], "base")
        self.assertEqual(
            self.lock["selected"]["deployment_artifact_sha256"], ARTIFACTS["base"]
        )
        self.assertEqual(self.lock["selected"]["runtime"], default_runtime())
        self.assertTrue(self.lock["unseen_release_authorized"])

    def test_lock_refuses_a_release_the_frozen_dataset_did_not_produce(self) -> None:
        # A synthetic release that merely claims the frozen manifest hash, with
        # matching scores and Judge evidence, is still not the frozen cohort.
        release = _validation_release()
        self.assertEqual(release["dataset_manifest_sha256"], MANIFEST_SHA256)
        package, mapping, responses = _judge(release, package_id="plan073-fabricated")
        aggregate = aggregate_batches(package, mapping, responses)
        observations = _observations(release, {"base": 0, "c1": 0, "c3": 0})
        result = _evaluate(self.freeze, release, observations, aggregate)
        self.assertEqual(result["terminal"], "SELECTED")
        with self.assertRaises(SelectionError):
            _lock(result, self.freeze, release, observations, aggregate)

    def test_lock_requires_a_formal_validation_run(self) -> None:
        commissioning = _freeze("commissioning")
        release = _validation_release()
        package, mapping, responses = _judge(release, package_id="plan073-comm")
        aggregate = aggregate_batches(package, mapping, responses)
        observations = _observations(release, {"base": 3, "c1": 1, "c3": 0})
        result = _evaluate(commissioning, release, observations, aggregate)
        with self.assertRaises(SelectionError):
            _lock(result, commissioning, release, observations, aggregate)

    def test_forged_selected_result_cannot_open_unseen_test(self) -> None:
        release = _validation_release()
        package, mapping, responses = _judge(release, package_id="plan073-forged")
        aggregate = aggregate_batches(package, mapping, responses)
        # Every candidate fails the floors, so the honest terminal is NO_GO.
        observations = _observations(release, {"base": 9, "c1": 9, "c3": 9})
        rejected = _evaluate(self.freeze, release, observations, aggregate)
        self.assertEqual(rejected["terminal"], "NO_GO")

        forged = copy.deepcopy(rejected)
        forged["terminal"] = "SELECTED"
        forged["selected"] = "base"
        forged["ranking"] = ["base"]
        forged["reasons"] = ["forged"]
        with self.assertRaises(SelectionError):
            _lock(forged, self.freeze, release, observations, aggregate)

        # Flipping the admission flag as well is still not enough: admission has
        # to follow from the scored rows the document itself carries.
        forged["candidates"]["base"]["admission"] = {
            "admissible": True,
            "failed_gates": [],
        }
        with self.assertRaises(SelectionError):
            _lock(forged, self.freeze, release, observations, aggregate)
        with self.assertRaises(SelectionError):
            validate_validation_result(forged, self.freeze)

    def test_tampered_metrics_are_caught_by_recomputation(self) -> None:
        release = _validation_release()
        package, mapping, responses = _judge(release, package_id="plan073-tamper")
        aggregate = aggregate_batches(package, mapping, responses)
        honest = _evaluate(
            self.freeze,
            release,
            _observations(release, {"base": 3, "c1": 1, "c3": 0}),
            aggregate,
        )
        validate_validation_result(honest, self.freeze)
        for path in (
            ("candidates", "c3", "metrics", "roc_auc"),
            ("candidates", "c3", "threshold_search", "threshold"),
            ("candidates", "c3", "metrics", "overall", "confusion", "false_pass"),
        ):
            tampered = copy.deepcopy(honest)
            target = tampered
            for key in path[:-1]:
                target = target[key]
            current = target[path[-1]]
            target[path[-1]] = current + 7 if isinstance(current, int) else 0.123456
            with self.assertRaises(SelectionError, msg=str(path)):
                validate_validation_result(tampered, self.freeze)

    def test_lock_refuses_a_result_bound_to_another_freeze(self) -> None:
        other = copy.deepcopy(self.freeze)
        other["source"]["git_commit"] = "1" * 40
        release = _validation_release()
        package, mapping, responses = _judge(release, package_id="plan073-other")
        aggregate = aggregate_batches(package, mapping, responses)
        observations = _observations(release, {"base": 3, "c1": 1, "c3": 0})
        result = _evaluate(self.freeze, release, observations, aggregate)
        with self.assertRaises(SelectionError):
            _lock(result, other, release, observations, aggregate)


class UnseenConfirmationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.freeze = _freeze()
        self.lock = _locked(self.freeze)
        self.release = _release(
            "unseen_test",
            ["PASS"] * 10 + ["REWRITE"] * 10,
            pairs=[(f"u{index}", f"s{index:02d}", f"s{index + 10:02d}") for index in range(10)],
            lock_sha=lock_sha256(self.lock),
        )
        package, mapping, responses = _judge(self.release, package_id="plan073-blind")
        self.aggregate = aggregate_batches(package, mapping, responses)

    def _observation(self, flips: int, **runtime: object) -> dict[str, object]:
        return {
            "candidate": self.lock["selected"]["candidate"],
            "deployment_artifact_sha256": self.lock["selected"][
                "deployment_artifact_sha256"
            ],
            "scores": _separable(self.release, flips=flips),
            "runtime": _runtime_facts(len(self.release["items"]), **runtime),
        }

    def test_locked_combination_that_holds_is_a_go(self) -> None:
        result = evaluate_unseen_confirmation(
            self.lock, self.freeze, self.release, self._observation(0), self.aggregate
        )
        self.assertEqual(result["terminal"], "GO")
        self.assertEqual(result["failed_gates"], [])
        self.assertEqual(
            result["locked_combination"]["threshold"]["projected_score"],
            self.lock["selected"]["threshold"]["projected_score"],
        )

    def test_locked_combination_that_fails_a_floor_is_a_no_go(self) -> None:
        result = evaluate_unseen_confirmation(
            self.lock, self.freeze, self.release, self._observation(8), self.aggregate
        )
        self.assertEqual(result["terminal"], "NO_GO")
        self.assertTrue(result["failed_gates"])

    def test_confirmation_refuses_a_different_candidate(self) -> None:
        observation = self._observation(0)
        observation["candidate"] = "c1"
        observation["deployment_artifact_sha256"] = ARTIFACTS["c1"]
        with self.assertRaises(SelectionError):
            evaluate_unseen_confirmation(
                self.lock, self.freeze, self.release, observation, self.aggregate
            )

    def test_confirmation_refuses_a_release_opened_by_another_lock(self) -> None:
        foreign = _release(
            "unseen_test", ["PASS", "REWRITE"], lock_sha="7" * 64
        )
        with self.assertRaises(SelectionError):
            evaluate_unseen_confirmation(
                self.lock,
                self.freeze,
                foreign,
                self._observation(0),
                self.aggregate,
            )

    def test_confirmation_never_refits_the_threshold(self) -> None:
        result = evaluate_unseen_confirmation(
            self.lock, self.freeze, self.release, self._observation(2), self.aggregate
        )
        self.assertEqual(
            result["metrics"]["threshold"],
            self.lock["selected"]["threshold"]["projected_score"],
        )

    def test_report_grade_validator_binds_and_recomputes(self) -> None:
        result = evaluate_unseen_confirmation(
            self.lock, self.freeze, self.release, self._observation(0), self.aggregate
        )
        self.assertEqual(
            validate_unseen_confirmation(result, self.freeze, self.lock)["terminal"],
            "GO",
        )
        for mutate in (
            lambda doc: doc.update(terminal="GO", failed_gates=[]),
            lambda doc: doc.update(selection_lock_sha256="d" * 64),
            lambda doc: doc["locked_combination"].update(candidate="c1"),
            lambda doc: doc["metrics"]["overall"]["confusion"].update(false_pass=9),
            lambda doc: doc["metrics"].update(roc_auc=0.5),
        ):
            broken = copy.deepcopy(result)
            mutate(broken)
            if broken == result:
                continue
            with self.assertRaises(SelectionError):
                validate_unseen_confirmation(broken, self.freeze, self.lock)

    def test_report_grade_validator_rejects_a_failing_run_relabelled_go(self) -> None:
        failing = evaluate_unseen_confirmation(
            self.lock, self.freeze, self.release, self._observation(8), self.aggregate
        )
        self.assertEqual(failing["terminal"], "NO_GO")
        relabelled = copy.deepcopy(failing)
        relabelled["terminal"] = "GO"
        relabelled["failed_gates"] = []
        relabelled["reasons"] = ["forged"]
        with self.assertRaises(SelectionError):
            validate_unseen_confirmation(relabelled, self.freeze, self.lock)

    def test_missing_judge_evidence_after_release_is_inconclusive(self) -> None:
        result = evaluate_unseen_confirmation(
            self.lock, self.freeze, self.release, self._observation(0), None
        )
        self.assertEqual(result["terminal"], "INCONCLUSIVE")


class ArchiveTest(unittest.TestCase):
    def test_run_artifacts_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs_root = Path(directory) / "runs"
            run_id = "plan073-formal-20260825T120000Z-archive"
            archive = SelectionArchive(runs_root, run_id, "formal").create()
            archive.write_json("validation-result.json", {"terminal": "SELECTED"})
            with self.assertRaises(SelectionError):
                archive.write_json("validation-result.json", {"terminal": "NO_GO"})
            with self.assertRaises(SelectionError):
                SelectionArchive(runs_root, run_id, "formal").create()
            SelectionArchive(runs_root, run_id, "formal").create(exist_ok=True)

    def test_run_identity_must_match_its_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(SelectionError):
                SelectionArchive(
                    Path(directory), "plan073-formal-20260825T120000Z-x", "commissioning"
                )


class FreezeContractTest(unittest.TestCase):
    def test_protocol_method_identity_cannot_drift(self) -> None:
        freeze = _freeze()
        freeze["protocol"]["method"]["ranking"] = "something-else-v1"
        with self.assertRaises(SelectionError):
            validate_freeze(freeze)

    def test_freeze_requires_all_three_candidates_in_order(self) -> None:
        freeze = _freeze()
        freeze["candidates"] = ["base", "c3", "c1"]
        with self.assertRaises(SelectionError):
            validate_freeze(freeze)

    def test_freeze_cannot_declare_unseen_open(self) -> None:
        freeze = _freeze()
        freeze["dataset"]["unseen_test_sealed_at_freeze"] = False
        with self.assertRaises(SelectionError):
            validate_freeze(freeze)

    def test_freeze_digest_covers_the_protocol_numbers(self) -> None:
        freeze = _freeze()
        before = freeze_sha256(freeze)
        freeze["protocol"]["quality_floors"]["max_false_pass_rate"] = 0.9
        self.assertNotEqual(before, freeze_sha256(validate_freeze(freeze)))

    def test_release_digest_is_canonical(self) -> None:
        release = _release("validation", ["PASS", "REWRITE"])
        self.assertEqual(
            release_sha256(release),
            sha256_bytes(canonical_json_bytes(dict(release))),
        )


if __name__ == "__main__":
    unittest.main()
