"""One frozen preparation and injected host-execution path for both sides."""

from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .. import config as config_module
from ..config import RuntimeConfig
from ..contracts import BinaryManifest, RunSpec, Side
from ..docker_supervisor import (
    ComposeRunContract,
    DockerCounter,
    DockerExecutionResult,
    DockerMountFact,
    DockerSupervisor,
    DockerTaskIdentity,
    HeavyLockGuard,
    HeavyLockLease,
    HostContainerContract,
)
from ..runtime_bridge import SubprocessDockerCommandRunner, SubprocessHostCommandRunner
from .adapters import UploadBinaryAdapter, adapter_for, manifest_agent_kwargs
from .freeze import (
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_IMAGE_REF,
    FIX_GIT_TASK_ID,
    TERMINAL_BENCH_REPO_REF,
    TERMINAL_BENCH_VERSION,
    validate_freeze,
    validate_runtime_image_digest,
)
from .materialize import (
    TERMINAL_BENCH_WORKDIR,
    MaterializedTask,
    PinnedTaskMaterializer,
)
from .tasksets import FrozenTask


EVAL_ROOT = Path(__file__).resolve().parents[2]
HARBOR_EXECUTABLE = Path(sys.executable).with_name("harbor")
ADAPTER_IMPORTS = {
    Side.CODEX: "rondo_eval.terminal_bench.adapters:CodexUploadAdapter",
    Side.RONDO: "rondo_eval.terminal_bench.adapters:RondoUploadAdapter",
}


class TerminalBenchRunError(ValueError):
    """Raised before Harbor is invoked when the frozen command is inconsistent."""


@dataclass(frozen=True)
class TerminalBenchRequest:
    side: Side
    batch_id: str
    binary: BinaryManifest
    image_digest: str
    source_checkout: str
    staging_root: str
    docker_task_id: str
    memory_bytes: int
    memory_swap_bytes: int
    pids_limit: int
    provider_transport_base_url: str
    provider_name: str | None = None
    timeout_seconds: int = 1800
    max_retries: int = 0
    budget_usd: float = 5.0
    seccomp_profile_path: str | None = None
    seccomp_profile_source_sha256: str | None = None
    seccomp_profile_effective_sha256: str | None = None
    require_container_metrics: bool = False
    frozen_model_catalog_path: str | None = None
    frozen_model_catalog_sha256: str | None = None
    frozen_model_catalog_source_commit: str | None = None
    frozen_task: FrozenTask | None = None


@dataclass(frozen=True)
class HarborCommand:
    """Auditable Harbor command with secret names but never secret values."""

    argv: tuple[str, ...]
    cwd: Path
    env: tuple[tuple[str, str], ...]
    required_secret_env: str
    provider_transport_base_url: str
    image_ref: str
    require_container_metrics: bool
    source_repo_ref: str
    task_source_digest: str
    task_label: str
    trial_name: str
    trials_dir: Path
    compose_contract: ComposeRunContract
    n_concurrent: int = 1

    def validate(
        self,
        spec: RunSpec,
        adapter: UploadBinaryAdapter,
        materialized: MaterializedTask,
    ) -> None:
        if self.env != (("HARBOR_TELEMETRY", "off"),):
            raise TerminalBenchRunError("Harbor telemetry must be disabled")
        if self.required_secret_env != spec.provider.api_key_env:
            raise TerminalBenchRunError("Harbor provider key projection differs from RunSpec")
        if self.provider_transport_base_url != adapter.provider_base_url:
            raise TerminalBenchRunError("Harbor provider transport differs from the adapter")
        _validate_budget_proxy_transport(self.provider_transport_base_url)
        if materialized.provider_api_key_env != spec.provider.api_key_env:
            raise TerminalBenchRunError("Compose secret source differs from RunSpec")
        if self.n_concurrent != 1 or spec.max_retries != 0:
            raise TerminalBenchRunError("Terminal-Bench P1 permits one task and no retries")
        if self.trial_name != _trial_name(materialized.task_label, spec.side):
            raise TerminalBenchRunError("Harbor trial identity differs from the frozen run")
        if self.trials_dir != materialized.task_path.parent / "trials":
            raise TerminalBenchRunError("Harbor trials directory differs from the frozen run")
        expected_contract = _compose_run_contract(
            materialized,
            trial_name=self.trial_name,
            trials_dir=self.trials_dir,
            require_container_metrics=self.require_container_metrics,
        )
        if self.compose_contract != expected_contract:
            raise TerminalBenchRunError("Docker Compose contract differs from the frozen trial")
        self.compose_contract.validate()
        expected = _harbor_argv(
            spec,
            adapter,
            materialized,
            trial_name=self.trial_name,
            trials_dir=self.trials_dir,
        )
        if self.argv != expected:
            raise TerminalBenchRunError("Harbor command differs from the frozen local-task form")
        if self.cwd != EVAL_ROOT:
            raise TerminalBenchRunError("Harbor must run from the locked eval project")
        if (
            self.image_ref != materialized.runtime_image_ref
            or self.source_repo_ref != TERMINAL_BENCH_REPO_REF
            or self.source_repo_ref != materialized.source_repo_ref
            or self.task_source_digest != materialized.source_digest
            or self.task_label != materialized.task_label
        ):
            raise TerminalBenchRunError("Harbor task materialization provenance differs")
        joined = "\0".join(self.argv)
        forbidden = (
            "--repo",
            "--task",
            "--dataset",
            "--upload",
            "--yes",
            "--env-file",
            "--agent-env",
            "--dangerously-bypass-approvals-and-sandbox",
        )
        if any(value in self.argv or value in joined for value in forbidden):
            raise TerminalBenchRunError("Harbor command contains a forbidden external path")
        if spec.task_image_digest not in materialized.runtime_image_ref:
            raise TerminalBenchRunError("Harbor task image differs from RunSpec")


@dataclass(frozen=True)
class PreparedTerminalBenchRun:
    spec: RunSpec
    command: HarborCommand
    adapter: UploadBinaryAdapter
    materialized_task: MaterializedTask

    def validate(self) -> None:
        self.spec.validate()
        self.materialized_task.validate()
        if self.spec.task_id != self.materialized_task.task_id:
            raise TerminalBenchRunError("RunSpec task differs from its materialization")
        if self.spec.terminal_bench_version != TERMINAL_BENCH_VERSION:
            raise TerminalBenchRunError("RunSpec Terminal-Bench version is not commit-pinned")
        if self.spec.task_image_digest != self.materialized_task.image_digest:
            raise TerminalBenchRunError("RunSpec image differs from its materialization")
        if self.spec.binary.source_dirty:
            raise TerminalBenchRunError("Terminal-Bench requires a clean binary source commit")
        if self.spec.side is not self.adapter.side or self.spec.binary != self.adapter.manifest:
            raise TerminalBenchRunError("adapter and RunSpec binary identity differ")
        self.adapter.validate_local_binary()
        self.command.validate(self.spec, self.adapter, self.materialized_task)


@dataclass(frozen=True)
class HostHarborResult:
    """Deliberately excludes stdout/stderr so secrets cannot be echoed by this API."""

    returncode: int
    trial_dir: Path
    docker_evidence: DockerExecutionResult | None = None

    @property
    def jobs_dir(self) -> Path:
        """Compatibility name for the exact single-trial evidence root."""

        return self.trial_dir


class HostHarborExecutor(Protocol):
    """Runs the host process under the shared lock and Docker supervisor.

    ``injected_env`` contains only non-secret process configuration.  The task
    secret is exposed solely through the exact read-only Compose mount in the
    frozen container contract.
    Implementations must extend a safe host environment without logging values,
    supervise all label-matching containers for the full process lifetime, and
    return no captured output containing environment values.
    """

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        injected_env: Mapping[str, str],
        timeout_seconds: int,
        exact_task_label: str,
        image_reference: str,
        compose_contract: ComposeRunContract,
    ) -> HostHarborResult: ...


class RunnerBackend(Protocol):
    async def run(self, prepared: PreparedTerminalBenchRun) -> HostHarborResult: ...


