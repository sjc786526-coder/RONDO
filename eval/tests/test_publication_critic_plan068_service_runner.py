from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.local_deployment.service_runner import (  # noqa: E402
    _announcement_matches,
    main,
)
from rondo_eval.publication_critic.local_deployment.qualification import (  # noqa: E402
    FREEZE_SCHEMA,
    freeze_sha256,
)
from rondo_eval.publication_critic.identity import (  # noqa: E402
    canonical_json_bytes,
    sha256_bytes,
)


BODY_SENTINEL = "PLAN068_PRIVATE_PACKET_BODY_SENTINEL"

FAKE_SERVICE = r'''#!/usr/bin/env python3
import argparse
import copy
import json
import os
from pathlib import Path
import signal
import sys
import time

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--descriptor", required=True)
args, _unknown = parser.parse_known_args()
root = Path(__file__).resolve().parent
(root / "service-pid").write_text(str(os.getpid()), encoding="ascii")
descriptor = json.loads(Path(args.descriptor).read_text(encoding="utf-8"))
announced = copy.deepcopy(descriptor["service_descriptor"])
if (root / "announcement-drift").exists():
    announced["untrusted_extra"] = True
print(json.dumps({
    "protocol": "rondo_publication_critic_v1",
    "endpoint": "127.0.0.1:23456",
    "descriptor": announced,
}, separators=(",", ":")), flush=True)
while not (root / "shutdown").exists():
    time.sleep(0.01)
'''

