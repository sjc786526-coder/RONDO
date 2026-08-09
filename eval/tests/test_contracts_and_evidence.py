from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import (  # noqa: E402
    BinaryManifest,
    ContractError,
    ProviderProjection,
    RunSpec,
    Side,
    assert_fair_pair,
)
from rondo_eval.evidence import (  # noqa: E402
    EvidenceError,
    build_static_payload,
    policy_identity,
    validate_static_decision,
)


POLICY = "policy bytes stay exact\n"
TASK_INPUT = [
    {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "review this"}],
        "internal_chat_message_metadata_passthrough": {
            "turn_id": "turn_0",
            "executed_tool_calls": [{"name": "shell"}],
        },
    },
    {
        "type": "function_call",
        "name": "shell",
        "call_id": "call_0",
        "arguments": "{}",
        "encrypted_function_args": "private",
    },
    {"type": "function_call_output", "call_id": "call_0", "output": "ok"},
    {
        "type": "message",
        "role": "developer",
        "content": [
            {"type": "input_text", "text": "approval reason: retry was denied"}
        ],
    },
]


def standard_request() -> dict:
    return {
        "model": "gpt-5.6-luna",
        "instructions": POLICY,
        "tools": [{"type": "function", "name": "shell"}],
        "input": TASK_INPUT,
    }


def lite_request() -> dict:
    return {
        "model": "gpt-5.6-luna",
        "input": [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [{"type": "function", "name": "shell"}],
            },
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": POLICY}],
            },
            *TASK_INPUT,
        ],
    }


class EvidenceTests(unittest.TestCase):
    def test_standard_and_lite_produce_identical_static_bytes(self) -> None:
        standard = build_static_payload(standard_request())
        lite = build_static_payload(lite_request())

        self.assertEqual(standard.canonical_bytes, lite.canonical_bytes)
        self.assertEqual(standard.policy_identity.sha256, lite.policy_identity.sha256)
        serialized = json.loads(standard.canonical_bytes)
        self.assertNotIn("tools", serialized)
        self.assertNotIn("additional_tools", standard.canonical_bytes.decode())
        self.assertNotIn("executed_tool_calls", standard.canonical_bytes.decode())
        self.assertNotIn("encrypted_function_args", standard.canonical_bytes.decode())
        self.assertIn("approval reason: retry was denied", standard.canonical_bytes.decode())
        self.assertIn("turn_id", standard.canonical_bytes.decode())
        self.assertEqual(serialized["input"][1]["type"], "function_call")

    def test_policy_hash_uses_exact_utf8_bytes(self) -> None:
        first = policy_identity(standard_request())
        changed = standard_request()
        changed["instructions"] = POLICY.rstrip()
        second = policy_identity(changed)

        self.assertTrue(first.aggregatable)
        self.assertNotEqual(first.sha256, second.sha256)

    def test_ambiguous_shape_is_unknown_and_static_build_fails(self) -> None:
        request = lite_request()
        request["instructions"] = "also standard"

        identity = policy_identity(request)
        self.assertFalse(identity.aggregatable)
        self.assertEqual(identity.request_shape, "unknown")
        with self.assertRaises(EvidenceError):
            build_static_payload(request)

    def test_lite_policy_position_is_fail_closed(self) -> None:
        request = lite_request()
        request["input"].insert(1, {"type": "message", "role": "user", "content": []})

        with self.assertRaises(EvidenceError):
            build_static_payload(request)

    def test_malformed_or_duplicate_additional_tools_is_fail_closed(self) -> None:
        malformed = lite_request()
        malformed["input"][0]["role"] = "user"
        with self.assertRaises(EvidenceError):
            build_static_payload(malformed)

        duplicate = lite_request()
        duplicate["input"].append(
            {"type": "additional_tools", "role": "developer", "tools": []}
        )
        with self.assertRaises(EvidenceError):
            build_static_payload(duplicate)

    def test_static_decision_contract_is_strict(self) -> None:
        decision = {"outcome": "deny", "rationale": "unsafe", "risk_tags": ["destructive"]}
        self.assertEqual(validate_static_decision(decision), decision)
        with self.assertRaises(EvidenceError):
            validate_static_decision({**decision, "extra": True})
        with self.assertRaises(EvidenceError):
            validate_static_decision({**decision, "outcome": []})