class InjectedHostHarborBackend:
    """Production wiring around an injected, supervisor-aware host executor."""

    def __init__(
        self,
        executor: HostHarborExecutor,
        *,
        getenv: Callable[[str], str | None] = os.environ.get,
    ) -> None:
        self._executor = executor
        self._getenv = getenv

    async def run(self, prepared: PreparedTerminalBenchRun) -> HostHarborResult:
        prepared.validate()
        secret_name = prepared.command.required_secret_env
        secret = self._getenv(secret_name)
        if not isinstance(secret, str) or not secret:
            raise TerminalBenchRunError("the projected provider key is unavailable")
        if secret in prepared.command.argv or secret in str(prepared.command):
            raise TerminalBenchRunError("provider key reached the serialized Harbor command")
        _replace_provider_secret(prepared.materialized_task.provider_secret_path, secret)
        try:
            result = await self._executor.run(
                prepared.command.argv,
                cwd=prepared.command.cwd,
                injected_env=dict(prepared.command.env),
                timeout_seconds=prepared.spec.timeout_seconds,
                exact_task_label=prepared.command.task_label,
                image_reference=prepared.command.image_ref,
                compose_contract=prepared.command.compose_contract,
            )
            if not isinstance(result, HostHarborResult):
                raise TerminalBenchRunError("host Harbor executor returned an invalid result")
            return result
        finally:
            _replace_provider_secret(prepared.materialized_task.provider_secret_path, "")


class DockerSupervisedHostHarborExecutor:
    """Concrete Harbor executor using DockerSupervisor for the whole host process."""

    def __init__(
        self,
        *,
        counter: DockerCounter,
        lock_guard: HeavyLockGuard,
        lease: HeavyLockLease,
        harbor_executable: Path = HARBOR_EXECUTABLE,
    ) -> None:
        lease.validate()
        self._counter = counter
        self._lock_guard = lock_guard
        self._lease = lease
        self._harbor_executable = harbor_executable

    async def run(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        injected_env: Mapping[str, str],
        timeout_seconds: int,
        exact_task_label: str,
        image_reference: str,
        compose_contract: ComposeRunContract,
    ) -> HostHarborResult:
        _require_budget_proxy_argv(argv)
        return await self._run_supervised(
            argv,
            cwd=cwd,
            injected_env=injected_env,
            timeout_seconds=timeout_seconds,
            exact_task_label=exact_task_label,
            image_reference=image_reference,
            compose_contract=compose_contract,
        )

    async def run_oracle(
        self,
        materialized: MaterializedTask,
        *,
        timeout_seconds: int,
    ) -> HostHarborResult:
        """Run Harbor's frozen oracle without loading or mounting a real key."""

        materialized.validate()
        trial_name = _oracle_trial_name(materialized.task_label)
        trials_dir = materialized.task_path.parent / "trials"
        argv = _harbor_oracle_argv(
            materialized,
            trial_name=trial_name,
            trials_dir=trials_dir,
        )
        return await self._run_supervised(
            argv,
            cwd=EVAL_ROOT,
            injected_env={"HARBOR_TELEMETRY": "off"},
            timeout_seconds=timeout_seconds,
            exact_task_label=materialized.task_label,
            image_reference=materialized.runtime_image_ref,
            compose_contract=_compose_run_contract(
                materialized,
                trial_name=trial_name,
                trials_dir=trials_dir,
                require_container_metrics=True,
            ),
        )

    async def _run_supervised(
        self,
        argv: tuple[str, ...],
        *,
        cwd: Path,
        injected_env: Mapping[str, str],
        timeout_seconds: int,
        exact_task_label: str,
        image_reference: str,
        compose_contract: ComposeRunContract,
    ) -> HostHarborResult:
        prefix = "dev.rondo.eval.task="
        if not exact_task_label.startswith(prefix):
            raise TerminalBenchRunError("host Harbor task label is invalid")
        identity = DockerTaskIdentity(exact_task_label.removeprefix(prefix))
        identity.validate()
        if identity.label != exact_task_label:
            raise TerminalBenchRunError("host Harbor task label is not exact")
        if not argv or Path(argv[0]) != self._harbor_executable:
            raise TerminalBenchRunError("host Harbor executable differs from the freeze")
        if cwd != EVAL_ROOT:
            raise TerminalBenchRunError("host Harbor cwd differs from the locked eval project")
        if dict(injected_env) != {"HARBOR_TELEMETRY": "off"}:
            raise TerminalBenchRunError("host Harbor environment is not minimally scoped")
        host_environment = dict(injected_env)
        # ``rondo-eval`` is deliberately a non-installed uv project.  Harbor
        # imports the custom adapter in its own child interpreter, so project
        # code must be made available explicitly instead of relying on the
        # parent process's ambient PYTHONPATH.
        host_environment["PYTHONPATH"] = str(EVAL_ROOT)
        runner = SubprocessHostCommandRunner(
            executable=self._harbor_executable,
            cwd=cwd,
            environment=host_environment,
        )
        supervisor = DockerSupervisor(
            runner=runner,
            counter=self._counter,
            lock_guard=self._lock_guard,
            cleanup_runner=SubprocessDockerCommandRunner(),
        )
        image_identity = supervisor.resolve_image_identity(
            identity,
            image_reference,
            lease=self._lease,
            timeout_seconds=5,
        )
        bound_container = replace(
            compose_contract.container,
            image_reference=image_identity.image_reference,
            image_id=image_identity.image_id,
            require_image_identity=True,
        )
        bound_contract = replace(compose_contract, container=bound_container)
        evidence = await asyncio.to_thread(
            supervisor.supervise_host_command,
            identity,
            argv,
            lease=self._lease,
            timeout_seconds=timeout_seconds,
            compose_contract=bound_contract,
        )
        trials_dir = Path(argv[argv.index("--trials-dir") + 1])
        trial_name = argv[argv.index("--trial-name") + 1]
        return HostHarborResult(
            returncode=evidence.returncode,
            trial_dir=trials_dir / trial_name,
            docker_evidence=evidence,
        )


