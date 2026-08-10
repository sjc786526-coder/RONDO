"""Strict `/v1/responses` client for the pinned llama.cpp server.

llama.cpp b10333 converts Responses requests to its Chat Completions parser.
That pin does not map the OpenAI `text.format` field, so this client uses the
pin-specific top-level `response_format` field and validates the result again
locally.  The server-side grammar is never treated as a security boundary.
"""

from __future__ import annotations

import copy
import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..config import ConfigError, RuntimeConfig, load_local_model_secret
from ..evidence import (
    EvidenceError,
    StaticApprovalPayload,
    validate_static_decision,
    validate_static_payload,
)
from ..exit_codes import SERVICE_UNAVAILABLE, STRUCTURED_OUTPUT_ERROR


_MAX_RESPONSE_BYTES = 1_048_576


class LocalApprovalError(RuntimeError):
    """Base error with a stable command-line exit code."""

    exit_code: int


class ServiceUnavailableError(LocalApprovalError):
    exit_code = SERVICE_UNAVAILABLE


class StructuredOutputError(LocalApprovalError):
    exit_code = STRUCTURED_OUTPUT_ERROR


@dataclass(frozen=True)
class LocalApprovalSettings:
    base_url: str
    responses_url: str
    model_id: str
    model_path: str
    model_sha256: str
    quantization: str
    binary: str
    host: str
    port: int
    context_size: int
    gpu_layers: int | str
    flash_attention: str
    parallel: int
    metrics: bool
    slots: bool
    timeout_seconds: float
    temperature: float
    top_p: float
    seed: int
    max_output_tokens: int


def settings_from_config(config: RuntimeConfig) -> LocalApprovalSettings:
    """Project the local-model TOML table into a fail-closed runtime contract."""

    local = config.local_model()
    if local.get("runtime") != "llama_cpp" or local.get("api") != "responses":
        raise ConfigError("local_model must use llama_cpp and the Responses API")
    for key in ("model_id", "model_path", "base_url"):
        if not isinstance(local.get(key), str):
            raise ConfigError(f"local_model {key} must be a string")
    model_sha256 = local.get("model_sha256", "")
    if not isinstance(model_sha256, str):
        raise ConfigError("local_model model_sha256 must be a string")
    if not local["model_id"]:
        raise ConfigError("local_model model_id is empty")
    if local["model_path"]:
        if not re.fullmatch(r"[0-9a-f]{64}", model_sha256):
            raise ConfigError("local_model model_sha256 must pin the configured model")
    elif model_sha256:
        raise ConfigError("local_model model_sha256 requires a model_path")
    if local.get("format") != "gguf":
        raise ConfigError("local_model format must be gguf")
    quantization = local.get("quantization")
    if not isinstance(quantization, str) or not quantization:
        raise ConfigError("local_model quantization must be a non-empty string")

    try:
        parsed = urllib.parse.urlsplit(local["base_url"])
        endpoint_port = parsed.port
    except ValueError as exc:
        raise ConfigError("local_model base_url is invalid") from exc
    if (
        parsed.scheme != "http"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
    ):
        raise ConfigError("local_model base_url must be a loopback HTTP /v1 endpoint")

    server = local.get("server")
    request = local.get("request")
    if not isinstance(server, dict) or not isinstance(request, dict):
        raise ConfigError("local_model server and request tables are required")
    binary = _nonempty_string(server, "binary", "local_model server")
    host = _nonempty_string(server, "host", "local_model server")
    port = _integer(server, "port", minimum=1, maximum=65535)
    if host != "127.0.0.1" or parsed.hostname not in {host, "localhost"}:
        raise ConfigError("llama.cpp must bind to 127.0.0.1 and match base_url")
    if (endpoint_port or 80) != port:
        raise ConfigError("local_model base_url and server port differ")
    if server.get("tools") is not False or server.get("web_ui") is not False:
        raise ConfigError("local approval server tools and web UI must be disabled")
    metrics = _boolean(server, "metrics")
    slots = _boolean(server, "slots")
    context_size = _integer(server, "context_size", minimum=0, maximum=10_000_000)
    parallel = _integer(server, "parallel", minimum=1, maximum=64)
    gpu_layers = server.get("gpu_layers")
    if gpu_layers != "auto" and (
        not isinstance(gpu_layers, int) or isinstance(gpu_layers, bool) or gpu_layers < 0
    ):
        raise ConfigError("local_model server gpu_layers must be non-negative or auto")
    flash = server.get("flash_attention")
    if flash not in {"auto", "on", "off"}:
        raise ConfigError("local_model server flash_attention is invalid")

    if request.get("stream") is not False or request.get("max_retries") != 0:
        raise ConfigError("local approval requests must be non-streaming with zero retries")
    if request.get("structured_output") is not True:
        raise ConfigError("local approval requests require structured output")
    temperature = _finite_number(request, "temperature", minimum=0.0)
    top_p = _finite_number(request, "top_p", minimum=0.0, maximum=1.0)
    seed = _integer(request, "seed", minimum=-(2**31), maximum=2**31 - 1)
    max_tokens = _integer(request, "max_output_tokens", minimum=1, maximum=1_000_000)
    timeout = _finite_number(request, "timeout_seconds", minimum=0.001, maximum=3600.0)

    base_url = local["base_url"].rstrip("/")
    return LocalApprovalSettings(
        base_url=base_url,
        responses_url=f"{base_url}/responses",
        model_id=local["model_id"],
        model_path=local["model_path"],
        model_sha256=model_sha256,
        quantization=quantization,
        binary=binary,
        host=host,
        port=port,
        context_size=context_size,
        gpu_layers=gpu_layers,
        flash_attention=flash,
        parallel=parallel,
        metrics=metrics,
        slots=slots,
        timeout_seconds=timeout,
        temperature=temperature,
        top_p=top_p,
        seed=seed,
        max_output_tokens=max_tokens,
    )


