"""Count-only exact input-token census over the archived real `E_final` set.

Plan 023 measured one real `E_final` at 5,313 input tokens against the frozen
4k contract.  This module answers the same question for the whole archived set
**without generating a single token**: it rebuilds the real Local request for
every archived `E_final` and asks the frozen b10333 server for the exact
input-token count of that request.

`POST /v1/responses/input_tokens` runs the same Responses -> Chat Completions
conversion, the same Jinja chat template and the same tokenizer as the real
`/v1/responses` path; for a string prompt `tokenize_input_prompts(vocab, mctx,
prompt, true, true)[0]` and `tokenize_mixed(vocab, prompt, true, true)` are the
same call, so these counts are exact for the real request, not an estimate.

The census reuses the existing production evidence reader, Guardian meta
validator, request builder, shared watchdog lease and serving contract.  It adds
no provenance, attestation or qualification machinery: it never generates
tokens, never writes approval or qualification evidence, and never reads
`.env.local` (the server is started with the sanitized launcher environment, so
no API key is involved on either side).  Only stable digests, token counts and
fit results leave this module; evidence bodies and rendered prompts do not.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .. import runtime_bridge
from ..config import ConfigError, RepoPaths, RuntimeConfig, load_runtime_config
from ..evidence import StaticApprovalPayload, build_static_payload
from ..exit_codes import CONFIG_ERROR, INFRA_ERROR, SUCCESS
from ..terminal_bench.live import (
    TerminalBenchRunError,
    _read_safe_evidence_file as read_production_evidence_file,
    _validate_guardian_meta as validate_production_guardian_meta,
)
from . import model_backed
from .client import (
    _NO_REDIRECT_OPENER,
    LocalApprovalClient,
    LocalApprovalSettings,
    settings_from_config,
)
from .launcher import (
    LLAMA_CPP_CUDA_CAPABILITY,
    _get_json,
    _sanitized_environment,
    build_serve_command,
    inspect_runtime,
    model_path as resolve_model,
    serve_config_sha256,
)
from .qualification import (
    NvidiaSmiSampler,
    QualificationError,
    _await_ready,
    _foreign_compute_pids,
    _identity,
    _lease,
    _load_selector,
    _log_diagnostics,
    _port_released,
    _prepare_private_directory,
    _remove_private_directory,
    _require_free_port,
    _require_watchdog,
    _service_context_size,
    _stop_process,
)


CENSUS_SCHEMA_VERSION = 1
# The archived real set is closed and known; a different size means the input is
# no longer the complete set this census claims to describe.
EXPECTED_EVIDENCE_COUNT = 47
# Plan 023 measured this exact count for the selector-bound `E_final` through
# the real request path.  A different value means this census is not measuring
# the same thing and must not publish an overall conclusion.
ANCHOR_INPUT_TOKENS = 5_313
CENSUS_MAX_OUTPUT_TOKENS = 512
CONTEXT_WINDOWS: tuple[tuple[str, int], ...] = (("4k", 4096), ("8k", 8192))
RESULT_RELATIVE_PATH = "eval/results/baselines/local-approval-exact-token-census-v1.json"
PERCENTILE_METHOD = (
    "nearest-rank on ascending input_tokens: index = ceil(p / 100 * n), 1-based"
)

_EVIDENCE_GLOB = "eval-data/runs/*/guardian-evidence/*/E_final.json"
_RUN_LEDGER_RELATIVE_PATH = "eval/results/runs.jsonl"
_COUNT_ENDPOINT_SUFFIX = "/responses/input_tokens"
_MAX_COUNT_RESPONSE_BYTES = 65_536
_WATCHDOG_RECHECK_EVERY = 10
# The only refusal this census attributes to the request itself.  b10333 raises
# `invalid_argument` from its Responses adapter for an item shape it cannot map,
# which `/v1/responses` refuses identically.  Every other status - including the
# catch-all `500 server_error`, which any internal fault also produces - fails
# the whole census instead of being recorded as a property of one sample.
_STRUCTURAL_REFUSAL = (400, "invalid_request_error")
# The two bounded points at which this census works through the archived set.
# A generic failure in either - counting, or the health probe that follows a
# refusal - stops the whole run; naming which stage it was, which archive was
# in flight and how many archives already had an exact count is the whole of
# the diagnostic, and none of it is derived from evidence text.
_STAGE_ANCHOR_COUNT = "anchor_count"
_STAGE_ARCHIVE_COUNT = "archive_count"


class CensusError(RuntimeError):
    """Fail-closed census error carrying a stable, non-sensitive code."""

    exit_code = INFRA_ERROR

    def __init__(self, code: str, facts: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.facts = dict(facts or {})


class RequestRejected(RuntimeError):
    """b10333's Responses adapter cannot map this request's item shapes.

    This is a property of the archived evidence rather than of the service: the
    real `/v1/responses` decision path shares the same adapter and refuses the
    same request.  Such an input is recorded and the census keeps going, but it
    has no exact token count, so the census as a whole ends incomplete and
    publishes no baseline.  Every refusal is followed by a fresh synthetic probe
    so a failing service can never be recorded as a set of bad inputs.
    """

    def __init__(self, facts: dict[str, Any]) -> None:
        super().__init__("request_rejected")
        self.facts = dict(facts)


@dataclass(frozen=True)
class EvidenceInput:
    """One archived `E_final` that already passed the production checks.

    Only `e_final_sha256` reaches the published result; the path and the payload
    stay in memory for the duration of the run.
    """

    relative_path: str
    e_final_sha256: str
    request_shape: str
    payload: StaticApprovalPayload


def _expected_guardian_identities(config: RuntimeConfig) -> dict[str, tuple[str, str]]:
    """Read the expected Guardian model/effort per run from the tracked ledger.

    The ledger is the same independent tracked record the qualification selector
    cross-checks against, so the expected identity does not come from the very
    files being validated.  This is a lookup, not a second provenance system.
    """

    path = config.paths.worktree_root / _RUN_LEDGER_RELATIVE_PATH
    if path.is_symlink() or not path.is_file():
        raise CensusError("evidence_run_ledger_missing")
    identities: dict[str, tuple[str, str]] = {}
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise CensusError("evidence_run_ledger_invalid")
                run_id = record.get("run_id")
                configuration = record.get("config")
                if not isinstance(run_id, str) or not isinstance(configuration, dict):
                    continue
                model = configuration.get("effective_guardian_model")
                effort = configuration.get("guardian_effort")
                if not isinstance(model, str) or not isinstance(effort, str):
                    continue
                if record.get("artifacts") != f"eval-data/runs/{run_id}":
                    continue
                existing = identities.get(run_id)
                if existing is not None and existing != (model, effort):
                    raise CensusError("evidence_run_ledger_conflict", {"run_id": run_id})
                identities[run_id] = (model, effort)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CensusError("evidence_run_ledger_invalid") from exc
    return identities


def collect_evidence_inputs(
    config: RuntimeConfig, *, expected_count: int | None = None
) -> list[EvidenceInput]:
    """Build the complete, de-duplicated input set or refuse to continue.

    Every archived `E_final` is taken, regardless of the outcome of the run that
    produced it: selecting by run outcome, length or fit would silently change
    what the published distribution describes.
    """

    expected = EXPECTED_EVIDENCE_COUNT if expected_count is None else expected_count
    root = config.paths.common_root
    ledger = _expected_guardian_identities(config)
    paths = sorted(root.glob(_EVIDENCE_GLOB))
    if len(paths) != expected:
        raise CensusError(
            "evidence_set_size_unexpected",
            {"expected": expected, "found": len(paths)},
        )
    inputs: list[EvidenceInput] = []
    seen_digests: set[str] = set()
    seen_review_ids: set[str] = set()
    for path in paths:
        relative = path.relative_to(root)
        run_id = relative.parts[2]
        expected_identity = ledger.get(run_id)
        if expected_identity is None:
            raise CensusError("evidence_run_record_missing", {"run_id": run_id})
        meta_path = path.with_name("meta.json")
        try:
            before = os.lstat(path)
            meta_before = os.lstat(meta_path)
            e_final_bytes = read_production_evidence_file(root, path)
            meta_bytes = read_production_evidence_file(root, meta_path)
            after = os.lstat(path)
            meta_after = os.lstat(meta_path)
        except TerminalBenchRunError as exc:
            raise CensusError("evidence_source_unsafe", {"run_id": run_id}) from exc
        except OSError as exc:
            raise CensusError("evidence_source_missing", {"run_id": run_id}) from exc
        if _identity(before) != _identity(after) or _identity(meta_before) != _identity(
            meta_after
        ):
            raise CensusError("evidence_source_changed_while_reading", {"run_id": run_id})
        try:
            e_final = json.loads(e_final_bytes.decode("utf-8"))
            meta = json.loads(meta_bytes.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise CensusError("evidence_source_unparsable", {"run_id": run_id}) from exc
        review_id = meta.get("review_id") if isinstance(meta, dict) else None
        if not isinstance(review_id, str) or not review_id:
            raise CensusError("evidence_meta_invalid", {"run_id": run_id})
        try:
            validate_production_guardian_meta(
                meta,
                review_id=review_id,
                expected_model=expected_identity[0],
                expected_effort=expected_identity[1],
            )
        except TerminalBenchRunError as exc:
            raise CensusError("evidence_meta_invalid", {"run_id": run_id}) from exc
        try:
            payload = build_static_payload(e_final)
        except Exception as exc:
            raise CensusError("evidence_source_unparsable", {"run_id": run_id}) from exc
        digest = hashlib.sha256(e_final_bytes).hexdigest()
        if digest in seen_digests:
            raise CensusError("evidence_duplicate_content", {"e_final_sha256": digest})
        if review_id in seen_review_ids:
            raise CensusError("evidence_duplicate_review_id", {"run_id": run_id})
        seen_digests.add(digest)
        seen_review_ids.add(review_id)
        inputs.append(
            EvidenceInput(
                relative_path=relative.as_posix(),
                e_final_sha256=digest,
                request_shape=payload.policy_identity.request_shape,
                payload=payload,
            )
        )
    return inputs


def select_anchor(config: RuntimeConfig, inputs: Sequence[EvidenceInput]) -> EvidenceInput:
    """Return the `E_final` Plan 023 already measured through the real path."""

    selector = _load_selector(config)
    for item in inputs:
        if (
            item.relative_path == selector["relative_path"]
            and item.e_final_sha256 == selector["e_final_sha256"]
        ):
            return item
    raise CensusError("anchor_not_in_evidence_set")


def count_input_tokens(
    settings: LocalApprovalSettings,
    body: bytes,
    *,
    opener: Any = _NO_REDIRECT_OPENER,
    code: str = "count_endpoint_unavailable",
) -> int:
    """Ask the running frozen server for the exact input-token count.

    llama.cpp answers a refused request with its own structured error object.
    Only its stable parts leave this function - HTTP status, error type and a
    digest of the message.  The free-text message itself is never reported or
    persisted: no filter can prove that a server-composed string does not quote
    the evidence that produced it.
    """

    url = f"{settings.base_url}{_COUNT_ENDPOINT_SUFFIX}"
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=settings.timeout_seconds) as response:
            if response.geturl() != url or response.status != 200:
                raise CensusError(code, {"http_status": response.status})
            raw = response.read(_MAX_COUNT_RESPONSE_BYTES + 1)
    except CensusError:
        raise
    except urllib.error.HTTPError as exc:
        facts = _http_error_facts(exc)
        if (facts.get("http_status"), facts.get("error_type")) == _STRUCTURAL_REFUSAL:
            raise RequestRejected(facts) from exc
        raise CensusError(code, facts) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CensusError(code, {"transport": type(exc).__name__}) from exc
    if len(raw) > _MAX_COUNT_RESPONSE_BYTES:
        raise CensusError("count_response_invalid")
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CensusError("count_response_invalid") from exc
    tokens = value.get("input_tokens") if isinstance(value, dict) else None
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
        raise CensusError("count_response_invalid")
    return tokens


def _http_error_facts(error: urllib.error.HTTPError) -> dict[str, Any]:
    """Keep only the stable, request-independent parts of a server error.

    The message digest still separates one refusal class from another across
    runs, which is all the census needs, without letting server-composed text
    reach the console or a tracked file.
    """

    facts: dict[str, Any] = {"http_status": error.code}
    try:
        payload = json.loads(error.read(_MAX_COUNT_RESPONSE_BYTES + 1))
    except Exception:
        return facts
    detail = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        return facts
    for key in ("type", "code"):
        value = detail.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            facts[f"error_{key}"] = value
    message = detail.get("message")
    if isinstance(message, str):
        facts["message_sha256"] = hashlib.sha256(message.encode("utf-8")).hexdigest()
    return facts


def _counting_stage_facts(
    stage: str, e_final_sha256: str, counted_before_failure: int
) -> dict[str, Any]:
    """Locate one counting failure without describing what was being counted.

    All three values are already published parts of a census result - the stage
    is one of two fixed names, the digest identifies the archive the way every
    record does, and the count is how many distinct archives had an exact count
    when the failure happened.  No path, request, evidence text or free-form
    trace is added, and naming the stage does not make an endpoint failure a
    property of the archive that happened to be in flight.
    """

    return {
        "stage": stage,
        "e_final_sha256": e_final_sha256,
        "counted_before_failure": counted_before_failure,
    }


def _probe_count_endpoint(
    settings: LocalApprovalSettings,
    builder: LocalApprovalClient,
    *,
    count: Callable[[LocalApprovalSettings, bytes], int] | None = None,
) -> None:
    """Prove the count endpoint still answers this request shape.

    The probe body is built by the same request builder from a synthetic
    `E_final`, so an endpoint-level failure is diagnosable without any archived
    evidence reaching an error report.  It runs before the first evidence
    request and again after every refusal, so a service that stopped working
    cannot be recorded as a run of unservable inputs.
    """

    payload = build_static_payload(
        {
            "instructions": "census endpoint probe policy",
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "probe"}]}
            ],
        }
    )
    body = json.dumps(
        builder.build_request(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if count is None:
        count_input_tokens(settings, body, code="count_endpoint_probe_failed")
        return
    try:
        count(settings, body)
    except (CensusError, RequestRejected) as exc:
        raise CensusError(
            "count_endpoint_probe_failed", getattr(exc, "facts", {})
        ) from exc


def percentile(sorted_counts: Sequence[int], percent: int) -> int:
    """Nearest-rank percentile; see `PERCENTILE_METHOD` for the exact rule."""

    if not sorted_counts:
        raise CensusError("summary_input_empty")
    index = math.ceil(percent / 100 * len(sorted_counts))
    return sorted_counts[max(1, min(index, len(sorted_counts))) - 1]


def fit_results(input_tokens: int) -> dict[str, bool]:
    """Decide each context window on `input_tokens + max_output_tokens`."""

    required = input_tokens + CENSUS_MAX_OUTPUT_TOKENS
    return {name: required <= size for name, size in CONTEXT_WINDOWS}


def summarize(
    records: Sequence[dict[str, Any]], *, request_shapes: Mapping[str, int]
) -> dict[str, Any]:
    """Summarise the whole set, keeping counted and refused inputs apart.

    Every archived input appears in `evidence_count`.  Token statistics and
    context coverage can only describe the inputs the frozen runtime accepted,
    so they are reported over `counted` and labelled as such.  A census with any
    refusal is incomplete: these statistics never stand for the whole set.
    """

    counted = [record for record in records if record["status"] == "counted"]
    if not counted:
        raise CensusError("no_input_was_counted")
    counts = sorted(int(record["input_tokens"]) for record in counted)
    refusals: dict[str, int] = {}
    for record in records:
        if record["status"] == "refused":
            detail = record["refusal"]
            reason = (
                f"{detail.get('http_status')} {detail.get('error_type')} "
                f"{detail.get('message_sha256')}"
            )
            refusals[reason] = refusals.get(reason, 0) + 1
    windows: dict[str, Any] = {}
    for name, size in CONTEXT_WINDOWS:
        fits = sum(1 for record in counted if record["fits"][name])
        windows[name] = {
            "context_size": size,
            "fits": fits,
            "does_not_fit": len(counted) - fits,
        }
    return {
        "evidence_count": len(records),
        "counted": len(counted),
        "refused": len(records) - len(counted),
        "refusal_classes": dict(sorted(refusals.items())),
        "max_output_tokens": CENSUS_MAX_OUTPUT_TOKENS,
        "percentile_method": PERCENTILE_METHOD,
        "statistics_scope": "counted inputs only",
        "input_tokens": {
            "min": counts[0],
            "p50": percentile(counts, 50),
            "p90": percentile(counts, 90),
            "p95": percentile(counts, 95),
            "max": counts[-1],
        },
        "request_shapes": dict(sorted(request_shapes.items())),
        "context_windows": windows,
    }


def _canonical_digest(value: Any) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_document(
    *,
    identity: dict[str, Any],
    anchor: dict[str, Any],
    records: Iterable[dict[str, Any]],
    request_shapes: Mapping[str, int],
) -> dict[str, Any]:
    """Build the stable machine-readable result, ordered by content digest.

    Ordering by `e_final_sha256` instead of filesystem order keeps two runs over
    the same input set byte-identical, which is what makes the repeat run a
    check on the measurement rather than on the traversal order.  The top-level
    `status` is `complete` only when every input has an exact count.
    """

    ordered = sorted(records, key=lambda record: record["e_final_sha256"])
    if len({record["e_final_sha256"] for record in ordered}) != len(ordered):
        raise CensusError("record_digest_collision")
    missing = [record for record in ordered if record["status"] != "counted"]
    document = {
        "schema_version": CENSUS_SCHEMA_VERSION,
        "purpose": (
            "exact input-token census of the complete archived real Guardian "
            "E_final set, counted with the frozen GGUF tokenizer and template"
        ),
        "status": "incomplete" if missing else "complete",
        "missing_counts": len(missing),
        "identity": identity,
        "anchor": anchor,
        "records": ordered,
        "summary": summarize(ordered, request_shapes=request_shapes),
    }
    document["digest"] = _canonical_digest(document)
    return document


def write_document(path: Path, document: dict[str, Any]) -> Path:
    """Write the result, refusing to publish an incomplete run as the baseline."""

    if document.get("status") != "complete" and path.name == Path(RESULT_RELATIVE_PATH).name:
        raise CensusError("incomplete_census_must_not_be_published")
    raw = json.dumps(document, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
    raw += b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("census result write did not progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    return path


def _verify_service_identity(
    settings: LocalApprovalSettings,
    model: Path,
    props: Any,
    http_get: Callable[..., Any],
) -> None:
    """Bind the running service to the frozen build, GGUF and model alias."""

    reported = props.get("model_path") if isinstance(props, dict) else None
    try:
        path_matches = (
            isinstance(reported, str)
            and Path(reported).is_absolute()
            and Path(reported).resolve(strict=False) == model.resolve(strict=True)
        )
    except OSError:
        path_matches = False
    if (
        not isinstance(props, dict)
        or props.get("build_info") != model_backed.service_build_info(settings)
        or not path_matches
    ):
        raise CensusError("service_identity_differs")
    try:
        models = http_get(f"{settings.base_url}/models", timeout=10.0)
    except Exception as exc:
        raise CensusError("service_models_unavailable") from exc
    data = models.get("data") if isinstance(models, dict) else None
    if (
        not isinstance(data, list)
        or len(data) != 1
        or not isinstance(data[0], dict)
        or data[0].get("id") != settings.model_id
    ):
        raise CensusError("service_model_alias_differs")


def _teardown(
    process: subprocess.Popen[Any] | None,
    settings: LocalApprovalSettings,
    private_root: Path | None,
    log_path: Path | None,
) -> tuple[dict[str, bool], str | None]:
    """Stop only this task's own server and remove its private artifacts."""

    stopped = True if process is None else _stop_process(process)
    log_text: str | None = None
    if log_path is not None:
        try:
            log_text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log_text = None
    released = _port_released(settings.host, settings.port)
    removed = True if private_root is None else _remove_private_directory(private_root)
    return (
        {
            "server_stopped": stopped,
            "port_released": released,
            "private_artifacts_removed": removed,
        },
        log_text,
    )


