"""Bounded DeepSeek V4 token recount using the official tokenizer and Rust prompt renderer."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MAX_INPUT_BYTES = 1024 * 1024
MAX_RENDER_BYTES = 256 * 1024
METHOD = "deepseek_v4_official_tokenizer_plus_b1_chat_envelope_v2"
# The provider reports a fixed 21-token chat envelope above the official rendered messages.
# B1 observed the same delta on all nine usage-present A/B/C synthetic/public calls, while every
# completion recount matched exactly. This is request framing, not a content- or task-dependent
# adjustment.
PROVIDER_CHAT_ENVELOPE_TOKENS = 21
TASK_ARGUMENT = {"A": "scalar", "B": "direct-gate", "C": "five-dimension"}
BEGIN = "<｜begin▁of▁sentence｜>"
USER = "<｜User｜>"
ASSISTANT = "<｜Assistant｜>"


class TokenRecountError(RuntimeError):
    """The bounded request, frozen renderer, or official tokenizer is invalid."""


def _strict_object(body: bytes) -> dict[str, Any]:
    if not body or len(body) > MAX_INPUT_BYTES:
        raise TokenRecountError("recount_input_size_invalid")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in values:
            if key in result:
                raise TokenRecountError("recount_json_duplicate_key")
            result[key] = value
        return result

    try:
        value = json.loads(body, object_pairs_hook=pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TokenRecountError("recount_json_invalid") from exc
    if not isinstance(value, dict):
        raise TokenRecountError("recount_json_not_object")
    return value


def _safe_file(path: Path, maximum: int) -> None:
    if path.is_symlink() or not path.is_file():
        raise TokenRecountError("recount_file_unsafe")
    size = path.stat().st_size
    if not 0 < size <= maximum:
        raise TokenRecountError("recount_file_size_invalid")


def _render_messages(
    request: Mapping[str, Any],
    *,
    renderer: Path,
    descriptor: Path,
) -> dict[str, str]:
    task = request.get("task")
    packet = request.get("packet")
    if task not in TASK_ARGUMENT or not isinstance(packet, Mapping):
        raise TokenRecountError("recount_request_invalid")
    completed = subprocess.run(
        (
            str(renderer),
            "--descriptor",
            str(descriptor),
            "--task",
            TASK_ARGUMENT[str(task)],
            "--render-messages",
        ),
        input=json.dumps(
            dict(packet),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=10,
        check=False,
        env={
            name: os.environ[name]
            for name in ("PATH", "LANG", "LC_ALL")
            if name in os.environ
        },
    )
    if completed.returncode != 0 or len(completed.stdout) > MAX_RENDER_BYTES:
        raise TokenRecountError("recount_renderer_failed")
    value = _strict_object(completed.stdout)
    if set(value) != {"system", "user"} or not all(
        isinstance(value[name], str) and value[name] for name in ("system", "user")
    ):
        raise TokenRecountError("recount_renderer_output_invalid")
    return {"system": value["system"], "user": value["user"]}


def recount(
    request: Mapping[str, Any],
    *,
    tokenizer: Any,
    tokenizer_config: Mapping[str, Any],
    renderer: Path,
    descriptor: Path,
) -> dict[str, Any]:
    if (
        set(request) != {"schema", "task", "packet", "response_text"}
        or request.get("schema")
        != "rondo-publication-critic-plan100-token-recount-request@v1"
    ):
        raise TokenRecountError("recount_request_invalid")
    response_text = request.get("response_text")
    if not isinstance(response_text, str):
        raise TokenRecountError("recount_response_unavailable")
    if (
        tokenizer_config.get("tokenizer_class") != "LlamaTokenizerFast"
        or tokenizer_config.get("add_bos_token") is not False
        or tokenizer_config.get("add_eos_token") is not False
        or tokenizer_config.get("bos_token", {}).get("content") != BEGIN
    ):
        raise TokenRecountError("recount_tokenizer_config_invalid")
    messages = _render_messages(request, renderer=renderer, descriptor=descriptor)
    prompt = f"{BEGIN}{messages['system']}{USER}{messages['user']}{ASSISTANT}"
    prompt_tokens = (
        len(tokenizer.encode(prompt, add_special_tokens=False).ids)
        + PROVIDER_CHAT_ENVELOPE_TOKENS
    )
    completion_tokens = len(
        tokenizer.encode(response_text, add_special_tokens=False).ids
    )
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "method": METHOD,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tokenizer-json", type=Path, required=True)
    parser.add_argument("--tokenizer-config", type=Path, required=True)
    parser.add_argument("--renderer", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for path, maximum in (
        (args.tokenizer_json, 16 * 1024 * 1024),
        (args.tokenizer_config, 64 * 1024),
        (args.renderer, 128 * 1024 * 1024),
        (args.descriptor, 1024 * 1024),
    ):
        _safe_file(path, maximum)
    request = _strict_object(sys.stdin.buffer.read(MAX_INPUT_BYTES + 1))
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise TokenRecountError("recount_dependency_unavailable") from exc
    tokenizer = Tokenizer.from_file(str(args.tokenizer_json))
    tokenizer_config = _strict_object(args.tokenizer_config.read_bytes())
    result = recount(
        request,
        tokenizer=tokenizer,
        tokenizer_config=tokenizer_config,
        renderer=args.renderer,
        descriptor=args.descriptor,
    )
    sys.stdout.write(
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