class UnifiedTerminalBenchRunner:
    """Validate one shared RunSpec, then invoke the injected Harbor backend."""

    def __init__(self, backend: RunnerBackend) -> None:
        self._backend = backend

    async def run(self, prepared: PreparedTerminalBenchRun) -> HostHarborResult:
        prepared.validate()
        return await self._backend.run(prepared)


class TaskMaterializer(Protocol):
    def materialize(self, **kwargs) -> MaterializedTask: ...


def prepare_terminal_bench_run(
    config: RuntimeConfig,
    request: TerminalBenchRequest,
    *,
    materializer: TaskMaterializer | None = None,
) -> PreparedTerminalBenchRun:
    """Create the sole B2 projection from config, pinned source, image and binary."""

    validate_freeze()
    frozen_task = request.frozen_task
    if frozen_task is None:
        image_digest = validate_runtime_image_digest(request.image_digest)
        task_id = FIX_GIT_TASK_ID
        task_slug = "fix-git"
    else:
        frozen_task.validate()
        if request.image_digest != frozen_task.image_digest:
            raise TerminalBenchRunError("request image differs from the frozen task")
        image_digest = frozen_task.image_digest
        task_id = frozen_task.task_id
        task_slug = frozen_task.slug
    seccomp_values = (
        request.seccomp_profile_path,
        request.seccomp_profile_source_sha256,
        request.seccomp_profile_effective_sha256,
    )
    if any(value is not None for value in seccomp_values) and (
        not all(value is not None for value in seccomp_values)
        or not Path(request.seccomp_profile_path or "").is_absolute()
    ):
        raise TerminalBenchRunError("Terminal-Bench seccomp profile is incomplete")
    if not isinstance(request.require_container_metrics, bool):
        raise TerminalBenchRunError("Terminal-Bench container metric gate is invalid")
    _validate_frozen_model_catalog_request(config, request)
    if request.max_retries != 0:
        raise TerminalBenchRunError("Terminal-Bench P1 retries are disabled")
    spec = config_module.make_run_spec(
        config,
        side=request.side,
        batch_id=request.batch_id,
        task_id=task_id,
        task_image_digest=image_digest,
        binary=request.binary,
        terminal_bench_version=TERMINAL_BENCH_VERSION,
        provider_name=request.provider_name,
        timeout_seconds=request.timeout_seconds,
        max_retries=request.max_retries,
        budget_usd=request.budget_usd,
    )
    task_label = _task_label(request.docker_task_id)
    materialized = (materializer or PinnedTaskMaterializer()).materialize(
        source_checkout=Path(request.source_checkout),
        staging_root=Path(request.staging_root),
        staging_name=f"{request.batch_id}-{request.side.value}-{task_slug}",
        image_digest=image_digest,
        task_label=task_label,
        memory_bytes=request.memory_bytes,
        memory_swap_bytes=request.memory_swap_bytes,
        pids_limit=request.pids_limit,
        provider_api_key_env=spec.provider.api_key_env,
        frozen_task=frozen_task,
        seccomp_profile=(
            Path(request.seccomp_profile_path)
            if request.seccomp_profile_path is not None
            else None
        ),
        seccomp_profile_source_sha256=request.seccomp_profile_source_sha256,
        seccomp_profile_effective_sha256=request.seccomp_profile_effective_sha256,
    )
    materialized.validate()
    transport_base_url = _validate_budget_proxy_transport(
        request.provider_transport_base_url
    )
    model_name = f"{spec.provider.provider_id}/{spec.provider.main_model}"
    adapter = adapter_for(
        request.side,
        request.binary,
        logs_dir=Path(request.staging_root) / "adapter-construction-check",
        model_name=model_name,
        provider_base_url=transport_base_url,
        provider_api_key_env=spec.provider.api_key_env,
        main_effort=spec.provider.main_effort,
        guardian_model=spec.provider.guardian_model,
        guardian_effort=spec.provider.guardian_effort,
        task_workdir=(
            frozen_task.workdir
            if frozen_task is not None
            else "/app/personal-site"
        ),
        task_requires_existing_git_repo=(
            frozen_task.requires_existing_git_repo
            if frozen_task is not None
            else True
        ),
        frozen_model_catalog_path=request.frozen_model_catalog_path,
        frozen_model_catalog_sha256=request.frozen_model_catalog_sha256,
        frozen_model_catalog_source_commit=request.frozen_model_catalog_source_commit,
    )
    trial_name = _trial_name(materialized.task_label, spec.side)
    trials_dir = materialized.task_path.parent / "trials"
    command = HarborCommand(
        argv=_harbor_argv(
            spec,
            adapter,
            materialized,
            trial_name=trial_name,
            trials_dir=trials_dir,
        ),
        cwd=EVAL_ROOT,
        env=(("HARBOR_TELEMETRY", "off"),),
        required_secret_env=spec.provider.api_key_env,
        provider_transport_base_url=transport_base_url,
        image_ref=materialized.runtime_image_ref,
        require_container_metrics=request.require_container_metrics,
        source_repo_ref=materialized.source_repo_ref,
        task_source_digest=materialized.source_digest,
        task_label=materialized.task_label,
        trial_name=trial_name,
        trials_dir=trials_dir,
        compose_contract=_compose_run_contract(
            materialized,
            trial_name=trial_name,
            trials_dir=trials_dir,
            require_container_metrics=request.require_container_metrics,
        ),
    )
    prepared = PreparedTerminalBenchRun(
        spec=spec,
        command=command,
        adapter=adapter,
        materialized_task=materialized,
    )
    prepared.validate()
    return prepared


