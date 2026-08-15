"""Identity-gated loopback adapter between the live Guardian and llama.cpp.

A Guardian provider pointed straight at the pinned b10333 server cannot work:
that pin converts Responses requests through its Chat Completions parser and
never maps the OpenAI `text.format` control, so the output contract is silently
dropped, and nothing on that wire consumes the launcher receipt that says which
model instance is answering.  This adapter closes both gaps in the one place
that is allowed to know about them.  RONDO keeps speaking its own Responses
wire and keeps its own Guardian semantics; what reaches the pinned server
keeps the two boundaries its 12k qualification did establish - the shared
`build_static_payload()` input normalization and the qualified serving
contract, sampling and output budget - while carrying the Guardian's own
instructions and output schema.  It is therefore not that qualification's
static request, and the length conclusions drawn from the qualification and
the token census do not bound this route.

Three properties are load bearing:

1. The inbound `input` is normalized by `build_static_payload()`, the same
   provider-neutral boundary the token census and the qualification used, so
   the evidence role and reasoning handling this route depends on is the one
   already proved against the pin rather than a second, parallel copy of it.
   The request as a whole is *not* the qualified static request: it carries the
   Guardian's own instructions and output schema (see below), so the census
   length figures do not bound this route.
2. Nothing is written downstream until the launcher receipt has been checked
   again after the response was read.  The whole answer is buffered, so a
   result produced by an instance that changed inside the request window can
   never reach the approval chain.
3. Every failure is an HTTP failure.  Transport faults, identity drift and
   non-conforming output are never rendered as a decision, so RONDO records
   them as a failed-closed review instead of a business deny.

The server-side grammar is not treated as a security boundary; the decision is
validated here against the schema the Guardian actually asked for.
"""

from __future__ import annotations

import argparse
import copy
import hmac
import json
import secrets
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config import (
    ConfigError,
    RepoPaths,
    RuntimeConfig,
    load_local_model_secret,
    load_runtime_config,
)
from ..evidence import EvidenceError, build_static_payload
from ..exit_codes import CONFIG_ERROR, INFRA_ERROR, SUCCESS
from .client import (
    LocalApprovalClient,
    LocalApprovalError,
    LocalApprovalSettings,
    ServiceUnavailableError,
    StructuredOutputError,
    response_output_text,
)


RESPONSES_PATH = "/v1/responses"
# Environment variable the Guardian provider reads when no local model key is
# configured; the value is minted per bridge process and never written to disk.
_EPHEMERAL_SECRET_NAME = "RONDO_LOCAL_GUARDIAN_BRIDGE_TOKEN"
# One Guardian turn at the qualified 12,288-token contract is far below this;
# the limit only exists so an unbounded body cannot be buffered.
MAX_REQUEST_BYTES = 4 * 1024 * 1024
_SUPPORTED_SCHEMA_KEYS = frozenset({"type", "additionalProperties", "properties", "required"})
_SUPPORTED_PROPERTY_KEYS = frozenset({"type", "enum"})


class BridgeError(RuntimeError):
    """Refusal that is reported to RONDO as a transport failure, never a deny."""

    http_status = 502
    reason = "bridge_error"


class UnauthorizedError(BridgeError):
    http_status = 401
    reason = "unauthorized"


class GuardianRequestError(BridgeError):
    http_status = 400
    reason = "invalid_guardian_request"


class UpstreamUnavailableError(BridgeError):
    http_status = 503
    reason = "service_unavailable"


class UpstreamOutputError(BridgeError):
    http_status = 502
    reason = "structured_output"


@dataclass(frozen=True)
class BridgeDecision:
    """One fully buffered, identity-confirmed answer ready to be streamed."""

    response_id: str
    output_text: str
    usage: dict[str, int] | None

    def sse_body(self) -> bytes:
        completed: dict[str, Any] = {"id": self.response_id}
        if self.usage is not None:
            completed["usage"] = self.usage
        events = (
            {"type": "response.created", "response": {"id": self.response_id}},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": self.output_text}],
                },
            },
            {"type": "response.completed", "response": completed},
        )
        return b"".join(
            b"data: "
            + json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                "utf-8"
            )
            + b"\n\n"
            for event in events
        )


