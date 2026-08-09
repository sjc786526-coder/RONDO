from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.config import RuntimeConfig  # noqa: E402
from rondo_eval.contracts import BinaryManifest, Side  # noqa: E402
from rondo_eval.api_budget_proxy import PersistentBudgetLedger  # noqa: E402
from rondo_eval.terminal_bench import (  # noqa: E402
    AdapterError,
    CodexUploadAdapter,
    DockerSupervisedHostHarborExecutor,
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_IMAGE_REF,
    FIX_GIT_IMAGE_TAG,
    FIX_GIT_TASK_ARCHIVE_SHA256,
    FIX_GIT_TASK_ID,
    HARBOR_REQUIREMENT,
    HARBOR_WHEEL_SHA256,
    HostHarborResult,
    InjectedHostHarborBackend,
    MaterializationError,
    MaterializedTask,
    PinnedTaskMaterializer,
    RondoUploadAdapter,
    TERMINAL_BENCH_COMMIT,
    TERMINAL_BENCH_REPO_REF,
    TERMINAL_BENCH_VERSION,
    TerminalBenchRequest,
    UnifiedTerminalBenchRunner,
    prepare_terminal_bench_run,
)
from rondo_eval.terminal_bench import materialize as materialize_module  # noqa: E402
from rondo_eval.terminal_bench import adapters as adapters_module  # noqa: E402
from rondo_eval.terminal_bench import live as live_module  # noqa: E402
from rondo_eval.terminal_bench import runner as runner_module  # noqa: E402
from rondo_eval.terminal_bench.compat import exec_result  # noqa: E402
from rondo_eval.terminal_bench.freeze import FreezeError, validate_runtime_image_digest  # noqa: E402
from rondo_eval.docker_supervisor import (  # noqa: E402
    DockerExecutionResult,
    DockerOperation,
    HeavyLockLease,
)


@dataclass
class FakeExecResult:
    return_code: int
    stdout: str = ""
    stderr: str = ""


class FakeEnvironment:
    default_user = "root"

    def __init__(self, *, corrupt_remote: bool = False) -> None:
        self.corrupt_remote = corrupt_remote
        self.calls: list[tuple[str, dict[str, str] | None, int | None, str | None]] = []
        self.uploads: list[tuple[Path, str]] = []
        self.remote: dict[str, bytes] = {}

    async def upload_file(self, local_path, remote_path):
        source = Path(local_path)
        self.uploads.append((source, remote_path))
        data = source.read_bytes()
        self.remote[remote_path] = data + (b"corrupt" if self.corrupt_remote else b"")

    async def exec(self, command, *, cwd=None, env=None, timeout_sec=None, user=None):
        del cwd
        self.calls.append((command, env, timeout_sec, user))
        raw = command.removeprefix("set -o pipefail; ")
        if raw.startswith("sha256sum -- "):
            path = raw.removeprefix("sha256sum -- ").strip("'")
            digest = hashlib.sha256(self.remote[path]).hexdigest()
            return FakeExecResult(0, f"{digest}  {path}\n")
        return FakeExecResult(0)


class FakeMaterializer:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls = []

    def materialize(self, **kwargs):
        self.calls.append(kwargs)
        task = self.root / kwargs["staging_name"]
        task.mkdir()
        overlay = self.root / f"{kwargs['staging_name']}.compose.yaml"
        overlay.write_text("services:\n  main: {}\n")
        staged_digest = materialize_module._harbor_content_digest(task)
        overlay_digest = hashlib.sha256(overlay.read_bytes()).hexdigest()
        return MaterializedTask(
            task_path=task,
            overlay_path=overlay,
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
            staged_task_digest=staged_digest,
            overlay_sha256=overlay_digest,
        )


class FakeRunnerBackend:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, prepared):
        self.calls.append(prepared)
        return HostHarborResult(0, prepared.materialized_task.task_path.parent / "jobs")


class FakeHostExecutor:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        return HostHarborResult(0, Path(argv[argv.index("--jobs-dir") + 1]))


