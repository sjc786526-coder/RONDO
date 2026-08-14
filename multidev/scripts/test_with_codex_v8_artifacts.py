#!/usr/bin/env python3

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from with_codex_v8_artifacts import child_environment
from with_codex_v8_artifacts import parse_command
from with_codex_v8_artifacts import parse_rustc_host
from with_codex_v8_artifacts import source_build_requested


class WithCodexV8ArtifactsTest(unittest.TestCase):
    def test_parse_command_requires_separator_and_command(self) -> None:
        for argv in [[], ["--"], ["cargo", "test"]]:
            with self.subTest(argv=argv), self.assertRaisesRegex(RuntimeError, "usage"):
                parse_command(argv)

        self.assertEqual(
            parse_command(["--", "cargo", "nextest", "run"]),
            ["cargo", "nextest", "run"],
        )

    def test_parse_rustc_host_uses_native_gnu_target(self) -> None:
        spec = parse_rustc_host(
            "rustc 1.95.0\n"
            "binary: rustc\n"
            "host: x86_64-unknown-linux-gnu\n"
            "release: 1.95.0\n"
        )

        self.assertEqual(spec.target, "x86_64-unknown-linux-gnu")

    def test_parse_rustc_host_rejects_missing_duplicate_and_unknown_targets(
        self,
    ) -> None:
        for output, message in [
            ("rustc 1.95.0\n", "exactly one host"),
            (
                "host: x86_64-unknown-linux-gnu\nhost: aarch64-unknown-linux-gnu\n",
                "exactly one host",
            ),
            ("host: riscv64gc-unknown-linux-gnu\n", "Unsupported rustc host target"),
        ]:
            with (
                self.subTest(output=output),
                self.assertRaisesRegex(RuntimeError, message),
            ):
                parse_rustc_host(output)

    def test_source_build_is_rejected_whenever_variable_is_present(self) -> None:
        self.assertFalse(source_build_requested({}))
        self.assertTrue(source_build_requested({"V8_FROM_SOURCE": "1"}))
        self.assertTrue(source_build_requested({"V8_FROM_SOURCE": "0"}))
        self.assertTrue(source_build_requested({"V8_FROM_SOURCE": ""}))

    def test_child_environment_replaces_both_ambient_overrides(self) -> None:
        environ = {
            "KEEP": "value",
            "RUSTY_V8_ARCHIVE": "/ambient/archive",
            "RUSTY_V8_SRC_BINDING_PATH": "/ambient/binding",
        }

        child_env = child_environment(
            environ,
            Path("/verified/archive"),
            Path("/verified/binding"),
        )

        self.assertEqual(
            child_env,
            {
                "KEEP": "value",
                "RUSTY_V8_ARCHIVE": "/verified/archive",
                "RUSTY_V8_SRC_BINDING_PATH": "/verified/binding",
            },
        )
        self.assertEqual(environ["RUSTY_V8_ARCHIVE"], "/ambient/archive")
        self.assertEqual(environ["RUSTY_V8_SRC_BINDING_PATH"], "/ambient/binding")


if __name__ == "__main__":
    unittest.main()
