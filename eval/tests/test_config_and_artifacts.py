from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval import artifacts  # noqa: E402
from rondo_eval.artifacts import ArtifactError, ArtifactWriter  # noqa: E402
from rondo_eval.config import (  # noqa: E402
    ConfigError,
    RepoPaths,
    load_local_model_secret,
    load_provider_secret,
    load_runtime_config,
)


PAID_EVAL_CONFIG = """\
[paid_eval]
active_provider = "relay"
main_model = "main"
guardian_model = "guardian"
main_reasoning_effort = "medium"
guardian_reasoning_effort = "low"
max_attempts = 1
retry_backoff_seconds = 0

[paid_eval.providers.relay]
display_name = "Test relay"
api = "responses"
base_url = "https://relay.example/v1"
api_key_env = "OPENAI_API_KEY"
unbilled_retry_statuses = []

[paid_eval.models.main]
model_id = "test-main-model"
input_usd_per_million = "1.00"
cached_input_usd_per_million = "0.10"
output_usd_per_million = "6.00"
long_context_threshold_tokens = 272000
long_context_input_multiplier = "2"
long_context_output_multiplier = "1.5"
cache_write_input_multiplier = "1.25"
price_snapshot_date = "2026-08-10"
price_source_url = "https://developers.openai.com/api/docs/models/compare"

[paid_eval.models.guardian]
model_id = "test-guardian-model"
input_usd_per_million = "0.20"
cached_input_usd_per_million = "0.02"
output_usd_per_million = "1.20"
long_context_threshold_tokens = 272000
long_context_input_multiplier = "2"
long_context_output_multiplier = "1.5"
cache_write_input_multiplier = "1.25"
price_snapshot_date = "2026-08-10"
price_source_url = "https://developers.openai.com/api/docs/models/compare"
"""


class ConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = RepoPaths(root, root)
        (root / "rondo.secrets.example.env").write_text("OPENAI_API_KEY=\n", encoding="utf-8")
        (root / "rondo.local.toml").write_text(
            PAID_EVAL_CONFIG,
            encoding="utf-8",
        )
        (root / ".env.local").write_text("OPENAI_API_KEY=secret-test-value\n", encoding="utf-8")
        os.chmod(root / ".env.local", 0o600)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_loader_returns_only_selected_secret(self) -> None:
        config = load_runtime_config(self.paths)
        self.assertEqual(
            load_provider_secret(config),
            ("OPENAI_API_KEY", "secret-test-value"),
        )

    def test_shell_syntax_is_rejected(self) -> None:
        (self.paths.common_root / ".env.local").write_text(
            "export OPENAI_API_KEY=secret-test-value\n",
            encoding="utf-8",
        )
        with self.assertRaises(ConfigError):
            load_provider_secret(load_runtime_config(self.paths))

    def test_direct_secret_in_toml_is_rejected(self) -> None:
        (self.paths.common_root / "rondo.local.toml").write_text(
            PAID_EVAL_CONFIG.replace(
                'api_key_env = "OPENAI_API_KEY"',
                'api_key_env = "OPENAI_API_KEY"\napi_key = "never-here"',
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ConfigError):
            load_runtime_config(self.paths)

    def test_local_model_secret_uses_the_same_strict_loader(self) -> None:
        (self.paths.common_root / "rondo.secrets.example.env").write_text(
            "OPENAI_API_KEY=\nRONDO_LOCAL_MODEL_API_KEY=\n",
            encoding="utf-8",
        )
        (self.paths.common_root / "rondo.local.toml").write_text(
            PAID_EVAL_CONFIG
            + "[local_model]\napi_key_env = \"RONDO_LOCAL_MODEL_API_KEY\"\n",
            encoding="utf-8",
        )
        (self.paths.common_root / ".env.local").write_text(
            "OPENAI_API_KEY=secret-test-value\nRONDO_LOCAL_MODEL_API_KEY=local-secret-value\n",
            encoding="utf-8",
        )
        config = load_runtime_config(self.paths)
        self.assertEqual(
            load_local_model_secret(config),
            ("RONDO_LOCAL_MODEL_API_KEY", "local-secret-value"),
        )

    def test_empty_local_model_secret_means_loopback_without_auth(self) -> None:
        (self.paths.common_root / "rondo.secrets.example.env").write_text(
            "OPENAI_API_KEY=\nRONDO_LOCAL_MODEL_API_KEY=\n",
            encoding="utf-8",
        )
        (self.paths.common_root / "rondo.local.toml").write_text(
            PAID_EVAL_CONFIG
            + "[local_model]\napi_key_env = \"RONDO_LOCAL_MODEL_API_KEY\"\n",
            encoding="utf-8",
        )
        (self.paths.common_root / ".env.local").write_text(
            "OPENAI_API_KEY=secret-test-value\nRONDO_LOCAL_MODEL_API_KEY=\n",
            encoding="utf-8",
        )
        self.assertIsNone(load_local_model_secret(load_runtime_config(self.paths)))


class ArtifactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = RepoPaths(root, root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _record(self, run_id: str, *, track: str = "tb", side: str = "rondo") -> dict:
        return {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": "2026-08-09T00:00:00+08:00",
            "track": track,
            "side": side,
            "git_commit": "a" * 40,
            "git_dirty": False,
            "binary_sha256": "b" * 64,
            "upstream_codex": {
                "tag": "rust-v0.147.0",
                "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
            },
            "config": {"model": "fake"},
            "outcome": "completed",
            "summary": {"success_rate": 1.0},
            "tasks": [{"task_id": "fake", "outcome": "pass"}],
            "metrics": {
                "wall_seconds": 1.0,
                "cpu_user_seconds": 0.5,
                "cpu_system_seconds": 0.25,
                "peak_rss_bytes": 4096,
                "exit_code": 0,
            },
            "cost": {"estimated_usd": 0.0, "actual_usd": 0.0},
            "artifacts": f"eval-data/runs/{run_id}",
            "notes": "",
        }

    @staticmethod
    def _write_private_summary(writer: ArtifactWriter, record: dict) -> None:
        writer.write_json(
            "run-summary.json",
            {
                "schema_version": 1,
                "run_id": record["run_id"],
                "side": record["side"],
                "git_commit": record["git_commit"],
                "outcome": record["outcome"],
                "config": record["config"],
                "summary": record["summary"],
                "tasks": record["tasks"],
            },
        )

    @staticmethod
    def _set_tb_product(
        record: dict,
        product: str,
        *,
        campaign_schema_version: int | None = None,
    ) -> None:
        record["product"] = product
        auto_review = (
            {
                "schema_version": 1,
                "model": None,
                "model_provider": None,
                "reasoning_effort": None,
                "evidence_dir": None,
            }
            if product == "rondo-multi"
            else {
                "schema_version": 1,
                "model": "guardian",
                "model_provider": None,
                "reasoning_effort": "low",
                "evidence_dir": "guardian-evidence",
            }
        )
        record["config"] = {
            "private_summary_schema_version": 1,
            "guardian_model": "guardian",
            "guardian_effort": "low",
            "product": product,
            "binary_product": product,
            "auto_review_config": auto_review,
        }
        if campaign_schema_version is not None:
            record["config"].update(
                {
                    "campaign_id": "campaign-product-contract",
                    "campaign_schema_version": campaign_schema_version,
                }
            )
            if campaign_schema_version == 7:
                record["config"]["campaign_product"] = product

    def test_finalize_publishes_private_artifacts_and_appends_index(self) -> None:
        cases = (
            ("20260809-000000000-tb-rondo-r1", "rondo"),
            ("20260809-000000001-tb-codex-r1", "codex"),
        )
        for run_id, side in cases:
            writer = ArtifactWriter(self.paths, run_id).start()
            writer.write_json("result.json", {"ok": True})
            target = writer.finalize(self._record(run_id, side=side), secrets=())
            self.assertTrue((target / "result.json").is_file())
            if os.name == "posix":
                self.assertEqual(target.stat().st_mode & 0o777, 0o700)
                self.assertEqual((target / "result.json").stat().st_mode & 0o777, 0o600)
        rows = [
            json.loads(line)
            for line in (self.paths.common_root / "eval/results/runs.jsonl").read_text().splitlines()
        ]
        self.assertEqual([row["run_id"] for row in rows], [case[0] for case in cases])
        expected_index = b"".join(
            json.dumps(
                self._record(run_id, side=side),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
            for run_id, side in cases
        )
        self.assertEqual(
            (self.paths.common_root / "eval/results/runs.jsonl").read_bytes(),
            expected_index,
        )
        self.assertTrue(
            all(
                row["upstream_codex"]
                == {
                    "tag": "rust-v0.147.0",
                    "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                    "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
                }
                for row in rows
            )
        )

    def test_durable_index_rejects_product_config_and_auto_review_tampering(self) -> None:
        mutations = (
            lambda row: row["config"].__setitem__("product", "rondo-local"),
            lambda row: row["config"].__setitem__("binary_product", "rondo-local"),
            lambda row: row["config"]["auto_review_config"].__setitem__(
                "schema_version", 2
            ),
            lambda row: row["config"]["auto_review_config"].__setitem__(
                "model", "forged-model"
            ),
            lambda row: row["config"]["auto_review_config"].__setitem__(
                "unexpected", None
            ),
        )
        for index, mutate in enumerate(mutations, start=1):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = RepoPaths(root, root)
                run_id = f"20260809-0100000{index:02d}-tb-rondo-r1"
                record = self._record(run_id)
                record["product"] = "rondo-multi"
                record["config"] = {
                    "private_summary_schema_version": 1,
                    "guardian_model": "guardian",
                    "guardian_effort": "low",
                    "product": "rondo-multi",
                    "binary_product": "rondo-multi",
                    "auto_review_config": {
                        "schema_version": 1,
                        "model": None,
                        "model_provider": None,
                        "reasoning_effort": None,
                        "evidence_dir": None,
                    },
                }
                writer = ArtifactWriter(paths, run_id).start()
                writer.write_json("result.json", {"ok": True})
                self._write_private_summary(writer, record)
                writer.finalize(record, secrets=())
                index_path = root / "eval/results/runs.jsonl"
                tampered = json.loads(index_path.read_text(encoding="utf-8"))
                mutate(tampered)
                index_path.write_text(
                    json.dumps(tampered, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                next_id = f"20260809-0200000{index:02d}-tb-rondo-r1"
                with self.assertRaisesRegex(ArtifactError, "product|auto-review"):
                    ArtifactWriter(paths, next_id).start()

    def test_boolean_values_cannot_impersonate_numeric_schema_versions(self) -> None:
        mutations = (
            lambda record: record.__setitem__("schema_version", True),
            lambda record: record["config"].__setitem__(
                "private_summary_schema_version", True
            ),
            lambda record: record["config"]["auto_review_config"].__setitem__(
                "schema_version", True
            ),
        )
        for number, mutate in enumerate(mutations, start=90):
            with self.subTest(number=number), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = RepoPaths(root, root)
                run_id = f"20260809-0000000{number}-tb-rondo-r1"
                record = self._record(run_id)
                self._set_tb_product(record, "rondo-multi")
                mutate(record)
                writer = ArtifactWriter(paths, run_id).start()
                self._write_private_summary(writer, record)
                with self.assertRaisesRegex(ArtifactError, "schema|version"):
                    writer.finalize(record, secrets=())
                self.assertFalse(writer.journal.exists())
                self.assertFalse(writer.target.exists())

        run_id = "20260809-000000093-tb-rondo-r1"
        record = self._record(run_id)
        self._set_tb_product(record, "rondo-multi")
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json(
            "run-summary.json",
            {
                "schema_version": True,
                "run_id": run_id,
                "side": "rondo",
                "git_commit": record["git_commit"],
                "outcome": record["outcome"],
                "config": record["config"],
                "summary": record["summary"],
                "tasks": record["tasks"],
            },
        )
        with self.assertRaisesRegex(ArtifactError, "private run summary"):
            writer.finalize(record, secrets=())
        self.assertFalse(writer.journal.exists())
        self.assertFalse(writer.target.exists())

    def test_v7_campaign_product_binding_is_required_before_publication(self) -> None:
        for number, side in enumerate(("rondo", "codex"), start=70):
            with self.subTest(side=side), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = RepoPaths(root, root)
                run_id = f"20260809-0000000{number}-tb-{side}-r1"
                record = self._record(run_id, side=side)
                record["config"] = {
                    "private_summary_schema_version": 1,
                    "campaign_id": "campaign-product-contract",
                    "campaign_schema_version": 7,
                    "campaign_product": "rondo-multi",
                }
                if side == "rondo":
                    self._set_tb_product(
                        record, "rondo-multi", campaign_schema_version=7
                    )
                writer = ArtifactWriter(paths, run_id).start()
                self._write_private_summary(writer, record)
                writer.finalize(record, secrets=())

                row = json.loads(
                    (root / "eval/results/runs.jsonl").read_text(encoding="utf-8")
                )
                self.assertEqual(row["config"]["campaign_product"], "rondo-multi")
                self.assertEqual("product" in row, side == "rondo")

        for number, side in enumerate(("rondo", "codex"), start=72):
            with self.subTest(missing_side=side), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = RepoPaths(root, root)
                run_id = f"20260809-0000000{number}-tb-{side}-r1"
                record = self._record(run_id, side=side)
                if side == "rondo":
                    self._set_tb_product(
                        record, "rondo-multi", campaign_schema_version=7
                    )
                else:
                    record["config"] = {
                        "private_summary_schema_version": 1,
                        "campaign_id": "campaign-product-contract",
                        "campaign_schema_version": 7,
                    }
                record["config"].pop("campaign_product", None)
                writer = ArtifactWriter(paths, run_id).start()
                self._write_private_summary(writer, record)
                with self.assertRaisesRegex(ArtifactError, "v7 campaign|campaign"):
                    writer.finalize(record, secrets=())
                self.assertFalse(writer.journal.exists())
                self.assertFalse(writer.target.exists())
                self.assertFalse(writer.results.exists())

    def test_private_summary_is_required_and_revalidated_during_recovery(self) -> None:
        from unittest import mock

        run_id = "20260809-000000074-tb-rondo-r1"
        record = self._record(run_id)
        self._set_tb_product(record, "rondo-multi", campaign_schema_version=7)
        missing = ArtifactWriter(self.paths, run_id).start()
        with self.assertRaisesRegex(ArtifactError, "private run summary"):
            missing.finalize(record, secrets=())
        self.assertFalse(missing.journal.exists())
        self.assertFalse(missing.target.exists())
        missing.abort()

        writer = ArtifactWriter(self.paths, run_id).start()
        self._write_private_summary(writer, record)
        with mock.patch(
            "rondo_eval.artifacts._atomic_replace_index", side_effect=KeyboardInterrupt
        ):
            with self.assertRaises(KeyboardInterrupt):
                writer.finalize(record, secrets=())
        summary_path = writer.target / "run-summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["config"]["campaign_product"] = "rondo-local"
        summary_path.write_text(
            json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        journal = json.loads(writer.journal.read_text(encoding="utf-8"))
        journal["tree_identity"] = artifacts._artifact_tree_identity(writer.target, ())
        writer.journal.write_text(
            json.dumps(journal, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        next_id = "20260809-000000075-tb-rondo-r1"
        with self.assertRaisesRegex(ArtifactError, "private run summary differs"):
            ArtifactWriter(self.paths, next_id).start()
        self.assertTrue(writer.journal.exists())
        self.assertFalse(writer.results.exists())

    def test_replay_product_and_binary_contract_is_durable(self) -> None:
        for number, product in enumerate(("rondo-local", "rondo-multi"), start=76):
            with self.subTest(product=product), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = RepoPaths(root, root)
                run_id = f"20260809-0000000{number}-replay-rondo-r1"
                record = self._record(run_id, track="replay")
                record["tasks"] = None
                record["metrics"] = {"drift": 0.0}
                record["product"] = product
                record["config"] = {
                    "product": product,
                    "binary_product": product,
                }
                writer = ArtifactWriter(paths, run_id).start()
                writer.write_json("result.json", {"ok": True})
                writer.finalize(record, secrets=())

                index_path = root / "eval/results/runs.jsonl"
                row = json.loads(index_path.read_text(encoding="utf-8"))
                row["config"]["binary_product"] = (
                    "rondo-local" if product == "rondo-multi" else "rondo-multi"
                )
                index_path.write_text(
                    json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                next_id = f"20260809-0000000{number + 2}-replay-rondo-r1"
                with self.assertRaisesRegex(ArtifactError, "replay product"):
                    ArtifactWriter(paths, next_id).start()

        run_id = "20260809-000000080-replay-rondo-r1"
        record = self._record(run_id, track="replay")
        record["tasks"] = None
        record["metrics"] = {"drift": 0.0}
        record["product"] = "rondo-local"
        record["config"] = {
            "product": "rondo-local",
            "binary_product": "rondo-local",
            "auto_review_config": {"schema_version": 999},
        }
        writer = ArtifactWriter(self.paths, run_id).start()
        with self.assertRaisesRegex(ArtifactError, "replay record"):
            writer.finalize(record, secrets=())
        self.assertFalse(writer.journal.exists())

    def test_shadow_local_sides_are_exactly_local(self) -> None:
        for number, side in enumerate(("local-static", "local-ft-static"), start=81):
            with self.subTest(side=side), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                paths = RepoPaths(root, root)
                run_id = f"20260809-0000000{number}-shadow-{side}-r1"
                record = self._record(run_id, track="shadow", side=side)
                record["tasks"] = None
                record["metrics"] = {"agreement": 1.0}
                record["product"] = "rondo-local"
                record["config"] = {
                    "product": "rondo-local",
                    "binary_product": "rondo-local",
                }
                writer = ArtifactWriter(paths, run_id).start()
                writer.write_json("result.json", {"ok": True})
                writer.finalize(record, secrets=())

                index_path = root / "eval/results/runs.jsonl"
                row = json.loads(index_path.read_text(encoding="utf-8"))
                row["product"] = "rondo-multi"
                row["config"]["product"] = "rondo-multi"
                row["config"]["binary_product"] = "rondo-multi"
                index_path.write_text(
                    json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n",
                    encoding="utf-8",
                )
                next_id = f"20260809-0000000{number + 2}-shadow-{side}-r1"
                with self.assertRaisesRegex(ArtifactError, "shadow side"):
                    ArtifactWriter(paths, next_id).start()

        for number, side in enumerate(("luna-static", "sol-static"), start=85):
            with self.subTest(non_product_side=side):
                run_id = f"20260809-0000000{number}-shadow-{side}-r1"
                record = self._record(run_id, track="shadow", side=side)
                record["tasks"] = None
                record["metrics"] = {"agreement": 1.0}
                record["product"] = "rondo-local"
                record["config"] = {
                    "product": "rondo-local",
                    "binary_product": "rondo-local",
                }
                writer = ArtifactWriter(self.paths, run_id).start()
                with self.assertRaisesRegex(ArtifactError, "cannot carry a product"):
                    writer.finalize(record, secrets=())

    def test_upstream_codex_identity_is_exact(self) -> None:
        invalid_values = (
            None,
            {},
            {
                "tag": "rust-v0.147.0",
                "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
            },
            {
                "tag": "rust-v0.147.0",
                "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
                "extra": "not-schema-v1",
            },
            {
                "tag": "rust-v0.146.0",
                "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
            },
            {
                "tag": "rust-v0.147.0",
                "commit": "a" * 40,
                "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
            },
            {
                "tag": "rust-v0.147.0",
                "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                "workspace_lock_normalization": "134 workspace packages: 0.0.0 -> 0.147.0",
            },
        )
        for number, value in enumerate(invalid_values, start=25):
            with self.subTest(value=value):
                run_id = f"20260809-0000000{number}-tb-rondo-r1"
                writer = ArtifactWriter(self.paths, run_id).start()
                writer.write_json("result.json", {"ok": True})
                record = self._record(run_id)
                record["upstream_codex"] = value
                with self.assertRaises(ArtifactError):
                    writer.finalize(record, secrets=())

    def test_upstream_codex_identity_is_required_for_every_track(self) -> None:
        cases = (
            ("20260809-000000032-tb-rondo-r1", "tb", "rondo"),
            ("20260809-000000033-replay-codex-r1", "replay", "codex"),
            ("20260809-000000034-shadow-luna-static-r1", "shadow", "luna-static"),
        )
        for run_id, track, side in cases:
            with self.subTest(track=track):
                writer = ArtifactWriter(self.paths, run_id).start()
                writer.write_json("result.json", {"ok": True})
                record = self._record(run_id, track=track, side=side)
                if track != "tb":
                    record["tasks"] = None
                    record["metrics"] = {"fake_metric": 1.0}
                del record["upstream_codex"]
                with self.assertRaises(ArtifactError):
                    writer.finalize(record, secrets=())

    def test_secret_scan_fails_before_publication(self) -> None:
        run_id = "20260809-000000002-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_bytes("stdout.log", b"prefix s3cr3t suffix")
        with self.assertRaises(ArtifactError):
            writer.finalize(self._record(run_id), secrets=["s3cr3t"])
        self.assertFalse(writer.target.exists())
        self.assertTrue(writer.staging.exists())

    def test_mandatory_scan_rejects_sensitive_artifact_shapes_without_exact_secrets(self) -> None:
        unsafe_values = (
            b'{"api_key":"not-for-an-artifact"}',
            b"OPENAI_API_KEY=not-for-an-artifact",
            b"Authorization: Basic dXNlcjpwYXNz\n",
            b"request=https://user:password@example.invalid/path",
        )
        for number, contents in enumerate(unsafe_values, start=3):
            with self.subTest(contents=contents):
                run_id = f"20260809-00000000{number}-tb-rondo-r1"
                writer = ArtifactWriter(self.paths, run_id).start()
                writer.write_bytes("stdout.log", contents)
                with self.assertRaises(ArtifactError):
                    writer.finalize(self._record(run_id), secrets=())

    def test_secret_scan_allows_exact_guardian_authorization_schema_field(self) -> None:
        run_id = "20260809-000000035-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json(
            "guardian-evidence/0001/E_final.json",
            {
                "input": [],
                "text": {
                    "format": {
                        "schema": {
                            "properties": {
                                "user_authorization": {
                                    "type": "string",
                                    "enum": ["unknown", "low", "medium", "high"],
                                }
                            }
                        }
                    }
                }
            },
        )

        target = writer.finalize(self._record(run_id), secrets=())

        self.assertTrue((target / "guardian-evidence/0001/E_final.json").is_file())

    def test_secret_scan_rejects_guardian_authorization_value_outside_schema(self) -> None:
        run_id = "20260809-000000036-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_bytes(
            "guardian-evidence/0001/E_final.json",
            b'{"user_authorization":"Bearer hidden-secret"}',
        )
        with self.assertRaises(ArtifactError):
            writer.finalize(self._record(run_id), secrets=())

    def test_secret_scan_allows_credential_shaped_guardian_task_input(self) -> None:
        run_id = "20260809-000000037-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json(
            "guardian-evidence/0001/E_final.json",
            {
                "input": [
                    {
                        "role": "user",
                        "content": (
                            "sanitize fixture OPENAI_API_KEY=task-decoy and "
                            "https://fixture-user:fixture-password@example.invalid/path"
                        ),
                    }
                ],
                "text": {
                    "format": {
                        "schema": {
                            "properties": {
                                "user_authorization": {
                                    "type": "string",
                                    "enum": ["unknown", "low", "medium", "high"],
                                }
                            }
                        }
                    }
                },
            },
        )

        target = writer.finalize(self._record(run_id), secrets=("real-runtime-key",))

        self.assertTrue((target / "guardian-evidence/0001/E_final.json").is_file())

    def test_guardian_task_input_still_rejects_exact_configured_secret(self) -> None:
        run_id = "20260809-000000038-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json(
            "guardian-evidence/0001/E_final.json",
            {
                "input": [{"role": "user", "content": "real-runtime-key"}],
                "text": {
                    "format": {
                        "schema": {
                            "properties": {
                                "user_authorization": {
                                    "type": "string",
                                    "enum": ["unknown", "low", "medium", "high"],
                                }
                            }
                        }
                    }
                },
            },
        )

        with self.assertRaises(ArtifactError):
            writer.finalize(self._record(run_id), secrets=("real-runtime-key",))

    def test_tracked_record_is_included_in_secret_scan(self) -> None:
        run_id = "20260809-000000006-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json("result.json", {"ok": True})
        record = self._record(run_id)
        record["notes"] = "accidentally copied s3cr3t here"
        with self.assertRaises(ArtifactError):
            writer.finalize(record, secrets=["s3cr3t"])
        self.assertFalse(writer.target.exists())
        self.assertFalse((self.paths.common_root / "eval/results/runs.jsonl").exists())

    def test_tracked_record_rejects_sensitive_key_even_without_exact_secrets(self) -> None:
        run_id = "20260809-000000007-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json("result.json", {"ok": True})
        record = self._record(run_id)
        record["config"] = {"api_key": "not-for-the-index"}
        with self.assertRaises(ArtifactError):
            writer.finalize(record, secrets=())

    def test_existing_target_is_never_overwritten(self) -> None:
        run_id = "20260809-000000008-tb-rondo-r1"
        target = self.paths.common_root / "eval-data/runs" / run_id
        target.mkdir(parents=True)
        with self.assertRaises(ArtifactError):
            ArtifactWriter(self.paths, run_id).start()

    def test_duplicate_run_id_in_index_is_rejected(self) -> None:
        run_id = "20260809-000000009-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id)
        writer.results.parent.mkdir(parents=True)
        writer.results.write_text(json.dumps(self._record(run_id)) + "\n", encoding="utf-8")
        with self.assertRaises(ArtifactError):
            writer.start()
        self.assertFalse(writer.staging.exists())
        self.assertFalse(writer.target.exists())

    def test_abort_releases_only_the_unpublished_staging_claim(self) -> None:
        run_id = "20260809-000000035-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json("result.json", {"ok": True})
        writer.abort()
        self.assertFalse(writer.staging.exists())
        self.assertFalse(writer.target.exists())
        self.assertFalse(writer.journal.exists())

    def test_partial_index_write_base_exception_keeps_previous_index_intact(self) -> None:
        from unittest import mock

        baseline_id = "20260809-000000010-tb-rondo-r1"
        baseline = ArtifactWriter(self.paths, baseline_id).start()
        baseline.write_json("result.json", {"ok": True})
        baseline.finalize(self._record(baseline_id), secrets=())
        original_index = baseline.results.read_bytes()

        run_id = "20260809-000000036-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json("result.json", {"ok": True})
        real_write = os.write

        def interrupt_after_partial_write(descriptor, contents):
            real_write(descriptor, bytes(contents[:11]))
            raise KeyboardInterrupt

        with mock.patch(
            "rondo_eval.artifacts._write_all", side_effect=interrupt_after_partial_write
        ):
            with self.assertRaises(KeyboardInterrupt):
                writer.finalize(self._record(run_id), secrets=())
        self.assertFalse(writer.staging.exists())
        self.assertTrue(writer.target.exists())
        self.assertTrue(writer.journal.exists())
        self.assertEqual(writer.results.read_bytes(), original_index)
        self.assertFalse(
            (writer.results.parent / f".runs.jsonl.publish-{run_id}.tmp").exists()
        )

        next_id = "20260809-000000037-tb-rondo-r1"
        next_writer = ArtifactWriter(self.paths, next_id).start()
        next_writer.abort()
        self.assertTrue(writer.target.exists())
        self.assertFalse(writer.journal.exists())
        rows = [json.loads(line) for line in writer.results.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["run_id"] for row in rows], [baseline_id, run_id])

    def test_interrupted_publication_is_reconciled_from_journal(self) -> None:
        from unittest import mock

        run_id = "20260809-000000024-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json("result.json", {"ok": True})
        with mock.patch("rondo_eval.artifacts._atomic_replace_index", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                writer.finalize(self._record(run_id), secrets=())
        self.assertTrue(writer.target.exists())
        self.assertTrue(writer.journal.exists())
        self.assertFalse(writer.staging.exists())

        with self.assertRaises(ArtifactError):
            ArtifactWriter(self.paths, run_id).start()
        self.assertTrue(writer.target.exists())
        self.assertFalse(writer.journal.exists())
        rows = [json.loads(line) for line in writer.results.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([row["run_id"] for row in rows], [run_id])

    def test_recovery_rejects_artifact_changes_after_crash(self) -> None:
        from unittest import mock

        run_id = "20260809-000000038-tb-rondo-r1"
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json("result.json", {"ok": True})
        with mock.patch("rondo_eval.artifacts._atomic_replace_index", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                writer.finalize(self._record(run_id), secrets=())
        (writer.target / "result.json").write_text('{"ok":false}\n', encoding="utf-8")

        next_id = "20260809-000000039-tb-rondo-r1"
        with self.assertRaisesRegex(ArtifactError, "differs from its publication journal"):
            ArtifactWriter(self.paths, next_id).start()
        self.assertFalse(writer.results.exists())
        self.assertTrue(writer.journal.exists())

    def test_subprocess_crashes_recover_old_or_new_complete_index(self) -> None:
        crash_script = r'''
import json
import os
import signal
import sys
from pathlib import Path

from rondo_eval import artifacts
from rondo_eval.artifacts import ArtifactWriter
from rondo_eval.config import RepoPaths

root = Path(sys.argv[1])
run_id = sys.argv[2]
point = sys.argv[3]
record = json.loads((root / "record.json").read_text(encoding="utf-8"))

if point == "after-journal":
    original = ArtifactWriter._write_journal
    def crash(self, *args, **kwargs):
        original(self, *args, **kwargs)
        os.kill(os.getpid(), signal.SIGKILL)
    ArtifactWriter._write_journal = crash
elif point == "partial-index":
    def crash(path, contents, temporary_name):
        temporary = path.parent / temporary_name
        descriptor = artifacts._open_new_regular_file(temporary, 0o644)
        os.write(descriptor, contents[:13])
        os.fsync(descriptor)
        os.close(descriptor)
        os.kill(os.getpid(), signal.SIGKILL)
    artifacts._atomic_replace_index = crash
elif point == "after-index":
    original = artifacts._atomic_replace_index
    def crash(path, contents, temporary_name):
        original(path, contents, temporary_name)
        os.kill(os.getpid(), signal.SIGKILL)
    artifacts._atomic_replace_index = crash
else:
    raise AssertionError(point)

writer = ArtifactWriter(RepoPaths(root, root), run_id).start()
writer.write_json("result.json", {"ok": True})
writer.finalize(record, secrets=())
raise AssertionError("crash point was not reached")
'''
        for number, point in enumerate(
            ("after-journal", "partial-index", "after-index"), start=40
        ):
            with self.subTest(point=point):
                root = self.paths.common_root / point
                root.mkdir()
                run_id = f"20260809-0000000{number}-tb-rondo-r1"
                (root / "record.json").write_text(
                    json.dumps(self._record(run_id)), encoding="utf-8"
                )
                environment = dict(os.environ)
                environment["PYTHONPATH"] = str(EVAL_ROOT)
                completed = subprocess.run(
                    [sys.executable, "-c", crash_script, str(root), run_id, point],
                    env=environment,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, -signal.SIGKILL, completed.stderr)

                paths = RepoPaths(root, root)
                with self.assertRaises(ArtifactError):
                    ArtifactWriter(paths, run_id).start()
                results = root / "eval/results/runs.jsonl"
                rows = [json.loads(line) for line in results.read_text().splitlines()]
                self.assertEqual([row["run_id"] for row in rows], [run_id])
                self.assertTrue((root / "eval-data/runs" / run_id / "result.json").is_file())
                self.assertFalse((root / "eval-data/runs" / f".{run_id}.publish.json").exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_symlinked_run_ancestor_fails_closed_before_write(self) -> None:
        run_id = "20260809-000000011-tb-rondo-r1"
        redirected = self.paths.common_root / "redirected"
        redirected.mkdir()
        os.symlink(redirected, self.paths.common_root / "eval-data", target_is_directory=True)
        with self.assertRaises(ArtifactError):
            ArtifactWriter(self.paths, run_id).start()
        self.assertEqual(list(redirected.iterdir()), [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_symlinked_result_or_lock_fails_closed_before_publication(self) -> None:
        for number, unsafe_name in ((12, "runs.jsonl"), (13, "runs.jsonl.lock")):
            with self.subTest(unsafe_name=unsafe_name):
                root = self.paths.common_root / f"case-{number}"
                root.mkdir()
                paths = RepoPaths(root, root)
                run_id = f"20260809-0000000{number}-tb-rondo-r1"
                writer = ArtifactWriter(paths, run_id)
                writer.results.parent.mkdir(parents=True)
                redirect = root / "redirect"
                redirect.write_text("unchanged", encoding="utf-8")
                os.symlink(redirect, writer.results.parent / unsafe_name)
                with self.assertRaises(ArtifactError):
                    writer.start()
                self.assertEqual(redirect.read_text(encoding="utf-8"), "unchanged")
                self.assertFalse(writer.target.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks are unavailable")
    def test_symlinked_result_ancestor_fails_closed_before_publication(self) -> None:
        root = self.paths.common_root / "result-ancestor"
        root.mkdir()
        paths = RepoPaths(root, root)
        run_id = "20260809-000000014-tb-rondo-r1"
        redirect = root / "redirect"
        redirect.mkdir()
        os.symlink(redirect, root / "eval", target_is_directory=True)
        with self.assertRaises(ArtifactError):
            ArtifactWriter(paths, run_id).start()
        self.assertEqual(list(redirect.iterdir()), [])
        self.assertFalse((root / "eval-data/runs" / run_id).exists())

    def test_results_can_be_explicitly_written_to_development_worktree(self) -> None:
        common = self.paths.common_root
        measurement = common / ".claude/worktrees/measurement"
        development = common / ".claude/worktrees/development"
        measurement.mkdir(parents=True)
        development.mkdir(parents=True)
        paths = RepoPaths(common, measurement)
        run_id = "20260809-000000014-tb-rondo-r1"
        writer = ArtifactWriter(paths, run_id, results_worktree_root=development).start()
        writer.write_json("result.json", {"ok": True})
        writer.finalize(self._record(run_id), secrets=())
        self.assertTrue((development / "eval/results/runs.jsonl").is_file())
        self.assertFalse((measurement / "eval/results/runs.jsonl").exists())

    def test_results_worktree_outside_common_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as outside:
            run_id = "20260809-000000015-tb-rondo-r1"
            with self.assertRaises(ArtifactError):
                ArtifactWriter(self.paths, run_id, results_worktree_root=Path(outside)).start()

    def test_invalid_completed_records_are_rejected(self) -> None:
        invalid_changes = (
            {"config": {}},
            {"summary": {}},
            {"tasks": []},
            {"tasks": [{}]},
            {"cost": {"estimated_usd": -0.01, "actual_usd": 0.0}},
            {"created_at": "2026-08-09T00:00:00"},
            {"track": "anything"},
            {"side": "anything"},
            {"metrics": None},
            {
                "metrics": {
                    "wall_seconds": 1.0,
                    "cpu_user_seconds": 0.5,
                    "cpu_system_seconds": 0.25,
                    "peak_rss_bytes": 0,
                    "exit_code": 0,
                }
            },
        )
        for number, changes in enumerate(invalid_changes, start=16):
            with self.subTest(changes=changes):
                run_id = f"20260809-0000000{number}-tb-rondo-r1"
                writer = ArtifactWriter(self.paths, run_id).start()
                writer.write_json("result.json", {"ok": True})
                record = self._record(run_id)
                record.update(changes)
                with self.assertRaises(ArtifactError):
                    writer.finalize(record, secrets=())

    def test_completed_record_allows_unknown_actual_cost_but_requires_estimate(
        self,
    ) -> None:
        run_id = "20260809-000000012-tb-rondo-r1"
        record = self._record(run_id)
        record["cost"] = {"estimated_usd": 0.125, "actual_usd": None}
        writer = ArtifactWriter(self.paths, run_id).start()
        writer.write_json("result.json", {"ok": True})
        writer.finalize(record, secrets=())

        missing_estimate = self._record("20260809-000000013-tb-rondo-r1")
        missing_estimate["cost"] = {"estimated_usd": None, "actual_usd": None}
        writer = ArtifactWriter(self.paths, missing_estimate["run_id"]).start()
        writer.write_json("result.json", {"ok": True})
        with self.assertRaises(ArtifactError):
            writer.finalize(missing_estimate, secrets=())


if __name__ == "__main__":
    unittest.main()
