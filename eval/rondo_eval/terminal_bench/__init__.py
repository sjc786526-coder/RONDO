"""Frozen Terminal-Bench 2.1 preparation and upload adapters."""

from typing import TYPE_CHECKING

from .adapters import (
    AdapterError,
    CodexUploadAdapter,
    RondoUploadAdapter,
    UploadBinaryAdapter,
)
from .freeze import (
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_IMAGE_REF,
    FIX_GIT_IMAGE_REPOSITORY,
    FIX_GIT_IMAGE_TAG,
    FIX_GIT_TASK_ARCHIVE_SHA256,
    FIX_GIT_TASK_ID,
    HARBOR_REQUIREMENT,
    HARBOR_VERSION,
    HARBOR_WHEEL_SHA256,
    TERMINAL_BENCH_COMMIT,
    TERMINAL_BENCH_DATASET_ID,
    TERMINAL_BENCH_REPO_REF,
    TERMINAL_BENCH_VERSION,
    FreezeError,
)
from .materialize import MaterializationError, MaterializedTask, PinnedTaskMaterializer
from .live import (
    BudgetedTerminalBenchResult,
    EvidenceObservation,
    run_budgeted_terminal_bench,
)
from .runner import (
    DockerSupervisedHostHarborExecutor,
    HarborCommand,
    HostHarborResult,
    InjectedHostHarborBackend,
    PreparedTerminalBenchRun,
    TerminalBenchRequest,
    UnifiedTerminalBenchRunner,
    prepare_terminal_bench_run,
)

if TYPE_CHECKING:
    from .docker_smoke import (
        DockerNoApiSmokeResult,
        LocalResponsesFakeServer,
        SmokeRequestObservation,
    )

__all__ = [
    "AdapterError",
    "CodexUploadAdapter",
    "BudgetedTerminalBenchResult",
    "DockerSupervisedHostHarborExecutor",
    "DockerNoApiSmokeResult",
    "EvidenceObservation",
    "FIX_GIT_IMAGE_DIGEST",
    "FIX_GIT_IMAGE_REF",
    "FIX_GIT_IMAGE_REPOSITORY",
    "FIX_GIT_IMAGE_TAG",
    "FIX_GIT_TASK_ARCHIVE_SHA256",
    "FIX_GIT_TASK_ID",
    "FreezeError",
    "HARBOR_REQUIREMENT",
    "HARBOR_VERSION",
    "HARBOR_WHEEL_SHA256",
    "HarborCommand",
    "HostHarborResult",
    "InjectedHostHarborBackend",
    "MaterializationError",
    "MaterializedTask",
    "LocalResponsesFakeServer",
    "PreparedTerminalBenchRun",
    "PinnedTaskMaterializer",
    "RondoUploadAdapter",
    "SmokeRequestObservation",
    "TERMINAL_BENCH_COMMIT",
    "TERMINAL_BENCH_DATASET_ID",
    "TERMINAL_BENCH_REPO_REF",
    "TERMINAL_BENCH_VERSION",
    "TerminalBenchRequest",
    "UnifiedTerminalBenchRunner",
    "UploadBinaryAdapter",
    "prepare_terminal_bench_run",
    "run_budgeted_terminal_bench",
    "run_docker_no_api_smoke",
]


_DOCKER_SMOKE_EXPORTS = {
    "DockerNoApiSmokeResult",
    "LocalResponsesFakeServer",
    "SmokeRequestObservation",
    "run_docker_no_api_smoke",
}


def __getattr__(name: str):
    if name not in _DOCKER_SMOKE_EXPORTS:
        raise AttributeError(name)
    from . import docker_smoke

    return getattr(docker_smoke, name)