class ContractTests(unittest.TestCase):
    def _spec(self, side: Side) -> RunSpec:
        binary = BinaryManifest(
            path="eval-data/bin/codex",
            sha256="a" * 64,
            code_mode_host_path="eval-data/bin/codex-code-mode-host",
            code_mode_host_sha256="e" * 64,
            bwrap_path="eval-data/bin/codex-resources/bwrap",
            bwrap_sha256="f" * 64,
            libcap_version="2.78",
            libcap_archive_sha256="1" * 64,
            libcap_static_sha256="2" * 64,
            source_commit="b" * 40,
            source_dirty=False,
            rust_toolchain="rustc 1.95.0",
            build_command=("cargo", "build", "--bin", "codex"),
            code_mode_host_build_command=(
                "cargo", "build", "--bin", "codex-code-mode-host"
            ),
            bwrap_build_command=("package", "bwrap"),
        )
        provider = ProviderProjection(
            provider_id="openai",
            api="responses",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            main_model="gpt-5.6-luna",
            guardian_model="gpt-5.6-luna",
            guardian_effort="low",
            config_sha256="d" * 64,
        )
        return RunSpec(
            side=side,
            batch_id="p1-minimal",
            task_id="example",
            task_image_digest=f"sha256:{'c' * 64}",
            binary=binary,
            terminal_bench_version="frozen",
            provider=provider,
        )

    def test_fair_pair_accepts_only_side_difference(self) -> None:
        assert_fair_pair(self._spec(Side.CODEX), self._spec(Side.RONDO))

    def test_fair_pair_rejects_configuration_drift(self) -> None:
        drifted = self._spec(Side.RONDO)
        object.__setattr__(drifted, "timeout_seconds", 99)
        with self.assertRaises(ContractError):
            assert_fair_pair(self._spec(Side.CODEX), drifted)

    def test_fair_pair_rejects_budget_drift(self) -> None:
        drifted = self._spec(Side.RONDO)
        object.__setattr__(drifted, "budget_usd", 4.0)
        with self.assertRaises(ContractError):
            assert_fair_pair(self._spec(Side.CODEX), drifted)

    def test_code_mode_host_is_frozen_on_in_fairness_contract(self) -> None:
        spec = self._spec(Side.CODEX)
        self.assertIs(spec.fairness_fingerprint()["code_mode_host"], True)
        for invalid in (False, 1, None):
            with self.subTest(invalid=invalid):
                spec = self._spec(Side.CODEX)
                object.__setattr__(spec, "code_mode_host", invalid)
                with self.assertRaises(ContractError):
                    spec.validate()

    def test_workspace_write_network_access_is_frozen_on_for_container_runtime(self) -> None:
        spec = self._spec(Side.CODEX)
        self.assertIs(spec.fairness_fingerprint()["sandbox_network_access"], True)
        for invalid in (False, 1, None):
            with self.subTest(invalid=invalid):
                spec = self._spec(Side.CODEX)
                object.__setattr__(spec, "sandbox_network_access", invalid)
                with self.assertRaises(ContractError):
                    spec.validate()

    def test_contract_rejects_floating_image(self) -> None:
        spec = self._spec(Side.CODEX)
        object.__setattr__(spec, "task_image_digest", "ubuntu:latest")
        with self.assertRaises(ContractError):
            spec.validate()

    def test_contract_rejects_typed_manifest_and_budget_confusion(self) -> None:
        spec = self._spec(Side.CODEX)
        object.__setattr__(spec.binary, "source_dirty", "false")
        with self.assertRaises(ContractError):
            spec.validate()
        spec = self._spec(Side.CODEX)
        object.__setattr__(spec, "budget_usd", 5.01)
        with self.assertRaises(ContractError):
            spec.validate()
        spec = self._spec(Side.CODEX)
        object.__setattr__(spec.binary, "workspace_lock_normalization", "")
        with self.assertRaises(ContractError):
            spec.validate()


if __name__ == "__main__":
    unittest.main()
