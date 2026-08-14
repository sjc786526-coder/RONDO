"""Product-agnostic fair-comparison contracts for frozen Codex vs RONDO runs.

Three narrow, versioned contracts live here, and nothing else:

1. ``project_task_independent`` -- a pure projection of the partitions of one
   Responses request that do **not** depend on the task body.  Two sides
   running the same task must agree on it byte for byte; everything the
   trajectory forks into is deliberately excluded.
2. ``SymmetryPreflight`` -- the fail-closed registry that compares those
   projections across sides.  It is consulted after a request body is parsed
   and before any byte can leave the process, so an asymmetric pair is stopped
   with no upstream cost on either side.
3. ``RepeatContract`` / ``ComparisonConditions`` -- the frozen execution
   contract that must be pinned before a campaign may be created.

This module performs no I/O and opens no sockets.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .api_budget_proxy import canonical_request_sha256
from .contracts import Side


TASK_INDEPENDENT_PROJECTION_VERSION = 1
CATALOG_PROJECTION_VERSION = 2
PREFLIGHT_RECEIPT_SCHEMA_VERSION = 1

# Terminal-Bench task IDs are namespaced -- ``terminal-bench/fix-git`` -- so the
# separator has to be accepted or no real task could ever hold a receipt.  Each
# segment must still start with an alphanumeric, which keeps ``.``/``..`` out of
# any path a receipt name is derived from.
_TASK_ID_SEGMENT = r"[a-z0-9][a-z0-9._-]*"
_TASK_ID = re.compile(rf"{_TASK_ID_SEGMENT}(?:/{_TASK_ID_SEGMENT})?\Z")
_MAX_TASK_ID_LENGTH = 128
_ROLES = {"main", "guardian"}
_STABLE_PREFIX_ROLES = {"developer", "system"}
_STABLE_PREFIX_TYPES = {"message", None}
_TRANSPORT_ONLY_ITEM_FIELDS = ("id", "encrypted_function_args")
_MAX_REPEATS_PER_TASK = 9
_SHA256 = re.compile(r"[0-9a-f]{64}")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

AGGREGATION_STRICT_MAJORITY = "strict_majority"
_AGGREGATIONS = {AGGREGATION_STRICT_MAJORITY}

# Ordered so a report always lists partitions the same way.
TASK_INDEPENDENT_PARTITIONS = (
    "sampling_contract",
    "tool_specs",
    "instructions",
    "output_schema",
    "stable_input_prefix",
)


class FairComparisonError(ValueError):
    """Raised before any upstream byte when a comparison contract is unsafe.

    ``reasons`` is ordered most specific first, so a caller that can surface
    only one code -- the proxy answers a blocked request with exactly one --
    reports the differing partition rather than the enclosing scope.
    """

    def __init__(self, message: str, *, reasons: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.reasons = reasons


def valid_task_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= _MAX_TASK_ID_LENGTH
        and _TASK_ID.fullmatch(value) is not None
    )


# --------------------------------------------------------------------------
# Task-independent request projection
# --------------------------------------------------------------------------


def _plain_json(value: object) -> Any:
    """Return a defensive copy that is guaranteed to be canonicalizable."""

    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise FairComparisonError("request partition is not canonical JSON") from exc


def _stable_input_prefix(request: Mapping[str, Any]) -> list[Any]:
    """Return the leading developer/system items of ``input``.

    Responses Lite carries the effective policy and the catalog-derived tool
    descriptions in a developer message at the head of ``input`` rather than in
    top-level ``instructions``.  Projecting only the top-level field would miss
    exactly the class of asymmetry this gate exists to catch, so the leading
    developer/system run is projected too.  The scan stops at the first item
    that is not one -- the task body is a user message, so it is never
    included.
    """

    items = request.get("input")
    if not isinstance(items, list):
        return []
    prefix: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            break
        if item.get("type") not in _STABLE_PREFIX_TYPES:
            break
        if item.get("role") not in _STABLE_PREFIX_ROLES:
            break
        projected = _plain_json(item)
        for field in _TRANSPORT_ONLY_ITEM_FIELDS:
            projected.pop(field, None)
        prefix.append(projected)
    return prefix


def _sampling_contract(request: Mapping[str, Any]) -> dict[str, Any]:
    reasoning = request.get("reasoning")
    if not isinstance(reasoning, dict):
        reasoning = {}
    return _plain_json(
        {
            "model": request.get("model"),
            "reasoning_effort": reasoning.get("effort"),
            "reasoning_summary": reasoning.get("summary"),
            "parallel_tool_calls": request.get("parallel_tool_calls"),
            "tool_choice": request.get("tool_choice"),
            "truncation": request.get("truncation"),
        }
    )


def project_task_independent(request: Mapping[str, Any]) -> dict[str, Any]:
    """Project the frozen, task-independent partitions of one request."""

    if not isinstance(request, Mapping):
        raise FairComparisonError("request must be a JSON object")
    text = request.get("text")
    output_schema = text.get("format") if isinstance(text, dict) else None
    partitions = {
        "sampling_contract": _sampling_contract(request),
        "tool_specs": _plain_json(request.get("tools", [])),
        "instructions": _plain_json(request.get("instructions")),
        "output_schema": _plain_json(output_schema),
        "stable_input_prefix": _stable_input_prefix(request),
    }
    if set(partitions) != set(TASK_INDEPENDENT_PARTITIONS):  # pragma: no cover
        raise FairComparisonError("task-independent partition set drifted")
    return {
        "projection_version": TASK_INDEPENDENT_PROJECTION_VERSION,
        "partitions": partitions,
    }


@dataclass(frozen=True)
class TaskIndependentContract:
    projection_version: int
    digest: str
    partition_digests: tuple[tuple[str, str], ...]

    def partition_digest(self, name: str) -> str:
        for key, value in self.partition_digests:
            if key == name:
                return value
        raise FairComparisonError("unknown task-independent partition")

    def to_dict(self) -> dict[str, object]:
        return {
            "projection_version": self.projection_version,
            "digest": self.digest,
            "partition_digests": {key: value for key, value in self.partition_digests},
        }


def task_independent_contract(request: Mapping[str, Any]) -> TaskIndependentContract:
    """Return the versioned digest set of one request's frozen partitions."""

    projection = project_task_independent(request)
    partitions = projection["partitions"]
    digests = tuple(
        (
            name,
            canonical_request_sha256({"partition": name, "value": partitions[name]}),
        )
        for name in TASK_INDEPENDENT_PARTITIONS
    )
    return TaskIndependentContract(
        projection_version=projection["projection_version"],
        digest=canonical_request_sha256(projection),
        partition_digests=digests,
    )


def compare_task_independent(
    expected: TaskIndependentContract,
    actual: TaskIndependentContract,
) -> tuple[str, ...]:
    """Return bounded, attributable reason codes for every differing partition."""

    if expected.projection_version != actual.projection_version:
        return ("task_independent_projection_version_differs",)
    if expected.digest == actual.digest:
        return ()
    reasons = tuple(
        f"task_independent_{name}_differs"
        for name in TASK_INDEPENDENT_PARTITIONS
        if expected.partition_digest(name) != actual.partition_digest(name)
    )
    # A digest difference with no differing partition would mean the projection
    # and its per-partition decomposition disagree.  Fail closed rather than
    # report a clean comparison.
    return reasons or ("task_independent_contract_differs",)


# --------------------------------------------------------------------------
# Fail-closed preflight registry
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservedRequest:
    """One recorded request digest, kept for provenance and drift only."""

    task_id: str
    role: str
    side: Side
    sequence: int
    full_request_sha256: str
    task_independent_digest: str


class NoUpstreamTransport:
    """A transport that fails closed instead of opening any upstream socket."""

    def open(self, *_args: object, **_kwargs: object) -> Any:
        raise FairComparisonError(
            "stub preflight forbids upstream requests",
            reasons=("stub_preflight_upstream_forbidden",),
        )


