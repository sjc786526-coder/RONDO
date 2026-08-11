from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from rondo_eval.model_cli_diagnostic import (
    MAX_RETRIES_PER_MODEL,
    MODEL_CAMPAIGN_CAP_USD,
    PHASES,
    SHORT_REQUEST_RESERVATION_USD,
    DEFAULT_GUARDIAN_ALIAS,
    SUPPORTED_MAIN_ALIASES,
    BinaryTarget,
    Phase,
    _catalog_with_auto_review_override,
    _codex_command,
    _diagnostic_retryable,
    _max_attempts_for_retry_budget,
    _outer_retry_delay_seconds,
    _phase_succeeded,
    _redacted_cli_observation,
    _remove_generated_plugin_cache,
    _safe_environment,
)


class ModelCliDiagnosticTests(unittest.TestCase):
    def test_frozen_codex_runs_before_rondo(self) -> None:
        self.assertEqual(
            [phase.name for phase in PHASES],
            ["codex-main", "codex-approval", "rondo-main", "rondo-approval"],
        )
        self.assertEqual(MAX_RETRIES_PER_MODEL, 25)
        self.assertEqual(str(MODEL_CAMPAIGN_CAP_USD * 2), "300")
        self.assertEqual(str(SHORT_REQUEST_RESERVATION_USD), "1")
        self.assertEqual(SUPPORTED_MAIN_ALIASES, ("luna", "terra", "sol"))
        self.assertEqual(DEFAULT_GUARDIAN_ALIAS, "luna")
        self.assertEqual(
            [phase.name for phase in PHASES if phase.side == "rondo"],
            ["rondo-main", "rondo-approval"],
        )
        self.assertEqual(
            [
                phase.name
                for phase in PHASES
                if phase.side == "rondo" and phase.kind == "approval"
            ],
            ["rondo-approval"],
        )

    def test_command_uses_real_cli_shape_without_rondo_only_overrides_for_codex(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = BinaryTarget("codex", Path(directory) / "codex", "a" * 64, "b" * 40)
            command = _codex_command(
                target,
                base_url="http://127.0.0.1:43210/v1",
                phase=Phase("codex", "approval"),
                main_model="gpt-5.6-terra",
                guardian_model="gpt-5.6-luna",
                model_catalog_json=Path(directory) / "models.json",
            )
        joined = "\n".join(command)
        self.assertIn("--strict-config", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--enable", command)
        self.assertIn("unified_exec", command)
        self.assertIn('model_reasoning_effort="medium"', command)
        self.assertIn('service_tier="default"', command)
        self.assertNotIn("disable_response_storage", joined)
        self.assertIn("request_max_retries=0", joined)
        self.assertIn("stream_max_retries=0", joined)
        self.assertNotIn("auto_review.model", joined)
        self.assertIn("model_catalog_json=", joined)
        self.assertNotIn("auto_review.reasoning_effort", joined)
        self.assertIn('sandbox_mode="read-only"', command)
        self.assertIn("touch guardian-approved.tmp", joined)
        self.assertIn('"sandbox_permissions":"require_escalated"', joined)

    def test_rondo_command_uses_selected_main_and_guardian(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = BinaryTarget("rondo", Path(directory) / "codex", "a" * 64, "b" * 40)
            command = _codex_command(
                target,
                base_url="http://127.0.0.1:43210/v1",
                phase=Phase("rondo", "approval"),
                main_model="gpt-5.6-terra",
                guardian_model="gpt-5.6-sol",
            )
        joined = "\n".join(command)
        self.assertIn("gpt-5.6-terra", command)
        self.assertIn('auto_review.model="gpt-5.6-sol"', command)
        self.assertIn('auto_review.reasoning_effort="low"', command)
        self.assertNotIn("model_catalog_json", joined)
        self.assertIn('"sandbox_permissions":"require_escalated"', joined)

    def test_success_requires_guardian_usage_for_approval(self) -> None:
        run_id = "run"
        requests = [
            {
                "request_id": request_id,
                "role": role,
                "role_provenance": "declared",
                "declared_role": role,
                "inferred_role": role,
                "contract_match": True,
                "usage_valid": True,
                "attempt_count": 1,
                "settlement_kind": "usage_priced",
            }
            for request_id, role in (
                ("main-before", "main"),
                ("guardian", "guardian"),
                ("main-after", "main"),
            )
        ]
        snapshot = {
            "reserved_usd": "0.000000",
            "runs": {
                run_id: {
                    "requests": {
                        request["request_id"]: {
                            "status": "settled",
                            "usage_valid": True,
                            "attempt_count": 1,
                            "settlement_kind": "usage_priced",
                        }
                        for request in requests
                    }
                }
            },
        }
        self.assertTrue(
            _phase_succeeded(
                Phase("codex", "approval"),
                returncode=0,
                snapshot=snapshot,
                run_id=run_id,
                requests=requests,
            )
        )
        self.assertFalse(
            _phase_succeeded(
                Phase("codex", "approval"),
                returncode=0,
                snapshot=snapshot,
                run_id=run_id,
                requests=requests[:-1],
            )
        )
        invalid = [dict(request) for request in requests]
        invalid[1]["contract_match"] = False
        self.assertFalse(
            _phase_succeeded(
                Phase("codex", "approval"),
                returncode=0,
                snapshot=snapshot,
                run_id=run_id,
                requests=invalid,
            )
        )

    def test_frozen_catalog_overrides_guardian_without_modifying_source(self) -> None:
        source = {
            "models": [
                {"slug": "gpt-5.6-sol", "auto_review_model_override": None},
                {"slug": "gpt-5.6-luna", "auto_review_model_override": None},
            ]
        }
        projected = _catalog_with_auto_review_override(
            source,
            main_model="gpt-5.6-sol",
            guardian_model="gpt-5.6-sol",
        )
        self.assertEqual(len(projected["models"]), 1)
        self.assertEqual(
            projected["models"][0]["auto_review_model_override"],
            "gpt-5.6-sol",
        )
        self.assertIsNone(source["models"][0]["auto_review_model_override"])

    def test_task_authorization_allows_unknown_failure_retry_after_full_debit(self) -> None:
        self.assertTrue(
            _diagnostic_retryable(
                success=False,
                snapshot={"reserved_usd": "0.000000"},
                states=[{"settlement_kind": "conservative_reservation"}],
            )
        )
        self.assertTrue(
            _diagnostic_retryable(
                success=False,
                snapshot={"reserved_usd": "0.000000"},
                states=[{"settlement_kind": "usage_priced"}],
            )
        )
        self.assertFalse(
            _diagnostic_retryable(
                success=False,
                snapshot={"reserved_usd": "5.000000"},
                states=[{"settlement_kind": "conservative_reservation"}],
            )
        )

    def test_outer_retry_backoff_is_bounded(self) -> None:
        self.assertEqual(
            [_outer_retry_delay_seconds(value) for value in range(7)],
            [5, 10, 20, 40, 60, 60, 60],
        )
        with self.assertRaisesRegex(Exception, "retry count"):
            _outer_retry_delay_seconds(-1)

    def test_proxy_attempts_are_bounded_by_remaining_campaign_retries(self) -> None:
        self.assertEqual(
            _max_attempts_for_retry_budget(
                provider_max_attempts=5,
                retry_count=24,
                max_retries=25,
                phase_attempt=0,
            ),
            2,
        )
        self.assertEqual(
            _max_attempts_for_retry_budget(
                provider_max_attempts=5,
                retry_count=24,
                max_retries=25,
                phase_attempt=1,
            ),
            1,
        )
        self.assertEqual(
            _max_attempts_for_retry_budget(
                provider_max_attempts=5,
                retry_count=25,
                max_retries=25,
                phase_attempt=1,
            ),
            0,
        )

    def test_short_canary_retry_limit_is_accepted_by_campaign_contract(self) -> None:
        self.assertGreaterEqual(MAX_RETRIES_PER_MODEL, 5)
        self.assertFalse(
            _diagnostic_retryable(
                success=True,
                snapshot={"reserved_usd": "0.000000"},
                states=[{"settlement_kind": "usage_priced"}],
            )
        )

    def test_cli_observation_does_not_persist_text_or_command_output(self) -> None:
        observation = _redacted_cli_observation(
            b'{"type":"item.started","item":{"id":"cmd-1",'
            b'"type":"command_execution","command":"/bin/bash -lc '
            b"'touch guardian-approved.tmp'\",\"status\":\"in_progress\"}}\n"
            b'{"type":"item.completed","item":{"type":"command_execution",'
            b'"id":"cmd-1","command":"/bin/bash -lc '
            b"'touch guardian-approved.tmp'\",\"aggregated_output\":\"private\","
            b'"exit_code":0,"status":"completed"}}\n'
            b'{"type":"item.completed","item":{"type":"agent_message",'
            b'"text":"private response"}}\n',
            expected_final_message="private response",
        )
        self.assertEqual(
            observation["command_events"][0]["expected_command"], True
        )
        encoded = str(observation)
        self.assertNotIn("private", encoded)
        self.assertNotIn("guardian-approved.tmp", encoded)
        self.assertIs(observation["exact_final_message"], True)
        self.assertIs(observation["approval_command_succeeded"], True)

    def test_cli_observation_rejects_extra_message_or_incomplete_command(self) -> None:
        extra_message = _redacted_cli_observation(
            b'{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}\n'
            b'{"type":"item.completed","item":{"type":"agent_message","text":"ERROR"}}\n',
            expected_final_message="OK",
        )
        self.assertIs(extra_message["exact_final_message"], False)
        incomplete = _redacted_cli_observation(
            b'{"type":"item.completed","item":{"id":"cmd-1",'
            b'"type":"command_execution","command":"touch guardian-approved.tmp",'
            b'"status":"completed","exit_code":1}}\n',
            expected_final_message=None,
        )
        self.assertIs(incomplete["approval_command_succeeded"], False)

    def test_child_environment_is_an_explicit_nonsecret_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "secret",
                "ANTHROPIC_API_KEY": "secret",
                "AWS_SECRET_ACCESS_KEY": "secret",
                "HTTP_PROXY": "http://proxy.example",
                "CUSTOM_TOKEN": "secret",
            },
            clear=False,
        ):
            environment = _safe_environment(Path(directory))
        self.assertEqual(
            set(environment),
            {"CODEX_HOME", "HOME", "PATH", "LANG", "LC_ALL", "NO_PROXY", "no_proxy"},
        )
        self.assertFalse(any("secret" in value for value in environment.values()))
        self.assertEqual(environment["NO_PROXY"], "127.0.0.1,localhost")

    def test_generated_plugin_cache_cleanup_is_narrow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            cache = codex_home / ".tmp" / "plugins"
            clone = codex_home / ".tmp" / "plugins-clone-test"
            retained = codex_home / ".tmp" / "retained"
            evidence = codex_home / "sessions" / "receipt.json"
            cache.mkdir(parents=True)
            clone.mkdir()
            evidence.parent.mkdir()
            (cache / "discarded").write_text("cache", encoding="utf-8")
            (clone / "discarded").write_text("cache", encoding="utf-8")
            retained.write_text("keep", encoding="utf-8")
            evidence.write_text("evidence", encoding="utf-8")

            _remove_generated_plugin_cache(codex_home)

            self.assertFalse(cache.exists())
            self.assertFalse(clone.exists())
            self.assertEqual(retained.read_text(encoding="utf-8"), "keep")
            self.assertEqual(evidence.read_text(encoding="utf-8"), "evidence")


if __name__ == "__main__":
    unittest.main()
