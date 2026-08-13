"""Incremental, campaign-independent proof store for B7 Oracle runs."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..config import RepoPaths
from .tasksets import FrozenCanaryCatalog, FrozenTask


class OracleProofError(ValueError):
    """The Oracle proof set is partial, stale, or contradictory."""


@dataclass(frozen=True)
class OracleProofContract:
    task: dict[str, object]
    taskset_entry_sha256: str
    catalog_entry_sha256: str
    verifier_tree_sha256: str
    shared_components: dict[str, str]
    terminal_bench_commit: str
    harbor_version: str
    seccomp_source_sha256: str
    seccomp_effective_sha256: str

    @property
    def sha256(self) -> str:
        return _canonical_sha256(asdict(self))


class OracleProofStore:
    """Publish one durable task proof at a time, then aggregate ten proofs."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise OracleProofError("Oracle proof root must be absolute")
        if root.is_symlink() or (root.exists() and not root.is_dir()):
            raise OracleProofError("Oracle proof root is unsafe")
        self.root = root

    def proof_path(self, contract: OracleProofContract) -> Path:
        slug = str(contract.task["task_id"]).split("/", maxsplit=1)[1]
        return self.root / "tasks" / f"{slug}-{contract.sha256}.json"

    def valid_proof(self, contract: OracleProofContract) -> dict[str, object] | None:
        path = self.proof_path(contract)
        if not _regular_file(path):
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        if (
            not isinstance(value, dict)
            or set(value)
            != {
                "schema_version",
                "contract",
                "contract_sha256",
                "status",
                "reward",
                "docker_compatibility",
            }
            or value["schema_version"] != 1
            or value["contract"] != asdict(contract)
            or value["contract_sha256"] != contract.sha256
            or value["status"] != "completed"
            or value["reward"] != 1.0
            or not _valid_docker_compatibility(
                value["docker_compatibility"], contract=contract
            )
        ):
            return None
        return value

    def publish(
        self,
        contract: OracleProofContract,
        *,
        outcome: str,
        task_outcome: str,
        reward: float,
        docker_receipt: Mapping[str, object],
    ) -> Path:
        if outcome != "completed" or task_outcome != "pass" or reward != 1.0:
            raise OracleProofError("Oracle task did not satisfy the proof gate")
        compatibility = _docker_compatibility(contract, docker_receipt)
        value = {
            "schema_version": 1,
            "contract": asdict(contract),
            "contract_sha256": contract.sha256,
            "status": "completed",
            "reward": 1.0,
            "docker_compatibility": compatibility,
        }
        path = self.proof_path(contract)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path.exists() or path.is_symlink():
            existing = self.valid_proof(contract)
            if existing != value:
                raise OracleProofError("Oracle proof destination already exists")
            return path
        _atomic_json(path, value)
        return path

    def publish_manifest(
        self,
        *,
        catalog: FrozenCanaryCatalog,
        contracts: Sequence[OracleProofContract],
    ) -> Path | None:
        value = self._manifest_value(catalog=catalog, contracts=contracts)
        if value is None:
            return None
        path = self.root / "manifest.json"
        _atomic_json(path, value, replace=True)
        return path

    def validate_manifest(
        self,
        *,
        catalog: FrozenCanaryCatalog,
        contracts: Sequence[OracleProofContract],
    ) -> Path | None:
        path = self.root / "manifest.json"
        if not _regular_file(path):
            return None
        expected = self._manifest_value(catalog=catalog, contracts=contracts)
        if expected is None:
            return None
        try:
            observed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return path if observed == expected else None

    def _manifest_value(
        self,
        *,
        catalog: FrozenCanaryCatalog,
        contracts: Sequence[OracleProofContract],
    ) -> dict[str, object] | None:
        if tuple(item.task["task_id"] for item in contracts) != tuple(
            task.task_id for task in catalog.tasks
        ):
            raise OracleProofError("Oracle proof contracts differ from the catalog")
        proofs: list[dict[str, str]] = []
        for contract in contracts:
            if self.valid_proof(contract) is None:
                return None
            path = self.proof_path(contract)
            proofs.append(
                {
                    "task_id": str(contract.task["task_id"]),
                    "contract_sha256": contract.sha256,
                    "relative_path": path.relative_to(self.root).as_posix(),
                    "proof_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
        return {
            "schema_version": 1,
            "terminal_bench_commit": catalog.terminal_bench_commit,
            "taskset_sha256": catalog.taskset_sha256,
            "catalog_sha256": catalog.catalog_sha256,
            "proofs": proofs,
        }


def build_oracle_contract(
    paths: RepoPaths,
    *,
    catalog: FrozenCanaryCatalog,
    task: FrozenTask,
    seccomp_source_sha256: str,
    seccomp_effective_sha256: str,
) -> OracleProofContract:
    task.validate()
    task_value = asdict(task)
    taskset_entry = {"partition": "canary", "task_id": task.task_id}
    source_root = (
        paths.common_root
        / "eval-data/sources"
        / "terminal-bench-2-1-ffccbe05"
        / "tasks"
        / task.slug
    )
    component_root = paths.worktree_root / "eval/rondo_eval"
    component_paths = {
        # verifier_runtime normalizes every official solution/verifier exec
        # through compat.exec_result; changing that normalization changes the
        # fact proved by an otherwise identical Oracle run.
        "harbor_compat": component_root / "terminal_bench/compat.py",
        "frozen_image_contract": component_root / "terminal_bench/freeze.py",
        "frozen_task_contract": component_root / "terminal_bench/tasksets.py",
        "materializer": component_root / "terminal_bench/materialize.py",
        "runner": component_root / "terminal_bench/runner.py",
        "oracle": component_root / "terminal_bench/oracle_smoke.py",
        "verifier_runtime": component_root / "terminal_bench/verifier_runtime.py",
        "result_parser": component_root / "terminal_bench/results.py",
        "docker_supervisor": component_root / "docker_supervisor.py",
        "runtime_bridge": component_root / "runtime_bridge.py",
        "proof_validator": component_root / "terminal_bench/oracle_proof.py",
    }
    return OracleProofContract(
        task=task_value,
        taskset_entry_sha256=_canonical_sha256(taskset_entry),
        catalog_entry_sha256=_canonical_sha256(task_value),
        verifier_tree_sha256=_tree_sha256(source_root / "tests"),
        shared_components={
            key: _file_sha256(value) for key, value in sorted(component_paths.items())
        },
        terminal_bench_commit=catalog.terminal_bench_commit,
        harbor_version=importlib.metadata.version("harbor"),
        seccomp_source_sha256=seccomp_source_sha256,
        seccomp_effective_sha256=seccomp_effective_sha256,
    )


def _docker_compatibility(
    contract: OracleProofContract,
    receipt: Mapping[str, object],
) -> dict[str, object]:
    image = receipt.get("image")
    container = receipt.get("container")
    seccomp = receipt.get("seccomp")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("returncode") != 0
        or not isinstance(image, dict)
        or not isinstance(container, dict)
        or not isinstance(seccomp, dict)
    ):
        raise OracleProofError("Oracle Docker receipt is incomplete")
    stable_container = {
        key: container.get(key)
        for key in (
            "cap_add",
            "cap_drop",
            "cgroupns",
            "memory",
            "memory_swap",
            "mounts",
            "network_mode",
            "networks",
            "pids",
            "privileged",
            "read_only_rootfs",
            "security_opt",
            "user",
        )
    }
    value = {
        "image": image,
        "container": stable_container,
        "seccomp": seccomp,
        "cleanup": receipt.get("cleanup"),
        "operation": receipt.get("operation"),
    }
    if not _valid_docker_compatibility(value, contract=contract):
        raise OracleProofError("Oracle Docker compatibility evidence is invalid")
    return value


def _valid_docker_compatibility(
    value: object,
    *,
    contract: OracleProofContract,
) -> bool:
    container_keys = {
        "cap_add",
        "cap_drop",
        "cgroupns",
        "memory",
        "memory_swap",
        "mounts",
        "network_mode",
        "networks",
        "pids",
        "privileged",
        "read_only_rootfs",
        "security_opt",
        "user",
    }
    task = contract.task
    memory_mb = task.get("memory_mb")
    pids_limit = task.get("pids_limit")
    expected_memory = (
        memory_mb * 1024**2
        if isinstance(memory_mb, int) and not isinstance(memory_mb, bool)
        else None
    )
    image = value.get("image") if isinstance(value, dict) else None
    container = value.get("container") if isinstance(value, dict) else None
    seccomp = value.get("seccomp") if isinstance(value, dict) else None
    return (
        isinstance(value, dict)
        and set(value) == {"image", "container", "seccomp", "cleanup", "operation"}
        and isinstance(image, dict)
        and set(image) == {"id", "reference"}
        and image.get("reference") == task.get("image_ref")
        and isinstance(image.get("id"), str)
        and image["id"].startswith("sha256:")
        and len(image["id"]) == 71
        and isinstance(container, dict)
        and set(container) == container_keys
        and expected_memory is not None
        and container.get("memory") == expected_memory
        and container.get("memory_swap") == expected_memory + 1024**3
        and isinstance(pids_limit, int)
        and not isinstance(pids_limit, bool)
        and container.get("pids") == pids_limit
        and isinstance(seccomp, dict)
        and set(seccomp) == {"kind", "sha256"}
        and seccomp.get("kind") == "custom"
        and seccomp.get("sha256") == contract.seccomp_effective_sha256
        and value["cleanup"] == "verified_empty"
        and value["operation"] == "host"
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    if not _regular_file(path):
        raise OracleProofError("Oracle component file is unavailable")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path) -> str:
    if root.is_symlink() or not root.is_dir():
        raise OracleProofError("Oracle verifier tree is unavailable")
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    if not files:
        raise OracleProofError("Oracle verifier tree is empty")
    for path in files:
        if path.is_symlink() or not _regular_file(path):
            raise OracleProofError("Oracle verifier tree is unsafe")
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        payload = path.read_bytes()
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _regular_file(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode) and not path.is_symlink()
    except OSError:
        return False


def _atomic_json(path: Path, value: object, *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise OracleProofError("Oracle proof temporary path already exists")
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if not replace and (path.exists() or path.is_symlink()):
            raise OracleProofError("Oracle proof destination already exists")
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise
