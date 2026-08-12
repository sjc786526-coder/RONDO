from __future__ import annotations

import asyncio
import hashlib
import http.client
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.config import RuntimeConfig  # noqa: E402
from rondo_eval.contracts import BinaryManifest, RunOutcome, Side  # noqa: E402
from rondo_eval.docker_supervisor import (  # noqa: E402
    HeavyLockLease,
)
from rondo_eval.terminal_bench import materialize as materialize_module  # noqa: E402
from rondo_eval.terminal_bench import docker_smoke as docker_smoke_module  # noqa: E402
from rondo_eval.terminal_bench.docker_smoke import (  # noqa: E402
    NO_API_SMOKE_BEARER,
    NO_API_SMOKE_CALL_ID,
    NO_API_SMOKE_COMMAND,
    NO_API_SMOKE_MARKER,
    DockerNoApiSmokeError,
    LocalResponsesFakeServer,
    _parser,
    _smoke_exit_code,
    run_docker_no_api_smoke,
)
from rondo_eval.terminal_bench.freeze import (  # noqa: E402
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_IMAGE_REF,
    FIX_GIT_IMAGE_TAG,
    FIX_GIT_TASK_ARCHIVE_SHA256,
    FIX_GIT_TASK_ID,
    TERMINAL_BENCH_COMMIT,
    TERMINAL_BENCH_REPO_REF,
)
from rondo_eval.terminal_bench.materialize import MaterializedTask  # noqa: E402
from rondo_eval.terminal_bench.pair import (  # noqa: E402
    B2_NO_API_BATCH_ID,
    load_no_api_pair_identity,
)
from rondo_eval.terminal_bench.results import ParsedHarborResult  # noqa: E402
from rondo_eval.terminal_bench.__main__ import _load_manifest  # noqa: E402
from rondo_eval.terminal_bench.runner import (  # noqa: E402
    HostHarborResult,
    TerminalBenchRequest,
    TerminalBenchRunError,
)


def _code_mode_wire_output(result_text: str) -> list[dict[str, str]]:
    return [
        {
            "type": "input_text",
            "text": "Script completed\nWall time 0.1 seconds\nOutput:\n",
        },
        {"type": "input_text", "text": result_text},
    ]


class FakeMaterializer:
    def __init__(self, root: Path) -> None:
        self.root = root

    def materialize(self, **kwargs) -> MaterializedTask:
        self.root.mkdir(parents=True, exist_ok=True)
        task = self.root / kwargs["staging_name"]
        task.mkdir()
        overlay = self.root / f"{kwargs['staging_name']}.compose.yaml"
        provider_secret = self.root / f"{kwargs['staging_name']}.provider-api-key"
        provider_secret.write_bytes(b"")
        provider_secret.chmod(0o600)
        overlay.write_text(
            materialize_module._compose_overlay_text(
                task_label=kwargs["task_label"],
                memory_bytes=kwargs["memory_bytes"],
                memory_swap_bytes=kwargs["memory_swap_bytes"],
                pids_limit=kwargs["pids_limit"],
                provider_api_key_env=kwargs["provider_api_key_env"],
                runtime_user=materialize_module.TERMINAL_BENCH_AGENT_USER,
                provider_secret_path=provider_secret,
                seccomp_profile=kwargs.get("seccomp_profile"),
                seccomp_profile_source_sha256=kwargs.get("seccomp_profile_source_sha256"),
                seccomp_profile_effective_sha256=kwargs.get("seccomp_profile_effective_sha256"),
            ),
            encoding="utf-8",
        )
        return MaterializedTask(
            task_path=task,
            overlay_path=overlay,
            provider_secret_path=provider_secret,
            source_repo_ref=TERMINAL_BENCH_REPO_REF,
            source_commit=TERMINAL_BENCH_COMMIT,
            source_digest=f"sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}",
            source_image_tag=FIX_GIT_IMAGE_TAG,
            runtime_image_ref=FIX_GIT_IMAGE_REF,
            task_label=kwargs["task_label"],
            memory_bytes=kwargs["memory_bytes"],
            memory_swap_bytes=kwargs["memory_swap_bytes"],
            pids_limit=kwargs["pids_limit"],
            provider_api_key_env=kwargs["provider_api_key_env"],
            runtime_user=materialize_module.TERMINAL_BENCH_AGENT_USER,
            staged_task_digest=materialize_module._harbor_content_digest(task),
            overlay_sha256=hashlib.sha256(overlay.read_bytes()).hexdigest(),
            seccomp_profile=kwargs.get("seccomp_profile"),
            seccomp_profile_source_sha256=kwargs.get("seccomp_profile_source_sha256"),
            seccomp_profile_effective_sha256=kwargs.get("seccomp_profile_effective_sha256"),
        )


