"""Opt-in, watchdog-supervised Plan 008 namespace/seccomp diagnosis."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

from ..docker_supervisor import (
    ComposeRunContract,
    DockerLimits,
    DockerMountFact,
    DockerSupervisor,
    DockerTaskIdentity,
    HeavyLockLease,
    HostContainerContract,
)
from ..runtime_bridge import (
    CapturingSubprocessDockerCommandRunner,
    DockerCliCounter,
    PowerShellDockerDesktopHostProbe,
    SubprocessDockerCommandRunner,
    lease_from_watchdog,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}\Z")
_TASK_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.-]{5,95}\Z")
_CONTAINER_BWRAP = "/opt/rondo-eval/diagnostic/bwrap"
_PROFILE_LABEL = "dev.rondo.eval.seccomp-profile-sha256"
_TRACKED_PROFILE = Path("eval/seccomp/plan008-userns-minimal-v0.2.3.json")
_UPSTREAM_PROFILE_SHA256 = "536529b665dd0972c37bfb569f5d4ac8a53592e7b00752bc39ff063ca9864c74"
_DERIVED_PROFILE_SHA256 = "9c5198e529f03d38babe9f270f663fa6867bda4e4d14a37a1f6680179d9bbd2f"
_PROFILE_DELTA = b'''\t\t{
\t\t\t"names": [
\t\t\t\t"clone",
\t\t\t\t"mount",
\t\t\t\t"pivot_root",
\t\t\t\t"umount2",
\t\t\t\t"unshare"
\t\t\t],
\t\t\t"action": "SCMP_ACT_ALLOW",
\t\t\t"excludes": {
\t\t\t\t"caps": [
\t\t\t\t\t"CAP_SYS_ADMIN"
\t\t\t\t]
\t\t\t},
\t\t\t"comment": "RONDO Plan 008: minimal non-CAP_SYS_ADMIN bubblewrap userns delta"
\t\t},
'''

DIAGNOSTIC_SCRIPT = r"""
set -eu
printf 'uid='; id -u
printf 'gid='; id -g
if [ -r /proc/sys/user/max_user_namespaces ]; then printf 'max_user_namespaces='; cat /proc/sys/user/max_user_namespaces; else echo 'max_user_namespaces=unavailable'; fi
if [ -r /proc/sys/kernel/unprivileged_userns_clone ]; then printf 'unprivileged_userns_clone='; cat /proc/sys/kernel/unprivileged_userns_clone; else echo 'unprivileged_userns_clone=unavailable'; fi
awk '/^CapEff:/{print "cap_eff=" $2} /^NoNewPrivs:/{print "no_new_privs=" $2} /^Seccomp:/{print "seccomp=" $2} /^Seccomp_filters:/{print "seccomp_filters=" $2}' /proc/self/status
python3 - <<'PY'
import ctypes, errno
libc = ctypes.CDLL(None, use_errno=True)
result = libc.unshare(0x10000000)
error = ctypes.get_errno()
print("unshare_userns=" + ("ok" if result == 0 else "denied"))
print("unshare_errno=" + ("0" if result == 0 else str(error)))
PY
if /opt/rondo-eval/diagnostic/bwrap --new-session --die-with-parent --ro-bind / / --unshare-user --unshare-pid -- /bin/true; then echo 'bwrap_baseline=ok'; else echo 'bwrap_baseline=denied'; fi
sleep 6
""".strip()


class NamespaceDiagnosticError(ValueError):
    pass


@dataclass(frozen=True)
class NamespaceDiagnosticSpec:
    common_root: Path
    project_root: Path
    image: str
    task_id: str
    bwrap_binary: Path
    bwrap_sha256: str
    seccomp_profile: Path | None = None
    memory_bytes: int = 512 * 1024**2
    memory_swap_bytes: int = 768 * 1024**2
    pids_limit: int = 128
    timeout_seconds: int = 30


@dataclass(frozen=True)
class NamespaceDiagnosticPlan:
    argv: tuple[str, ...]
    seccomp_profile_sha256: str | None
    compose_contract: ComposeRunContract


@dataclass(frozen=True)
class NamespaceDiagnosticResult:
    uid: int
    gid: int
    max_user_namespaces: int | None
    unprivileged_userns_clone: int | None
    cap_eff: str
    no_new_privs: int
    seccomp: int
    seccomp_filters: int
    unshare_userns: str
    unshare_errno: int
    bwrap_baseline: str
    seccomp_profile_sha256: str | None
    docker_returncode: int
    docker_sample_count: int
    docker_baseline_total_bytes: int
    docker_final_total_bytes: int
    docker_baseline_task_bytes: int
    docker_final_task_bytes: int
    docker_baseline_data_root_free_bytes: int
    docker_final_data_root_free_bytes: int
    docker_data_root: str
    docker_warnings: tuple[str, ...]


def build_namespace_diagnostic_plan(
    spec: NamespaceDiagnosticSpec,
    *,
    tracked_file_check: Callable[[Path, Path], None] | None = None,
) -> NamespaceDiagnosticPlan:
    if not _IMAGE.fullmatch(spec.image):
        raise NamespaceDiagnosticError("diagnostic image must be registry digest pinned")
    if not _TASK_ID.fullmatch(spec.task_id):
        raise NamespaceDiagnosticError("diagnostic task id is invalid")
    limits = _limits(spec)
    common_root = _directory(spec.common_root, "common root")
    project_root = _directory(spec.project_root, "project root")
    try:
        project_root.relative_to(common_root)
    except ValueError as exc:
        raise NamespaceDiagnosticError("project root must stay below the common root") from exc
    bwrap = _project_file(common_root, spec.bwrap_binary, "bwrap binary")
    if not _SHA256.fullmatch(spec.bwrap_sha256) or _sha256_file(bwrap) != spec.bwrap_sha256:
        raise NamespaceDiagnosticError("diagnostic bwrap identity differs")
    if not os.access(bwrap, os.X_OK):
        raise NamespaceDiagnosticError("diagnostic bwrap is not executable")
    project = "rondodiag-" + hashlib.sha256(spec.task_id.encode()).hexdigest()[:16]
    argv = [
        "docker", "container", "run", "--rm", "--name", f"rondo-eval-{spec.task_id}",
        "--label", f"dev.rondo.eval.task={spec.task_id}",
        "--label", f"com.docker.compose.project={project}",
        "--label", "com.docker.compose.service=main",
        "--user", "1000:1000", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges=true",
        "--memory", str(limits.memory_bytes), "--memory-swap", str(limits.memory_swap_bytes),
        "--pids-limit", str(limits.pids_limit), "--network", "none", "--read-only",
        "--tmpfs", "/tmp:rw,nosuid,nodev,noexec,size=64m",
        "--mount", f"type=bind,source={bwrap},target={_CONTAINER_BWRAP},readonly",
    ]
    profile_sha256 = None
    # Docker daemon inspect normalizes the CLI spelling to a colon.
    security_opt = ("no-new-privileges:true",)
    if spec.seccomp_profile is not None:
        profile = _project_file(project_root, spec.seccomp_profile, "seccomp profile")
        if profile != (project_root / _TRACKED_PROFILE).resolve():
            raise NamespaceDiagnosticError("only the frozen Plan 008 seccomp profile is allowed")
        (tracked_file_check or _require_clean_tracked_file)(project_root, profile)
        _validate_frozen_profile(profile.read_bytes())
        profile_sha256 = _DERIVED_PROFILE_SHA256
        argv.extend(("--label", f"{_PROFILE_LABEL}={profile_sha256}", "--security-opt", f"seccomp={profile}"))
    argv.extend((spec.image, "/bin/sh", "-ceu", DIAGNOSTIC_SCRIPT))
    result = tuple(argv)
    _reject_forbidden_argv(result)
    contract = ComposeRunContract(
        container=HostContainerContract(
            user="1000:1000", memory_bytes=limits.memory_bytes,
            memory_swap_bytes=limits.memory_swap_bytes, pids_limit=limits.pids_limit,
            compose_project=project, compose_service="main", network_mode="none", networks=(),
            mounts=(DockerMountFact("bind", os.fspath(bwrap), _CONTAINER_BWRAP, True),
                    DockerMountFact("tmpfs", "", "/tmp", False)),
            cap_drop=("ALL",), security_opt=security_opt, read_only_rootfs=True,
            seccomp_profile_sha256=profile_sha256,
        ),
        network_names=(),
    )
    contract.validate()
    return NamespaceDiagnosticPlan(result, profile_sha256, contract)


def run_supervised_namespace_diagnostic(
    spec: NamespaceDiagnosticSpec,
    *,
    docker_data_root: Path,
    tracked_file_check: Callable[[Path, Path], None] | None = None,
    watchdog_factory: Callable[[], object] = lease_from_watchdog,
    runner: object | None = None,
    counter: object | None = None,
    cleanup_runner: object | None = None,
    supervisor_factory: Callable[..., object] = DockerSupervisor,
) -> NamespaceDiagnosticResult:
    """Run only through the shared watchdog lease and strict supervisor."""
    plan = build_namespace_diagnostic_plan(spec, tracked_file_check=tracked_file_check)
    proof = watchdog_factory()
    proof.lease.validate()
    capture = runner or CapturingSubprocessDockerCommandRunner()
    supervisor = supervisor_factory(
        runner=capture,
        counter=counter or DockerCliCounter(
            host_data_root=docker_data_root,
            desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        ),
        lock_guard=proof.guard,
        cleanup_runner=cleanup_runner or SubprocessDockerCommandRunner(),
    )
    execution = supervisor.supervise_diagnostic_command(
        DockerTaskIdentity(spec.task_id), plan.argv,
        lease=HeavyLockLease(proof.lease.token, proof.lease.held),
        limits=_limits(spec), compose_contract=plan.compose_contract,
    )
    if execution.returncode != 0:
        raise NamespaceDiagnosticError("diagnostic container did not exit successfully")
    if not execution.samples:
        raise NamespaceDiagnosticError("diagnostic Docker supervision produced no samples")
    output = capture.safe_output()
    values = _parse_output(output)
    baseline, final = execution.samples[0], execution.samples[-1]
    return NamespaceDiagnosticResult(
        **values, seccomp_profile_sha256=plan.seccomp_profile_sha256,
        docker_returncode=execution.returncode, docker_sample_count=len(execution.samples),
        docker_baseline_total_bytes=baseline.docker_total_bytes,
        docker_final_total_bytes=final.docker_total_bytes,
        docker_baseline_task_bytes=baseline.task_bytes,
        docker_final_task_bytes=final.task_bytes,
        docker_baseline_data_root_free_bytes=baseline.data_root_filesystem_free_bytes,
        docker_final_data_root_free_bytes=final.data_root_filesystem_free_bytes,
        docker_data_root=final.data_root,
        docker_warnings=tuple(execution.warnings),
    )


def _limits(spec: NamespaceDiagnosticSpec) -> DockerLimits:
    limits = DockerLimits(spec.memory_bytes, spec.memory_swap_bytes, spec.pids_limit, spec.timeout_seconds)
    try:
        limits.validate()
    except Exception as exc:
        raise NamespaceDiagnosticError("diagnostic resource limits are invalid") from exc
    return limits


def _parse_output(output: str) -> dict[str, object]:
    expected = {"uid", "gid", "max_user_namespaces", "unprivileged_userns_clone", "cap_eff", "no_new_privs", "seccomp", "seccomp_filters", "unshare_userns", "unshare_errno", "bwrap_baseline"}
    values: dict[str, str] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in expected or key in values or not value:
            raise NamespaceDiagnosticError("diagnostic output is invalid")
        values[key] = value
    if set(values) != expected:
        raise NamespaceDiagnosticError("diagnostic output is incomplete")
    if values["unshare_userns"] not in {"ok", "denied"} or values["bwrap_baseline"] not in {"ok", "denied"}:
        raise NamespaceDiagnosticError("diagnostic probe status is invalid")
    try:
        parsed: dict[str, object] = {key: int(values[key]) for key in ("uid", "gid", "no_new_privs", "seccomp", "seccomp_filters", "unshare_errno")}
        for key in ("max_user_namespaces", "unprivileged_userns_clone"):
            parsed[key] = None if values[key] == "unavailable" else int(values[key])
    except ValueError as exc:
        raise NamespaceDiagnosticError("diagnostic numeric output is invalid") from exc
    if not re.fullmatch(r"[0-9A-Fa-f]{16}", values["cap_eff"]):
        raise NamespaceDiagnosticError("diagnostic capability output is invalid")
    parsed.update(cap_eff=values["cap_eff"].lower(), unshare_userns=values["unshare_userns"], bwrap_baseline=values["bwrap_baseline"])
    return parsed


def _validate_frozen_profile(raw: bytes) -> None:
    if hashlib.sha256(raw).hexdigest() != _DERIVED_PROFILE_SHA256 or raw.count(_PROFILE_DELTA) != 1:
        raise NamespaceDiagnosticError("seccomp profile identity or delta differs")
    upstream = raw.replace(_PROFILE_DELTA, b"", 1)
    # The tracked derived file has one final LF; upstream deliberately has none.
    if not upstream.endswith(b"\n") or hashlib.sha256(upstream[:-1]).hexdigest() != _UPSTREAM_PROFILE_SHA256:
        raise NamespaceDiagnosticError("seccomp profile does not derive from frozen upstream")
    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NamespaceDiagnosticError("seccomp profile is invalid JSON") from exc
    if not isinstance(document, dict) or document.get("defaultAction") != "SCMP_ACT_ERRNO":
        raise NamespaceDiagnosticError("seccomp profile must remain default-deny")


def _reject_forbidden_argv(argv: Sequence[str]) -> None:
    lowered = tuple(value.casefold() for value in argv)
    if "--privileged" in lowered or "seccomp=unconfined" in lowered or "--cap-add" in lowered or "sys_admin" in lowered:
        raise NamespaceDiagnosticError("diagnostic argv requests forbidden privilege")


def _directory(path: Path, label: str) -> Path:
    try:
        resolved, path_stat = path.resolve(strict=True), path.lstat()
    except OSError as exc:
        raise NamespaceDiagnosticError(f"{label} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISDIR(path_stat.st_mode):
        raise NamespaceDiagnosticError(f"{label} is invalid")
    return resolved


def _project_file(project_root: Path, path: Path, label: str) -> Path:
    path = path if path.is_absolute() else project_root / path
    try:
        resolved, path_stat = path.resolve(strict=True), path.lstat()
    except OSError as exc:
        raise NamespaceDiagnosticError(f"{label} is unavailable") from exc
    if path.is_symlink() or not stat.S_ISREG(path_stat.st_mode) or not resolved.is_relative_to(project_root):
        raise NamespaceDiagnosticError(f"{label} must be a project-local regular file")
    return resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise NamespaceDiagnosticError("diagnostic file could not be hashed") from exc
    return digest.hexdigest()


def _require_clean_tracked_file(project_root: Path, path: Path) -> None:
    relative = path.relative_to(project_root)
    commands = (("git", "-C", os.fspath(project_root), "ls-files", "--error-unmatch", "--", os.fspath(relative)), ("git", "-C", os.fspath(project_root), "diff", "--quiet", "--", os.fspath(relative)), ("git", "-C", os.fspath(project_root), "diff", "--cached", "--quiet", "--", os.fspath(relative)))
    for argv in commands:
        try:
            completed = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise NamespaceDiagnosticError("cannot verify tracked seccomp profile") from exc
        if completed.returncode != 0:
            raise NamespaceDiagnosticError("seccomp profile must be clean and tracked")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="run or emit the supervised namespace diagnostic")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--emit-argv", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--common-root", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--bwrap", type=Path, required=True)
    parser.add_argument("--bwrap-sha256", required=True)
    parser.add_argument("--seccomp-profile", type=Path)
    parser.add_argument("--docker-data-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.emit_argv and not args.run:
        raise NamespaceDiagnosticError("diagnostic CLI is inert without --emit-argv or --run")
    spec = NamespaceDiagnosticSpec(
        args.common_root,
        args.project_root,
        args.image,
        args.task_id,
        args.bwrap,
        args.bwrap_sha256,
        args.seccomp_profile,
    )
    if args.emit_argv:
        plan = build_namespace_diagnostic_plan(spec)
        print(json.dumps(plan.argv, ensure_ascii=True, separators=(",", ":")))
        return 0
    if args.docker_data_root is None:
        raise NamespaceDiagnosticError("--run requires --docker-data-root")
    result = run_supervised_namespace_diagnostic(spec, docker_data_root=args.docker_data_root)
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