class SymmetryPreflight:
    """Freeze the task-independent contract per task/role and enforce it.

    The first registration for a ``(task_id, role)`` key freezes the expected
    contract.  Every later registration -- from either side -- must match it
    exactly.  The full request digest is recorded separately and is never
    asserted equal across sides: after the trajectories fork the dynamic bodies
    legitimately differ.
    """

    def __init__(
        self,
        *,
        allow_upstream: bool = False,
        require_expectation: bool = False,
    ) -> None:
        self._allow_upstream = bool(allow_upstream)
        # When set, a request with no pre-seeded contract is refused instead of
        # being allowed to define one.  Paid runs use this so nothing can be
        # forwarded that a stub run did not already prove symmetric.
        self._require_expectation = bool(require_expectation)
        self._expected: dict[
            tuple[str, str], tuple[Side | None, TaskIndependentContract]
        ] = {}
        self._observed: list[ObservedRequest] = []

    @property
    def allow_upstream(self) -> bool:
        return self._allow_upstream

    @property
    def observed(self) -> tuple[ObservedRequest, ...]:
        return tuple(self._observed)

    def frozen_contract(self, task_id: str, role: str) -> TaskIndependentContract | None:
        entry = self._expected.get((task_id, role))
        return None if entry is None else entry[1]

    def expect(
        self,
        *,
        task_id: str,
        role: str,
        contract: TaskIndependentContract,
    ) -> None:
        """Pre-seed the expected contract from a receipt proved on a stub.

        Without this, the first side to arrive would define the contract and be
        forwarded unchecked -- only the second side could ever be stopped, and
        by then the first has already been charged.  Seeding makes both sides
        answer to a contract frozen before any paid run started.
        """

        if not valid_task_id(task_id):
            raise FairComparisonError(
                "preflight task id is invalid",
                reasons=("preflight_task_id_invalid",),
            )
        if role not in _ROLES:
            raise FairComparisonError(
                "preflight request role is invalid",
                reasons=("preflight_role_invalid",),
            )
        if not isinstance(contract, TaskIndependentContract):
            raise FairComparisonError(
                "preflight expectation is invalid",
                reasons=("preflight_expectation_invalid",),
            )
        if (task_id, role) in self._expected:
            raise FairComparisonError(
                "preflight expectation is already frozen",
                reasons=("preflight_expectation_duplicated",),
            )
        self._expected[(task_id, role)] = (None, contract)

    @property
    def seeded_keys(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            key for key, (side, _contract) in sorted(self._expected.items()) if side is None
        )

    def register(
        self,
        *,
        task_id: str,
        role: str,
        side: Side,
        request: Mapping[str, Any],
    ) -> TaskIndependentContract:
        """Freeze or verify one request; raise before it may be forwarded."""

        if not valid_task_id(task_id):
            raise FairComparisonError(
                "preflight task id is invalid",
                reasons=("preflight_task_id_invalid",),
            )
        if role not in _ROLES:
            raise FairComparisonError(
                "preflight request role is invalid",
                reasons=("preflight_role_invalid",),
            )
        if not isinstance(side, Side):
            raise FairComparisonError(
                "preflight side is invalid",
                reasons=("preflight_side_invalid",),
            )
        contract = task_independent_contract(request)
        key = (task_id, role)
        entry = self._expected.get(key)
        if entry is None:
            if self._require_expectation:
                raise FairComparisonError(
                    "no frozen task-independent contract covers this request",
                    reasons=("preflight_expectation_missing",),
                )
            self._expected[key] = (side, contract)
        else:
            expected_side, expected = entry
            reasons = compare_task_independent(expected, contract)
            if reasons:
                if expected_side is None:
                    scope = "frozen_contract"
                elif expected_side is not side:
                    scope = "cross_side"
                else:
                    scope = "same_side"
                raise FairComparisonError(
                    "task-independent request contract is asymmetric",
                    # Most specific first: the proxy surfaces reasons[0].
                    reasons=(*reasons, f"{scope}_asymmetry"),
                )
        self._observed.append(
            ObservedRequest(
                task_id=task_id,
                role=role,
                side=side,
                sequence=len(self._observed) + 1,
                full_request_sha256=canonical_request_sha256(dict(request)),
                task_independent_digest=contract.digest,
            )
        )
        return contract

    def provenance(self) -> dict[str, object]:
        """Return the per-side digest record kept for provenance and drift."""

        return {
            "projection_version": TASK_INDEPENDENT_PROJECTION_VERSION,
            "frozen_contracts": [
                {
                    "task_id": task_id,
                    "role": role,
                    "first_side": None if first_side is None else first_side.value,
                    **contract.to_dict(),
                }
                for (task_id, role), (first_side, contract) in sorted(
                    self._expected.items()
                )
            ],
            "observed_requests": [
                {
                    "task_id": item.task_id,
                    "role": item.role,
                    "side": item.side.value,
                    "sequence": item.sequence,
                    "full_request_sha256": item.full_request_sha256,
                    "task_independent_digest": item.task_independent_digest,
                }
                for item in self._observed
            ],
        }


