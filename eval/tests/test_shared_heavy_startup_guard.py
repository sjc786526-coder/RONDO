from __future__ import annotations

import fcntl
import os
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
LIBRARY = REPO_ROOT / "scripts" / "build-watchdog-lib.sh"
WRAPPER = REPO_ROOT / "scripts" / "with-build-lock.sh"
RUN_SYSTEMD_FIXTURE = os.environ.get("RONDO_PLAN072_SYSTEMD_FIXTURE") == "1"


def run_helper(
    command: str, *, environment: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    if environment is not None:
        env.update(environment)
    return subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(LIBRARY))}; {command}"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


class SharedHeavyScopeObservationTests(unittest.TestCase):
    def _run_fake(
        self,
        root: Path,
        *,
        listing: str,
        properties: str = "",
        list_rc: int = 0,
        show_rc: int = 0,
    ) -> subprocess.CompletedProcess[str]:
        fake_systemctl = root / "systemctl"
        fake_systemctl.write_text(
            """#!/usr/bin/env bash
case " $* " in
  *" list-units "*)
    printf '%s' "${PLAN072_FAKE_LISTING:-}"
    exit "${PLAN072_FAKE_LIST_RC:-0}"
    ;;
  *" show "*)
    printf '%s' "${PLAN072_FAKE_PROPERTIES:-}"
    exit "${PLAN072_FAKE_SHOW_RC:-0}"
    ;;
esac
exit 2
""",
            encoding="utf-8",
        )
        fake_systemctl.chmod(0o700)
        return run_helper(
            f"rondo_active_heavy_scopes 1000 {shlex.quote(str(root))}",
            environment={
                "PATH": f"{root}{os.pathsep}{os.environ['PATH']}",
                "PLAN072_FAKE_LISTING": listing,
                "PLAN072_FAKE_PROPERTIES": properties,
                "PLAN072_FAKE_LIST_RC": str(list_rc),
                "PLAN072_FAKE_SHOW_RC": str(show_rc),
            },
        )

    def test_populated_scope_is_reported_as_the_exact_conflict(self) -> None:
        unit = "rondo-build-1000-20260825010101-4242.scope"
        control_group = f"/test.slice/{unit}"
        with tempfile.TemporaryDirectory(prefix="plan072-pure-") as directory:
            root = Path(directory)
            cgroup = root / control_group.removeprefix("/")
            cgroup.mkdir(parents=True)
            (cgroup / "cgroup.events").write_text("populated 1\n", encoding="utf-8")
            result = self._run_fake(
                root,
                listing=f"{unit} loaded active running fixture\n",
                properties=(
                    "LoadState=loaded\n"
                    "ActiveState=active\n"
                    f"ControlGroup={control_group}\n"
                ),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"{unit}\n")

    def test_inactive_failed_without_cgroup_and_unpopulated_scopes_are_clear(
        self,
    ) -> None:
        unit = "rondo-build-1000-20260825010102-4243.scope"
        for active_state in ("inactive", "failed"):
            with self.subTest(active_state=active_state), tempfile.TemporaryDirectory(
                prefix="plan072-pure-"
            ) as directory:
                root = Path(directory)
                result = self._run_fake(
                    root,
                    listing=f"{unit} loaded {active_state} dead fixture\n",
                    properties=(
                        "LoadState=not-found\n"
                        f"ActiveState={active_state}\n"
                        "ControlGroup=\n"
                    ),
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")

        with tempfile.TemporaryDirectory(prefix="plan072-pure-") as directory:
            root = Path(directory)
            control_group = f"/test.slice/{unit}"
            cgroup = root / control_group.removeprefix("/")
            cgroup.mkdir(parents=True)
            (cgroup / "cgroup.events").write_text("populated 0\n", encoding="utf-8")
            result = self._run_fake(
                root,
                listing=f"{unit} loaded active running fixture\n",
                properties=(
                    "LoadState=loaded\n"
                    "ActiveState=active\n"
                    f"ControlGroup={control_group}\n"
                ),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_inactive_or_failed_populated_cgroup_is_still_a_conflict(self) -> None:
        unit = "rondo-build-1000-20260825010105-4246.scope"
        control_group = f"/test.slice/{unit}"
        for active_state in ("inactive", "failed"):
            with self.subTest(active_state=active_state), tempfile.TemporaryDirectory(
                prefix="plan072-pure-"
            ) as directory:
                root = Path(directory)
                cgroup = root / control_group.removeprefix("/")
                cgroup.mkdir(parents=True)
                (cgroup / "cgroup.events").write_text(
                    "populated 1\n", encoding="utf-8"
                )
                result = self._run_fake(
                    root,
                    listing=f"{unit} loaded {active_state} dead fixture\n",
                    properties=(
                        "LoadState=loaded\n"
                        f"ActiveState={active_state}\n"
                        f"ControlGroup={control_group}\n"
                    ),
                )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f"{unit}\n")

    def test_observation_failures_remain_fail_closed(self) -> None:
        unit = "rondo-build-1000-20260825010103-4244.scope"
        cases = (
            {"listing": "", "list_rc": 1},
            {
                "listing": f"{unit} loaded active running fixture\n",
                "properties": "LoadState=loaded\nActiveState=active\nControlGroup=\n",
            },
            {
                "listing": f"{unit} loaded active running fixture\n",
                "show_rc": 1,
            },
        )
        for index, case in enumerate(cases):
            with self.subTest(case=index), tempfile.TemporaryDirectory(
                prefix="plan072-pure-"
            ) as directory:
                result = self._run_fake(Path(directory), **case)
            self.assertNotEqual(result.returncode, 0)

    def test_malformed_population_fact_remains_fail_closed(self) -> None:
        unit = "rondo-build-1000-20260825010104-4245.scope"
        control_group = f"/test.slice/{unit}"
        with tempfile.TemporaryDirectory(prefix="plan072-pure-") as directory:
            root = Path(directory)
            cgroup = root / control_group.removeprefix("/")
            cgroup.mkdir(parents=True)
            (cgroup / "cgroup.events").write_text("populated maybe\n", encoding="utf-8")
            result = self._run_fake(
                root,
                listing=f"{unit} loaded active running fixture\n",
                properties=(
                    "LoadState=loaded\n"
                    "ActiveState=active\n"
                    f"ControlGroup={control_group}\n"
                ),
            )
        self.assertNotEqual(result.returncode, 0)

    def test_wrapper_guard_precedes_both_payload_paths(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")
        blocking_flock = source.index("if ! flock 199; then")
        guard = source.index('rondo_active_heavy_scopes "$uid"')
        watchdog_disabled = source.index('if [[ "${RONDO_BUILD_WATCHDOG:-1}" == "0" ]]')
        supervised_payload = source.index("systemd-run --user --scope")
        self.assertLess(blocking_flock, guard)
        self.assertLess(guard, watchdog_disabled)
        self.assertLess(watchdog_disabled, supervised_payload)


@unittest.skipUnless(
    RUN_SYSTEMD_FIXTURE,
    "set RONDO_PLAN072_SYSTEMD_FIXTURE=1 for the task-owned systemd fixture",
)
class SharedHeavyScopeSystemdFixtureTests(unittest.TestCase):
    def _canonical_lock(self) -> tuple[int, Path]:
        uid = os.getuid()
        runtime = Path(f"/run/user/{uid}")
        runtime_stat = runtime.lstat()
        if (
            stat.S_ISLNK(runtime_stat.st_mode)
            or not stat.S_ISDIR(runtime_stat.st_mode)
            or runtime_stat.st_uid != uid
            or not os.access(runtime, os.W_OK)
        ):
            runtime = Path(f"/tmp/rondo-runtime-{uid}")
        lock = runtime / "rondo-cargo-build.lock"
        before = lock.lstat()
        self.assertTrue(stat.S_ISREG(before.st_mode))
        self.assertFalse(stat.S_ISLNK(before.st_mode))
        self.assertEqual(before.st_uid, uid)
        self.assertEqual(stat.S_IMODE(before.st_mode), 0o600)
        fd = os.open(lock, os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW)
        opened = os.fstat(fd)
        self.assertEqual((before.st_dev, before.st_ino), (opened.st_dev, opened.st_ino))
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd, lock

    def _properties(self, unit: str) -> dict[str, str]:
        result = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                unit,
                "--property=Id",
                "--property=Description",
                "--property=LoadState",
                "--property=ActiveState",
                "--property=SubState",
                "--property=ControlGroup",
                "--no-pager",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)

    def _assert_owned_active(
        self, process: subprocess.Popen[str], unit: str, description: str, start_ticks: str
    ) -> str:
        self.assertIsNone(process.poll())
        properties = self._properties(unit)
        self.assertEqual(properties.get("Id"), unit)
        self.assertEqual(properties.get("Description"), description)
        self.assertEqual(properties.get("LoadState"), "loaded")
        self.assertIn(properties.get("ActiveState"), {"active", "activating"})
        control_group = properties.get("ControlGroup", "")
        self.assertTrue(control_group.endswith(f"/{unit}"), control_group)
        current_ticks = Path(f"/proc/{process.pid}/stat").read_text(encoding="utf-8").split()[21]
        self.assertEqual(current_ticks, start_ticks)
        process_group = next(
            line.split(":", 2)[2]
            for line in Path(f"/proc/{process.pid}/cgroup").read_text(encoding="utf-8").splitlines()
            if line.startswith("0::")
        )
        self.assertTrue(
            process_group == control_group or process_group.startswith(f"{control_group}/")
        )
        events = Path(f"/sys/fs/cgroup{control_group}/cgroup.events").read_text(
            encoding="utf-8"
        )
        self.assertIn("populated 1", events.splitlines())
        return control_group

    def _run_wrapper(self, marker: Path, metrics: Path) -> subprocess.CompletedProcess[str]:
        command = [
            str(WRAPPER),
            "/bin/bash",
            "-c",
            'printf "%s\\n" "$1" >"$2"; sleep 2',
            "plan072-payload",
            "plan072",
            str(marker),
        ]
        env = {
            **os.environ,
            "CARGO_TARGET_DIR": str(REPO_ROOT / ".codex" / "plan072-no-target"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "RONDO_BUILD_METRICS_DIR": str(metrics),
        }
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.send_signal(signal.SIGTERM)
            stdout, stderr = process.communicate(timeout=15)
            self.fail(f"wrapper exceeded deadline: stdout={stdout!r} stderr={stderr!r}")
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def test_lock_scope_contradiction_is_rejected_then_normal_start_recovers(self) -> None:
        lock_fd, _lock_path = self._canonical_lock()
        fixture: subprocess.Popen[str] | None = None
        temporary: Path | None = None
        uid = os.getuid()
        nonce = secrets.token_hex(6)
        unit = f"rondo-build-{uid}-072{time.time_ns()}-{os.getpid()}.scope"
        description = f"rondo-plan072-fixture-{nonce}"
        start_ticks = ""
        try:
            baseline = run_helper(f"rondo_active_heavy_scopes {uid}")
            self.assertEqual(baseline.returncode, 0, baseline.stderr)
            self.assertEqual(baseline.stdout, "", f"unexpected heavy scope: {baseline.stdout}")

            temporary = Path(tempfile.mkdtemp(prefix="rondo-plan072-"))
            self.assertEqual(stat.S_IMODE(temporary.stat().st_mode), 0o700)
            conflict_marker = temporary / "conflict.marker"
            recovery_marker = temporary / "recovery.marker"
            fixture = subprocess.Popen(
                [
                    "systemd-run",
                    "--user",
                    "--scope",
                    "--collect",
                    "--quiet",
                    f"--unit={unit}",
                    f"--description={description}",
                    "-p",
                    "KillMode=control-group",
                    "--",
                    "/bin/sleep",
                    "20",
                ],
                close_fds=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            for _ in range(100):
                if fixture.poll() is not None:
                    break
                try:
                    start_ticks = Path(f"/proc/{fixture.pid}/stat").read_text(
                        encoding="utf-8"
                    ).split()[21]
                    self._assert_owned_active(fixture, unit, description, start_ticks)
                    break
                except (AssertionError, FileNotFoundError, StopIteration):
                    time.sleep(0.05)
            else:
                self.fail("task-owned fixture did not become active before deadline")
            self._assert_owned_active(fixture, unit, description, start_ticks)

            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
            lock_fd = -1

            conflict = self._run_wrapper(conflict_marker, temporary / "conflict-metrics")
            self.assertEqual(conflict.returncode, 84, conflict.stderr)
            self.assertIn(unit, conflict.stderr)
            self.assertFalse(conflict_marker.exists())
            self._assert_owned_active(fixture, unit, description, start_ticks)

            subprocess.run(
                [
                    "systemctl",
                    "--user",
                    "kill",
                    "--kill-whom=all",
                    "--signal=SIGTERM",
                    unit,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            fixture.wait(timeout=10)
            for _ in range(100):
                properties = self._properties(unit)
                if properties.get("ActiveState") in {"inactive", "failed"}:
                    break
                time.sleep(0.05)
            else:
                self.fail("task-owned fixture did not become inactive before deadline")

            recovery = self._run_wrapper(recovery_marker, temporary / "recovery-metrics")
            self.assertEqual(recovery.returncode, 0, recovery.stderr)
            self.assertEqual(recovery_marker.read_text(encoding="utf-8"), "plan072\n")
        finally:
            if lock_fd >= 0:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            if fixture is not None and fixture.poll() is None:
                try:
                    self._assert_owned_active(fixture, unit, description, start_ticks)
                except (AssertionError, FileNotFoundError, StopIteration):
                    fixture.wait(timeout=25)
                else:
                    subprocess.run(
                        [
                            "systemctl",
                            "--user",
                            "kill",
                            "--kill-whom=all",
                            "--signal=SIGKILL",
                            unit,
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    fixture.wait(timeout=10)
            if fixture is not None and fixture.poll() is not None:
                fixture.communicate(timeout=1)
            if temporary is not None:
                shutil.rmtree(temporary)


if __name__ == "__main__":
    unittest.main()
