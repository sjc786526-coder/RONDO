from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"
LIBRARY = SCRIPTS_DIR / "build-watchdog-lib.sh"


def run_helper(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(LIBRARY))}; {command}"],
        check=False,
        capture_output=True,
        text=True,
    )


class BuildWatchdogLibraryTests(unittest.TestCase):
    def test_population_uses_descendant_aware_cgroup_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cgroup.events").write_text("populated 1\nfrozen 0\n", encoding="utf-8")
            (root / "cgroup.procs").write_text("", encoding="utf-8")

            result = run_helper(
                f"rondo_cgroup_population_state {shlex.quote(str(root))} {os.getpid()}"
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "active")

    def test_population_only_reports_gone_for_populated_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cgroup.events").write_text("populated 0\n", encoding="utf-8")

            result = run_helper(
                f"rondo_cgroup_population_state {shlex.quote(str(root))} {os.getpid()}"
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "gone")

    def test_population_treats_unreadable_or_malformed_fact_as_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "cgroup.events").write_text("populated maybe\n", encoding="utf-8")

            result = run_helper(
                f"rondo_cgroup_population_state {shlex.quote(str(root))} {os.getpid()}"
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "unknown")

    def test_population_requires_both_missing_cgroup_and_dead_runner_for_gone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            live = run_helper(
                f"rondo_cgroup_population_state {shlex.quote(str(missing))} {os.getpid()}"
            )
            dead = run_helper(
                f"rondo_cgroup_population_state {shlex.quote(str(missing))} 999999999"
            )

        self.assertEqual(live.stdout, "unknown")
        self.assertEqual(dead.stdout, "gone")

    def test_direct_kill_walks_descendants_and_rechecks_membership(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            child = root / "child"
            proc_root = root / "proc"
            record = root / "signals.txt"
            child.mkdir()
            (root / "cgroup.procs").write_text("123\nnot-a-pid\n1\n", encoding="utf-8")
            (child / "cgroup.procs").write_text("456\n", encoding="utf-8")
            (proc_root / "123").mkdir(parents=True)
            (proc_root / "456").mkdir(parents=True)
            (proc_root / "123/cgroup").write_text(
                "0::/expected.scope/child\n", encoding="utf-8"
            )
            (proc_root / "456/cgroup").write_text(
                "0::/unrelated.scope\n", encoding="utf-8"
            )

            result = run_helper(
                f"kill() {{ printf '%s\\n' \"$*\" >> {shlex.quote(str(record))}; }}; "
                "rondo_kill_cgroup_subtree "
                f"{shlex.quote(str(root))} /expected.scope {shlex.quote(str(proc_root))}"
            )
            signals = record.read_text(encoding="utf-8").splitlines()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(signals, ["-KILL 123"])

    def test_direct_kill_prefers_atomic_cgroup_kill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cgroup_kill = root / "cgroup.kill"
            cgroup_kill.write_text("", encoding="utf-8")

            result = run_helper(
                "kill() { return 99; }; "
                "rondo_kill_cgroup_subtree "
                f"{shlex.quote(str(root))} /expected.scope"
            )
            written = cgroup_kill.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(written, "1")

    def test_nextest_config_keeps_local_profile_and_uses_unique_junit_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "nextest-source.toml"
            output = root / "nextest-run.toml"
            junit = root / "junit-local.xml"
            source.write_text(
                "[profile.default]\ntest-threads = 10\n\n[profile.local]\ninherits = \"default\"\n",
                encoding="utf-8",
            )

            result = run_helper(
                "rondo_prepare_nextest_config "
                f"{shlex.quote(str(source))} {shlex.quote(str(output))} {shlex.quote(str(junit))}"
            )
            with output.open("rb") as handle:
                config = tomllib.load(handle)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(config["profile"]["local"]["inherits"], "default")
        self.assertEqual(config["profile"]["local"]["junit"]["path"], str(junit))

    def test_nextest_config_rejects_an_existing_local_junit_override(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "nextest-source.toml"
            output = root / "nextest-run.toml"
            junit = root / "junit-local.xml"
            source.write_text(
                "[profile.local.junit]\npath = \"existing.xml\"\n",
                encoding="utf-8",
            )

            result = run_helper(
                "rondo_prepare_nextest_config "
                f"{shlex.quote(str(source))} {shlex.quote(str(output))} {shlex.quote(str(junit))}"
            )

        self.assertNotEqual(result.returncode, 0)

    def test_junit_report_statuses_are_explicit_and_content_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.xml"
            invalid = root / "invalid.xml"
            retained = root / "retained.xml"
            invalid.write_text("<testsuites>\n", encoding="utf-8")
            retained.write_text(
                '<?xml version="1.0"?>\n<testsuites tests="1">\n</testsuites>\n',
                encoding="utf-8",
            )

            missing_result = run_helper(
                f"rondo_inspect_junit_report {shlex.quote(str(missing))}"
            )
            invalid_result = run_helper(
                f"rondo_inspect_junit_report {shlex.quote(str(invalid))}"
            )
            retained_result = run_helper(
                f"rondo_inspect_junit_report {shlex.quote(str(retained))}"
            )

        status, digest = retained_result.stdout.rstrip("\n").split("\t")
        self.assertEqual(missing_result.stdout, "absent\t\n")
        self.assertEqual(invalid_result.stdout, "invalid\t\n")
        self.assertEqual(status, "retained")
        self.assertRegex(digest, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
