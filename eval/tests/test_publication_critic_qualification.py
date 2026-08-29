import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.qualification import (  # noqa: E402
    BINARY_DIMENSIONS,
    DECISION_CONFIG_SCHEMA,
    DECISION_IMPLEMENTATION_COMPONENT_PATHS,
    DECISION_IMPLEMENTATION_LOCK,
    FORMAL_DECISION_PROJECTION,
    QualificationError,
    decision_config_sha256,
    decision_implementation_identity,
    decode_with_decision_config,
    evaluate_qualification_predictions,
    freeze_decision_config,
    validate_decision_config,
)
from rondo_eval.publication_critic.successor_task import (  # noqa: E402
    DIMENSION_CLASSES,
    HARD_DIMENSIONS,
    STRUCTURED_OUTPUT_SCHEMA,
    TASK_AUTHORITY,
    derive_verdict,
)


class PublicationCriticQualificationTests(unittest.TestCase):
    def test_contract_projections_bind_validation_only_runtime(self) -> None:
        decision = self._load_json(
            "eval/templates/publication-critic/decision-config-contract-v1.json"
        )
        metrics = self._load_json(
            "eval/templates/publication-critic/qualification-metrics-contract-v1.json"
        )
        formal = self._load_json(FORMAL_DECISION_PROJECTION.as_posix())
        self.assertEqual(decision["version"], "v1")
        self.assertEqual(decision["selection"]["split"], "validation")
        self.assertEqual(decision["selection"]["test_access"], "forbidden")
        self.assertEqual(
            decision["reference_selector"],
            "eval/rondo_eval/publication_critic/directional_data.py#"
            "DevelopmentRelease.select_and_freeze_validation_decision_config",
        )
        self.assertEqual(
            decision["formal_output_projection"],
            FORMAL_DECISION_PROJECTION.as_posix(),
        )
        self.assertEqual(
            formal["raw_output"]["historical_decoder_role"],
            "zero_margin_diagnostic_only",
        )
        self.assertEqual(formal["raw_output"]["formal_decision_use"], "forbidden")
        self.assertEqual(
            formal["formal_decision"]["decoder"],
            "eval/rondo_eval/publication_critic/qualification.py#"
            "decode_with_decision_config",
        )
        self.assertTrue(formal["formal_decision"]["requires_frozen_decision_config"])
        self.assertEqual(
            decision["selection"]["pair_eligibility"],
            "all_validation_pairs_closed",
        )
        self.assertNotIn("global threshold", decision["required_identity"])
        self.assertEqual(
            metrics["confusion"]["binary_heads"],
            ["PASS", "FAIL"],
        )
        self.assertEqual(
            metrics["confusion"]["conditional_continuity"],
            ["PASS", "FAIL", "N/A"],
        )

    def test_decision_config_is_model_task_data_bound_and_validation_only(self) -> None:
        config = self._config()
        validate_decision_config(config, repo_root=REPO_ROOT)
        self.assertEqual(config["schema"], DECISION_CONFIG_SCHEMA)
        self.assertEqual(config["selection"]["split"], "validation")
        self.assertEqual(config["selection"]["test_access"], "forbidden")
        self.assertEqual(
            config["selection"]["method"],
            "bounded_validation_pair_closed_grid_v1",
        )
        self.assertEqual(config["selection"]["validation_pair_rows"], 2)
        self.assertEqual(
            config["selection"]["pair_evaluation"],
            self._pair_evaluation(),
        )
        self.assertEqual(
            config["decision_implementation"],
            decision_implementation_identity(REPO_ROOT),
        )
        self.assertRegex(
            decision_config_sha256(config, repo_root=REPO_ROOT),
            r"^[0-9a-f]{64}$",
        )

        with self.assertRaisesRegex(QualificationError, "selection.split"):
            self._config(selection_split="test")
        broken = copy.deepcopy(config)
        broken["heads"]["conditional_continuity"]["na_over_applicable_margin"] = 0
        with self.assertRaisesRegex(QualificationError, "conservative range"):
            validate_decision_config(broken, repo_root=REPO_ROOT)
        broken = copy.deepcopy(config)
        broken["development_data"]["manifest_sha256"] = "0" * 63
        with self.assertRaisesRegex(QualificationError, "SHA-256"):
            validate_decision_config(broken, repo_root=REPO_ROOT)
        broken = copy.deepcopy(config)
        broken["development_data"]["validation_pairs_sha256"] = "0" * 63
        with self.assertRaisesRegex(QualificationError, "SHA-256"):
            validate_decision_config(broken, repo_root=REPO_ROOT)
        broken = copy.deepcopy(config)
        broken["selection"]["pair_evaluation"]["pairs"][0]["closed"] = False
        broken["selection"]["pair_evaluation"]["pairs"][0]["reason"] = "open"
        with self.assertRaisesRegex(QualificationError, "closed"):
            validate_decision_config(broken, repo_root=REPO_ROOT)
        broken = copy.deepcopy(config)
        broken["decision_implementation"]["bundle_sha256"] = "0" * 64
        with self.assertRaisesRegex(QualificationError, "decision_implementation"):
            validate_decision_config(broken, repo_root=REPO_ROOT)

    def test_decision_config_rejects_decoder_component_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                TASK_AUTHORITY.as_posix(),
                DECISION_IMPLEMENTATION_LOCK.as_posix(),
                *DECISION_IMPLEMENTATION_COMPONENT_PATHS,
            }
            for relative in paths:
                source = REPO_ROOT / relative
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            config = self._config(repo_root=root)
            with (root / "eval/rondo_eval/publication_critic/qualification.py").open(
                "ab"
            ) as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(
                QualificationError,
                "decision implementation component",
            ):
                validate_decision_config(config, repo_root=root)

    def test_decoder_is_per_head_fail_closed_and_conservative_for_na(self) -> None:
        output = self._structured_output(batch_size=6)
        for dimension in BINARY_DIMENSIONS:
            output["heads"][dimension]["logits"] = [
                [1.0, 0.0],
                [1.0, 0.0],
                [1.0, 0.0],
                [1.0, 0.0],
                [1.0, 0.0],
                [0.2, 0.0],
            ]
        output["heads"]["conditional_continuity"]["logits"] = [
            [1.0, 0.0, 1.1],  # weak N/A top despite strong PASS-over-FAIL
            [1.0, 0.0, 1.5],  # exact N/A margin boundary
            [0.0, -1.0, 1.0],  # decisive N/A
            [1.0, 0.0, 0.9],  # clearly applicable PASS
            [0.9, 0.0, 1.0],  # weak N/A top without the PASS shortcut
            [1.0, 0.0, 0.0],  # another head fails closed
        ]
        decoded = decode_with_decision_config(
            output,
            self._config(),
            repo_root=REPO_ROOT,
        )
        self.assertEqual(decoded[0]["conditional_continuity"], "FAIL")
        self.assertEqual(decoded[1]["conditional_continuity"], "FAIL")
        self.assertEqual(decoded[2]["conditional_continuity"], "N/A")
        self.assertEqual(decoded[3]["conditional_continuity"], "PASS")
        self.assertEqual(decoded[4]["conditional_continuity"], "FAIL")
        self.assertEqual(decoded[5]["useful_state_transfer"], "FAIL")
        self.assertEqual(derive_verdict(decoded[0]), "REWRITE")
        self.assertEqual(derive_verdict(decoded[1]), "REWRITE")
        self.assertEqual(derive_verdict(decoded[2]), "PASS")
        self.assertEqual(derive_verdict(decoded[3]), "PASS")
        self.assertEqual(derive_verdict(decoded[4]), "REWRITE")
        self.assertEqual(derive_verdict(decoded[5]), "REWRITE")

    def test_metrics_fix_every_confusion_cell_and_head_failure_recall(self) -> None:
        gold = []
        predicted = []
        continuity_cells = [
            (expected, actual)
            for expected in ("PASS", "FAIL", "N/A")
            for actual in ("PASS", "FAIL", "N/A")
        ]
        binary_cells = [
            ("PASS", "PASS"),
            ("PASS", "FAIL"),
            ("FAIL", "PASS"),
            ("FAIL", "FAIL"),
        ]
        for index, (continuity_gold, continuity_predicted) in enumerate(
            continuity_cells
        ):
            expected = self._labels(continuity=continuity_gold)
            actual = self._labels(continuity=continuity_predicted)
            for dimension in BINARY_DIMENSIONS:
                expected[dimension], actual[dimension] = binary_cells[index % 4]
            gold.append(expected)
            predicted.append(actual)
        metrics = evaluate_qualification_predictions(gold, predicted)
        self.assertEqual(
            metrics["schema"],
            "rondo-publication-critic-qualification-metrics@v1",
        )
        for dimension in BINARY_DIMENSIONS:
            details = metrics["per_dimension"][dimension]
            self.assertEqual(details["classes"], ["PASS", "FAIL"])
            self.assertTrue(
                all(
                    details["confusion"][expected][actual] > 0
                    for expected in ("PASS", "FAIL")
                    for actual in ("PASS", "FAIL")
                )
            )
            self.assertEqual(details["fail_to_na"], 0)
            self.assertEqual(details["pass_to_na"], 0)
        continuity = metrics["per_dimension"]["conditional_continuity"]
        self.assertTrue(
            all(
                continuity["confusion"][expected][actual] == 1
                for expected in ("PASS", "FAIL", "N/A")
                for actual in ("PASS", "FAIL", "N/A")
            )
        )
        self.assertEqual(continuity["fail_to_pass"], 1)
        self.assertEqual(continuity["fail_to_na"], 1)
        self.assertEqual(continuity["failure_recall"]["denominator"], 3)

        no_fail = evaluate_qualification_predictions(
            [self._labels()],
            [self._labels()],
        )
        self.assertEqual(
            no_fail["per_dimension"]["honest_uncertainty"]["failure_recall"],
            {
                "status": "unavailable",
                "numerator": 0,
                "denominator": 0,
                "value": None,
            },
        )

    def test_multi_defect_gate_can_be_correct_while_one_head_misses_fail(self) -> None:
        expected = self._labels()
        expected["honest_uncertainty"] = "FAIL"
        expected["scope_and_signal"] = "FAIL"
        actual = copy.deepcopy(expected)
        actual["honest_uncertainty"] = "PASS"
        metrics = evaluate_qualification_predictions([expected], [actual])
        self.assertEqual(metrics["gate"]["correct"], 1)
        self.assertEqual(metrics["gate"]["false_pass"], 0)
        self.assertEqual(
            metrics["per_dimension"]["honest_uncertainty"]["fail_to_pass"],
            1,
        )
        self.assertEqual(
            metrics["per_dimension"]["honest_uncertainty"]["failure_recall"],
            {
                "status": "available",
                "numerator": 0,
                "denominator": 1,
                "value": 0.0,
            },
        )

    def _config(
        self,
        *,
        selection_split: str = "validation",
        repo_root: Path = REPO_ROOT,
    ) -> dict:
        return freeze_decision_config(
            model_artifact_sha256="1" * 64,
            development_revision="publication-critic-v10",
            development_manifest_sha256="2" * 64,
            validation_candidates_sha256="3" * 64,
            validation_pairs_sha256="4" * 64,
            validation_rows=3,
            validation_pair_rows=2,
            pair_evaluation=self._pair_evaluation(),
            selection_method="bounded_validation_pair_closed_grid_v1",
            selection_split=selection_split,
            head_margins=self._margins(),
            repo_root=repo_root,
        )

    @staticmethod
    def _margins() -> dict[str, dict[str, float]]:
        return {
            **{
                dimension: {"pass_over_fail_margin": 0.2}
                for dimension in BINARY_DIMENSIONS
            },
            "conditional_continuity": {
                "pass_over_fail_margin": 0.2,
                "na_over_applicable_margin": 0.5,
            },
        }

    @staticmethod
    def _pair_evaluation() -> dict:
        return {
            "summary": {
                "boundary": {"total": 1, "closed": 1},
                "soft_only_invariance": {"total": 1, "closed": 1},
            },
            "pairs": [
                {
                    "pair_id": "boundary-validation-a",
                    "kind": "boundary",
                    "closed": True,
                    "reason": None,
                },
                {
                    "pair_id": "soft-validation-a",
                    "kind": "soft_only_invariance",
                    "closed": True,
                    "reason": None,
                },
            ],
        }

    @staticmethod
    def _labels(*, continuity: str = "PASS") -> dict[str, str]:
        return {
            dimension: continuity if dimension == "conditional_continuity" else "PASS"
            for dimension in HARD_DIMENSIONS
        }

    @staticmethod
    def _structured_output(*, batch_size: int) -> dict:
        return {
            "schema": STRUCTURED_OUTPUT_SCHEMA,
            "backbone_forward_count": 1,
            "batch_size": batch_size,
            "heads": {
                dimension: {
                    "classes": list(DIMENSION_CLASSES[dimension]),
                    "logits": [
                        (
                            [1.0, 0.0, 0.0]
                            if dimension == "conditional_continuity"
                            else [1.0, 0.0]
                        )
                        for _ in range(batch_size)
                    ],
                }
                for dimension in HARD_DIMENSIONS
            },
        }

    @staticmethod
    def _load_json(relative: str) -> dict:
        return json.loads((REPO_ROOT / relative).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
