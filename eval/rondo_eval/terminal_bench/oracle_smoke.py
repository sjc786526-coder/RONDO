"""One supervised, no-key oracle/verifier check for frozen fix-git."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import ConfigError, RepoPaths, load_runtime_config
from ..contracts import RunOutcome
from ..docker_supervisor import DockerSupervisionError
from ..exit_codes import EVIDENCE_ERROR, INFRA_ERROR
from ..runtime_bridge import (
    DockerCliCounter,
    PowerShellDockerDesktopHostProbe,
    RuntimeBridgeError,
    lease_from_watchdog,
)
from .docker_smoke import _print_safe_cli_error, _write_current_receipt
from .freeze import FIX_GIT_IMAGE_DIGEST
from .materialize import PinnedTaskMaterializer
from .pair import load_no_api_pair_identity, validate_harbor_installation
from .results import ParsedHarborResult, parse_single_task_result, validate_eval_harness_checkout
from .runner import DockerSupervisedHostHarborExecutor, HARBOR_EXECUTABLE, HostHarborResult
from .verifier_runtime import prepare_task_workdir, prepare_verifier_apt_dirs

from harbor.agents.oracle import OracleAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.trial.paths import TrialPaths


ORACLE_BATCH_ID = "p1-plan012-oracle-verifier"


class PreparedOracleAgent(OracleAgent):
    """Frozen Harbor oracle with only the task/verifier filesystem preflight."""

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None = None,
        *,
        task_dir: str,
        task_workdir: str,
        agent_timeout_seconds: str,
        **kwargs: object,
    ) -> None:
        logs_dir = Path(logs_dir)
        task_path = Path(task_dir)
        if not task_path.is_absolute() or task_path.is_symlink():
            raise OracleVerifierSmokeError("oracle task path is invalid")
        try:
            timeout = int(agent_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise OracleVerifierSmokeError("oracle timeout is invalid") from exc
        if timeout < 1 or timeout > 7200:
            raise OracleVerifierSmokeError("oracle timeout is invalid")
        self._task_workdir = task_workdir
        super().__init__(
            logs_dir=logs_dir,
            model_name=model_name,
            task_dir=task_path,
            trial_paths=TrialPaths(logs_dir.parent),
            agent_timeout_sec=float(timeout),
            **kwargs,
        )

    async def setup(self, environment: BaseEnvironment) -> None:
        await prepare_task_workdir(environment, self._task_workdir)
        await prepare_verifier_apt_dirs(environment)


class OracleVerifierSmokeError(ValueError):
    """The frozen solution/verifier chain did not prove reward 1."""


@dataclass(frozen=True)
class OracleVerifierSmokeResult:
    harbor: HostHarborResult
    parsed: ParsedHarborResult

    @property
    def passed(self) -> bool:
        return (
            self.harbor.returncode == 0
            and self.parsed.outcome is RunOutcome.COMPLETED
            and self.parsed.task_outcome == "pass"
            and self.parsed.reward == 1.0
        )

    def safe_summary(self) -> dict[str, object]:
        if self.harbor.docker_evidence is None:
            raise OracleVerifierSmokeError("oracle verifier result lacks Docker evidence")
        return {
            "schema_version": 1,
            "batch_id": ORACLE_BATCH_ID,
            "status": "completed" if self.passed else "failed",
            "outcome": self.parsed.outcome.value,
            "task_outcome": self.parsed.task_outcome,
            "reward": self.parsed.reward,
            "official_api_requests": 0,
            "actual_usd": 0.0,
            "docker": self.harbor.docker_evidence.receipt(),
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.terminal_bench.oracle_smoke"
    )
    parser.add_argument("--docker-host-volume", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = RepoPaths.discover(Path.cwd())
        pair_identity = load_no_api_pair_identity()
        eval_harness_commit = validate_eval_harness_checkout(common_root=paths.common_root)
        config = load_runtime_config(paths)
        provider = config.paid_provider()
        api_key_env = provider.get("api_key_env")
        if not isinstance(api_key_env, str) or not api_key_env:
            raise OracleVerifierSmokeError("provider key variable name is unavailable")
        seccomp_profile = pair_identity.validate_no_api_seccomp(
            project_root=paths.worktree_root
        )
        validate_harbor_installation(pair_identity, executable=HARBOR_EXECUTABLE)
        proof = lease_from_watchdog()
        counter = DockerCliCounter(
            host_data_root=args.docker_host_volume,
            desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        )
        oracle_id = f"tb-oracle-{uuid.uuid4().hex[:12]}"
        work_root = paths.common_root / "eval-data" / "work" / oracle_id
        if work_root.exists() or work_root.is_symlink():
            raise OracleVerifierSmokeError("oracle work directory already exists")
        work_root.mkdir(parents=True, mode=0o700)
        materialized = PinnedTaskMaterializer().materialize(
            source_checkout=(
                paths.common_root
                / "eval-data"
                / "sources"
                / "terminal-bench-2-1-ffccbe05"
            ),
            staging_root=work_root / "staging",
            staging_name=f"{ORACLE_BATCH_ID}-fix-git",
            image_digest=FIX_GIT_IMAGE_DIGEST,
            task_label=f"dev.rondo.eval.task={oracle_id}",
            memory_bytes=2 * 1024**3,
            memory_swap_bytes=3 * 1024**3,
            pids_limit=256,
            provider_api_key_env=api_key_env,
            seccomp_profile=seccomp_profile,
            seccomp_profile_source_sha256=pair_identity.no_api_seccomp.source_sha256,
            seccomp_profile_effective_sha256=pair_identity.no_api_seccomp.effective_sha256,
        )
        if materialized.provider_secret_path.read_bytes() != b"":
            raise OracleVerifierSmokeError("oracle provider placeholder is not empty")
        executor = DockerSupervisedHostHarborExecutor(
            counter=counter,
            lock_guard=proof.guard,
            lease=proof.lease,
        )
        harbor = asyncio.run(
            executor.run_oracle(materialized, timeout_seconds=args.timeout_seconds)
        )
        if materialized.provider_secret_path.read_bytes() != b"":
            raise OracleVerifierSmokeError("oracle unexpectedly populated provider secret")
        parsed = parse_single_task_result(
            harbor.trial_dir,
            host_returncode=harbor.returncode,
        )
        result = OracleVerifierSmokeResult(harbor=harbor, parsed=parsed)
        summary = result.safe_summary()
        receipt = {
            **summary,
            "eval_harness_commit": eval_harness_commit,
        }
        _write_current_receipt(
            paths.common_root / "eval-data" / "b2" / "oracle-current.json",
            receipt,
        )
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0 if result.passed else EVIDENCE_ERROR
    except (DockerSupervisionError, RuntimeBridgeError) as exc:
        _print_safe_cli_error(exc, exit_code=INFRA_ERROR)
        return INFRA_ERROR
    except (ConfigError, OracleVerifierSmokeError, OSError, ValueError) as exc:
        _print_safe_cli_error(exc, exit_code=EVIDENCE_ERROR)
        return EVIDENCE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
