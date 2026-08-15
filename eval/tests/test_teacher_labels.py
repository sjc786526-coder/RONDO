from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.evidence import build_static_payload  # noqa: E402
from rondo_eval.local_approval import teacher_labels  # noqa: E402
from rondo_eval.terminal_bench import live as terminal_bench_live  # noqa: E402


def approval_text(action: dict, *, prefix: str = "") -> str:
    return (
        prefix
        + ">>> APPROVAL REQUEST START\n"
        + "Assess the exact planned action below.\n"
        + "Planned action JSON:\n"
        + json.dumps(action, indent=2, sort_keys=True)
        + "\n>>> APPROVAL REQUEST END\n"
    )


def exec_action(command: str) -> dict:
    return {
        "tool": "exec_command",
        "command": ["bash", "-lc", command],
        "cwd": "/workspace",
        "sandbox_permissions": "require_escalated",
        "justification": "Synthetic fixture action.",
        "tty": False,
    }


def logical_payload(text: str) -> dict:
    return build_static_payload(
        {
            "instructions": "synthetic Guardian policy",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                }
            ],
        }
    ).logical_payload


def prepared(
    *,
    digest: str,
    semantic_id: str,
    fit: bool,
    partition: str | None = None,
) -> teacher_labels.PreparedInstance:
    payload = logical_payload(approval_text(exec_action(digest[:8])))
    return teacher_labels.PreparedInstance(
        source_relative_path=f"eval-data/runs/run-{digest[:8]}/guardian-evidence/r/E_final.json",
        run_id=f"run-{digest[:8]}",
        review_id=f"review-{digest[:8]}",
        task_id="task-fixture",
        e_final_sha256=digest,
        meta_sha256="f" * 64,
        request_shape="standard",
        static_payload_sha256=hashlib.sha256(
            teacher_labels._canonical_bytes(payload)
        ).hexdigest(),
        action_fingerprint_sha256="e" * 64,
        semantic_id=semantic_id,
        partition=partition or teacher_labels.partition_for(semantic_id),
        input_tokens=11_000 if fit else 12_000,
        fits_12k=fit,
        canonical_payload=payload,
    )


class TeacherIdentityTests(unittest.TestCase):
    def test_last_complete_terminal_exec_action_is_the_identity_source(self) -> None:
        earlier = exec_action("echo earlier")
        final = exec_action("echo final")
        text = approval_text(earlier) + approval_text(final)
        payload = logical_payload(text)

        self.assertEqual(
            teacher_labels.extract_approval_action(payload),
            final,
        )
        first_fp, first_id = teacher_labels.semantic_id_for("task-a", final)
        second_fp, second_id = teacher_labels.semantic_id_for("task-a", final)
        self.assertEqual(first_fp, second_fp)
        self.assertEqual(first_id, second_id)
        self.assertNotEqual(
            first_id,
            teacher_labels.semantic_id_for("task-b", final)[1],
        )
        self.assertIn(teacher_labels.partition_for(first_id), {"seed", "holdout"})

    def test_action_boundary_and_supported_shape_are_fail_closed(self) -> None:
        action = exec_action("true")
        cases = {
            "trailing": approval_text(action) + "untrusted tail",
            "missing_end": approval_text(action).replace(
                ">>> APPROVAL REQUEST END\n", ""
            ),
            "unknown_tool": approval_text({**action, "tool": "apply_patch"}),
            "unknown_field": approval_text({**action, "surprise": True}),
            "ambiguous_header": approval_text(action).replace(
                "Planned action JSON:\n",
                "Planned action JSON:\nPlanned action JSON:\n",
            ),
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                with self.assertRaises(teacher_labels.TeacherLabelsError):
                    teacher_labels.extract_approval_action(logical_payload(text))

    def test_approval_blocks_cannot_cross_messages_or_ignore_later_items(self) -> None:
        action_text = approval_text(exec_action("true"))
        split = action_text.index("Planned action JSON:")
        payload = logical_payload("placeholder")
        payload["input"] = [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": action_text[:split]}],
            },
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": action_text[split:]}],
            },
        ]
        with self.assertRaises(teacher_labels.TeacherLabelsError):
            teacher_labels.extract_approval_action(payload)

        trailing = logical_payload(action_text)
        trailing["input"].append({"type": "function_call", "name": "later"})
        with self.assertRaises(teacher_labels.TeacherLabelsError):
            teacher_labels.extract_approval_action(trailing)

    def test_json_canonicalization_is_utf8_sorted_and_rejects_nan(self) -> None:
        action = exec_action("printf '你好'")
        first = teacher_labels.semantic_id_for("任务", action)
        second = teacher_labels.semantic_id_for(
            "任务", dict(reversed(list(action.items())))
        )
        self.assertEqual(first, second)
        with self.assertRaises(teacher_labels.TeacherLabelsError):
            teacher_labels.semantic_id_for("task", {"value": float("nan")})


class TeacherSelectionTests(unittest.TestCase):
    def test_semantic_and_fit_representatives_are_deterministic(self) -> None:
        semantic_a = "1" * 64
        semantic_b = "2" * 64
        low = prepared(digest="1" * 64, semantic_id=semantic_a, fit=False)
        high = prepared(digest="9" * 64, semantic_id=semantic_a, fit=True)
        unique = prepared(digest="5" * 64, semantic_id=semantic_b, fit=True)

        records, outbound = teacher_labels._build_instance_records(
            [high, unique, low], {}
        )
        by_digest = {record["e_final_sha256"]: record for record in records}
        self.assertTrue(by_digest[low.e_final_sha256]["is_semantic_representative"])
        self.assertFalse(by_digest[low.e_final_sha256]["selected"])
        self.assertEqual(
            by_digest[low.e_final_sha256]["exclusion_reason"],
            "input_plus_output_exceeds_12288",
        )
        self.assertTrue(by_digest[high.e_final_sha256]["selected"])
        self.assertEqual(len(outbound), 2)

        reversed_records, reversed_outbound = teacher_labels._build_instance_records(
            [low, unique, high], {}
        )
        self.assertEqual(records, reversed_records)
        self.assertEqual(outbound, reversed_outbound)

    def test_previous_manifest_freezes_existing_representatives(self) -> None:
        semantic = "3" * 64
        prior = prepared(digest="f" * 64, semantic_id=semantic, fit=True)
        newcomer = prepared(digest="0" * 64, semantic_id=semantic, fit=True)
        records, _outbound = teacher_labels._build_instance_records(
            [prior, newcomer], {semantic: (prior.e_final_sha256, prior.e_final_sha256)}
        )
        by_digest = {record["e_final_sha256"]: record for record in records}
        self.assertTrue(by_digest[prior.e_final_sha256]["is_semantic_representative"])
        self.assertTrue(by_digest[prior.e_final_sha256]["selected"])
        self.assertEqual(
            by_digest[newcomer.e_final_sha256]["exclusion_reason"],
            "semantic_duplicate",
        )


class TeacherMetaTests(unittest.TestCase):
    def test_review_id_comes_from_meta_not_archive_slot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source_root = Path(temporary)
            relative_path = (
                "eval-data/runs/run-1/guardian-evidence/0001/E_final.json"
            )
            meta_path = (source_root / relative_path).with_name("meta.json")
            meta_path.parent.mkdir(parents=True)
            meta = {
                "review_id": "review-1",
                "guardian_source_baseline": (
                    terminal_bench_live.GUARDIAN_SOURCE_BASELINE
                ),
                "guardian_source_commit": terminal_bench_live.GUARDIAN_SOURCE_COMMIT,
                "evidence": "e_final",
                "decision": "approved",
                "terminal_status": "approved",
                "failure_reason": None,
                "attempt_count": 1,
                "duration_ms": 1,
                "guardian_thread_id": None,
                "model": "gpt-5.6-sol",
                "reasoning_effort": "low",
                "token_usage": None,
                "time_to_first_token_ms": None,
            }
            meta_path.write_text(json.dumps(meta), encoding="utf-8")

            loaded, digest = teacher_labels._read_meta(
                source_root,
                relative_path,
                expected_model="gpt-5.6-sol",
                expected_effort="low",
            )

            self.assertEqual(loaded, meta)
            self.assertEqual(
                digest,
                hashlib.sha256(meta_path.read_bytes()).hexdigest(),
            )


