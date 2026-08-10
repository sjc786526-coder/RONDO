"""One frozen preparation and injected host-execution path for both sides."""

from __future__ import annotations

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .. import config as config_module
from ..config import RuntimeConfig
from ..contracts import BinaryManifest, RunSpec, Side
from ..docker_supervisor import (
    ComposeRunContract,
    ComposeSecretMountContract,
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
from .materialize import MaterializedTask, PinnedTaskMaterializer


EVAL_ROOT = Path(__file__).resolve().parents[2]
HARBOR_EXECUTABLE = EVAL_ROOT / ".venv" / "bin" / "harbor"
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
    provider_name: str = "openai"
    timeout_seconds: int = 1800
    max_retries: int = 0
    budget_usd: float = 5.0


@dataclass(frozen=True)
class HarborCommand:
    """Auditable Harbor command with secret names but never secret values."""

    argv: tuple[str, ...]
    cwd: Path
    env: tuple[tuple[str, str], ...]
    required_secret_env: str
    provider_transport_base_url: str
    image_ref: str
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
            self.image_ref != FIX_GIT_IMAGE_REF
            or self.image_ref != materialized.runtime_image_ref
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
        if FIX_GIT_IMAGE_DIGEST not in materialized.runtime_image_ref:
            raise TerminalBenchRunError("Harbor task image is not the B1 digest")


@dataclass(frozen=True)
class PreparedTerminalBenchRun:
    spec: RunSpec
    command: HarborCommand
    adapter: UploadBinaryAdapter
    materialized_task: MaterializedTask

    def validate(self) -> None:
        self.spec.validate()
        self.materialized_task.validate()
        if self.spec.task_id != FIX_GIT_TASK_ID:
            raise TerminalBenchRunError("RunSpec task differs from the frozen P1 task")
        if self.spec.terminal_bench_version != TERMINAL_BENCH_VERSION:
            raise TerminalBenchRunError("RunSpec Terminal-Bench version is not commit-pinned")
        if self.spec.task_image_digest != FIX_GIT_IMAGE_DIGEST:
            raise TerminalBenchRunError("RunSpec image differs from the supervised B1 digest")
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

    ``injected_env`` contains exactly one task-required secret plus telemetry.
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
        injected_env = dict(prepared.command.env)
        injected_env[secret_name] = secret
        result = await self._executor.run(
            prepared.command.argv,
            cwd=prepared.command.cwd,
            injected_env=injected_env,
            timeout_seconds=prepared.spec.timeout_seconds,
            exact_task_label=prepared.command.task_label,
            compose_contract=prepared.command.compose_contract,
        )
        if not isinstance(result, HostHarborResult):
            raise TerminalBenchRunError("host Harbor executor returned an invalid result")
        return result


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
        _require_budget_proxy_argv(argv)
        if set(injected_env) != {"HARBOR_TELEMETRY", _provider_secret_name(injected_env)}:
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
        evidence = await asyncio.to_thread(
            supervisor.supervise_host_command,
            identity,
            argv,
            lease=self._lease,
            timeout_seconds=timeout_seconds,
            compose_contract=compose_contract,
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
    image_digest = validate_runtime_image_digest(request.image_digest)
    if request.max_retries != 0:
        raise TerminalBenchRunError("Terminal-Bench P1 retries are disabled")
    spec = config_module.make_run_spec(
        config,
        side=request.side,
        batch_id=request.batch_id,
        task_id=FIX_GIT_TASK_ID,
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
        staging_name=f"{request.batch_id}-{request.side.value}-fix-git",
        image_digest=image_digest,
        task_label=task_label,
        memory_bytes=request.memory_bytes,
        memory_swap_bytes=request.memory_swap_bytes,
        pids_limit=request.pids_limit,
        provider_api_key_env=spec.provider.api_key_env,
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
        guardian_model=spec.provider.guardian_model,
        guardian_effort=spec.provider.guardian_effort,
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
        source_repo_ref=materialized.source_repo_ref,
        task_source_digest=materialized.source_digest,
        task_label=materialized.task_label,
        trial_name=trial_name,
        trials_dir=trials_dir,
        compose_contract=_compose_run_contract(
            materialized,
            trial_name=trial_name,
            trials_dir=trials_dir,
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


def _compose_run_contract(
    materialized: MaterializedTask,
    *,
    trial_name: str,
    trials_dir: Path,
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
    )
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
            compose_secret_mount=ComposeSecretMountContract(
                destination="/run/secrets/rondo_eval_provider_api_key",
                source_basename="rondo_eval_provider_api_key",
            ),
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


def _provider_secret_name(environment: Mapping[str, str]) -> str:
    names = [name for name in environment if name != "HARBOR_TELEMETRY"]
    if len(names) != 1 or not names[0]:
        raise TerminalBenchRunError("host Harbor requires exactly one provider secret")
    if environment.get("HARBOR_TELEMETRY") != "off" or not environment[names[0]]:
        raise TerminalBenchRunError("host Harbor environment is invalid")
    return names[0]


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
