from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from decimal import Decimal
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.api_budget_proxy import (  # noqa: E402
    BATCH_CAP_USD,
    GUARDIAN_OUTPUT_SCHEMA,
    MAX_REQUEST_RESERVATION_USD,
    UPSTREAM_TIMEOUT_SECONDS,
    ApiBudgetProxyError,
    BudgetStopped,
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    Usage,
    _UrllibTransport,
    _validated_lite_header,
    _validated_originator,
    _validated_user_agent,
    canonical_request_sha256,
    canonical_guardian_request_sha256,
    completed_run_accounting,
    load_validated_budget_ledger_state,
    milestone_metadata_ready,
    price_usage,
)
from rondo_eval.contracts import ModelPricing  # noqa: E402


MAIN_PRICING = ModelPricing(
    model_id="profile-main-model",
    input_usd_per_million=Decimal("5.00"),
    cached_input_usd_per_million=Decimal("0.50"),
    output_usd_per_million=Decimal("30.00"),
    long_context_threshold_tokens=272_000,
    long_context_input_multiplier=Decimal("2"),
    long_context_output_multiplier=Decimal("1.5"),
    cache_write_input_multiplier=Decimal("1.25"),
    price_snapshot_date="2026-08-10",
    price_source_url="https://developers.openai.com/api/docs/models/gpt-5.6-sol",
)
GUARDIAN_PRICING = ModelPricing(
    model_id="profile-guardian-model",
    input_usd_per_million=Decimal("0.20"),
    cached_input_usd_per_million=Decimal("0.02"),
    output_usd_per_million=Decimal("1.20"),
    long_context_threshold_tokens=272_000,
    long_context_input_multiplier=Decimal("2"),
    long_context_output_multiplier=Decimal("1.5"),
    cache_write_input_multiplier=Decimal("1.25"),
    price_snapshot_date="2026-08-10",
    price_source_url="https://developers.openai.com/api/docs/models/gpt-5.6-luna",
)
MAIN_MAX_USAGE_COST = price_usage(
    Usage(1_050_000, 0, 1_050_000, 128_000), pricing=MAIN_PRICING
)
GUARDIAN_MAX_USAGE_COST = price_usage(
    Usage(1_050_000, 0, 1_050_000, 128_000), pricing=GUARDIAN_PRICING
)


class _FakeUpstream:
    def __init__(self) -> None:
        self.mode = "json"
        self.modes: list[str] = []
        self.redirect_hits = 0
        self.requests: list[dict[str, object]] = []
        self.sse_terminal_sent = threading.Event()
        self.json_terminal_sent = threading.Event()
        self.release_sse = threading.Event()
        self.hang_started = threading.Event()
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802
                owner.redirect_hits += 1
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers["Content-Length"])
                body = self.rfile.read(length)
                with owner._lock:
                    owner.requests.append(
                        {
                            "path": self.path,
                            "authorization": self.headers.get("Authorization"),
                            "lite": self.headers.get(
                                "x-openai-internal-codex-responses-lite"
                            ),
                            "role": self.headers.get("X-RONDO-Eval-Role"),
                            "user_agent": self.headers.get("User-Agent"),
                            "originator": self.headers.get("originator"),
                            "body": body,
                        }
                    )
                    mode = owner.modes.pop(0) if owner.modes else owner.mode
                if mode == "disconnect":
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                if mode == "hang_before_headers":
                    owner.hang_started.set()
                    owner.release_sse.wait(timeout=5)
                    return
                if mode == "redirect":
                    self.send_response(302)
                    self.send_header("Location", owner.endpoint + "/redirect-target")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if mode in {
                    "unbilled_503",
                    "unbilled_503_with_usage",
                    "unbilled_503_with_terminal",
                    "malformed_503",
                }:
                    if mode == "malformed_503":
                        encoded = b'{"error":'
                    else:
                        error: dict[str, object] = {
                            "code": "gateway_overloaded",
                            "message": "upstream-error-sentinel-must-not-persist",
                        }
                        if mode == "unbilled_503_with_usage":
                            error["usage"] = {"input_tokens": 1, "output_tokens": 0}
                        if mode == "unbilled_503_with_terminal":
                            error["response"] = {"status": "completed"}
                        encoded = json.dumps({"error": error}).encode()
                    self.send_response(503)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                if mode in {"missing_usage", "invalid_usage"}:
                    response: dict[str, object] = {"id": "fake-response", "output": []}
                    if mode == "invalid_usage":
                        response["usage"] = {
                            "input_tokens": 1_050_001,
                            "output_tokens": 1,
                        }
                    encoded = json.dumps(response).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Authorization", "must-not-be-relayed")
                    self.send_header("Content-Length", str(len(encoded)))
                    self.end_headers()
                    self.wfile.write(encoded)
                    return
                if mode == "sse_incomplete":
                    encoded = b"event: response.output_text.delta\ndata: {\"delta\":\"partial\"}\n\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(encoded)
                    self.wfile.flush()
                    self.close_connection = True
                    return
                if mode in {"sse_terminal_error", "sse_terminal_failed"}:
                    if mode == "sse_terminal_error":
                        event_name = "error"
                        response = {
                            "type": "error",
                            "error": {
                                "code": "provider_stream_error",
                                "message": "sensitive-upstream-message-must-not-persist",
                            },
                        }
                    else:
                        event_name = "response.failed"
                        response = {
                            "type": "response.failed",
                            "response": {
                                "status": "failed",
                                "error": {
                                    "code": "model_failed",
                                    "message": "another-message-must-not-persist",
                                },
                            },
                        }
                    encoded = f"event: {event_name}\n".encode()
                    encoded += b"data: " + json.dumps(response).encode()
                    encoded += b"\n\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(encoded)
                    self.wfile.flush()
                    self.close_connection = True
                    return
                if mode in {"sse", "sse_hold_open"}:
                    response = {
                        "type": "response.completed",
                        "response": {
                            "id": "fake-response",
                            "usage": {
                                "input_tokens": 2000,
                                "input_tokens_details": {"cached_tokens": 1000},
                                "output_tokens": 100,
                            },
                        },
                    }
                    encoded = b"event: response.completed\n" + b"data: " + json.dumps(response).encode()
                    encoded += b"\n\n"
                    if mode == "sse":
                        encoded += b"data: [DONE]\n\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(encoded[:23])
                    self.wfile.flush()
                    self.wfile.write(encoded[23:])
                    self.wfile.flush()
                    owner.sse_terminal_sent.set()
                    if mode == "sse_hold_open":
                        owner.release_sse.wait(timeout=5)
                    self.close_connection = True
                    return
                response = {
                    "id": "fake-response",
                    "status": "completed",
                    "output": [],
                    "usage": {
                        "input_tokens": 1000,
                        "input_tokens_details": {"cached_tokens": 100},
                        "output_tokens": 50,
                    },
                }
                encoded = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Authorization", "must-not-be-relayed")
                if mode != "json_hold_open":
                    self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                self.wfile.flush()
                if mode == "json_hold_open":
                    owner.json_terminal_sent.set()
                    owner.release_sse.wait(timeout=5)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}/v1/responses"

    def close(self) -> None:
        self.release_sse.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


class ApiBudgetProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.secret = "sk-test-never-persist-this-value"
        self.upstream = _FakeUpstream()
        self.ledger = PersistentBudgetLedger(
            self.root / "budget.json",
            batch_id="p1-batch",
            total_cap_usd="80",
            default_run_cap_usd="40",
        )
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="benchmark-r1",
            metadata_path=self.root / "metadata.json",
            **self._profile_kwargs(),
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()

    def tearDown(self) -> None:
        self.proxy.close()
        self.ledger.close()
        self.upstream.close()
        self.temp.cleanup()

    @staticmethod
    def _profile_kwargs(**overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "main_model": MAIN_PRICING.model_id,
            "main_effort": "low",
            "main_pricing": MAIN_PRICING,
            "guardian_model": GUARDIAN_PRICING.model_id,
            "guardian_pricing": GUARDIAN_PRICING,
            "guardian_effort": "low",
            "max_attempts": 5,
            "retry_backoff_seconds": 0.0,
            "unbilled_retry_statuses": (503,),
        }
        values.update(overrides)
        return values

    def _post(
        self,
        body: dict[str, object],
        *,
        role: str | None = "main",
        request_id: str = "request-1",
        extra_headers: dict[str, str] | None = None,
        path: str = "/responses",
        authenticate: bool = True,
        proxy: LoopbackResponsesProxy | None = None,
    ) -> tuple[int, bytes, object]:
        active_proxy = proxy or self.proxy
        encoded = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "X-RONDO-Eval-Request-Id": request_id,
            "User-Agent": "codex_cli_rs/0.147.0 (proxy-test)",
            "originator": "codex_cli_rs",
        }
        if authenticate:
            headers["Authorization"] = f"Bearer {active_proxy.downstream_api_key}"
        if role is not None:
            headers["X-RONDO-Eval-Role"] = role
        if extra_headers:
            headers.update(extra_headers)
        request = Request(
            active_proxy.base_url + path,
            data=encoded,
            headers=headers,
            method="POST",
        )
        try:
            response = urlopen(request, timeout=10)
        except HTTPError as error:
            return error.code, error.read(), error.headers
        with response:
            return response.status, response.read(), response.headers

    def test_any_credential_free_https_compatible_base_url_is_accepted(self) -> None:
        self.assertEqual(
            self.proxy.upstream_endpoint, "https://provider.example/v1/responses"
        )
        for number, (base_url, endpoint) in enumerate(
            (
                ("https://api.example.com/v1", "https://api.example.com/v1/responses"),
                (
                    "https://gateway.example.net/openai/v1/",
                    "https://gateway.example.net/openai/v1/responses",
                ),
                ("https://[::1]:8443/v1", "https://[::1]:8443/v1/responses"),
            )
        ):
            with self.subTest(base_url=base_url):
                proxy = LoopbackResponsesProxy(
                    upstream_base_url=base_url,
                    api_key=self.secret,
                    ledger=self.ledger,
                    run_id=f"valid-upstream-{number}",
                    metadata_path=self.root / f"valid-upstream-{number}.json",
                    **self._profile_kwargs(),
                    _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
                )
                self.assertEqual(proxy.upstream_endpoint, endpoint)

    def test_transport_timeout_is_bounded_independently_from_agent_timeout(self) -> None:
        self.assertEqual(UPSTREAM_TIMEOUT_SECONDS, 90.0)
        proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="extended-timeout",
            metadata_path=self.root / "extended-timeout.json",
            **self._profile_kwargs(),
            timeout_seconds=180.0,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        )
        self.assertEqual(proxy._timeout, 180.0)
        with self.assertRaisesRegex(ApiBudgetProxyError, "180 second"):
            LoopbackResponsesProxy(
                upstream_base_url="https://provider.example/v1",
                api_key=self.secret,
                ledger=self.ledger,
                run_id="overlong-timeout",
                metadata_path=self.root / "overlong-timeout.json",
                **self._profile_kwargs(),
                timeout_seconds=900.0,
                _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
            )

    def test_short_probe_can_reserve_one_dollar_per_request(self) -> None:
        short_proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="short-probe",
            metadata_path=self.root / "short-probe.json",
            **self._profile_kwargs(),
            request_reservation_usd="1",
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()
        self.upstream.mode = "disconnect"
        try:
            status, _body, _headers = self._post(
                self._body(),
                request_id="short-request",
                proxy=short_proxy,
            )
        finally:
            short_proxy.close()
        self.assertEqual(status, 502)
        request = self.ledger.snapshot()["runs"]["short-probe"]["requests"][
            "short-request"
        ]
        self.assertEqual(request["reserved_usd"], "1.000000")
        self.assertEqual(request["charged_usd"], "1.000000")

    def test_main_admission_reserves_capacity_for_concurrent_guardian(self) -> None:
        limited_ledger = PersistentBudgetLedger(
            self.root / "guardian-headroom-budget.json",
            batch_id="guardian-headroom",
            total_cap_usd="1.5",
            default_run_cap_usd="5",
        )
        limited_proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=limited_ledger,
            run_id="guardian-headroom-run",
            metadata_path=self.root / "guardian-headroom-metadata.json",
            **self._profile_kwargs(),
            request_reservation_usd="1",
            max_guardian_logical_requests=1,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()
        forwarded_before = len(self.upstream.requests)
        try:
            status, _body, _headers = self._post(
                self._body(),
                request_id="main-without-guardian-headroom",
                proxy=limited_proxy,
            )
        finally:
            limited_proxy.close()
        self.assertEqual(status, 429)
        self.assertEqual(len(self.upstream.requests), forwarded_before)
        run = limited_ledger.snapshot()["runs"]["guardian-headroom-run"]
        self.assertTrue(run["stopped"])
        self.assertEqual(run["stop_reason"], "budget_capacity_exhausted")
        self.assertEqual(run["requests"], {})
        limited_ledger.close()

    def test_reserved_main_headroom_allows_concurrent_guardian_claim(self) -> None:
        ledger = PersistentBudgetLedger(
            self.root / "guardian-concurrent-budget.json",
            batch_id="guardian-concurrent",
            total_cap_usd="2",
            default_run_cap_usd="5",
        )
        proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=ledger,
            run_id="guardian-concurrent-run",
            metadata_path=self.root / "guardian-concurrent-metadata.json",
            **self._profile_kwargs(),
            request_reservation_usd="1",
            max_guardian_logical_requests=1,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        )
        proxy._claim_and_reserve_logical_request("main", "a" * 64, "main")
        proxy._claim_and_reserve_logical_request("guardian", "b" * 64, "guardian")
        requests = ledger.snapshot()["runs"]["guardian-concurrent-run"]["requests"]
        self.assertEqual(set(requests), {"main", "guardian"})
        self.assertEqual(
            sum(Decimal(item["reserved_usd"]) for item in requests.values()),
            Decimal("2.000000"),
        )
        proxy.close()
        ledger.close()

    def test_invalid_request_reservations_are_rejected(self) -> None:
        for number, reservation in enumerate(("0", "40.000001", "nan", True)):
            with self.subTest(reservation=reservation), self.assertRaisesRegex(
                ApiBudgetProxyError, "request reservation"
            ):
                LoopbackResponsesProxy(
                    upstream_base_url="https://provider.example/v1",
                    api_key=self.secret,
                    ledger=self.ledger,
                    run_id=f"invalid-reservation-{number}",
                    metadata_path=self.root / f"invalid-reservation-{number}.json",
                    **self._profile_kwargs(),
                    request_reservation_usd=reservation,
                    _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
                )

    def test_guardian_logical_request_limit_is_bounded(self) -> None:
        for number, limit in enumerate((True, False, 0, 4, -1)):
            with self.subTest(limit=limit), self.assertRaisesRegex(
                ApiBudgetProxyError, "between one and three"
            ):
                LoopbackResponsesProxy(
                    upstream_base_url="https://provider.example/v1",
                    api_key=self.secret,
                    ledger=self.ledger,
                    run_id=f"invalid-guardian-limit-{number}",
                    metadata_path=self.root / f"invalid-guardian-limit-{number}.json",
                    **self._profile_kwargs(),
                    max_guardian_logical_requests=limit,
                    _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
                )

    def test_invalid_compatible_base_urls_are_rejected_before_registration(self) -> None:
        for number, base_url in enumerate(
            (
                "",
                "http://api.example.com/v1",
                "https://user:secret@api.example.com/v1",
                "https://api.example.com/v1?query=1",
                "https://api.example.com/v1#fragment",
                " https://api.example.com/v1",
                "https://api.example.com/v1\\other",
                "https://api.example.com:invalid/v1",
            )
        ):
            with self.subTest(base_url=base_url), self.assertRaises(ApiBudgetProxyError):
                LoopbackResponsesProxy(
                    upstream_base_url=base_url,
                    api_key=self.secret,
                    ledger=self.ledger,
                    run_id=f"invalid-upstream-{number}",
                    metadata_path=self.root / f"invalid-upstream-{number}.json",
                    **self._profile_kwargs(),
                    _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
                )

    def test_direct_proxy_boundary_requires_sorted_unique_retry_statuses(self) -> None:
        for number, statuses in enumerate(((503, 429), (503, 503), (399,), (600,))):
            with self.subTest(statuses=statuses), self.assertRaises(ApiBudgetProxyError):
                LoopbackResponsesProxy(
                    upstream_base_url="https://provider.example/v1",
                    api_key=self.secret,
                    ledger=self.ledger,
                    run_id=f"invalid-statuses-{number}",
                    metadata_path=self.root / f"invalid-statuses-{number}.json",
                    **self._profile_kwargs(unbilled_retry_statuses=statuses),
                    _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
                )

    def test_upstream_redirect_is_not_followed(self) -> None:
        self.upstream.mode = "redirect"
        status, _body, _headers = self._post(self._body(), request_id="redirect-1")
        self.assertEqual(status, 302)
        self.assertEqual(self.upstream.redirect_hits, 0)

    @staticmethod
    def _body(
        *,
        stream: bool = False,
        effort: str | None = "low",
        guardian: bool = False,
        prompt: str = "secret prompt is never recorded",
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": GUARDIAN_PRICING.model_id if guardian else MAIN_PRICING.model_id,
            "input": [{"role": "user", "content": prompt}],
            "stream": stream,
            "tools": [{"type": "function", "name": "local_tool"}],
        }
        if effort is not None:
            body["reasoning"] = {"effort": effort}
        if guardian:
            body["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "codex_output_schema",
                    "strict": True,
                    "schema": GUARDIAN_OUTPUT_SCHEMA,
                }
            }
        return body

    def test_json_is_forwarded_and_only_redacted_metadata_is_saved(self) -> None:
        self.assertNotEqual(self.proxy.downstream_api_key, self.secret)
        self.assertRegex(
            self.proxy.docker_base_url,
            r"^http://host[.]docker[.]internal:[0-9]+/v1$",
        )
        status, response_body, headers = self._post(self._body(), role="main")
        self.assertEqual(status, 200, response_body)
        self.assertEqual(json.loads(response_body)["id"], "fake-response")
        self.assertIsNone(headers.get("Authorization"))
        self.assertEqual(len(self.upstream.requests), 1)
        self.assertEqual(
            self.upstream.requests[0]["authorization"], f"Bearer {self.secret}"
        )
        self.assertIsNone(self.upstream.requests[0]["role"])
        self.assertEqual(
            self.upstream.requests[0]["user_agent"],
            "codex_cli_rs/0.147.0 (proxy-test)",
        )
        self.assertEqual(self.upstream.requests[0]["originator"], "codex_cli_rs")
        metadata_bytes = (self.root / "metadata.json").read_bytes()
        ledger_bytes = (self.root / "budget.json").read_bytes()
        self.assertNotIn(self.secret.encode(), metadata_bytes)
        self.assertNotIn(self.secret.encode(), ledger_bytes)
        self.assertNotIn(self.proxy.downstream_api_key.encode(), metadata_bytes)
        self.assertNotIn(self.proxy.downstream_api_key.encode(), ledger_bytes)
        self.assertNotIn(b"secret prompt", metadata_bytes)
        observation = json.loads(metadata_bytes)["requests"][0]
        self.assertEqual(observation["role"], "main")
        self.assertEqual(observation["role_provenance"], "declared")
        self.assertEqual(observation["declared_role"], "main")
        self.assertEqual(observation["inferred_role"], "main")
        self.assertEqual(observation["model"], MAIN_PRICING.model_id)
        self.assertEqual(observation["attempt_count"], 1)
        self.assertEqual(observation["settlement_kind"], "usage_priced")
        self.assertEqual(observation["shape"]["input_items"], 1)
        self.assertEqual(len(observation["body_sha256"]), 64)
        self.assertEqual(
            observation["canonical_body_sha256"],
            canonical_request_sha256(self._body()),
        )
        self.assertEqual(
            canonical_request_sha256({"stream": False, "model": "same"}),
            canonical_request_sha256({"model": "same", "stream": False}),
        )
        self.assertTrue(observation["contract_match"])
        self.assertTrue(observation["usage_valid"])
        self.assertTrue(milestone_metadata_ready(self.root / "metadata.json"))
        invalid_metadata = json.loads(metadata_bytes)
        invalid_metadata["requests"][0]["canonical_body_sha256"] = "not-a-digest"
        invalid_metadata_path = self.root / "invalid-metadata.json"
        invalid_metadata_path.write_text(json.dumps(invalid_metadata), encoding="utf-8")
        self.assertFalse(milestone_metadata_ready(invalid_metadata_path))
        snapshot = self.ledger.snapshot()
        request = snapshot["runs"]["benchmark-r1"]["requests"]["request-1"]
        self.assertEqual(request["reserved_usd"], format(MAIN_MAX_USAGE_COST, "f"))
        self.assertEqual(
            completed_run_accounting(snapshot, "benchmark-r1"),
            {
                "stopped": False,
                "stop_reason": None,
                "reserved_usd": "0.000000",
                "spent_usd": format(
                    price_usage(Usage(1000, 100, 0, 50), pricing=MAIN_PRICING), "f"
                ),
                "request_count": 1,
                "settled_request_count": 1,
                "usage_valid_request_count": 1,
            },
        )
        over_cap = json.loads(json.dumps(snapshot))
        over_cap["runs"]["benchmark-r1"]["cap_usd"] = "0.000001"
        with self.assertRaisesRegex(ApiBudgetProxyError, "exceeds its cap"):
            completed_run_accounting(over_cap, "benchmark-r1")
        snapshot["runs"]["benchmark-r1"]["stopped"] = True
        snapshot["runs"]["benchmark-r1"]["stop_reason"] = "proxy_closing"
        with self.assertRaisesRegex(ApiBudgetProxyError, "must not be stopped"):
            completed_run_accounting(snapshot, "benchmark-r1")
        self.assertEqual(os.stat(self.root / "metadata.json").st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.root / "budget.json").st_mode & 0o777, 0o600)

    def test_guardian_digest_matches_e_final_normalization(self) -> None:
        body = self._body(guardian=True)
        body.update(
            {
                "store": False,
                "prompt_cache_key": "private-cache-key",
                "client_metadata": {"private": True},
            }
        )
        body["input"] = [
            {
                "id": "provider-id",
                "call_id": "original-call",
                "encrypted_function_args": "private",
                "internal_chat_message_metadata_passthrough": {
                    "turn_id": "original-turn"
                },
            },
            {"call_id": "original-call"},
        ]
        status, _response, _headers = self._post(body, role="guardian")
        self.assertEqual(status, 200)
        observation = json.loads((self.root / "metadata.json").read_bytes())["requests"][0]
        self.assertEqual(
            observation["canonical_body_sha256"],
            canonical_guardian_request_sha256(body),
        )
        normalized = dict(body)
        for field in ("client_metadata", "prompt_cache_key", "store", "stream"):
            normalized.pop(field, None)
        normalized["input"] = [
            {
                "call_id": "call_0",
                "internal_chat_message_metadata_passthrough": {"turn_id": "turn_0"},
            },
            {"call_id": "call_0"},
        ]
        self.assertEqual(
            observation["canonical_body_sha256"],
            canonical_request_sha256(normalized),
        )

    def test_downstream_bearer_is_required_and_is_not_forwarded(self) -> None:
        status, body, _headers = self._post(
            self._body(), request_id="no-auth", authenticate=False
        )
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")
        status, body, _headers = self._post(
            self._body(),
            request_id="wrong-auth",
            extra_headers={"Authorization": "Bearer wrong-loopback-token"},
        )
        self.assertEqual(status, 401)
        self.assertNotIn(self.secret.encode(), body)
        self.assertNotIn(self.proxy.downstream_api_key.encode(), body)
        self.assertEqual(self.upstream.requests, [])

    def test_lite_header_is_forwarded_only_for_exact_true(self) -> None:
        status, _body, _headers = self._post(
            self._body(),
            request_id="lite-valid",
            extra_headers={"x-openai-internal-codex-responses-lite": "true"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.upstream.requests[0]["lite"], "true")

    def test_other_lite_header_values_are_rejected_before_upstream(self) -> None:
        for number, value in enumerate(("True", "false", "1")):
            with self.subTest(value=value):
                status, body, _headers = self._post(
                    self._body(),
                    request_id=f"lite-invalid-{number}",
                    extra_headers={"x-openai-internal-codex-responses-lite": value},
                )
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body)["error"]["code"], "invalid_lite_header")
        self.assertEqual(self.upstream.requests, [])

    def test_lite_header_validator_rejects_non_exact_parsed_values(self) -> None:
        class Headers:
            def __init__(self, values: list[str]):
                self.values = values

            def get_all(self, _name: str, _default: list[str]) -> list[str]:
                return self.values

        for values in ([" true"], ["true "], ["true", "true"]):
            with self.subTest(values=values), self.assertRaises(ApiBudgetProxyError):
                _validated_lite_header(Headers(values))

    def test_user_agent_is_forwarded_once_and_invalid_values_are_rejected(self) -> None:
        class Headers:
            def __init__(self, values: list[str]):
                self.values = values

            def get_all(self, _name: str, _default: list[str]) -> list[str]:
                return self.values

        self.assertEqual(
            _validated_user_agent(Headers(["codex_cli_rs/0.147.0 (test)"])),
            "codex_cli_rs/0.147.0 (test)",
        )
        for values in ([], ["one", "two"], ["bad\nagent"], ["x" * 513]):
            with self.subTest(values=values), self.assertRaises(ApiBudgetProxyError):
                _validated_user_agent(Headers(values))

    def test_single_printable_codex_originator_is_forwarded(self) -> None:
        class Headers:
            def __init__(self, values: list[str]):
                self.values = values

            def get_all(self, _name: str, _default: list[str]) -> list[str]:
                return self.values

        self.assertIsNone(_validated_originator(Headers([])))
        self.assertEqual(_validated_originator(Headers(["codex_cli_rs"])), "codex_cli_rs")
        self.assertEqual(_validated_originator(Headers(["codex_exec"])), "codex_exec")
        for values in (
            ["codex_cli_rs", "codex_cli_rs"],
            ["bad\noriginator"],
            ["x" * 65],
        ):
            with self.subTest(values=values), self.assertRaises(ApiBudgetProxyError):
                _validated_originator(Headers(values))

    def test_sse_is_streamed_and_completed_usage_is_settled(self) -> None:
        self.upstream.mode = "sse"
        status, response_body, _headers = self._post(
            self._body(stream=True, effort="low", guardian=True),
            role="guardian",
            request_id="sse-1",
        )
        self.assertEqual(status, 200)
        self.assertIn(b"response.completed", response_body)
        observation = json.loads((self.root / "metadata.json").read_text())["requests"][0]
        self.assertEqual(observation["role"], "guardian")
        self.assertEqual(observation["reasoning_effort"], "low")
        self.assertTrue(observation["stream"])
        self.assertTrue(observation["usage_valid"])
        self.assertTrue(milestone_metadata_ready(self.root / "metadata.json"))

    def test_sse_completed_usage_settles_before_upstream_eof(self) -> None:
        self.upstream.mode = "sse_hold_open"
        result: list[tuple[int, bytes, object]] = []
        error: list[BaseException] = []

        def send() -> None:
            try:
                result.append(self._post(
                    self._body(stream=True, effort="low", guardian=True),
                    role="guardian",
                    request_id="sse-hold-open",
                ))
            except BaseException as exc:  # pragma: no cover - asserted below
                error.append(exc)

        thread = threading.Thread(target=send)
        thread.start()
        self.assertTrue(self.upstream.sse_terminal_sent.wait(timeout=2))
        thread.join(timeout=2)
        try:
            self.assertFalse(thread.is_alive(), "proxy waited for upstream EOF")
            self.assertEqual(error, [])
            self.assertEqual(result[0][0], 200)
            self.assertIn(b"response.completed", result[0][1])
            snapshot = self.ledger.snapshot()
            request = snapshot["runs"]["benchmark-r1"]["requests"]["sse-hold-open"]
            self.assertEqual(request["status"], "settled")
            self.assertTrue(request["usage_valid"])
            self.assertEqual(snapshot["reserved_usd"], "0.000000")
        finally:
            self.upstream.release_sse.set()
            thread.join(timeout=2)

    def test_sse_terminal_is_not_visible_until_reservation_is_settled(self) -> None:
        self.upstream.mode = "sse"
        settle_started = threading.Event()
        release_settle = threading.Event()
        terminal_visible = threading.Event()
        original_settle = self.ledger.settle

        def blocking_settle(*args: object, **kwargs: object):
            settle_started.set()
            if not release_settle.wait(timeout=2):
                raise AssertionError("test did not release budget settlement")
            return original_settle(*args, **kwargs)

        self.ledger.settle = blocking_settle  # type: ignore[method-assign]
        parsed_host_port = self.proxy.base_url.removeprefix("http://").removesuffix("/v1")
        host, port_text = parsed_host_port.rsplit(":", 1)
        connection = HTTPConnection(host, int(port_text), timeout=5)
        encoded = json.dumps(self._body(stream=True)).encode()
        connection.request(
            "POST",
            "/v1/responses",
            body=encoded,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(encoded)),
                "Authorization": f"Bearer {self.proxy.downstream_api_key}",
                "X-RONDO-Eval-Request-Id": "sse-settlement-order",
                "X-RONDO-Eval-Role": "main",
                "User-Agent": "codex_cli_rs/0.147.0 (proxy-test)",
                "originator": "codex_cli_rs",
            },
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 200)

        terminal_line: list[bytes] = []

        def read_terminal() -> None:
            terminal_line.append(response.readline())
            terminal_visible.set()

        reader = threading.Thread(target=read_terminal)
        reader.start()
        try:
            self.assertTrue(settle_started.wait(timeout=2))
            self.assertFalse(
                terminal_visible.wait(timeout=0.1),
                "response.completed became visible before budget settlement",
            )
            release_settle.set()
            self.assertTrue(terminal_visible.wait(timeout=2))
            self.assertEqual(terminal_line, [b"event: response.completed\n"])
            self.assertIn(b'"type": "response.completed"', response.readline())
            request = self.ledger.snapshot()["runs"]["benchmark-r1"]["requests"][
                "sse-settlement-order"
            ]
            self.assertEqual(request["status"], "settled")
            self.assertTrue(request["usage_valid"])
        finally:
            release_settle.set()
            reader.join(timeout=2)
            connection.close()
            self.ledger.settle = original_settle  # type: ignore[method-assign]

    def test_settled_main_terminal_allows_immediate_guardian_reservation(self) -> None:
        self.upstream.modes = ["sse", "json"]
        original_settle = self.ledger.settle

        def delayed_main_settle(*args: object, **kwargs: object):
            if len(args) >= 2 and args[1] == "main-before-guardian":
                # Widen the old write-before-settle race deterministically.
                threading.Event().wait(timeout=0.2)
            return original_settle(*args, **kwargs)

        self.ledger.settle = delayed_main_settle  # type: ignore[method-assign]
        parsed_host_port = self.proxy.base_url.removeprefix("http://").removesuffix("/v1")
        host, port_text = parsed_host_port.rsplit(":", 1)
        connection = HTTPConnection(host, int(port_text), timeout=5)
        encoded = json.dumps(self._body(stream=True)).encode()
        connection.request(
            "POST",
            "/v1/responses",
            body=encoded,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(encoded)),
                "Authorization": f"Bearer {self.proxy.downstream_api_key}",
                "X-RONDO-Eval-Request-Id": "main-before-guardian",
                "X-RONDO-Eval-Role": "main",
                "User-Agent": "codex_cli_rs/0.147.0 (proxy-test)",
                "originator": "codex_cli_rs",
            },
        )
        response = connection.getresponse()
        try:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.readline(), b"event: response.completed\n")
            self.assertIn(b'"type": "response.completed"', response.readline())
            self.assertEqual(response.readline(), b"\n")
            guardian_status, _body, _headers = self._post(
                self._body(effort="low", guardian=True),
                role="guardian",
                request_id="guardian-after-main",
            )
            self.assertEqual(guardian_status, 200)
            snapshot = self.ledger.snapshot()
            self.assertEqual(snapshot["reserved_usd"], "0.000000")
            self.assertEqual(
                list(snapshot["runs"]["benchmark-r1"]["requests"]),
                ["main-before-guardian", "guardian-after-main"],
            )
            observations = json.loads((self.root / "metadata.json").read_text())[
                "requests"
            ]
            self.assertEqual(
                [observation["role"] for observation in observations],
                ["main", "guardian"],
            )
        finally:
            connection.close()
            self.ledger.settle = original_settle  # type: ignore[method-assign]

    def test_nonstream_completed_usage_settles_before_upstream_eof(self) -> None:
        self.upstream.mode = "json_hold_open"
        result: list[tuple[int, bytes, object]] = []
        error: list[BaseException] = []

        def send() -> None:
            try:
                result.append(self._post(self._body(), request_id="json-hold-open"))
            except BaseException as exc:  # pragma: no cover - asserted below
                error.append(exc)

        thread = threading.Thread(target=send)
        thread.start()
        self.assertTrue(self.upstream.json_terminal_sent.wait(timeout=2))
        thread.join(timeout=2)
        try:
            self.assertFalse(thread.is_alive(), "proxy waited for upstream EOF")
            self.assertEqual(error, [])
            self.assertEqual(result[0][0], 200)
            self.assertEqual(json.loads(result[0][1])["status"], "completed")
            snapshot = self.ledger.snapshot()
            request = snapshot["runs"]["benchmark-r1"]["requests"]["json-hold-open"]
            self.assertEqual(request["status"], "settled")
            self.assertTrue(request["usage_valid"])
            self.assertEqual(snapshot["reserved_usd"], "0.000000")
        finally:
            self.upstream.release_sse.set()
            thread.join(timeout=2)

    def test_upstream_header_timeout_settles_reservation_and_stops_run(self) -> None:
        self.proxy.close()
        self.upstream.mode = "hang_before_headers"
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="timeout-run",
            metadata_path=self.root / "timeout-metadata.json",
            **self._profile_kwargs(),
            timeout_seconds=0.1,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()
        try:
            status, body, _headers = self._post(
                self._body(), request_id="timeout-request"
            )
        finally:
            self.upstream.release_sse.set()
        self.assertTrue(self.upstream.hang_started.is_set())
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["error"]["code"], "upstream_unavailable")
        snapshot = self.ledger.snapshot()
        run = snapshot["runs"]["timeout-run"]
        request = run["requests"]["timeout-request"]
        self.assertEqual(request["status"], "settled")
        self.assertFalse(request["usage_valid"])
        self.assertEqual(request["attempt_count"], 1)
        self.assertEqual(request["settlement_kind"], "conservative_reservation")
        self.assertEqual(request["charged_usd"], format(MAIN_MAX_USAGE_COST, "f"))
        self.assertTrue(run["stopped"])
        self.assertEqual(snapshot["reserved_usd"], "0.000000")
        observation = json.loads(
            (self.root / "timeout-metadata.json").read_text(encoding="utf-8")
        )["requests"][0]
        self.assertEqual(observation["upstream_status"], 0)

    def test_incomplete_sse_preserves_http_status_and_end_kind(self) -> None:
        self.upstream.mode = "sse_incomplete"
        status, _body, _headers = self._post(
            self._body(), request_id="sse-incomplete"
        )
        self.assertEqual(status, 200)
        observation = json.loads(
            (self.root / "metadata.json").read_text(encoding="utf-8")
        )["requests"][0]
        self.assertEqual(observation["upstream_status"], 200)
        self.assertEqual(observation["stream_end_kind"], "clean_eof")
        request = self.ledger.snapshot()["runs"]["benchmark-r1"]["requests"][
            "sse-incomplete"
        ]
        self.assertFalse(request["usage_valid"])
        self.assertEqual(request["settlement_kind"], "conservative_reservation")

    def test_terminal_error_records_only_bounded_protocol_facts(self) -> None:
        self.upstream.mode = "sse_terminal_error"

        status, _body, _headers = self._post(
            self._body(), request_id="sse-terminal-error"
        )

        self.assertEqual(status, 200)
        observation = json.loads(
            (self.root / "metadata.json").read_text(encoding="utf-8")
        )["requests"][0]
        self.assertEqual(observation["upstream_status"], 200)
        self.assertEqual(observation["stream_end_kind"], "terminal")
        self.assertEqual(observation["terminal_event_type"], "error")
        self.assertEqual(observation["terminal_error_code"], "provider_stream_error")
        self.assertNotIn("sensitive-upstream-message", json.dumps(observation))
        run = self.ledger.snapshot()["runs"]["benchmark-r1"]
        self.assertTrue(run["stopped"])
        self.assertEqual(run["stop_reason"], "upstream_terminal_error")
        request = run["requests"]["sse-terminal-error"]
        self.assertFalse(request["usage_valid"])
        self.assertEqual(request["settlement_kind"], "conservative_reservation")

    def test_terminal_failed_records_status_without_message(self) -> None:
        self.upstream.mode = "sse_terminal_failed"

        status, _body, _headers = self._post(
            self._body(), request_id="sse-terminal-failed"
        )

        self.assertEqual(status, 200)
        observation = json.loads(
            (self.root / "metadata.json").read_text(encoding="utf-8")
        )["requests"][0]
        self.assertEqual(observation["terminal_event_type"], "response.failed")
        self.assertEqual(observation["terminal_response_status"], "failed")
        self.assertEqual(observation["terminal_error_code"], "model_failed")
        self.assertNotIn("another-message", json.dumps(observation))
        run = self.ledger.snapshot()["runs"]["benchmark-r1"]
        self.assertEqual(run["stop_reason"], "upstream_terminal_failed")

    def test_missing_role_header_projects_declared_main_from_request_shape(self) -> None:
        status, _body, _headers = self._post(self._body(), role=None)
        self.assertEqual(status, 200)
        observation = json.loads((self.root / "metadata.json").read_text())["requests"][0]
        self.assertEqual(observation["role"], "main")
        self.assertEqual(observation["role_provenance"], "declared")
        self.assertEqual(observation["declared_role"], "main")
        self.assertEqual(observation["inferred_role"], "main")
        self.assertTrue(observation["contract_match"])
        self.assertIsNone(self.upstream.requests[0]["role"])
        self.assertTrue(milestone_metadata_ready(self.root / "metadata.json"))
        request = self.ledger.snapshot()["runs"]["benchmark-r1"]["requests"]["request-1"]
        self.assertEqual(request["reserved_usd"], format(MAIN_MAX_USAGE_COST, "f"))

    def test_missing_role_header_projects_declared_guardian_from_exact_schema(self) -> None:
        status, _body, _headers = self._post(
            self._body(effort="low", guardian=True),
            role=None,
        )
        self.assertEqual(status, 200)
        observation = json.loads((self.root / "metadata.json").read_text())["requests"][0]
        self.assertEqual(observation["role"], "guardian")
        self.assertEqual(observation["role_provenance"], "declared")
        self.assertEqual(observation["declared_role"], "guardian")
        self.assertEqual(observation["inferred_role"], "guardian")
        self.assertTrue(observation["contract_match"])
        self.assertIsNone(self.upstream.requests[0]["role"])
        self.assertTrue(milestone_metadata_ready(self.root / "metadata.json"))
        request = self.ledger.snapshot()["runs"]["benchmark-r1"]["requests"]["request-1"]
        self.assertEqual(
            request["reserved_usd"], format(GUARDIAN_MAX_USAGE_COST, "f")
        )

    def test_configured_non_low_guardian_effort_is_enforced(self) -> None:
        self.proxy.close()
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="high-effort-run",
            metadata_path=self.root / "high-effort-metadata.json",
            **self._profile_kwargs(guardian_effort="high"),
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()
        status, _body, _headers = self._post(
            self._body(effort="high", guardian=True),
            role="guardian",
            request_id="high-effort",
        )
        self.assertEqual(status, 200)
        observation = json.loads(
            (self.root / "high-effort-metadata.json").read_text(encoding="utf-8")
        )["requests"][0]
        self.assertEqual(observation["reasoning_effort"], "high")

    def test_configured_main_effort_is_enforced_before_reservation(self) -> None:
        self.proxy.close()
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="main-effort-run",
            metadata_path=self.root / "main-effort-metadata.json",
            **self._profile_kwargs(main_effort="medium"),
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()
        rejected, _body, _headers = self._post(
            self._body(effort="low"),
            request_id="wrong-main-effort",
        )
        accepted, _body, _headers = self._post(
            self._body(effort="medium"),
            request_id="matching-main-effort",
        )
        self.assertEqual(rejected, 400)
        self.assertEqual(accepted, 200)
        requests = self.ledger.snapshot()["runs"]["main-effort-run"]["requests"]
        self.assertNotIn("wrong-main-effort", requests)
        self.assertIn("matching-main-effort", requests)

    def test_guardian_contract_blocks_duplicate_charged_parse_replay_before_reserve(self) -> None:
        self.proxy.close()
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="single-guardian-run",
            metadata_path=self.root / "single-guardian-metadata.json",
            **self._profile_kwargs(),
            max_guardian_logical_requests=1,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()

        sequence = (
            (self._body(), "main", "main-before"),
            (
                self._body(effort="low", guardian=True),
                "guardian",
                "guardian-first",
            ),
            (self._body(), "main", "main-after"),
        )
        for body, role, request_id in sequence:
            status, _response, _headers = self._post(
                body,
                role=role,
                request_id=request_id,
            )
            self.assertEqual(status, 200)
        upstream_before_replay = len(self.upstream.requests)

        status, body, _headers = self._post(
            self._body(effort="low", guardian=True),
            role="guardian",
            request_id="guardian-charged-parse-replay",
        )

        self.assertEqual(status, 409)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "guardian_duplicate_logical_request_rejected",
        )
        self.assertEqual(len(self.upstream.requests), upstream_before_replay)
        metadata = json.loads(
            (self.root / "single-guardian-metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(metadata["requests"]), 3)
        run = self.ledger.snapshot()["runs"]["single-guardian-run"]
        self.assertEqual(
            set(run["requests"]),
            {"main-before", "guardian-first", "main-after"},
        )
        self.assertTrue(run["stopped"])
        self.assertEqual(
            run["stop_reason"],
            "guardian_duplicate_logical_request_rejected",
        )

    def test_failed_reservation_does_not_consume_guardian_body_or_counter(self) -> None:
        self.proxy.close()
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="guardian-reserve-retry-run",
            metadata_path=self.root / "guardian-reserve-retry-metadata.json",
            **self._profile_kwargs(),
            request_reservation_usd="1",
            max_guardian_logical_requests=1,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()
        original_reserve = self.ledger.reserve
        failed = False

        def fail_once(*args: object, **kwargs: object):
            nonlocal failed
            if not failed:
                failed = True
                raise BudgetStopped("injected reservation contention")
            return original_reserve(*args, **kwargs)

        self.ledger.reserve = fail_once  # type: ignore[method-assign]
        try:
            first, _body, _headers = self._post(
                self._body(effort="low", guardian=True),
                role="guardian",
                request_id="guardian-reserve-failed",
            )
            second, _body, _headers = self._post(
                self._body(effort="low", guardian=True),
                role="guardian",
                request_id="guardian-reserve-retry",
            )
        finally:
            self.ledger.reserve = original_reserve  # type: ignore[method-assign]

        self.assertEqual(first, 429)
        self.assertEqual(second, 200)
        self.assertEqual(len(self.upstream.requests), 1)
        run = self.ledger.snapshot()["runs"]["guardian-reserve-retry-run"]
        self.assertFalse(run["stopped"])
        self.assertEqual(set(run["requests"]), {"guardian-reserve-retry"})

    def test_two_distinct_guardian_reviews_are_allowed_but_a_third_is_bounded(self) -> None:
        self.proxy.close()
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="two-guardian-run",
            metadata_path=self.root / "two-guardian-metadata.json",
            **self._profile_kwargs(),
            max_guardian_logical_requests=2,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()

        for number in (1, 2):
            status, _body, _headers = self._post(
                self._body(
                    effort="low",
                    guardian=True,
                    prompt=f"distinct review {number}",
                ),
                role="guardian",
                request_id=f"guardian-{number}",
            )
            self.assertEqual(status, 200)
        upstream_before_limit = len(self.upstream.requests)

        status, body, _headers = self._post(
            self._body(effort="low", guardian=True, prompt="distinct review 3"),
            role="guardian",
            request_id="guardian-3",
        )

        self.assertEqual(status, 409)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "guardian_logical_request_limit_exceeded",
        )
        self.assertEqual(len(self.upstream.requests), upstream_before_limit)

    def test_single_guardian_contract_keeps_unbilled_attempts_inside_first_request(self) -> None:
        self.proxy.close()
        self.upstream.modes = ["unbilled_503", "json"]
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="single-guardian-unbilled-run",
            metadata_path=self.root / "single-guardian-unbilled-metadata.json",
            **self._profile_kwargs(),
            max_guardian_logical_requests=1,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()

        status, _body, _headers = self._post(
            self._body(effort="low", guardian=True),
            role="guardian",
            request_id="guardian-first-logical-request",
        )

        self.assertEqual(status, 200)
        self.assertEqual(len(self.upstream.requests), 2)
        request = self.ledger.snapshot()["runs"]["single-guardian-unbilled-run"][
            "requests"
        ]["guardian-first-logical-request"]
        self.assertEqual(request["attempt_count"], 2)
        self.assertEqual(request["settlement_kind"], "usage_priced")

    def test_short_canary_logical_request_cap_blocks_before_reserve_and_forward(self) -> None:
        self.proxy.close()
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="short-canary-run",
            metadata_path=self.root / "short-canary-metadata.json",
            **self._profile_kwargs(),
            max_guardian_logical_requests=1,
            max_logical_requests=2,
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()

        for request_id in ("canary-main-1", "canary-main-2"):
            status, _body, _headers = self._post(
                self._body(),
                role="main",
                request_id=request_id,
            )
            self.assertEqual(status, 200)
        upstream_before_limit = len(self.upstream.requests)

        status, body, _headers = self._post(
            self._body(),
            role="main",
            request_id="canary-main-over-limit",
        )

        self.assertEqual(status, 409)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "logical_request_limit_exceeded",
        )
        self.assertEqual(len(self.upstream.requests), upstream_before_limit)
        run = self.ledger.snapshot()["runs"]["short-canary-run"]
        self.assertEqual(set(run["requests"]), {"canary-main-1", "canary-main-2"})
        self.assertTrue(run["stopped"])
        self.assertEqual(run["stop_reason"], "logical_request_limit_exceeded")
        metadata = json.loads(
            (self.root / "short-canary-metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(len(metadata["requests"]), 2)

    def test_missing_usage_charges_reservation_stops_run_and_prevents_forward(self) -> None:
        self.upstream.mode = "missing_usage"
        status, _body, _headers = self._post(self._body(), request_id="missing-1")
        self.assertEqual(status, 200)
        run = self.ledger.snapshot()["runs"]["benchmark-r1"]
        self.assertTrue(run["stopped"])
        self.assertEqual(run["stop_reason"], "missing_or_invalid_usage")
        self.assertEqual(run["spent_usd"], format(MAIN_MAX_USAGE_COST, "f"))
        before = len(self.upstream.requests)
        status, body, _headers = self._post(self._body(), request_id="missing-2")
        self.assertEqual(status, 429)
        self.assertEqual(json.loads(body)["error"]["code"], "budget_stopped")
        self.assertEqual(len(self.upstream.requests), before)

    def test_invalid_usage_also_charges_reservation_and_stops_run(self) -> None:
        self.upstream.mode = "invalid_usage"
        status, _body, _headers = self._post(self._body(), request_id="invalid-usage-1")
        self.assertEqual(status, 200)
        run = self.ledger.snapshot()["runs"]["benchmark-r1"]
        self.assertTrue(run["stopped"])
        self.assertEqual(run["spent_usd"], format(MAIN_MAX_USAGE_COST, "f"))

    def test_retries_hosted_tools_wrong_guardian_and_non_responses_path_are_rejected(self) -> None:
        cases = [
            (
                self._body(),
                {"X-Stainless-Retry-Count": "1"},
                "main",
                "/responses",
                409,
            ),
            (
                {**self._body(), "tools": [{"type": "web_search"}]},
                {},
                "main",
                "/responses",
                400,
            ),
            (self._body(effort="medium", guardian=True), {}, "guardian", "/responses", 400),
            (self._body(guardian=True), {}, "main", "/responses", 400),
            (self._body(), {}, "main", "/not-responses", 404),
        ]
        for number, (body, headers, role, path, expected) in enumerate(cases):
            with self.subTest(expected=expected):
                status, _response, _response_headers = self._post(
                    body,
                    role=role,
                    request_id=f"rejected-{number}",
                    extra_headers=headers,
                    path=path,
                )
                self.assertEqual(status, expected)
        self.assertEqual(self.upstream.requests, [])

    def test_websocket_upgrade_is_rejected_before_forwarding(self) -> None:
        parsed_host_port = self.proxy.base_url.removeprefix("http://").removesuffix("/v1")
        host, port_text = parsed_host_port.rsplit(":", 1)
        connection = HTTPConnection(host, int(port_text), timeout=5)
        encoded = json.dumps(self._body()).encode()
        connection.request(
            "POST",
            "/v1/responses",
            body=encoded,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(encoded)),
                "Authorization": f"Bearer {self.proxy.downstream_api_key}",
                "Connection": "Upgrade",
                "Upgrade": "websocket",
            },
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.read())["error"]["code"], "websocket_disabled")
        connection.close()
        self.assertEqual(self.upstream.requests, [])

    def test_upstream_exception_is_stable_and_contains_no_secret(self) -> None:
        self.upstream.mode = "disconnect"
        status, body, _headers = self._post(self._body(), request_id="disconnect-1")
        self.assertEqual(status, 502)
        self.assertNotIn(self.secret.encode(), body)
        self.assertNotIn(self.secret.encode(), (self.root / "metadata.json").read_bytes())
        self.assertNotIn(self.secret.encode(), (self.root / "budget.json").read_bytes())

    def test_main_attempt_counts_one_through_five_share_one_reservation(self) -> None:
        for expected_attempts in range(1, 6):
            with self.subTest(expected_attempts=expected_attempts):
                self.upstream.modes = ["unbilled_503"] * (expected_attempts - 1) + ["json"]
                status, _body, _headers = self._post(
                    self._body(),
                    request_id=f"attempts-{expected_attempts}",
                )
                self.assertEqual(status, 200)
                request = self.ledger.snapshot()["runs"]["benchmark-r1"]["requests"][
                    f"attempts-{expected_attempts}"
                ]
                self.assertEqual(request["attempt_count"], expected_attempts)
                self.assertEqual(request["settlement_kind"], "usage_priced")
                self.assertTrue(request["usage_valid"])

    def test_guardian_canonical_unbilled_failure_is_retried_then_priced_once(self) -> None:
        self.upstream.modes = ["unbilled_503", "json"]
        status, _body, _headers = self._post(
            self._body(effort="low", guardian=True),
            role="guardian",
            request_id="guardian-retry",
        )
        self.assertEqual(status, 200)
        self.assertEqual([item["role"] for item in self.upstream.requests], [None, None])
        request = self.ledger.snapshot()["runs"]["benchmark-r1"]["requests"][
            "guardian-retry"
        ]
        self.assertEqual(request["attempt_count"], 2)
        self.assertEqual(request["charged_usd"], "0.000242")

    def test_five_confirmed_unbilled_attempts_stop_at_zero_and_block_followup(self) -> None:
        self.upstream.mode = "unbilled_503"
        status, body, _headers = self._post(self._body(), request_id="exhausted")
        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"]["code"], "unbilled_retry_exhausted")
        self.assertEqual(len(self.upstream.requests), 5)
        run = self.ledger.snapshot()["runs"]["benchmark-r1"]
        request = run["requests"]["exhausted"]
        self.assertEqual(request["attempt_count"], 5)
        self.assertEqual(request["charged_usd"], "0.000000")
        self.assertFalse(request["usage_valid"])
        self.assertEqual(request["settlement_kind"], "operator_confirmed_unbilled")
        self.assertEqual(run["stop_reason"], "operator_confirmed_unbilled_attempts_exhausted")
        metadata_bytes = (self.root / "metadata.json").read_bytes()
        ledger_bytes = (self.root / "budget.json").read_bytes()
        observation = json.loads(metadata_bytes)["requests"][0]
        self.assertEqual(observation["attempt_count"], 5)
        self.assertEqual(
            observation["settlement_kind"],
            "operator_confirmed_unbilled",
        )
        self.assertNotIn(b"upstream-error-sentinel-must-not-persist", metadata_bytes)
        self.assertNotIn(b"upstream-error-sentinel-must-not-persist", ledger_bytes)
        before = len(self.upstream.requests)
        status, _body, _headers = self._post(self._body(), request_id="after-exhausted")
        self.assertEqual(status, 429)
        self.assertEqual(len(self.upstream.requests), before)

    def test_configured_status_with_usage_is_unknown_and_never_retried(self) -> None:
        self.upstream.mode = "unbilled_503_with_usage"
        status, body, _headers = self._post(self._body(), request_id="ambiguous")
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["error"]["code"], "unclassified_upstream_failure")
        self.assertEqual(len(self.upstream.requests), 1)
        run = self.ledger.snapshot()["runs"]["benchmark-r1"]
        request = run["requests"]["ambiguous"]
        self.assertEqual(request["attempt_count"], 1)
        self.assertEqual(request["charged_usd"], format(MAIN_MAX_USAGE_COST, "f"))
        self.assertEqual(request["settlement_kind"], "conservative_reservation")
        self.assertEqual(run["stop_reason"], "unclassified_upstream_failure")

    def test_configured_status_with_terminal_evidence_is_never_retried(self) -> None:
        self.upstream.mode = "unbilled_503_with_terminal"
        status, body, _headers = self._post(
            self._body(), request_id="terminal-ambiguous"
        )
        self.assertEqual(status, 502)
        self.assertEqual(
            json.loads(body)["error"]["code"], "unclassified_upstream_failure"
        )
        self.assertEqual(len(self.upstream.requests), 1)
        request = self.ledger.snapshot()["runs"]["benchmark-r1"]["requests"][
            "terminal-ambiguous"
        ]
        self.assertEqual(request["attempt_count"], 1)
        self.assertEqual(request["settlement_kind"], "conservative_reservation")

    def test_allowlisted_malformed_response_is_unknown_and_never_retried(self) -> None:
        self.upstream.mode = "malformed_503"
        status, body, _headers = self._post(
            self._body(), request_id="malformed-ambiguous"
        )
        self.assertEqual(status, 502)
        self.assertEqual(
            json.loads(body)["error"]["code"], "unclassified_upstream_failure"
        )
        self.assertEqual(len(self.upstream.requests), 1)
        request = self.ledger.snapshot()["runs"]["benchmark-r1"]["requests"][
            "malformed-ambiguous"
        ]
        self.assertEqual(request["attempt_count"], 1)
        self.assertEqual(request["settlement_kind"], "conservative_reservation")

    def test_retry_backoff_and_attempts_share_one_transport_budget(self) -> None:
        self.proxy.close()
        now = [0.0]

        def monotonic() -> float:
            return now[0]

        def sleep(seconds: float) -> None:
            now[0] += seconds

        self.upstream.mode = "unbilled_503"
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="deadline-run",
            metadata_path=self.root / "deadline-metadata.json",
            **self._profile_kwargs(retry_backoff_seconds=30.0),
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
            _monotonic=monotonic,
            _sleep=sleep,
        ).start()
        status, _body, _headers = self._post(self._body(), request_id="deadline")
        self.assertEqual(status, 409)
        run = self.ledger.snapshot()["runs"]["deadline-run"]
        self.assertEqual(run["requests"]["deadline"]["attempt_count"], 2)
        self.assertEqual(run["spent_usd"], "0.000000")
        self.assertEqual(run["stop_reason"], "operator_confirmed_unbilled_deadline_exhausted")
        self.assertEqual(now[0], 30.0)

    def test_deadline_is_rechecked_after_lifecycle_lock_before_attempt(self) -> None:
        self.proxy.close()
        times = iter((0.0, 0.0, 91.0))

        def monotonic() -> float:
            return next(times, 91.0)

        class RecordingTransport:
            calls = 0

            def open(self, *_args: object, **_kwargs: object):
                self.calls += 1
                raise AssertionError("expired request reached transport")

        transport = RecordingTransport()
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="stale-deadline-run",
            metadata_path=self.root / "stale-deadline-metadata.json",
            **self._profile_kwargs(),
            _transport=transport,  # type: ignore[arg-type]
            _monotonic=monotonic,
        ).start()

        status, body, _headers = self._post(
            self._body(), request_id="stale-deadline-request"
        )

        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)["error"]["code"], "upstream_deadline_exhausted")
        self.assertEqual(transport.calls, 0)
        request = self.ledger.snapshot()["runs"]["stale-deadline-run"]["requests"][
            "stale-deadline-request"
        ]
        self.assertEqual(request["attempt_count"], 0)

    def test_close_waits_for_handler_and_prevents_a_post_close_retry(self) -> None:
        self.proxy.close()
        sleep_started = threading.Event()
        release_sleep = threading.Event()

        def blocking_sleep(_seconds: float) -> None:
            sleep_started.set()
            release_sleep.wait(timeout=5)

        self.upstream.mode = "unbilled_503"
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="close-lifecycle-run",
            metadata_path=self.root / "close-lifecycle-metadata.json",
            **self._profile_kwargs(retry_backoff_seconds=1.0),
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
            _sleep=blocking_sleep,
        ).start()
        client_result: list[tuple[int, bytes, object]] = []
        client = threading.Thread(
            target=lambda: client_result.append(
                self._post(self._body(), request_id="close-lifecycle-request")
            )
        )
        client.start()
        self.assertTrue(sleep_started.wait(timeout=2))

        closed = threading.Event()

        def close_proxy() -> None:
            self.proxy.close()
            closed.set()

        closer = threading.Thread(target=close_proxy)
        closer.start()
        self.assertTrue(self.proxy._closing.wait(timeout=2))
        self.assertFalse(closed.is_set())
        release_sleep.set()
        closer.join(timeout=2)
        client.join(timeout=2)

        self.assertTrue(closed.is_set())
        self.assertFalse(closer.is_alive())
        self.assertFalse(client.is_alive())
        self.assertEqual(len(self.upstream.requests), 1)
        self.assertEqual(client_result[0][0], 409)
        run = self.ledger.snapshot()["runs"]["close-lifecycle-run"]
        request = run["requests"]["close-lifecycle-request"]
        self.assertEqual(request["attempt_count"], 1)
        self.assertEqual(request["settlement_kind"], "operator_confirmed_unbilled")
        self.assertEqual(run["stop_reason"], "operator_confirmed_unbilled_proxy_closing")


