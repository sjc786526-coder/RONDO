from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
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
from rondo_eval.local_approval.identity import (  # noqa: E402
    clear_launcher_identity,
    publish_launcher_identity,
)
from rondo_eval.local_approval.launcher import (  # noqa: E402
    CHAT_TEMPLATE_RELATIVE_PATH,
    CHAT_TEMPLATE_REPO,
    CHAT_TEMPLATE_REVISION,
    CHAT_TEMPLATE_SHA256,
    CHAT_TEMPLATE_SIZE_BYTES,
    CHAT_TEMPLATE_SOURCE_FILE,
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
    chat_template,
    inspect_runtime,
    main as launcher_main,
    model_path,
    run_server,
    serve_config_sha256,
    serve_environment,
)


FROZEN_TEMPLATE = REPO_ROOT / CHAT_TEMPLATE_RELATIVE_PATH
FROZEN_TEMPLATE_LOCK = (
    REPO_ROOT / "eval/locks/ministral-3-8b-instruct-2512-chat-template.json"
)


def _install_template_fixture(root: Path) -> None:
    target = root / CHAT_TEMPLATE_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(FROZEN_TEMPLATE.read_bytes())
    lock = root / "eval/locks/ministral-3-8b-instruct-2512-chat-template.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repo": CHAT_TEMPLATE_REPO,
                "revision": CHAT_TEMPLATE_REVISION,
                "source_file": CHAT_TEMPLATE_SOURCE_FILE,
                "installed": {
                    "relative_path": CHAT_TEMPLATE_RELATIVE_PATH,
                    "size_bytes": CHAT_TEMPLATE_SIZE_BYTES,
                    "sha256": CHAT_TEMPLATE_SHA256,
                },
            }
        ),
        encoding="utf-8",
    )


