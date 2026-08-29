from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from rondo_eval.publication_critic.full_model_training.contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
)
from rondo_eval.publication_critic.full_model_training.plan099_artifacts import (
    Plan099ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan099_cli import (
    _export_candidate,
    _resume_checkpoint,
    _validate_environment_receipt,
    verify_candidate_handoff,
)
from rondo_eval.publication_critic.full_model_training.plan099_cli import (
    main as plan099_main,
)
from rondo_eval.publication_critic.full_model_training.plan099_contract import (
    MINIMUM_L40S_VISIBLE_MEMORY_BYTES,
    assess_development_checkpoint,
    authorize_paid_segment,
    authorize_pod_lifecycle,
    create_budget_snapshot,
    load_freeze,
    plan099_runtime_control_root,
    validate_budget_snapshot,
    validate_current_pod_runtime_control_chain,
    validate_live_resource_receipt,
    validate_pod_lifecycle_authorization,
    validate_runtime_control_chain,
    validate_runtime_control_file,
)
from rondo_eval.publication_critic.full_model_training.plan099_data import (
    commissioning_dataset,
    load_train_dataset,
    load_validation_dataset,
)
from rondo_eval.publication_critic.full_model_training.plan099_model import (
    model_identity,
    verify_inference_ready,
)
from rondo_eval.publication_critic.full_model_training.plan099_objective import (
    HEAD_SLICES,
    reference_objective,
    structured_output_from_flat,
)
from rondo_eval.publication_critic.full_model_training.plan099_training import (
    Plan099TrainingController,
    validate_terminal_candidate,
)
from rondo_eval.publication_critic.qualification import (
    evaluate_qualification_predictions,
)
from rondo_eval.publication_critic.successor_task import (
    DIMENSION_CLASSES,
    HARD_DIMENSIONS,
    evaluate_pair_predictions,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIFECYCLE_GUARD = (
    REPO_ROOT / "training/publication-critic-plan094/runpod-lifecycle-guard.py"
)
GUARD_SPEC = importlib.util.spec_from_file_location(
    "plan099_lifecycle_guard_profile", LIFECYCLE_GUARD
)
assert GUARD_SPEC is not None and GUARD_SPEC.loader is not None
guard = importlib.util.module_from_spec(GUARD_SPEC)
GUARD_SPEC.loader.exec_module(guard)


def test_freeze_and_v10_entrypoints_expose_only_development_splits() -> None:
    freeze = load_freeze(REPO_ROOT)
    train = load_train_dataset(REPO_ROOT)
    validation = load_validation_dataset(REPO_ROOT)
    commissioning = commissioning_dataset(train)

    assert freeze["model"]["base"]["revision"] == (
        "e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc"
    )
    assert freeze["recipe"]["scope"]["trainable_parameter_elements"] == 22_528
    assert freeze["resource"]["pods"]["maximum_lifecycle_seconds"] == 10_380
    assert {
        row["role"]
        for row in freeze["assets"]["runtime_control_upload_allowlist"]["roles"]
    } == {"live-resource", "lifecycle", "segment"}
    assert (len(train.candidates), len(train.pairs)) == (162, 72)
    assert (len(validation.candidates), len(validation.pairs)) == (27, 12)
    assert len(commissioning.pairs) == 6
    assert {row["kind"] for row in commissioning.pairs} == {
        "boundary",
        "soft_only_invariance",
    }
    assert {
        row["target_dimension"]
        for row in commissioning.pairs
        if row["kind"] == "boundary"
    } == set(HARD_DIMENSIONS)
    assert not (REPO_ROOT / "training/publication-critic-v10/splits/test").exists()


def test_five_head_objective_rewards_absolute_and_pair_correct_logits() -> None:
    freeze = load_freeze(REPO_ROOT)
    dataset = commissioning_dataset(load_train_dataset(REPO_ROOT))
    good = _gold_logits(dataset.candidates)
    bad = [tuple(-value for value in row) for row in good]
    good_loss = reference_objective(
        candidate_ids=dataset.candidate_ids,
        flat_logits=good,
        labels_by_id=dataset.labels_by_id,
        pairs=dataset.pairs,
        recipe=freeze["recipe"],
    )
    bad_loss = reference_objective(
        candidate_ids=dataset.candidate_ids,
        flat_logits=bad,
        labels_by_id=dataset.labels_by_id,
        pairs=dataset.pairs,
        recipe=freeze["recipe"],
    )

    assert set(good_loss) == {"dimension", "gate", "boundary", "invariance", "total"}
    assert good_loss["total"] < bad_loss["total"]
    output = structured_output_from_flat(good)
    assert output["backbone_forward_count"] == 1
    assert set(output["heads"]) == set(HARD_DIMENSIONS)


def test_development_gate_accepts_exact_gold_and_fails_closed_on_collapse() -> None:
    validation = load_validation_dataset(REPO_ROOT)
    gold = tuple(row["labels"] for row in validation.candidates)
    metrics = evaluate_qualification_predictions(gold, gold)
    pair_evaluation = _pair_evaluation(validation, gold)
    accepted = assess_development_checkpoint(
        metrics=metrics,
        pair_evaluation=pair_evaluation,
        predicted_rows=gold,
        training_loss=0.25,
    )
    assert accepted["eligible"] is True

    collapsed = tuple(
        {dimension: "PASS" for dimension in HARD_DIMENSIONS} for _ in gold
    )
    rejected = assess_development_checkpoint(
        metrics=evaluate_qualification_predictions(gold, collapsed),
        pair_evaluation=_pair_evaluation(validation, collapsed),
        predicted_rows=collapsed,
        training_loss=0.25,
    )
    assert rejected["eligible"] is False
    assert rejected["checks"]["non_collapsed"] is False
    assert rejected["checks"]["all_validation_pairs_closed"] is False


def test_dynamic_budget_reserves_existing_volume_and_closure() -> None:
    snapshot = _budget_snapshot()
    assert validate_budget_snapshot(snapshot)["stage_b_dynamic_budget_usd"] == 8.4
    resource = _resource_receipt()
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    lifecycle = authorize_pod_lifecycle(
        snapshot, resource, maximum_lifecycle_seconds=7200, now=now
    )
    assert lifecycle["billable_seconds_upper_bound"] == 7620
    assert lifecycle["cumulative_billable_seconds_upper_bound"] == 7620
    segment = authorize_paid_segment(
        snapshot,
        lifecycle,
        maximum_seconds=3600,
        now=now,
    )
    assert segment["maximum_seconds"] == 3600
    exhausted = dict(snapshot)
    exhausted["conservative_task_cost_usd"] = 9.0
    with pytest.raises(FullModelTrainingError, match="plan099_budget_exhausted"):
        validate_budget_snapshot(exhausted)


def test_cli_creates_budget_resource_and_accepts_real_l40s_visible_memory(
    tmp_path: Path,
) -> None:
    budget_path = tmp_path / "budget.json"
    assert (
        plan099_main(
            [
                "create-budget-snapshot",
                "--captured-at",
                "2026-08-28T12:00:00Z",
                "--baseline-available-balance-usd",
                "10",
                "--baseline-known-unsettled-usd",
                "1",
                "--baseline-volume-rate-usd-per-hour",
                "0.1",
                "--current-available-balance-usd",
                "9.5",
                "--current-known-unsettled-usd",
                "1.1",
                "--current-volume-rate-usd-per-hour",
                "0.1",
                "--conservative-task-cost-usd",
                "4",
                "--closure-reserve-usd",
                "1",
                "--next-action",
                "commissioning",
                "--output",
                str(budget_path),
            ]
        )
        == 0
    )
    budget = json.loads(budget_path.read_text(encoding="utf-8"))
    assert budget == create_budget_snapshot(
        captured_at="2026-08-28T12:00:00Z",
        stage_b_baseline_available_balance_usd=10.0,
        stage_b_baseline_known_unsettled_usd=1.0,
        stage_b_baseline_volume_rate_usd_per_hour=0.1,
        current_available_balance_usd=9.5,
        current_known_unsettled_usd=1.1,
        current_volume_rate_usd_per_hour=0.1,
        conservative_task_cost_usd=4.0,
        closure_reserve_usd=1.0,
        next_action="commissioning",
    )
    assert budget_path.read_bytes() == pretty_json_bytes(budget)
    assert os.stat(budget_path).st_mode & 0o777 == 0o600

    resource_path = tmp_path / "resource.json"
    visible_memory = 46_068 * 1024**2
    assert MINIMUM_L40S_VISIBLE_MEMORY_BYTES <= visible_memory < 48 * 1024**3
    assert (
        plan099_main(
            [
                "create-live-resource-receipt",
                "--captured-at",
                "2026-08-28T12:00:00Z",
                "--provider",
                "RunPod",
                "--cloud-type",
                "SECURE",
                "--data-center-id",
                "US-TX-3",
                "--pod-id",
                "pod099",
                "--pod-name",
                "rondo-plan099-test",
                "--pod-started-at",
                "2026-08-28T12:00:00Z",
                "--account-task-pod-count",
                "1",
                "--task-cumulative-pods-created",
                "1",
                "--task-prior-pod-wall-seconds",
                "0",
                "--gpu-name",
                "NVIDIA L40S",
                "--gpu-count",
                "1",
                "--gpu-total-memory-bytes",
                str(visible_memory),
                "--compute-rate-usd-per-hour",
                "0.5",
                "--container-rate-usd-per-hour",
                "0.1",
                "--container-disk-gb",
                "20",
                "--image-identity",
                "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
                "--volume-id",
                "mwemzrn33y",
                "--volume-mount-path",
                "/workspace",
                "--volume-size-gb",
                "70",
                "--output",
                str(resource_path),
            ]
        )
        == 0
    )
    resource = json.loads(resource_path.read_text(encoding="utf-8"))
    assert resource == validate_live_resource_receipt(resource)
    assert resource_path.read_bytes() == pretty_json_bytes(resource)
    assert os.stat(resource_path).st_mode & 0o777 == 0o600

    environment_core = {
        "schema": "rondo-publication-critic-plan099-environment-receipt-v1",
        "python": "3.12.3",
        "torch": "2.8.0+cu128",
        "cuda": "12.8",
        "transformers": "4.52.3",
        "tokenizers": "0.21.4",
        "huggingface_hub": "0.36.2",
        "safetensors": "0.5.3",
        "psutil": "7.0.0",
        "gpu_name": "NVIDIA L40S",
        "gpu_count": 1,
        "gpu_total_memory_bytes": visible_memory,
        "image_identity": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
        "live_resource_receipt_sha256": resource["content_sha256"],
        "pod_id": resource["pod_id"],
        "pod_name": resource["pod_name"],
    }
    environment = {
        **environment_core,
        "content_sha256": hashlib.sha256(
            canonical_json_bytes(environment_core)
        ).hexdigest(),
    }
    assert (
        _validate_environment_receipt(environment, expected_resource=resource)
        == environment
    )

    below_floor = dict(resource)
    below_floor["gpu_total_memory_bytes"] = MINIMUM_L40S_VISIBLE_MEMORY_BYTES - 1
    core = {key: value for key, value in below_floor.items() if key != "content_sha256"}
    below_floor["content_sha256"] = hashlib.sha256(
        canonical_json_bytes(core)
    ).hexdigest()
    with pytest.raises(
        FullModelTrainingError, match="plan099_live_resource_receipt_invalid"
    ):
        validate_live_resource_receipt(below_floor)

    identity_path = tmp_path / "runtime-local/source-identity.json"
    assembled = {
        "schema": "rondo-publication-critic-plan099-execution-root-v1",
        "commit": "a" * 40,
        "source_archive_sha256": "b" * 64,
        "data_archive_sha256": "c" * 64,
        "freeze_sha256": "d" * 64,
    }
    with patch(
        "rondo_eval.publication_critic.full_model_training.plan099_cli.assemble_execution_root",
        return_value=assembled,
    ):
        assert (
            plan099_main(
                [
                    "assemble-execution-root",
                    "--source-archive",
                    str(tmp_path / "source.tar"),
                    "--data-archive",
                    str(tmp_path / "data.tar"),
                    "--source-sha256",
                    "b" * 64,
                    "--data-sha256",
                    "c" * 64,
                    "--commit",
                    "a" * 40,
                    "--output",
                    str(tmp_path / "source"),
                    "--identity-output",
                    str(identity_path),
                ]
            )
            == 0
        )
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    assert identity == {
        "commit": "a" * 40,
        "source_archive_sha256": "b" * 64,
        "freeze_sha256": "d" * 64,
    }
    assert identity_path.read_bytes() == pretty_json_bytes(identity)
    assert os.stat(identity_path).st_mode & 0o777 == 0o600


def test_plan099_guard_consumes_absolute_trigger_and_closes_exact_pod() -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    authorization = authorize_pod_lifecycle(
        _budget_snapshot(),
        _resource_receipt(),
        maximum_lifecycle_seconds=120,
        now=now,
    )
    clock = [now]
    calls: list[tuple[str, str, datetime, float]] = []

    def sleeper(seconds: float) -> None:
        clock[0] += timedelta(seconds=seconds)

    def terminate(receipt: Mapping[str, Any], captured: datetime, timeout: float):
        calls.append((receipt["pod_id"], receipt["pod_name"], captured, timeout))
        return {
            "deleted_pod": {
                "id": receipt["pod_id"],
                "name": receipt["pod_name"],
            },
            "pod_count": 0,
            "compute_rate_usd_per_hour": 0.0,
        }

    result = guard.enforce_lifecycle(
        authorization,
        terminator=terminate,
        validator=validate_pod_lifecycle_authorization,
        result_schema=guard.PLAN099_RESULT_SCHEMA,
        now=lambda: clock[0],
        sleeper=sleeper,
    )
    assert calls == [
        (
            "pod099",
            "rondo-plan099-test",
            now + timedelta(seconds=180),
            360.0,
        )
    ]
    assert result["schema"] == guard.PLAN099_RESULT_SCHEMA
    assert result["status"] == "pod_absent_confirmed"
    assert guard.PROFILES["plan099"]["task_prefix"] == "rondo-plan099-"
    assert guard.PROFILES["plan099"]["started_at_field"] == "pod_started_at"
    terminal = {
        "deleted_pod": {"id": "pod099", "name": "rondo-plan099-test"},
        "pod_count": 0,
        "compute_rate_usd_per_hour": 0.0,
    }
    with patch.object(
        guard.subprocess,
        "run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(terminal), stderr=""
        ),
    ) as run_terminal:
        assert (
            guard._run_terminal(
                Path("terminal-helper.py"),
                "runpodctl",
                authorization,
                now,
                360.0,
                task_prefix="rondo-plan099-",
                started_at_field="pod_started_at",
            )
            == terminal
        )
    command = run_terminal.call_args.args[0]
    assert command[command.index("--task-pod-name-prefix") + 1] == "rondo-plan099-"
    assert (
        command[command.index("--task-started-at") + 1]
        == (authorization["pod_started_at"])
    )

    late_clock = [now]

    def late_sleeper(seconds: float) -> None:
        late_clock[0] += timedelta(seconds=seconds)

    def late_terminator(
        receipt: Mapping[str, Any], captured: datetime, timeout: float
    ) -> Mapping[str, Any]:
        del captured, timeout
        late_clock[0] += timedelta(seconds=361)
        return {
            "deleted_pod": {"id": receipt["pod_id"], "name": receipt["pod_name"]},
            "pod_count": 0,
            "compute_rate_usd_per_hour": 0.0,
        }

    with pytest.raises(
        guard.LifecycleGuardError, match="terminal_confirmation_deadline_exceeded"
    ):
        guard.enforce_lifecycle(
            authorization,
            terminator=late_terminator,
            validator=validate_pod_lifecycle_authorization,
            result_schema=guard.PLAN099_RESULT_SCHEMA,
            now=lambda: late_clock[0],
            sleeper=late_sleeper,
        )

    boundary = authorize_pod_lifecycle(
        _budget_snapshot(),
        _resource_receipt(),
        maximum_lifecycle_seconds=10_380,
        now=now,
    )
    assert boundary["billable_seconds_upper_bound"] == 10_800
    assert boundary["cumulative_billable_seconds_upper_bound"] == 10_800
    assert boundary["termination_trigger_at"] == "2026-08-28T14:54:00Z"
    assert (
        authorize_paid_segment(
            _budget_snapshot(), boundary, maximum_seconds=10_380, now=now
        )["maximum_seconds"]
        == 10_380
    )
    with pytest.raises(
        FullModelTrainingError, match="plan099_segment_duration_invalid"
    ):
        authorize_paid_segment(
            _budget_snapshot(), boundary, maximum_seconds=10_381, now=now
        )
    with pytest.raises(FullModelTrainingError, match="plan099_lifecycle_invalid"):
        authorize_pod_lifecycle(
            _budget_snapshot(),
            _resource_receipt(),
            maximum_lifecycle_seconds=10_381,
            now=now,
        )

    replacement = authorize_pod_lifecycle(
        _budget_snapshot(),
        _resource_receipt(prior_wall_seconds=4_000, cumulative_pods=2),
        maximum_lifecycle_seconds=6_380,
        now=now,
    )
    assert replacement["billable_seconds_upper_bound"] == 6_800
    assert replacement["cumulative_billable_seconds_upper_bound"] == 10_800
    with pytest.raises(FullModelTrainingError, match="plan099_lifecycle_invalid"):
        authorize_pod_lifecycle(
            _budget_snapshot(),
            _resource_receipt(prior_wall_seconds=4_000, cumulative_pods=2),
            maximum_lifecycle_seconds=6_381,
            now=now,
        )

    tampered = dict(replacement)
    tampered["cumulative_billable_seconds_upper_bound"] -= 1
    core = {key: value for key, value in tampered.items() if key != "content_sha256"}
    tampered["content_sha256"] = hashlib.sha256(canonical_json_bytes(core)).hexdigest()
    with pytest.raises(FullModelTrainingError, match="plan099_lifecycle_invalid"):
        validate_pod_lifecycle_authorization(tampered)


def test_plan099_bootstrap_reuses_exact_image_torch_and_guard_is_host_armed(
    tmp_path: Path,
) -> None:
    bootstrap = REPO_ROOT / "training/publication-critic-plan099/runpod-bootstrap.sh"
    worker = REPO_ROOT / "training/publication-critic-plan099/runpod-worker.sh"
    subprocess.run(["bash", "-n", str(bootstrap)], check=True, timeout=10)
    subprocess.run(["bash", "-n", str(worker)], check=True, timeout=10)
    source = bootstrap.read_text(encoding="utf-8")
    assert 'python3 -m venv --copies --system-site-packages "$task_root/venv"' in source
    assert source.count('torch.__version__ == "2.8.0+cu128"') == 2
    assert source.count('torch.version.cuda == "12.8"') == 2
    assert "validate-runtime-controls" in source
    assert '--identity-output "$runtime_local/source-identity.json"' in source
    assert "--no-cache-dir" in source
    assert '"$task_root/venv/bin/python" -m pip check' in source
    assert (
        'exec timeout --signal=TERM --kill-after=60s "$RONDO_PLAN099_MAX_SECONDS"'
        in source
    )
    assert "RONDO_PLAN099_BOOTSTRAP_INNER=1" in source
    venv = tmp_path / "worker-venv"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "venv",
            "--copies",
            "--system-site-packages",
            str(venv),
        ],
        check=True,
        timeout=30,
    )
    python = venv / "bin/python"
    worker_condition = 'if [ ! -x "$python" ] || [ -L "$python" ]; then exit 2; fi'
    worker_source = worker.read_text(encoding="utf-8")
    assert worker_condition in worker_source
    assert (
        'runtime_root="/run/rondo-plan099-${RONDO_PLAN099_VALIDATED_ACTUAL_POD_ID}/runtime-control"'
        in worker_source
    )
    assert "z1z3m7n90nz4xr) exit 2" in worker_source
    assert (
        '--validated-actual-pod-id "$RONDO_PLAN099_VALIDATED_ACTUAL_POD_ID"' in source
    )
    assert (
        '--validated-actual-pod-name "$RONDO_PLAN099_VALIDATED_ACTUAL_POD_NAME"'
        in source
    )
    assert 'case "$resource" in "$runtime_root/live-resource/"*.json)' in worker_source
    assert 'case "$lifecycle" in "$runtime_root/lifecycle/"*.json)' in worker_source
    assert 'case "$segment" in "$runtime_root/segment/"*.json)' in worker_source
    assert 'case "$resource" in "$task_root"/*)' not in worker_source
    subprocess.run(
        [
            "bash",
            "-c",
            f'python="$1"; {worker_condition}',
            "plan099-worker-check",
            str(python),
        ],
        check=True,
        timeout=10,
    )
    assert python.is_file()
    assert not python.is_symlink()
    dependencies = (
        REPO_ROOT / "training/publication-critic-plan099/dependencies-v1.txt"
    ).read_text(encoding="utf-8")
    assert not any(
        line.strip().lower().startswith("torch")
        for line in dependencies.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    runbook = (REPO_ROOT / "training/publication-critic-plan099/runbook.md").read_text(
        encoding="utf-8"
    )
    assert "由开发工具持有的长期 exec 会话持续托管" in runbook
    assert "nohup setsid env RONDO_PLAN099_STAGE_B_APPROVED=1" not in runbook
    assert "--profile plan099" in runbook
    assert "正常提前释放仍只接受指定 queue" in runbook


def test_runtime_control_allowlist_accepts_only_exact_canonical_chain(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    run_base = tmp_path / "run"
    run_base.mkdir(mode=0o700)
    pod_ids = ("replacement099a", "replacement099b")
    pod_names = (
        "rondo-plan099-20260829-stageb02a",
        "rondo-plan099-20260829-stageb02b",
    )

    def create_chain(
        pod_id: str, pod_name: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        resource = _resource_receipt(pod_id=pod_id, pod_name=pod_name)
        lifecycle = authorize_pod_lifecycle(
            _budget_snapshot(), resource, maximum_lifecycle_seconds=7200, now=now
        )
        segment = authorize_paid_segment(
            _budget_snapshot(), lifecycle, maximum_seconds=3600, now=now
        )
        return resource, lifecycle, segment

    with patch(
        "rondo_eval.publication_critic.full_model_training.plan099_contract."
        "RUNTIME_CONTROL_BASE",
        run_base,
    ):
        chains = [
            create_chain(pod_id, pod_name)
            for pod_id, pod_name in zip(pod_ids, pod_names, strict=True)
        ]
        roots: list[Path] = []
        paths_by_pod: list[dict[str, Path]] = []
        for pod_id, chain in zip(pod_ids, chains, strict=True):
            runtime_root = plan099_runtime_control_root(pod_id)
            runtime_root.parent.mkdir(mode=0o700)
            runtime_root.mkdir(mode=0o700)
            roots.append(runtime_root)
            values = dict(zip(("live-resource", "lifecycle", "segment"), chain))
            paths: dict[str, Path] = {}
            for role, value in values.items():
                directory = runtime_root / role
                directory.mkdir(mode=0o700)
                path = directory / f"{value['content_sha256']}.json"
                path.write_bytes(pretty_json_bytes(value))
                path.chmod(0o600)
                paths[role] = path
                assert (
                    validate_runtime_control_file(role, path, runtime_root, pod_id)
                    == value
                )
            paths_by_pod.append(paths)

        assert roots[0] != roots[1]
        resource, lifecycle, segment = chains[0]
        runtime_root = roots[0]
        paths = paths_by_pod[0]
        assert (
            validate_current_pod_runtime_control_chain(
                resource,
                lifecycle,
                segment,
                validated_actual_pod_id=pod_ids[0],
                validated_actual_pod_name=pod_names[0],
            )["resource"]["pod_id"]
            == pod_ids[0]
        )

        wrong_path = runtime_root / "live-resource" / ("0" * 64 + ".json")
        wrong_path.write_bytes(pretty_json_bytes(resource))
        wrong_path.chmod(0o600)
        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_invalid"
        ):
            validate_runtime_control_file(
                "live-resource", wrong_path, runtime_root, pod_ids[0]
            )

        noncanonical = paths["segment"]
        noncanonical.write_bytes(json.dumps(segment, sort_keys=True).encode("utf-8"))
        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_invalid"
        ):
            validate_runtime_control_file(
                "segment", noncanonical, runtime_root, pod_ids[0]
            )
        noncanonical.write_bytes(pretty_json_bytes(segment))

        paths["live-resource"].chmod(0o644)
        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_invalid"
        ):
            validate_runtime_control_file(
                "live-resource", paths["live-resource"], runtime_root, pod_ids[0]
            )
        paths["live-resource"].chmod(0o600)

        oversized = (
            runtime_root / "live-resource" / f"{resource['content_sha256']}.json"
        )
        original = oversized.read_bytes()
        oversized.write_bytes(b" " * (16 * 1024 + 1))
        oversized.chmod(0o600)
        with pytest.raises(FullModelTrainingError, match="regular_file_too_large"):
            validate_runtime_control_file(
                "live-resource", oversized, runtime_root, pod_ids[0]
            )
        oversized.write_bytes(original)
        oversized.chmod(0o600)

        symlink = runtime_root / "live-resource" / ("1" * 64 + ".json")
        symlink.symlink_to(paths["live-resource"])
        with pytest.raises(FullModelTrainingError, match="regular_file_required"):
            validate_runtime_control_file(
                "live-resource", symlink, runtime_root, pod_ids[0]
            )

        workspace_copy = tmp_path / "workspace-runtime-control.json"
        workspace_copy.write_bytes(pretty_json_bytes(resource))
        workspace_copy.chmod(0o666)
        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_invalid"
        ):
            validate_runtime_control_file(
                "live-resource", workspace_copy, runtime_root, pod_ids[0]
            )

        other_run_root = tmp_path / "other-run" / "runtime-control"
        (other_run_root / "live-resource").mkdir(parents=True, mode=0o700)
        other_run_root.parent.chmod(0o700)
        other_run_root.chmod(0o700)
        other_path = other_run_root / "live-resource" / paths["live-resource"].name
        other_path.write_bytes(paths["live-resource"].read_bytes())
        other_path.chmod(0o600)
        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_invalid"
        ):
            validate_runtime_control_file(
                "live-resource", other_path, other_run_root, pod_ids[0]
            )

        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_invalid"
        ):
            validate_runtime_control_file(
                "live-resource", paths["live-resource"], runtime_root, pod_ids[1]
            )

        (runtime_root / "lifecycle").chmod(0o755)
        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_invalid"
        ):
            validate_runtime_control_file(
                "lifecycle", paths["lifecycle"], runtime_root, pod_ids[0]
            )
        (runtime_root / "lifecycle").chmod(0o700)

        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_pod_not_approved"
        ):
            plan099_runtime_control_root("z1z3m7n90nz4xr")
        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_pod_not_approved"
        ):
            validate_current_pod_runtime_control_chain(
                resource,
                lifecycle,
                segment,
                validated_actual_pod_id=pod_ids[1],
                validated_actual_pod_name=pod_names[1],
            )

        other_resource = _resource_receipt(
            prior_wall_seconds=1,
            pod_id=pod_ids[0],
            pod_name=pod_names[0],
        )
        other_lifecycle = authorize_pod_lifecycle(
            _budget_snapshot(),
            other_resource,
            maximum_lifecycle_seconds=7199,
            now=now,
        )
        other_segment = authorize_paid_segment(
            _budget_snapshot(), other_lifecycle, maximum_seconds=3600, now=now
        )
        with pytest.raises(
            FullModelTrainingError, match="plan099_runtime_control_chain_invalid"
        ):
            validate_runtime_control_chain(resource, other_lifecycle, other_segment)

        assert os.stat(paths["live-resource"]).st_mode & 0o777 == 0o600


def test_fake_formal_checkpoint_first_recovery_selection_and_retention(
    tmp_path: Path,
) -> None:
    freeze = load_freeze(REPO_ROOT)
    train = load_train_dataset(REPO_ROOT)
    validation = load_validation_dataset(REPO_ROOT)
    store = Plan099ArtifactStore(tmp_path / "artifacts")
    source_identity = _source_identity(freeze)
    first = _FakeAdapter(validation)
    controller = Plan099TrainingController(
        freeze=freeze,
        run_kind="formal",
        namespace="rondo-plan099-formal-fake",
        source_identity=source_identity,
        artifact_store=store,
        process_nonce="first-process",
    )
    controller.initialize(first, validation)
    stopped = controller.run(first, training=train, validation=validation)
    assert stopped["status"] == "recovery_required"
    assert stopped["current_step"] == 8
    assert store.has_evaluation_result("checkpoint-attempt-0-step-000008")

    second = _FakeAdapter(validation)
    controller.resume_fresh_process(
        second,
        checkpoint_id="checkpoint-attempt-0-step-000008",
        validation=validation,
        process_nonce="second-process",
    )
    stopped_for_best = controller.run(second, training=train, validation=validation)
    assert stopped_for_best["status"] == "recovery_required"
    assert stopped_for_best["recovery_checkpoint_id"] == (
        "checkpoint-attempt-0-step-000002"
    )
    third = _FakeAdapter(validation)
    terminal = controller.resume_fresh_process(
        third,
        checkpoint_id="checkpoint-attempt-0-step-000002",
        validation=validation,
        process_nonce="third-process",
    )
    assert terminal["status"] == "terminal"
    assert terminal["terminal"]["disposition"] == "CANDIDATE"
    assert terminal["terminal"]["best_checkpoint_id"] == (
        "checkpoint-attempt-0-step-000002"
    )
    assert set(terminal["fresh_process_recoveries"]) == {
        "checkpoint-attempt-0-step-000002",
        "checkpoint-attempt-0-step-000008",
    }
    kept = terminal["terminal"]["retention"]["kept_checkpoints"]
    assert kept == [
        "checkpoint-attempt-0-step-000002",
        "checkpoint-attempt-0-step-000008",
        "checkpoint-attempt-0-step-000016",
    ]
    assert len(list((store.root / "recovery-checkpoints").iterdir())) == 3
    assert len(store.evaluation_result_ids()) == 5
    assert validate_terminal_candidate(terminal, store)["checkpoint_id"] == (
        "checkpoint-attempt-0-step-000002"
    )
    candidate = tmp_path / "candidate"
    _export_candidate(terminal, store.root, candidate)
    assert verify_candidate_handoff(candidate)["status"] == "verified"

    before_terminal = json.loads(json.dumps(terminal))
    before_terminal["status"] = "paused"
    before_terminal["terminal"] = None
    reentered = Plan099TrainingController.from_state(
        freeze=freeze, artifact_store=store, value=before_terminal
    )
    reentered._finish()
    assert reentered.state["terminal"]["disposition"] == "CANDIDATE"


def test_early_missing_decision_config_can_still_form_candidate(
    tmp_path: Path,
) -> None:
    freeze = load_freeze(REPO_ROOT)
    train = load_train_dataset(REPO_ROOT)
    validation = load_validation_dataset(REPO_ROOT)
    store = Plan099ArtifactStore(tmp_path / "artifacts")
    controller = _new_formal_controller(freeze, store, "early-none")
    first = _FakeAdapter(validation, gold_from_step=8)
    controller.initialize(first, validation)
    controller.run(first, training=train, validation=validation)
    assert [
        store.read_evaluation_result(checkpoint_id)["assessment"]
        for checkpoint_id in (
            "checkpoint-attempt-0-step-000002",
            "checkpoint-attempt-0-step-000004",
        )
    ] == [None, None]
    second = _FakeAdapter(validation, gold_from_step=8)
    controller.resume_fresh_process(
        second,
        checkpoint_id="checkpoint-attempt-0-step-000008",
        validation=validation,
        process_nonce="early-none-second",
    )
    terminal = controller.run(second, training=train, validation=validation)
    assert terminal["terminal"]["disposition"] == "CANDIDATE"
    candidate = tmp_path / "candidate"
    _export_candidate(terminal, store.root, candidate)
    verify_candidate_handoff(candidate)


def test_all_missing_decision_configs_finish_as_valid_no_go(tmp_path: Path) -> None:
    freeze = load_freeze(REPO_ROOT)
    train = load_train_dataset(REPO_ROOT)
    validation = load_validation_dataset(REPO_ROOT)
    store = Plan099ArtifactStore(tmp_path / "artifacts")
    controller = _new_formal_controller(freeze, store, "all-none")
    first = _FakeAdapter(validation, gold_from_step=None)
    controller.initialize(first, validation)
    controller.run(first, training=train, validation=validation)
    second = _FakeAdapter(validation, gold_from_step=None)
    controller.resume_fresh_process(
        second,
        checkpoint_id="checkpoint-attempt-0-step-000008",
        validation=validation,
        process_nonce="all-none-second",
    )
    terminal = controller.run(second, training=train, validation=validation)
    assert terminal["status"] == "terminal"
    assert terminal["terminal"]["disposition"] == "NO-GO"
    assert terminal["terminal"]["best_checkpoint_id"] is None
    assert terminal["terminal"]["retention"]["kept_checkpoints"] == [
        "checkpoint-attempt-0-step-000008",
        "checkpoint-attempt-0-step-000016",
    ]


def test_step12_continuation_ignores_stale_recovery_pointer(tmp_path: Path) -> None:
    freeze = load_freeze(REPO_ROOT)
    train = load_train_dataset(REPO_ROOT)
    validation = load_validation_dataset(REPO_ROOT)
    store = Plan099ArtifactStore(tmp_path / "artifacts")
    controller = _new_formal_controller(freeze, store, "step12")
    first = _FakeAdapter(validation)
    controller.initialize(first, validation)
    controller.run(first, training=train, validation=validation)
    second = _FakeAdapter(validation)
    controller.resume_fresh_process(
        second,
        checkpoint_id="checkpoint-attempt-0-step-000008",
        validation=validation,
        process_nonce="step12-second",
    )
    paused = controller.run(
        second, training=train, validation=validation, stop_after=12
    )
    assert paused["status"] == "paused"
    assert paused["recovery_checkpoint_id"] is None
    stale = json.loads(json.dumps(paused))
    stale["recovery_checkpoint_id"] = "checkpoint-attempt-0-step-000008"
    assert _resume_checkpoint(stale, store) == (
        "checkpoint-attempt-0-step-000012",
        False,
    )
    resumed = Plan099TrainingController.from_state(
        freeze=freeze, artifact_store=store, value=paused
    )
    resumed.recover_latest_for_continuation(
        _FakeAdapter(validation),
        checkpoint_id="checkpoint-attempt-0-step-000012",
        validation=validation,
        process_nonce="step12-third",
    )
    assert resumed.state["current_step"] == 12


def test_orphan_checkpoint_is_adopted_only_from_exact_predecessor(
    tmp_path: Path,
) -> None:
    freeze = load_freeze(REPO_ROOT)
    train = load_train_dataset(REPO_ROOT)
    validation = load_validation_dataset(REPO_ROOT)
    store = _InterruptAfterCheckpointStore(tmp_path / "artifacts")
    published: list[dict[str, Any]] = []
    controller = Plan099TrainingController(
        freeze=freeze,
        run_kind="formal",
        namespace="rondo-plan099-formal-orphan",
        source_identity=_source_identity(freeze),
        artifact_store=store,
        process_nonce="orphan-first",
        state_publisher=lambda value: published.append(json.loads(json.dumps(value))),
    )
    first = _FakeAdapter(validation)
    controller.initialize(first, validation)
    with pytest.raises(RuntimeError, match="checkpoint-published-process-loss"):
        controller.run(first, training=train, validation=validation, stop_after=2)
    durable = published[-1]
    assert durable["current_step"] == 0
    assert _resume_checkpoint(durable, store) == (
        "checkpoint-attempt-0-step-000002",
        True,
    )
    resumed = Plan099TrainingController.from_state(
        freeze=freeze, artifact_store=store, value=durable
    )
    result = resumed.adopt_orphan_checkpoint(
        _FakeAdapter(validation),
        checkpoint_id="checkpoint-attempt-0-step-000002",
        validation=validation,
        process_nonce="orphan-second",
    )
    assert result["status"] == "paused"
    assert result["current_step"] == 2
    assert store.has_evaluation_result("checkpoint-attempt-0-step-000002")


