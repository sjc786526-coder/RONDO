from __future__ import annotations

import errno
import os
import tempfile
import types
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import mock

from rondo_eval.model_cli_diagnostic import (
    MAX_RETRIES_PER_MODEL,
    MODEL_CAMPAIGN_CAP_USD,
    PLAN014_CANARY_CAP_USD,
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
    _phase_budget_contract,
    _prompt,
    _redacted_cli_observation,
    _recover_unrecorded_formal_attempt,
    _remove_generated_plugin_cache,
    _safe_environment,
    _selected_campaign_phases,
    run_campaign,
)


class ModelCliDiagnosticTests(unittest.TestCase):
    def test_approval_prompt_forbids_pre_tool_assistant_message(self) -> None:
        prompt = _prompt("approval")
        self.assertIn(
            "Do not emit an assistant or commentary message before the tool call.",
            prompt,
        )
        self.assertTrue(prompt.endswith("reply with exactly DONE."))

    @staticmethod
    def _successful_approval_contract() -> tuple[
        list[dict[str, object]], dict[str, Any]
    ]:
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
        snapshot: dict[str, Any] = {
            "reserved_usd": "0.000000",
            "runs": {
                run_id: {
                    "stopped": False,
                    "stop_reason": None,
                    "requests": {
                        request["request_id"]: {
                            "status": "settled",
                            "usage_valid": True,
                            "attempt_count": 1,
                            "settlement_kind": "usage_priced",
                        }
                        for request in requests
                    },
                }
            },
        }
        return requests, snapshot

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
        requests, snapshot = self._successful_approval_contract()
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

    def test_success_rejects_a_stopped_ledger_run(self) -> None:
        requests, snapshot = self._successful_approval_contract()
        run = snapshot["runs"]["run"]
        run["stopped"] = True
        run["stop_reason"] = "guardian_logical_request_limit_exceeded"
        self.assertFalse(
            _phase_succeeded(
                Phase("codex", "approval"),
                returncode=0,
                snapshot=snapshot,
                run_id="run",
                requests=requests,
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

    def test_plan014_canary_is_exactly_frozen_codex_four_request_zero_retry_shape(self) -> None:
        phases = _selected_campaign_phases(
            start_side="codex",
            phase_kind=None,
            plan014_canary=True,
        )
        self.assertEqual(
            [phase.name for phase in phases],
            ["codex-main", "codex-approval"],
        )
        contracts = [
            _phase_budget_contract(phase, plan014_canary=True) for phase in phases
        ]
        self.assertEqual(contracts, [(1, 1), (3, 3)])
        self.assertEqual(sum((contract[0] for contract in contracts), start=0), 4)
        self.assertEqual(PLAN014_CANARY_CAP_USD, 4)

        ordinary = _selected_campaign_phases(
            start_side="rondo",
            phase_kind="approval",
            plan014_canary=False,
        )
        self.assertEqual([phase.name for phase in ordinary], ["rondo-approval"])
        self.assertEqual(
            _phase_budget_contract(ordinary[0], plan014_canary=False),
            (5, None),
        )

    def test_plan014_campaign_binds_pair_and_projects_one_plus_three_caps(self) -> None:
        provider = types.SimpleNamespace(
            profile_sha256="a" * 64,
            base_url="https://provider.example/v1",
            main_model="gpt-5.6-sol",
            guardian_model="gpt-5.6-sol",
            main_effort="medium",
            guardian_effort="low",
            max_attempts=5,
        )
        config = mock.Mock()
        config.paid_provider_projection.return_value = provider
        config.paid_eval.return_value = {
            "main_model": "sol",
            "guardian_model": "sol",
        }
        identity = mock.Mock(pair_id="p1-fix-git-pair-v19", lock_sha256="b" * 64)
        targets = {
            side: BinaryTarget(side, Path(f"/{side}"), side[0] * 64, side[0] * 40)
            for side in ("codex", "rondo")
        }
        phase_attempts = [
            {
                "phase": "codex-main",
                "spent_usd": "0.100000",
                "logical_request_count": 1,
                "upstream_attempt_count": 1,
            },
            {
                "phase": "codex-approval",
                "spent_usd": "0.200000",
                "logical_request_count": 3,
                "upstream_attempt_count": 3,
            },
        ]
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "rondo_eval.model_cli_diagnostic.load_runtime_config", return_value=config
        ), mock.patch(
            "rondo_eval.model_cli_diagnostic.load_provider_secret",
            return_value=("KEY", "secret"),
        ), mock.patch(
            "rondo_eval.model_cli_diagnostic._binary_target",
            side_effect=lambda _root, side: targets[side],
        ), mock.patch(
            "rondo_eval.model_cli_diagnostic._load_frozen_model_catalog",
            return_value={"models": []},
        ), mock.patch(
            "rondo_eval.model_cli_diagnostic._run_phase_once",
            side_effect=[
                (phase_attempts[0], True, False, 0),
                (phase_attempts[1], True, False, 0),
            ],
        ) as run_phase, mock.patch(
            "rondo_eval.terminal_bench.pair.load_active_pair_identity",
            return_value=identity,
        ):
            receipt = run_campaign(
                types.SimpleNamespace(common_root=Path(directory)),
                output_root=Path(directory) / "canary",
                main_model_alias="sol",
                guardian_model_alias="sol",
                max_retries=0,
                plan014_canary=True,
            )

        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["campaign_cap_usd"], "4")
        self.assertEqual(receipt["pair_id"], "p1-fix-git-pair-v19")
        identity.validate_selected_profile.assert_called_once_with(provider)
        self.assertEqual(run_phase.call_count, 2)
        self.assertEqual(
            [call.kwargs["max_attempts"] for call in run_phase.call_args_list],
            [1, 1],
        )
        self.assertEqual(
            [call.kwargs["run_cap_usd"] for call in run_phase.call_args_list],
            [1, 3],
        )
        self.assertEqual(
            [call.kwargs["max_logical_requests"] for call in run_phase.call_args_list],
            [1, 3],
        )

    def test_formal_canary_uses_identity_bundles_terra_efforts_and_fallback(self) -> None:
        provider = types.SimpleNamespace(
            profile_sha256="a" * 64,
            base_url="https://provider.example/v1",
            main_model="gpt-5.6-terra",
            guardian_model="gpt-5.6-terra",
            main_effort="medium",
            guardian_effort="low",
            main_pricing=object(),
            guardian_pricing=object(),
            max_attempts=5,
        )
        config = mock.Mock()
        identity = mock.Mock(
            campaign_id="p2-b7-canary-baseline-v23",
            batch_id="p2-b7-canary-v23",
            lock_sha256="b" * 64,
            bundles={
                "codex": {"manifest_path": "eval-data/bin/codex/manifest.json"},
                "rondo": {"manifest_path": "eval-data/bin/rondo/manifest.json"},
            },
            budget={
                "task_budget_cap_usd": "400.000000",
                "task_budget_prior_estimated_usd": "0.000000",
            },
            maximum_legal_request_reservation_usd=Decimal("2.000000"),
            upstream_timeout_seconds=180.0,
            max_guardian_logical_requests=3,
            product=object(),
            catalog_identity={
                "sources": [
                    {"side": "upstream", "commit": "c" * 40},
                    {"side": "rondo", "commit": "d" * 40},
                ]
            },
        )
        identity.provider_projection.return_value = provider
        targets = {
            side: BinaryTarget(side, Path(f"/{side}"), side[0] * 64, side[0] * 40)
            for side in ("codex", "rondo")
        }
        shared = mock.Mock()
        shared.to_dict.return_value = {"models": []}
        shared.identity.return_value = identity.catalog_identity
        attempts = [
            {"phase": "codex-main", "spent_usd": "0.100000"},
            {"phase": "codex-approval", "spent_usd": "0.200000"},
        ]
        with tempfile.TemporaryDirectory() as directory, mock.patch(
            "rondo_eval.model_cli_diagnostic.load_runtime_config", return_value=config
        ), mock.patch(
            "rondo_eval.model_cli_diagnostic.load_provider_secret",
            return_value=("KEY", "secret"),
        ), mock.patch(
            "rondo_eval.model_cli_diagnostic._binary_target",
            side_effect=lambda _root, side, **_kwargs: targets[side],
        ) as binary, mock.patch(
            "rondo_eval.model_cli_diagnostic.load_shared_model_catalog",
            return_value=shared,
        ), mock.patch(
            "rondo_eval.model_cli_diagnostic.maximum_usage_cost",
            return_value=Decimal("2.000000"),
        ), mock.patch(
            "rondo_eval.model_cli_diagnostic._run_phase_once",
            side_effect=[
                (attempts[0], True, False, 0),
                (attempts[1], True, False, 0),
            ],
        ) as run_phase:
            receipt = run_campaign(
                types.SimpleNamespace(common_root=Path(directory)),
                output_root=Path(directory) / "formal-wire",
                main_model_alias="terra",
                guardian_model_alias="terra",
                max_retries=3,
                formal_campaign_canary=True,
                p2_campaign_identity=identity,
            )

        self.assertEqual(receipt["status"], "completed")
        self.assertTrue(receipt["formal_campaign_canary"])
        self.assertEqual(receipt["campaign_cap_usd"], "400.000000")
        self.assertEqual(receipt["main_reasoning_effort"], "medium")
        self.assertEqual(receipt["guardian_reasoning_effort"], "low")
        self.assertEqual(binary.call_count, 2)
        self.assertEqual(
            [call.kwargs["run_cap_usd"] for call in run_phase.call_args_list],
            [Decimal("2.000000"), Decimal("6.000000")],
        )
        self.assertEqual(
            [call.kwargs["request_reservation_usd"] for call in run_phase.call_args_list],
            [Decimal("2.000000"), Decimal("2.000000")],
        )
        self.assertEqual(
            [call.kwargs["unpriced_fallback_usd"] for call in run_phase.call_args_list],
            ["1.000000", "1.000000"],
        )

    def test_formal_wire_recovers_a_created_but_unsent_attempt_at_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            attempt_root = root / "001-codex-main"
            attempt_root.mkdir()
            recovered, retry_delta = _recover_unrecorded_formal_attempt(
                root,
                attempts=[],
                request_reservation_usd=Decimal("2.000000"),
            )
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered["spent_usd"], "0.000000")
        self.assertEqual(
            recovered["settlements"][0]["settlement_kind"],
            "not_sent_unbilled",
        )
        self.assertEqual(retry_delta, 0)

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
            b'"text":"private response"}}\n'
            b'{"type":"turn.completed"}\n',
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
        self.assertIs(observation["turn_succeeded"], True)

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

    def test_cli_observation_rejects_failed_turn_and_post_message_command(self) -> None:
        completed_command = (
            b'{"type":"item.started","item":{"id":"cmd-1",'
            b'"type":"command_execution","command":"touch guardian-approved.tmp",'
            b'"status":"in_progress"}}\n'
            b'{"type":"item.completed","item":{"id":"cmd-1",'
            b'"type":"command_execution","command":"touch guardian-approved.tmp",'
            b'"status":"completed","exit_code":0}}\n'
        )
        failed = _redacted_cli_observation(
            completed_command
            + b'{"type":"item.completed","item":{"type":"agent_message","text":"DONE"}}\n'
            + b'{"type":"turn.failed"}\n'
            + b'{"type":"turn.completed"}\n',
            expected_final_message="DONE",
        )
        self.assertIs(failed["turn_succeeded"], False)
        self.assertIs(failed["exact_final_message"], False)
        self.assertIs(failed["approval_command_succeeded"], False)

        post_message_command = _redacted_cli_observation(
            b'{"type":"item.completed","item":{"type":"agent_message","text":"DONE"}}\n'
            + completed_command
            + b'{"type":"turn.completed"}\n',
            expected_final_message="DONE",
        )
        self.assertIs(post_message_command["turn_succeeded"], True)
        self.assertIs(post_message_command["exact_final_message"], True)
        self.assertIs(post_message_command["approval_command_succeeded"], False)

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

    def test_generated_plugin_cache_cleanup_tolerates_a_live_writer_race(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            codex_home = Path(directory)
            cache = codex_home / ".tmp" / "plugins"
            cache.mkdir(parents=True)
            race = OSError(errno.ENOTEMPTY, "directory not empty")
            with mock.patch(
                "rondo_eval.model_cli_diagnostic.shutil.rmtree",
                side_effect=[race, race, race, race, race],
            ) as rmtree, mock.patch(
                "rondo_eval.model_cli_diagnostic.time.sleep"
            ) as sleep:
                _remove_generated_plugin_cache(codex_home)
            self.assertEqual(rmtree.call_count, 5)
            self.assertEqual(sleep.call_count, 4)
            self.assertTrue(cache.is_dir())


if __name__ == "__main__":
    unittest.main()
