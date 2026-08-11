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

from rondo_eval.api_budget_proxy import _UrllibTransport  # noqa: E402
from rondo_eval.config import RepoPaths, RuntimeConfig  # noqa: E402
from rondo_eval.provider_probe import (  # noqa: E402
    PROBE_USER_AGENT,
    ProviderProbeError,
    probe_models_status,
    run_provider_probes,
)


class _Provider:
    def __init__(self) -> None:
        self.secret = "provider-probe-secret-sentinel"
        self.models_redirect = False
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
        paths = RepoPaths(self.root, self.root)
        self.config = RuntimeConfig(paths, {
            "providers": {
                "openai": {
                    "api": "responses",
                    "base_url": "https://provider.example/v1",
                    "api_key_env": "OPENAI_API_KEY",
                    "main_model": "gpt-5.6-sol",
                    "guardian_model": "gpt-5.6-luna",
                    "guardian_reasoning_effort": "low",
                }
            }
        }, "a" * 64)

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
        self.assertEqual(receipt["request_count"], 2)
        self.assertEqual(receipt["reserved_usd"], "0.000000")
        self.assertEqual([item["terminal"] for item in receipt["responses"]], [True, True])
        self.assertEqual(len(self.provider.requests), 2)
        self.assertTrue(all(
            item["authorization"] == f"Bearer {self.provider.secret}"
            for item in self.provider.requests
        ))
        for item in self.provider.requests:
            self.assertEqual(item["role"], "main")
            self.assertEqual(item["user_agent"], PROBE_USER_AGENT)
            self.assertEqual(item["originator"], "codex_cli_rs")
            body = item["body"]
            self.assertEqual(body["max_output_tokens"], 64)
            self.assertEqual(body["reasoning"], {"effort": "low"})
        for path in (self.root / "probe").iterdir():
            if path.is_file():
                self.assertNotIn(self.provider.secret.encode(), path.read_bytes())

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

if __name__ == "__main__":
    unittest.main()
