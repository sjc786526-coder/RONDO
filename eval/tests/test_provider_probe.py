from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.api_budget_proxy import (  # noqa: E402
    PersistentBudgetLedger,
    _UrllibTransport,
)
from rondo_eval.config import RepoPaths, RuntimeConfig  # noqa: E402
from rondo_eval.provider_probe import (  # noqa: E402
    PROBE_USER_AGENT,
    PROBE_BATCH_ID,
    PROBE_RUN_ID,
    PROBE_TOTAL_CAP_USD,
    ProviderProbeError,
    probe_models_status,
    run_provider_probes,
)


def _paid_eval_config(
    root: Path,
    *,
    main_model: str = "gpt-test-main",
    guardian_model: str = "gpt-test-guardian",
    guardian_effort: str = "low",
) -> RuntimeConfig:
    price_source = "https://developers.openai.com/api/docs/models/compare"

    def model(model_id: str) -> dict[str, str]:
        return {
            "model_id": model_id,
            "input_usd_per_million": "5",
            "cached_input_usd_per_million": "0.5",
            "output_usd_per_million": "30",
            "long_context_threshold_tokens": 272_000,
            "long_context_input_multiplier": "2",
            "long_context_output_multiplier": "1.5",
            "cache_write_input_multiplier": "1.25",
            "price_snapshot_date": "2026-08-10",
            "price_source_url": price_source,
        }

    return RuntimeConfig(
        RepoPaths(root, root),
        {
            "paid_eval": {
                "active_provider": "relay",
                "main_model": "main",
                "guardian_model": "guardian",
                "guardian_reasoning_effort": guardian_effort,
                "max_attempts": 5,
                "retry_backoff_seconds": 0.0,
                "providers": {
                    "relay": {
                        "display_name": "Test relay",
                        "api": "responses",
                        "base_url": "https://provider.example/v1",
                        "api_key_env": "OPENAI_API_KEY",
                        "unbilled_retry_statuses": [429, 500, 502, 503, 504],
                    }
                },
                "models": {
                    "main": model(main_model),
                    "guardian": model(guardian_model),
                },
            }
        },
        "a" * 64,
    )


