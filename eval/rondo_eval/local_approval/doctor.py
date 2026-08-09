"""Layered health diagnosis for local static approval infrastructure."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

from ..config import ConfigError, RepoPaths, RuntimeConfig, load_runtime_config
from ..evidence import build_static_payload
from ..exit_codes import (
    CONFIG_ERROR,
    INFRA_ERROR,
    MODEL_MISSING,
    SERVICE_UNAVAILABLE,
    STRUCTURED_OUTPUT_ERROR,
    SUCCESS,
)
from .client import (
    LocalApprovalClient,
    LocalApprovalSettings,
    ServiceUnavailableError,
    StructuredOutputError,
    settings_from_config,
)
from .launcher import (
    ModelMissingError,
    RouterProbe,
    RuntimeInspection,
    inspect_runtime,
    model_path,
    probe_router_runtime,
)


@dataclass(frozen=True)
class DoctorReport:
    status: str
    exit_code: int
    configuration: str
    runtime: str
    model: str
    service: str
    schema: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def run_doctor(
    config: RuntimeConfig,
    *,
    runtime_inspector: Callable[[RuntimeConfig, LocalApprovalSettings], RuntimeInspection] = inspect_runtime,
    router_probe: Callable[
        [RuntimeConfig, LocalApprovalSettings, RuntimeInspection], RouterProbe
    ] = probe_router_runtime,
    decision_probe: Callable[[RuntimeConfig], dict[str, object]] | None = None,
) -> DoctorReport:
    """Return one precise state without turning missing weights into success."""

    try:
        settings = settings_from_config(config)
    except ConfigError:
        return DoctorReport(
            "configuration_error",
            CONFIG_ERROR,
            "invalid",
            "not_checked",
            "not_checked",
            "not_checked",
            "not_checked",
        )

    try:
        runtime = runtime_inspector(config, settings)
    except Exception:
        return DoctorReport(
            "runtime_probe_error",
            INFRA_ERROR,
            "valid",
            "unknown",
            "not_checked",
            "not_checked",
            "not_checked",
        )
    if not runtime.ok:
        return DoctorReport(
            runtime.status,
            INFRA_ERROR,
            "valid",
            runtime.status,
            "not_checked",
            "not_checked",
            "not_checked",
        )

    try:
        model_path(config, settings)
    except ModelMissingError:
        try:
            probe = router_probe(config, settings, runtime)
        except Exception:
            return DoctorReport(
                "runtime_probe_error",
                INFRA_ERROR,
                "valid",
                "unknown",
                "missing",
                "not_checked",
                "not_checked",
            )
        if not probe.ok:
            return DoctorReport(
                probe.status,
                INFRA_ERROR,
                "valid",
                "invalid",
                "missing",
                "not_checked",
                "not_checked",
            )
        return DoctorReport(
            "infrastructure_ready_model_missing",
            MODEL_MISSING,
            "valid",
            "ready",
            "missing",
            "not_started",
            "not_checked",
        )
    except ConfigError:
        return DoctorReport(
            "configuration_error",
            CONFIG_ERROR,
            "invalid",
            "ready",
            "invalid",
            "not_checked",
            "not_checked",
        )

    try:
        if decision_probe is None:
            _probe_decision(config)
        else:
            decision_probe(config)
    except ServiceUnavailableError:
        return DoctorReport(
            "service_unavailable",
            SERVICE_UNAVAILABLE,
            "valid",
            "ready",
            "present",
            "unavailable",
            "not_checked",
        )
    except StructuredOutputError:
        return DoctorReport(
            "service_schema_error",
            STRUCTURED_OUTPUT_ERROR,
            "valid",
            "ready",
            "present",
            "reachable",
            "invalid",
        )
    except ConfigError:
        return DoctorReport(
            "configuration_error",
            CONFIG_ERROR,
            "invalid",
            "ready",
            "present",
            "not_checked",
            "not_checked",
        )
    except Exception:
        return DoctorReport(
            "internal_error",
            INFRA_ERROR,
            "valid",
            "ready",
            "present",
            "unknown",
            "unknown",
        )
    return DoctorReport(
        "ready",
        SUCCESS,
        "valid",
        "ready",
        "present",
        "reachable",
        "valid",
    )


def _probe_decision(config: RuntimeConfig) -> dict[str, object]:
    payload = build_static_payload(
        {
            "instructions": "RONDO local approval doctor policy v1",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": "Return a structured decision for this service schema probe.",
                        }
                    ],
                }
            ],
        }
    )
    return LocalApprovalClient(config).decide(payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose local approval readiness")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(RepoPaths.discover(args.repo))
    except ConfigError:
        report = DoctorReport(
            "configuration_error",
            CONFIG_ERROR,
            "invalid",
            "not_checked",
            "not_checked",
            "not_checked",
            "not_checked",
        )
    else:
        report = run_doctor(config)
    print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