def _local_data(
    base_url: str,
    *,
    model_path_value: str = "",
    model_sha256_value: str = "",
    api_key_env: bool = False,
    server_overrides: dict | None = None,
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
            "context_size": 4096,
            "gpu_layers": "auto",
            "fit": "on",
            "batch_size": 512,
            "ubatch_size": 256,
            "cache_type_k": "f16",
            "cache_type_v": "f16",
            "no_mmproj": True,
            "chat_template_file": CHAT_TEMPLATE_RELATIVE_PATH,
            "chat_template_sha256": CHAT_TEMPLATE_SHA256,
            "jinja": True,
            "flash_attention": "on",
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
    if server_overrides:
        local_model["server"].update(server_overrides)
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


def _current_process_command() -> list[str]:
    raw = Path("/proc/self/cmdline").read_bytes().rstrip(b"\0")
    return [os.fsdecode(item) for item in raw.split(b"\0")]


class LocalApprovalClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        _install_template_fixture(self.root)
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

    def test_model_backed_consumer_cannot_bypass_launcher_identity(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        with FakeApprovalServer(model_path=os.fspath(model)) as fake:
            client = LocalApprovalClient(
                self._config(
                    fake.base_url,
                    model_path_value=os.fspath(model),
                    model_sha256_value=digest,
                )
            )
            with self.assertRaises(ServiceUnavailableError):
                client.decide(_payload())
        self.assertEqual(fake.requests, [])

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

    def test_server_contract_rejects_missing_wrong_type_and_unsupported_values(self) -> None:
        required = (
            "context_size",
            "gpu_layers",
            "fit",
            "batch_size",
            "ubatch_size",
            "cache_type_k",
            "cache_type_v",
            "no_mmproj",
            "chat_template_file",
            "chat_template_sha256",
            "jinja",
            "flash_attention",
            "parallel",
        )
        for key in required:
            with self.subTest(missing=key):
                config = self._config("http://127.0.0.1:8080/v1")
                del config.data["local_model"]["server"][key]
                with self.assertRaises(ConfigError):
                    settings_from_config(config)

        invalid = (
            ("context_size", True),
            ("context_size", 0),
            ("context_size", 2**31),
            ("gpu_layers", True),
            ("gpu_layers", -1),
            ("gpu_layers", 2**31),
            ("gpu_layers", "99"),
            ("gpu_layers", "AUTO"),
            ("gpu_layers", []),
            ("fit", True),
            ("fit", "auto"),
            ("batch_size", True),
            ("batch_size", 0),
            ("ubatch_size", True),
            ("ubatch_size", 0),
            ("ubatch_size", 513),
            ("cache_type_k", "q8_0"),
            ("cache_type_v", "q4_0"),
            ("no_mmproj", False),
            ("no_mmproj", 1),
            ("jinja", False),
            ("jinja", 1),
            ("parallel", True),
            ("parallel", 2),
            ("flash_attention", []),
            ("chat_template_file", "../outside.jinja"),
            ("chat_template_file", "/outside.jinja"),
            ("chat_template_sha256", "A" * 64),
        )
        for key, value in invalid:
            with self.subTest(key=key, value=value):
                config = self._config("http://127.0.0.1:8080/v1")
                config.data["local_model"]["server"][key] = value
                with self.assertRaises(ConfigError):
                    settings_from_config(config)

    def test_gpu_layer_auto_all_and_integer_boundaries_are_supported(self) -> None:
        for value in ("auto", "all", 0, 2**31 - 1):
            with self.subTest(value=value):
                config = self._config(
                    "http://127.0.0.1:8080/v1",
                    server_overrides={"gpu_layers": value},
                )
                self.assertEqual(settings_from_config(config).gpu_layers, value)

    def test_tracked_example_is_the_exact_8k_baseline_contract(self) -> None:
        data = tomllib.loads(
            (REPO_ROOT / "rondo.local.example.toml").read_text(encoding="utf-8")
        )
        config = RuntimeConfig(RepoPaths(REPO_ROOT, REPO_ROOT), data, "0" * 64)
        settings = settings_from_config(config)
        self.assertEqual(
            (
                settings.context_size,
                settings.gpu_layers,
                settings.fit,
                settings.batch_size,
                settings.ubatch_size,
                settings.parallel,
                settings.flash_attention,
                settings.cache_type_k,
                settings.cache_type_v,
                settings.no_mmproj,
                settings.jinja,
            ),
            (8192, "all", "off", 512, 256, 1, "on", "f16", "f16", True, True),
        )
        self.assertEqual(chat_template(config, settings).sha256, CHAT_TEMPLATE_SHA256)


class LauncherAndDoctorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        _install_template_fixture(self.root)
        (self.root / "rondo.secrets.example.env").write_text(
            "RONDO_LOCAL_MODEL_API_KEY=\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _config(
        self,
        *,
        model: str = "",
        port: int = 8080,
        server_overrides: dict | None = None,
    ) -> RuntimeConfig:
        digest = hashlib.sha256(Path(model).read_bytes()).hexdigest() if model else ""
        return RuntimeConfig(
            self.paths,
            _local_data(
                f"http://127.0.0.1:{port}/v1",
                model_path_value=model,
                model_sha256_value=digest,
                server_overrides=server_overrides,
            ),
            "0" * 64,
        )

    def _publish_identity(
        self, config: RuntimeConfig, model: Path, *, runtime_sha256: str = "a" * 64
    ):
        settings = settings_from_config(config)
        return publish_launcher_identity(
            config,
            pid=os.getpid(),
            command=_current_process_command(),
            runtime_sha256=runtime_sha256,
            model_sha256=settings.model_sha256,
            model_path=model,
            model_id=settings.model_id,
            base_url=settings.base_url,
            host=settings.host,
            port=settings.port,
            serve_config_sha256=serve_config_sha256(config, settings),
        )

    @staticmethod
    def _ready_runtime(_config: RuntimeConfig, _settings: object) -> RuntimeInspection:
        return RuntimeInspection(
            "runtime_ready",
            Path("/fake/llama-server"),
            "ready",
            "a" * 64,
            "cpu_only_x64",
            "not_run",
        )

    @staticmethod
    def _gpu_ready_runtime(_config: RuntimeConfig, _settings: object) -> RuntimeInspection:
        return RuntimeInspection(
            "runtime_ready",
            Path("/fake/llama-server"),
            "fixture-only GPU/model capability",
            "a" * 64,
            "gpu_model_serving_validated",
            "fixture_only",
        )

    @staticmethod
    def _ready_router(
        _config: RuntimeConfig, _settings: object, _runtime: RuntimeInspection
    ) -> RouterProbe:
        return RouterProbe("router_ready", "ready")

    def test_frozen_official_template_lock_bytes_and_sha_are_exact(self) -> None:
        self.assertEqual(FROZEN_TEMPLATE.stat().st_size, CHAT_TEMPLATE_SIZE_BYTES)
        self.assertEqual(
            hashlib.sha256(FROZEN_TEMPLATE.read_bytes()).hexdigest(),
            CHAT_TEMPLATE_SHA256,
        )
        lock = json.loads(FROZEN_TEMPLATE_LOCK.read_bytes())
        self.assertEqual(
            lock,
            {
                "schema_version": 1,
                "repo": CHAT_TEMPLATE_REPO,
                "revision": CHAT_TEMPLATE_REVISION,
                "source_file": CHAT_TEMPLATE_SOURCE_FILE,
                "installed": {
                    "relative_path": CHAT_TEMPLATE_RELATIVE_PATH,
                    "size_bytes": CHAT_TEMPLATE_SIZE_BYTES,
                    "sha256": CHAT_TEMPLATE_SHA256,
                },
            },
        )
        config = RuntimeConfig(
            RepoPaths(REPO_ROOT, REPO_ROOT),
            _local_data("http://127.0.0.1:8080/v1"),
            "0" * 64,
        )
        inspection = chat_template(config, settings_from_config(config))
        self.assertEqual(inspection.path, FROZEN_TEMPLATE.resolve())
        self.assertEqual(inspection.sha256, CHAT_TEMPLATE_SHA256)

    def test_template_validation_rejects_missing_symlink_size_hash_and_lock_drift(self) -> None:
        cases = ("missing", "symlink", "size", "hash", "lock")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                _install_template_fixture(root)
                target = root / CHAT_TEMPLATE_RELATIVE_PATH
                lock_path = (
                    root
                    / "eval/locks/ministral-3-8b-instruct-2512-chat-template.json"
                )
                if case == "missing":
                    target.unlink()
                elif case == "symlink":
                    outside = root / "outside.jinja"
                    outside.write_bytes(FROZEN_TEMPLATE.read_bytes())
                    target.unlink()
                    target.symlink_to(outside)
                elif case == "size":
                    target.write_bytes(FROZEN_TEMPLATE.read_bytes() + b"x")
                elif case == "hash":
                    changed = bytearray(FROZEN_TEMPLATE.read_bytes())
                    changed[0] ^= 1
                    target.write_bytes(changed)
                else:
                    lock = json.loads(lock_path.read_bytes())
                    lock["revision"] = "0" * 40
                    lock_path.write_text(json.dumps(lock), encoding="utf-8")
                config = RuntimeConfig(
                    RepoPaths(root, root),
                    _local_data("http://127.0.0.1:8080/v1"),
                    "0" * 64,
                )
                with self.assertRaises(ConfigError):
                    chat_template(config, settings_from_config(config))

    def test_formal_launcher_stops_at_model_missing_without_router_fallback(self) -> None:
        config = self._config()
        settings = settings_from_config(config)
        with self.assertRaises(ModelMissingError) as raised:
            model_path(config, settings)
        self.assertEqual(raised.exception.exit_code, MODEL_MISSING)

    def test_launcher_model_missing_status_does_not_claim_gpu_readiness(self) -> None:
        config = self._config()
        with mock.patch(
            "rondo_eval.local_approval.launcher.RepoPaths.discover",
            return_value=self.paths,
        ), mock.patch(
            "rondo_eval.local_approval.launcher.load_runtime_config",
            return_value=config,
        ), mock.patch(
            "rondo_eval.local_approval.launcher.run_server",
            side_effect=ModelMissingError("missing"),
        ), mock.patch("builtins.print") as output:
            exit_code = launcher_main(["--repo", os.fspath(self.root)])
        self.assertEqual(exit_code, MODEL_MISSING)
        status = json.loads(output.call_args.args[0])
        self.assertEqual(status["status"], "model_missing_gpu_runtime_unvalidated")

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

    def test_run_server_rejects_current_cpu_only_runtime_with_model(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        lease = runtime_bridge.WatchdogLease(token="c" * 48)
        guard = mock.Mock()
        guard.is_held.return_value = True
        watchdog = runtime_bridge.WatchdogProof(lease=lease, guard=guard)
        popen = mock.Mock()
        with mock.patch(
            "rondo_eval.local_approval.launcher.inspect_runtime",
            side_effect=self._ready_runtime,
        ):
            with self.assertRaises(LauncherError):
                run_server(
                    self._config(model=os.fspath(model)),
                    watchdog_factory=lambda: watchdog,
                    popen=popen,
                )
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
            "a" * 64,
            "gpu_model_serving_validated",
        )
        identity_publisher = mock.Mock(return_value=mock.sentinel.identity)
        identity_clearer = mock.Mock()
        with mock.patch(
            "rondo_eval.local_approval.launcher.inspect_runtime",
            return_value=runtime,
        ):
            result = run_server(
                self._config(model=os.fspath(model)),
                watchdog_factory=lambda: watchdog,
                popen=popen,
                identity_publisher=identity_publisher,
                identity_clearer=identity_clearer,
                watchdog_interval_seconds=0.01,
            )
        self.assertEqual(result, 0)
        self.assertEqual(guard.is_held.call_count, 3)
        popen.assert_called_once()
        process.terminate.assert_not_called()
        process.kill.assert_not_called()
        identity_publisher.assert_called_once()
        identity_clearer.assert_called_once_with(
            mock.ANY, mock.sentinel.identity
        )

    def test_launcher_identity_receipt_is_private_and_rejects_symlinked_parent(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        config = self._config(model=os.fspath(model))
        identity = self._publish_identity(config, model)
        receipt = self.root / "eval-data/local-approval/launcher-identity.json"
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        raw_receipt = receipt.read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw_receipt)["schema_version"], 2)
        self.assertNotIn("api_key", raw_receipt.lower())
        clear_launcher_identity(config, identity)

        (self.root / "outside").mkdir()
        receipt.parent.rmdir()
        (self.root / "eval-data").rmdir()
        (self.root / "eval-data").symlink_to("outside", target_is_directory=True)
        with self.assertRaises(ConfigError):
            self._publish_identity(config, model)

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
            "b" * 64,
            "gpu_model_serving_validated",
        )
        identity_publisher = mock.Mock(return_value=mock.sentinel.identity)
        identity_clearer = mock.Mock()
        with mock.patch(
            "rondo_eval.local_approval.launcher.inspect_runtime",
            return_value=runtime,
        ):
            with self.assertRaises(LauncherError) as raised:
                run_server(
                    self._config(model=os.fspath(model)),
                    watchdog_factory=lambda: watchdog,
                    popen=popen,
                    identity_publisher=identity_publisher,
                    identity_clearer=identity_clearer,
                    watchdog_interval_seconds=0.01,
                )
        self.assertEqual(raised.exception.exit_code, INFRA_ERROR)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        identity_clearer.assert_called_once_with(
            mock.ANY, mock.sentinel.identity
        )

    def test_serve_commands_exactly_express_4k_smoke_and_8k_baseline(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        common = [
            "/runtime/llama-server",
            "--offline",
            "--no-models-autoload",
            "--no-ui",
            "--host",
            "127.0.0.1",
            "--port",
            "8080",
            "--model",
            os.fspath(model.resolve()),
            "--alias",
            "rondo-local-approval",
            "--no-mmproj",
        ]
        common_tail = [
            "--split-mode",
            "none",
            "--main-gpu",
            "0",
            "--batch-size",
            "512",
            "--ubatch-size",
            "256",
            "--parallel",
            "1",
            "--flash-attn",
            "on",
            "--cache-type-k",
            "f16",
            "--cache-type-v",
            "f16",
            "--jinja",
            "--chat-template-file",
            os.fspath((self.root / CHAT_TEMPLATE_RELATIVE_PATH).resolve()),
            "--metrics",
            "--slots",
        ]
        cases = (
            (
                {},
                [
                    *common,
                    "--gpu-layers",
                    "auto",
                    "--split-mode",
                    "none",
                    "--main-gpu",
                    "0",
                    "--fit",
                    "on",
                    "--ctx-size",
                    "4096",
                    *common_tail[4:],
                ],
            ),
            (
                {"context_size": 8192, "gpu_layers": "all", "fit": "off"},
                [
                    *common,
                    "--gpu-layers",
                    "all",
                    "--split-mode",
                    "none",
                    "--main-gpu",
                    "0",
                    "--fit",
                    "off",
                    "--ctx-size",
                    "8192",
                    *common_tail[4:],
                ],
            ),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                config = self._config(
                    model=os.fspath(model), server_overrides=overrides
                )
                command = build_serve_command(
                    config,
                    settings_from_config(config),
                    Path("/runtime/llama-server"),
                )
                self.assertEqual(command, expected)
                self.assertNotIn("99", command)
                self.assertNotIn("LLAMA_API_KEY", command)
        self.assertLess(expected.index("--jinja"), expected.index("--chat-template-file"))

    def test_integer_gpu_layers_are_passed_as_exact_decimal(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        config = self._config(
            model=os.fspath(model), server_overrides={"gpu_layers": 17}
        )
        command = build_serve_command(
            config, settings_from_config(config), Path("/runtime/llama-server")
        )
        self.assertEqual(command[command.index("--gpu-layers") + 1], "17")

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

    def test_doctor_reports_model_missing_and_gpu_unvalidated_after_router_probe(self) -> None:
        report = run_doctor(
            self._config(),
            runtime_inspector=self._ready_runtime,
            router_probe=self._ready_router,
        )
        self.assertEqual(
            report.status,
            "cpu_frontend_ready_model_missing_gpu_unvalidated",
        )
        self.assertEqual(report.exit_code, MODEL_MISSING)
        self.assertEqual(report.runtime, "cpu_only_ready")
        self.assertEqual(report.service, "not_started")
        self.assertEqual(report.runtime_capability, "cpu_only_x64")
        self.assertEqual(report.model_backed_validation, "not_run")

    def test_doctor_reports_cpu_runtime_is_not_gpu_model_ready(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        identity_probe = mock.Mock()
        decision_probe = mock.Mock()
        report = run_doctor(
            self._config(model=os.fspath(model)),
            runtime_inspector=self._ready_runtime,
            identity_probe=identity_probe,
            decision_probe=decision_probe,
        )
        self.assertEqual((report.status, report.exit_code), ("gpu_runtime_not_validated", INFRA_ERROR))
        self.assertEqual(report.runtime_capability, "cpu_only_x64")
        self.assertEqual(report.model_backed_validation, "not_run")
        identity_probe.assert_not_called()
        decision_probe.assert_not_called()

    def test_doctor_distinguishes_service_schema_and_success(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        config = self._config(model=os.fspath(model))

        def unavailable(_config: RuntimeConfig) -> dict[str, object]:
            raise ServiceUnavailableError("not running")

        report = run_doctor(
            config,
            runtime_inspector=self._gpu_ready_runtime,
            identity_probe=lambda _config, _model: None,
            decision_probe=unavailable,
        )
        self.assertEqual((report.status, report.exit_code), ("service_unavailable", SERVICE_UNAVAILABLE))

        def bad_schema(_config: RuntimeConfig) -> dict[str, object]:
            raise StructuredOutputError("invalid")

        report = run_doctor(
            config,
            runtime_inspector=self._gpu_ready_runtime,
            identity_probe=lambda _config, _model: None,
            decision_probe=bad_schema,
        )
        self.assertEqual((report.status, report.exit_code), ("service_schema_error", STRUCTURED_OUTPUT_ERROR))

        report = run_doctor(
            config,
            runtime_inspector=self._gpu_ready_runtime,
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
            identity = self._publish_identity(config, model)
            try:
                with mock.patch(
                    "rondo_eval.local_approval.launcher._load_runtime_lock"
                ) as runtime_lock:
                    runtime_lock.return_value.identity_sha256 = "a" * 64
                    report = run_doctor(config, runtime_inspector=self._gpu_ready_runtime)
            finally:
                clear_launcher_identity(config, identity)
        self.assertEqual((report.status, report.exit_code), ("ready", SUCCESS))
        self.assertEqual(report.runtime_capability, "gpu_model_serving_validated")
        self.assertEqual(
            report.model_backed_validation,
            "model_schema_probe_passed",
        )

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
            identity = self._publish_identity(config, model)
            try:
                with mock.patch(
                    "rondo_eval.local_approval.launcher._load_runtime_lock"
                ) as runtime_lock:
                    runtime_lock.return_value.identity_sha256 = "a" * 64
                    report = run_doctor(config, runtime_inspector=self._gpu_ready_runtime)
            finally:
                clear_launcher_identity(config, identity)
        self.assertEqual(
            (report.status, report.exit_code),
            ("service_schema_error", STRUCTURED_OUTPUT_ERROR),
        )

    def test_decision_rejects_launcher_receipt_replacement_mid_request(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        receipt_path = self.root / "eval-data/local-approval/launcher-identity.json"
        with FakeApprovalServer(
            model_path=os.fspath(model),
            on_decision=lambda: receipt_path.unlink(),
        ) as fake:
            config = RuntimeConfig(
                self.paths,
                _local_data(
                    fake.base_url,
                    model_path_value=os.fspath(model),
                    model_sha256_value=hashlib.sha256(model.read_bytes()).hexdigest(),
                ),
                "0" * 64,
            )
            identity = self._publish_identity(config, model)
            with mock.patch(
                "rondo_eval.local_approval.launcher._load_runtime_lock"
            ) as runtime_lock:
                runtime_lock.return_value.identity_sha256 = "a" * 64
                with self.assertRaises(ServiceUnavailableError):
                    LocalApprovalClient(config).decide(_payload())
            clear_launcher_identity(config, identity)
        self.assertEqual(len(fake.requests), 1)

    def test_old_identity_is_rejected_after_any_service_configuration_change(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        with FakeApprovalServer(model_path=os.fspath(model)) as fake:
            original = RuntimeConfig(
                self.paths,
                _local_data(
                    fake.base_url,
                    model_path_value=os.fspath(model),
                    model_sha256_value=hashlib.sha256(model.read_bytes()).hexdigest(),
                ),
                "0" * 64,
            )
            identity = self._publish_identity(original, model)
            try:
                valid_changes = (
                    {"context_size": 8192},
                    {"gpu_layers": "all"},
                    {"gpu_layers": 17},
                    {"fit": "off"},
                    {"batch_size": 1024},
                    {"ubatch_size": 128},
                    {"flash_attention": "off"},
                    {"metrics": False},
                    {"slots": False},
                    {"binary": "eval-data/tools/other/llama-server"},
                    {"chat_template_sha256": "0" * 64},
                    {
                        "chat_template_file":
                        "eval/templates/local-approval/other.jinja"
                    },
                )
                with mock.patch(
                    "rondo_eval.local_approval.launcher._load_runtime_lock"
                ) as runtime_lock:
                    runtime_lock.return_value.identity_sha256 = "a" * 64
                    for change in valid_changes:
                        with self.subTest(change=change):
                            changed = RuntimeConfig(
                                self.paths,
                                _local_data(
                                    fake.base_url,
                                    model_path_value=os.fspath(model),
                                    model_sha256_value=hashlib.sha256(
                                        model.read_bytes()
                                    ).hexdigest(),
                                    server_overrides=change,
                                ),
                                "0" * 64,
                            )
                            with self.assertRaises(ServiceUnavailableError):
                                LocalApprovalClient(changed).decide(_payload())

                changed_quantization = RuntimeConfig(
                    self.paths,
                    _local_data(
                        fake.base_url,
                        model_path_value=os.fspath(model),
                        model_sha256_value=hashlib.sha256(model.read_bytes()).hexdigest(),
                    ),
                    "0" * 64,
                )
                changed_quantization.data["local_model"]["quantization"] = "Q4_K_S"
                with mock.patch(
                    "rondo_eval.local_approval.launcher._load_runtime_lock"
                ) as runtime_lock:
                    runtime_lock.return_value.identity_sha256 = "a" * 64
                    with self.assertRaises(ServiceUnavailableError):
                        LocalApprovalClient(changed_quantization).decide(_payload())

                invalid_changes = (
                    {"cache_type_k": "q8_0"},
                    {"cache_type_v": "q8_0"},
                    {"no_mmproj": False},
                    {"jinja": False},
                    {"parallel": 2},
                )
                for change in invalid_changes:
                    with self.subTest(change=change), self.assertRaises(ConfigError):
                        LocalApprovalClient(
                            RuntimeConfig(
                                self.paths,
                                _local_data(
                                    fake.base_url,
                                    model_path_value=os.fspath(model),
                                    model_sha256_value=hashlib.sha256(
                                        model.read_bytes()
                                    ).hexdigest(),
                                    server_overrides=change,
                                ),
                                "0" * 64,
                            )
                        )
            finally:
                clear_launcher_identity(original, identity)
        self.assertEqual(fake.requests, [])

    def test_legacy_and_malformed_receipts_are_rejected_before_network(self) -> None:
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
            receipt = self.root / "eval-data/local-approval/launcher-identity.json"
            for case in ("v1", "malformed"):
                with self.subTest(case=case):
                    self._publish_identity(config, model)
                    value = json.loads(receipt.read_bytes())
                    if case == "v1":
                        value["schema_version"] = 1
                        value.pop("serve_config_sha256")
                    else:
                        value["serve_config_sha256"] = 7
                    receipt.write_text(json.dumps(value), encoding="utf-8")
                    os.chmod(receipt, 0o600)
                    with mock.patch(
                        "rondo_eval.local_approval.launcher._load_runtime_lock"
                    ) as runtime_lock:
                        runtime_lock.return_value.identity_sha256 = "a" * 64
                        with self.assertRaises(ServiceUnavailableError):
                            LocalApprovalClient(config).decide(_payload())
        self.assertEqual(fake.requests, [])

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
