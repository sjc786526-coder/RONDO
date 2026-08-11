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
    GUARDIAN_OUTPUT_SCHEMA,
    MAX_REQUEST_RESERVATION_USD,
    PRICE_SNAPSHOT_DATE,
    PRICE_SOURCE_URL,
    TERRA_PRICE_SOURCE_URL,
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
    milestone_metadata_ready,
    price_usage,
)


class _FakeUpstream:
    def __init__(self) -> None:
        self.mode = "json"
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
                    mode = owner.mode
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
            self.root / "budget.json", batch_id="p1-batch"
        )
        self.proxy = LoopbackResponsesProxy(
            upstream_base_url="https://provider.example/v1",
            api_key=self.secret,
            ledger=self.ledger,
            run_id="benchmark-r1",
            metadata_path=self.root / "metadata.json",
            _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
        ).start()

    def tearDown(self) -> None:
        self.proxy.close()
        self.ledger.close()
        self.upstream.close()
        self.temp.cleanup()

    def _post(
        self,
        body: dict[str, object],
        *,
        role: str | None = "main",
        request_id: str = "request-1",
        extra_headers: dict[str, str] | None = None,
        path: str = "/responses",
        authenticate: bool = True,
    ) -> tuple[int, bytes, object]:
        encoded = json.dumps(body).encode()
        headers = {
            "Content-Type": "application/json",
            "X-RONDO-Eval-Request-Id": request_id,
            "User-Agent": "codex_cli_rs/0.147.0 (proxy-test)",
            "originator": "codex_cli_rs",
        }
        if authenticate:
            headers["Authorization"] = f"Bearer {self.proxy.downstream_api_key}"
        if role is not None:
            headers["X-RONDO-Eval-Role"] = role
        if extra_headers:
            headers.update(extra_headers)
        request = Request(
            self.proxy.base_url + path,
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
                    _transport=_UrllibTransport(endpoint_override=self.upstream.endpoint),
                )
                self.assertEqual(proxy.upstream_endpoint, endpoint)

    def test_transport_timeout_is_bounded_independently_from_agent_timeout(self) -> None:
        self.assertEqual(UPSTREAM_TIMEOUT_SECONDS, 90.0)
        with self.assertRaisesRegex(ApiBudgetProxyError, "90 second"):
            LoopbackResponsesProxy(
                upstream_base_url="https://provider.example/v1",
                api_key=self.secret,
                ledger=self.ledger,
                run_id="overlong-timeout",
                metadata_path=self.root / "overlong-timeout.json",
                timeout_seconds=900.0,
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
        effort: str | None = None,
        guardian: bool = False,
    ) -> dict[str, object]:
        body: dict[str, object] = {
            "model": "gpt-5.6-luna" if guardian else "gpt-5.6-sol",
            "input": [{"role": "user", "content": "secret prompt is never recorded"}],
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
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response_body)["id"], "fake-response")
        self.assertIsNone(headers.get("Authorization"))
        self.assertEqual(len(self.upstream.requests), 1)
        self.assertEqual(
            self.upstream.requests[0]["authorization"], f"Bearer {self.secret}"
        )
        self.assertEqual(self.upstream.requests[0]["role"], "main")
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
        self.assertEqual(observation["model"], "gpt-5.6-sol")
        self.assertEqual(observation["shape"]["input_items"], 1)
        self.assertEqual(len(observation["body_sha256"]), 64)
        self.assertTrue(observation["contract_match"])
        self.assertTrue(observation["usage_valid"])
        self.assertTrue(milestone_metadata_ready(self.root / "metadata.json"))
        self.assertEqual(os.stat(self.root / "metadata.json").st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(self.root / "budget.json").st_mode & 0o777, 0o600)

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
        self.assertTrue(run["stopped"])
        self.assertEqual(snapshot["reserved_usd"], "0.000000")
        observation = json.loads(
            (self.root / "timeout-metadata.json").read_text(encoding="utf-8")
        )["requests"][0]
        self.assertEqual(observation["upstream_status"], 0)

    def test_missing_role_header_projects_declared_main_from_request_shape(self) -> None:
        status, _body, _headers = self._post(self._body(), role=None)
        self.assertEqual(status, 200)
        observation = json.loads((self.root / "metadata.json").read_text())["requests"][0]
        self.assertEqual(observation["role"], "main")
        self.assertEqual(observation["role_provenance"], "declared")
        self.assertEqual(observation["declared_role"], "main")
        self.assertEqual(observation["inferred_role"], "main")
        self.assertTrue(observation["contract_match"])
        self.assertEqual(self.upstream.requests[0]["role"], "main")
        self.assertTrue(milestone_metadata_ready(self.root / "metadata.json"))

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
        self.assertEqual(self.upstream.requests[0]["role"], "guardian")
        self.assertTrue(milestone_metadata_ready(self.root / "metadata.json"))

    def test_missing_usage_charges_reservation_stops_run_and_prevents_forward(self) -> None:
        self.upstream.mode = "missing_usage"
        status, _body, _headers = self._post(self._body(), request_id="missing-1")
        self.assertEqual(status, 200)
        run = self.ledger.snapshot()["runs"]["benchmark-r1"]
        self.assertTrue(run["stopped"])
        self.assertEqual(run["stop_reason"], "missing_or_invalid_usage")
        self.assertEqual(run["spent_usd"], format(MAX_REQUEST_RESERVATION_USD, "f"))
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
        self.assertEqual(run["spent_usd"], format(MAX_REQUEST_RESERVATION_USD, "f"))

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


class PersistentBudgetLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_frozen_main_and_guardian_pricing_and_reservation(self) -> None:
        usage = Usage(
            input_tokens=300_000,
            cached_input_tokens=100_000,
            cache_write_input_tokens=50_000,
            output_tokens=10_000,
        )
        self.assertEqual(PRICE_SNAPSHOT_DATE, "2026-08-10")
        self.assertEqual(
            PRICE_SOURCE_URL,
            "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
        )
        self.assertEqual(price_usage(usage), Decimal("2.675000"))
        self.assertEqual(
            TERRA_PRICE_SOURCE_URL,
            "https://developers.openai.com/api/docs/models/gpt-5.6-terra",
        )
        self.assertEqual(
            price_usage(usage, model="gpt-5.6-terra"),
            Decimal("1.070000"),
        )
        self.assertEqual(
            price_usage(usage, model="gpt-5.6-luna"),
            Decimal("0.107000"),
        )
        self.assertEqual(MAX_REQUEST_RESERVATION_USD, Decimal("5.000000"))

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
                ledger.reserve(f"r{number}", f"q{number}")
                ledger.settle(
                    f"r{number}",
                    f"q{number}",
                    Usage(1000, 0, 0, 10),
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
        with self.assertRaises(ApiBudgetProxyError):
            PersistentBudgetLedger(
                self.root / "too-much.json", batch_id="bad", total_cap_usd="20.01"
            )
        path = self.root / "bad-mode.json"
        path.write_text("{}", encoding="utf-8")
        os.chmod(path, 0o644)
        with self.assertRaises(ApiBudgetProxyError):
            PersistentBudgetLedger(path, batch_id="bad-mode")


if __name__ == "__main__":
    unittest.main()
