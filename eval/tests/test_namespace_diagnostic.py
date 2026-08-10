from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.terminal_bench.namespace_diagnostic import (  # noqa: E402
    DIAGNOSTIC_SCRIPT,
    NamespaceDiagnosticError,
    NamespaceDiagnosticSpec,
    build_namespace_diagnostic_plan,
    main,
    run_supervised_namespace_diagnostic,
)
from rondo_eval.docker_supervisor import (  # noqa: E402
    DockerLimits,
    DockerTaskIdentity,
    _validate_diagnostic_argv,
)


IMAGE = f"example.invalid/fix-git@sha256:{'a' * 64}"


class NamespaceDiagnosticTests(unittest.TestCase):
    def _spec(self, root: Path, *, profile: Path | None = None) -> NamespaceDiagnosticSpec:
        bwrap = root / "eval-data" / "bin" / "bwrap"
        bwrap.parent.mkdir(parents=True, exist_ok=True)
        bwrap.write_bytes(b"frozen-bwrap")
        bwrap.chmod(0o700)
        return NamespaceDiagnosticSpec(
            common_root=root,
            project_root=root,
            image=IMAGE,
            task_id="20260810-namespace-diag-r1",
            bwrap_binary=bwrap,
            bwrap_sha256=hashlib.sha256(bwrap.read_bytes()).hexdigest(),
            seccomp_profile=profile,
        )

    def test_default_plan_is_inert_nonprivileged_and_collects_fixed_facts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = build_namespace_diagnostic_plan(self._spec(root))

        argv = plan.argv
        lowered = tuple(value.casefold() for value in argv)
        self.assertIsNone(plan.seccomp_profile_sha256)
        self.assertIsNone(plan.seccomp_profile_source_sha256)
        self.assertEqual(argv[:3], ("docker", "container", "run"))
        self.assertNotIn("--privileged", lowered)
        self.assertNotIn("--cap-add", lowered)
        self.assertNotIn("seccomp=unconfined", lowered)
        self.assertEqual(argv[argv.index("--cap-drop") + 1], "ALL")
        self.assertEqual(argv[argv.index("--user") + 1], "1000:1000")
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertIn("--read-only", argv)
        self.assertEqual(argv[-1], DIAGNOSTIC_SCRIPT)
        for marker in (
            "max_user_namespaces",
            "unprivileged_userns_clone",
            "^CapEff:",
            "unshare_userns",
            "bwrap_baseline",
        ):
            self.assertIn(marker, DIAGNOSTIC_SCRIPT)
        _validate_diagnostic_argv(
            plan.argv,
            DockerTaskIdentity("20260810-namespace-diag-r1"),
            DockerLimits(512 * 1024**2, 768 * 1024**2, 128, 60),
        )

    def test_frozen_binary_may_live_in_common_root_outside_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            common_root = Path(temporary)
            checkout = common_root / ".claude" / "worktrees" / "diagnostic"
            checkout.mkdir(parents=True)
            bwrap = common_root / "eval-data" / "deps" / "bwrap"
            bwrap.parent.mkdir(parents=True)
            bwrap.write_bytes(b"frozen-bwrap")
            bwrap.chmod(0o700)
            spec = NamespaceDiagnosticSpec(
                common_root=common_root,
                project_root=checkout,
                image=IMAGE,
                task_id="20260810-namespace-diag-r2",
                bwrap_binary=bwrap,
                bwrap_sha256=hashlib.sha256(bwrap.read_bytes()).hexdigest(),
            )

            plan = build_namespace_diagnostic_plan(spec)

        mount = plan.argv[plan.argv.index("--mount") + 1]
        self.assertIn(f"source={bwrap.resolve()}", mount)

    def test_custom_profile_must_be_exact_frozen_tracked_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            profile = root / "eval" / "seccomp" / "plan008-userns-minimal-v0.2.3.json"
            profile.parent.mkdir(parents=True)
            profile.write_bytes((EVAL_ROOT / "seccomp" / profile.name).read_bytes())
            checks: list[tuple[Path, Path]] = []
            plan = build_namespace_diagnostic_plan(
                self._spec(root, profile=profile),
                tracked_file_check=lambda project, path: checks.append((project, path)),
            )
            source_digest = "9c5198e529f03d38babe9f270f663fa6867bda4e4d14a37a1f6680179d9bbd2f"
            digest = "a67068e2712d6dd8168d96c71e5e46df2ec74e1ef7c6e49bf54447c5a12fa3bf"
            resolved_root = root.resolve()
            resolved_profile = profile.resolve()

            _validate_diagnostic_argv(
                plan.argv,
                DockerTaskIdentity("20260810-namespace-diag-r1"),
                DockerLimits(512 * 1024**2, 768 * 1024**2, 128, 60),
            )

        self.assertEqual(plan.seccomp_profile_sha256, digest)
        self.assertEqual(plan.seccomp_profile_source_sha256, source_digest)
        self.assertEqual(checks, [(resolved_root, resolved_profile)])
        self.assertIn(f"seccomp={resolved_profile}", plan.argv)
        self.assertIn(f"dev.rondo.eval.seccomp-profile-sha256={source_digest}", plan.argv)

    def test_rejects_floating_image_bad_binary_and_unsafe_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = self._spec(root)
            with self.assertRaises(NamespaceDiagnosticError):
                build_namespace_diagnostic_plan(
                    NamespaceDiagnosticSpec(**{**spec.__dict__, "image": "image:latest"})
                )
            with self.assertRaises(NamespaceDiagnosticError):
                build_namespace_diagnostic_plan(
                    NamespaceDiagnosticSpec(**{**spec.__dict__, "bwrap_sha256": "0" * 64})
                )

            profile = root / "unsafe.json"
            for document in (
                {
                    "defaultAction": "SCMP_ACT_ALLOW",
                    "syscalls": [{"names": ["unshare"], "action": "SCMP_ACT_ALLOW"}],
                },
                {
                    "defaultAction": "SCMP_ACT_ERRNO",
                    "syscalls": [{"names": ["unshare"], "action": "SCMP_ACT_NOTIFY"}],
                },
                {
                    "defaultAction": "SCMP_ACT_ERRNO",
                    "syscalls": [{"names": ["read"], "action": "SCMP_ACT_ALLOW"}],
                },
            ):
                with self.subTest(document=document):
                    profile.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(NamespaceDiagnosticError):
                        build_namespace_diagnostic_plan(
                            self._spec(root, profile=profile),
                            tracked_file_check=lambda _project, _path: None,
                        )

    def test_public_run_uses_watchdog_supervisor_and_returns_safe_structure(self) -> None:
        output = "\n".join(
            (
                "uid=1000", "gid=1000", "max_user_namespaces=15000",
                "unprivileged_userns_clone=1", "cap_eff=0000000000000000",
                "no_new_privs=1", "seccomp=2", "seccomp_filters=1",
                "unshare_userns=denied", "unshare_errno=1", "bwrap_baseline=denied",
            )
        ) + "\n"

        class Capture:
            def safe_output(self):
                return output

        calls = []

        class Supervisor:
            def __init__(self, **kwargs):
                calls.append(kwargs)

            def supervise_diagnostic_command(self, *args, **kwargs):
                calls.append((args, kwargs))
                return SimpleNamespace(
                    returncode=0,
                    samples=(
                        SimpleNamespace(
                            docker_total_bytes=100,
                            task_bytes=0,
                            data_root_filesystem_free_bytes=200,
                            data_root="/mnt/c",
                        ),
                        SimpleNamespace(
                            docker_total_bytes=120,
                            task_bytes=0,
                            data_root_filesystem_free_bytes=180,
                            data_root="/mnt/c",
                        ),
                    ),
                    warnings=("docker growth reached the warning threshold",),
                )

        with tempfile.TemporaryDirectory() as temporary:
            result = run_supervised_namespace_diagnostic(
                self._spec(Path(temporary)), docker_data_root=Path("/var/lib/docker"),
                watchdog_factory=lambda: SimpleNamespace(
                    lease=SimpleNamespace(token="a" * 48, held=True, validate=lambda: None),
                    guard=object(),
                ),
                runner=Capture(), counter=object(), cleanup_runner=object(),
                supervisor_factory=Supervisor,
            )

        self.assertEqual(result.unshare_errno, 1)
        self.assertEqual(result.docker_sample_count, 2)
        self.assertEqual(result.docker_baseline_total_bytes, 100)
        self.assertEqual(result.docker_final_total_bytes, 120)
        self.assertEqual(result.docker_baseline_data_root_free_bytes, 200)
        self.assertEqual(result.docker_final_data_root_free_bytes, 180)
        self.assertEqual(result.docker_data_root, "/mnt/c")
        self.assertEqual(
            result.docker_warnings,
            ("docker growth reached the warning threshold",),
        )
        self.assertEqual(len(calls), 2)

    def test_cli_never_executes_and_requires_explicit_emit_mode(self) -> None:
        with self.assertRaises(NamespaceDiagnosticError):
            main(
                [
                    "--project-root",
                    "/does/not/matter",
                    "--common-root",
                    "/does/not/matter",
                    "--image",
                    IMAGE,
                    "--task-id",
                    "20260810-namespace-diag-r1",
                    "--bwrap",
                    "/does/not/matter/bwrap",
                    "--bwrap-sha256",
                    "0" * 64,
                ]
            )


if __name__ == "__main__":
    unittest.main()
