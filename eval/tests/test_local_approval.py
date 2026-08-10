from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval import runtime_bridge  # noqa: E402
from rondo_eval.config import ConfigError, RepoPaths, RuntimeConfig  # noqa: E402
from rondo_eval.evidence import StaticApprovalPayload, build_static_payload  # noqa: E402
from rondo_eval.exit_codes import (  # noqa: E402
    CONFIG_ERROR,
    INFRA_ERROR,
    MODEL_MISSING,
    SERVICE_UNAVAILABLE,
    STRUCTURED_OUTPUT_ERROR,
    SUCCESS,
)
from rondo_eval.local_approval.client import (  # noqa: E402
    LocalApprovalClient,
    ServiceUnavailableError,
    StructuredOutputError,
    settings_from_config,
)
from rondo_eval.local_approval.doctor import run_doctor  # noqa: E402
from rondo_eval.local_approval.fake_server import FakeApprovalServer  # noqa: E402
from rondo_eval.local_approval.launcher import (  # noqa: E402
    LLAMA_CPP_ASSET_SHA256,
    LLAMA_CPP_BINARY_SHA256,
    LLAMA_CPP_BUILD,
    LLAMA_CPP_COMMIT,
    LauncherError,
    ModelMissingError,
    RouterProbe,
    RuntimeInspection,
    RuntimeLock,
    _verify_host_dependency_closure,
    _verify_runtime_closure,
    build_serve_command,
    inspect_runtime,
    model_path,
    run_server,
    serve_environment,
)


def _local_data(
    base_url: str,
    *,
    model_path_value: str = "",
    model_sha256_value: str = "",
    api_key_env: bool = False,
) -> dict:
    local_model: dict = {
        "runtime": "llama_cpp",
        "api": "responses",
        "base_url": base_url,
        "model_id": "rondo-local-approval",
        "model_path": model_path_value,
        "model_sha256": model_sha256_value,
        "format": "gguf",
        "quantization": "Q4_K_M",
        "server": {
            "binary": "llama-server",
            "host": "127.0.0.1",
            "port": int(base_url.rsplit(":", 1)[1].split("/", 1)[0]),
            "context_size": 0,
            "gpu_layers": "auto",
            "flash_attention": "auto",
            "parallel": 1,
            "metrics": True,
            "slots": True,
            "web_ui": False,
            "tools": False,
        },
        "request": {
            "stream": False,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 42,
            "max_output_tokens": 512,
            "timeout_seconds": 2,
            "max_retries": 0,
            "structured_output": True,
        },
    }
    if api_key_env:
        local_model["api_key_env"] = "RONDO_LOCAL_MODEL_API_KEY"
    return {"local_model": local_model}


def _payload() -> StaticApprovalPayload:
    return build_static_payload(
        {
            "instructions": "exact guardian policy\n",
            "tools": [{"type": "function", "name": "read_file"}],
            "input": [
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "approve deleting build cache?"}],
                    "encrypted_function_args": "warehouse-only",
                }
            ],
        }
    )