def _validate_frozen_model_catalog_request(
    config: RuntimeConfig,
    request: TerminalBenchRequest,
) -> None:
    values = (
        request.frozen_model_catalog_path,
        request.frozen_model_catalog_sha256,
        request.frozen_model_catalog_source_commit,
    )
    if request.side is Side.RONDO:
        if any(value is not None for value in values):
            raise TerminalBenchRunError("RONDO cannot receive a frozen model catalog")
        return
    if all(value is None for value in values):
        return
    if not all(isinstance(value, str) and value for value in values):
        raise TerminalBenchRunError("frozen model catalog identity is incomplete")
    path = Path(request.frozen_model_catalog_path or "")
    try:
        common_root = config.paths.common_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        metadata = path.lstat()
        raw = path.read_bytes()
    except OSError as exc:
        raise TerminalBenchRunError("frozen model catalog is unavailable") from exc
    if (
        not path.is_absolute()
        or path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or not resolved.is_relative_to(common_root)
        or not raw
        or len(raw) > 4 * 1024 * 1024
    ):
        raise TerminalBenchRunError("frozen model catalog file is unsafe")
    expected_sha256 = request.frozen_model_catalog_sha256 or ""
    if (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
        or hashlib.sha256(raw).hexdigest() != expected_sha256
        or request.frozen_model_catalog_source_commit != request.binary.source_commit
    ):
        raise TerminalBenchRunError("frozen model catalog identity differs")