class PersistentBudgetLedgerTests(unittest.TestCase):
    def test_read_only_loader_reuses_exact_validation_without_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "ledger.json"
            with PersistentBudgetLedger(
                path,
                batch_id="read-only-validation",
                total_cap_usd="10.00",
                max_runs=2,
                default_run_cap_usd="5.00",
            ) as ledger:
                ledger.claim_run("run-a")
                ledger.reserve("run-a", "request-a", "1.00")
            lock_path = path.with_name(f".{path.name}.lock")
            lock_path.unlink()
            before = path.read_bytes()
            state = load_validated_budget_ledger_state(
                path,
                batch_id="read-only-validation",
                total_cap_usd="10.00",
                max_runs=2,
                default_run_cap_usd="5.00",
            )
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(lock_path.exists())
            self.assertEqual(
                state["runs"]["run-a"]["requests"]["request-a"]["status"],
                "reserved",
            )

            malformed = json.loads(before)
            malformed["runs"]["run-a"]["spent_usd"] = "1.000000"
            path.write_text(
                json.dumps(malformed, sort_keys=True, separators=(",", ":")) + "\n",
                "utf-8",
            )
            path.chmod(0o600)
            with self.assertRaisesRegex(
                ApiBudgetProxyError, "run total is inconsistent"
            ):
                load_validated_budget_ledger_state(
                    path,
                    batch_id="read-only-validation",
                    total_cap_usd="10.00",
                    max_runs=2,
                    default_run_cap_usd="5.00",
                )

            path.write_bytes(before)
            path.chmod(0o644)
            with self.assertRaisesRegex(ApiBudgetProxyError, "mode 0600"):
                load_validated_budget_ledger_state(
                    path,
                    batch_id="read-only-validation",
                    total_cap_usd="10.00",
                    max_runs=2,
                    default_run_cap_usd="5.00",
                )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_explicit_profile_pricing_and_authorized_caps(self) -> None:
        usage = Usage(
            input_tokens=300_000,
            cached_input_tokens=100_000,
            cache_write_input_tokens=50_000,
            output_tokens=10_000,
        )
        terra_pricing = ModelPricing(
            model_id="locally-selected-terra-alias",
            input_usd_per_million=Decimal("2.00"),
            cached_input_usd_per_million=Decimal("0.20"),
            output_usd_per_million=Decimal("12.00"),
            long_context_threshold_tokens=272_000,
            long_context_input_multiplier=Decimal("2"),
            long_context_output_multiplier=Decimal("1.5"),
            cache_write_input_multiplier=Decimal("1.25"),
            price_snapshot_date="2026-08-10",
            price_source_url="https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        )
        alternate_policy = ModelPricing(
            model_id="local-model-with-different-pricing-policy",
            input_usd_per_million=Decimal("5.00"),
            cached_input_usd_per_million=Decimal("0.50"),
            output_usd_per_million=Decimal("30.00"),
            long_context_threshold_tokens=500_000,
            long_context_input_multiplier=Decimal("1"),
            long_context_output_multiplier=Decimal("1"),
            cache_write_input_multiplier=Decimal("1"),
            price_snapshot_date="2026-08-10",
            price_source_url="https://developers.openai.com/api/docs/models/compare",
        )
        self.assertEqual(price_usage(usage, pricing=MAIN_PRICING), Decimal("2.675000"))
        self.assertEqual(
            price_usage(usage, pricing=terra_pricing),
            Decimal("1.070000"),
        )
        self.assertEqual(
            price_usage(usage, pricing=GUARDIAN_PRICING),
            Decimal("0.107000"),
        )
        self.assertEqual(
            price_usage(usage, pricing=alternate_policy),
            Decimal("1.350000"),
        )
        self.assertEqual(BATCH_CAP_USD, Decimal("10.00"))
        self.assertEqual(MAX_REQUEST_RESERVATION_USD, Decimal("5.000000"))

    def test_priced_overage_records_full_cost_and_reopens_fail_closed(self) -> None:
        path = self.root / "priced-overage.json"
        ledger = PersistentBudgetLedger(path, batch_id="priced-overage")
        ledger.ensure_run("r1")
        ledger.reserve("r1", "q1", amount_usd="1")
        ledger.begin_attempt("r1", "q1", max_attempts=1)
        settlement = ledger.settle(
            "r1",
            "q1",
            Usage(1_050_000, 0, 1_050_000, 128_000),
            pricing=MAIN_PRICING,
        )
        self.assertEqual(settlement.charged_usd, Decimal("18.885000"))
        self.assertTrue(settlement.usage_valid)
        run = ledger.snapshot()["runs"]["r1"]
        self.assertEqual(run["spent_usd"], "18.885000")
        self.assertTrue(run["stopped"])
        self.assertEqual(run["stop_reason"], "usage_cost_exceeded_reservation")
        self.assertEqual(
            run["requests"]["q1"]["settlement_kind"], "usage_priced_overage"
        )
        with self.assertRaisesRegex(ApiBudgetProxyError, "must not be stopped"):
            completed_run_accounting(ledger.snapshot(), "r1")
        ledger.close()

        reopened = PersistentBudgetLedger(path, batch_id="priced-overage")
        self.assertEqual(reopened.snapshot()["runs"]["r1"], run)
        reopened.close()

        original_state = json.loads(path.read_text(encoding="utf-8"))
        tampered = json.loads(json.dumps(original_state))
        tampered_run = tampered["runs"]["r1"]
        tampered_run["requests"]["unreserved-extra"] = {
            "status": "settled",
            "reserved_usd": "5.000000",
            "charged_usd": "5.000000",
            "usage_valid": True,
            "attempt_count": 1,
            "settlement_kind": "usage_priced",
        }
        tampered_run["spent_usd"] = "23.885000"
        path.write_text(json.dumps(tampered), encoding="utf-8")
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(ApiBudgetProxyError, "run exceeds its cap"):
            PersistentBudgetLedger(path, batch_id="priced-overage")

        batch_tampered = json.loads(json.dumps(original_state))
        for run_id in ("r2", "r3"):
            batch_tampered["runs"][run_id] = {
                "cap_usd": "5.000000",
                "spent_usd": "5.000000",
                "stopped": False,
                "stop_reason": None,
                "requests": {
                    "q1": {
                        "status": "settled",
                        "reserved_usd": "5.000000",
                        "charged_usd": "5.000000",
                        "usage_valid": True,
                        "attempt_count": 1,
                        "settlement_kind": "usage_priced",
                    }
                },
            }
        path.write_text(json.dumps(batch_tampered), encoding="utf-8")
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(ApiBudgetProxyError, "ledger exceeds its batch cap"):
            PersistentBudgetLedger(path, batch_id="priced-overage")

    def test_four_runs_can_reserve_and_settle_concurrently(self) -> None:
        path = self.root / "budget.json"
        ledger = PersistentBudgetLedger(path, batch_id="concurrent")
        for number in range(4):
            ledger.ensure_run(f"r{number}")
        barrier = threading.Barrier(4)
        errors: list[BaseException] = []

        def worker(number: int) -> None:
            try:
                barrier.wait(timeout=5)
                ledger.reserve(f"r{number}", f"q{number}", amount_usd=Decimal("2.5"))
                ledger.begin_attempt(f"r{number}", f"q{number}", max_attempts=1)
                ledger.settle(
                    f"r{number}",
                    f"q{number}",
                    Usage(1000, 0, 0, 10),
                    pricing=MAIN_PRICING,
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(number,)) for number in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        self.assertEqual(ledger.snapshot()["run_slots_used"], 4)
        with self.assertRaises(BudgetStopped):
            ledger.ensure_run("r4")
        ledger.close()

    def test_crashed_reservation_is_charged_and_run_stopped_on_reopen(self) -> None:
        path = self.root / "budget.json"
        ledger = PersistentBudgetLedger(path, batch_id="recover")
        ledger.ensure_run("r1")
        ledger.reserve("r1", "q1")
        ledger.close()
        reopened = PersistentBudgetLedger(path, batch_id="recover")
        run = reopened.snapshot()["runs"]["r1"]
        self.assertTrue(run["stopped"])
        self.assertEqual(run["stop_reason"], "interrupted_request")
        self.assertEqual(run["spent_usd"], format(MAX_REQUEST_RESERVATION_USD, "f"))
        self.assertEqual(run["requests"]["q1"]["attempt_count"], 0)
        self.assertEqual(
            run["requests"]["q1"]["settlement_kind"],
            "conservative_reservation",
        )
        with self.assertRaises(BudgetStopped):
            reopened.reserve("r1", "q2")
        reopened.close()

    def test_claim_run_rejects_reusing_an_existing_invocation(self) -> None:
        path = self.root / "claim-budget.json"
        with PersistentBudgetLedger(path, batch_id="claim-batch") as ledger:
            ledger.claim_run("run-1")
            with self.assertRaises(BudgetStopped):
                ledger.claim_run("run-1")

    def test_invalid_state_and_over_authorized_configuration_fail_closed(self) -> None:
        with PersistentBudgetLedger(
            self.root / "formal-max-envelope.json",
            batch_id="formal-max-envelope",
            total_cap_usd="80",
            default_run_cap_usd="40",
        ) as ledger:
            ledger.claim_run("rondo")
            ledger.reserve("rondo", "main", amount_usd=MAIN_MAX_USAGE_COST)
            ledger.reserve("rondo", "guardian", amount_usd=MAIN_MAX_USAGE_COST)
            requests = ledger.snapshot()["runs"]["rondo"]["requests"]
            self.assertEqual(
                sum(Decimal(request["reserved_usd"]) for request in requests.values()),
                Decimal("37.770000"),
            )
        with PersistentBudgetLedger(
            self.root / "formal-concurrent.json",
            batch_id="formal-concurrent",
            total_cap_usd="20",
            default_run_cap_usd="10",
        ) as ledger:
            ledger.claim_run("rondo")
            ledger.reserve("rondo", "main", amount_usd="5")
            ledger.reserve("rondo", "guardian", amount_usd="5")
            requests = ledger.snapshot()["runs"]["rondo"]["requests"]
            self.assertEqual(
                sum(Decimal(request["reserved_usd"]) for request in requests.values()),
                Decimal("10.000000"),
            )
        with self.assertRaises(ApiBudgetProxyError):
            PersistentBudgetLedger(
                self.root / "too-much.json", batch_id="bad", total_cap_usd="1600.01"
            )
        with PersistentBudgetLedger(
            self.root / "campaign.json",
            batch_id="campaign",
            total_cap_usd="1600",
            max_runs=321,
            default_run_cap_usd="40",
        ) as campaign:
            self.assertEqual(campaign.snapshot()["max_runs"], 321)
        with self.assertRaises(ApiBudgetProxyError):
            PersistentBudgetLedger(
                self.root / "too-many-runs.json",
                batch_id="bad-runs",
                total_cap_usd="1600",
                max_runs=322,
                default_run_cap_usd="40",
            )
        with self.assertRaises(ApiBudgetProxyError):
            PersistentBudgetLedger(
                self.root / "too-much-run.json",
                batch_id="bad-run",
                default_run_cap_usd="40.01",
            )
        path = self.root / "bad-mode.json"
        path.write_text("{}", encoding="utf-8")
        os.chmod(path, 0o644)
        with self.assertRaises(ApiBudgetProxyError):
            PersistentBudgetLedger(path, batch_id="bad-mode")


if __name__ == "__main__":
    unittest.main()
