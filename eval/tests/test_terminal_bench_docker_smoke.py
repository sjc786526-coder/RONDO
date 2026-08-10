from __future__ import annotations

import asyncio
import hashlib
import http.client
import io
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlsplit


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.config import RuntimeConfig  # noqa: E402
from rondo_eval.contracts import BinaryManifest, RunOutcome, Side  # noqa: E402
from rondo_eval.docker_supervisor import (  # noqa: E402
    DockerContainerMetrics,
    DockerDesktopVhdxEvidence,
    DockerImageIdentity,
    DockerSeccompEvidence,
    HeavyLockLease,
)
from rondo_eval.terminal_bench import materialize as materialize_module  # noqa: E402
from rondo_eval.terminal_bench import docker_smoke as docker_smoke_module  # noqa: E402
from rondo_eval.terminal_bench.docker_smoke import (  # noqa: E402
    NO_API_SMOKE_BEARER,
    NO_API_SMOKE_CALL_ID,
    NO_API_SMOKE_MARKER,
    DockerNoApiSmokeError,
    LocalResponsesFakeServer,
    _parser,
    _print_safe_cli_error,
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
    PairSequenceLedger,
    load_pair_identity,
    no_api_safe_summary_path,
    persist_no_api_safe_summary,
)
from rondo_eval.terminal_bench.__main__ import _load_manifest  # noqa: E402
from rondo_eval.terminal_bench.runner import (  # noqa: E402
    HostHarborResult,
    TerminalBenchRequest,
    TerminalBenchRunError,
)


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
        body = json.dumps({"model": "gpt-5.6-luna", "stream": True, "input": "fix"})
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
                "model": "gpt-5.6-luna",
                "stream": True,
                "input": [
                    {
                        "type": "custom_tool_call_output",
                        "call_id": NO_API_SMOKE_CALL_ID,
                        "output": json.dumps(
                            {"output": NO_API_SMOKE_MARKER, "exit_code": 0}
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

    def config(self) -> RuntimeConfig:
        return RuntimeConfig(
            paths=mock.Mock(),
            data={
                "providers": {
                    "openai": {
                        "api": "responses",
                        "base_url": "https://api.openai.com/v1",
                        "api_key_env": "OPENAI_API_KEY",
                        "main_model": "gpt-5.6-luna",
                        "guardian_model": "gpt-5.6-luna",
                        "guardian_reasoning_effort": "low",
                    }
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
            batch_id="p1-no-api-smoke",
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
        self.assertTrue(all(item.model == "gpt-5.6-luna" for item in result.requests))
        self.assertTrue(all(item.authorized for item in result.requests))
        self.assertTrue(result.safe_summary()["code_mode_tool_round_trip"])
        samples = (
            SimpleNamespace(
                docker_total_bytes=10,
                task_bytes=2,
                data_root_filesystem_free_bytes=100,
            ),
            SimpleNamespace(
                docker_total_bytes=11,
                task_bytes=3,
                data_root_filesystem_free_bytes=99,
                data_root="/must-not-be-persisted",
            ),
        )
        evidence = SimpleNamespace(
            samples=samples,
            warnings=(),
            image_identity=DockerImageIdentity(FIX_GIT_IMAGE_REF, f"sha256:{'a' * 64}"),
            desktop_vhdx=DockerDesktopVhdxEvidence(1000, 1200, 1100, 200),
            container_metrics=DockerContainerMetrics("b" * 64, 1.5, 4096),
            effective_seccomp=DockerSeccompEvidence(
                "custom",
                "a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf",
            ),
        )
        durable = replace(
            result,
            harbor=replace(result.harbor, docker_evidence=evidence),
        ).safe_summary()["docker"]
        self.assertEqual(durable["image_identity"]["image_id"], f"sha256:{'a' * 64}")
        self.assertEqual(durable["desktop_vhdx"]["peak_growth_bytes"], 200)
        self.assertEqual(durable["container_metrics"]["peak_memory_bytes"], 4096)
        self.assertEqual(durable["effective_seccomp"]["profile_kind"], "custom")
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
        with LocalResponsesFakeServer() as server:
            port = urlsplit(server.loopback_base_url).port
            assert port is not None
            headers = {
                "Authorization": f"Bearer {NO_API_SMOKE_BEARER}",
                "Content-Type": "application/json",
            }
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(
                "POST",
                "/v1/responses",
                body=json.dumps(
                    {"model": "gpt-5.6-luna", "stream": True, "input": "fix"}
                ),
                headers=headers,
            )
            first = connection.getresponse()
            first.read()
            connection.close()
            self.assertEqual(first.status, 200)

            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request(
                "POST",
                "/v1/responses",
                body=json.dumps(
                    {
                        "model": "gpt-5.6-luna",
                        "stream": True,
                        "input": [
                            {
                                "type": "custom_tool_call_output",
                                "call_id": NO_API_SMOKE_CALL_ID,
                                "output": "wrong marker",
                            }
                        ],
                    }
                ),
                headers=headers,
            )
            second = connection.getresponse()
            second.read()
            connection.close()
            self.assertEqual(second.status, 400)
            self.assertEqual(server.requests[-1].rejection, "tool_round_trip_mismatch")
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

        with self.assertRaisesRegex(DockerNoApiSmokeError, "error event"):
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
                body=json.dumps({"model": "gpt-5.6-luna", "stream": True}),
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

    def test_function_rejects_caller_transport_and_cli_requires_three_inputs(self) -> None:
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
                "--side",
                "codex",
                "--binary-manifest",
                "/tmp/binary.json",
                "--docker-host-volume",
                "/mnt/docker-data",
            ]
        )
        self.assertEqual((args.side, args.binary_manifest.name), ("codex", "binary.json"))

    def test_cli_error_is_single_line_structured_and_does_not_render_causes(self) -> None:
        caught = DockerNoApiSmokeError("tracked Harbor identity differs")
        caught.__cause__ = RuntimeError("sensitive-cause")
        output = io.StringIO()

        with redirect_stderr(output):
            _print_safe_cli_error(caught, exit_code=65)

        value = json.loads(output.getvalue())
        self.assertEqual(value["reason"], "tracked Harbor identity differs")
        self.assertEqual(value["exit_code"], 65)
        self.assertNotIn("sensitive-cause", output.getvalue())

    @unittest.skipUnless(hasattr(os, "fork"), "requires POSIX process death injection")
    def test_cli_recovers_durable_safe_summary_before_external_preflight(self) -> None:
        identity = load_pair_identity()
        paths = SimpleNamespace(
            common_root=self.root,
            worktree_root=EVAL_ROOT.parent,
        )
        ledger_path = (
            self.root
            / "eval-data"
            / "pairs"
            / f"{identity.pair_id}-no-api.json"
        )
        run_id = "tb-no-api-rondo-summary-cut"
        summary = {
            "schema_version": 1,
            "side": "rondo",
            "outcome": "completed",
            "task_outcome": "pass",
            "reward": 1.0,
            "fake_requests": 2,
            "fake_contract_hits": 2,
            "fake_contract_satisfied": True,
            "agent_json_events": 3,
            "code_mode_tool_round_trip": True,
            "host_returncode": 0,
            "pair_validation": True,
            "docker": {
                "sample_count": 2,
                "baseline_total_bytes": 1,
                "final_total_bytes": 2,
                "baseline_task_bytes": 1,
                "final_task_bytes": 2,
                "baseline_data_root_free_bytes": 100,
                "final_data_root_free_bytes": 99,
                "image_identity": {
                    "image_reference": FIX_GIT_IMAGE_REF,
                    "image_id": f"sha256:{'a' * 64}",
                },
                "desktop_vhdx": {
                    "baseline_bytes": 1000,
                    "peak_bytes": 1200,
                    "final_bytes": 1100,
                    "peak_growth_bytes": 200,
                },
                "container_metrics": {
                    "container_id": "b" * 64,
                    "cpu_usage_seconds": 1.0,
                    "peak_memory_bytes": 4096,
                },
                "effective_seccomp": {
                    "profile_kind": "custom",
                    "profile_sha256": identity.no_api_seccomp.effective_sha256,
                },
            },
        }
        child = os.fork()
        if child == 0:
            try:
                with PairSequenceLedger(
                    ledger_path, identity=identity, mode="no_api"
                ) as sequence:
                    sequence.claim(
                        side=Side.RONDO,
                        run_id=run_id,
                        eval_harness_commit="f" * 40,
                    )
                persist_no_api_safe_summary(
                    no_api_safe_summary_path(
                        ledger_path, identity=identity, run_id=run_id
                    ),
                    identity=identity,
                    side=Side.RONDO,
                    run_id=run_id,
                    eval_harness_commit="f" * 40,
                    summary=summary,
                )
            except BaseException:
                os._exit(99)
            os._exit(77)
        _pid, status = os.waitpid(child, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 77)

        external_preflight = mock.Mock(side_effect=AssertionError("external preflight ran"))
        output = io.StringIO()
        with mock.patch.object(
            docker_smoke_module.RepoPaths, "discover", return_value=paths
        ), mock.patch.object(
            docker_smoke_module, "load_pair_identity", return_value=identity
        ), mock.patch.object(
            docker_smoke_module, "validate_eval_harness_checkout", external_preflight
        ), mock.patch.object(
            docker_smoke_module, "load_runtime_config", external_preflight
        ), mock.patch.object(
            docker_smoke_module, "_load_manifest", external_preflight
        ), mock.patch.object(
            docker_smoke_module, "validate_harbor_installation", external_preflight
        ), mock.patch.object(
            docker_smoke_module, "lease_from_watchdog", external_preflight
        ), redirect_stdout(output):
            exit_code = docker_smoke_module.main(
                [
                    "--side",
                    "rondo",
                    "--binary-manifest",
                    str(self.root / "not-read.json"),
                    "--docker-host-volume",
                    str(self.root / "not-probed"),
                    "--pair-validation",
                ]
            )
        self.assertEqual(exit_code, 0)
        external_preflight.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "recovered")
        state = json.loads(ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(state["runs"][0]["status"], "completed")

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