@dataclass(frozen=True)
class PreflightReceipt:
    """Proof that both sides were symmetric on a stub before any paid request.

    The receipt is what makes the runtime gate meaningful: it is produced by
    driving both frozen binaries against a local stub endpoint at zero cost,
    and the paid runner refuses to start a slot without one.  It is bound to
    the campaign lock, the task and both bundle manifests so a receipt cannot
    be reused across campaigns, tasks or binaries.
    """

    schema_version: int
    campaign_id: str
    campaign_lock_sha256: str
    task_id: str
    projection_version: int
    bundle_manifest_sha256: tuple[tuple[str, str], ...]
    contracts: tuple[tuple[str, TaskIndependentContract], ...]

    def validate(self) -> None:
        if self.schema_version != PREFLIGHT_RECEIPT_SCHEMA_VERSION:
            raise FairComparisonError(
                "preflight receipt schema is unsupported",
                reasons=("preflight_receipt_schema_unsupported",),
            )
        if not valid_task_id(self.task_id):
            raise FairComparisonError(
                "preflight receipt task id is invalid",
                reasons=("preflight_receipt_task_invalid",),
            )
        if not _SHA256.fullmatch(self.campaign_lock_sha256 or ""):
            raise FairComparisonError(
                "preflight receipt lock digest is invalid",
                reasons=("preflight_receipt_lock_invalid",),
            )
        if self.projection_version != TASK_INDEPENDENT_PROJECTION_VERSION:
            raise FairComparisonError(
                "preflight receipt projection version is unsupported",
                reasons=("preflight_receipt_projection_unsupported",),
            )
        sides = [side for side, _digest in self.bundle_manifest_sha256]
        if sorted(sides) != [Side.CODEX.value, Side.RONDO.value] or any(
            not _SHA256.fullmatch(digest or "")
            for _side, digest in self.bundle_manifest_sha256
        ):
            raise FairComparisonError(
                "preflight receipt must bind both frozen bundles",
                reasons=("preflight_receipt_bundles_invalid",),
            )
        roles = [role for role, _contract in self.contracts]
        if not roles or len(set(roles)) != len(roles) or any(
            role not in _ROLES for role in roles
        ):
            raise FairComparisonError(
                "preflight receipt roles are invalid",
                reasons=("preflight_receipt_roles_invalid",),
            )

    def require_binding(
        self,
        *,
        campaign_id: str,
        campaign_lock_sha256: str,
        task_id: str,
        bundle_manifest_sha256: dict[str, str],
    ) -> None:
        """Fail closed unless the receipt was produced for exactly this run."""

        self.validate()
        reasons = tuple(
            reason
            for reason, matched in (
                ("preflight_receipt_campaign_differs", self.campaign_id == campaign_id),
                (
                    "preflight_receipt_lock_differs",
                    self.campaign_lock_sha256 == campaign_lock_sha256,
                ),
                ("preflight_receipt_task_differs", self.task_id == task_id),
                (
                    "preflight_receipt_bundle_differs",
                    dict(self.bundle_manifest_sha256) == dict(bundle_manifest_sha256),
                ),
            )
            if not matched
        )
        if reasons:
            raise FairComparisonError(
                "preflight receipt does not cover this run", reasons=reasons
            )

    def seed(self, preflight: "SymmetryPreflight") -> None:
        self.validate()
        for role, contract in self.contracts:
            preflight.expect(task_id=self.task_id, role=role, contract=contract)

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "campaign_id": self.campaign_id,
            "campaign_lock_sha256": self.campaign_lock_sha256,
            "task_id": self.task_id,
            "projection_version": self.projection_version,
            "bundle_manifest_sha256": dict(self.bundle_manifest_sha256),
            "contracts": {
                role: contract.to_dict() for role, contract in self.contracts
            },
        }

    @classmethod
    def from_dict(cls, value: object) -> "PreflightReceipt":
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "campaign_id",
            "campaign_lock_sha256",
            "task_id",
            "projection_version",
            "bundle_manifest_sha256",
            "contracts",
        }:
            raise FairComparisonError(
                "preflight receipt is not frozen",
                reasons=("preflight_receipt_not_frozen",),
            )
        bundles = value["bundle_manifest_sha256"]
        contracts = value["contracts"]
        if not isinstance(bundles, dict) or not isinstance(contracts, dict):
            raise FairComparisonError(
                "preflight receipt is not frozen",
                reasons=("preflight_receipt_not_frozen",),
            )
        parsed: list[tuple[str, TaskIndependentContract]] = []
        for role, item in sorted(contracts.items()):
            if not isinstance(item, dict) or set(item) != {
                "projection_version",
                "digest",
                "partition_digests",
            }:
                raise FairComparisonError(
                    "preflight receipt contract is invalid",
                    reasons=("preflight_receipt_contract_invalid",),
                )
            digests = item["partition_digests"]
            if not isinstance(digests, dict) or set(digests) != set(
                TASK_INDEPENDENT_PARTITIONS
            ) or any(
                not isinstance(digest, str) or not _SHA256.fullmatch(digest)
                for digest in digests.values()
            ):
                raise FairComparisonError(
                    "preflight receipt contract is invalid",
                    reasons=("preflight_receipt_contract_invalid",),
                )
            parsed.append(
                (
                    str(role),
                    TaskIndependentContract(
                        projection_version=item["projection_version"],
                        digest=str(item["digest"]),
                        partition_digests=tuple(
                            (name, digests[name]) for name in TASK_INDEPENDENT_PARTITIONS
                        ),
                    ),
                )
            )
        receipt = cls(
            schema_version=value["schema_version"],
            campaign_id=str(value["campaign_id"]),
            campaign_lock_sha256=str(value["campaign_lock_sha256"]),
            task_id=str(value["task_id"]),
            projection_version=value["projection_version"],
            bundle_manifest_sha256=tuple(
                (str(side), str(digest)) for side, digest in sorted(bundles.items())
            ),
            contracts=tuple(parsed),
        )
        receipt.validate()
        return receipt


