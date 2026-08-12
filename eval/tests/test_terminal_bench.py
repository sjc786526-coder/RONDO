from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import unittest
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
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
from rondo_eval.terminal_bench.tasksets import FrozenTask  # noqa: E402
from rondo_eval.docker_supervisor import (  # noqa: E402
    DockerContainerFact,
    DockerExecutionResult,
    DockerImageIdentity,
    DockerOperation,
    DockerSupervisionError,
    HeavyLockLease,
)


@dataclass
class FakeExecResult:
    return_code: int
    stdout: str = ""
    stderr: str = ""


class FakeEnvironment:
    default_user = "1000:1000"

    def __init__(
        self,
        *,
        corrupt_remote: bool = False,
        remote_owner: str = "0:0",
        remote_owners: dict[str, str] | None = None,
        resolved_pwd: str = adapters_module.FIX_GIT_CANONICAL_WORKDIR,
        fail_command_contains: str | None = None,
    ) -> None:
        self.corrupt_remote = corrupt_remote
        self.remote_owner = remote_owner
        self.remote_owners = {
            "/run/secrets/rondo_eval_provider_api_key": "1000:1000",
            **dict(remote_owners or {}),
        }
        self.resolved_pwd = resolved_pwd
        self.fail_command_contains = fail_command_contains
        self.calls: list[tuple[str, dict[str, str] | None, int | None, str | None]] = []
        self.effective_users: list[str] = []
        self.uploads: list[tuple[Path, str]] = []
        self.remote: dict[str, bytes] = {}

    async def upload_file(self, local_path, remote_path):
        source = Path(local_path)
        self.uploads.append((source, remote_path))
        data = source.read_bytes()
        self.remote[remote_path] = data + (b"corrupt" if self.corrupt_remote else b"")
        self.remote_owners.setdefault(remote_path, "1000:1000")

    async def exec(self, command, *, cwd=None, env=None, timeout_sec=None, user=None):
        del cwd
        self.calls.append((command, env, timeout_sec, user))
        self.effective_users.append(user or self.default_user)
        raw = command.removeprefix("set -o pipefail; ")
        if self.fail_command_contains and self.fail_command_contains in raw:
            return FakeExecResult(1)
        if (
            "task_workdir=$(pwd -P)" in raw
            and (
                (match := re.search(r'test "\$task_workdir" = "([^"]+)"', raw))
                is None
                or self.resolved_pwd != match.group(1)
            )
        ):
            return FakeExecResult(1)
        if raw.startswith("stat -c '%u:%g' -- "):
            owner = next(
                (
                    value
                    for path, value in self.remote_owners.items()
                    if raw.endswith(path)
                ),
                self.remote_owner,
            )
            return FakeExecResult(0, f"{owner}\n")
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
        frozen = kwargs.get("frozen_task")
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
            )
        )
        staged_digest = materialize_module._harbor_content_digest(task)
        overlay_digest = hashlib.sha256(overlay.read_bytes()).hexdigest()
        return MaterializedTask(
            task_path=task,
            overlay_path=overlay,
            provider_secret_path=provider_secret,
            source_repo_ref=TERMINAL_BENCH_REPO_REF,
            source_commit=TERMINAL_BENCH_COMMIT,
            source_digest=(
                frozen.source_digest
                if frozen is not None
                else f"sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}"
            ),
            source_image_tag=(frozen.image_tag if frozen is not None else FIX_GIT_IMAGE_TAG),
            runtime_image_ref=(frozen.image_ref if frozen is not None else FIX_GIT_IMAGE_REF),
            task_label=kwargs["task_label"],
            memory_bytes=kwargs["memory_bytes"],
            memory_swap_bytes=kwargs["memory_swap_bytes"],
            pids_limit=kwargs["pids_limit"],
            provider_api_key_env=kwargs["provider_api_key_env"],
            runtime_user=materialize_module.TERMINAL_BENCH_AGENT_USER,
            staged_task_digest=staged_digest,
            overlay_sha256=overlay_digest,
            seccomp_profile=kwargs.get("seccomp_profile"),
            seccomp_profile_source_sha256=kwargs.get("seccomp_profile_source_sha256"),
            seccomp_profile_effective_sha256=kwargs.get("seccomp_profile_effective_sha256"),
            task_id=(frozen.task_id if frozen is not None else FIX_GIT_TASK_ID),
            image_digest=(
                frozen.image_digest if frozen is not None else FIX_GIT_IMAGE_DIGEST
            ),
            frozen_task=frozen,
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
        self.provider_secrets = []

    async def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        secret_mounts = [
            item
            for item in kwargs["compose_contract"].container.mounts
            if item.destination == "/run/secrets/rondo_eval_provider_api_key"
        ]
        if len(secret_mounts) != 1:
            raise AssertionError("expected one exact provider secret mount")
        self.provider_secrets.append(Path(secret_mounts[0].source).read_text(encoding="utf-8"))
        trials = Path(argv[argv.index("--trials-dir") + 1])
        return HostHarborResult(0, trials / argv[argv.index("--trial-name") + 1])


class FakeBudgetProxy:
    last_kwargs: dict[str, object] = {}

    def __init__(self, **kwargs) -> None:
        type(self).last_kwargs = dict(kwargs)
        self.kwargs = kwargs
        kwargs["ledger"].ensure_run(kwargs["run_id"])
        self.docker_base_url = "http://host.docker.internal:43123/v1"
        self.downstream_api_key = "fake-budget-proxy-downstream-key"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class TerminalBenchTests(unittest.TestCase):
    def test_harbor_executable_comes_from_the_active_eval_environment(self) -> None:
        self.assertEqual(
            runner_module.HARBOR_EXECUTABLE,
            Path(sys.executable).with_name("harbor"),
        )

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
                "paid_eval": {
                    "active_provider": "relay",
                    "main_model": "sol",
                    "guardian_model": "luna",
                    "main_reasoning_effort": "medium",
                    "guardian_reasoning_effort": "low",
                    "max_attempts": 5,
                    "retry_backoff_seconds": 1.0,
                    "providers": {
                        "relay": {
                            "display_name": "Test relay",
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

    def frozen_catalog(self) -> tuple[Path, str]:
        path = self.root / "frozen-model-catalog.json"
        encoded = (
            json.dumps(
                {
                    "models": [
                        {
                            "slug": "gpt-5.6-sol",
                            "auto_review_model_override": "gpt-5.6-luna",
                        },
                        {"slug": "gpt-5.6-luna"},
                    ]
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        path.write_bytes(encoded)
        path.chmod(0o400)
        return path, hashlib.sha256(encoded).hexdigest()

    def adapter(
        self,
        adapter_type=CodexUploadAdapter,
        *,
        extra_env=None,
        **overrides,
    ):
        manifest = self.manifest()
        return adapter_type(
            logs_dir=self.root / "logs",
            model_name="openai/gpt-5.6-sol",
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
            provider_base_url="https://provider.example/v1",
            provider_api_key_env="OPENAI_API_KEY",
            main_effort="medium",
            guardian_model="gpt-5.6-luna",
            guardian_effort="low",
            extra_env=extra_env,
            **overrides,
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
        self.assertEqual(Path(argv[0]), runner_module.HARBOR_EXECUTABLE)
        self.assertEqual(argv[1:3], ("trials", "start"))
        self.assertEqual(Path(argv[argv.index("--path") + 1]), prepared.materialized_task.task_path)
        self.assertNotIn("--repo", argv)
        self.assertNotIn("--upload", argv)
        self.assertIn("--delete", argv)
        self.assertNotIn("--max-retries", argv)
        self.assertEqual(
            Path(argv[argv.index("--trials-dir") + 1]),
            prepared.command.trials_dir,
        )
        self.assertEqual(
            argv[argv.index("--trial-name") + 1],
            prepared.command.trial_name,
        )
        container = prepared.command.compose_contract.container
        self.assertEqual(container.cap_drop, ("ALL",))
        self.assertEqual(len(container.mounts), 4)
        secret_mount = next(
            item
            for item in container.mounts
            if item.destination == "/run/secrets/rondo_eval_provider_api_key"
        )
        self.assertEqual(
            Path(secret_mount.source),
            prepared.materialized_task.provider_secret_path,
        )
        self.assertTrue(secret_mount.read_only)
        self.assertIsNone(container.compose_secret_mount)
        self.assertEqual(prepared.command.image_ref, FIX_GIT_IMAGE_REF)
        self.assertEqual(prepared.command.source_repo_ref, TERMINAL_BENCH_REPO_REF)
        self.assertEqual(prepared.command.task_source_digest, f"sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}")
        self.assertEqual(prepared.spec.provider.base_url, "https://provider.example/v1")
        self.assertIs(prepared.spec.code_mode_host, True)
        self.assertIs(prepared.spec.sandbox_network_access, True)
        self.assertEqual(
            prepared.command.provider_transport_base_url,
            "http://host.docker.internal:43123/v1",
        )
        self.assertNotIn(FIX_GIT_IMAGE_TAG, "\0".join(argv))
        drifted_container = replace(container, cap_drop=())
        drifted_command = replace(
            prepared.command,
            compose_contract=replace(
                prepared.command.compose_contract, container=drifted_container
            ),
        )
        with self.assertRaisesRegex(runner_module.TerminalBenchRunError, "Compose contract"):
            drifted_command.validate(
                prepared.spec, prepared.adapter, prepared.materialized_task
            )

    def test_prepare_projects_one_generic_frozen_task_without_cross_wiring(self) -> None:
        task = FrozenTask(
            task_id="terminal-bench/build-cython-ext",
            source_digest="sha256:" + "1" * 64,
            image_tag="alexgshaw/build-cython-ext:20251031",
            image_ref="alexgshaw/build-cython-ext@sha256:" + "2" * 64,
            workdir="/app",
            memory_mb=2048,
            timeout_seconds=1800,
            agent_timeout_seconds=900,
            verifier_timeout_seconds=900,
            build_timeout_seconds=600,
            requires_existing_git_repo=False,
        )
        request = replace(
            self.request(Side.RONDO),
            image_digest=task.image_digest,
            frozen_task=task,
        )
        materializer = FakeMaterializer(self.root / "generic")
        materializer.root.mkdir()

        prepared = prepare_terminal_bench_run(
            self.runtime_config(), request, materializer=materializer
        )

        self.assertEqual(prepared.spec.task_id, task.task_id)
        self.assertEqual(prepared.spec.task_image_digest, task.image_digest)
        self.assertEqual(prepared.command.image_ref, task.image_ref)
        self.assertEqual(prepared.command.task_source_digest, task.source_digest)
        self.assertEqual(prepared.adapter._task_workdir, "/app")
        self.assertFalse(prepared.adapter._task_requires_existing_git_repo)
        self.assertIn("build-cython-ext", prepared.materialized_task.task_path.name)
        with self.assertRaisesRegex(
            runner_module.TerminalBenchRunError, "materialization"
        ):
            replace(
                prepared.command, task_source_digest="sha256:" + "3" * 64
            ).validate(prepared.spec, prepared.adapter, prepared.materialized_task)
        container = prepared.command.compose_contract.container
        observed = DockerContainerFact(
            container_id="b" * 64,
            user=container.user,
            privileged=container.privileged,
            cap_add=container.cap_add,
            cap_drop=container.cap_drop,
            security_opt=container.security_opt,
            memory_bytes=container.memory_bytes,
            memory_swap_bytes=container.memory_swap_bytes,
            pids_limit=container.pids_limit,
            read_only_rootfs=container.read_only_rootfs,
            cgroupns_mode=container.cgroupns_mode,
            network_mode=container.network_mode,
            networks=container.networks,
            mounts=container.mounts,
            compose_project=container.compose_project,
            compose_service=container.compose_service,
            image_reference=task.image_ref,
            image_id=f"sha256:{'e' * 64}",
        )
        container.validate_observation(
            observed, ("name=seccomp,profile=builtin",)
        )
        for observed_cap_drop in ((), ("ALL", "NET_RAW")):
            with self.assertRaises(DockerSupervisionError):
                container.validate_observation(
                    replace(observed, cap_drop=observed_cap_drop),
                    ("name=seccomp,profile=builtin",),
                )

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
                self.assertNotIn("apt-get", commands)
                self.assertIn("/var/lib/apt/lists/partial", commands)
                self.assertIn("/var/cache/apt/archives/partial", commands)
                self.assertNotIn("command -v bwrap", commands)
                self.assertIn(f"{adapter.remote_path} --version", commands)
                self.assertTrue(environment.calls)
                self.assertTrue(all(call[3] == "root" for call in environment.calls))
                self.assertNotIn("chown", commands)
                for remote_path in (
                    str(adapter.remote_directory),
                    str(PurePosixPath(adapter.remote_bwrap_path).parent),
                    adapter.remote_path,
                    adapter.remote_code_mode_host_path,
                    adapter.remote_bwrap_path,
                ):
                    self.assertIn(f"stat -c '%u:%g' -- {remote_path}", commands)
                    self.assertIn(f"test ! -l {remote_path}", commands)
                for remote_path in (
                    adapter.remote_path,
                    adapter.remote_code_mode_host_path,
                    adapter.remote_bwrap_path,
                ):
                    self.assertIn(f"stat -c '%a' -- {remote_path}", commands)
                self.assertNotIn("chmod 0555", commands)

    def test_frozen_adapter_uploads_and_uses_source_bound_model_catalog(self) -> None:
        catalog_path, catalog_sha256 = self.frozen_catalog()
        adapter = self.adapter(
            frozen_model_catalog_path=str(catalog_path),
            frozen_model_catalog_sha256=catalog_sha256,
            frozen_model_catalog_source_commit=self.manifest().source_commit,
        )
        environment = FakeEnvironment()
        asyncio.run(adapter.install(environment))
        self.assertEqual(
            environment.uploads[-1],
            (catalog_path, adapter.remote_frozen_model_catalog_path),
        )
        install_commands = "\n".join(call[0] for call in environment.calls)
        self.assertIn(
            f"sha256sum -- {adapter.remote_frozen_model_catalog_path}",
            install_commands,
        )
        catalog_digest_calls = [
            call
            for call in environment.calls
            if f"sha256sum -- {adapter.remote_frozen_model_catalog_path}" in call[0]
        ]
        self.assertEqual(len(catalog_digest_calls), 1)
        self.assertIsNone(catalog_digest_calls[0][3])
        self.assertIn(
            f"stat -c '%a' -- {adapter.remote_frozen_model_catalog_path}",
            install_commands,
        )

        environment.calls.clear()
        asyncio.run(adapter.run("repair the repository", environment, mock.Mock()))
        run_commands = "\n".join(call[0] for call in environment.calls)
        self.assertIn(
            f'model_catalog_json="{adapter.remote_frozen_model_catalog_path}"',
            run_commands,
        )
        self.assertIn(
            f"test -r {adapter.remote_frozen_model_catalog_path}",
            run_commands,
        )
        self.assertIn(
            f"test ! -w {adapter.remote_frozen_model_catalog_path}",
            run_commands,
        )

        with self.assertRaisesRegex(AdapterError, "RONDO"):
            self.adapter(
                RondoUploadAdapter,
                frozen_model_catalog_path=str(catalog_path),
                frozen_model_catalog_sha256=catalog_sha256,
                frozen_model_catalog_source_commit=self.manifest().source_commit,
            )

    def test_prepare_projects_frozen_catalog_and_rejects_identity_drift(self) -> None:
        catalog_path, catalog_sha256 = self.frozen_catalog()
        config = self.runtime_config()
        config.paths.common_root = self.root
        request = replace(
            self.request(),
            frozen_model_catalog_path=str(catalog_path),
            frozen_model_catalog_sha256=catalog_sha256,
            frozen_model_catalog_source_commit=self.manifest().source_commit,
        )
        materializer = FakeMaterializer(self.root / "fake-catalog")
        materializer.root.mkdir()
        prepared = prepare_terminal_bench_run(
            config,
            request,
            materializer=materializer,
        )
        joined = "\0".join(prepared.command.argv)
        self.assertIn(f"frozen_model_catalog_path={catalog_path}", joined)
        self.assertIn(f"frozen_model_catalog_sha256={catalog_sha256}", joined)

        for drifted in (
            replace(request, frozen_model_catalog_sha256="0" * 64),
            replace(request, side=Side.RONDO),
        ):
            with self.subTest(side=drifted.side), self.assertRaises(
                runner_module.TerminalBenchRunError
            ):
                prepare_terminal_bench_run(
                    config,
                    drifted,
                    materializer=mock.Mock(),
                )

    def test_adapter_install_rejects_uploaded_file_owner_drift(self) -> None:
        adapter = self.adapter()
        environment = FakeEnvironment(
            remote_owners={adapter.remote_bwrap_path: "0:0"}
        )
        with self.assertRaisesRegex(AdapterError, "command_id=verify_file_owner"):
            asyncio.run(adapter.install(environment))
        commands = "\n".join(call[0] for call in environment.calls)
        self.assertNotIn("chown", commands)
        self.assertNotIn("chmod 0555", commands)
        self.assertNotIn(f"{adapter.remote_path} --version", commands)

    def test_adapter_run_uses_safe_permissions_and_no_secret_in_exec_argv(self) -> None:
        secret = "sentinel-secret-must-not-serialize"
        adapter = self.adapter(extra_env={"OPENAI_API_KEY": secret})
        environment = FakeEnvironment()
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
        self.assertIn('model_provider="rondo_eval_provider"', commands)
        self.assertIn(
            'model_providers.rondo_eval_provider.wire_api="responses"',
            commands,
        )
        self.assertIn(
            "model_providers.rondo_eval_provider.supports_websockets=false",
            commands,
        )
        self.assertIn(
            "model_providers.rondo_eval_provider.request_max_retries=0",
            commands,
        )
        self.assertIn(
            "model_providers.rondo_eval_provider.stream_max_retries=0",
            commands,
        )
        self.assertNotIn("model_providers.openai.", commands)
        self.assertIn(adapter.remote_path + " exec", commands)
        raw_codex_command = next(
            command
            for command, _env, _timeout, user in environment.calls
            if user is None and adapter.remote_path + " exec" in command
        )
        self.assertTrue(raw_codex_command.startswith("set -o pipefail; "))
        self.assertIn("--enable unified_exec", raw_codex_command)
        self.assertIn('model_reasoning_effort="medium"', raw_codex_command)
        self.assertEqual(raw_codex_command.count("set -o pipefail; "), 1)
        self.assertNotIn("2>&1", raw_codex_command)
        self.assertIn("2>/logs/agent/codex.stderr.txt", raw_codex_command)
        self.assertLess(
            raw_codex_command.index("set -o pipefail; "),
            raw_codex_command.index("| tee "),
        )
        with self.assertRaises(AdapterError):
            adapters_module._validate_safe_codex_command(
                raw_codex_command.replace(
                    "2>/logs/agent/codex.stderr.txt",
                    "2>&1",
                ),
                side=Side.CODEX,
                main_effort="medium",
                guardian_model="gpt-5.6-luna",
                guardian_effort="low",
            )
        with self.assertRaises(AdapterError):
            adapters_module._validate_safe_codex_command(
                raw_codex_command.replace("features.code_mode_host=true", ""),
                side=Side.CODEX,
                main_effort="medium",
                guardian_model="gpt-5.6-luna",
                guardian_effort="low",
            )
        with self.assertRaises(AdapterError):
            adapters_module._validate_safe_codex_command(
                raw_codex_command.replace(
                    "sandbox_workspace_write.network_access=true", ""
                ),
                side=Side.CODEX,
                main_effort="medium",
                guardian_model="gpt-5.6-luna",
                guardian_effort="low",
            )
        with self.assertRaises(AdapterError):
            adapters_module._validate_safe_codex_command(
                raw_codex_command.replace(
                    "features.code_mode_host=true",
                    "features.code_mode_host=false",
                ),
                side=Side.CODEX,
                main_effort="medium",
                guardian_model="gpt-5.6-luna",
                guardian_effort="low",
            )
        self.assertTrue(
            all(
                not call[1]
                or call[1]
                == {
                    "CODEX_HOME": "/tmp/rondo-eval-codex-home",
                    "GIT_CONFIG_GLOBAL": "/tmp/rondo-eval-codex-home/gitconfig",
                }
                for call in environment.calls
            )
        )
        self.assertIn("/run/secrets/rondo_eval_provider_api_key", commands)
        self.assertNotIn("auto_review.model", commands)
        self.assertNotIn("auto_review.reasoning_effort", commands)
        self.assertNotIn("auto_review.evidence_dir", commands)
        root_calls = [call for call in environment.calls if call[3] == "root"]
        agent_calls = [call for call in environment.calls if call[3] is None]
        self.assertEqual(len(root_calls), 1)
        self.assertEqual(len(agent_calls), 6)
        self.assertEqual(
            environment.effective_users,
            ["root", *("1000:1000" for _ in range(6))],
        )
        self.assertIn("task_workdir=$(pwd -P)", root_calls[0][0])
        self.assertIn(
            f'test "$task_workdir" = "{adapters_module.FIX_GIT_CANONICAL_WORKDIR}"',
            root_calls[0][0],
        )
        self.assertIn('test ! -L "$task_workdir"', root_calls[0][0])
        self.assertIn('chmod -R a+rwX -- "$task_workdir"', root_calls[0][0])
        self.assertNotIn("/logs/agent", root_calls[0][0])
        self.assertNotIn("/run/secrets/rondo_eval_provider_api_key", root_calls[0][0])
        self.assertNotIn("/tmp/rondo-eval", root_calls[0][0])
        self.assertNotIn("chown", commands)
        secret_agent_calls = [
            call
            for call in agent_calls
            if "/run/secrets/rondo_eval_provider_api_key" in call[0]
        ]
        self.assertEqual(len(secret_agent_calls), 2)
        self.assertTrue(any("stat -c '%u:%g'" in call[0] for call in secret_agent_calls))
        self.assertTrue(any("chmod 0600" in call[0] for call in secret_agent_calls))
        self.assertTrue(any("test -r /run/secrets/" in call[0] for call in secret_agent_calls))
        self.assertTrue(any("test ! -w /run/secrets/" in call[0] for call in secret_agent_calls))
        self.assertTrue(
            any(
                'test "$(id -u):$(id -g)" = "1000:1000"' in call[0]
                for call in agent_calls
            )
        )
        self.assertTrue(
            any(
                f'test "$task_workdir" = "{adapters_module.FIX_GIT_CANONICAL_WORKDIR}"'
                in call[0]
                for call in agent_calls
            )
        )
        self.assertTrue(any('.git/refs"' in call[0] for call in agent_calls))
        self.assertTrue(any('.git/logs"' in call[0] for call in agent_calls))
        self.assertTrue(any('.git/index"' in call[0] for call in agent_calls))
        self.assertTrue(
            any(
                'git config --global --replace-all safe.directory "$task_workdir"'
                in call[0]
                and "git config --global --replace-all user.name 'Test User'"
                in call[0]
                and "git config --global --replace-all user.email test@example.com"
                in call[0]
                and 'git -C "$task_workdir" status --porcelain=v1'
                in call[0]
                for call in agent_calls
            )
        )

        rondo = self.adapter(RondoUploadAdapter, extra_env={"OPENAI_API_KEY": secret})
        rondo_environment = FakeEnvironment()
        asyncio.run(rondo.run("repair the repository", rondo_environment, mock.Mock()))
        rondo_commands = "\n".join(call[0] for call in rondo_environment.calls)
        self.assertIn("features.code_mode_host=true", rondo_commands)
        self.assertIn('auto_review.model="gpt-5.6-luna"', rondo_commands)
        self.assertIn('auto_review.reasoning_effort="low"', rondo_commands)
        self.assertIn('auto_review.evidence_dir="/logs/agent/guardian-evidence"', rondo_commands)

    def test_adapter_non_git_task_uses_frozen_workdir_without_repo_precondition(self) -> None:
        adapter = self.adapter(
            RondoUploadAdapter,
            task_workdir="/app",
            task_requires_existing_git_repo=False,
        )
        environment = FakeEnvironment(resolved_pwd="/app")

        asyncio.run(adapter.run("do the task", environment, mock.Mock()))

        prepare = next(
            command
            for command, _env, _timeout, _user in environment.calls
            if "git config --global" in command
        )
        self.assertIn('test "$task_workdir" = "/app"', prepare)
        self.assertNotIn('test -d "$task_workdir/.git"', prepare)
        self.assertNotIn('git -C "$task_workdir" status', prepare)

    def test_adapter_run_rejects_root_workdir_and_permission_projection_failure(self) -> None:
        adapter = self.adapter()
        for environment in (
            FakeEnvironment(resolved_pwd="/"),
            FakeEnvironment(resolved_pwd="/tmp/unexpected"),
            FakeEnvironment(fail_command_contains="chmod -R a+rwX"),
        ):
            with self.subTest(environment=environment.__dict__):
                with self.assertRaises(AdapterError):
                    asyncio.run(
                        adapter.run("repair the repository", environment, mock.Mock())
                    )
                self.assertEqual(len(environment.calls), 1)
                command, _env, _timeout, user = environment.calls[0]
                self.assertEqual(user, "root")
                self.assertIn("task_workdir=$(pwd -P)", command)
                self.assertIn(
                    f'test "$task_workdir" = "{adapters_module.FIX_GIT_CANONICAL_WORKDIR}"',
                    command,
                )
                self.assertIn(
                    'chmod -R a+rwX -- "$task_workdir"', command
                )
                self.assertNotIn("chown", command)

    def test_adapter_run_rejects_unwritable_git_state_and_secret_owner_drift(self) -> None:
        adapter = self.adapter()
        git_environment = FakeEnvironment(fail_command_contains='.git/logs"')
        with self.assertRaisesRegex(AdapterError, "command_id=prepare_agent_and_git"):
            asyncio.run(
                adapter.run("repair the repository", git_environment, mock.Mock())
            )
        self.assertFalse(
            any(
                "OPENAI_API_KEY" in call[0]
                for call in git_environment.calls
            )
        )

        secret_environment = FakeEnvironment(
            remote_owners={
                "/run/secrets/rondo_eval_provider_api_key": "0:0"
            }
        )
        with self.assertRaisesRegex(AdapterError, "command_id=verify_secret_owner"):
            asyncio.run(
                adapter.run("repair the repository", secret_environment, mock.Mock())
            )
        commands = "\n".join(call[0] for call in secret_environment.calls)
        self.assertIn("stat -c '%u:%g' -- /run/secrets/", commands)
        self.assertNotIn("python3 -c", commands)
        self.assertNotIn("chown", commands)

        git_probe_environment = FakeEnvironment(
            fail_command_contains='git -C "$task_workdir" status'
        )
        with self.assertRaisesRegex(AdapterError, "command_id=prepare_agent_and_git"):
            asyncio.run(
                adapter.run("repair the repository", git_probe_environment, mock.Mock())
            )
        git_probe_commands = "\n".join(call[0] for call in git_probe_environment.calls)
        self.assertNotIn("/run/secrets/rondo_eval_provider_api_key", git_probe_commands)

    def test_checked_exec_diagnostic_is_bounded_and_secret_redacted(self) -> None:
        secret = "sk-secret-must-never-escape"

        class StderrEnvironment(FakeEnvironment):
            async def exec(self, command, **kwargs):
                self.calls.append((command, kwargs.get("env"), kwargs.get("timeout_sec"), kwargs.get("user")))
                return FakeExecResult(1, stdout=secret, stderr=f"permission denied {secret}")

        environment = StderrEnvironment()
        with self.assertRaises(AdapterError) as caught:
            asyncio.run(
                adapters_module._checked_exec(
                    environment,
                    f"unsafe-full-argv {secret}",
                    stage="install",
                    command_id="verify_bundle_sha256",
                )
            )
        rendered = str(caught.exception)
        self.assertEqual(caught.exception.stage, "install")
        self.assertEqual(caught.exception.command_id, "verify_bundle_sha256")
        self.assertEqual(caught.exception.stderr_summary, "permission_denied")
        self.assertNotIn(secret, rendered)
        self.assertNotIn("unsafe-full-argv", rendered)
        self.assertIsNone(caught.exception.__cause__)

        agent_environment = StderrEnvironment()
        with self.assertRaises(AdapterError) as agent_caught:
            asyncio.run(
                adapters_module._checked_exec_as_agent(
                    agent_environment,
                    command=f"unsafe-agent-command {secret}",
                    env={"CODEX_HOME": "/tmp/rondo-eval-codex-home"},
                    stage="run",
                    command_id="prepare_agent_and_git",
                )
            )
        agent_rendered = str(agent_caught.exception)
        self.assertEqual(agent_caught.exception.command_id, "prepare_agent_and_git")
        self.assertNotIn(secret, agent_rendered)
        self.assertNotIn("unsafe-agent-command", agent_rendered)
        self.assertIsNone(agent_caught.exception.__cause__)

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
        (task / "tests" / "test_outputs.py").write_text("def test_ok():\n    pass\n")
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
        self.assertIn(
            f"file: {json.dumps(str(result.provider_secret_path))}",
            overlay,
        )
        self.assertIn("source: rondo_eval_provider_api_key", overlay)
        self.assertEqual(result.provider_secret_path.read_bytes(), b"")
        self.assertEqual(result.provider_secret_path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            (result.task_path / "tests" / "test.sh").stat().st_mode & 0o777,
            0o555,
        )
        self.assertEqual(
            (result.task_path / "solution").stat().st_mode & 0o777,
            0o555,
        )
        self.assertEqual(
            (result.task_path / "solution" / "solve.sh").stat().st_mode & 0o777,
            0o555,
        )
        self.assertEqual(
            (result.task_path / "tests").stat().st_mode & 0o777,
            0o555,
        )
        self.assertEqual(
            (result.task_path / "tests" / "test_outputs.py").stat().st_mode & 0o777,
            0o444,
        )
        self.assertEqual(
            (result.task_path / "tests" / "rondo-apt.conf").read_text(),
            'APT::Sandbox::User "root";\n',
        )
        self.assertEqual(
            (result.task_path / "tests" / "rondo-apt.conf").stat().st_mode & 0o777,
            0o444,
        )
        self.assertIn('user: "1000:1000"', overlay)
        self.assertIn("    cap_drop:\n      - ALL\n", overlay)
        self.assertEqual(result.runtime_user, "1000:1000")
        staged_document = materialize_module._read_toml(result.task_path / "task.toml")
        self.assertEqual(staged_document["agent"]["user"], "1000:1000")
        self.assertEqual(staged_document["verifier"]["user"], "root")
        self.assertEqual(
            staged_document["verifier"]["env"],
            {
                "HOME": "/root",
                "APT_CONFIG": "/tests/rondo-apt.conf",
                "TAR_OPTIONS": "--no-same-owner",
            },
        )
        self.assertEqual(
            staged_document["solution"]["env"],
            {
                "GIT_CONFIG_COUNT": "3",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": "/app/personal-site",
                "GIT_CONFIG_KEY_1": "user.name",
                "GIT_CONFIG_VALUE_1": "Test User",
                "GIT_CONFIG_KEY_2": "user.email",
                "GIT_CONFIG_VALUE_2": "test@example.com",
            },
        )
        for field, value in (("user", "1000:1000"), ("env", {"HOME": "/tmp"})):
            with self.subTest(verifier_field=field):
                original = staged_document["verifier"][field]
                staged_document["verifier"][field] = value
                with self.assertRaises(MaterializationError):
                    materialize_module._validate_staged_task(staged_document)
                staged_document["verifier"][field] = original
        object.__setattr__(
            result,
            "staged_task_digest",
            materialize_module._harbor_content_digest(result.task_path),
        )
        original_overlay_sha256 = hashlib.sha256(
            result.overlay_path.read_bytes()
        ).hexdigest()
        object.__setattr__(result, "overlay_sha256", original_overlay_sha256)
        result.validate()
        for unsafe_line in (
            '    user: "0:0"\n',
            "    privileged: true\n",
            "    cap_add: [SYS_ADMIN]\n",
            '    security_opt: ["seccomp=unconfined"]\n',
        ):
            with self.subTest(unsafe_line=unsafe_line.strip()):
                result.overlay_path.write_text(
                    overlay.replace('    user: "1000:1000"\n', unsafe_line)
                )
                object.__setattr__(
                    result,
                    "overlay_sha256",
                    hashlib.sha256(result.overlay_path.read_bytes()).hexdigest(),
                )
                with self.assertRaises(MaterializationError):
                    result.validate()
        result.overlay_path.write_text(overlay)
        object.__setattr__(result, "overlay_sha256", original_overlay_sha256)
        result.validate()
        for drifted_cap_drop in (
            overlay.replace("    cap_drop:\n      - ALL\n", ""),
            overlay.replace("      - ALL\n", "      - NET_RAW\n"),
        ):
            result.overlay_path.write_text(drifted_cap_drop)
            object.__setattr__(
                result,
                "overlay_sha256",
                hashlib.sha256(result.overlay_path.read_bytes()).hexdigest(),
            )
            with self.assertRaises(MaterializationError):
                result.validate()
        result.overlay_path.write_text(overlay)
        object.__setattr__(result, "overlay_sha256", original_overlay_sha256)
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
        self.assertEqual(kwargs["injected_env"], {"HARBOR_TELEMETRY": "off"})
        self.assertEqual(executor.provider_secrets, [secret])
        self.assertEqual(prepared.materialized_task.provider_secret_path.read_bytes(), b"")
        self.assertEqual(kwargs["exact_task_label"], "dev.rondo.eval.task=p1-b3-rondo")
        self.assertEqual(kwargs["compose_contract"], prepared.command.compose_contract)

    def test_injected_backend_clears_provider_secret_after_executor_failure(self) -> None:
        prepared = self.prepare(Side.RONDO)

        class FailingExecutor(FakeHostExecutor):
            async def run(self, argv, **kwargs):
                await super().run(argv, **kwargs)
                raise RuntimeError("fake host failure")

        executor = FailingExecutor()
        backend = InjectedHostHarborBackend(
            executor,
            getenv=lambda name: "failure-secret" if name == "OPENAI_API_KEY" else None,
        )
        with self.assertRaisesRegex(RuntimeError, "fake host failure"):
            asyncio.run(UnifiedTerminalBenchRunner(backend).run(prepared))
        self.assertEqual(executor.provider_secrets, ["failure-secret"])
        self.assertEqual(prepared.materialized_task.provider_secret_path.read_bytes(), b"")

    def test_concrete_host_executor_uses_public_full_lifetime_supervisor(self) -> None:
        prepared = self.prepare()
        fake_supervisor = mock.Mock()
        fake_supervisor.resolve_image_identity.return_value = DockerImageIdentity(
            FIX_GIT_IMAGE_REF,
            f"sha256:{'a' * 64}",
        )
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
                    injected_env={"HARBOR_TELEMETRY": "off"},
                    timeout_seconds=prepared.spec.timeout_seconds,
                    exact_task_label=prepared.command.task_label,
                    compose_contract=prepared.command.compose_contract,
                )
            )

        self.assertEqual(result.docker_evidence.operation, DockerOperation.HOST)
        host_runner.assert_called_once_with(
            executable=runner_module.HARBOR_EXECUTABLE,
            cwd=EVAL_ROOT,
            environment={
                "HARBOR_TELEMETRY": "off",
                "PYTHONPATH": str(EVAL_ROOT),
            },
        )
        fake_supervisor.supervise_host_command.assert_called_once()
        fake_supervisor.resolve_image_identity.assert_called_once()
        bound_contract = fake_supervisor.supervise_host_command.call_args.kwargs[
            "compose_contract"
        ]
        self.assertTrue(bound_contract.container.require_image_identity)
        self.assertEqual(bound_contract.container.image_reference, FIX_GIT_IMAGE_REF)
        self.assertEqual(bound_contract.container.image_id, f"sha256:{'a' * 64}")

    def test_supervised_oracle_uses_no_model_key_or_custom_agent(self) -> None:
        prepared = self.prepare()
        materialized = prepared.materialized_task
        fake_supervisor = mock.Mock()
        fake_supervisor.resolve_image_identity.return_value = DockerImageIdentity(
            FIX_GIT_IMAGE_REF,
            f"sha256:{'a' * 64}",
        )
        fake_supervisor.supervise_host_command.return_value = DockerExecutionResult(
            operation=DockerOperation.HOST,
            argv=(),
            returncode=0,
            samples=(),
            warnings=(),
        )
        with mock.patch.object(runner_module, "SubprocessHostCommandRunner"), mock.patch.object(
            runner_module, "DockerSupervisor", return_value=fake_supervisor
        ):
            executor = DockerSupervisedHostHarborExecutor(
                counter=mock.Mock(),
                lock_guard=mock.Mock(),
                lease=HeavyLockLease(token="x" * 16, held=True),
            )
            result = asyncio.run(
                executor.run_oracle(materialized, timeout_seconds=1800)
            )

        self.assertEqual(result.returncode, 0)
        argv = fake_supervisor.supervise_host_command.call_args.args[1]
        self.assertEqual(argv[1:3], ("trials", "start"))
        self.assertEqual(
            argv[argv.index("--agent") + 1],
            "rondo_eval.terminal_bench.oracle_smoke:PreparedOracleAgent",
        )
        self.assertNotIn("--model", argv)
        self.assertEqual(
            argv[argv.index("--agent-kwarg") + 1],
            f"task_dir={materialized.task_path}",
        )
        self.assertNotIn("--agent-env", argv)
        self.assertEqual(materialized.provider_secret_path.read_bytes(), b"")
        contract = fake_supervisor.supervise_host_command.call_args.kwargs[
            "compose_contract"
        ]
        self.assertTrue(contract.container.require_container_metrics)
        self.assertEqual(contract.container.user, "1000:1000")

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
                "review_id": "review-1",
                "guardian_source_baseline": "rust-v0.147.0",
                "guardian_source_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                "evidence": "e_final",
                "decision": "approved",
                "failure_reason": None,
                "attempt_count": 1,
                "duration_ms": 10,
                "guardian_thread_id": "thread-1",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "low",
                "terminal_status": "approved",
                "token_usage": None,
                "time_to_first_token_ms": None,
            })
        )
        metadata = self.root / "api-metadata.json"
        metadata.write_text(json.dumps({
            "schema_version": 1,
            "requests": [{
                "role": "guardian",
                "body_sha256": "a" * 64,
                "canonical_body_sha256": "b" * 64,
                "role_provenance": "declared",
                "declared_role": "guardian",
                "inferred_role": "guardian",
                "contract_match": True,
                "usage_valid": True,
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 0,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 2,
                },
                "attempt_count": 1,
                "settlement_kind": "usage_priced",
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
        pair_identity = mock.Mock()
        pair_identity.require_selected_profile.return_value = SimpleNamespace(
            max_guardian_logical_requests=1
        )
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
                pair_identity=pair_identity,
                materializer=materializer,
            ))

        self.assertTrue(result.metadata_ready)
        self.assertEqual(len(result.evidence), 1)
        self.assertTrue(result.evidence[0].policy.aggregatable)
        self.assertEqual(
            observed["env"],
            {"HARBOR_TELEMETRY": "off"},
        )
        self.assertNotIn("official-key-sentinel", "\0".join(observed["argv"]))
        self.assertEqual(FakeBudgetProxy.last_kwargs["timeout_seconds"], 90.0)
        self.assertEqual(
            FakeBudgetProxy.last_kwargs["max_guardian_logical_requests"], 1
        )
        self.assertNotEqual(
            FakeBudgetProxy.last_kwargs["timeout_seconds"],
            self.request(Side.RONDO).timeout_seconds,
        )

    def test_budgeted_frozen_live_path_projects_source_bound_catalog(self) -> None:
        jobs = self.root / "jobs-codex"
        jobs.mkdir()
        metadata = self.root / "api-metadata.json"
        metadata.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "requests": [
                        {
                            "role": "main",
                            "role_provenance": "declared",
                            "declared_role": "main",
                            "inferred_role": "main",
                            "contract_match": True,
                            "usage_valid": True,
                            "usage": {
                                "input_tokens": 10,
                                "cached_input_tokens": 0,
                                "cache_write_input_tokens": 0,
                                "output_tokens": 2,
                            },
                            "attempt_count": 1,
                            "settlement_kind": "usage_priced",
                        }
                    ],
                }
            )
        )
        catalog_bytes = b'{"models":[]}\n'
        catalog_sha256 = hashlib.sha256(catalog_bytes).hexdigest()
        projection = mock.Mock(
            source_commit=self.manifest().source_commit,
            sha256=catalog_sha256,
        )

        def write_private(path: Path) -> None:
            path.write_bytes(catalog_bytes)
            path.chmod(0o400)

        projection.write_private.side_effect = write_private
        observed: dict[str, object] = {}

        class FakeSupervisedExecutor:
            def __init__(self, **kwargs):
                observed["constructor"] = kwargs

            async def run(self, argv, **kwargs):
                observed["argv"] = argv
                return HostHarborResult(0, jobs)

        config = self.runtime_config()
        config.paths.common_root = self.root
        materializer = FakeMaterializer(self.root / "fake-live-codex")
        materializer.root.mkdir()
        ledger_path = self.root / "budget-codex.json"
        loader = mock.Mock(return_value=projection)
        pair_identity = mock.Mock()
        pair_identity.require_selected_profile.return_value = SimpleNamespace(
            max_guardian_logical_requests=1
        )
        with PersistentBudgetLedger(
            ledger_path,
            batch_id="p1-live-codex",
        ) as ledger, mock.patch.object(
            live_module,
            "LoopbackResponsesProxy",
            FakeBudgetProxy,
        ), mock.patch.object(
            live_module,
            "DockerSupervisedHostHarborExecutor",
            FakeSupervisedExecutor,
        ), mock.patch.object(
            live_module,
            "load_frozen_model_catalog",
            loader,
        ):
            result = asyncio.run(
                live_module.run_budgeted_terminal_bench(
                    config,
                    self.request(Side.CODEX),
                    api_key="official-key-sentinel",
                    ledger=ledger,
                    metadata_path=metadata,
                    counter=mock.Mock(),
                    lock_guard=mock.Mock(),
                    lease=HeavyLockLease(token="x" * 16, held=True),
                    pair_identity=pair_identity,
                    materializer=materializer,
                )
            )

        loader.assert_called_once_with(
            self.root,
            source_commit=self.manifest().source_commit,
            main_model="gpt-5.6-sol",
            guardian_model="gpt-5.6-luna",
        )
        projection.write_private.assert_called_once_with(
            metadata.with_name("frozen-model-catalog.json")
        )
        self.assertEqual(
            result.prepared.adapter._frozen_model_catalog_sha256,
            catalog_sha256,
        )
        self.assertIn(
            f"frozen_model_catalog_sha256={catalog_sha256}",
            "\0".join(observed["argv"]),
        )

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
build_timeout_sec = 600.0
docker_image = "{FIX_GIT_IMAGE_TAG}"
cpus = 1
memory_mb = 2048
storage_mb = 10240
gpus = 0
allow_internet = true

[verifier.env]

[environment.env]

[solution.env]
'''


if __name__ == "__main__":
    unittest.main()