def run_census(
    config: RuntimeConfig,
    *,
    output_path: Path,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    watchdog_factory: Callable[[], runtime_bridge.WatchdogProof] | None = None,
    gpu_sampler: Any | None = None,
    http_get: Callable[..., Any] = _get_json,
    clock: Callable[[], float] = time.monotonic,
    count: Callable[[LocalApprovalSettings, bytes], int] | None = None,
) -> dict[str, Any]:
    """Run one count-only census over the complete archived `E_final` set."""

    settings = settings_from_config(config)
    model_backed.require_qualification_contract(config, settings)
    if settings.max_output_tokens != CENSUS_MAX_OUTPUT_TOKENS:
        raise CensusError("output_budget_unexpected", {"expected": CENSUS_MAX_OUTPUT_TOKENS})
    inputs = collect_evidence_inputs(config)
    anchor = select_anchor(config, inputs)
    # The real request builder is reused verbatim, so the counted bytes are the
    # bytes the real decision path would have sent.
    builder = LocalApprovalClient(config)
    bodies = {
        item.e_final_sha256: json.dumps(
            builder.build_request(item.payload),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        for item in inputs
    }
    model = resolve_model(config, settings)

    watchdog = _lease(watchdog_factory)
    runtime = inspect_runtime(config, settings)
    if not runtime.ok or runtime.binary is None or runtime.identity_sha256 is None:
        raise CensusError("runtime_not_ready")
    if runtime.capability != LLAMA_CPP_CUDA_CAPABILITY:
        raise CensusError("runtime_capability_unexpected")

    sampler = gpu_sampler if gpu_sampler is not None else NvidiaSmiSampler()
    if sampler.compute_process_pids():
        raise CensusError("gpu_not_exclusive")
    _require_free_port(settings.host, settings.port)

    counter = count or count_input_tokens
    # Everything that can still fail happens before the private directory
    # exists, so no failure path can leave one behind.
    command = build_serve_command(config, settings, runtime.binary)
    serving_config = serve_config_sha256(config, settings)
    private_root = _prepare_private_directory(config, prefix="census")
    log_path = private_root / "server.log"
    process: subprocess.Popen[Any] | None = None
    failure: CensusError | QualificationError | None = None
    records: list[dict[str, Any]] = []
    anchor_tokens = 0
    try:
        _require_watchdog(watchdog)
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            process = popen(
                command,
                env=_sanitized_environment(),
                stdout=descriptor,
                stderr=subprocess.STDOUT,
            )
        finally:
            os.close(descriptor)
        props = _await_ready(process, settings, http_get, clock)
        _require_watchdog(watchdog)
        _service_context_size(props)
        _verify_service_identity(settings, model, props, http_get)
        foreign = _foreign_compute_pids(sampler, process.pid)
        if foreign:
            raise CensusError("gpu_not_exclusive", {"foreign_compute_pids": foreign})

        _probe_count_endpoint(settings, builder, count=count)
        # The anchor is counted first: if it does not reproduce the already
        # measured 5,313 tokens, this census is not measuring the real request
        # path and the other 46 counts would mean nothing.
        anchor_facts = _counting_stage_facts(
            _STAGE_ANCHOR_COUNT, anchor.e_final_sha256, 0
        )
        try:
            anchor_tokens = counter(settings, bodies[anchor.e_final_sha256])
        except RequestRejected as rejected:
            raise CensusError(
                "anchor_request_rejected", {**rejected.facts, **anchor_facts}
            ) from rejected
        except CensusError as error:
            raise CensusError(error.code, {**error.facts, **anchor_facts}) from error
        if anchor_tokens != ANCHOR_INPUT_TOKENS:
            raise CensusError(
                "anchor_token_count_mismatch",
                {"expected": ANCHOR_INPUT_TOKENS, "observed": anchor_tokens},
            )
        # Archives that already have an exact count, so a later failure can say
        # how far the run got.  The anchor is counted above and reused below,
        # so it belongs here rather than being counted twice.
        counted: set[str] = {anchor.e_final_sha256}
        for index, item in enumerate(inputs, start=1):
            record: dict[str, Any] = {"e_final_sha256": item.e_final_sha256}
            try:
                tokens = (
                    anchor_tokens
                    if item.e_final_sha256 == anchor.e_final_sha256
                    else counter(settings, bodies[item.e_final_sha256])
                )
            except RequestRejected as rejected:
                record["status"] = "refused"
                record["refusal"] = rejected.facts
                # Prove the refusal was about this request, not the service.
                # A probe that fails generically is still a run-level failure,
                # and it is located the same way a failed count would be.
                try:
                    _probe_count_endpoint(settings, builder, count=count)
                except CensusError as error:
                    raise CensusError(
                        error.code,
                        {
                            **error.facts,
                            **_counting_stage_facts(
                                _STAGE_ARCHIVE_COUNT, item.e_final_sha256, len(counted)
                            ),
                        },
                    ) from error
            except CensusError as error:
                # Still fail-closed: a generic failure stops the census instead
                # of being recorded against this archive as a refusal.
                raise CensusError(
                    error.code,
                    {
                        **error.facts,
                        **_counting_stage_facts(
                            _STAGE_ARCHIVE_COUNT, item.e_final_sha256, len(counted)
                        ),
                    },
                ) from error
            else:
                counted.add(item.e_final_sha256)
                record["status"] = "counted"
                record["input_tokens"] = tokens
                record["fits"] = fit_results(tokens)
            records.append(record)
            if index % _WATCHDOG_RECHECK_EVERY == 0:
                _require_watchdog(watchdog)
        _require_watchdog(watchdog)
        foreign = _foreign_compute_pids(sampler, process.pid)
        if foreign:
            raise CensusError("gpu_not_exclusive", {"foreign_compute_pids": foreign})
    except (CensusError, QualificationError) as error:
        failure = error
    finally:
        cleanup, log_text = _teardown(process, settings, private_root, log_path)

    if failure is not None:
        facts = dict(failure.facts)
        facts["cleanup"] = cleanup
        if log_text is not None:
            facts.update(_log_diagnostics(log_text))
        raise type(failure)(failure.code, facts) from failure
    if not all(cleanup.values()):
        raise CensusError("cleanup_incomplete", {"cleanup": cleanup})

    identity = {
        "runtime_relative_path": model_backed.CUDA_RUNTIME_RELATIVE_PATH,
        "runtime_identity_sha256": runtime.identity_sha256,
        "service_build_info": model_backed.service_build_info(settings),
        "model_relative_path": model_backed.MODEL_RELATIVE_PATH,
        "model_sha256": settings.model_sha256,
        "chat_template_sha256": settings.chat_template_sha256,
        "serve_config_sha256": serving_config,
        "request_contract_sha256": model_backed.request_contract_sha256(settings),
        "count_endpoint": f"/v1{_COUNT_ENDPOINT_SUFFIX}",
        "generated_tokens": 0,
    }
    shapes: dict[str, int] = {}
    for item in inputs:
        shapes[item.request_shape] = shapes.get(item.request_shape, 0) + 1
    document = build_document(
        identity=identity,
        anchor={
            "e_final_sha256": anchor.e_final_sha256,
            "input_tokens": anchor_tokens,
            "expected_input_tokens": ANCHOR_INPUT_TOKENS,
        },
        records=records,
        request_shapes=shapes,
    )
    written = write_document(output_path, document)
    return {
        "status": document["status"],
        "missing_counts": document["missing_counts"],
        "digest": document["digest"],
        "anchor_input_tokens": anchor_tokens,
        "summary": document["summary"],
        "cleanup": cleanup,
        "output": _reportable_path(config, written),
    }


def _reportable_path(config: RuntimeConfig, path: Path) -> str:
    try:
        return path.resolve().relative_to(config.paths.worktree_root).as_posix()
    except ValueError:
        return path.name


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count exact input tokens for every archived real E_final"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"result path (default: {RESULT_RELATIVE_PATH})",
    )
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(RepoPaths.discover(args.repo))
        output = args.output or config.paths.worktree_root / RESULT_RELATIVE_PATH
        summary = run_census(config, output_path=output)
    except (CensusError, QualificationError) as error:
        report: dict[str, Any] = {"status": "not_counted", "blocker": error.code}
        if error.facts:
            report["facts"] = error.facts
        print(json.dumps(report, sort_keys=True))
        return error.exit_code
    except ConfigError:
        print(json.dumps({"status": "not_counted", "blocker": "configuration"}, sort_keys=True))
        return CONFIG_ERROR
    print(json.dumps(summary, sort_keys=True))
    # A run that could not count every input is not a census result, however
    # many inputs it did count.
    return SUCCESS if summary["status"] == "complete" else INFRA_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