def preflight_receipt_from_stub_run(
    *,
    campaign_id: str,
    campaign_lock_sha256: str,
    task_id: str,
    bundle_manifest_sha256: dict[str, str],
    requests_by_side: Mapping[Side, Mapping[str, Mapping[str, Any]]],
) -> PreflightReceipt:
    """Freeze a receipt from the requests both sides produced against a stub.

    ``requests_by_side`` maps each side to ``{role: request}``.  Both sides must
    cover exactly the same roles and agree on every task-independent partition;
    anything else raises instead of producing a receipt.
    """

    if set(requests_by_side) != {Side.RONDO, Side.CODEX}:
        raise FairComparisonError(
            "a stub preflight must cover both sides",
            reasons=("preflight_stub_sides_incomplete",),
        )
    roles = {side: set(values) for side, values in requests_by_side.items()}
    if roles[Side.RONDO] != roles[Side.CODEX] or not roles[Side.RONDO]:
        raise FairComparisonError(
            "both sides must produce the same request roles",
            reasons=("preflight_stub_roles_differ",),
        )
    preflight = SymmetryPreflight(allow_upstream=False)
    for side in (Side.RONDO, Side.CODEX):
        for role in sorted(roles[side]):
            preflight.register(
                task_id=task_id,
                role=role,
                side=side,
                request=requests_by_side[side][role],
            )
    receipt = PreflightReceipt(
        schema_version=PREFLIGHT_RECEIPT_SCHEMA_VERSION,
        campaign_id=campaign_id,
        campaign_lock_sha256=campaign_lock_sha256,
        task_id=task_id,
        projection_version=TASK_INDEPENDENT_PROJECTION_VERSION,
        bundle_manifest_sha256=tuple(sorted(bundle_manifest_sha256.items())),
        contracts=tuple(
            (role, preflight.frozen_contract(task_id, role))
            for role in sorted(roles[Side.RONDO])
        ),
    )
    receipt.validate()
    return receipt