def test_terminal_retention_marker_publish_is_reentrant(tmp_path: Path) -> None:
    freeze = load_freeze(REPO_ROOT)
    train = load_train_dataset(REPO_ROOT)
    validation = load_validation_dataset(REPO_ROOT)
    store = _InterruptAfterRetentionStore(tmp_path / "artifacts")
    controller = _new_formal_controller(freeze, store, "retention-reentry")
    first = _FakeAdapter(validation)
    controller.initialize(first, validation)
    controller.run(first, training=train, validation=validation)
    second = _FakeAdapter(validation)
    controller.resume_fresh_process(
        second,
        checkpoint_id="checkpoint-attempt-0-step-000008",
        validation=validation,
        process_nonce="retention-second",
    )
    controller.run(second, training=train, validation=validation)
    third = _FakeAdapter(validation)
    store.interrupt = True
    with pytest.raises(RuntimeError, match="retention-published-process-loss"):
        controller.resume_fresh_process(
            third,
            checkpoint_id="checkpoint-attempt-0-step-000002",
            validation=validation,
            process_nonce="retention-third",
        )
    assert controller.state["status"] == "paused"
    store.interrupt = False
    controller._finish()
    assert controller.state["terminal"]["disposition"] == "CANDIDATE"


def test_checkpoint_state_survives_process_loss_before_evaluation(
    tmp_path: Path,
) -> None:
    freeze = load_freeze(REPO_ROOT)
    train = load_train_dataset(REPO_ROOT)
    validation = load_validation_dataset(REPO_ROOT)
    store = Plan099ArtifactStore(tmp_path / "artifacts")
    published: list[dict[str, Any]] = []

    def interrupt(value: Mapping[str, Any]) -> None:
        published.append(json.loads(json.dumps(value)))
        if value["status"] == "evaluation_pending":
            raise RuntimeError("simulated-process-loss")

    controller = Plan099TrainingController(
        freeze=freeze,
        run_kind="formal",
        namespace="rondo-plan099-formal-interrupted",
        source_identity={
            "commit": "a" * 40,
            "source_archive_sha256": "b" * 64,
            "freeze_sha256": hashlib.sha256(canonical_json_bytes(freeze)).hexdigest(),
        },
        artifact_store=store,
        process_nonce="lost-process",
        state_publisher=interrupt,
    )
    adapter = _FakeAdapter(validation)
    controller.initialize(adapter, validation)
    with pytest.raises(RuntimeError, match="simulated-process-loss"):
        controller.run(adapter, training=train, validation=validation, stop_after=2)
    durable = published[-1]
    assert durable["status"] == "evaluation_pending"
    assert durable["pending_checkpoint_id"] == "checkpoint-attempt-0-step-000002"

    resumed = Plan099TrainingController.from_state(
        freeze=freeze, artifact_store=store, value=durable
    )
    recovered = resumed.recover_pending_evaluation(
        _FakeAdapter(validation), validation=validation
    )
    assert recovered["status"] == "paused"
    assert recovered["pending_checkpoint_id"] is None
    assert store.has_evaluation_result("checkpoint-attempt-0-step-000002")


