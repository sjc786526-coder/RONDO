from __future__ import annotations

import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.config import (  # noqa: E402
    ConfigError,
    RepoPaths,
    load_provider_secret,
    load_runtime_config,
    make_run_spec,
)
from rondo_eval.contracts import BinaryManifest, Side  # noqa: E402


PAID_EVAL_CONFIG = """\
[paid_eval]
active_provider = "relay"
main_model = "sol"
guardian_model = "luna"
main_reasoning_effort = "medium"
guardian_reasoning_effort = "low"
max_attempts = 5
retry_backoff_seconds = 1.0

[paid_eval.providers.relay]
display_name = "Test relay"
api = "responses"
base_url = "https://relay.example/v1"
api_key_env = "OPENAI_API_KEY"
unbilled_retry_statuses = [429, 500, 502, 503, 504]

[paid_eval.providers.official]
display_name = "Test official endpoint"
api = "responses"
base_url = "https://official.example/v1"
api_key_env = "OFFICIAL_API_KEY"
unbilled_retry_statuses = [429, 500, 502, 503, 504]

[paid_eval.models.sol]
model_id = "test-sol-model"
input_usd_per_million = "5.00"
cached_input_usd_per_million = "0.50"
output_usd_per_million = "30.00"
long_context_threshold_tokens = 272000
long_context_input_multiplier = "2"
long_context_output_multiplier = "1.5"
cache_write_input_multiplier = "1.25"
price_snapshot_date = "2026-08-10"
price_source_url = "https://developers.openai.com/api/docs/models/compare"

[paid_eval.models.luna]
model_id = "test-luna-model"
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


class ConfigHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = RepoPaths(root, root)
        (root / "rondo.secrets.example.env").write_text(
            "OPENAI_API_KEY=\nOFFICIAL_API_KEY=\nRONDO_LOCAL_MODEL_API_KEY=\n",
            encoding="utf-8",
        )
        (root / "rondo.local.toml").write_text(
            PAID_EVAL_CONFIG, encoding="utf-8"
        )
        (root / ".env.local").write_text(
            "OPENAI_API_KEY=test-secret\nRONDO_LOCAL_MODEL_API_KEY=\n", encoding="utf-8"
        )
        os.chmod(root / ".env.local", 0o600)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_factory_projects_provider_and_source_hash(self) -> None:
        config = load_runtime_config(self.paths)
        binary = BinaryManifest(
            path="eval-data/bin/codex",
            sha256="a" * 64,
            code_mode_host_path="eval-data/bin/codex-code-mode-host",
            code_mode_host_sha256="e" * 64,
            bwrap_path="eval-data/bin/codex-resources/bwrap",
            bwrap_sha256="f" * 64,
            bwrap_asset_url=(
                "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
                "bwrap-x86_64-unknown-linux-musl.tar.gz"
            ),
            bwrap_archive_sha256="1" * 64,
            bwrap_source_tree_sha256="2" * 64,
            source_commit="b" * 40,
            source_dirty=False,
            rust_toolchain="rustc 1.95.0",
            build_command=("cargo", "build", "--bin", "codex"),
            code_mode_host_build_command=(
                "cargo", "build", "--bin", "codex-code-mode-host"
            ),
        )
        spec = make_run_spec(
            config,
            side=Side.CODEX,
            batch_id="p1",
            task_id="fix-git",
            task_image_digest=f"sha256:{'c' * 64}",
            binary=binary,
            terminal_bench_version="harbor-v0.20.0",
        )
        self.assertEqual(spec.provider.config_sha256, config.source_sha256)
        self.assertEqual(spec.provider.config_source, "rondo.local.toml")
        self.assertEqual(spec.provider.provider_id, "relay")
        self.assertEqual(spec.provider.main_model, "test-sol-model")
        self.assertEqual(spec.provider.main_effort, "medium")
        self.assertEqual(spec.provider.guardian_model, "test-luna-model")
        self.assertEqual(spec.provider.max_attempts, 5)
        self.assertEqual(
            spec.provider.unbilled_retry_statuses, (429, 500, 502, 503, 504)
        )
        self.assertEqual(
            spec.provider.main_pricing.input_usd_per_million, Decimal("5.00")
        )
        self.assertNotEqual(spec.provider.profile_sha256, config.source_sha256)
        self.assertIs(spec.code_mode_host, True)
        self.assertIs(spec.sandbox_network_access, True)

    def test_active_provider_is_the_only_secret_and_projection_selection(self) -> None:
        config = load_runtime_config(self.paths)
        self.assertEqual(
            load_provider_secret(config),
            ("OPENAI_API_KEY", "test-secret"),
        )
        self.assertEqual(
            load_provider_secret(config, "relay"),
            ("OPENAI_API_KEY", "test-secret"),
        )
        with self.assertRaises(ConfigError):
            load_provider_secret(config, "official")
        with self.assertRaises(ConfigError):
            config.paid_provider_projection("official")

    def test_profile_hash_is_canonical_and_changes_with_selection(self) -> None:
        first = load_runtime_config(self.paths).paid_provider_projection()
        canonical_equivalent = PAID_EVAL_CONFIG.replace(
            "retry_backoff_seconds = 1.0", "retry_backoff_seconds = 1"
        ).replace(
            'input_usd_per_million = "5.00"',
            'input_usd_per_million = "5.0"',
            1,
        ).replace(
            "unbilled_retry_statuses = [429, 500, 502, 503, 504]",
            "unbilled_retry_statuses = [504, 503, 502, 500, 429]",
            1,
        )
        (self.paths.common_root / "rondo.local.toml").write_text(
            canonical_equivalent, encoding="utf-8"
        )
        equivalent = load_runtime_config(self.paths).paid_provider_projection()
        self.assertEqual(first.profile_sha256, equivalent.profile_sha256)
        switched = canonical_equivalent.replace(
            'active_provider = "relay"', 'active_provider = "official"'
        )
        (self.paths.common_root / "rondo.local.toml").write_text(
            switched, encoding="utf-8"
        )
        selected = load_runtime_config(self.paths).paid_provider_projection()
        self.assertNotEqual(first.profile_sha256, selected.profile_sha256)
        self.assertEqual(selected.provider_id, "official")

        for original, changed in (
            (
                'main_reasoning_effort = "medium"',
                'main_reasoning_effort = "high"',
            ),
            (
                "long_context_threshold_tokens = 272000",
                "long_context_threshold_tokens = 272001",
            ),
            (
                'long_context_input_multiplier = "2"',
                'long_context_input_multiplier = "3"',
            ),
            (
                'long_context_output_multiplier = "1.5"',
                'long_context_output_multiplier = "2"',
            ),
            (
                'cache_write_input_multiplier = "1.25"',
                'cache_write_input_multiplier = "1.1"',
            ),
        ):
            with self.subTest(changed=changed):
                (self.paths.common_root / "rondo.local.toml").write_text(
                    canonical_equivalent.replace(original, changed, 1),
                    encoding="utf-8",
                )
                repriced = load_runtime_config(
                    self.paths
                ).paid_provider_projection()
                self.assertNotEqual(first.profile_sha256, repriced.profile_sha256)

    def test_unknown_env_name_and_shell_expansion_are_rejected(self) -> None:
        config = load_runtime_config(self.paths)
        (self.paths.common_root / ".env.local").write_text(
            "OPENAI_API_KEY=test-secret\nUNTRACKED_KEY=value\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_provider_secret(config)
        (self.paths.common_root / ".env.local").write_text(
            "OPENAI_API_KEY=$(command)\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_provider_secret(config)

    def test_toml_schema_rejects_secret_aliases_and_unknown_tables(self) -> None:
        for extra in ('token = "secret"\n', 'openai_api_key = "secret"\n'):
            (self.paths.common_root / "rondo.local.toml").write_text(
                PAID_EVAL_CONFIG + extra, encoding="utf-8"
            )
            with self.assertRaises(ConfigError):
                load_runtime_config(self.paths)
        (self.paths.common_root / "rondo.local.toml").write_text(
            PAID_EVAL_CONFIG + "\n[unexpected]\nvalue = 1\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_runtime_config(self.paths)

    def test_retry_and_model_metadata_fail_closed(self) -> None:
        invalid_configs = (
            PAID_EVAL_CONFIG.replace(
                'main_reasoning_effort = "medium"',
                'main_reasoning_effort = "ultra"',
            ),
            PAID_EVAL_CONFIG.replace("max_attempts = 5", "max_attempts = 0"),
            PAID_EVAL_CONFIG.replace("max_attempts = 5", "max_attempts = 6"),
            PAID_EVAL_CONFIG.replace(
                "retry_backoff_seconds = 1.0", "retry_backoff_seconds = -1.0"
            ),
            PAID_EVAL_CONFIG.replace(
                "unbilled_retry_statuses = [429, 500, 502, 503, 504]",
                "unbilled_retry_statuses = [302]",
                1,
            ),
            PAID_EVAL_CONFIG.replace(
                "unbilled_retry_statuses = [429, 500, 502, 503, 504]",
                "unbilled_retry_statuses = [429, 429]",
                1,
            ),
            PAID_EVAL_CONFIG.replace(
                'price_snapshot_date = "2026-08-10"',
                'price_snapshot_date = "2026-8-10"',
                1,
            ),
            PAID_EVAL_CONFIG.replace(
                'price_source_url = "https://developers.openai.com/api/docs/models/compare"',
                'price_source_url = "https://prices.example/models"',
                1,
            ),
            PAID_EVAL_CONFIG.replace(
                'input_usd_per_million = "5.00"',
                "input_usd_per_million = 5.00",
                1,
            ),
            PAID_EVAL_CONFIG.replace(
                "long_context_threshold_tokens = 272000",
                "long_context_threshold_tokens = 0",
                1,
            ),
            PAID_EVAL_CONFIG.replace(
                'long_context_input_multiplier = "2"',
                "long_context_input_multiplier = 2",
                1,
            ),
            PAID_EVAL_CONFIG.replace(
                'cache_write_input_multiplier = "1.25"',
                'cache_write_input_multiplier = "0"',
                1,
            ),
            PAID_EVAL_CONFIG.replace(
                'active_provider = "relay"', 'active_provider = "missing"'
            ),
        )
        for value in invalid_configs:
            with self.subTest(value=value):
                (self.paths.common_root / "rondo.local.toml").write_text(
                    value, encoding="utf-8"
                )
                with self.assertRaises(ConfigError):
                    load_runtime_config(self.paths)

    def test_tracked_allowlist_cannot_contain_a_secret_value(self) -> None:
        (self.paths.common_root / "rondo.secrets.example.env").write_text(
            "OPENAI_API_KEY=not-empty\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_runtime_config(self.paths)

    def test_worktree_owns_tracked_allowlist_while_common_root_owns_local_data(self) -> None:
        common = self.paths.common_root / "common"
        worktree = self.paths.common_root / "worktree"
        common.mkdir()
        worktree.mkdir()
        (common / "rondo.local.toml").write_text(PAID_EVAL_CONFIG, encoding="utf-8")
        (common / ".env.local").write_text(
            "OPENAI_API_KEY=test-secret\n", encoding="utf-8"
        )
        os.chmod(common / ".env.local", 0o600)
        (worktree / "rondo.secrets.example.env").write_text(
            "OPENAI_API_KEY=\nOFFICIAL_API_KEY=\n", encoding="utf-8"
        )

        config = load_runtime_config(RepoPaths(common, worktree))

        self.assertEqual(load_provider_secret(config), ("OPENAI_API_KEY", "test-secret"))


if __name__ == "__main__":
    unittest.main()
