"""Small in-process fake for no-model `/v1/responses` contract tests."""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Mapping, Sequence

from .launcher import LLAMA_CPP_BUILD, LLAMA_CPP_COMMIT


_MAX_REQUEST_BYTES = 1_048_576


class FakeApprovalServer:
    """Context-managed fake that records bodies but never authorization values."""

    def __init__(
        self,
        *,
        decision: Mapping[str, Any] | None = None,
        response_override: Any | None = None,
        required_bearer: str | None = None,
    ):
        self.decision = dict(
            decision
            or {"outcome": "deny", "rationale": "fake server decision", "risk_tags": ["fake"]}
        )
        self.response_override = response_override
        self.required_bearer = required_bearer
        self.requests: list[dict[str, Any]] = []
        self.authorization_seen: list[bool] = []
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_type(self))
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> "FakeApprovalServer":
        if self._thread is not None:
            raise RuntimeError("fake approval server is already started")
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
            self._thread = None
        self._server.server_close()

    def __enter__(self) -> "FakeApprovalServer":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()


def _handler_type(fake: FakeApprovalServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RONDOFakeApproval/1"

        def log_message(self, _format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path in {"/health", "/v1/health"}:
                self._json(200, {"status": "ok"})
                return
            if self.path == "/props":
                self._json(
                    200,
                    {
                        "role": "router",
                        "build_info": f"build {LLAMA_CPP_BUILD} ({LLAMA_CPP_COMMIT[:8]})",
                    },
                )
                return
            self._json(404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path != "/v1/responses":
                self._json(404, {"error": {"message": "not found"}})
                return
            length_text = self.headers.get("Content-Length")
            try:
                length = int(length_text) if length_text is not None else -1
            except ValueError:
                length = -1
            if not 0 <= length <= _MAX_REQUEST_BYTES:
                self._json(400, {"error": {"message": "invalid request size"}})
                return
            try:
                body = json.loads(self.rfile.read(length))
            except (UnicodeError, json.JSONDecodeError):
                self._json(400, {"error": {"message": "invalid JSON"}})
                return
            if not isinstance(body, dict) or _contains_tool_transport(body):
                self._json(400, {"error": {"message": "tool transport is forbidden"}})
                return
            response_format = body.get("response_format")
            json_schema = response_format.get("json_schema") if isinstance(response_format, dict) else None
            if (
                not isinstance(response_format, dict)
                or response_format.get("type") != "json_schema"
                or not isinstance(json_schema, dict)
                or not isinstance(json_schema.get("schema"), dict)
                or json_schema.get("strict") is not True
            ):
                self._json(400, {"error": {"message": "pinned response_format is required"}})
                return
            authorization = self.headers.get("Authorization")
            authorized = fake.required_bearer is None or authorization == f"Bearer {fake.required_bearer}"
            fake.authorization_seen.append(authorization is not None)
            if not authorized:
                self._json(401, {"error": {"message": "unauthorized"}})
                return
            fake.requests.append(body)
            envelope = fake.response_override
            if envelope is None:
                decision_text = json.dumps(
                    fake.decision,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                envelope = {
                    "id": "resp_fake_local_approval",
                    "object": "response",
                    "status": "completed",
                    "model": body.get("model"),
                    "output": [
                        {
                            "id": "msg_fake_local_approval",
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": decision_text}],
                        }
                    ],
                }
            self._json(200, envelope)

        def _json(self, status: int, value: Any) -> None:
            body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _contains_tool_transport(value: Any) -> bool:
    if isinstance(value, Mapping):
        if "tools" in value or value.get("type") == "additional_tools":
            return True
        return any(_contains_tool_transport(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_tool_transport(item) for item in value)
    return False


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local approval fake server")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    fake = FakeApprovalServer()
    if args.port:
        fake._server.server_close()
        fake._server = ThreadingHTTPServer(("127.0.0.1", args.port), _handler_type(fake))
    try:
        fake.start()
        print(json.dumps({"status": "ready", "base_url": fake.base_url}, sort_keys=True), flush=True)
        assert fake._thread is not None
        fake._thread.join()
    except KeyboardInterrupt:
        pass
    finally:
        fake.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