def stub_preflight(
    pairs: Iterable[tuple[str, str, Side, Mapping[str, Any]]],
) -> SymmetryPreflight:
    """Compare already-captured requests offline.

    ``pairs`` yields ``(task_id, role, side, request)``.  This is a pure
    comparison over request bodies -- it opens nothing and has no transport of
    its own; ``allow_upstream`` is false so any caller that inspects the
    preflight sees that forwarding is not permitted from here.  The structural
    guarantee that a request cannot reach a provider belongs to
    ``NoUpstreamTransport`` and to the stub producer, not to this helper.
    """

    preflight = SymmetryPreflight(allow_upstream=False)
    for task_id, role, side, request in pairs:
        preflight.register(task_id=task_id, role=role, side=side, request=request)
    return preflight


# --------------------------------------------------------------------------
# Frozen execution contract
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RepeatContract:
    """Repetition rules frozen after the pilot and before any paid data."""

    repeats_per_task: int
    aggregation: str
    frozen_after: str

    def validate(self) -> None:
        if (
            isinstance(self.repeats_per_task, bool)
            or not isinstance(self.repeats_per_task, int)
            or self.repeats_per_task < 3
            or self.repeats_per_task > _MAX_REPEATS_PER_TASK
        ):
            raise FairComparisonError(
                "repeat count must be at least three",
                reasons=("repeat_count_below_minimum",),
            )
        if self.repeats_per_task % 2 == 0:
            raise FairComparisonError(
                "repeat count must be odd so per-task aggregation cannot tie",
                reasons=("repeat_count_not_odd",),
            )
        if self.aggregation not in _AGGREGATIONS:
            raise FairComparisonError(
                "repeat aggregation formula is not frozen",
                reasons=("repeat_aggregation_unsupported",),
            )
        if self.frozen_after != "pilot":
            raise FairComparisonError(
                "repeat count must be frozen after the pilot",
                reasons=("repeat_freeze_point_invalid",),
            )

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "repeats_per_task": self.repeats_per_task,
            "aggregation": self.aggregation,
            "frozen_after": self.frozen_after,
        }

    @classmethod
    def from_dict(cls, value: object) -> "RepeatContract":
        if not isinstance(value, dict) or set(value) != {
            "repeats_per_task",
            "aggregation",
            "frozen_after",
        }:
            raise FairComparisonError(
                "repeat contract is not frozen",
                reasons=("repeat_contract_not_frozen",),
            )
        contract = cls(
            repeats_per_task=value["repeats_per_task"],
            aggregation=str(value["aggregation"]),
            frozen_after=str(value["frozen_after"]),
        )
        contract.validate()
        return contract


def aggregate_repeat_outcomes(
    outcomes: tuple[Any, ...],
    *,
    contract: RepeatContract,
    pass_value: Any,
    fail_value: Any,
) -> Any:
    """Aggregate one task's frozen repeats into a single outcome.

    The only frozen formula is a strict majority over an odd repeat count, so
    the result never depends on ordering and can never tie.  Dropping or adding
    samples is rejected rather than silently renormalized.
    """

    contract.validate()
    values = tuple(outcomes)
    if len(values) != contract.repeats_per_task:
        raise FairComparisonError(
            "repeat sample count differs from the frozen contract",
            reasons=("repeat_sample_count_differs",),
        )
    unexpected = [item for item in values if item not in (pass_value, fail_value)]
    if unexpected:
        raise FairComparisonError(
            "repeat aggregation received a non-terminal outcome",
            reasons=("repeat_outcome_not_terminal",),
        )
    passes = sum(1 for item in values if item == pass_value)
    return pass_value if passes * 2 > len(values) else fail_value