def _canonical_payload(
    payload: StaticApprovalPayload, logical_payload: dict
) -> StaticApprovalPayload:
    canonical = json.dumps(
        logical_payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return StaticApprovalPayload(payload.policy_identity, canonical, logical_payload)


class LocalApprovalClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        (self.root / "rondo.secrets.example.env").write_text(
            "RONDO_LOCAL_MODEL_API_KEY=\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _config(self, base_url: str, **kwargs: object) -> RuntimeConfig:
        return RuntimeConfig(self.paths, _local_data(base_url, **kwargs), "0" * 64)

    def test_fake_round_trip_is_tool_free_and_uses_pinned_response_format(self) -> None:
        with FakeApprovalServer() as fake:
            decision = LocalApprovalClient(self._config(fake.base_url)).decide(_payload())
        self.assertEqual(
            decision,
            {"outcome": "deny", "rationale": "fake server decision", "risk_tags": ["fake"]},
        )
        self.assertEqual(len(fake.requests), 1)
        request = fake.requests[0]
        self.assertNotIn("tools", request)
        self.assertNotIn("text", request)
        self.assertNotIn("additional_tools", str(request))
        self.assertNotIn("encrypted_function_args", str(request))
        self.assertEqual(
            request["response_format"]["json_schema"]["schema"],
            _payload().logical_payload["output_schema"],
        )
        self.assertTrue(request["response_format"]["json_schema"]["strict"])

    def test_client_rejects_any_tool_transport_before_network(self) -> None:
        payload = _payload()
        invalid = _canonical_payload(
            payload,
            {**payload.logical_payload, "tools": []},
        )
        client = LocalApprovalClient(self._config("http://127.0.0.1:1/v1"))
        with self.assertRaises(ConfigError):
            client.build_request(invalid)

    def test_client_accepts_tool_search_output_tools_as_static_evidence(self) -> None:
        payload = build_static_payload(
            {
                "instructions": "exact guardian policy\n",
                "input": [
                    {
                        "type": "tool_search_output",
                        "tools": [{"type": "function", "name": "read_file"}],
                    }
                ],
            }
        )
        with FakeApprovalServer() as fake:
            LocalApprovalClient(self._config(fake.base_url)).decide(payload)
        self.assertEqual(fake.requests[0]["input"][0]["type"], "tool_search_output")
        self.assertEqual(fake.requests[0]["input"][0]["tools"][0]["name"], "read_file")

    def test_client_final_sink_rejects_provider_private_fields(self) -> None:
        client = LocalApprovalClient(self._config("http://127.0.0.1:1/v1"))
        for private_input in (
            {"encrypted_function_args": "private"},
            {
                "internal_chat_message_metadata_passthrough": {
                    "executed_tool_calls": [{"name": "shell"}]
                }
            },
        ):
            payload = _payload()
            logical = dict(payload.logical_payload)
            logical["input"] = [private_input]
            with self.assertRaises(ConfigError):
                client.build_request(_canonical_payload(payload, logical))

    def test_client_rejects_mismatched_canonical_bytes(self) -> None:
        payload = _payload()
        invalid = StaticApprovalPayload(
            payload.policy_identity,
            b"{}",
            payload.logical_payload,
        )
        client = LocalApprovalClient(self._config("http://127.0.0.1:1/v1"))
        with self.assertRaises(ConfigError):
            client.build_request(invalid)

    def test_server_grammar_is_backed_by_local_schema_validation(self) -> None:
        invalid_response = {
            "model": "rondo-local-approval",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"outcome":"allow","rationale":7,"risk_tags":[]}',
                        }
                    ],
                }
            ],
        }
        with FakeApprovalServer(response_override=invalid_response) as fake:
            with self.assertRaises(StructuredOutputError) as raised:
                LocalApprovalClient(self._config(fake.base_url)).decide(_payload())
        self.assertEqual(raised.exception.exit_code, STRUCTURED_OUTPUT_ERROR)

    def test_response_model_identity_must_match_configuration(self) -> None:
        response = {
            "model": "different-local-model",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": '{"outcome":"deny","rationale":"no","risk_tags":[]}',
                        }
                    ],
                }
            ],
        }
        with FakeApprovalServer(response_override=response) as fake:
            with self.assertRaises(StructuredOutputError):
                LocalApprovalClient(self._config(fake.base_url)).decide(_payload())

    def test_optional_secret_is_sent_as_bearer_without_entering_request_body(self) -> None:
        secret = "local-test-secret"
        (self.root / ".env.local").write_text(
            f"RONDO_LOCAL_MODEL_API_KEY={secret}\n",
            encoding="utf-8",
        )
        os.chmod(self.root / ".env.local", 0o600)
        with FakeApprovalServer(required_bearer=secret) as fake:
            client = LocalApprovalClient(self._config(fake.base_url, api_key_env=True))
            client.decide(_payload())
        self.assertEqual(fake.authorization_seen, [True])
        self.assertNotIn(secret, str(fake.requests))

    def test_redirect_is_rejected_without_forwarding_bearer(self) -> None:
        secret = "local-redirect-secret"
        (self.root / ".env.local").write_text(
            f"RONDO_LOCAL_MODEL_API_KEY={secret}\n",
            encoding="utf-8",
        )
        os.chmod(self.root / ".env.local", 0o600)
        with FakeApprovalServer(required_bearer=secret) as target:
            with FakeApprovalServer(redirect_to=f"{target.base_url}/responses") as redirect:
                client = LocalApprovalClient(
                    self._config(redirect.base_url, api_key_env=True)
                )
                with self.assertRaises(ServiceUnavailableError):
                    client.decide(_payload())
        self.assertEqual(redirect.authorization_seen, [True])
        self.assertEqual(target.authorization_seen, [])
        self.assertEqual(target.requests, [])

    def test_final_response_url_must_equal_configured_endpoint(self) -> None:
        response = mock.MagicMock()
        response.status = 200
        response.geturl.return_value = "http://localhost:1/v1/responses"
        context = mock.MagicMock()
        context.__enter__.return_value = response
        with mock.patch(
            "rondo_eval.local_approval.client._NO_REDIRECT_OPENER.open",
            return_value=context,
        ):
            with self.assertRaises(ServiceUnavailableError):
                LocalApprovalClient(
                    self._config("http://127.0.0.1:1/v1")
                ).decide(_payload())

    def test_non_loopback_endpoint_is_configuration_error(self) -> None:
        config = RuntimeConfig(self.paths, _local_data("http://127.0.0.1:8080/v1"), "0" * 64)
        config.data["local_model"]["base_url"] = "https://example.com/v1"
        with self.assertRaises(ConfigError):
            settings_from_config(config)


class LauncherAndDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        (self.root / "rondo.secrets.example.env").write_text(
            "RONDO_LOCAL_MODEL_API_KEY=\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _config(self, *, model: str = "", port: int = 8080) -> RuntimeConfig:
        digest = hashlib.sha256(Path(model).read_bytes()).hexdigest() if model else ""
        return RuntimeConfig(
            self.paths,
            _local_data(
                f"http://127.0.0.1:{port}/v1",
                model_path_value=model,
                model_sha256_value=digest,
            ),
            "0" * 64,
        )

    @staticmethod
    def _ready_runtime(_config: RuntimeConfig, _settings: object) -> RuntimeInspection:
        return RuntimeInspection("runtime_ready", Path("/fake/llama-server"), "ready")

    @staticmethod
    def _ready_router(
        _config: RuntimeConfig, _settings: object, _runtime: RuntimeInspection
    ) -> RouterProbe:
        return RouterProbe("router_ready", "ready")

    def test_formal_launcher_stops_at_model_missing_without_router_fallback(self) -> None:
        config = self._config()
        settings = settings_from_config(config)
        with self.assertRaises(ModelMissingError) as raised:
            model_path(config, settings)
        self.assertEqual(raised.exception.exit_code, MODEL_MISSING)

    def test_model_requires_gguf_header_and_configured_digest(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"not-gguf")
        config = self._config(model=os.fspath(model))
        with self.assertRaises(ConfigError):
            model_path(config, settings_from_config(config))

        model.write_bytes(b"GGUFfake-model-fixture")
        config = self._config(model=os.fspath(model))
        config.data["local_model"]["model_sha256"] = "0" * 64
        with self.assertRaises(ConfigError):
            model_path(config, settings_from_config(config))

    def test_run_server_checks_model_before_requesting_watchdog_lease(self) -> None:
        watchdog_factory = mock.Mock()
        with self.assertRaises(ModelMissingError):
            run_server(self._config(), watchdog_factory=watchdog_factory)
        watchdog_factory.assert_not_called()

    def test_run_server_requires_watchdog_before_runtime_probe_or_popen(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        watchdog_factory = mock.Mock(
            side_effect=runtime_bridge.RuntimeBridgeError("not supervised")
        )
        popen = mock.Mock()
        with mock.patch(
            "rondo_eval.local_approval.launcher.inspect_runtime"
        ) as runtime_probe:
            with self.assertRaises(LauncherError) as raised:
                run_server(
                    self._config(model=os.fspath(model)),
                    watchdog_factory=watchdog_factory,
                    popen=popen,
                )
        self.assertEqual(raised.exception.exit_code, INFRA_ERROR)
        runtime_probe.assert_not_called()
        popen.assert_not_called()

    def test_run_server_guards_the_full_mocked_process_lifecycle(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        lease = runtime_bridge.WatchdogLease(token="a" * 48)
        guard = mock.Mock()
        guard.is_held.side_effect = [True, True, True]
        watchdog = runtime_bridge.WatchdogProof(lease=lease, guard=guard)
        process = mock.Mock()
        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="llama-server", timeout=0.01),
            0,
        ]
        popen = mock.Mock(return_value=process)
        runtime = RuntimeInspection(
            "runtime_ready",
            self.root / "llama-server",
            "ready",
        )
        with mock.patch(
            "rondo_eval.local_approval.launcher.inspect_runtime",
            return_value=runtime,
        ):
            result = run_server(
                self._config(model=os.fspath(model)),
                watchdog_factory=lambda: watchdog,
                popen=popen,
                watchdog_interval_seconds=0.01,
            )
        self.assertEqual(result, 0)
        self.assertEqual(guard.is_held.call_count, 3)
        popen.assert_called_once()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    def test_run_server_terminates_then_kills_on_watchdog_loss(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        lease = runtime_bridge.WatchdogLease(token="b" * 48)
        guard = mock.Mock()
        guard.is_held.side_effect = [True, True, False]
        watchdog = runtime_bridge.WatchdogProof(lease=lease, guard=guard)
        process = mock.Mock()
        process.wait.side_effect = [
            subprocess.TimeoutExpired(cmd="llama-server", timeout=0.01),
            subprocess.TimeoutExpired(cmd="llama-server", timeout=5),
            -9,
        ]
        popen = mock.Mock(return_value=process)
        runtime = RuntimeInspection(
            "runtime_ready",
            self.root / "llama-server",
            "ready",
        )
        with mock.patch(
            "rondo_eval.local_approval.launcher.inspect_runtime",
            return_value=runtime,
        ):
            with self.assertRaises(LauncherError) as raised:
                run_server(
                    self._config(model=os.fspath(model)),
                    watchdog_factory=lambda: watchdog,
                    popen=popen,
                    watchdog_interval_seconds=0.01,
                )
        self.assertEqual(raised.exception.exit_code, INFRA_ERROR)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()

    def test_serve_command_is_pinned_loopback_offline_and_contains_no_secret(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        config = self._config(model=os.fspath(model))
        settings = settings_from_config(config)
        command = build_serve_command(config, settings, Path("/runtime/llama-server"))
        self.assertIn("--offline", command)
        self.assertIn("--no-models-autoload", command)
        self.assertIn("--no-ui", command)
        self.assertEqual(command[command.index("--host") + 1], "127.0.0.1")
        self.assertEqual(command[command.index("--alias") + 1], "rondo-local-approval")
        self.assertEqual(command[command.index("--n-gpu-layers") + 1], "99")
        self.assertNotIn("LLAMA_API_KEY", command)

    def test_launcher_maps_only_local_secret_to_llama_api_key(self) -> None:
        config = self._config()
        config.data["local_model"]["api_key_env"] = "RONDO_LOCAL_MODEL_API_KEY"
        secret = "local-test-secret"
        (self.root / ".env.local").write_text(
            f"RONDO_LOCAL_MODEL_API_KEY={secret}\n",
            encoding="utf-8",
        )
        os.chmod(self.root / ".env.local", 0o600)
        with mock.patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "must-not-leak",
                "LD_LIBRARY_PATH": "/ambient/injection",
            },
            clear=False,
        ):
            environment = serve_environment(config)
        self.assertEqual(environment["LLAMA_API_KEY"], secret)
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertNotIn("LD_LIBRARY_PATH", environment)

    def test_doctor_distinguishes_configuration_and_runtime_failures(self) -> None:
        invalid = self._config()
        invalid.data["local_model"]["server"]["tools"] = True
        self.assertEqual(run_doctor(invalid).exit_code, CONFIG_ERROR)

        runtime_missing = lambda _config, _settings: RuntimeInspection(  # noqa: E731
            "runtime_missing", None, "missing"
        )
        report = run_doctor(self._config(), runtime_inspector=runtime_missing)
        self.assertEqual((report.status, report.exit_code), ("runtime_missing", INFRA_ERROR))

    def test_doctor_reports_only_waiting_for_model_after_router_probe(self) -> None:
        report = run_doctor(
            self._config(),
            runtime_inspector=self._ready_runtime,
            router_probe=self._ready_router,
        )
        self.assertEqual(report.status, "infrastructure_ready_model_missing")
        self.assertEqual(report.exit_code, MODEL_MISSING)
        self.assertEqual(report.service, "not_started")

    def test_doctor_distinguishes_service_schema_and_success(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        config = self._config(model=os.fspath(model))

        def unavailable(_config: RuntimeConfig) -> dict[str, object]:
            raise ServiceUnavailableError("not running")

        report = run_doctor(
            config,
            runtime_inspector=self._ready_runtime,
            identity_probe=lambda _config, _model: None,
            decision_probe=unavailable,
        )
        self.assertEqual((report.status, report.exit_code), ("service_unavailable", SERVICE_UNAVAILABLE))

        def bad_schema(_config: RuntimeConfig) -> dict[str, object]:
            raise StructuredOutputError("invalid")

        report = run_doctor(
            config,
            runtime_inspector=self._ready_runtime,
            identity_probe=lambda _config, _model: None,
            decision_probe=bad_schema,
        )
        self.assertEqual((report.status, report.exit_code), ("service_schema_error", STRUCTURED_OUTPUT_ERROR))

        report = run_doctor(
            config,
            runtime_inspector=self._ready_runtime,
            identity_probe=lambda _config, _model: None,
            decision_probe=lambda _config: {"outcome": "deny"},
        )
        self.assertEqual((report.status, report.exit_code), ("ready", SUCCESS))

    def test_doctor_binds_fake_endpoint_build_model_path_and_alias(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        with FakeApprovalServer(model_path=os.fspath(model)) as fake:
            config = RuntimeConfig(
                self.paths,
                _local_data(
                    fake.base_url,
                    model_path_value=os.fspath(model),
                    model_sha256_value=hashlib.sha256(model.read_bytes()).hexdigest(),
                ),
                "0" * 64,
            )
            report = run_doctor(config, runtime_inspector=self._ready_runtime)
        self.assertEqual((report.status, report.exit_code), ("ready", SUCCESS))

    def test_doctor_rejects_endpoint_with_different_model_identity(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        other = self.root / "other.gguf"
        with FakeApprovalServer(model_path=os.fspath(other)) as fake:
            config = RuntimeConfig(
                self.paths,
                _local_data(
                    fake.base_url,
                    model_path_value=os.fspath(model),
                    model_sha256_value=hashlib.sha256(model.read_bytes()).hexdigest(),
                ),
                "0" * 64,
            )
            report = run_doctor(config, runtime_inspector=self._ready_runtime)
        self.assertEqual(
            (report.status, report.exit_code),
            ("service_schema_error", STRUCTURED_OUTPUT_ERROR),
        )

    def test_pin_constants_are_exact(self) -> None:
        self.assertEqual(LLAMA_CPP_BUILD, 10333)
        self.assertEqual(LLAMA_CPP_COMMIT, "08659901c43b51de735740f1cf61bb82fbe0c4e4")
        self.assertEqual(
            LLAMA_CPP_ASSET_SHA256,
            "936ce04d98abe2a977e9dd2ff92659bb96947e136acee8f2bc3e21d8eaebbf23",
        )
        self.assertEqual(
            LLAMA_CPP_BINARY_SHA256,
            "1d374fdb717832ec01d4829eff9feb46dfc83b7ccbb9d867c15315dbd8aa4bbe",
        )

    def test_runtime_version_probe_requires_build_and_commit(self) -> None:
        binary = self.root / "llama-server"
        binary.write_text(
            "#!/bin/sh\nprintf '%s\\n' 'version: 10333 (08659901)'\n",
            encoding="utf-8",
        )
        os.chmod(binary, 0o700)
        config = self._config()
        config.data["local_model"]["server"]["binary"] = os.fspath(binary)
        settings = settings_from_config(config)
        with mock.patch(
            "rondo_eval.local_approval.launcher._verify_runtime_closure",
            return_value="a" * 64,
        ):
            self.assertEqual(inspect_runtime(config, settings).status, "runtime_ready")

        binary.write_text("#!/bin/sh\nprintf '%s\\n' 'version: 10332 (deadbeef)'\n", encoding="utf-8")
        with mock.patch(
            "rondo_eval.local_approval.launcher._verify_runtime_closure",
            return_value="a" * 64,
        ):
            self.assertEqual(inspect_runtime(config, settings).status, "runtime_pin_mismatch")

    def test_runtime_closure_mismatch_is_rejected_before_version_probe(self) -> None:
        binary = self.root / "llama-server"
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(binary, 0o700)
        config = self._config()
        config.data["local_model"]["server"]["binary"] = os.fspath(binary)
        settings = settings_from_config(config)
        with mock.patch(
            "rondo_eval.local_approval.launcher._verify_runtime_closure",
            side_effect=ValueError("mismatch"),
        ), mock.patch("rondo_eval.local_approval.launcher.subprocess.run") as probe:
            inspection = inspect_runtime(config, settings)
        self.assertEqual(inspection.status, "runtime_pin_mismatch")
        probe.assert_not_called()

    def test_runtime_closure_hashes_every_file_and_rejects_extra_entries(self) -> None:
        runtime = self.root / "runtime"
        runtime.mkdir()
        binary = runtime / "llama-server"
        binary.write_bytes(b"server")
        library = runtime / "libllama-server-impl.so"
        library.write_bytes(b"library")
        (runtime / "libllama-server-impl-link.so").symlink_to(library.name)
        lock = RuntimeLock(
            "runtime",
            {
                binary.name: hashlib.sha256(binary.read_bytes()).hexdigest(),
                library.name: hashlib.sha256(library.read_bytes()).hexdigest(),
            },
            {"libllama-server-impl-link.so": library.name},
        )
        config = self._config()
        with mock.patch(
            "rondo_eval.local_approval.launcher._load_runtime_lock",
            return_value=lock,
        ), mock.patch(
            "rondo_eval.local_approval.launcher._verify_host_dependency_closure"
        ):
            self.assertEqual(_verify_runtime_closure(config, binary), lock.identity_sha256)
            library.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                _verify_runtime_closure(config, binary)
            library.write_bytes(b"library")
            os.chmod(library, 0o666)
            with self.assertRaises(ValueError):
                _verify_runtime_closure(config, binary)
            os.chmod(library, 0o600)
            (runtime / "unexpected").write_bytes(b"extra")
            with self.assertRaises(ValueError):
                _verify_runtime_closure(config, binary)

    def test_runtime_root_symlink_is_rejected(self) -> None:
        actual = self.root / "actual-runtime"
        actual.mkdir()
        binary = actual / "llama-server"
        binary.write_bytes(b"server")
        linked = self.root / "runtime-link"
        linked.symlink_to(actual.name, target_is_directory=True)
        lock = RuntimeLock(
            linked.name,
            {binary.name: hashlib.sha256(binary.read_bytes()).hexdigest()},
            {},
        )
        with mock.patch(
            "rondo_eval.local_approval.launcher._load_runtime_lock",
            return_value=lock,
        ):
            with self.assertRaises(ValueError):
                _verify_runtime_closure(self._config(), binary)

    def test_runtime_final_rescan_rejects_dependency_probe_mutation(self) -> None:
        runtime = self.root / "runtime"
        runtime.mkdir()
        binary = runtime / "llama-server"
        binary.write_bytes(b"server")
        lock = RuntimeLock(
            runtime.name,
            {binary.name: hashlib.sha256(binary.read_bytes()).hexdigest()},
            {},
        )

        def mutate(_lock: RuntimeLock, root: Path) -> None:
            (root / "late-entry").write_bytes(b"late")

        with mock.patch(
            "rondo_eval.local_approval.launcher._load_runtime_lock",
            return_value=lock,
        ), mock.patch(
            "rondo_eval.local_approval.launcher._verify_host_dependency_closure",
            side_effect=mutate,
        ):
            with self.assertRaises(ValueError):
                _verify_runtime_closure(self._config(), binary)

    def test_host_dependency_probe_binds_canonical_path_and_digest(self) -> None:
        runtime = self.root / "runtime"
        runtime.mkdir()
        binary = runtime / "llama-server"
        binary.write_bytes(b"server")
        dependency = self.root / "libfixture.so"
        dependency.write_bytes(b"host-library")
        probe = self.root / "fake-ldd"
        probe.write_text(
            "#!/bin/sh\nprintf '%s\\n' 'linux-vdso.so.1 (0x0)' "
            f"'libfixture.so => {dependency} (0x1)'\n",
            encoding="utf-8",
        )
        os.chmod(probe, 0o700)
        lock = RuntimeLock(
            runtime.name,
            {binary.name: hashlib.sha256(binary.read_bytes()).hexdigest()},
            {},
            os.fspath(probe),
            hashlib.sha256(probe.read_bytes()).hexdigest(),
            {os.fspath(dependency): hashlib.sha256(dependency.read_bytes()).hexdigest()},
        )
        _verify_host_dependency_closure(lock, runtime)
        dependency.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            _verify_host_dependency_closure(lock, runtime)


if __name__ == "__main__":
    unittest.main()