def _harbor_argv(
    spec: RunSpec,
    adapter: UploadBinaryAdapter,
    materialized: MaterializedTask,
    *,
    trial_name: str,
    trials_dir: Path,
) -> tuple[str, ...]:
    argv = [
        str(HARBOR_EXECUTABLE),
        "trials",
        "start",
        "--path",
        str(materialized.task_path),
        "--trial-name",
        trial_name,
        "--trials-dir",
        str(trials_dir),
        "--extra-docker-compose",
        str(materialized.overlay_path),
        "--agent",
        ADAPTER_IMPORTS[spec.side],
        "--model",
        f"{spec.provider.provider_id}/{spec.provider.main_model}",
    ]
    for key, value in manifest_agent_kwargs(adapter):
        if "\x00" in value or "\n" in value or "\r" in value:
            raise TerminalBenchRunError("agent kwarg is unsafe")
        argv.extend(("--agent-kwarg", f"{key}={value}"))
    argv.extend(
        (
            # Harbor may delete only the environment it creates for this one
            # staged task; the exact label keeps outer ownership observable.
            "--delete",
        )
    )
    return tuple(argv)


def _trial_name(task_label: str, side: Side) -> str:
    """Return a deterministic, Compose-safe and run-unique Harbor trial name."""

    task_id = task_label.removeprefix("dev.rondo.eval.task=")
    if not task_id or task_id == task_label:
        raise TerminalBenchRunError("Docker task label is invalid")
    suffix = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    return f"rondo-p1-{side.value}-{suffix}"


def _oracle_trial_name(task_label: str) -> str:
    task_id = task_label.removeprefix("dev.rondo.eval.task=")
    if not task_id or task_id == task_label:
        raise TerminalBenchRunError("Docker task label is invalid")
    suffix = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:12]
    return f"rondo-p1-oracle-{suffix}"


def _harbor_oracle_argv(
    materialized: MaterializedTask,
    *,
    trial_name: str,
    trials_dir: Path,
) -> tuple[str, ...]:
    frozen_task = materialized.frozen_task
    task_workdir = (
        frozen_task.workdir if frozen_task is not None else TERMINAL_BENCH_WORKDIR
    )
    agent_timeout_seconds = (
        frozen_task.agent_timeout_seconds if frozen_task is not None else 900
    )
    expected = (
        str(HARBOR_EXECUTABLE),
        "trials",
        "start",
        "--path",
        str(materialized.task_path),
        "--trial-name",
        trial_name,
        "--trials-dir",
        str(trials_dir),
        "--extra-docker-compose",
        str(materialized.overlay_path),
        "--agent",
        "rondo_eval.terminal_bench.oracle_smoke:PreparedOracleAgent",
        "--agent-kwarg",
        f"task_dir={materialized.task_path}",
        "--agent-kwarg",
        f"task_workdir={task_workdir}",
        "--agent-kwarg",
        f"agent_timeout_seconds={agent_timeout_seconds}",
        "--delete",
    )
    if any(
        token in expected
        for token in ("--model", "--agent-env", "--env-file")
    ):
        raise TerminalBenchRunError("oracle command contains provider configuration")
    if expected.count("--agent-kwarg") != 3:
        raise TerminalBenchRunError("oracle command task path projection is ambiguous")
    return expected


