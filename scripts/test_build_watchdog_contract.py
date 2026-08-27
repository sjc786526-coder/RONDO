import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LIBRARY = REPO_ROOT / "scripts/build-watchdog-lib.sh"
WRAPPER = REPO_ROOT / "scripts/with-build-lock.sh"


def run_helper(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", f"source {shlex.quote(str(LIBRARY))}; {command}"],
        check=False,
        capture_output=True,
        text=True,
    )


def init_repository(repository: Path) -> None:
    subprocess.run(["git", "init", str(repository)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=RONDO Test",
            "-c",
            "user.email=rondo-test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "initial",
        ],
        check=True,
        capture_output=True,
    )


class BuildWatchdogContractTests(unittest.TestCase):
    def test_wrapper_exports_only_explicit_or_product_target(self) -> None:
        environment = dict(os.environ)
        environment.pop("CARGO_TARGET_DIR", None)
        environment.update(
            {
                "RONDO_BUILD_LOCK": "0",
                "RONDO_BUILD_WATCHDOG": "0",
            }
        )
        payload = [
            str(WRAPPER),
            "python3",
            "-c",
            "import os; print(os.environ.get('CARGO_TARGET_DIR', 'absent'))",
        ]
        common_dir = subprocess.run(
            [
                "git",
                "-C",
                str(REPO_ROOT),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        expected = (
            Path(common_dir.stdout.strip()).resolve().parent
            / ".codex/cargo-target/rondo-multi"
        )
        existed_before = expected.exists()
        legacy = subprocess.run(
            payload,
            cwd=REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        product_environment = dict(environment)
        product_environment["RONDO_BUILD_CARGO_PRODUCT"] = "rondo-multi"
        product = subprocess.run(
            payload,
            cwd=REPO_ROOT,
            env=product_environment,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(legacy.returncode, 0, legacy.stderr)
        self.assertEqual(legacy.stdout, "absent\n")
        self.assertEqual(product.returncode, 0, product.stderr)
        self.assertEqual(product.stdout, f"{expected}\n")
        self.assertEqual(expected.exists(), existed_before)

    def test_linked_worktree_target_mapping_is_shared_and_product_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            linked = root / "linked"
            init_repository(repository)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "worktree",
                    "add",
                    "-b",
                    "linked",
                    str(linked),
                ],
                check=True,
                capture_output=True,
            )

            main_multi = run_helper(
                f"rondo_product_cargo_target {shlex.quote(str(repository))} rondo-multi"
            )
            linked_multi = run_helper(
                f"rondo_product_cargo_target {shlex.quote(str(linked))} rondo-multi"
            )
            linked_local = run_helper(
                f"rondo_product_cargo_target {shlex.quote(str(linked))} rondo-local"
            )

            expected_root = repository.resolve()
            expected_multi = expected_root / ".codex/cargo-target/rondo-multi"
            expected_local = expected_root / ".codex/cargo-target/rondo-local"
            self.assertEqual(main_multi.returncode, 0, main_multi.stderr)
            self.assertEqual(linked_multi.returncode, 0, linked_multi.stderr)
            self.assertEqual(linked_local.returncode, 0, linked_local.stderr)
            self.assertEqual(main_multi.stdout, str(expected_multi))
            self.assertEqual(linked_multi.stdout, str(expected_multi))
            self.assertEqual(linked_local.stdout, str(expected_local))
            self.assertFalse(expected_multi.exists())
            self.assertFalse(expected_local.exists())

    def test_invalid_product_non_git_checkout_and_limit_order_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            non_git_root = root / "not-a-repository"
            init_repository(repository)
            non_git_root.mkdir()
            unknown = run_helper(
                f"rondo_product_cargo_target {shlex.quote(str(repository))} unknown"
            )
            non_git = run_helper(
                f"rondo_product_cargo_target {shlex.quote(str(non_git_root))} rondo-multi"
            )

        equal = run_helper(
            "rondo_project_limits_are_valid 270000000000 270000000000 "
            "290000000000 5"
        )
        reversed_limits = run_helper(
            "rondo_project_limits_are_valid 290000000000 285000000000 "
            "270000000000 5"
        )
        zero_interval = run_helper(
            "rondo_project_limits_are_valid 270000000000 285000000000 "
            "290000000000 0"
        )
        self.assertNotEqual(unknown.returncode, 0)
        self.assertNotEqual(non_git.returncode, 0)
        self.assertNotEqual(equal.returncode, 0)
        self.assertNotEqual(reversed_limits.returncode, 0)
        self.assertNotEqual(zero_interval.returncode, 0)

    def test_effective_summary_records_product_target_and_all_storage_limits(self) -> None:
        summary = run_helper(
            "rondo_write_effective_run_summary_fields "
            "/repo rondo-multi /repo/.codex/cargo-target/rondo-multi "
            "270000000000 285000000000 290000000000 50000000000"
        )

        self.assertEqual(summary.returncode, 0, summary.stderr)
        self.assertEqual(
            summary.stdout.splitlines(),
            [
                "project_root=/repo",
                "cargo_product=rondo-multi",
                "cargo_target_dir=/repo/.codex/cargo-target/rondo-multi",
                "project_warn_bytes=270000000000",
                "project_stop_bytes=285000000000",
                "project_max_bytes=290000000000",
                "windows_c_free_stop_bytes=50000000000",
            ],
        )

    def test_oom_message_requires_cgroup_oom_evidence(self) -> None:
        confirmed = run_helper(
            "rondo_payload_was_confirmed_oom_killed 137 cgroup_reported_oom_kill"
        )
        psi_stop = run_helper(
            "rondo_payload_was_confirmed_oom_killed 137 "
            "memory_full_psi_sustained_above_limit"
        )
        unexplained_sigkill = run_helper(
            "rondo_payload_was_confirmed_oom_killed 137 none"
        )
        ordinary_failure = run_helper(
            "rondo_payload_was_confirmed_oom_killed 1 cgroup_reported_oom_kill"
        )

        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        self.assertNotEqual(psi_stop.returncode, 0)
        self.assertNotEqual(unexplained_sigkill.returncode, 0)
        self.assertNotEqual(ordinary_failure.returncode, 0)


if __name__ == "__main__":
    unittest.main()