class _FakeAdapter:
    training_state_codec = "plan099-fake-state-v1"

    def __init__(self, validation: Any, *, gold_from_step: int | None = 1) -> None:
        self.validation = validation
        self.global_step = 0
        self.gold_from_step = gold_from_step

    def current_model_artifact_sha256(self) -> str:
        return hashlib.sha256(f"fake-model-{self.global_step}".encode()).hexdigest()

    def runtime_identity(self) -> dict[str, Any]:
        return {"runtime": "fake", "global_step": self.global_step}

    def apply_update(self, dataset: Any) -> dict[str, Any]:
        self.global_step += 1
        return {
            "schema": "rondo-publication-critic-plan099-update-receipt-v1",
            "global_step": self.global_step,
            "dataset_split": dataset.split,
            "candidate_rows": len(dataset.candidates),
            "pair_rows": len(dataset.pairs),
            "losses": {"total": 1.0 / (self.global_step + 1)},
            "gradient_norm_before_clip": 1.0,
            "maximum_parameter_delta": 0.1,
        }

    def evaluate(self, dataset: Any) -> dict[str, Any]:
        rows = (
            _gold_logits(dataset.candidates)
            if self.gold_from_step is not None
            and self.global_step >= self.gold_from_step
            else _all_pass_logits(len(dataset.candidates))
        )
        return {
            "flat_logits": rows,
            "structured_output": structured_output_from_flat(rows),
            "losses": {
                "dimension": 0.1,
                "gate": 0.1,
                "boundary": 0.1,
                "invariance": 0.1,
                "total": 0.2,
            },
        }

    def save_model(self, destination: Path) -> None:
        freeze = load_freeze(REPO_ROOT)
        identity = model_identity(
            freeze_sha256=hashlib.sha256(canonical_json_bytes(freeze)).hexdigest(),
            source_commit="a" * 40,
            model_contract=freeze["model"],
        )
        config = {
            "model_type": "fake",
            "rondo_publication_critic": {
                "schema": "rondo-publication-critic-plan099-five-head-config-v1",
                "logical_head_order": list(HARD_DIMENSIONS),
                "classes": {
                    key: list(DIMENSION_CLASSES[key]) for key in HARD_DIMENSIONS
                },
                "flat_logit_count": 11,
                "backbone_state_prefix": "backbone.",
            },
        }
        files = {
            "model.safetensors": f"fake-step-{self.global_step}".encode(),
            "config.json": pretty_json_bytes(config),
            "tokenizer.json": b"{}\n",
            "tokenizer_config.json": b"{}\n",
            "special_tokens_map.json": b"{}\n",
            "merges.txt": b"#version: 0.2\n",
            "vocab.json": b"{}\n",
            "chat_template.jinja": b"{{ messages }}\n",
            "rondo-plan099-model-identity.json": pretty_json_bytes(identity),
        }
        for relative, raw in files.items():
            (destination / relative).write_bytes(raw)
        metadata = {
            relative: {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
            for relative, raw in sorted(files.items())
        }
        manifest = {
            "schema": "rondo-publication-critic-plan099-inference-ready-manifest-v1",
            "files": metadata,
            "exact_tree_sha256": hashlib.sha256(
                canonical_json_bytes(metadata)
            ).hexdigest(),
        }
        (destination / "inference-manifest.json").write_bytes(
            pretty_json_bytes(manifest)
        )
        verify_inference_ready(destination)

    def capture_training_state(self, selection: Mapping[str, Any]) -> dict[str, Any]:
        return {"global_step": self.global_step, "selection": dict(selection)}

    def write_training_state(self, destination: Path, value: Mapping[str, Any]) -> None:
        destination.mkdir(mode=0o700)
        (destination / "state.json").write_bytes(pretty_json_bytes(value))

    def read_training_state(self, root: Path) -> Mapping[str, Any]:
        return json.loads((root / "state.json").read_text(encoding="utf-8"))

    def restore(self, model_root: Path, state: Mapping[str, Any]) -> None:
        verify_inference_ready(model_root)
        self.global_step = int(state["global_step"])


class _InterruptAfterCheckpointStore(Plan099ArtifactStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.interrupt = True

    def save_checkpoint(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        receipt = super().save_checkpoint(*args, **kwargs)
        if self.interrupt:
            self.interrupt = False
            raise RuntimeError("checkpoint-published-process-loss")
        return receipt


class _InterruptAfterRetentionStore(Plan099ArtifactStore):
    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.interrupt = False

    def mark_retention_complete(self, checkpoint_id: str) -> dict[str, Any]:
        receipt = super().mark_retention_complete(checkpoint_id)
        if self.interrupt:
            self.interrupt = False
            raise RuntimeError("retention-published-process-loss")
        return receipt


def _new_formal_controller(
    freeze: Mapping[str, Any], store: Plan099ArtifactStore, suffix: str
) -> Plan099TrainingController:
    return Plan099TrainingController(
        freeze=freeze,
        run_kind="formal",
        namespace=f"rondo-plan099-formal-{suffix}",
        source_identity=_source_identity(freeze),
        artifact_store=store,
        process_nonce=f"{suffix}-first",
    )


def _source_identity(freeze: Mapping[str, Any]) -> dict[str, str]:
    return {
        "commit": "a" * 40,
        "source_archive_sha256": "b" * 64,
        "freeze_sha256": hashlib.sha256(canonical_json_bytes(freeze)).hexdigest(),
    }


def _budget_snapshot() -> dict[str, Any]:
    return {
        "schema": "rondo-publication-critic-plan099-budget-snapshot-v1",
        "captured_at": "2026-08-28T12:00:00Z",
        "stage_b_baseline_available_balance_usd": 10.0,
        "stage_b_baseline_known_unsettled_usd": 1.0,
        "stage_b_baseline_volume_rate_usd_per_hour": 0.1,
        "stage_b_dynamic_budget_usd": 8.4,
        "current_available_balance_usd": 10.0,
        "current_known_unsettled_usd": 1.0,
        "current_volume_rate_usd_per_hour": 0.1,
        "conservative_task_cost_usd": 4.0,
        "closure_reserve_usd": 1.0,
        "next_action": "commissioning",
    }


def _resource_receipt(
    *,
    prior_wall_seconds: int = 0,
    cumulative_pods: int = 1,
    pod_id: str = "pod099",
    pod_name: str = "rondo-plan099-test",
) -> dict[str, Any]:
    core = {
        "schema": "rondo-publication-critic-plan099-live-resource-receipt-v1",
        "captured_at": "2026-08-28T12:00:00Z",
        "provider": "RunPod",
        "cloud_type": "SECURE",
        "data_center_id": "US-TX-3",
        "pod_id": pod_id,
        "pod_name": pod_name,
        "pod_started_at": "2026-08-28T12:00:00Z",
        "account_task_pod_count": 1,
        "task_cumulative_pods_created": cumulative_pods,
        "task_prior_pod_wall_seconds": prior_wall_seconds,
        "gpu_name": "NVIDIA L40S",
        "gpu_count": 1,
        "gpu_total_memory_bytes": 48 * 1024**3,
        "compute_rate_usd_per_hour": 0.5,
        "container_rate_usd_per_hour": 0.1,
        "container_disk_gb": 20,
        "image_identity": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
        "volume_id": "mwemzrn33y",
        "volume_mount_path": "/workspace",
        "volume_size_gb": 70,
    }
    return {
        **core,
        "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
    }


def _gold_logits(candidates: Any) -> tuple[tuple[float, ...], ...]:
    rows = []
    for candidate in candidates:
        row = [0.0] * 11
        for dimension in HARD_DIMENSIONS:
            start, stop = HEAD_SLICES[dimension]
            target = DIMENSION_CLASSES[dimension].index(candidate["labels"][dimension])
            for index in range(start, stop):
                row[index] = 4.0 if index - start == target else -4.0
        rows.append(tuple(row))
    return tuple(rows)


def _all_pass_logits(rows: int) -> tuple[tuple[float, ...], ...]:
    value = []
    for dimension in HARD_DIMENSIONS:
        value.extend(
            4.0 if index == 0 else -4.0
            for index in range(len(DIMENSION_CLASSES[dimension]))
        )
    return tuple(tuple(value) for _ in range(rows))


def _pair_evaluation(dataset: Any, predicted: Any) -> dict[str, Any]:
    by_id = dict(zip(dataset.candidate_ids, predicted, strict=True))
    return evaluate_pair_predictions(
        [
            {
                "pair_id": pair["pair_id"],
                "kind": pair["kind"],
                "left_labels": by_id[pair["left_candidate_id"]],
                "right_labels": by_id[pair["right_candidate_id"]],
                "target_dimension": pair["target_dimension"],
            }
            for pair in dataset.pairs
        ]
    )