class TeacherCensusTests(unittest.TestCase):
    def test_tracked_census_is_the_frozen_complete_input(self) -> None:
        counts, identity = teacher_labels._validate_census(EVAL_ROOT.parent)

        self.assertEqual(len(counts), teacher_labels.EXPECTED_SOURCE_INSTANCES)
        self.assertEqual(
            identity["digest"], teacher_labels.EXPECTED_CENSUS_DIGEST
        )
        self.assertEqual(len(identity["file_sha256"]), 64)


class TeacherResponseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fingerprints = ("3" * 64, "4" * 64)
        self.fingerprint_by_id = {
            teacher_labels._semantic_id_from_fingerprint(
                "task-fixture", fingerprint
            ): fingerprint
            for fingerprint in self.fingerprints
        }
        self.ids = set(self.fingerprint_by_id)
        self.valid = [
            {
                "semantic_id": semantic_id,
                "decision": {
                    "outcome": "allow",
                    "rationale": "The synthetic action is authorized.",
                    "risk_tags": [],
                },
            }
            for semantic_id in sorted(self.ids)
        ]

    def test_raw_response_set_and_decision_schema_are_strict(self) -> None:
        accepted = teacher_labels.validate_raw_responses(self.valid, self.ids)
        self.assertEqual(set(accepted), self.ids)

        bad_cases = [
            self.valid[:-1],
            self.valid + [self.valid[0]],
            [{**self.valid[0], "extra": True}, self.valid[1]],
            [
                {
                    **self.valid[0],
                    "decision": {**self.valid[0]["decision"], "outcome": "maybe"},
                },
                self.valid[1],
            ],
            [
                {
                    **self.valid[0],
                    "decision": {
                        **self.valid[0]["decision"],
                        "risk_tags": ["same", "same"],
                    },
                },
                self.valid[1],
            ],
        ]
        for responses in bad_cases:
            with self.subTest(responses=responses):
                with self.assertRaises(teacher_labels.TeacherLabelsError):
                    teacher_labels.validate_raw_responses(responses, self.ids)

    def test_attempt_provenance_is_complete_and_strict(self) -> None:
        retry_id = sorted(self.ids)[0]
        attempts = [
            {
                "schema_version": teacher_labels.ATTEMPT_SCHEMA_VERSION,
                "semantic_id": semantic_id,
                "attempt": 2 if semantic_id == retry_id else 1,
                "retry_reason": (
                    "transport_failed" if semantic_id == retry_id else None
                ),
            }
            for semantic_id in sorted(self.ids)
        ]
        accepted = teacher_labels.validate_attempts(attempts, self.ids)
        self.assertEqual(set(accepted), self.ids)
        invalid = [dict(row) for row in attempts]
        invalid[0]["attempt"] = 1
        with self.assertRaises(teacher_labels.TeacherLabelsError):
            teacher_labels.validate_attempts(invalid, self.ids)

        for field in ("schema_version", "attempt"):
            invalid_bool = [dict(row) for row in attempts]
            invalid_bool[0][field] = True
            with self.subTest(field=field):
                with self.assertRaises(teacher_labels.TeacherLabelsError):
                    teacher_labels.validate_attempts(invalid_bool, self.ids)

    def test_manifest_unknown_fields_counts_and_representatives_fail_closed(self) -> None:
        patches = (
            mock.patch.object(teacher_labels, "EXPECTED_SOURCE_INSTANCES", 2),
            mock.patch.object(teacher_labels, "EXPECTED_SEMANTIC_IDENTITIES", 2),
            mock.patch.object(teacher_labels, "EXPECTED_DUPLICATE_INSTANCES", 0),
            mock.patch.object(teacher_labels, "EXPECTED_12K_FIT_INSTANCES", 2),
            mock.patch.object(teacher_labels, "EXPECTED_SELECTED_LABELS", 2),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        manifest = self._manifest()
        self.assertEqual(set(teacher_labels._manifest_selected(manifest)), self.ids)

        bad_unknown = json.loads(json.dumps(manifest))
        bad_unknown["instances"][0]["unknown"] = True
        with self.assertRaises(teacher_labels.TeacherLabelsError):
            teacher_labels._manifest_selected(bad_unknown)

        bad_counts = json.loads(json.dumps(manifest))
        bad_counts["counts"]["selected_labels"] = 1
        with self.assertRaises(teacher_labels.TeacherLabelsError):
            teacher_labels._manifest_selected(bad_counts)

        bad_representative = json.loads(json.dumps(manifest))
        bad_representative["instances"][0][
            "semantic_representative_e_final_sha256"
        ] = "9" * 64
        with self.assertRaises(teacher_labels.TeacherLabelsError):
            teacher_labels._manifest_selected(bad_representative)

    def test_recorded_raw_responses_preserve_exact_lines_and_private_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_dir = Path(temporary) / "batch"
            private_dir.mkdir(mode=0o700)
            manifest = self._manifest()
            lines = [json.dumps(row, separators=(",", ":")) for row in self.valid]
            selected = {
                item["semantic_id"]: item for item in manifest["instances"]
            }
            frozen = (manifest, b"manifest", selected, [], b"outbound", b"receipt")
            with mock.patch.object(
                teacher_labels, "_validate_frozen_batch", return_value=frozen
            ):
                result = teacher_labels.record_raw_responses(
                    worktree_root=EVAL_ROOT.parent,
                    private_dir=private_dir,
                    input_lines=lines,
                    retry_reasons={sorted(self.ids)[0]: "transport_failed"},
                )
            raw_path = private_dir / "raw-responses.jsonl"
            self.assertEqual(raw_path.read_text(), "\n".join(lines) + "\n")
            self.assertEqual(raw_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(result["responses"], 2)
            self.assertEqual(result["retries"]["transport_failed"], 1)
            attempts = [
                json.loads(line)
                for line in (private_dir / "attempts.jsonl").read_text().splitlines()
            ]
            self.assertEqual([row["attempt"] for row in attempts], [2, 1])

    def test_summary_rejects_labels_and_metadata_tampered_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private_dir = Path(temporary) / "batch"
            private_dir.mkdir(mode=0o700)
            manifest = self._manifest()
            selected = {
                item["semantic_id"]: item for item in manifest["instances"]
            }
            frozen = (manifest, b"manifest", selected, [], b"outbound", b"receipt")
            raw = teacher_labels._jsonl_bytes(self.valid)
            attempts = teacher_labels._jsonl_bytes(
                [
                    {
                        "schema_version": teacher_labels.ATTEMPT_SCHEMA_VERSION,
                        "semantic_id": semantic_id,
                        "attempt": 1,
                        "retry_reason": None,
                    }
                    for semantic_id in sorted(self.ids)
                ]
            )
            teacher_labels._write_exclusive(
                private_dir / "raw-responses.jsonl", raw, mode=0o600
            )
            teacher_labels._write_exclusive(
                private_dir / "attempts.jsonl", attempts, mode=0o600
            )
            with mock.patch.object(
                teacher_labels, "_validate_frozen_batch", return_value=frozen
            ):
                teacher_labels.verify_batch(
                    worktree_root=EVAL_ROOT.parent,
                    private_dir=private_dir,
                    teacher_model=teacher_labels.TEACHER_MODEL,
                    generated_date="2026-08-15",
                )
                labels, _labels_raw = teacher_labels._load_jsonl(
                    private_dir / "labels.jsonl", private=True
                )
                labels[0]["decision"]["rationale"] = "Coupled tamper."
                tampered_labels = teacher_labels._jsonl_bytes(labels)
                (private_dir / "labels.jsonl").write_bytes(tampered_labels)
                metadata, _metadata_raw = teacher_labels._load_json(
                    private_dir / "import-metadata.json", private=True
                )
                metadata["labels_sha256"] = hashlib.sha256(
                    tampered_labels
                ).hexdigest()
                (private_dir / "import-metadata.json").write_bytes(
                    teacher_labels._json_file_bytes(metadata)
                )

                with self.assertRaisesRegex(
                    teacher_labels.TeacherLabelsError,
                    "existing_output_differs",
                ):
                    teacher_labels.build_summary(
                        worktree_root=EVAL_ROOT.parent,
                        private_dir=private_dir,
                    )

    def _manifest(self) -> dict:
        instances = []
        for index, semantic_id in enumerate(sorted(self.ids)):
            digest = f"{index + 1:064x}"
            instances.append(
                {
                    "source_instance_id": digest,
                    "source_relative_path": (
                        f"eval-data/runs/run-{index}/guardian-evidence/"
                        f"{index + 1:04d}/E_final.json"
                    ),
                    "run_id": f"run-{index}",
                    "review_id": f"review-{index}",
                    "task_id": "task-fixture",
                    "semantic_id": semantic_id,
                    "partition": teacher_labels.partition_for(semantic_id),
                    "selected": True,
                    "fits_12k": True,
                    "is_label_representative": True,
                    "exclusion_reason": None,
                    "usage": teacher_labels._usage(
                        teacher_labels.partition_for(semantic_id)
                    ),
                    "e_final_sha256": digest,
                    "meta_sha256": "e" * 64,
                    "request_shape": teacher_labels.EXPECTED_REQUEST_SHAPE,
                    "static_payload_sha256": "f" * 64,
                    "action_fingerprint_sha256": self.fingerprint_by_id[
                        semantic_id
                    ],
                    "semantic_representative_e_final_sha256": digest,
                    "label_representative_e_final_sha256": digest,
                    "is_semantic_representative": True,
                    "input_tokens": 1_000,
                }
            )
        semantic_partitions = {
            partition: sum(item["partition"] == partition for item in instances)
            for partition in ("seed", "holdout")
        }
        return {
            "schema_version": teacher_labels.MANIFEST_SCHEMA_VERSION,
            "batch_id": "20260815-fixture",
            "purpose": "first point-in-time gpt-5.6-sol teacher labels for L3 static replay",
            "created_date": "2026-08-15",
            "identity_rule_version": teacher_labels.IDENTITY_RULE_VERSION,
            "representative_rule_version": teacher_labels.REPRESENTATIVE_RULE_VERSION,
            "static_payload_schema_version": teacher_labels.STATIC_PAYLOAD_SCHEMA_VERSION,
            "static_decision_schema_name": teacher_labels.STATIC_DECISION_SCHEMA_NAME,
            "prompt_version": teacher_labels.PROMPT_VERSION,
            "prompt_sha256": "c" * 64,
            "label_schema_version": teacher_labels.LABEL_SCHEMA_VERSION,
            "label_schema_sha256": "d" * 64,
            "census": {
                "schema_version": teacher_labels.token_census.CENSUS_SCHEMA_VERSION,
                "digest": teacher_labels.EXPECTED_CENSUS_DIGEST,
                "file_sha256": "b" * 64,
            },
            "context_contract": {
                "context_size": teacher_labels.CONTEXT_SIZE,
                "max_output_tokens": teacher_labels.MAX_OUTPUT_TOKENS,
                "fit_rule": "input_tokens + max_output_tokens <= context_size",
            },
            "usage_contract": {
                "seed": "evaluation and future synthesis reference; real evidence itself is not training data",
                "holdout": "evaluation only; forbidden from synthesis context, synthesis prompt, synthesis-time reference, and training",
            },
            "counts": {
                "source_instances": 2,
                "semantic_unique": 2,
                "duplicate_instances": 0,
                "fit_12k_instances": 2,
                "selected_labels": 2,
                "semantic_partitions": semantic_partitions,
                "selected_partitions": semantic_partitions,
                "exclusions": {},
            },
            "instances": instances,
        }


if __name__ == "__main__":
    unittest.main()