class LocalApprovalClient:
    """Send one tool-free static decision request with no automatic retries."""

    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.settings = settings_from_config(config)

    def build_request(self, payload: StaticApprovalPayload) -> dict[str, Any]:
        try:
            validate_static_payload(payload)
        except EvidenceError as exc:
            raise ConfigError("static approval payload failed the final sink check") from exc
        logical = copy.deepcopy(payload.logical_payload)
        policy = logical.get("guardian_policy")
        instructions = logical.get("instructions")
        task_input = logical.get("input")
        schema = logical.get("output_schema")
        if (
            not isinstance(policy, str)
            or not policy
            or not isinstance(instructions, str)
            or not instructions
            or not isinstance(task_input, list)
            or not isinstance(schema, dict)
        ):
            raise ConfigError("static approval payload does not match schema v1")
        request: dict[str, Any] = {
            "model": self.settings.model_id,
            "instructions": f"{instructions}\n\nGuardian policy follows exactly:\n{policy}",
            "input": task_input,
            "stream": False,
            "temperature": self.settings.temperature,
            "top_p": self.settings.top_p,
            "seed": self.settings.seed,
            "max_output_tokens": self.settings.max_output_tokens,
            # b10333-specific passthrough to the Chat Completions parser.
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "rondo_static_approval_v1",
                    "strict": True,
                    "schema": schema,
                },
            },
        }
        return request

    def decide(self, payload: StaticApprovalPayload) -> dict[str, Any]:
        body = json.dumps(
            self.build_request(payload),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers = self._headers(content_type=True)
        request = urllib.request.Request(
            self.settings.responses_url,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with _NO_REDIRECT_OPENER.open(
                request, timeout=self.settings.timeout_seconds
            ) as response:
                if response.geturl() != self.settings.responses_url:
                    raise ServiceUnavailableError(
                        "local approval endpoint response URL changed"
                    )
                if response.status != 200:
                    raise ServiceUnavailableError("local approval endpoint returned a non-200 status")
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ServiceUnavailableError("local approval service is unavailable") from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise StructuredOutputError("local approval response exceeds the size limit")
        try:
            envelope = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise StructuredOutputError("local approval response is not valid JSON") from exc
        return _parse_response(envelope, expected_model=self.settings.model_id)

    def verify_service_identity(
        self,
        expected_model_path: Path,
        *,
        expected_build: int,
        expected_commit: str,
    ) -> None:
        """Bind a configured endpoint to the pinned build, model path, and alias."""

        parsed = urllib.parse.urlsplit(self.settings.base_url)
        props_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/props", "", ""))
        props = self._get_json(props_url)
        if not isinstance(props, Mapping):
            raise StructuredOutputError("local approval service props are invalid")
        build_info = props.get("build_info")
        reported_path = props.get("model_path")
        try:
            path_matches = (
                isinstance(reported_path, str)
                and Path(reported_path).is_absolute()
                and Path(reported_path).resolve(strict=False)
                == expected_model_path.resolve(strict=True)
            )
        except OSError:
            path_matches = False
        if (
            not isinstance(build_info, str)
            or re.search(rf"(?<!\d){expected_build}(?!\d)", build_info) is None
            or expected_commit[:8] not in build_info
            or not path_matches
        ):
            raise StructuredOutputError("local approval service identity differs")

        models = self._get_json(f"{self.settings.base_url}/models")
        data = models.get("data") if isinstance(models, Mapping) else None
        if (
            not isinstance(data, list)
            or len(data) != 1
            or not isinstance(data[0], Mapping)
            or data[0].get("id") != self.settings.model_id
        ):
            raise StructuredOutputError("local approval model alias differs")

    def _headers(self, *, content_type: bool = False) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if content_type:
            headers["Content-Type"] = "application/json"
        secret = load_local_model_secret(self.config)
        if secret is not None:
            headers["Authorization"] = f"Bearer {secret[1]}"
        return headers

    def _get_json(self, url: str) -> Any:
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with _NO_REDIRECT_OPENER.open(
                request, timeout=self.settings.timeout_seconds
            ) as response:
                if response.geturl() != url or response.status != 200:
                    raise ServiceUnavailableError(
                        "local approval identity endpoint is unavailable"
                    )
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ServiceUnavailableError(
                "local approval identity endpoint is unavailable"
            ) from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise StructuredOutputError("local approval identity response exceeds the size limit")
        try:
            return json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise StructuredOutputError(
                "local approval identity response is not valid JSON"
            ) from exc


def _parse_response(envelope: Any, *, expected_model: str) -> dict[str, Any]:
    if not isinstance(envelope, Mapping) or envelope.get("status") != "completed":
        raise StructuredOutputError("local approval response is not completed")
    if envelope.get("model") != expected_model:
        raise StructuredOutputError("local approval response model identity differs")
    output = envelope.get("output")
    if not isinstance(output, list):
        raise StructuredOutputError("local approval response output is invalid")
    texts: list[str] = []
    for item in output:
        if not isinstance(item, Mapping):
            raise StructuredOutputError("local approval response item is invalid")
        if item.get("type") != "message" or item.get("role") != "assistant":
            raise StructuredOutputError("local approval response contains a non-message output")
        content = item.get("content")
        if not isinstance(content, list):
            raise StructuredOutputError("local approval message content is invalid")
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "output_text":
                raise StructuredOutputError("local approval response contains non-text content")
            text = part.get("text")
            if not isinstance(text, str):
                raise StructuredOutputError("local approval output_text is invalid")
            texts.append(text)
    if len(texts) != 1:
        raise StructuredOutputError("local approval response must contain exactly one output_text")
    try:
        decision = json.loads(texts[0])
    except json.JSONDecodeError as exc:
        raise StructuredOutputError("local approval output_text is not JSON") from exc
    if not isinstance(decision, Mapping):
        raise StructuredOutputError("local approval decision must be an object")
    try:
        return validate_static_decision(decision)
    except EvidenceError as exc:
        raise StructuredOutputError("local approval decision does not match schema v1") from exc


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


_NO_REDIRECT_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirectHandler(),
)


def _nonempty_string(table: Mapping[str, Any], key: str, label: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{label} {key} must be a non-empty string")
    return value


def _boolean(table: Mapping[str, Any], key: str) -> bool:
    value = table.get(key)
    if not isinstance(value, bool):
        raise ConfigError(f"local_model {key} must be a boolean")
    return value


def _integer(
    table: Mapping[str, Any], key: str, *, minimum: int, maximum: int
) -> int:
    value = table.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not minimum <= value <= maximum:
        raise ConfigError(f"local_model {key} is outside its allowed range")
    return value


def _finite_number(
    table: Mapping[str, Any],
    key: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    value = table.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"local_model {key} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise ConfigError(f"local_model {key} is outside its allowed range")
    return result


def resolve_config_path(config: RuntimeConfig, value: str) -> Path:
    """Resolve a configured machine path without expanding shell syntax."""

    path = Path(value)
    return path if path.is_absolute() else config.paths.common_root / path