def output_format(guardian_request: Mapping[str, Any]) -> dict[str, Any]:
    """Read the structured output contract the Guardian request carries.

    A Guardian turn without one would let the local model answer in free text
    and be graded by a lenient prose parser, so its absence is refused instead
    of defaulted.  The schema is resolved here as well, before anything is
    sent: a contract this boundary could not check afterwards is not worth
    spending a model call on.
    """

    text = guardian_request.get("text")
    text_format = text.get("format") if isinstance(text, Mapping) else None
    if not isinstance(text_format, Mapping) or set(text_format) != {
        "type",
        "strict",
        "schema",
        "name",
    }:
        raise GuardianRequestError("Guardian request carries no known text.format control")
    name = text_format["name"]
    schema = text_format["schema"]
    if (
        text_format["type"] != "json_schema"
        or not isinstance(name, str)
        or not name
        or not isinstance(text_format["strict"], bool)
        or not isinstance(schema, Mapping)
        or not schema
    ):
        raise GuardianRequestError("Guardian text.format is not a usable JSON schema request")
    _supported_schema(schema)
    return {"name": name, "schema": copy.deepcopy(dict(schema))}


def build_upstream_request(
    settings: LocalApprovalSettings,
    guardian_request: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one live Guardian request onto the qualified pinned request.

    The Guardian's own instructions and output schema are carried through
    verbatim: the local model answers RONDO's real question under RONDO's real
    contract.  That is deliberately *not* the qualified static request, which
    wraps the policy in `STATIC_INSTRUCTIONS` and asks for the
    `rondo_static_approval_v1` shape; prepending eval-side instructions to a
    live approval turn would change what the Guardian asked.  What this route
    reuses from the qualified path is the `input` normalization and the serving
    contract that decides *how* the answer is produced - sampling, output
    budget, and the pin-specific `response_format` passthrough.  `tools` are
    not forwarded: b10333 refuses a grammar together with tools, and a static
    local approval model is given no tools or self-investigation by design.
    """

    if guardian_request.get("model") != settings.model_id:
        raise GuardianRequestError("Guardian request model differs from the configured local model")
    text_format = output_format(guardian_request)
    try:
        logical = build_static_payload(guardian_request).logical_payload
    except EvidenceError as exc:
        raise GuardianRequestError("Guardian request is not a normalizable static payload") from exc
    return {
        "model": settings.model_id,
        "instructions": logical["guardian_policy"],
        "input": logical["input"],
        "stream": False,
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "seed": settings.seed,
        "max_output_tokens": settings.max_output_tokens,
        # b10333-specific passthrough to the Chat Completions parser. The pin
        # reads only `json_schema.schema`; `strict` stays pinned to the
        # qualified value because the pin never looks at it and the real
        # conformance check is the local one below.
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": text_format["name"],
                "strict": True,
                "schema": text_format["schema"],
            },
        },
    }


def validate_decision(text: str, schema: Mapping[str, Any]) -> dict[str, Any]:
    """Check the model answer against the schema the Guardian actually sent.

    Only the constructs the Guardian output contract uses are understood, and
    an unknown construct is refused rather than skipped, because a schema this
    boundary cannot evaluate is a schema it cannot claim was honored.
    """

    required, properties = _supported_schema(schema)
    try:
        decision = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UpstreamOutputError("local Guardian output is not JSON") from exc
    if not isinstance(decision, Mapping):
        raise UpstreamOutputError("local Guardian output is not a JSON object")
    if set(decision) - set(properties):
        raise UpstreamOutputError("local Guardian output has fields outside the schema")
    if required - set(decision):
        raise UpstreamOutputError("local Guardian output is missing a required field")
    for name, value in decision.items():
        allowed = properties[name]
        if not isinstance(value, str):
            raise UpstreamOutputError("local Guardian output field is not a string")
        if allowed is not None and value not in allowed:
            raise UpstreamOutputError("local Guardian output field is outside its enum")
    return dict(decision)


def _supported_schema(
    schema: Mapping[str, Any],
) -> tuple[set[str], dict[str, frozenset[str] | None]]:
    if not isinstance(schema, Mapping):
        raise GuardianRequestError("Guardian output schema is not an object")
    properties = schema.get("properties")
    required = schema.get("required", [])
    if (
        set(schema) - _SUPPORTED_SCHEMA_KEYS
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or not isinstance(properties, Mapping)
        or not properties
        or not isinstance(required, list)
    ):
        raise GuardianRequestError("Guardian output schema uses unsupported constructs")
    resolved: dict[str, frozenset[str] | None] = {}
    for name, definition in properties.items():
        if (
            not isinstance(name, str)
            or not isinstance(definition, Mapping)
            or set(definition) - _SUPPORTED_PROPERTY_KEYS
            or definition.get("type") != "string"
        ):
            raise GuardianRequestError("Guardian output schema property is unsupported")
        values = definition.get("enum")
        if values is None:
            resolved[name] = None
            continue
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(value, str) for value in values)
        ):
            raise GuardianRequestError("Guardian output schema enum is unsupported")
        resolved[name] = frozenset(values)
    if any(not isinstance(name, str) or name not in resolved for name in required):
        raise GuardianRequestError("Guardian output schema requires an undeclared property")
    return set(required), resolved


def _usage(envelope: Mapping[str, Any]) -> dict[str, int] | None:
    usage = envelope.get("usage")
    if not isinstance(usage, Mapping):
        return None
    counts: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        counts[key] = value
    return counts


class GuardianBridge:
    """Authorize, normalize, forward and gate exactly one Guardian request."""

    def __init__(self, config: RuntimeConfig, *, client: LocalApprovalClient | None = None):
        self.config = config
        self.client = client if client is not None else LocalApprovalClient(config)
        self.settings = self.client.settings
        # The credential for the RONDO -> bridge hop.  A key configured for the
        # local model is read through the one strict loader and reused; without
        # one the bridge mints a token that lives only in this process, so the
        # hop is never unauthenticated and no key file has to be created for it.
        # Cloud credentials have no path into either case.
        configured = load_local_model_secret(config)
        self._secret_name = configured[0] if configured is not None else _EPHEMERAL_SECRET_NAME
        self._secret = configured[1] if configured is not None else secrets.token_hex(32)
        self._secret_is_ephemeral = configured is None

    @property
    def secret_name(self) -> str:
        return self._secret_name

    @property
    def secret(self) -> str:
        return self._secret

    @property
    def secret_is_ephemeral(self) -> bool:
        return self._secret_is_ephemeral

    def authorize(self, authorization: str | None) -> None:
        expected = f"Bearer {self._secret}"
        if not isinstance(authorization, str) or not hmac.compare_digest(authorization, expected):
            raise UnauthorizedError("local Guardian bridge rejected the presented credential")

    def decide(self, body: bytes) -> BridgeDecision:
        try:
            guardian_request = json.loads(body)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise GuardianRequestError("Guardian request is not valid JSON") from exc
        if not isinstance(guardian_request, Mapping):
            raise GuardianRequestError("Guardian request is not a JSON object")
        upstream = build_upstream_request(self.settings, guardian_request)
        schema = upstream["response_format"]["json_schema"]["schema"]
        try:
            identity = self.client.require_service_identity()
            if identity is None:
                # No pinned model means no launcher receipt, and therefore no
                # way to say which instance answered.  An unbound relay is not
                # something this route may serve an approval from.
                raise ServiceUnavailableError(
                    "local Guardian route is not bound to a launcher instance"
                )
            envelope = self.client.post_decision_request(upstream, identity)
        except ServiceUnavailableError as exc:
            raise UpstreamUnavailableError("local Guardian service or instance is unavailable") from exc
        except StructuredOutputError as exc:
            raise UpstreamOutputError("local Guardian response could not be read") from exc
        except LocalApprovalError as exc:
            raise UpstreamUnavailableError("local Guardian request failed") from exc
        try:
            text = response_output_text(envelope, expected_model=self.settings.model_id)
        except StructuredOutputError as exc:
            raise UpstreamOutputError("local Guardian response envelope is not usable") from exc
        validate_decision(text, schema)
        response_id = envelope.get("id")
        if not isinstance(response_id, str) or not response_id:
            response_id = f"resp_{secrets.token_hex(12)}"
        return BridgeDecision(response_id, text, _usage(envelope))


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """Never print a traceback: they can carry request text to stderr."""

    def handle_error(self, request: Any, client_address: Any) -> None:
        return


class GuardianBridgeServer:
    """Loopback-only front end; one adapter instance, no upstream fan-out."""

    def __init__(self, bridge: GuardianBridge, *, port: int = 0):
        self.bridge = bridge
        self.request_count = 0
        self.failures: list[str] = []
        self._server = _QuietThreadingHTTPServer(("127.0.0.1", port), _handler_type(self))
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> "GuardianBridgeServer":
        if self._thread is not None:
            raise RuntimeError("local Guardian bridge is already started")
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join(timeout=5)
            self._thread = None
        self._server.server_close()

    def __enter__(self) -> "GuardianBridgeServer":
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.close()


def _handler_type(front: GuardianBridgeServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RONDOGuardianBridge/1"
        protocol_version = "HTTP/1.1"

        def log_message(self, _format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            if self.path != RESPONSES_PATH:
                self._fail(404, "not_found")
                return
            length_text = self.headers.get("Content-Length")
            try:
                length = int(length_text) if length_text is not None else -1
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_REQUEST_BYTES:
                self._fail(413, "invalid_request_size")
                return
            # Read the body before deciding anything: leaving it undrained on a
            # keep-alive connection would desync the next request on it.
            body = self.rfile.read(length)
            try:
                front.bridge.authorize(self.headers.get("Authorization"))
                front.request_count += 1
                payload = front.bridge.decide(body).sse_body()
            except BridgeError as error:
                front.failures.append(error.reason)
                self._fail(error.http_status, error.reason)
                return
            except Exception:
                # Anything unforeseen is still a refusal, and it is reported as
                # a fixed code: an escaping traceback would both leave the
                # request unanswered and put request data on stderr.
                front.failures.append("bridge_error")
                self._fail(502, "bridge_error")
                return
            # Only reached once the receipt has been re-checked after the
            # response was read, so nothing acceptable as an approval has been
            # written before the instance was confirmed.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            self._fail(404, "not_found")

        def _fail(self, status: int, reason: str) -> None:
            # Reasons are fixed identifiers, never model text or request data.
            payload = json.dumps(
                {"error": {"type": "local_guardian_bridge", "code": reason}},
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            # A refusal can happen before the body was drained, so the
            # connection is retired rather than left to desync the next
            # request parsed off it.
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Serve the identity-gated local Guardian bridge on loopback"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        print(json.dumps({"status": "configuration_error"}, sort_keys=True))
        return CONFIG_ERROR
    try:
        config = load_runtime_config(RepoPaths.discover(args.repo))
        bridge = GuardianBridge(config)
        if bridge.secret_is_ephemeral:
            # A minted token only exists inside the process that made it, so a
            # standalone server would refuse every caller.  Serving from here
            # requires a configured local model key.
            raise ConfigError("standalone bridge requires a configured local model key")
        server = GuardianBridgeServer(bridge, port=args.port)
    except ConfigError:
        print(json.dumps({"status": "configuration_error"}, sort_keys=True))
        return CONFIG_ERROR
    except OSError:
        print(json.dumps({"status": "bind_failed"}, sort_keys=True))
        return INFRA_ERROR
    with server:
        print(
            json.dumps(
                {"status": "listening", "base_url": server.base_url},
                sort_keys=True,
            ),
            flush=True,
        )
        try:
            while True:
                threading.Event().wait(3600)
        except KeyboardInterrupt:
            return SUCCESS
    return SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
