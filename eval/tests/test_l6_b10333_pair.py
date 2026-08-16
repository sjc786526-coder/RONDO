from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from eval.tests.test_l6_paired_outputs import build_receipt, fixture_bundle
from rondo_eval.local_approval import (
    client as local_client,
    cross_eval,
    l6_b10333_pair,
    paired_outputs,
)


WORKTREE_ROOT = Path(__file__).resolve().parents[2]


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


def response(decision: dict) -> dict:
    return {
        "status": "completed",
        "model": l6_b10333_pair.MODEL_ALIAS,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(decision),
                    }
                ],
            }
        ],
    }


class RecordingFactory:
    def __init__(
        self,
        *,
        structured_failure_once: bool = False,
        structured_failure_count: int | None = None,
        timeout_once: bool = False,
        infrastructure_failure_once: bool = False,
        terminal_statuses: list[str] | None = None,
    ) -> None:
        self.events: list[tuple[str, str]] = []
        self.commands: dict[str, list[str]] = {}
        self.requests: list[tuple[str, dict]] = []
        self.structured_failure_count = (
            1 if structured_failure_once else 0
        ) if structured_failure_count is None else structured_failure_count
        self.timeout_once = timeout_once
        self.infrastructure_failure_once = infrastructure_failure_once
        self.terminal_statuses = list(terminal_statuses or [])

    def __call__(
        self,
        *,
        deployment: paired_outputs.ResolvedDeployment,
        command: list[str],
        base_url: str,
        log_path: Path,
    ):
        factory = self

        class Transport:
            def post(self, request: dict) -> dict:
                factory.events.append(("post", deployment.side))
                factory.requests.append((deployment.side, request))
                if factory.terminal_statuses:
                    status = factory.terminal_statuses.pop(0)
                    if status == "structured_output_failure":
                        raise local_client.StructuredOutputError(
                            "fixture-invalid-json"
                        )
                    if status == "timeout":
                        raise l6_b10333_pair.L6B10333RequestTimeout(
                            "fixture-timeout"
                        )
                    if status == "refusal":
                        raise paired_outputs.ModelRefusal("fixture-refusal")
                    raise AssertionError(f"unknown fixture terminal: {status}")
                if factory.timeout_once:
                    factory.timeout_once = False
                    raise l6_b10333_pair.L6B10333RequestTimeout(
                        "fixture-timeout"
                    )
                if factory.infrastructure_failure_once:
                    factory.infrastructure_failure_once = False
                    raise local_client.ServiceUnavailableError(
                        "fixture-infrastructure-failure"
                    )
                if factory.structured_failure_count:
                    factory.structured_failure_count -= 1
                    raise local_client.StructuredOutputError("fixture-invalid-json")
                return response(
                    {
                        "outcome": "allow",
                        "rationale": "Synthetic b10333 paired fixture decision.",
                        "risk_tags": [],
                    }
                )

        @contextlib.contextmanager
        def session():
            factory.events.append(("start", deployment.side))
            factory.commands[deployment.side] = list(command)
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"fixture {deployment.side} server log\n")
            os.chmod(log_path, 0o600)
            self_url = base_url
            if self_url != "http://127.0.0.1:19037/v1":
                raise AssertionError("base URL drift")
            try:
                yield Transport()
            finally:
                factory.events.append(("stop", deployment.side))

        return session()


