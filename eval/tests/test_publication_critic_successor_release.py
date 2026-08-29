import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.identity import canonical_json_bytes  # noqa: E402
from rondo_eval.publication_critic.successor_build import (  # noqa: E402
    ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256,
    ACCEPTED_IMPLEMENTATION_COMMIT,
    ACCEPTED_TASK,
    ACCEPTED_TASK_SHA256,
    CONFIG_PATH,
    DESIGN_PATH,
    MODULE_CONTRACT_PATH,
    SuccessorBuildError,
    finalize_successor_release,
    load_build_contracts,
    validate_module_file,
    validate_review_file,
)
from rondo_eval.publication_critic.successor_data import (  # noqa: E402
    SuccessorRelease,
    validate_split,
)
from rondo_eval.publication_critic.successor_task import HARD_DIMENSIONS  # noqa: E402


COMMISSIONING_ROOT = Path(
    "/home/sjc/desktop/RONDO/eval-data/publication-critic/plan098/commissioning"
)


class PublicationCriticSuccessorReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        COMMISSIONING_ROOT.mkdir(parents=True, exist_ok=True)

    def test_commissioning_chain_freezes_physical_release_and_train_only_smoke(
        self,
    ) -> None:
        contracts = load_build_contracts(REPO_ROOT)
        with tempfile.TemporaryDirectory(dir=COMMISSIONING_ROOT) as directory:
            workspace = Path(directory) / "workspace"
            output = Path(directory) / "publication-critic-v9"
            self._write_complete_workspace(workspace, contracts.design)

            coverage = finalize_successor_release(
                workspace,
                output,
                repo_root=REPO_ROOT,
                enforce_config_paths=False,
            )

            self.assertEqual(coverage["total_candidates"], 216)
            self.assertEqual(coverage["total_pairs"], 96)
            self.assertEqual(
                {
                    split: details["candidates"]
                    for split, details in coverage["splits"].items()
                },
                {"train": 162, "validation": 27, "test": 27},
            )
            self.assertEqual(
                (output / "design-lock.json").read_bytes(),
                (REPO_ROOT / DESIGN_PATH).read_bytes(),
            )
            self.assertEqual(
                (output / "generation-config.json").read_bytes(),
                (REPO_ROOT / CONFIG_PATH).read_bytes(),
            )
            identity = self._read_json(output / "release-identity.json")
            design = self._read_json(output / "design-lock.json")
            config = self._read_json(output / "generation-config.json")
            self.assertEqual(
                identity["accepted_implementation"],
                design["accepted_implementation"],
            )
            self.assertEqual(
                config["accepted_implementation"],
                {
                    "commit": identity["accepted_implementation"]["commit"],
                    "bundle_sha256": identity["accepted_implementation"][
                        "bundle_sha256"
                    ],
                },
            )
            self.assertEqual(
                identity["design_lock_sha256"],
                hashlib.sha256((output / "design-lock.json").read_bytes()).hexdigest(),
            )
            smoke = self._read_json(output / "train-only-smoke-bundle.json")
            self.assertEqual(smoke["split"], "train")
            self.assertEqual(len(smoke["candidates"]), 9)
            self.assertEqual(len(smoke["pairs"]), 4)
            validate_split(
                "train",
                smoke["candidates"],
                smoke["pairs"],
                repo_root=REPO_ROOT,
            )

            release = SuccessorRelease.open(
                output,
                expected_accepted_commit=ACCEPTED_IMPLEMENTATION_COMMIT,
                repo_root=REPO_ROOT,
            )
            self.assertEqual(len(release.load_train().candidates), 162)
            self.assertEqual(len(release.load_validation().candidates), 27)
            self.assertFalse(hasattr(release, "load_test"))

    def test_tracked_release_identity_and_public_consumer(self) -> None:
        root = REPO_ROOT / "training/publication-critic-v9"
        coverage = self._read_json(root / "coverage.json")
        identity = self._read_json(root / "release-identity.json")
        manifest = self._read_json(root / "manifest.json")
        design = self._read_json(root / "design-lock.json")
        config = self._read_json(root / "generation-config.json")

        self.assertEqual(coverage["accepted_task"], ACCEPTED_TASK)
        self.assertEqual(coverage["total_candidates"], 216)
        self.assertEqual(coverage["total_pairs"], 96)
        self.assertEqual(coverage["duplicate_check"]["exact_duplicates"], 0)
        self.assertEqual(
            coverage["duplicate_check"]["cross_group_near_duplicates"],
            0,
        )
        self.assertEqual(identity["accepted_task"], ACCEPTED_TASK)
        self.assertEqual(
            identity["accepted_implementation"],
            design["accepted_implementation"],
        )
        self.assertEqual(
            identity["accepted_implementation"]["bundle_sha256"],
            ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256,
        )
        self.assertEqual(
            config["accepted_implementation"],
            {
                "commit": ACCEPTED_IMPLEMENTATION_COMMIT,
                "bundle_sha256": ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256,
            },
        )
        self.assertEqual(
            identity["manifest_sha256"],
            hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            identity["design_lock_sha256"],
            hashlib.sha256((root / "design-lock.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            identity["generation_config_sha256"],
            hashlib.sha256((root / "generation-config.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["task_contract"],
            {
                "name": ACCEPTED_TASK["name"],
                "version": ACCEPTED_TASK["version"],
                "content_sha256": ACCEPTED_TASK["content_sha256"],
                "accepted_commit": ACCEPTED_IMPLEMENTATION_COMMIT,
            },
        )
        for module_id, binding in identity["module_records"].items():
            path = root / binding["path"]
            self.assertEqual(path.stem, module_id)
            self.assertEqual(
                binding["sha256"],
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )

        smoke = self._read_json(root / "train-only-smoke-bundle.json")
        self.assertEqual(smoke["split"], "train")
        validate_split(
            "train",
            smoke["candidates"],
            smoke["pairs"],
            repo_root=REPO_ROOT,
        )
        release = SuccessorRelease.open(
            root,
            expected_accepted_commit=ACCEPTED_IMPLEMENTATION_COMMIT,
            repo_root=REPO_ROOT,
        )
        train = release.load_train()
        validation = release.load_validation()
        self.assertEqual(len(train.candidates), 162)
        self.assertEqual(len(validation.candidates), 27)
        self.assertFalse(hasattr(release, "load_test"))
        self.assertTrue((root / manifest["splits"]["test"]["candidates"]["path"]).is_file())
        self.assertTrue((root / manifest["splits"]["test"]["pairs"]["path"]).is_file())
        train_ids = {row["candidate_id"] for row in train.candidates}
        self.assertTrue(
            {row["candidate_id"] for row in smoke["candidates"]} <= train_ids
        )

    def test_module_schedule_and_review_identity_fail_closed(self) -> None:
        contracts = load_build_contracts(REPO_ROOT)
        design = contracts.design
        source = self._module_source("hard-boundaries", design)
        with tempfile.TemporaryDirectory(dir=COMMISSIONING_ROOT) as directory:
            root = Path(directory)
            source_path = root / "module.json"
            self._write_json(source_path, source)
            module = validate_module_file(
                source_path,
                contracts=contracts,
                repo_root=REPO_ROOT,
            )

            wrong_schedule = copy.deepcopy(source)
            original_target = wrong_schedule["groups"][0]["pairs"][0][
                "target_dimension"
            ]
            wrong_schedule["groups"][0]["pairs"][0]["target_dimension"] = (
                "internal_consistency"
            )
            wrong_labels = wrong_schedule["groups"][0]["candidates"][1]["labels"]
            wrong_labels[original_target] = "PASS"
            wrong_labels["internal_consistency"] = "FAIL"
            self._write_json(source_path, wrong_schedule)
            with self.assertRaisesRegex(SuccessorBuildError, "boundary schedule"):
                validate_module_file(
                    source_path,
                    contracts=contracts,
                    repo_root=REPO_ROOT,
                )

            self._write_json(source_path, source)
            review = self._review(module)
            review["module_sha256"] = "0" * 64
            review_path = root / "review.json"
            self._write_json(review_path, review)
            with self.assertRaisesRegex(SuccessorBuildError, "module hash"):
                validate_review_file(
                    review_path,
                    module,
                    contracts=contracts,
                    repo_root=REPO_ROOT,
                )

    def test_accepted_task_drift_relocks_module_validation(self) -> None:
        contracts = load_build_contracts(REPO_ROOT)
        source = self._module_source("continuity-context", contracts.design)
        source["accepted_task"]["content_sha256"] = "f" * 64
        with tempfile.TemporaryDirectory(dir=COMMISSIONING_ROOT) as directory:
            path = Path(directory) / "module.json"
            self._write_json(path, source)
            with self.assertRaisesRegex(SuccessorBuildError, "accepted task"):
                validate_module_file(
                    path,
                    contracts=contracts,
                    repo_root=REPO_ROOT,
                )

    def test_core_component_drift_relocks_finalizer_before_output(self) -> None:
        with tempfile.TemporaryDirectory(dir=COMMISSIONING_ROOT) as directory:
            root = Path(directory) / "repo"
            accepted_implementation = self._read_json(
                REPO_ROOT / DESIGN_PATH
            )["accepted_implementation"]
            required = [
                DESIGN_PATH,
                CONFIG_PATH,
                MODULE_CONTRACT_PATH,
                *(
                    Path(component["path"])
                    for component in accepted_implementation["components"]
                ),
            ]
            for relative in required:
                source = REPO_ROOT / relative
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)

            authority = root / ACCEPTED_TASK["authority_path"]
            protected = [
                component
                for component in accepted_implementation["components"]
                if component["path"] != ACCEPTED_TASK["authority_path"]
            ]
            for component in protected:
                with self.subTest(component=component["path"]):
                    path = root / component["path"]
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n")
                    self.assertEqual(
                        hashlib.sha256(authority.read_bytes()).hexdigest(),
                        ACCEPTED_TASK_SHA256,
                    )
                    output = root / "formal-output"
                    with self.assertRaisesRegex(
                        SuccessorBuildError,
                        "accepted implementation component drifted",
                    ):
                        finalize_successor_release(
                            root / "unused-workspace",
                            output,
                            repo_root=root,
                            enforce_config_paths=False,
                        )
                    self.assertFalse(output.exists())
                    path.write_bytes(original)

    def _write_complete_workspace(self, root: Path, design: dict) -> None:
        for module_spec in design["module_contract"]["modules"]:
            module_id = module_spec["module_id"]
            source_path = root / f"modules/{module_id}.json"
            source = self._module_source(module_id, design)
            self._write_json(source_path, source)
            module = validate_module_file(source_path, repo_root=REPO_ROOT)
            self._write_json(
                root / f"reviews/{module_id}.json",
                self._review(module),
            )

    def _module_source(self, module_id: str, design: dict) -> dict:
        spec = next(
            item
            for item in design["module_contract"]["modules"]
            if item["module_id"] == module_id
        )
        groups = []
        group_index = 0
        for split in ("train", "validation", "test"):
            for target in spec["boundary_targets_by_split"][split]:
                groups.append(
                    self._group(
                        module_id,
                        group_index,
                        split,
                        target,
                        soft_module=module_id == "soft-combinations",
                    )
                )
                group_index += 1
        return {
            "schema": "rondo-publication-critic-successor-module-source@v1",
            "module_id": module_id,
            "owner_role": spec["owner_role"],
            "accepted_task": copy.deepcopy(ACCEPTED_TASK),
            "groups": groups,
        }

    def _group(
        self,
        module_id: str,
        index: int,
        split: str,
        target: str,
        *,
        soft_module: bool,
    ) -> dict:
        token = hashlib.sha256(f"{module_id}-{index}".encode()).hexdigest()[:20]
        applicable = index < 6 or target in {
            "conditional_continuity",
            "internal_consistency",
        }
        base_labels = self._pass_labels(continuity="PASS" if applicable else "N/A")
        boundary_labels = copy.deepcopy(base_labels)
        boundary_labels[target] = "FAIL"
        group_id = f"pcv9-{module_id}-{index + 1:02d}"

        base = self._candidate(
            "qplus",
            token,
            base_labels,
            hard_pass=True,
            soft_good=index % 2 == 0,
            complete=not applicable,
            anchor=index < 6,
        )
        boundary = self._candidate(
            "qminus",
            token,
            boundary_labels,
            hard_pass=False,
            soft_good=index % 2 != 0,
            complete=not applicable,
            target=target,
        )
        pairs = [
            {
                "key": "boundary",
                "kind": "boundary",
                "left_key": "qplus",
                "right_key": "qminus",
                "target_dimension": target,
                "soft_change": None,
            }
        ]
        if soft_module:
            third = self._candidate(
                "soft",
                token,
                copy.deepcopy(base_labels),
                hard_pass=True,
                soft_good=index % 2 != 0,
                complete=not applicable,
                soft_variant=True,
            )
            pairs.append(
                {
                    "key": "soft-only",
                    "kind": "soft_only_invariance",
                    "left_key": "qplus",
                    "right_key": "soft",
                    "target_dimension": None,
                    "soft_change": "Changes cadence and emphasis without changing hard facts.",
                }
            )
        else:
            multi_labels = copy.deepcopy(base_labels)
            multi_labels[target] = "FAIL"
            extra = (
                "internal_consistency"
                if target != "internal_consistency"
                else "useful_state_transfer"
            )
            multi_labels[extra] = "FAIL"
            third = self._candidate(
                "multi",
                token,
                multi_labels,
                hard_pass=False,
                soft_good=index % 2 == 0,
                complete=False,
                target=target,
                multi=True,
                visible_conflict=index < 6,
            )

        return {
            "group_id": group_id,
            "split": split,
            "source": {"kind": "new_synthetic", "reference": None},
            "context": self._context(module_id, index, token),
            "candidates": [base, boundary, third],
            "pairs": pairs,
        }

    @staticmethod
    def _context(module_id: str, index: int, token: str) -> dict:
        bucket = index % 3
        if bucket == 0:
            target_kind = "new_event"
            continuity = {"state": "not_applicable"}
        elif bucket == 1:
            target_kind = "existing_event"
            continuity = {
                "state": "available",
                "source_team_revision": 100 + index,
                "freshness": "current",
                "coverage": {"state": "complete"},
                "prior_publications": [
                    {
                        "summary": f"Prior checkpoint {token} established the bounded input.",
                        "handoff": "Continue from the isolated integration seam.",
                        "evidence": {
                            "fact_references": {"state": "none"},
                            "observation_availability": "unknown",
                        },
                    }
                ],
            }
        else:
            target_kind = "existing_event"
            continuity = {
                "state": "unavailable",
                "last_known_revision": 100 + index,
                "freshness": "known_stale",
            }
        return {
            "actor_role": "root",
            "target_kind": target_kind,
            "local_scope": {
                "title": f"Commissioning {module_id} scenario {token}"
            },
            "continuity": continuity,
            "evidence_v1": {
                "semantic_entailment": "not_evaluated",
                "candidate_window": "not_frozen_before_commit",
            },
        }

    @staticmethod
    def _candidate(
        key: str,
        token: str,
        labels: dict,
        *,
        hard_pass: bool,
        soft_good: bool,
        complete: bool,
        target: str | None = None,
        multi: bool = False,
        soft_variant: bool = False,
        anchor: bool = False,
        visible_conflict: bool = False,
    ) -> dict:
        if complete:
            summary = (
                f"Checkpoint {token} is complete; the bounded artifact and focused "
                "verification are recorded."
            )
            handoff = None
            quote = "is complete"
        else:
            summary = (
                f"Checkpoint {token} remains in progress; the bounded artifact is "
                "recorded and the isolated integration check remains open."
            )
            handoff = "Run the isolated integration check before closing this checkpoint."
            quote = "remains in progress"
        if soft_variant:
            summary = summary.replace("bounded artifact", "focused artifact")
        if target == "useful_state_transfer":
            summary = f"Checkpoint {token} has seen various activity and remains in progress."
            handoff = "Continue the work."
            quote = "remains in progress"
        elif target == "honest_uncertainty":
            summary += " External behavior is definitively verified despite unavailable evidence."
        elif target == "conditional_continuity":
            summary = f"Checkpoint {token} remains open, but no reusable state is available."
            handoff = None
            quote = "remains open"
        elif target == "scope_and_signal":
            summary += " " + "Verbose process trace obscures the result. " * 10
        elif target == "internal_consistency":
            summary = f"Checkpoint {token} is complete, while one integration check remains open."
            handoff = "Run that remaining integration check before closing."
            quote = "remains open"
        if visible_conflict:
            summary = f"Checkpoint {token} is complete, but the integration check remains open."
            handoff = "Continue the unfinished integration check."
            quote = "remains open"
        if multi:
            summary += " A second reusable-state gap also remains unresolved."

        tags = [
            (
                "hard_pass_soft_good"
                if hard_pass and soft_good
                else "hard_pass_soft_bad"
                if hard_pass
                else "hard_fail_soft_good"
                if soft_good
                else "hard_fail_soft_bad"
            )
        ]
        if not hard_pass:
            tags.append("multi_hard_failure" if multi else "single_hard_failure")
        if anchor:
            tags.append("real_shaped_anchor")
        if visible_conflict:
            tags.append("visible_conflict")
        return {
            "key": key,
            "summary": summary,
            "handoff": handoff,
            "labels": labels,
            "continuity_basis": {"field": "candidate.summary", "quote": quote},
            "tags": tags,
        }

    @staticmethod
    def _pass_labels(*, continuity: str) -> dict[str, str]:
        return {
            dimension: continuity if dimension == "conditional_continuity" else "PASS"
            for dimension in HARD_DIMENSIONS
        }

    @staticmethod
    def _review(module) -> dict:
        return {
            "schema": "rondo-publication-critic-successor-module-review@v1",
            "module_id": module.module_id,
            "reviewer_role": f"plan098-blind-reviewer-{module.module_id}",
            "accepted_task": copy.deepcopy(ACCEPTED_TASK),
            "module_sha256": module.source_sha256,
            "verdict": "accept",
            "findings": [],
            "checklist": {
                "contract_alignment": True,
                "complete_absolute_labels": True,
                "visible_basis_sufficient": True,
                "boundary_closure": True,
                "soft_only_invariance": True,
                "split_grouping": True,
                "language_quality": True,
                "no_hidden_metadata": True,
            },
        }

    @staticmethod
    def _write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(value))

    @staticmethod
    def _read_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
