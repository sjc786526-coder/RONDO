from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import (  # noqa: E402
    BinaryManifest,
    ContractError,
    ModelPricing,
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
    main_pricing = ModelPricing(
        model_id="test-main-model",
        input_usd_per_million=Decimal("5.00"),
        cached_input_usd_per_million=Decimal("0.50"),
        output_usd_per_million=Decimal("30.00"),
        long_context_threshold_tokens=272_000,
        long_context_input_multiplier=Decimal("2"),
        long_context_output_multiplier=Decimal("1.5"),
        cache_write_input_multiplier=Decimal("1.25"),
        price_snapshot_date="2026-08-10",
        price_source_url="https://developers.openai.com/api/docs/models/compare",
    )
    guardian_pricing = ModelPricing(
        model_id="test-guardian-model",
        input_usd_per_million=Decimal("0.20"),
        cached_input_usd_per_million=Decimal("0.02"),
        output_usd_per_million=Decimal("1.20"),
        long_context_threshold_tokens=272_000,
        long_context_input_multiplier=Decimal("2"),
        long_context_output_multiplier=Decimal("1.5"),
        cache_write_input_multiplier=Decimal("1.25"),
        price_snapshot_date="2026-08-10",
        price_source_url="https://developers.openai.com/api/docs/models/compare",
    )
    provider = ProviderProjection(
        provider_id="relay",
        display_name="Test relay",
        api="responses",
        base_url="https://relay.example/v1",
        api_key_env="OPENAI_API_KEY",
        main_model=main_pricing.model_id,
        main_effort="medium",
        guardian_model=guardian_pricing.model_id,
        guardian_effort="low",
        main_pricing=main_pricing,
        guardian_pricing=guardian_pricing,
        max_attempts=5,
        retry_backoff_seconds=1.0,
        unbilled_retry_statuses=(429, 500, 502, 503, 504),
        profile_sha256="3" * 64,
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

    def test_provider_attempts_backoff_and_statuses_are_strict(self) -> None:
        for valid in (1, 5):
            with self.subTest(valid=valid):
                spec = _spec()
                object.__setattr__(spec.provider, "max_attempts", valid)
                spec.validate()

        for field, invalid_values in (
            ("max_attempts", (False, 0, 1.0, 6)),
            ("retry_backoff_seconds", (False, -1, float("nan"), float("inf"), 31)),
            (
                "unbilled_retry_statuses",
                ([429], (302,), (429, 429), (500, 429), (True,)),
            ),
        ):
            for invalid in invalid_values:
                with self.subTest(field=field, invalid=invalid):
                    spec = _spec()
                    object.__setattr__(spec.provider, field, invalid)
                    with self.assertRaises(ContractError):
                        spec.validate()

    def test_model_pricing_requires_decimal_rates_and_official_snapshot(self) -> None:
        mutations = (
            ("input_usd_per_million", 5.0),
            ("input_usd_per_million", Decimal("NaN")),
            ("long_context_threshold_tokens", False),
            ("long_context_threshold_tokens", 0),
            ("long_context_input_multiplier", 2.0),
            ("long_context_output_multiplier", Decimal("0")),
            ("cache_write_input_multiplier", Decimal("NaN")),
            ("price_snapshot_date", "2026-8-10"),
            ("price_source_url", "http://developers.openai.com/api/docs/models/compare"),
            ("price_source_url", "https://prices.example/models"),
        )
        for field, invalid in mutations:
            with self.subTest(field=field, invalid=invalid):
                spec = _spec()
                object.__setattr__(spec.provider.main_pricing, field, invalid)
                with self.assertRaises(ContractError):
                    spec.validate()


if __name__ == "__main__":
    unittest.main()
