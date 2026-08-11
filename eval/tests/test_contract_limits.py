from __future__ import annotations

import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import (  # noqa: E402
    BinaryManifest,
    ContractError,
    ProviderProjection,
    RunSpec,
    Side,
)


def _spec() -> RunSpec:
    binary = BinaryManifest(
        path="eval-data/bin/codex",
        sha256="a" * 64,
        code_mode_host_path="eval-data/bin/codex-code-mode-host",
        code_mode_host_sha256="b" * 64,
        bwrap_path="eval-data/bin/codex-resources/bwrap",
        bwrap_sha256="c" * 64,
        source_commit="d" * 40,
        source_dirty=False,
        rust_toolchain="rustc 1.95.0",
        build_command=("cargo", "build", "--bin", "codex"),
        code_mode_host_build_command=(
            "cargo",
            "build",
            "--bin",
            "codex-code-mode-host",
        ),
        bwrap_asset_url=(
            "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
            "bwrap-x86_64-unknown-linux-musl.tar.gz"
        ),
        bwrap_archive_sha256="e" * 64,
        bwrap_source_tree_sha256="f" * 64,
    )
    provider = ProviderProjection(
        provider_id="openai",
        api="responses",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        main_model="gpt-5.6-sol",
        guardian_model="gpt-5.6-luna",
        guardian_effort="low",
        config_sha256="1" * 64,
    )
    return RunSpec(
        side=Side.CODEX,
        batch_id="p1-contract-limits",
        task_id="fix-git",
        task_image_digest=f"sha256:{'2' * 64}",
        binary=binary,
        terminal_bench_version="terminal-bench-commit",
        provider=provider,
    )


class RunSpecLimitTests(unittest.TestCase):
    def test_timeout_accepts_only_bounded_integer_seconds(self) -> None:
        for valid in (1, 1800, 3600):
            with self.subTest(valid=valid):
                spec = _spec()
                object.__setattr__(spec, "timeout_seconds", valid)
                spec.validate()

        for invalid in (False, True, 0, -1, 1.0, float("nan"), float("inf"), 3601, 2**63):
            with self.subTest(invalid=invalid):
                spec = _spec()
                object.__setattr__(spec, "timeout_seconds", invalid)
                with self.assertRaises(ContractError):
                    spec.validate()

    def test_retries_accept_only_bounded_integers(self) -> None:
        for valid in (0, 1, 10):
            with self.subTest(valid=valid):
                spec = _spec()
                object.__setattr__(spec, "max_retries", valid)
                spec.validate()

        for invalid in (False, True, -1, 0.0, float("nan"), float("inf"), 11, 2**63):
            with self.subTest(invalid=invalid):
                spec = _spec()
                object.__setattr__(spec, "max_retries", invalid)
                with self.assertRaises(ContractError):
                    spec.validate()


if __name__ == "__main__":
    unittest.main()