class B10333CommandTests(unittest.TestCase):
    def _runtime(self, directory: Path) -> Path:
        path = directory / "llama-server"
        path.write_bytes(b"fixture-b10333-runtime")
        os.chmod(path, 0o755)
        return path

    def test_exact_adapter_on_off_and_paired_gguf_argv(self) -> None:
        for deployment_mode in ("adapter_on_off", "paired_gguf"):
            with self.subTest(deployment_mode=deployment_mode), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                built = build_receipt(directory, deployment_mode=deployment_mode)
                _receipt, _sha, _contracts, deployments = (
                    paired_outputs._revalidate_built_pair_receipt(built)
                )
                runtime = self._runtime(directory)
                template = dict(built.sources)["chat-template"].path
                with mock.patch.object(
                    l6_b10333_pair,
                    "FROZEN_SERVER_SHA256",
                    digest_bytes(runtime.read_bytes()),
                ):
                    commands = {
                        side: l6_b10333_pair.build_b10333_command(
                            deployments[side],
                            runtime_binary=runtime,
                            chat_template=template,
                            port=19037,
                        )
                        for side in paired_outputs.LOCAL_SIDE_ORDER
                    }
                common_prefix = [
                    os.fspath(runtime.resolve()),
                    "--offline",
                    "--no-models-autoload",
                    "--no-ui",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "19037",
                    "--model",
                ]
                common_tail = [
                    "--alias",
                    "rondo-l6-paired-approval",
                    "--no-mmproj",
                    "--gpu-layers",
                    "auto",
                    "--split-mode",
                    "none",
                    "--main-gpu",
                    "0",
                    "--fit",
                    "on",
                    "--ctx-size",
                    "12288",
                    "--batch-size",
                    "512",
                    "--ubatch-size",
                    "256",
                    "--parallel",
                    "1",
                    "--verbosity",
                    "3",
                    "--flash-attn",
                    "on",
                    "--cache-type-k",
                    "f16",
                    "--cache-type-v",
                    "f16",
                    "--jinja",
                    "--chat-template-file",
                    os.fspath(template.resolve()),
                    "--metrics",
                    "--slots",
                ]
                self.assertEqual(
                    commands["local-static"],
                    [
                        *common_prefix,
                        os.fspath(deployments["local-static"].model_gguf.resolve()),
                        *common_tail,
                    ],
                )
                ft_middle = [
                    *common_prefix,
                    os.fspath(deployments["local-ft-static"].model_gguf.resolve()),
                ]
                if deployment_mode == "adapter_on_off":
                    ft_middle.extend(
                        [
                            "--alias",
                            "rondo-l6-paired-approval",
                            "--no-mmproj",
                            "--lora",
                            os.fspath(
                                deployments["local-ft-static"].adapter_files[0][
                                    1
                                ].resolve()
                            ),
                            *common_tail[3:],
                        ]
                    )
                else:
                    ft_middle.extend(common_tail)
                self.assertEqual(commands["local-ft-static"], ft_middle)
                self.assertNotIn("--lora", commands["local-static"])
                if deployment_mode == "paired_gguf":
                    self.assertNotIn("--lora", commands["local-ft-static"])

    def test_command_rechecks_deployment_runtime_and_template_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory, deployment_mode="paired_gguf")
            _receipt, _sha, _contracts, deployments = (
                paired_outputs._revalidate_built_pair_receipt(built)
            )
            runtime = self._runtime(directory)
            template = dict(built.sources)["chat-template"].path
            (directory / "finetuned-model.gguf").write_bytes(b"drifted-model")
            with mock.patch.object(
                l6_b10333_pair,
                "FROZEN_SERVER_SHA256",
                digest_bytes(runtime.read_bytes()),
            ), self.assertRaisesRegex(
                l6_b10333_pair.L6B10333PairError,
                "resolved_deployment_drift",
            ):
                l6_b10333_pair.build_b10333_command(
                    deployments["local-ft-static"],
                    runtime_binary=runtime,
                    chat_template=template,
                    port=19037,
                )

    def test_ready_check_binds_loaded_adapter_path_and_scale(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory)
            _receipt, _sha, _contracts, deployments = (
                paired_outputs._revalidate_built_pair_receipt(built)
            )
            deployment = deployments["local-ft-static"]
            process = mock.Mock()
            process.poll.return_value = None
            valid = [
                {"status": "ok"},
                {
                    "build_info": l6_b10333_pair.model_backed.CUDA_SERVICE_BUILD_INFO,
                    "model_path": os.fspath(deployment.model_gguf.resolve()),
                },
                {"data": [{"id": l6_b10333_pair.MODEL_ALIAS}]},
                [
                    {
                        "id": 0,
                        "path": os.fspath(
                            deployment.adapter_files[0][1].resolve()
                        ),
                        "scale": 1.0,
                        "task_name": "",
                        "prompt_prefix": "",
                    }
                ],
            ]
            with mock.patch.object(
                l6_b10333_pair.launcher, "_get_json", side_effect=valid
            ):
                l6_b10333_pair._wait_for_side(
                    process,
                    deployment=deployment,
                    base_url="http://127.0.0.1:19037/v1",
                    startup_timeout_seconds=1.0,
                )

            drift = [*valid[:3], []]
            with mock.patch.object(
                l6_b10333_pair.launcher, "_get_json", side_effect=drift
            ), self.assertRaisesRegex(
                l6_b10333_pair.L6B10333PairError,
                "formal_pair_server_identity_mismatch",
            ):
                l6_b10333_pair._wait_for_side(
                    process,
                    deployment=deployment,
                    base_url="http://127.0.0.1:19037/v1",
                    startup_timeout_seconds=1.0,
                )

    def test_request_freezes_sampling_static_payload_and_structured_contract(self) -> None:
        bundle = fixture_bundle()
        approval_input = bundle.source_rows[next(iter(bundle.source_rows))]["input"]
        request = l6_b10333_pair.build_formal_request(approval_input)
        self.assertEqual(
            request,
            {
                "model": "rondo-l6-paired-approval",
                "instructions": (
                    f"{l6_b10333_pair.STATIC_INSTRUCTIONS}\n\n"
                    "Guardian policy follows exactly:\n"
                    f"{approval_input['guardian_policy']}"
                ),
                "input": approval_input["input"],
                "stream": False,
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": 42,
                "max_output_tokens": 512,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "rondo_static_approval_v1",
                        "strict": True,
                        "schema": l6_b10333_pair.STATIC_DECISION_SCHEMA,
                    },
                },
            },
        )
        drift = json.loads(json.dumps(approval_input))
        drift["output_schema"]["properties"]["outcome"]["enum"].append("maybe")
        with self.assertRaisesRegex(
            l6_b10333_pair.L6B10333PairError,
            "formal_pair_approval_input_invalid",
        ):
            l6_b10333_pair.build_formal_request(drift)

    def test_http_timeout_is_distinct_from_service_unavailable(self) -> None:
        transport = l6_b10333_pair._HttpTransport(
            "http://127.0.0.1:19037/v1/responses", timeout_seconds=1.0
        )
        with mock.patch.object(
            local_client._NO_REDIRECT_OPENER,
            "open",
            side_effect=TimeoutError("fixture-timeout"),
        ), self.assertRaises(l6_b10333_pair.L6B10333RequestTimeout):
            transport.post({"fixture": True})

    def test_subprocess_session_preserves_one_private_side_log(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            log_dir = directory / "logs"
            log_dir.mkdir(mode=0o700)
            log_path = log_dir / "formal-local-static.log"
            built = build_receipt(directory)
            _receipt, _sha, _contracts, deployments = (
                paired_outputs._revalidate_built_pair_receipt(built)
            )
            process = mock.Mock()
            with mock.patch.object(
                l6_b10333_pair.subprocess, "Popen", return_value=process
            ) as popen, mock.patch.object(
                l6_b10333_pair, "_wait_for_side"
            ), mock.patch.object(
                l6_b10333_pair.launcher, "_stop_server_process"
            ) as stop:
                with l6_b10333_pair.subprocess_side_session(
                    deployment=deployments["local-static"],
                    command=["/fixture/llama-server"],
                    base_url="http://127.0.0.1:19037/v1",
                    log_path=log_path,
                ):
                    pass
            self.assertEqual(mode(log_path), 0o600)
            self.assertEqual(
                popen.call_args.kwargs["stdout"],
                popen.call_args.kwargs["stderr"],
            )
            self.assertIsInstance(popen.call_args.kwargs["stdout"], int)
            stop.assert_called_once_with(process)


class B10333FormalCompositionTests(unittest.TestCase):
    def test_prepare_evidence_cli_builds_and_reloads_without_body_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            private = directory / "private"
            private.mkdir(mode=0o700)
            built = build_receipt(directory)
            sources = dict(built.sources)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = l6_b10333_pair.main(
                    [
                        "prepare-evidence",
                        "--pair-id",
                        built.receipt["pair_id"],
                        "--base-model",
                        str(sources["base-model"].path),
                        "--local-static-deployment",
                        str(sources["local-static"].path),
                        "--local-ft-deployment",
                        str(sources["local-ft-static"].path),
                        "--training-receipt",
                        str(sources["training-receipt"].path),
                        "--runtime-lock",
                        str(sources["runtime-lock"].path),
                        "--chat-template",
                        str(sources["chat-template"].path),
                        "--pair-contract",
                        str(sources["pair-contract"].path),
                        "--blind-identity-marker",
                        "PairFixtureBase",
                        "--blind-identity-marker",
                        "PairFixtureAdapter",
                        "--private-dir",
                        str(private),
                    ]
                )
            self.assertEqual(result, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(set(report), {
                "status",
                "pair_receipt",
                "pair_receipt_sha256",
                "pair_evidence",
                "pair_evidence_sha256",
            })
            self.assertEqual(report["status"], "ready")
            self.assertNotIn("guardian_policy", output.getvalue())
            rebuilt = paired_outputs.load_pair_evidence_locator(
                Path(report["pair_evidence"])
            )
            self.assertEqual(rebuilt.receipt, built.receipt)

    def test_serial_sessions_journal_artifacts_locator_and_formal_import(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory)
            runtime = directory / "llama-server"
            runtime.write_bytes(b"fixture-b10333-runtime")
            os.chmod(runtime, 0o755)
            run_dir = directory / "run"
            private_dir = directory / "private"
            run_dir.mkdir(mode=0o700)
            private_dir.mkdir(mode=0o700)
            factory = RecordingFactory()
            with mock.patch.object(
                l6_b10333_pair,
                "FROZEN_SERVER_SHA256",
                digest_bytes(runtime.read_bytes()),
            ), mock.patch.object(
                cross_eval, "load_synthetic_bundle", return_value=bundle
            ):
                smoke = l6_b10333_pair.run_structural_smoke(
                    bundle=bundle,
                    pair_receipt=built,
                    runtime_binary=runtime,
                    private_dir=private_dir,
                    port=19037,
                    sample_count=2,
                    session_factory=factory,
                )
                self.assertEqual(smoke.terminal_count, 4)
                self.assertEqual(smoke.status, "passed")
                self.assertFalse(
                    (run_dir / "paired-output-journal.jsonl").exists()
                )
                self.assertEqual(
                    [event for event in factory.events if event[0] != "post"],
                    [
                        ("start", "local-static"),
                        ("stop", "local-static"),
                        ("start", "local-ft-static"),
                        ("stop", "local-ft-static"),
                    ],
                )
                factory.events.clear()
                factory.requests.clear()
                factory.structured_failure_count = 1
                artifacts = l6_b10333_pair.run_formal_pair_bundle(
                    worktree_root=WORKTREE_ROOT,
                    bundle=bundle,
                    pair_receipt=built,
                    runtime_binary=runtime,
                    run_dir=run_dir,
                    private_dir=private_dir,
                    port=19037,
                    session_factory=factory,
                )
            self.assertEqual(artifacts.side_output_count, 18)
            self.assertEqual(
                [event for event in factory.events if event[0] != "post"],
                [
                    ("start", "local-static"),
                    ("stop", "local-static"),
                    ("start", "local-ft-static"),
                    ("stop", "local-ft-static"),
                ],
            )
            first_stop = factory.events.index(("stop", "local-static"))
            second_start = factory.events.index(("start", "local-ft-static"))
            self.assertLess(first_stop, second_start)
            self.assertEqual(
                [side for event, side in factory.events if event == "post"],
                ["local-static"] * 6 + ["local-ft-static"] * 6,
            )
            self.assertTrue(
                all(
                    request["temperature"] == 0.0
                    and request["top_p"] == 1.0
                    and request["seed"] == 42
                    and request["max_output_tokens"] == 512
                    for _side, request in factory.requests
                )
            )
            for path in (
                artifacts.outputs_path,
                artifacts.pair_receipt_path,
                artifacts.pair_evidence_path,
                smoke.receipt_path,
                run_dir / "paired-output-journal.jsonl",
            ):
                self.assertEqual(mode(path), 0o600)
            self.assertEqual(mode(artifacts.log_dir), 0o700)
            self.assertEqual(
                sorted(path.name for path in artifacts.log_dir.iterdir()),
                [
                    "formal-local-ft-static.log",
                    "formal-local-static.log",
                    "smoke-local-ft-static.log",
                    "smoke-local-static.log",
                ],
            )
            rebuilt = paired_outputs.load_pair_evidence_locator(
                artifacts.pair_evidence_path
            )
            self.assertEqual(rebuilt.receipt, built.receipt)
            rows, _raw = cross_eval._load_jsonl(
                artifacts.outputs_path, private=True
            )
            failures = [
                row["terminal"]
                for row in rows
                if row.get("terminal", {}).get("status")
                == "structured_output_failure"
            ]
            self.assertEqual(
                failures,
                [
                    {
                        "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
                        "contract_version": (
                            cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION
                        ),
                        "status": "structured_output_failure",
                        "failure_code": "b10333-structured-output",
                    }
                ],
            )

    def test_timeout_terminal_and_infrastructure_resolution_cli(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            private = directory / "private"
            run_dir = directory / "run"
            private.mkdir(mode=0o700)
            run_dir.mkdir(mode=0o700)
            built = build_receipt(directory)
            runtime = directory / "llama-server"
            runtime.write_bytes(b"fixture-b10333-runtime")
            os.chmod(runtime, 0o755)
            timeout_factory = RecordingFactory(timeout_once=True)
            with mock.patch.object(
                l6_b10333_pair,
                "FROZEN_SERVER_SHA256",
                digest_bytes(runtime.read_bytes()),
            ):
                smoke = l6_b10333_pair.run_structural_smoke(
                    bundle=bundle,
                    pair_receipt=built,
                    runtime_binary=runtime,
                    private_dir=private,
                    port=19037,
                    sample_count=1,
                    session_factory=timeout_factory,
                )
            smoke_value, _raw = cross_eval._load_json(
                smoke.receipt_path, private=True
            )
            self.assertEqual(
                smoke_value["results"][0]["terminal"]["status"], "timeout"
            )
            self.assertEqual(smoke.status, "passed")
            l6_b10333_pair._require_structural_smoke(
                bundle=bundle,
                pair_receipt=built,
                private_dir=private,
            )
            self.assertFalse((run_dir / "paired-output-journal.jsonl").exists())

            infra_private = directory / "infra-private"
            infra_run_dir = directory / "infra-run"
            infra_private.mkdir(mode=0o700)
            infra_run_dir.mkdir(mode=0o700)
            with mock.patch.object(
                l6_b10333_pair,
                "FROZEN_SERVER_SHA256",
                digest_bytes(runtime.read_bytes()),
            ):
                passed = l6_b10333_pair.run_structural_smoke(
                    bundle=bundle,
                    pair_receipt=built,
                    runtime_binary=runtime,
                    private_dir=infra_private,
                    port=19037,
                    sample_count=1,
                    session_factory=RecordingFactory(),
                )
            self.assertEqual(passed.status, "passed")
            infra_factory = RecordingFactory(infrastructure_failure_once=True)
            with mock.patch.object(
                l6_b10333_pair,
                "FROZEN_SERVER_SHA256",
                digest_bytes(runtime.read_bytes()),
            ), self.assertRaises(local_client.ServiceUnavailableError):
                l6_b10333_pair.run_formal_pair_bundle(
                    worktree_root=WORKTREE_ROOT,
                    bundle=bundle,
                    pair_receipt=built,
                    runtime_binary=runtime,
                    run_dir=infra_run_dir,
                    private_dir=infra_private,
                    port=19037,
                    session_factory=infra_factory,
                )
            self.assertEqual(
                [event for event in infra_factory.events if event[0] != "post"],
                [
                    ("start", "local-static"),
                    ("stop", "local-static"),
                ],
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "paired_journal_attempt_without_terminal",
            ):
                paired_outputs.run_paired_outputs(
                    bundle,
                    pair_receipt=built,
                    run_dir=infra_run_dir,
                    invoke=lambda _side, _input, _deployment: {},
                )

            output = io.StringIO()
            with mock.patch.object(
                cross_eval, "load_synthetic_bundle", return_value=bundle
            ), contextlib.redirect_stdout(output):
                result = l6_b10333_pair.main(
                    [
                        "resolve-interrupted",
                        "--worktree-root",
                        str(WORKTREE_ROOT),
                        "--pair-evidence-source",
                        str(infra_private / "l6-pair-evidence.json"),
                        "--run-dir",
                        str(infra_run_dir),
                        "--failure-code",
                        "b10333-service-unavailable",
                    ]
                )
            self.assertEqual(result, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["status"], "resolved")
            self.assertEqual(
                report["terminal"]["status"], "infrastructure_failure"
            )

    def test_smoke_accepts_only_honest_nondecision_terminals(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory)
            runtime = directory / "llama-server"
            runtime.write_bytes(b"fixture-b10333-runtime")
            os.chmod(runtime, 0o755)
            private = directory / "private"
            run_dir = directory / "run"
            private.mkdir(mode=0o700)
            run_dir.mkdir(mode=0o700)
            factory = RecordingFactory(
                terminal_statuses=[
                    "structured_output_failure",
                    "timeout",
                    "refusal",
                    "structured_output_failure",
                ]
            )
            with mock.patch.object(
                l6_b10333_pair,
                "FROZEN_SERVER_SHA256",
                digest_bytes(runtime.read_bytes()),
            ), mock.patch.object(
                cross_eval, "load_synthetic_bundle", return_value=bundle
            ):
                smoke = l6_b10333_pair.run_structural_smoke(
                    bundle=bundle,
                    pair_receipt=built,
                    runtime_binary=runtime,
                    private_dir=private,
                    port=19037,
                    sample_count=2,
                    session_factory=factory,
                )
                l6_b10333_pair._require_structural_smoke(
                    bundle=bundle,
                    pair_receipt=built,
                    private_dir=private,
                )
                formal = l6_b10333_pair.run_formal_pair_bundle(
                    worktree_root=WORKTREE_ROOT,
                    bundle=bundle,
                    pair_receipt=built,
                    runtime_binary=runtime,
                    run_dir=run_dir,
                    private_dir=private,
                    port=19037,
                    session_factory=factory,
                )
            value, _raw = cross_eval._load_json(smoke.receipt_path, private=True)
            self.assertEqual(smoke.status, "passed")
            self.assertEqual(value["schema_version"], 2)
            self.assertEqual(
                value["diagnostics"]["decision_count_by_side"],
                {"local-static": 0, "local-ft-static": 0},
            )
            self.assertEqual(
                [result["terminal"]["status"] for result in value["results"]],
                [
                    "structured_output_failure",
                    "timeout",
                    "refusal",
                    "structured_output_failure",
                ],
            )
            self.assertEqual(
                value["lifecycle"],
                {
                    "serial_side_sessions_completed": [
                        "local-static",
                        "local-ft-static",
                    ],
                    "process_cleanup_completed": True,
                },
            )
            self.assertEqual(formal.side_output_count, 18)

    def test_show_commands_cli_is_model_free_and_uses_locator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            private = directory / "private"
            private.mkdir(mode=0o700)
            built = build_receipt(directory, deployment_mode="paired_gguf")
            evidence_path = private / "source-evidence.json"
            paired_outputs.write_pair_evidence_locator(built, evidence_path)
            runtime = directory / "llama-server"
            runtime.write_bytes(b"fixture-b10333-runtime")
            os.chmod(runtime, 0o755)
            output = io.StringIO()
            with mock.patch.object(
                l6_b10333_pair,
                "FROZEN_SERVER_SHA256",
                digest_bytes(runtime.read_bytes()),
            ), contextlib.redirect_stdout(output):
                result = l6_b10333_pair.main(
                    [
                        "show-commands",
                        "--worktree-root",
                        str(WORKTREE_ROOT),
                        "--pair-evidence-source",
                        str(evidence_path),
                        "--runtime-binary",
                        str(runtime),
                        "--port",
                        "19037",
                    ]
                )
            self.assertEqual(result, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["status"], "ready")
            self.assertEqual(
                set(report["commands"]), set(paired_outputs.LOCAL_SIDE_ORDER)
            )
            self.assertNotIn("--lora", report["commands"]["local-static"])
            self.assertNotIn("--lora", report["commands"]["local-ft-static"])


if __name__ == "__main__":
    unittest.main()