class FakeHostExecutor:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def __init__(self, **kwargs) -> None:
        self.constructor = kwargs

    async def run(self, argv, **kwargs) -> HostHarborResult:
        type(self).calls.append((argv, kwargs))
        transport = next(
            value.removeprefix("provider_base_url=")
            for index, item in enumerate(argv[:-1])
            if item == "--agent-kwarg"
            for value in (argv[index + 1],)
            if value.startswith("provider_base_url=")
        )
        port = urlsplit(transport).port
        assert port is not None
        assert kwargs["injected_env"] == {"HARBOR_TELEMETRY": "off"}
        secret_mounts = [
            item
            for item in kwargs["compose_contract"].container.mounts
            if item.destination == "/run/secrets/rondo_eval_provider_api_key"
        ]
        assert len(secret_mounts) == 1
        bearer = Path(secret_mounts[0].source).read_text(encoding="utf-8")
        body = json.dumps({"model": "gpt-5.6-sol", "stream": True, "input": "fix"})
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "POST",
            "/v1/responses",
            body=body,
            headers={
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        connection.close()
        if (
            response.status != 200
            or '"type":"custom_tool_call"' not in payload
            or NO_API_SMOKE_MARKER not in payload
        ):
            raise AssertionError("loopback fake did not request the frozen code-mode call")
        follow_up = json.dumps(
            {
                "model": "gpt-5.6-sol",
                "stream": True,
                "input": [
                    {
                        "type": "custom_tool_call_output",
                        "call_id": NO_API_SMOKE_CALL_ID,
                        "output": _code_mode_wire_output(
                            json.dumps(
                                {"output": NO_API_SMOKE_MARKER, "exit_code": 0}
                            )
                        ),
                    }
                ],
            }
        )
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request(
            "POST",
            "/v1/responses",
            body=follow_up,
            headers={
                "Authorization": f"Bearer {bearer}",
                "Content-Type": "application/json",
            },
        )
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        connection.close()
        if response.status != 200 or '"text":"done"' not in payload:
            raise AssertionError("loopback fake did not complete after code-mode output")

        trials = Path(argv[argv.index("--trials-dir") + 1])
        trial_name = argv[argv.index("--trial-name") + 1]
        trial = trials / trial_name
        trial.mkdir(parents=True)
        (trial / "result.json").write_text(
            json.dumps(
                {
                    "trial_name": trial_name,
                    "task_name": FIX_GIT_TASK_ID,
                    "agent_result": {
                        "n_input_tokens": 0,
                        "n_cache_tokens": 0,
                        "n_output_tokens": 0,
                    },
                    "verifier_result": {"rewards": {"reward": 0.0}},
                    "exception_info": None,
                    "started_at": "2026-08-10T02:00:00Z",
                    "finished_at": "2026-08-10T02:00:01Z",
                }
            ),
            encoding="utf-8",
        )
        agent = trial / "agent"
        agent.mkdir()
        (agent / "codex.txt").write_text(
            "\n".join(
                (
                    json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "item-1",
                                "type": "agent_message",
                                "text": "done",
                            },
                        }
                    ),
                    json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {
                                "input_tokens": 0,
                                "cached_input_tokens": 0,
                                "cache_write_input_tokens": 0,
                                "output_tokens": 0,
                                "reasoning_output_tokens": 0,
                            },
                        }
                    ),
                )
            )
            + "\n",
            encoding="utf-8",
        )
        return HostHarborResult(0, trial)


class DockerNoApiSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary = self.root / "codex"
        self.binary.write_bytes(b"frozen binary")
        self.code_mode_host = self.root / "codex-code-mode-host"
        self.code_mode_host.write_bytes(b"frozen code-mode host")
        self.bwrap = self.root / "bwrap"
        self.bwrap.write_bytes(b"frozen package bwrap")
        FakeHostExecutor.calls.clear()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_frozen_marker_requires_canonical_git_probe(self) -> None:
        self.assertEqual(
            NO_API_SMOKE_COMMAND,
            "git -C /app/personal-site status --porcelain=v1 "
            "--untracked-files=no >/dev/null && printf rondo_code_mode_smoke",
        )
        self.assertEqual(
            docker_smoke_module.NO_API_SMOKE_CODE,
            'const result=await tools.exec_command({cmd:"git -C '
            '/app/personal-site status --porcelain=v1 --untracked-files=no '
            '>/dev/null && printf rondo_code_mode_smoke"});'
            'text(JSON.stringify({output:result.output,exit_code:result.exit_code}));',
        )

    def config(self) -> RuntimeConfig:
        return RuntimeConfig(
            paths=mock.Mock(),
            data={
                "paid_eval": {
                    "active_provider": "openai",
                    "main_model": "sol",
                    "guardian_model": "luna",
                    "main_reasoning_effort": "medium",
                    "guardian_reasoning_effort": "low",
                    "max_attempts": 5,
                    "retry_backoff_seconds": 1.0,
                    "providers": {
                        "openai": {
                            "display_name": "No-API fixture",
                            "api": "responses",
                            "base_url": "https://provider.example/v1",
                            "api_key_env": "OPENAI_API_KEY",
                            "unbilled_retry_statuses": [429, 500, 502, 503, 504],
                        }
                    },
                    "models": {
                        "sol": {
                            "model_id": "gpt-5.6-sol",
                            "input_usd_per_million": "5",
                            "cached_input_usd_per_million": "0.5",
                            "output_usd_per_million": "30",
                            "long_context_threshold_tokens": 272_000,
                            "long_context_input_multiplier": "2",
                            "long_context_output_multiplier": "1.5",
                            "cache_write_input_multiplier": "1.25",
                            "price_snapshot_date": "2026-08-10",
                            "price_source_url": "https://developers.openai.com/api/docs/models/compare",
                        },
                        "luna": {
                            "model_id": "gpt-5.6-luna",
                            "input_usd_per_million": "0.2",
                            "cached_input_usd_per_million": "0.02",
                            "output_usd_per_million": "1.2",
                            "long_context_threshold_tokens": 272_000,
                            "long_context_input_multiplier": "2",
                            "long_context_output_multiplier": "1.5",
                            "cache_write_input_multiplier": "1.25",
                            "price_snapshot_date": "2026-08-10",
                            "price_source_url": "https://developers.openai.com/api/docs/models/compare",
                        },
                    },
                }
            },
            source_sha256="b" * 64,
        )

    def request(self) -> TerminalBenchRequest:
        manifest = BinaryManifest(
            path=str(self.binary),
            sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            code_mode_host_path=str(self.code_mode_host),
            code_mode_host_sha256=hashlib.sha256(
                self.code_mode_host.read_bytes()
            ).hexdigest(),
            bwrap_path=str(self.bwrap),
            bwrap_sha256=hashlib.sha256(self.bwrap.read_bytes()).hexdigest(),
            bwrap_asset_url=(
                "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
                "bwrap-x86_64-unknown-linux-musl.tar.gz"
            ),
            bwrap_archive_sha256="1" * 64,
            bwrap_source_tree_sha256="2" * 64,
            source_commit="a" * 40,
            source_dirty=False,
            rust_toolchain="rustc 1.95.0",
            build_command=("guarded-build",),
            code_mode_host_build_command=("guarded-build-code-mode-host",),
        )
        return TerminalBenchRequest(
            side=Side.CODEX,
            batch_id=B2_NO_API_BATCH_ID,
            binary=manifest,
            image_digest=FIX_GIT_IMAGE_DIGEST,
            source_checkout=str(self.root / "source"),
            staging_root=str(self.root / "staging"),
            docker_task_id="p1-no-api-smoke-codex",
            memory_bytes=2 * 1024**3,
            memory_swap_bytes=3 * 1024**3,
            pids_limit=256,
            provider_transport_base_url=None,
            seccomp_profile_path=str(
                (EVAL_ROOT / "seccomp" / "plan008-userns-minimal-v0.2.3.json").resolve()
            ),
            seccomp_profile_source_sha256=(
                "9c5198e529f03d38babe9f270f663fa6867bda4e4d14a37a1f6680179d9bbd2f"
            ),
            seccomp_profile_effective_sha256=(
                "a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf"
            ),
            require_container_metrics=True,
        )

    def test_full_function_uses_real_prepare_backend_and_parser_with_reward_zero(self) -> None:
        result = asyncio.run(
            run_docker_no_api_smoke(
                self.config(),
                self.request(),
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=HeavyLockLease(token="x" * 16, held=True),
                pair_identity=mock.Mock(),
                materializer=FakeMaterializer(self.root / "fake-materialized"),
                executor_factory=FakeHostExecutor,
            )
        )

        self.assertEqual(result.parsed.outcome, RunOutcome.COMPLETED)
        self.assertEqual(result.parsed.reward, 0.0)
        self.assertTrue(result.contract_satisfied)
        self.assertTrue(result.passed)
        self.assertEqual(result.agent_json_events, 3)
        self.assertTrue(result.tool_round_trip)
        self.assertEqual(len(result.requests), 2)
        self.assertTrue(all(item.model == "gpt-5.6-sol" for item in result.requests))
        self.assertTrue(all(item.authorized for item in result.requests))
        docker_receipt = {"schema_version": 1, "cleanup": "verified_empty"}
        durable = replace(
            result,
            harbor=replace(
                result.harbor,
                docker_evidence=SimpleNamespace(receipt=lambda: docker_receipt),
            ),
        ).safe_summary()
        self.assertEqual(durable["docker"], docker_receipt)
        self.assertIn(
            '      - "seccomp=',
            result.prepared.materialized_task.overlay_path.read_text(encoding="utf-8"),
        )
        self.assertEqual(
            result.prepared.command.compose_contract.container.seccomp_profile_sha256,
            "a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf",
        )
        self.assertEqual(
            result.prepared.command.compose_contract.container.security_opt,
            ("no-new-privileges:true",),
        )
        self.assertTrue(
            result.prepared.command.compose_contract.container.require_container_metrics
        )
        _argv, kwargs = FakeHostExecutor.calls[0]
        self.assertEqual(kwargs["injected_env"], {"HARBOR_TELEMETRY": "off"})
        self.assertEqual(result.prepared.materialized_task.provider_secret_path.read_bytes(), b"")
        agent_kwargs = {
            _argv[index + 1].split("=", 1)[0]: _argv[index + 1].split("=", 1)[1]
            for index, item in enumerate(_argv[:-1])
            if item == "--agent-kwarg"
        }
        self.assertEqual(agent_kwargs["binary_bwrap_path"], str(self.bwrap))
        self.assertEqual(
            agent_kwargs["binary_bwrap_sha256"],
            hashlib.sha256(self.bwrap.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            json.loads(agent_kwargs["binary_bwrap_asset_url"]),
            self.request().binary.bwrap_asset_url,
        )
        self.assertEqual(
            json.loads(agent_kwargs["binary_bwrap_archive_sha256"]), "1" * 64
        )
        self.assertEqual(
            json.loads(agent_kwargs["binary_bwrap_source_tree_sha256"]), "2" * 64
        )
        self.assertEqual(_smoke_exit_code(result), 0)
        self.assertNotEqual(_smoke_exit_code(replace(result, requests=())), 0)

    def test_fake_rejects_second_round_without_nested_tool_marker(self) -> None:
        valid_wire = _code_mode_wire_output(
            json.dumps({"output": NO_API_SMOKE_MARKER, "exit_code": 0})
        )
        self.assertTrue(docker_smoke_module._valid_exec_result(valid_wire))
        for malformed_wire in (
            valid_wire[1]["text"],
            valid_wire[1:],
            valid_wire + [{"type": "input_text", "text": "extra"}],
            [valid_wire[0], {"type": "output_text", "text": valid_wire[1]["text"]}],
        ):
            with self.subTest(wire=malformed_wire):
                self.assertFalse(docker_smoke_module._valid_exec_result(malformed_wire))

        invalid_outputs = (
            "wrong marker",
            (
                "Script error: exec_command failed for git status && printf "
                f"{NO_API_SMOKE_MARKER}: spawn failed"
            ),
            json.dumps({"output": NO_API_SMOKE_MARKER, "exit_code": 1}),
            json.dumps({"output": NO_API_SMOKE_MARKER, "exit_code": False}),
            json.dumps({"output": f"extra {NO_API_SMOKE_MARKER}", "exit_code": 0}),
            json.dumps(
                {"output": NO_API_SMOKE_MARKER, "exit_code": 0, "extra": True}
            ),
        )
        for invalid_output in invalid_outputs:
            with self.subTest(output=invalid_output), LocalResponsesFakeServer() as server:
                port = urlsplit(server.loopback_base_url).port
                assert port is not None
                headers = {
                    "Authorization": f"Bearer {NO_API_SMOKE_BEARER}",
                    "Content-Type": "application/json",
                }
                for body in (
                    {"model": "gpt-5.6-sol", "stream": True, "input": "fix"},
                    {
                        "model": "gpt-5.6-sol",
                        "stream": True,
                        "input": [{
                            "type": "custom_tool_call_output",
                            "call_id": NO_API_SMOKE_CALL_ID,
                            "output": _code_mode_wire_output(invalid_output),
                        }],
                    },
                ):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", port, timeout=5
                    )
                    connection.request(
                        "POST", "/v1/responses", body=json.dumps(body), headers=headers
                    )
                    response = connection.getresponse()
                    response.read()
                    connection.close()
                self.assertEqual(response.status, 400)
                self.assertEqual(
                    server.requests[-1].rejection, "tool_round_trip_mismatch"
                )
                self.assertFalse(server.tool_round_trip)

    def test_completed_harbor_result_rejects_unexpected_code_mode_host_error_item(self) -> None:
        class ErrorItemHostExecutor(FakeHostExecutor):
            async def run(self, argv, **kwargs) -> HostHarborResult:
                result = await super().run(argv, **kwargs)
                codex_output = result.jobs_dir / "agent" / "codex.txt"
                codex_output.write_text(
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "item-error",
                                "type": "error",
                                "message": "unexpected error: code-mode-host binary is missing",
                            },
                        }
                    )
                    + "\n"
                    + json.dumps(
                        {
                            "type": "turn.completed",
                            "usage": {
                                "input_tokens": 0,
                                "cached_input_tokens": 0,
                                "cache_write_input_tokens": 0,
                                "output_tokens": 0,
                                "reasoning_output_tokens": 0,
                            },
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return result

        with self.assertRaises(DockerNoApiSmokeError) as caught:
            asyncio.run(
                run_docker_no_api_smoke(
                    self.config(),
                    self.request(),
                    counter=mock.Mock(),
                    lock_guard=mock.Mock(),
                    lease=HeavyLockLease(token="x" * 16, held=True),
                    pair_identity=mock.Mock(),
                    materializer=FakeMaterializer(self.root / "fake-materialized-error"),
                    executor_factory=ErrorItemHostExecutor,
                )
            )
        self.assertEqual(str(caught.exception), "no-API supervised run failed")
        self.assertNotIn("code-mode-host binary", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_server_rejects_websocket_and_nonlocal_configuration(self) -> None:
        with self.assertRaises(DockerNoApiSmokeError):
            LocalResponsesFakeServer(bind_host="0.0.0.0")

        with LocalResponsesFakeServer() as server:
            port = urlsplit(server.loopback_base_url).port
            assert port is not None
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(
                "POST",
                "/v1/responses",
                body=json.dumps({"model": "gpt-5.6-sol", "stream": True}),
                headers={
                    "Authorization": f"Bearer {NO_API_SMOKE_BEARER}",
                    "Upgrade": "websocket",
                },
            )
            response = connection.getresponse()
            response.read()
            connection.close()
            self.assertEqual(response.status, 400)
            self.assertEqual(server.requests[0].rejection, "websocket_disabled")

    def test_function_rejects_caller_transport_and_cli_requires_pair_inputs(self) -> None:
        request = self.request()
        object.__setattr__(request, "provider_transport_base_url", "https://example.com/v1")
        with self.assertRaises(DockerNoApiSmokeError):
            asyncio.run(
                run_docker_no_api_smoke(
                    self.config(),
                    request,
                    counter=mock.Mock(),
                    lock_guard=mock.Mock(),
                    lease=HeavyLockLease(token="x" * 16, held=True),
                    pair_identity=mock.Mock(),
                )
            )
        args = _parser().parse_args(
            [
                "--rondo-binary-manifest",
                "/tmp/rondo.json",
                "--codex-binary-manifest",
                "/tmp/codex.json",
                "--docker-host-volume",
                "/mnt/docker-data",
            ]
        )
        self.assertEqual(
            (args.rondo_binary_manifest.name, args.codex_binary_manifest.name),
            ("rondo.json", "codex.json"),
        )
        identity = mock.Mock()
        identity.no_api_seccomp.source_sha256 = "1" * 64
        identity.no_api_seccomp.effective_sha256 = "2" * 64
        identity.validate_no_api_seccomp.return_value = EVAL_ROOT / "seccomp.json"
        failed = SimpleNamespace(
            passed=False,
            parsed=SimpleNamespace(outcome=RunOutcome.INFRA_FAILED),
            safe_summary=lambda: {"status": "failed", "side": "rondo"},
        )
        proof = SimpleNamespace(
            guard=mock.Mock(),
            lease=HeavyLockLease(token="x" * 16, held=True),
        )
        with (
            mock.patch.object(
                docker_smoke_module.RepoPaths,
                "discover",
                return_value=SimpleNamespace(
                    common_root=self.root,
                    worktree_root=EVAL_ROOT.parent,
                ),
            ),
            mock.patch.object(
                docker_smoke_module, "load_no_api_pair_identity", return_value=identity
            ),
            mock.patch.object(docker_smoke_module, "load_runtime_config", return_value=self.config()),
            mock.patch.object(
                docker_smoke_module,
                "validate_eval_harness_checkout",
                return_value="a" * 40,
            ),
            mock.patch.object(docker_smoke_module, "validate_harbor_installation"),
            mock.patch.object(
                docker_smoke_module,
                "_load_manifest",
                side_effect=(self.request().binary, self.request().binary),
            ),
            mock.patch.object(docker_smoke_module, "lease_from_watchdog", return_value=proof),
            mock.patch.object(docker_smoke_module, "DockerCliCounter", return_value=mock.Mock()),
            mock.patch.object(
                docker_smoke_module,
                "run_docker_no_api_smoke",
                new=mock.AsyncMock(return_value=failed),
            ) as run,
            mock.patch.object(docker_smoke_module, "_write_current_receipt") as write,
            mock.patch("builtins.print"),
        ):
            status = docker_smoke_module.main(
                [
                    "--rondo-binary-manifest", "/tmp/rondo.json",
                    "--codex-binary-manifest", "/tmp/codex.json",
                    "--docker-host-volume", "/mnt/docker-data",
                ]
            )
        self.assertEqual(status, 70)
        self.assertEqual(run.await_count, 1)
        self.assertIs(run.await_args.args[1].side, Side.RONDO)
        write.assert_not_called()
        current = self.root / "eval-data" / "b2" / "current.json"
        docker_smoke_module._write_current_receipt(current, {"run": 1})
        docker_smoke_module._write_current_receipt(current, {"run": 2})
        self.assertEqual(json.loads(current.read_text()), {"run": 2})

    def test_cli_loader_requires_15_key_bundle_and_rejects_legacy_16_keys(self) -> None:
        bundle = self.root / "eval-data" / "bin" / "smoke-bundle"
        resources = bundle / "codex-resources"
        resources.mkdir(parents=True)
        codex = bundle / "codex"
        host = bundle / "codex-code-mode-host"
        bwrap = resources / "bwrap"
        codex.write_bytes(b"codex")
        host.write_bytes(b"host")
        bwrap.write_bytes(b"bwrap")
        value = {
            "path": str(codex),
            "sha256": hashlib.sha256(codex.read_bytes()).hexdigest(),
            "code_mode_host_path": str(host),
            "code_mode_host_sha256": hashlib.sha256(host.read_bytes()).hexdigest(),
            "bwrap_path": str(bwrap),
            "bwrap_sha256": hashlib.sha256(bwrap.read_bytes()).hexdigest(),
            "bwrap_asset_url": (
                "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
                "bwrap-x86_64-unknown-linux-musl.tar.gz"
            ),
            "bwrap_archive_sha256": "1" * 64,
            "bwrap_source_tree_sha256": "2" * 64,
            "source_commit": "a" * 40,
            "source_dirty": False,
            "rust_toolchain": "rustc 1.95.0",
            "build_command": ["build-codex"],
            "code_mode_host_build_command": ["build-host"],
            "workspace_lock_normalization": None,
        }
        manifest_path = bundle / "manifest.json"
        manifest_path.write_text(json.dumps(value), encoding="utf-8")
        loaded = _load_manifest(manifest_path, self.root)
        self.assertEqual(loaded.bwrap_path, str(bwrap))
        self.assertEqual(loaded.bwrap_sha256, value["bwrap_sha256"])
        self.assertEqual(loaded.bwrap_asset_url, value["bwrap_asset_url"])
        self.assertEqual(loaded.bwrap_archive_sha256, "1" * 64)
        self.assertEqual(loaded.bwrap_source_tree_sha256, "2" * 64)

        for key in (
            "bwrap_asset_url",
            "bwrap_archive_sha256",
            "bwrap_source_tree_sha256",
        ):
            value.pop(key)
        value.update(
            {
                "bwrap_build_command": ["package-bwrap"],
                "libcap_version": "2.78",
                "libcap_archive_sha256": "1" * 64,
                "libcap_static_sha256": "2" * 64,
            }
        )
        manifest_path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(TerminalBenchRunError, "schema differs"):
            _load_manifest(manifest_path, self.root)


if __name__ == "__main__":
    unittest.main()