FAKE_PROBE = r'''#!/usr/bin/env python3
import json
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
count_path = root / "probe-count"
with count_path.open("a", encoding="ascii") as handle:
    handle.write("1\n")
operation = next(
    value for value in ("ready", "review", "cancel", "shutdown") if value in sys.argv
)
if (root / "fail-ready-and-shutdown").exists() and operation in {"ready", "shutdown"}:
    print("publication_critic_probe_failed code=backend", file=sys.stderr)
    raise SystemExit(1)
if (root / "typed-review-failure").exists() and operation == "review":
    print("publication_critic_probe_failed code=queue_full", file=sys.stderr)
    raise SystemExit(1)
result = {
    "ready": "ready",
    "review": "pass",
    "cancel": "cancelled",
    "shutdown": "accepted",
}[operation]
if operation == "shutdown":
    (root / "shutdown").write_text("1", encoding="ascii")
print(json.dumps({"operation": operation, "result": result}, separators=(",", ":")))
'''


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.service = root / "fake-service.py"
        self.probe = root / "fake-probe.py"
        self.snapshot = root / "snapshot"
        self.repo_root = root / "repo"
        self.descriptor = root / "descriptor.json"
        self.freeze = root / "freeze.json"
        self.packet = root / "packet.json"
        self.output = root / "service-result.json"
        self.service.write_text(FAKE_SERVICE, encoding="utf-8")
        self.probe.write_text(FAKE_PROBE, encoding="utf-8")
        self.service.chmod(0o700)
        self.probe.chmod(0o700)
        self.snapshot.mkdir()
        (self.repo_root / "eval").mkdir(parents=True)
        service_descriptor = {
            "identity": {"frozen": "trusted-service-identity"},
            "limits": {
                "request_bytes": 131_072,
                "response_bytes": 16_384,
                "max_concurrency": 1,
                "queue_capacity": 4,
                "job_timeout_ms": 25_000,
                "io_timeout_ms": 2_000,
            },
        }
        service_sha256 = sha256_bytes(canonical_json_bytes(service_descriptor))
        artifacts = {
            object_id: {
                "candidate_artifact_sha256": character * 64,
                "deployment_artifact_sha256": character * 64,
                "service_descriptor_sha256": (
                    service_sha256 if object_id == "c1" else character * 64
                ),
            }
            for object_id, character in zip(("base", "c1", "c2", "c3"), "fabc")
        }
        artifacts["c1"]["candidate_artifact_sha256"] = "a" * 64
        artifacts["c1"]["deployment_artifact_sha256"] = "a" * 64
        freeze = {
            "schema": FREEZE_SCHEMA,
            "qualification_objects": ["base", "c1", "c2", "c3"],
            "cohort": {
                "sample_ids": [
                    "pc-v1-cal-nc-pass",
                    "pc-v1-cal-nc-rewrite",
                    "pc-v1-cal-ni-pass",
                    "pc-v1-cal-ni-rewrite",
                ],
                "future_unseen_test": False,
            },
            "threshold": {"source": "fixture", "projected_score": 0.5},
            "reference_method": "fixture-float32",
            "source": {
                "git_commit": "d" * 40,
                "tracked_source_clean": True,
                "environment_lock_path": "eval/environment/uv.lock",
                "environment_lock_sha256": "e" * 64,
            },
            "artifacts": artifacts,
            "runtime": {
                "device": "cuda",
                "dtype": "bfloat16",
                "cpu_threads": 4,
                "deployment_format": "fixture-safetensors",
                "service_limits": {
                    **service_descriptor["limits"],
                    "worker_startup_timeout_ms": 1_000,
                    "worker_io_timeout_ms": 500,
                    "worker_shutdown_timeout_ms": 500,
                    "graceful_shutdown_ms": 500,
                    "force_shutdown_ms": 500,
                    "call_timeout_ms": 500,
                    "startup_timeout_ms": 1_000,
                    "process_timeout_ms": 300,
                    "representative_cancel_after_ms": 10,
                },
            },
            "gates": {
                "max_projected_absolute_drift": 1.0,
                "min_ranking_concordance": 0.0,
                "reference_obvious_margin_floor": 0.1,
                "min_obvious_margin_direction_agreement": 0.0,
                "min_pair_direction_agreement": 0.0,
                "max_verdict_mismatches": 4,
                "max_load_seconds": 30.0,
                "max_peak_rss_bytes": 8_000_000_000,
                "max_peak_vram_bytes": 7_500_000_000,
                "max_warm_p95_latency_ms": 1_000.0,
                "max_service_score_absolute_drift": 1.0,
                "max_service_verdict_mismatches": 4,
                "min_stress_success_rate": 0.0,
                "max_stress_p95_latency_ms": 2_000.0,
            },
            "stress_call_counts": [1, 2, 4, 8],
            "representative_lifecycle_object": "c1",
        }
        self.freeze.write_text(json.dumps(freeze), encoding="utf-8")
        self.descriptor.write_text(
            json.dumps(
                {
                    "worker_protocol": "rondo-publication-critic-worker-v1",
                    "object_id": "c1",
                    "deployment_artifact_sha256": "a" * 64,
                    "qualification_freeze_sha256": freeze_sha256(freeze),
                    "service_descriptor": service_descriptor,
                }
            ),
            encoding="utf-8",
        )
        self.packet.write_text(
            json.dumps({"candidate": BODY_SENTINEL}),
            encoding="utf-8",
        )

    def arguments(self, *, cancel: bool = True) -> list[str]:
        arguments = [
            "--mode",
            "formal",
            "--service",
            str(self.service),
            "--probe",
            str(self.probe),
            "--python",
            sys.executable,
            "--snapshot",
            str(self.snapshot),
            "--descriptor",
            str(self.descriptor),
            "--freeze",
            str(self.freeze),
            "--packet",
            str(self.packet),
            "--output",
            str(self.output),
            "--repo-root",
            str(self.repo_root),
            "--device",
            "cuda",
            "--dtype",
            "bfloat16",
            "--cpu-threads",
            "4",
            "--worker-startup-timeout-ms",
            "1000",
            "--worker-io-timeout-ms",
            "500",
            "--worker-shutdown-timeout-ms",
            "500",
            "--graceful-shutdown-ms",
            "500",
            "--force-shutdown-ms",
            "500",
            "--call-timeout-ms",
            "500",
            "--startup-timeout-ms",
            "1000",
            "--process-timeout-ms",
            "300",
        ]
        if cancel:
            arguments.extend(["--cancel-after-ms", "10"])
        return arguments

    def service_pid(self) -> int:
        return int((self.root / "service-pid").read_text(encoding="ascii"))


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class ServiceRunnerTests(unittest.TestCase):
    def test_announcement_allows_only_one_ulp_threshold_round_trip(self) -> None:
        expected = {
            "identity": {"scoring": {"threshold": 0.9350569011196121}},
            "limits": {"queue_capacity": 8},
        }
        announced = json.loads(json.dumps(expected))
        announced["identity"]["scoring"]["threshold"] = math.nextafter(
            expected["identity"]["scoring"]["threshold"],
            0.0,
        )
        self.assertEqual(_announcement_matches(expected, announced), (True, True))

        announced["limits"]["queue_capacity"] = 9
        self.assertEqual(_announcement_matches(expected, announced), (False, False))

    def test_formal_run_records_typed_bounded_calls_and_private_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))

            self.assertEqual(main(fixture.arguments()), 0)

            result = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "COMPLETE")
            self.assertIsNone(result["failure_code"])
            self.assertEqual(result["ready"]["result"], "ready")
            self.assertEqual(len(result["warm_reviews"]), 3)
            self.assertEqual(
                [scenario["concurrency"] for scenario in result["stress"]],
                [1, 2, 4, 8],
            )
            self.assertEqual(
                [len(scenario["calls"]) for scenario in result["stress"]],
                [1, 2, 4, 8],
            )
            self.assertEqual(result["cancel"]["result"], "cancelled")
            self.assertEqual(result["post_cancel_ready"]["result"], "ready")
            self.assertEqual(result["post_cancel_review"]["result"], "pass")
            self.assertEqual(result["call_summary"]["stress_call_count"], 15)
            self.assertEqual(result["call_summary"]["stress_success_count"], 15)
            self.assertEqual(result["shutdown"]["result"], "accepted")
            self.assertTrue(result["service_exit"]["reaped"])
            self.assertEqual(fixture.output.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(BODY_SENTINEL, fixture.output.read_text(encoding="utf-8"))
            self.assertFalse(_pid_exists(fixture.service_pid()))

    def test_untrusted_announcement_is_rejected_without_invoking_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            (fixture.root / "announcement-drift").write_text("1", encoding="ascii")

            self.assertEqual(main(fixture.arguments()), 1)

            result = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(result["failure_code"], "announcement_identity_mismatch")
            self.assertNotIn("announcement", result)
            self.assertFalse((fixture.root / "probe-count").exists())
            self.assertFalse(_pid_exists(fixture.service_pid()))

    def test_probe_failure_still_reaps_task_owned_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            (fixture.root / "fail-ready-and-shutdown").write_text("1", encoding="ascii")

            self.assertEqual(main(fixture.arguments()), 1)

            result = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(result["failure_code"], "ready_probe_failed")
            self.assertEqual(result["ready"]["failure_code"], "backend")
            self.assertEqual(result["shutdown"]["failure_code"], "backend")
            self.assertIn(
                result["service_exit"]["method"],
                {"terminate_group", "terminate_group_after_exit", "kill_group"},
            )
            self.assertTrue(result["service_exit"]["reaped"])
            self.assertFalse(_pid_exists(fixture.service_pid()))

    def test_typed_review_failures_are_complete_qualification_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            (fixture.root / "typed-review-failure").write_text("1", encoding="ascii")

            self.assertEqual(main(fixture.arguments()), 0)

            result = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["call_summary"]["warm_success_count"], 0)
            self.assertEqual(result["call_summary"]["stress_success_count"], 0)
            self.assertEqual(
                result["call_summary"]["typed_failure_codes"],
                ["queue_full"] * 19,
            )
            self.assertTrue(result["service_exit"]["reaped"])

    def test_frozen_runtime_mismatch_starts_no_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            arguments = fixture.arguments()
            value_index = arguments.index("--worker-io-timeout-ms") + 1
            arguments[value_index] = "501"

            self.assertEqual(main(arguments), 1)

            result = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(result["status"], "FAILED")
            self.assertEqual(
                result["failure_code"],
                "freeze_runtime_arguments_mismatch",
            )
            self.assertFalse((fixture.root / "service-pid").exists())

    def test_output_is_exclusive_and_second_run_starts_no_service(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            fixture.output.write_text("existing\n", encoding="utf-8")

            self.assertEqual(main(fixture.arguments()), 1)

            self.assertEqual(fixture.output.read_text(encoding="utf-8"), "existing\n")
            self.assertFalse((fixture.root / "service-pid").exists())


if __name__ == "__main__":
    unittest.main()