def _compose_run_contract(
    materialized: MaterializedTask,
    *,
    trial_name: str,
    trials_dir: Path,
    require_container_metrics: bool,
) -> ComposeRunContract:
    """Project Harbor 0.20's fixed single-trial Compose topology exactly."""

    project = f"{trial_name}__env"
    network = f"{project}_default"
    trial_dir = trials_dir / trial_name
    mounts = (
        DockerMountFact("bind", str(trial_dir / "verifier"), "/logs/verifier", False),
        DockerMountFact("bind", str(trial_dir / "agent"), "/logs/agent", False),
        DockerMountFact(
            "bind",
            str(trial_dir / "artifacts" / "logs" / "artifacts"),
            "/logs/artifacts",
            False,
        ),
        DockerMountFact(
            "bind",
            str(materialized.provider_secret_path),
            "/run/secrets/rondo_eval_provider_api_key",
            True,
        ),
    )
    security_opt: tuple[str, ...] = ()
    seccomp_profile_sha256 = None
    if materialized.seccomp_profile is not None:
        security_opt = ("no-new-privileges:true",)
        seccomp_profile_sha256 = materialized.seccomp_profile_effective_sha256
    return ComposeRunContract(
        container=HostContainerContract(
            user=materialized.runtime_user,
            memory_bytes=materialized.memory_bytes,
            memory_swap_bytes=materialized.memory_swap_bytes,
            pids_limit=materialized.pids_limit,
            compose_project=project,
            compose_service="main",
            network_mode=network,
            networks=(network,),
            mounts=mounts,
            cap_drop=("ALL",),
            require_container_metrics=require_container_metrics,
            compose_secret_mount=None,
            security_opt=security_opt,
            seccomp_profile_sha256=seccomp_profile_sha256,
        ),
        network_names=(network,),
        volume_names=(),
    )


def _task_label(task_id: str) -> str:
    if not task_id or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for character in task_id
    ):
        raise TerminalBenchRunError("Docker task id is unsafe")
    return f"dev.rondo.eval.task={task_id}"


def _replace_provider_secret(path: Path, value: str) -> None:
    if not isinstance(value, str) or "\0" in value or "\r" in value or "\n" in value:
        raise TerminalBenchRunError("provider key cannot be represented as a Compose secret")
    payload = value.encode("utf-8")
    if len(payload) > 16 * 1024:
        raise TerminalBenchRunError("provider key exceeds the bounded Compose secret size")
    try:
        before = path.lstat()
        flags = os.O_WRONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                path.is_symlink()
                or not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o600
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            ):
                raise TerminalBenchRunError("provider secret placeholder identity changed")
            os.ftruncate(descriptor, 0)
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise OSError("provider secret write made no progress")
                offset += written
            os.fsync(descriptor)
            after_write = os.fstat(descriptor)
            if after_write.st_size != len(payload):
                raise TerminalBenchRunError("provider secret write was incomplete")
        finally:
            os.close(descriptor)
        after = path.lstat()
        if path.is_symlink() or (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino):
            raise TerminalBenchRunError("provider secret placeholder changed after write")
    except TerminalBenchRunError:
        raise
    except (OSError, UnicodeError) as exc:
        raise TerminalBenchRunError("provider secret placeholder could not be updated") from exc


def _validate_budget_proxy_transport(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise TerminalBenchRunError("provider transport URL is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname != "host.docker.internal"
        or port is None
        or not 1 <= port <= 65535
        or parsed.path.rstrip("/") != "/v1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise TerminalBenchRunError("paid runs require the Docker loopback budget proxy")
    return value


def _require_budget_proxy_argv(argv: tuple[str, ...]) -> None:
    values = [
        argv[index + 1]
        for index, item in enumerate(argv[:-1])
        if item == "--agent-kwarg" and argv[index + 1].startswith("provider_base_url=")
    ]
    if len(values) != 1:
        raise TerminalBenchRunError("Harbor command has no unique provider transport")
    _validate_budget_proxy_transport(values[0].removeprefix("provider_base_url="))
