from __future__ import annotations

import copy
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.contracts import (  # noqa: E402
    BinaryManifest,
    ContractError,
    ModelPricing,
    ProviderProjection,
    RunSpec,
    Side,
    assert_fair_pair,
)
from rondo_eval.evidence import (  # noqa: E402
    STATIC_APPROVAL_CONSUMERS,
    STATIC_DECISION_SCHEMA_NAME,
    STATIC_PAYLOAD_SCHEMA_VERSION,
    EvidenceError,
    PolicyIdentity,
    StaticApprovalPayload,
    build_static_payload,
    policy_identity,
    static_payload_bytes_for_consumer,
    validate_static_decision,
    validate_static_payload,
)


POLICY = "policy bytes stay exact\n"
FIXTURES = Path(__file__).with_name("fixtures")
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


# The archived encrypted-only shape: no `content`, empty `summary`, one opaque
# provider transport string.  Synthetic bytes; no archived body is copied here.
ENCRYPTED_ONLY_REASONING = {
    "type": "reasoning",
    "summary": [],
    "encrypted_content": "opaque-provider-transport",
}
PUBLIC_REASONING = {
    "type": "reasoning",
    "id": "rs_provider_session",
    "summary": [
        {"type": "summary_text", "text": "first public summary"},
        {"type": "summary_text", "text": "second public summary"},
    ],
    "content": [
        {"type": "reasoning_text", "text": "public reasoning text"},
        {"type": "text", "text": "public plain text"},
    ],
    "encrypted_content": "opaque-provider-transport",
}


def standard_request(task_input: list | None = None) -> dict:
    return {
        "model": "gpt-5.6-luna",
        "instructions": POLICY,
        "tools": [{"type": "function", "name": "shell"}],
        "input": [*(TASK_INPUT if task_input is None else task_input)],
    }


def lite_request(task_input: list | None = None) -> dict:
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
            *(TASK_INPUT if task_input is None else task_input),
        ],
    }


