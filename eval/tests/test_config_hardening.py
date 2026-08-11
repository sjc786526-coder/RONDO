from __future__ import annotations

import os
import sys
import tempfile
import unittest
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


OPENAI_CONFIG = """\
[providers.openai]
api = "responses"
base_url = "https://provider.example/v1"
api_key_env = "OPENAI_API_KEY"
main_model = "gpt-5.6-sol"
guardian_model = "gpt-5.6-luna"
guardian_reasoning_effort = "low"
"""


class ConfigHardeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.paths = RepoPaths(root, root)
        (root / "rondo.secrets.example.env").write_text(
            "OPENAI_API_KEY=\nRONDO_LOCAL_MODEL_API_KEY=\n", encoding="utf-8"
        )
        (root / "rondo.local.toml").write_text(OPENAI_CONFIG, encoding="utf-8")
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
        self.assertIs(spec.code_mode_host, True)
        self.assertIs(spec.sandbox_network_access, True)

    def test_unknown_env_name_and_shell_expansion_are_rejected(self) -> None:
        config = load_runtime_config(self.paths)
        (self.paths.common_root / ".env.local").write_text(
            "OPENAI_API_KEY=test-secret\nUNTRACKED_KEY=value\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_provider_secret(config, "openai")
        (self.paths.common_root / ".env.local").write_text(
            "OPENAI_API_KEY=$(command)\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_provider_secret(config, "openai")

    def test_toml_schema_rejects_secret_aliases_and_unknown_tables(self) -> None:
        for extra in ('token = "secret"\n', 'openai_api_key = "secret"\n'):
            (self.paths.common_root / "rondo.local.toml").write_text(
                OPENAI_CONFIG + extra, encoding="utf-8"
            )
            with self.assertRaises(ConfigError):
                load_runtime_config(self.paths)
        (self.paths.common_root / "rondo.local.toml").write_text(
            OPENAI_CONFIG + "\n[unexpected]\nvalue = 1\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_runtime_config(self.paths)

    def test_tracked_allowlist_cannot_contain_a_secret_value(self) -> None:
        (self.paths.common_root / "rondo.secrets.example.env").write_text(
            "OPENAI_API_KEY=not-empty\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_runtime_config(self.paths)


if __name__ == "__main__":
    unittest.main()