class FakeBudgetProxy:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        kwargs["ledger"].ensure_run(kwargs["run_id"])
        self.docker_base_url = "http://host.docker.internal:43123/v1"
        self.downstream_api_key = "fake-budget-proxy-downstream-key"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class TerminalBenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.binary_path = self.root / "codex"
        self.binary_path.write_bytes(b"frozen v0.147.0 binary")
        self.binary_digest = hashlib.sha256(self.binary_path.read_bytes()).hexdigest()
        self.code_mode_host_path = self.root / "codex-code-mode-host"
        self.code_mode_host_path.write_bytes(b"frozen v0.147.0 code-mode host")
        self.code_mode_host_digest = hashlib.sha256(
            self.code_mode_host_path.read_bytes()
        ).hexdigest()
        self.bwrap_path = self.root / "bwrap"
        self.bwrap_path.write_bytes(b"frozen package bwrap")
        self.bwrap_digest = hashlib.sha256(self.bwrap_path.read_bytes()).hexdigest()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def manifest(self) -> BinaryManifest:
        return BinaryManifest(
            path=str(self.binary_path),
            sha256=self.binary_digest,
            code_mode_host_path=str(self.code_mode_host_path),
            code_mode_host_sha256=self.code_mode_host_digest,
            bwrap_path=str(self.bwrap_path),
            bwrap_sha256=self.bwrap_digest,
            bwrap_asset_url=(
                "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
                "bwrap-x86_64-unknown-linux-musl.tar.gz"
            ),
            bwrap_archive_sha256="1" * 64,
            bwrap_source_tree_sha256="2" * 64,
            source_commit="a" * 40,
            source_dirty=False,
            rust_toolchain=(
                "rustc:\n"
                "rustc 1.95.0\nbinary: rustc\ncommit-hash: frozen\n"
                "commit-date: 2026-08-03\nhost: x86_64-unknown-linux-gnu\n"
                "release: 1.95.0\nLLVM version: 21.1.8\n"
                "cargo:\ncargo 1.95.0 (frozen 2026-07-21)"
            ),
            build_command=("guarded-build", "codex"),
            code_mode_host_build_command=("guarded-build", "codex-code-mode-host"),
            workspace_lock_normalization="135 workspace packages: 0.0.0 -> 0.147.0",
        )

    def runtime_config(self) -> RuntimeConfig:
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

    def request(self, side=Side.CODEX) -> TerminalBenchRequest:
        return TerminalBenchRequest(
            side=side,
            batch_id="p1-b3",
            binary=self.manifest(),
            image_digest=FIX_GIT_IMAGE_DIGEST,
            source_checkout=str(self.root / "source"),
            staging_root=str(self.root / "staging"),
            docker_task_id=f"p1-b3-{side.value}",
            memory_bytes=2 * 1024**3,
            memory_swap_bytes=3 * 1024**3,
            pids_limit=256,
            provider_transport_base_url="http://host.docker.internal:43123/v1",
        )

    def adapter(self, adapter_type=CodexUploadAdapter, *, extra_env=None):
        manifest = self.manifest()
        return adapter_type(
            logs_dir=self.root / "logs",
            model_name="openai/gpt-5.6-luna",
            binary_path=manifest.path,
            binary_sha256=manifest.sha256,
            binary_code_mode_host_path=manifest.code_mode_host_path,
            binary_code_mode_host_sha256=manifest.code_mode_host_sha256,
            binary_bwrap_path=manifest.bwrap_path,
            binary_bwrap_sha256=manifest.bwrap_sha256,
            binary_bwrap_asset_url=manifest.bwrap_asset_url,
            binary_bwrap_archive_sha256=manifest.bwrap_archive_sha256,
            binary_bwrap_source_tree_sha256=manifest.bwrap_source_tree_sha256,
            binary_source_commit=manifest.source_commit,
            binary_source_dirty=manifest.source_dirty,
            binary_rust_toolchain=manifest.rust_toolchain,
            binary_build_command=list(manifest.build_command),
            binary_code_mode_host_build_command=list(
                manifest.code_mode_host_build_command
            ),
            binary_workspace_lock_normalization=manifest.workspace_lock_normalization,
            provider_base_url="https://api.openai.com/v1",
            provider_api_key_env="OPENAI_API_KEY",
            guardian_model="gpt-5.6-luna",
            guardian_effort="low",
            extra_env=extra_env,
        )

    def prepare(self, side=Side.CODEX):
        materializer = FakeMaterializer(self.root / f"fake-{side.value}")
        materializer.root.mkdir()
        return prepare_terminal_bench_run(
            self.runtime_config(), self.request(side), materializer=materializer
        )

    def test_freeze_and_lock_are_exact(self) -> None:
        self.assertEqual(HARBOR_REQUIREMENT, "harbor==0.20.0")
        self.assertEqual(HARBOR_WHEEL_SHA256, "4b7e48223aea2384cdb8c9eff35eaebd482fc9b1ec09f8193a121c47356ff19a")
        self.assertEqual(TERMINAL_BENCH_COMMIT, "ffccbe05ee73a9d59518217f294ad711bda39304")
        self.assertEqual(FIX_GIT_IMAGE_REF, f"alexgshaw/fix-git@{FIX_GIT_IMAGE_DIGEST}")
        lock = json.loads((EVAL_ROOT / "locks" / "terminal-bench-2-1.json").read_text())
        self.assertEqual(lock["p1_task"]["linux_amd64_image"], FIX_GIT_IMAGE_REF)
        with self.assertRaises(FreezeError):
            validate_runtime_image_digest(FIX_GIT_IMAGE_TAG)
        with self.assertRaises(FreezeError):
            validate_runtime_image_digest(f"sha256:{'c' * 64}")

    def test_real_harbor_exec_result_allows_empty_optional_streams(self) -> None:
        from harbor.environments.base import ExecResult

        self.assertEqual(exec_result(ExecResult(return_code=0)), (0, "", ""))

    def test_prepare_materializes_local_task_and_projects_safe_harbor_cli(self) -> None:
        materializer = FakeMaterializer(self.root / "fake")
        materializer.root.mkdir()
        with mock.patch.object(runner_module.config_module, "make_run_spec", wraps=runner_module.config_module.make_run_spec) as factory:
            prepared = prepare_terminal_bench_run(self.runtime_config(), self.request(), materializer=materializer)

        factory.assert_called_once()
        self.assertEqual(materializer.calls[0]["image_digest"], FIX_GIT_IMAGE_DIGEST)
        argv = prepared.command.argv
        self.assertEqual(Path(argv[0]), EVAL_ROOT / ".venv" / "bin" / "harbor")
        self.assertEqual(argv[1], "run")
        self.assertEqual(Path(argv[argv.index("--path") + 1]), prepared.materialized_task.task_path)
        self.assertNotIn("--repo", argv)
        self.assertNotIn("--upload", argv)
        self.assertIn("--delete", argv)
        self.assertEqual(argv[argv.index("--max-retries") + 1], "0")
        self.assertEqual(prepared.command.image_ref, FIX_GIT_IMAGE_REF)
        self.assertEqual(prepared.command.source_repo_ref, TERMINAL_BENCH_REPO_REF)
        self.assertEqual(prepared.command.task_source_digest, f"sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}")
        self.assertEqual(prepared.spec.provider.base_url, "https://api.openai.com/v1")
        self.assertIs(prepared.spec.code_mode_host, True)
        self.assertIs(prepared.spec.sandbox_network_access, True)
        self.assertEqual(
            prepared.command.provider_transport_base_url,
            "http://host.docker.internal:43123/v1",
        )
        self.assertNotIn(FIX_GIT_IMAGE_TAG, "\0".join(argv))

    def test_real_harbor_factory_can_construct_both_custom_agents(self) -> None:
        try:
            from harbor.agents.factory import AgentFactory
            from harbor.cli.utils import parse_kwargs
        except ModuleNotFoundError:
            self.skipTest("Harbor is not installed")
        for side in (Side.CODEX, Side.RONDO):
            prepared = self.prepare(side)
            argv = prepared.command.argv
            values = [argv[index + 1] for index, value in enumerate(argv) if value == "--agent-kwarg"]
            self.assertTrue(all("\n" not in value and "\r" not in value for value in values))
            kwargs = parse_kwargs(values)
            instance = AgentFactory.create_agent_from_import_path(
                argv[argv.index("--agent") + 1],
                logs_dir=self.root / f"harbor-{side.value}",
                model_name=argv[argv.index("--model") + 1],
                **kwargs,
            )
            self.assertIsInstance(instance, (CodexUploadAdapter, RondoUploadAdapter))
            self.assertEqual(instance.manifest, prepared.spec.binary)
            self.assertEqual(
                instance.manifest.code_mode_host_sha256,
                self.code_mode_host_digest,
            )
            self.assertEqual(instance.manifest.bwrap_sha256, self.bwrap_digest)
            self.assertEqual(instance.manifest.bwrap_archive_sha256, "1" * 64)
            self.assertEqual(instance.manifest.bwrap_source_tree_sha256, "2" * 64)
            self.assertEqual(
                instance.manifest.workspace_lock_normalization,
                "135 workspace packages: 0.0.0 -> 0.147.0",
            )

    def test_both_adapters_upload_exact_binary_without_package_install(self) -> None:
        for adapter_type, suffix in ((CodexUploadAdapter, "/codex"), (RondoUploadAdapter, "/rondo")):
            with self.subTest(adapter=adapter_type.__name__):
                environment = FakeEnvironment()
                adapter = self.adapter(adapter_type)
                asyncio.run(adapter.install(environment))
                self.assertTrue(adapter.remote_path.endswith(suffix))
                self.assertTrue(
                    adapter.remote_code_mode_host_path.endswith("/codex-code-mode-host")
                )
                self.assertEqual(
                    adapter.remote_bwrap_path,
                    "/opt/rondo-eval/bin/codex-resources/bwrap",
                )
                self.assertEqual(
                    environment.uploads,
                    [
                        (self.binary_path, adapter.remote_path),
                        (
                            self.code_mode_host_path,
                            adapter.remote_code_mode_host_path,
                        ),
                        (self.bwrap_path, adapter.remote_bwrap_path),
                    ],
                )
                commands = "\n".join(call[0] for call in environment.calls).lower()
                self.assertNotIn("npm", commands)
                self.assertNotIn("latest", commands)
                self.assertIn(f"sha256sum -- {adapter.remote_path}", commands)
                self.assertIn(
                    f"sha256sum -- {adapter.remote_code_mode_host_path}", commands
                )
                self.assertIn(f"sha256sum -- {adapter.remote_bwrap_path}", commands)
                self.assertNotIn("apt", commands)
                self.assertNotIn("command -v bwrap", commands)
                self.assertIn(f"{adapter.remote_path} --version", commands)

    def test_adapter_run_uses_safe_permissions_and_no_secret_in_exec_argv(self) -> None:
        secret = "sentinel-secret-must-not-serialize"
        adapter = self.adapter(extra_env={"OPENAI_API_KEY": secret})
        environment = FakeEnvironment()
        raw_agent_commands = []
        original_exec_as_agent = adapter.exec_as_agent

        async def capture_exec_as_agent(environment_arg, *, command, env=None, **kwargs):
            raw_agent_commands.append(command)
            return await original_exec_as_agent(
                environment_arg,
                command=command,
                env=env,
                **kwargs,
            )

        with mock.patch.object(
            adapter,
            "exec_as_agent",
            side_effect=capture_exec_as_agent,
        ):
            asyncio.run(adapter.run("repair the repository", environment, mock.Mock()))

        commands = "\n".join(call[0] for call in environment.calls)
        self.assertNotIn(secret, commands)
        self.assertNotIn("dangerously-bypass", commands)
        self.assertNotIn("--yolo", commands)
        self.assertIn('approvals_reviewer="auto_review"', commands)
        self.assertIn('approval_policy="on-request"', commands)
        self.assertIn('sandbox_mode="workspace-write"', commands)
        self.assertIn("sandbox_workspace_write.network_access=true", commands)
        self.assertIn("features.code_mode_host=true", commands)
        self.assertIn('model_provider="rondo_eval_openai"', commands)
        self.assertIn(
            'model_providers.rondo_eval_openai.wire_api="responses"',
            commands,
        )
        self.assertIn(
            "model_providers.rondo_eval_openai.supports_websockets=false",
            commands,
        )
        self.assertIn(
            "model_providers.rondo_eval_openai.request_max_retries=0",
            commands,
        )
        self.assertIn(
            "model_providers.rondo_eval_openai.stream_max_retries=0",
            commands,
        )
        self.assertNotIn("model_providers.openai.", commands)
        self.assertIn(adapter.remote_path + " exec", commands)
        raw_codex_command = next(
            command for command in raw_agent_commands if adapter.remote_path + " exec" in command
        )
        self.assertTrue(raw_codex_command.startswith("set -o pipefail; "))
        self.assertIn("--enable unified_exec", raw_codex_command)
        self.assertEqual(raw_codex_command.count("set -o pipefail; "), 1)
        self.assertLess(
            raw_codex_command.index("set -o pipefail; "),
            raw_codex_command.index("| tee "),
        )
        with self.assertRaises(AdapterError):
            adapters_module._validate_safe_codex_command(
                raw_codex_command.replace("features.code_mode_host=true", ""),
                side=Side.CODEX,
            )
        with self.assertRaises(AdapterError):
            adapters_module._validate_safe_codex_command(
                raw_codex_command.replace(
                    "sandbox_workspace_write.network_access=true", ""
                ),
                side=Side.CODEX,
            )
        with self.assertRaises(AdapterError):
            adapters_module._validate_safe_codex_command(
                raw_codex_command.replace(
                    "features.code_mode_host=true",
                    "features.code_mode_host=false",
                ),
                side=Side.CODEX,
            )
        self.assertTrue(
            all(
                not call[1]
                or call[1] == {"CODEX_HOME": "/tmp/rondo-eval-codex-home"}
                for call in environment.calls
            )
        )
        self.assertIn("/run/secrets/rondo_eval_provider_api_key", commands)
        self.assertNotIn("auto_review.model", commands)
        self.assertNotIn("auto_review.reasoning_effort", commands)
        self.assertNotIn("auto_review.evidence_dir", commands)

        rondo = self.adapter(RondoUploadAdapter, extra_env={"OPENAI_API_KEY": secret})
        rondo_environment = FakeEnvironment()
        asyncio.run(rondo.run("repair the repository", rondo_environment, mock.Mock()))
        rondo_commands = "\n".join(call[0] for call in rondo_environment.calls)
        self.assertIn("features.code_mode_host=true", rondo_commands)
        self.assertIn('auto_review.model="gpt-5.6-luna"', rondo_commands)
        self.assertIn('auto_review.reasoning_effort="low"', rondo_commands)
        self.assertIn('auto_review.evidence_dir="/logs/agent/guardian-evidence"', rondo_commands)

    def test_adapter_rejects_wrong_binary_digest(self) -> None:
        adapter = self.adapter()
        object.__setattr__(adapter.manifest, "sha256", "d" * 64)
        with self.assertRaises(AdapterError):
            asyncio.run(adapter.install(FakeEnvironment()))

        adapter = self.adapter()
        object.__setattr__(adapter.manifest, "code_mode_host_sha256", "d" * 64)
        with self.assertRaises(AdapterError):
            asyncio.run(adapter.install(FakeEnvironment()))

        adapter = self.adapter()
        object.__setattr__(adapter.manifest, "bwrap_sha256", "d" * 64)
        with self.assertRaises(AdapterError):
            asyncio.run(adapter.install(FakeEnvironment()))

    def test_materializer_rewrites_unique_image_and_writes_exact_overlay(self) -> None:
        source = self.root / "source"
        task = source / "tasks" / "fix-git"
        for directory in (task / "environment", task / "tests", task / "solution"):
            directory.mkdir(parents=True, exist_ok=True)
        (task / "instruction.md").write_text("fix git\n")
        (task / "README.md").write_text("readme\n")
        (task / "environment" / "Dockerfile").write_text("FROM scratch\n")
        (task / "tests" / "test.sh").write_text("true\n")
        (task / "solution" / "solve.sh").write_text("true\n")
        (task / "task.toml").write_text(_TASK_TOML)
        (source / "tasks" / "dataset.toml").write_text(
            f'[[tasks]]\nname = "{FIX_GIT_TASK_ID}"\ndigest = "sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}"\n'
        )
        staging = self.root / "eval-data" / "staging"

        def fake_git(_checkout, *args):
            if args == ("rev-parse", "HEAD"):
                return TERMINAL_BENCH_COMMIT
            if args == ("rev-parse", "--show-toplevel"):
                return str(source)
            return ""

        with mock.patch.object(materialize_module, "_git", side_effect=fake_git), mock.patch.object(
            materialize_module, "_harbor_content_digest", return_value=FIX_GIT_TASK_ARCHIVE_SHA256
        ), mock.patch.object(materialize_module, "_require_ignored_staging"):
            result = PinnedTaskMaterializer().materialize(
                source_checkout=source,
                staging_root=staging,
                staging_name="p1-codex-fix-git",
                image_digest=FIX_GIT_IMAGE_DIGEST,
                task_label="dev.rondo.eval.task=p1-codex",
                memory_bytes=2 * 1024**3,
                memory_swap_bytes=3 * 1024**3,
                pids_limit=256,
                provider_api_key_env="OPENAI_API_KEY",
            )

        staged = result.task_path.joinpath("task.toml").read_text()
        overlay = result.overlay_path.read_text()
        self.assertIn(f'docker_image = "{FIX_GIT_IMAGE_REF}"', staged)
        self.assertNotIn(FIX_GIT_IMAGE_TAG, staged)
        self.assertIn("dev.rondo.eval.task: p1-codex", overlay)
        self.assertIn(f"mem_limit: {2 * 1024**3}", overlay)
        self.assertIn(f"memswap_limit: {3 * 1024**3}", overlay)
        self.assertIn("pids_limit: 256", overlay)
        self.assertIn("environment: OPENAI_API_KEY", overlay)
        self.assertIn("source: rondo_eval_provider_api_key", overlay)
        result.overlay_path.write_text(overlay + "# tampered\n")
        with self.assertRaises(MaterializationError):
            result.validate()

    def test_injected_backend_never_serializes_provider_key(self) -> None:
        prepared = self.prepare(Side.RONDO)
        executor = FakeHostExecutor()
        secret = "backend-secret-sentinel"
        backend = InjectedHostHarborBackend(executor, getenv=lambda name: secret if name == "OPENAI_API_KEY" else None)
        result = asyncio.run(UnifiedTerminalBenchRunner(backend).run(prepared))
        self.assertEqual(result.returncode, 0)
        argv, kwargs = executor.calls[0]
        self.assertNotIn(secret, "\0".join(argv))
        self.assertNotIn(secret, repr(prepared.command))
        self.assertEqual(kwargs["injected_env"], {"HARBOR_TELEMETRY": "off", "OPENAI_API_KEY": secret})
        self.assertEqual(kwargs["exact_task_label"], "dev.rondo.eval.task=p1-b3-rondo")

    def test_concrete_host_executor_uses_public_full_lifetime_supervisor(self) -> None:
        prepared = self.prepare()
        secret = "supervisor-secret-sentinel"
        fake_supervisor = mock.Mock()
        fake_supervisor.supervise_host_command.return_value = DockerExecutionResult(
            operation=DockerOperation.HOST,
            argv=prepared.command.argv,
            returncode=0,
            samples=(),
            warnings=(),
        )
        with mock.patch.object(runner_module, "SubprocessHostCommandRunner") as host_runner, mock.patch.object(
            runner_module, "DockerSupervisor", return_value=fake_supervisor
        ):
            executor = DockerSupervisedHostHarborExecutor(
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=HeavyLockLease(token="x" * 16, held=True),
            )
            result = asyncio.run(
                executor.run(
                    prepared.command.argv,
                    cwd=prepared.command.cwd,
                    injected_env={"HARBOR_TELEMETRY": "off", "OPENAI_API_KEY": secret},
                    timeout_seconds=prepared.spec.timeout_seconds,
                    exact_task_label=prepared.command.task_label,
                )
            )

        self.assertEqual(result.docker_evidence.operation, DockerOperation.HOST)
        self.assertNotIn(secret, "\0".join(prepared.command.argv))
        host_runner.assert_called_once_with(
            executable=EVAL_ROOT / ".venv" / "bin" / "harbor",
            cwd=EVAL_ROOT,
            environment={
                "HARBOR_TELEMETRY": "off",
                "OPENAI_API_KEY": secret,
                "PYTHONPATH": str(EVAL_ROOT),
            },
        )
        fake_supervisor.supervise_host_command.assert_called_once()

    def test_budgeted_live_path_keeps_official_key_out_of_harbor_and_requires_evidence(self) -> None:
        jobs = self.root / "jobs"
        bundle = jobs / "trial" / "agent" / "guardian-evidence" / "review-1"
        bundle.mkdir(parents=True)
        (bundle / "E_final.json").write_text(
            json.dumps({
                "instructions": "frozen guardian policy",
                "input": [{"role": "user", "content": "approval evidence"}],
                "tools": [],
            })
        )
        (bundle / "meta.json").write_text(
            json.dumps({
                "evidence": "e_final",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "low",
                "terminal_status": "completed",
            })
        )
        metadata = self.root / "api-metadata.json"
        metadata.write_text(json.dumps({
            "requests": [{
                "role": "guardian",
                "contract_match": True,
                "usage_valid": True,
            }]
        }))
        observed: dict[str, object] = {}

        class FakeSupervisedExecutor:
            def __init__(self, **kwargs):
                observed["constructor"] = kwargs

            async def run(self, argv, **kwargs):
                observed["argv"] = argv
                observed["env"] = kwargs["injected_env"]
                return HostHarborResult(0, jobs)

        materializer = FakeMaterializer(self.root / "fake-live")
        materializer.root.mkdir()
        ledger_path = self.root / "budget.json"
        with PersistentBudgetLedger(ledger_path, batch_id="p1-live") as ledger, mock.patch.object(
            live_module, "LoopbackResponsesProxy", FakeBudgetProxy
        ), mock.patch.object(
            live_module, "DockerSupervisedHostHarborExecutor", FakeSupervisedExecutor
        ):
            result = asyncio.run(live_module.run_budgeted_terminal_bench(
                self.runtime_config(),
                self.request(Side.RONDO),
                api_key="official-key-sentinel",
                ledger=ledger,
                metadata_path=metadata,
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=HeavyLockLease(token="x" * 16, held=True),
                materializer=materializer,
            ))

        self.assertTrue(result.metadata_ready)
        self.assertEqual(len(result.evidence), 1)
        self.assertTrue(result.evidence[0].policy.aggregatable)
        self.assertEqual(
            observed["env"],
            {
                "HARBOR_TELEMETRY": "off",
                "OPENAI_API_KEY": "fake-budget-proxy-downstream-key",
            },
        )
        self.assertNotIn("official-key-sentinel", "\0".join(observed["argv"]))

    def test_prepare_rejects_every_non_b1_image_before_materialization(self) -> None:
        for value in (FIX_GIT_IMAGE_TAG, f"sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}", f"sha256:{'c' * 64}"):
            request = self.request()
            object.__setattr__(request, "image_digest", value)
            materializer = mock.Mock()
            with self.assertRaises(FreezeError):
                prepare_terminal_bench_run(self.runtime_config(), request, materializer=materializer)
            materializer.materialize.assert_not_called()

    def test_prepare_rejects_direct_or_credentialed_provider_transport(self) -> None:
        for value in (
            "https://api.openai.com/v1",
            "http://user:secret@host.docker.internal:43123/v1",
            "http://127.0.0.1:43123/v1",
        ):
            request = self.request()
            object.__setattr__(request, "provider_transport_base_url", value)
            with self.assertRaises(runner_module.TerminalBenchRunError):
                prepare_terminal_bench_run(
                    self.runtime_config(),
                    request,
                    materializer=mock.Mock(),
                )


_TASK_TOML = f'''schema_version = "1.1"
artifacts = []

[task]
name = "{FIX_GIT_TASK_ID}"
description = "Evaluates Git recovery."
keywords = ["coding"]

[metadata]
difficulty = "easy"
category = "software-engineering"
expert_time_estimate_min = 5.0

[verifier]
timeout_sec = 900.0

[agent]
timeout_sec = 900.0

[environment]
docker_image = "{FIX_GIT_IMAGE_TAG}"
cpus = 1
memory_mb = 2048
storage_mb = 10240
gpus = 0
allow_internet = true
'''


if __name__ == "__main__":
    unittest.main()