class _Provider:
    def __init__(self) -> None:
        self.secret = "provider-probe-secret-sentinel"
        self.models_redirect = False
        self.guardian_failure = False
        self.requests: list[dict[str, object]] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                if self.path != "/v1/models":
                    self.send_error(404)
                    return
                owner.requests.append({
                    "method": "GET",
                    "authorization": self.headers.get("Authorization"),
                    "user_agent": self.headers.get("User-Agent"),
                    "originator": self.headers.get("originator"),
                })
                if owner.models_redirect:
                    self.send_response(302)
                    self.send_header("Location", "https://redirect.example/v1/models")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                payload = b'{"object":"list","data":[]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["Content-Length"])
                body = json.loads(self.rfile.read(length))
                owner.requests.append({
                    "method": "POST",
                    "authorization": self.headers.get("Authorization"),
                    "role": self.headers.get("X-RONDO-Eval-Role"),
                    "user_agent": self.headers.get("User-Agent"),
                    "originator": self.headers.get("originator"),
                    "body": body,
                })
                if owner.guardian_failure and self.headers.get("X-RONDO-Eval-Role") == "guardian":
                    payload = b'{"error":{"code":"temporary_unavailable"}}'
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                usage = {
                    "input_tokens": 12,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 3,
                }
                if body.get("stream") is True:
                    event = {
                        "type": "response.completed",
                        "response": {"id": "resp-stream", "usage": usage},
                    }
                    payload = (
                        "event: response.completed\ndata: "
                        + json.dumps(event, separators=(",", ":"))
                        + "\n\n"
                    ).encode()
                    content_type = "text/event-stream"
                else:
                    payload = json.dumps({
                        "id": "resp-nonstream",
                        "status": "completed",
                        "output": [],
                        "usage": usage,
                    }, separators=(",", ":")).encode()
                    content_type = "application/json"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class ProviderProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.provider = _Provider()
        self.config = _paid_eval_config(self.root)

    def tearDown(self) -> None:
        self.provider.close()
        self.temp.cleanup()

    def test_two_bounded_responses_probes_settle_without_persisting_secret(self) -> None:
        receipt = run_provider_probes(
            self.config,
            self.provider.secret,
            output_root=self.root / "probe",
            _transport=_UrllibTransport(
                endpoint_override=self.provider.base + "/responses"
            ),
        )
        self.assertEqual(receipt["logical_request_count"], 2)
        self.assertEqual(receipt["upstream_attempt_count"], 2)
        self.assertEqual(receipt["reserved_usd"], "0.000000")
        self.assertEqual([item["terminal"] for item in receipt["responses"]], [True, True])
        self.assertEqual([item["role"] for item in receipt["responses"]], ["main", "guardian"])
        self.assertIsNone(receipt["actual_usd"])
        self.assertNotIn("provider.example", json.dumps(receipt))
        self.assertEqual(len(self.provider.requests), 2)
        self.assertTrue(all(
            item["authorization"] == f"Bearer {self.provider.secret}"
            for item in self.provider.requests
        ))
        for index, item in enumerate(self.provider.requests):
            self.assertEqual(item["role"], ("main", "guardian")[index])
            self.assertEqual(item["user_agent"], PROBE_USER_AGENT)
            self.assertEqual(item["originator"], "codex_cli_rs")
            body = item["body"]
            self.assertEqual(body["model"], ("gpt-test-main", "gpt-test-guardian")[index])
            self.assertEqual(body["max_output_tokens"], 64)
            self.assertEqual(body["reasoning"], {"effort": "low"})
        self.assertNotIn("text", self.provider.requests[0]["body"])
        self.assertEqual(
            self.provider.requests[1]["body"]["text"]["format"]["name"],
            "guardian_decision",
        )
        for path in (self.root / "probe").iterdir():
            if path.is_file():
                self.assertNotIn(self.provider.secret.encode(), path.read_bytes())

    def test_models_and_guardian_effort_use_the_same_configured_provider_path(self) -> None:
        config = _paid_eval_config(
            self.root,
            main_model="gpt-configured-terra",
            guardian_model="gpt-configured-sol",
            guardian_effort="medium",
        )

        receipt = run_provider_probes(
            config,
            self.provider.secret,
            output_root=self.root / "terra-probe",
            _transport=_UrllibTransport(
                endpoint_override=self.provider.base + "/responses"
            ),
        )

        self.assertEqual(receipt["main_model"], "gpt-configured-terra")
        self.assertEqual(receipt["guardian_model"], "gpt-configured-sol")
        self.assertEqual(
            [item["body"]["model"] for item in self.provider.requests],
            ["gpt-configured-terra", "gpt-configured-sol"],
        )
        self.assertEqual(
            [item["body"]["reasoning"]["effort"] for item in self.provider.requests],
            ["low", "medium"],
        )

    def test_models_status_probe_uses_codex_user_agent_and_discards_body(self) -> None:
        status = probe_models_status(
            "https://provider.example/v1",
            self.provider.secret,
            _endpoint_override=self.provider.base + "/models",
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.provider.requests, [{
            "method": "GET",
            "authorization": f"Bearer {self.provider.secret}",
            "user_agent": PROBE_USER_AGENT,
            "originator": "codex_cli_rs",
        }])

    def test_failure_writes_profile_bound_receipt(self) -> None:
        self.provider.guardian_failure = True
        output = self.root / "failed-probe"

        with self.assertRaises(ProviderProbeError):
            run_provider_probes(
                self.config,
                self.provider.secret,
                output_root=output,
                _transport=_UrllibTransport(
                    endpoint_override=self.provider.base + "/responses"
                ),
            )

        receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(len(receipt["provider_profile_sha256"]), 64)
        self.assertEqual(receipt["logical_request_count"], 2)
        self.assertEqual(receipt["upstream_attempt_count"], 6)
        guardian = receipt["settlements"]["plan013-guardian"]
        self.assertEqual(guardian["attempt_count"], 5)
        self.assertEqual(guardian["settlement_kind"], "operator_confirmed_unbilled")

    def test_existing_crashed_reservation_is_reconciled_without_retry(self) -> None:
        output = self.root / "crashed-probe"
        output.mkdir()
        (output / "profile.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "batch_id": PROBE_BATCH_ID,
                    "run_id": PROBE_RUN_ID,
                    "provider_profile_sha256": "a" * 64,
                    "provider_endpoint_sha256": "b" * 64,
                    "main_model": "gpt-test-main",
                    "guardian_model": "gpt-test-guardian",
                    "guardian_effort": "low",
                    "total_cap_usd": format(PROBE_TOTAL_CAP_USD, "f"),
                }
            ),
            encoding="utf-8",
        )
        ledger_path = output / "budget.json"
        with PersistentBudgetLedger(
            ledger_path,
            batch_id=PROBE_BATCH_ID,
            total_cap_usd=PROBE_TOTAL_CAP_USD,
            max_runs=1,
            default_run_cap_usd="5",
        ) as ledger:
            ledger.ensure_run(PROBE_RUN_ID)
            ledger.reserve(PROBE_RUN_ID, "plan013-main")
            ledger.begin_attempt(PROBE_RUN_ID, "plan013-main", max_attempts=5)

        with self.assertRaisesRegex(ProviderProbeError, "reconciled without retry"):
            run_provider_probes(
                self.config,
                self.provider.secret,
                output_root=output,
                _transport=_UrllibTransport(
                    endpoint_override=self.provider.base + "/responses"
                ),
            )

        receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "reconciled_without_retry")
        request = receipt["settlements"]["plan013-main"]
        self.assertEqual(request["settlement_kind"], "conservative_reservation")
        self.assertEqual(self.provider.requests, [])

    def test_existing_stale_receipt_is_refreshed_after_ledger_recovery(self) -> None:
        output = self.root / "stale-receipt-probe"
        output.mkdir()
        profile = {
            "schema_version": 1,
            "batch_id": PROBE_BATCH_ID,
            "run_id": PROBE_RUN_ID,
            "provider_profile_sha256": "a" * 64,
            "provider_endpoint_sha256": "b" * 64,
            "main_model": "gpt-test-main",
            "guardian_model": "gpt-test-guardian",
            "guardian_effort": "low",
            "total_cap_usd": format(PROBE_TOTAL_CAP_USD, "f"),
        }
        (output / "profile.json").write_text(
            json.dumps(profile), encoding="utf-8"
        )
        ledger_path = output / "budget.json"
        with PersistentBudgetLedger(
            ledger_path,
            batch_id=PROBE_BATCH_ID,
            total_cap_usd=PROBE_TOTAL_CAP_USD,
            max_runs=1,
            default_run_cap_usd="5",
        ) as ledger:
            ledger.ensure_run(PROBE_RUN_ID)
            ledger.reserve(PROBE_RUN_ID, "plan013-main")
            ledger.begin_attempt(PROBE_RUN_ID, "plan013-main", max_attempts=5)
            stale_snapshot = ledger.snapshot()
        (output / "receipt.json").write_text(
            json.dumps(
                {
                    **profile,
                    "schema_version": 2,
                    "status": "failed",
                    "logical_request_count": 1,
                    "upstream_attempt_count": 1,
                    "responses": [],
                    "settlements": {
                        "plan013-main": {
                            "status": "reserved",
                            "charged_usd": None,
                            "usage_valid": None,
                            "attempt_count": 1,
                            "settlement_kind": None,
                        }
                    },
                    "estimated_spent_usd": stale_snapshot["spent_usd"],
                    "actual_usd": None,
                    "reserved_usd": stale_snapshot["reserved_usd"],
                    "failure_reason": "provider probe failed",
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ProviderProbeError, "reconciled without retry"):
            run_provider_probes(
                self.config,
                self.provider.secret,
                output_root=output,
                _transport=_UrllibTransport(
                    endpoint_override=self.provider.base + "/responses"
                ),
            )

        receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "reconciled_without_retry")
        self.assertEqual(
            receipt["failure_reason"],
            "previous_receipt_updated_after_ledger_recovery",
        )
        self.assertEqual(receipt["reserved_usd"], "0.000000")
        self.assertEqual(receipt["estimated_spent_usd"], "5.000000")
        self.assertEqual(
            receipt["settlements"]["plan013-main"]["settlement_kind"],
            "conservative_reservation",
        )
        self.assertEqual(self.provider.requests, [])

if __name__ == "__main__":
    unittest.main()