def forged_payload(payload: StaticApprovalPayload, logical: dict) -> StaticApprovalPayload:
    """Re-canonicalize an edited logical payload so only the edit is under test."""

    canonical = json.dumps(
        logical,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return StaticApprovalPayload(payload.policy_identity, canonical, logical)


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

    def test_static_input_payload_declares_v2_and_v1_cannot_pass_the_sink(self) -> None:
        payload = build_static_payload(standard_request())

        self.assertEqual(STATIC_PAYLOAD_SCHEMA_VERSION, 2)
        self.assertEqual(payload.logical_payload["schema_version"], 2)
        self.assertEqual(payload.policy_identity.schema_version, 2)
        # The structured decision output is a different contract and stays v1.
        self.assertEqual(STATIC_DECISION_SCHEMA_NAME, "rondo_static_approval_v1")

        stale_body = forged_payload(
            payload, {**payload.logical_payload, "schema_version": 1}
        )
        with self.assertRaises(EvidenceError):
            validate_static_payload(stale_body)

        stale_identity = StaticApprovalPayload(
            PolicyIdentity(
                1,
                payload.policy_identity.request_shape,
                payload.policy_identity.sha256,
                "known",
            ),
            payload.canonical_bytes,
            payload.logical_payload,
        )
        with self.assertRaises(EvidenceError):
            validate_static_payload(stale_identity)

    def test_encrypted_only_reasoning_is_dropped_for_all_three_consumers(self) -> None:
        with_reasoning = [TASK_INPUT[0], ENCRYPTED_ONLY_REASONING, *TASK_INPUT[1:]]
        standard = build_static_payload(standard_request(with_reasoning))
        lite = build_static_payload(lite_request(with_reasoning))
        without_reasoning = build_static_payload(standard_request())

        # Dropping the item is exactly equivalent to it never being there.
        self.assertEqual(standard.canonical_bytes, without_reasoning.canonical_bytes)
        self.assertEqual(standard.canonical_bytes, lite.canonical_bytes)
        consumer_bytes = {
            consumer: static_payload_bytes_for_consumer(standard, consumer)
            for consumer in STATIC_APPROVAL_CONSUMERS
        }
        self.assertEqual(
            set(consumer_bytes), {"luna-static", "sol-static", "local-static"}
        )
        self.assertEqual(len(set(consumer_bytes.values())), 1)
        decoded = consumer_bytes["local-static"].decode()
        self.assertNotIn("reasoning", decoded)
        self.assertNotIn("encrypted_content", decoded)
        self.assertNotIn("opaque-provider-transport", decoded)

    def test_public_reasoning_text_becomes_one_neutral_message_in_order(self) -> None:
        with_reasoning = [PUBLIC_REASONING, *TASK_INPUT]
        standard = build_static_payload(standard_request(with_reasoning))
        lite = build_static_payload(lite_request(with_reasoning))

        self.assertEqual(standard.canonical_bytes, lite.canonical_bytes)
        items = standard.logical_payload["input"]
        self.assertEqual(
            items[0],
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "first public summary"},
                    {"type": "output_text", "text": "second public summary"},
                    {"type": "output_text", "text": "public reasoning text"},
                    {"type": "output_text", "text": "public plain text"},
                ],
            },
        )
        # The remaining evidence keeps its order and its existing semantics.
        self.assertEqual(
            items[1:], build_static_payload(standard_request()).logical_payload["input"]
        )
        decoded = standard.canonical_bytes.decode()
        self.assertNotIn("opaque-provider-transport", decoded)
        self.assertNotIn("encrypted_content", decoded)
        self.assertNotIn("rs_provider_session", decoded)

    def test_unknown_or_malformed_reasoning_shapes_are_fail_closed(self) -> None:
        invalid_items = (
            {"type": "reasoning", "summary": [], "encrypted_content": 7},
            {"type": "reasoning", "summary": {}, "encrypted_content": "opaque"},
            {"type": "reasoning", "summary": [], "content": "not-an-array"},
            {"type": "reasoning", "summary": [], "id": 7},
            {"type": "reasoning", "summary": [], "unmapped_future_field": "x"},
            {"type": "reasoning", "summary": [{"type": "summary_text"}]},
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": 7}]},
            {"type": "reasoning", "summary": [{"type": "encrypted_summary", "text": "x"}]},
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "x", "extra": 1}],
            },
            {"type": "reasoning", "summary": ["plain string"]},
            {
                "type": "reasoning",
                "summary": [],
                "content": [{"type": "summary_text", "text": "wrong subtype"}],
            },
        )
        for item in invalid_items:
            with self.subTest(item=item):
                with self.assertRaises(EvidenceError):
                    build_static_payload(standard_request([item, *TASK_INPUT]))
                with self.assertRaises(EvidenceError):
                    build_static_payload(lite_request([item, *TASK_INPUT]))

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

    def test_lite_policy_item_requires_message_discriminator(self) -> None:
        request = lite_request()
        request["input"][1].pop("type")

        identity = policy_identity(request)
        self.assertFalse(identity.aggregatable)
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
        with self.assertRaises(EvidenceError):
            validate_static_decision({**decision, "rationale": ""})

    def test_three_static_consumers_receive_identical_tool_search_fixture_bytes(self) -> None:
        fixture = json.loads(
            (FIXTURES / "static_approval_tool_search.json").read_text(encoding="utf-8")
        )
        standard = build_static_payload(fixture["standard"])
        lite = build_static_payload(fixture["lite"])

        self.assertEqual(standard.canonical_bytes, lite.canonical_bytes)
        consumer_bytes = {
            consumer: static_payload_bytes_for_consumer(standard, consumer)
            for consumer in STATIC_APPROVAL_CONSUMERS
        }
        self.assertEqual(
            set(consumer_bytes),
            {"luna-static", "sol-static", "local-static"},
        )
        self.assertEqual(len(set(consumer_bytes.values())), 1)
        self.assertEqual(
            consumer_bytes["luna-static"],
            consumer_bytes["sol-static"],
        )
        self.assertEqual(
            consumer_bytes["sol-static"],
            consumer_bytes["local-static"],
        )

        logical = json.loads(consumer_bytes["local-static"])
        tool_search = next(
            item for item in logical["input"] if item.get("type") == "tool_search_output"
        )
        self.assertEqual(tool_search["call_id"], "search_fixture")
        self.assertEqual(tool_search["tools"][0]["name"], "mcp__calendar__create_event")
        self.assertNotIn("executed_tool_calls", consumer_bytes["local-static"].decode())
        self.assertNotIn("encrypted_function_args", consumer_bytes["local-static"].decode())

    def test_final_payload_validator_allows_evidence_tools_but_rejects_transport_fields(
        self,
    ) -> None:
        fixture = json.loads(
            (FIXTURES / "static_approval_tool_search.json").read_text(encoding="utf-8")
        )
        payload = build_static_payload(fixture["standard"])
        validate_static_payload(payload)

        mutations = (
            lambda logical: logical.update({"tools": []}),
            lambda logical: logical["input"].append(
                {"type": "additional_tools", "role": "developer", "tools": []}
            ),
            lambda logical: logical["input"][0].update(
                {"tools": [{"type": "function", "name": "message_smuggled"}]}
            ),
            lambda logical: logical["input"][2].update(
                {"tools": [{"type": "function", "name": "function_smuggled"}]}
            ),
            lambda logical: logical["input"][1].update({"tools": {}}),
            lambda logical: logical["input"][0].update(
                {"encrypted_function_args": "private"}
            ),
            lambda logical: logical["input"][0].update(
                {
                    "internal_chat_message_metadata_passthrough": {
                        "turn_id": "turn_fixture",
                        "executed_tool_calls": [],
                    }
                }
            ),
            lambda logical: logical["input"].append(copy.deepcopy(ENCRYPTED_ONLY_REASONING)),
            lambda logical: logical["input"].append(copy.deepcopy(PUBLIC_REASONING)),
            lambda logical: logical["input"][0].update(
                {"encrypted_content": "opaque-provider-transport"}
            ),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                logical = copy.deepcopy(payload.logical_payload)
                mutate(logical)
                with self.assertRaises(EvidenceError):
                    validate_static_payload(forged_payload(payload, logical))


class ContractTests(unittest.TestCase):
    def _spec(self, side: Side) -> RunSpec:
        binary = BinaryManifest(
            path="eval-data/bin/codex",
            sha256="a" * 64,
            code_mode_host_path="eval-data/bin/codex-code-mode-host",
            code_mode_host_sha256="e" * 64,
            bwrap_path="eval-data/bin/codex-resources/bwrap",
            bwrap_sha256="f" * 64,
            bwrap_asset_url=(
                "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
                "bwrap-x86_64-unknown-linux-musl.tar.gz"
            ),
            bwrap_archive_sha256="1" * 64,
            bwrap_source_tree_sha256="2" * 64,
            source_commit="b" * 40,
            source_dirty=False,
            rust_toolchain="rustc 1.95.0",
            build_command=("cargo", "build", "--bin", "codex"),
            code_mode_host_build_command=(
                "cargo", "build", "--bin", "codex-code-mode-host"
            ),
        )
        main_pricing = ModelPricing(
            model_id="test-main-model",
            input_usd_per_million=Decimal("5.00"),
            cached_input_usd_per_million=Decimal("0.50"),
            output_usd_per_million=Decimal("30.00"),
            long_context_threshold_tokens=272_000,
            long_context_input_multiplier=Decimal("2"),
            long_context_output_multiplier=Decimal("1.5"),
            cache_write_input_multiplier=Decimal("1.25"),
            price_snapshot_date="2026-08-10",
            price_source_url="https://developers.openai.com/api/docs/models/compare",
        )
        guardian_pricing = ModelPricing(
            model_id="test-guardian-model",
            input_usd_per_million=Decimal("0.20"),
            cached_input_usd_per_million=Decimal("0.02"),
            output_usd_per_million=Decimal("1.20"),
            long_context_threshold_tokens=272_000,
            long_context_input_multiplier=Decimal("2"),
            long_context_output_multiplier=Decimal("1.5"),
            cache_write_input_multiplier=Decimal("1.25"),
            price_snapshot_date="2026-08-10",
            price_source_url="https://developers.openai.com/api/docs/models/compare",
        )
        provider = ProviderProjection(
            provider_id="relay",
            display_name="Test relay",
            api="responses",
            base_url="https://relay.example/v1",
            api_key_env="OPENAI_API_KEY",
            main_model=main_pricing.model_id,
            main_effort="medium",
            guardian_model=guardian_pricing.model_id,
            guardian_effort="low",
            main_pricing=main_pricing,
            guardian_pricing=guardian_pricing,
            max_attempts=5,
            retry_backoff_seconds=1.0,
            unbilled_retry_statuses=(429, 500, 502, 503, 504),
            profile_sha256="3" * 64,
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

    def test_public_provider_projection_is_complete_and_redacted(self) -> None:
        provider = self._spec(Side.CODEX).provider
        projected = provider.to_public_dict()
        serialized = json.dumps(projected, sort_keys=True)

        self.assertEqual(projected["provider_profile_sha256"], "3" * 64)
        self.assertEqual(len(projected["provider_endpoint_sha256"]), 64)
        self.assertEqual(projected["main_model"], "test-main-model")
        self.assertEqual(projected["main_effort"], "medium")
        self.assertEqual(projected["guardian_model"], "test-guardian-model")
        self.assertNotIn(provider.base_url, serialized)
        self.assertNotIn(provider.display_name, serialized)
        self.assertNotIn(provider.api_key_env, serialized)
        self.assertNotIn(provider.config_sha256, serialized)

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
        object.__setattr__(spec, "budget_usd", 40.01)
        with self.assertRaises(ContractError):
            spec.validate()
        spec = self._spec(Side.CODEX)
        object.__setattr__(spec.binary, "workspace_lock_normalization", "")
        with self.assertRaises(ContractError):
            spec.validate()


if __name__ == "__main__":
    unittest.main()