@dataclass(frozen=True)
class ComparisonConditions:
    """Run conditions that both sides must share for a comparison to count."""

    eval_harness_commit: str
    upstream_timeout_seconds: str
    provider_profile_sha256: str
    catalog_artifact_sha256: str
    task_image_digests: tuple[tuple[str, str], ...]
    projection_version: int = TASK_INDEPENDENT_PROJECTION_VERSION

    def validate(self) -> None:
        if not _COMMIT.fullmatch(self.eval_harness_commit or ""):
            raise FairComparisonError(
                "eval harness commit is invalid",
                reasons=("harness_commit_invalid",),
            )
        for name, value in (
            ("provider_profile_sha256", self.provider_profile_sha256),
            ("catalog_artifact_sha256", self.catalog_artifact_sha256),
        ):
            if not isinstance(value, str) or not _SHA256.fullmatch(value):
                raise FairComparisonError(
                    f"{name} is invalid",
                    reasons=(f"{name}_invalid",),
                )
        try:
            timeout = float(self.upstream_timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise FairComparisonError(
                "upstream timeout is invalid",
                reasons=("upstream_timeout_invalid",),
            ) from exc
        if not 0 < timeout <= 3600:
            raise FairComparisonError(
                "upstream timeout is invalid",
                reasons=("upstream_timeout_invalid",),
            )
        if not self.task_image_digests:
            raise FairComparisonError(
                "task image freeze is empty",
                reasons=("task_image_freeze_empty",),
            )
        seen = [task_id for task_id, _digest in self.task_image_digests]
        if len(set(seen)) != len(seen) or list(seen) != sorted(seen):
            raise FairComparisonError(
                "task image freeze is not a sorted unique mapping",
                reasons=("task_image_freeze_invalid",),
            )
        if any(
            not _IMAGE_DIGEST.fullmatch(digest or "")
            for _task_id, digest in self.task_image_digests
        ):
            raise FairComparisonError(
                "task image digest is not a content address",
                reasons=("task_image_digest_invalid",),
            )
        if self.projection_version != TASK_INDEPENDENT_PROJECTION_VERSION:
            raise FairComparisonError(
                "task-independent projection version is unsupported",
                reasons=("projection_version_unsupported",),
            )

    def require_match(self, other: "ComparisonConditions") -> None:
        """Fail closed with an attributable reason on any condition drift."""

        self.validate()
        other.validate()
        reasons = tuple(
            reason
            for reason, matched in (
                (
                    "eval_harness_commit_differs",
                    self.eval_harness_commit == other.eval_harness_commit,
                ),
                (
                    "upstream_timeout_differs",
                    float(self.upstream_timeout_seconds)
                    == float(other.upstream_timeout_seconds),
                ),
                (
                    "provider_profile_differs",
                    self.provider_profile_sha256 == other.provider_profile_sha256,
                ),
                (
                    "catalog_artifact_differs",
                    self.catalog_artifact_sha256 == other.catalog_artifact_sha256,
                ),
                (
                    "task_image_differs",
                    self.task_image_digests == other.task_image_digests,
                ),
                (
                    "projection_version_differs",
                    self.projection_version == other.projection_version,
                ),
            )
            if not matched
        )
        if reasons:
            raise FairComparisonError(
                "comparison run conditions differ between sides",
                reasons=reasons,
            )

    def to_dict(self) -> dict[str, object]:
        self.validate()
        return {
            "eval_harness_commit": self.eval_harness_commit,
            "upstream_timeout_seconds": self.upstream_timeout_seconds,
            "provider_profile_sha256": self.provider_profile_sha256,
            "catalog_artifact_sha256": self.catalog_artifact_sha256,
            "task_image_digests": {
                task_id: digest for task_id, digest in self.task_image_digests
            },
            "projection_version": self.projection_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> "ComparisonConditions":
        if not isinstance(value, dict) or set(value) != {
            "eval_harness_commit",
            "upstream_timeout_seconds",
            "provider_profile_sha256",
            "catalog_artifact_sha256",
            "task_image_digests",
            "projection_version",
        }:
            raise FairComparisonError(
                "comparison conditions are not frozen",
                reasons=("comparison_conditions_not_frozen",),
            )
        images = value["task_image_digests"]
        if not isinstance(images, dict):
            raise FairComparisonError(
                "task image freeze is invalid",
                reasons=("task_image_freeze_invalid",),
            )
        conditions = cls(
            eval_harness_commit=str(value["eval_harness_commit"]),
            upstream_timeout_seconds=str(value["upstream_timeout_seconds"]),
            provider_profile_sha256=str(value["provider_profile_sha256"]),
            catalog_artifact_sha256=str(value["catalog_artifact_sha256"]),
            task_image_digests=tuple(
                (str(task_id), str(digest)) for task_id, digest in sorted(images.items())
            ),
            projection_version=value["projection_version"],
        )
        conditions.validate()
        return conditions
