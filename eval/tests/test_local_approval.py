from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import tomllib
import unittest
import urllib.error
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
from rondo_eval.local_approval import model_backed, qualification, token_census  # noqa: E402
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
    LLAMA_CPP_CUDA_BINARY_SHA256,
    LLAMA_CPP_CUDA_CAPABILITY,
    LauncherError,
    ModelMissingError,
    RouterProbe,
    RuntimeInspection,
    RuntimeLock,
    _get_json,
    _load_runtime_lock,
    _model_backed_capability,
    _verify_elf_metadata,
    _verify_host_dependency_closure,
    _verify_runtime_closure,
    build_serve_command,
    chat_template,
    inspect_runtime,
    main as launcher_main,
    model_path,
    resolve_binary,
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


# Shortened but format-exact llama.cpp b10333 CUDA load output.
_CUDA_LOAD_LOG = (
    "ggml_cuda_init: found 1 CUDA devices (Total VRAM: 8187 MiB):\n"
    "  Device 0: NVIDIA GeForce RTX 4060 Laptop GPU, compute capability 8.9, "
    "VMM: yes, VRAM: 8187 MiB\n"
    "load_tensors: offloading 32 repeating layers to GPU\n"
    "load_tensors: offloading output layer to GPU\n"
    "load_tensors: offloaded 33/33 layers to GPU\n"
    "llama_context: n_ctx         = 4096\n"
    "main: server is listening on http://127.0.0.1:8080 - starting the main loop\n"
)


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

    def test_model_backed_consumer_converts_runtime_lock_drift_before_network(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        with FakeApprovalServer(model_path=os.fspath(model)) as fake:
            config = self._config(
                fake.base_url,
                model_path_value=os.fspath(model),
                model_sha256_value=digest,
            )
            with mock.patch(
                "rondo_eval.local_approval.launcher.resolve_binary",
                return_value=self.root / "llama-server",
            ), mock.patch(
                "rondo_eval.local_approval.launcher._load_runtime_lock",
                side_effect=ValueError("lock drift"),
            ):
                with self.assertRaises(ServiceUnavailableError):
                    LocalApprovalClient(config).decide(_payload())
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
        self.assertEqual(
            settings.binary,
            "eval-data/tools/llama-b10333-cuda-linux-x64/llama-server",
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
    def _cuda_model_free_runtime(
        _config: RuntimeConfig, _settings: object
    ) -> RuntimeInspection:
        return RuntimeInspection(
            "runtime_ready",
            Path("/fake/llama-server"),
            "fixture-only CUDA model-free capability",
            "b" * 64,
            LLAMA_CPP_CUDA_CAPABILITY,
            "not_run",
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

    def test_run_server_rejects_cuda_runtime_without_model_backed_validation(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        lease = runtime_bridge.WatchdogLease(token="d" * 48)
        guard = mock.Mock()
        guard.is_held.return_value = True
        watchdog = runtime_bridge.WatchdogProof(lease=lease, guard=guard)
        popen = mock.Mock()
        with mock.patch(
            "rondo_eval.local_approval.launcher.inspect_runtime",
            side_effect=self._cuda_model_free_runtime,
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

    def test_model_free_loopback_probe_does_not_use_ambient_proxy(self) -> None:
        with FakeApprovalServer() as fake, mock.patch.dict(
            os.environ,
            {"HTTP_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""},
            clear=False,
        ):
            props_url = fake.base_url.removesuffix("/v1") + "/props"
            props = _get_json(props_url, timeout=1.0)
        self.assertEqual(props["role"], "router")

    def test_model_free_loopback_probe_rejects_redirect(self) -> None:
        with FakeApprovalServer() as target:
            target_health = target.base_url.removesuffix("/v1") + "/health"
            with FakeApprovalServer(get_redirect_to=target_health) as redirect:
                health_url = redirect.base_url.removesuffix("/v1") + "/health"
                with self.assertRaises(urllib.error.HTTPError):
                    _get_json(health_url, timeout=1.0)

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

    def test_doctor_reports_exact_cuda_intermediate_state_without_model(self) -> None:
        identity_probe = mock.Mock()
        decision_probe = mock.Mock()
        report = run_doctor(
            self._config(),
            runtime_inspector=self._cuda_model_free_runtime,
            router_probe=self._ready_router,
            identity_probe=identity_probe,
            decision_probe=decision_probe,
        )
        self.assertEqual(report.status, LLAMA_CPP_CUDA_CAPABILITY)
        self.assertEqual(report.exit_code, MODEL_MISSING)
        self.assertEqual(report.runtime, LLAMA_CPP_CUDA_CAPABILITY)
        self.assertEqual(report.model, "missing")
        self.assertEqual(report.service, "not_started")
        self.assertEqual(report.runtime_capability, LLAMA_CPP_CUDA_CAPABILITY)
        self.assertEqual(report.model_backed_validation, "not_run")
        identity_probe.assert_not_called()
        decision_probe.assert_not_called()

    def test_doctor_does_not_promote_cuda_intermediate_state_with_model(self) -> None:
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        identity_probe = mock.Mock()
        decision_probe = mock.Mock()
        report = run_doctor(
            self._config(model=os.fspath(model)),
            runtime_inspector=self._cuda_model_free_runtime,
            identity_probe=identity_probe,
            decision_probe=decision_probe,
        )
        self.assertEqual((report.status, report.exit_code), (LLAMA_CPP_CUDA_CAPABILITY, INFRA_ERROR))
        self.assertEqual(report.runtime, LLAMA_CPP_CUDA_CAPABILITY)
        self.assertEqual(report.model, "present")
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
                    "rondo_eval.local_approval.launcher.resolve_binary",
                    return_value=self.root / "llama-server",
                ), mock.patch(
                    "rondo_eval.local_approval.launcher._load_runtime_lock"
                ) as runtime_lock:
                    runtime_lock.return_value.identity_sha256 = "a" * 64
                    report = run_doctor(config, runtime_inspector=self._gpu_ready_runtime)
                    runtime_lock.assert_called_with(config, self.root / "llama-server")
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
                    "rondo_eval.local_approval.launcher.resolve_binary",
                    return_value=self.root / "llama-server",
                ), mock.patch(
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
                "rondo_eval.local_approval.launcher.resolve_binary",
                return_value=self.root / "llama-server",
            ), mock.patch(
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
        self.assertEqual(
            LLAMA_CPP_CUDA_BINARY_SHA256,
            "97a6b083ea34fea7e4e4440a0ddb734e1a2f6b775f4b31ef68ba5f998a9eeabd",
        )
        self.assertEqual(
            LLAMA_CPP_CUDA_CAPABILITY,
            "linux_cuda_built_model_unvalidated",
        )

    def test_runtime_lock_selector_is_exact_for_cpu_cuda_and_unknown_paths(self) -> None:
        for relative in (
            "eval-data/tools/llama-b10333/llama-server",
            "eval-data/tools/llama-b10333-cuda-linux-x64/llama-server",
        ):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"server")
        cpu_lock = self.root / "eval/locks/llama-cpp-b10333.json"
        cpu_lock.parent.mkdir(parents=True, exist_ok=True)
        cpu_lock.write_bytes((REPO_ROOT / "eval/locks/llama-cpp-b10333.json").read_bytes())
        cuda_lock = self.root / "eval/locks/llama-cpp-b10333-cuda-linux-x64.json"
        cuda_lock.write_bytes(
            (REPO_ROOT / "eval/locks/llama-cpp-b10333-cuda-linux-x64.json").read_bytes()
        )
        config = self._config()
        cpu = _load_runtime_lock(
            config, self.root / "eval-data/tools/llama-b10333/llama-server"
        )
        cuda = _load_runtime_lock(
            config,
            self.root
            / "eval-data/tools/llama-b10333-cuda-linux-x64/llama-server",
        )
        self.assertEqual(cpu.capability, "cpu_only_x64")
        self.assertEqual(cuda.capability, LLAMA_CPP_CUDA_CAPABILITY)
        unknown = self.root / "eval-data/tools/other/llama-server"
        unknown.parent.mkdir(parents=True)
        unknown.write_bytes(b"server")
        with self.assertRaises(ValueError):
            _load_runtime_lock(config, unknown)

    def test_configured_binary_rejects_path_command_absolute_and_symlink_alias(self) -> None:
        cuda = self.root / "eval-data/tools/llama-b10333-cuda-linux-x64/llama-server"
        cuda.parent.mkdir(parents=True)
        cuda.write_bytes(b"server")
        os.chmod(cuda, 0o700)
        alias = self.root / "eval-data/tools/alias/llama-server"
        alias.parent.mkdir(parents=True)
        alias.symlink_to(cuda)
        for configured in (
            "llama-server",
            os.fspath(cuda),
            "eval-data/tools/alias/llama-server",
            "eval-data/tools/other/llama-server",
        ):
            with self.subTest(configured=configured):
                config = self._config(server_overrides={"binary": configured})
                self.assertIsNone(resolve_binary(config, settings_from_config(config)))

    def test_exact_cuda_spelling_cannot_cross_link_to_cpu_runtime(self) -> None:
        cpu = self.root / "eval-data/tools/llama-b10333/llama-server"
        cpu.parent.mkdir(parents=True)
        cpu.write_bytes(b"cpu-server")
        os.chmod(cpu, 0o700)
        cuda_relative = "eval-data/tools/llama-b10333-cuda-linux-x64/llama-server"
        cuda = self.root / cuda_relative
        cuda.parent.mkdir(parents=True)
        cuda.symlink_to(cpu)
        config = self._config(server_overrides={"binary": cuda_relative})
        self.assertIsNone(resolve_binary(config, settings_from_config(config)))

        cuda.unlink()
        cuda.parent.rmdir()
        cuda.parent.symlink_to(cpu.parent, target_is_directory=True)
        self.assertIsNone(resolve_binary(config, settings_from_config(config)))

    def test_cuda_lock_schema_and_build_choices_are_frozen(self) -> None:
        value = json.loads(
            (REPO_ROOT / "eval/locks/llama-cpp-b10333-cuda-linux-x64.json").read_bytes()
        )
        self.assertEqual(value["source"]["commit"], LLAMA_CPP_COMMIT)
        self.assertEqual(value["toolkit"]["version"], "12.6.2")
        self.assertEqual(value["build"]["architecture"], "89-real")
        self.assertFalse(value["build"]["cub_3dot2"])
        self.assertFalse(value["build"]["permissive_linker_flag"])
        self.assertEqual(value["capability"], LLAMA_CPP_CUDA_CAPABILITY)
        self.assertEqual(value["model_backed_structured_output"], "not_run")

    def test_cuda_lock_rejects_missing_toolchain_identity(self) -> None:
        lock_path = self.root / "eval/locks/llama-cpp-b10333-cuda-linux-x64.json"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        value = json.loads(
            (REPO_ROOT / "eval/locks/llama-cpp-b10333-cuda-linux-x64.json").read_bytes()
        )
        value["toolchain"]["identity_files"].pop("/usr/bin/cmake")
        lock_path.write_text(json.dumps(value), encoding="utf-8")
        binary = self.root / "eval-data/tools/llama-b10333-cuda-linux-x64/llama-server"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"server")
        with self.assertRaises(ValueError):
            _load_runtime_lock(self._config(), binary)

    def test_cuda_elf_probe_rejects_needed_or_runpath_drift(self) -> None:
        runtime = self.root / "runtime"
        runtime.mkdir()
        binary = runtime / "llama-server"
        binary.write_bytes(b"server")
        probe = self.root / "readelf"
        probe.write_text(
            "#!/bin/sh\nprintf '%s\\n' "
            "' 0x1 (NEEDED) Shared library: [libfixture.so]' "
            "' 0x1d (RUNPATH) Library runpath: [/toolkit/lib64:$ORIGIN]'\n",
            encoding="utf-8",
        )
        os.chmod(probe, 0o700)
        lock = RuntimeLock(
            runtime.name,
            {binary.name: hashlib.sha256(binary.read_bytes()).hexdigest()},
            {},
            dependency_targets=(binary.name,),
            elf_probe_path=os.fspath(probe),
            elf_probe_sha256=hashlib.sha256(probe.read_bytes()).hexdigest(),
            elf_runpath="/toolkit/lib64:$ORIGIN",
            elf_needed={binary.name: ("libfixture.so",)},
        )
        _verify_elf_metadata(lock, runtime)
        changed = RuntimeLock(
            runtime.name,
            lock.regular_files,
            {},
            dependency_targets=(binary.name,),
            elf_probe_path=os.fspath(probe),
            elf_probe_sha256=lock.elf_probe_sha256,
            elf_runpath="/wrong:$ORIGIN",
            elf_needed=lock.elf_needed,
        )
        with self.assertRaises(ValueError):
            _verify_elf_metadata(changed, runtime)

    def test_runtime_version_probe_requires_build_and_commit(self) -> None:
        relative_binary = "eval-data/tools/llama-b10333/llama-server"
        binary = self.root / relative_binary
        binary.parent.mkdir(parents=True)
        binary.write_text(
            "#!/bin/sh\nprintf '%s\\n' 'version: 10333 (08659901)'\n",
            encoding="utf-8",
        )
        os.chmod(binary, 0o700)
        config = self._config()
        config.data["local_model"]["server"]["binary"] = relative_binary
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

    def test_cuda_runtime_requires_current_exact_device_probe(self) -> None:
        relative_binary = (
            "eval-data/tools/llama-b10333-cuda-linux-x64/llama-server"
        )
        binary = self.root / relative_binary
        binary.parent.mkdir(parents=True)
        binary.write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = --version ]; then\n"
            "  printf '%s\\n' 'version: 1 (0865990)'\n"
            "else\n"
            "  printf '%s\\n' 'Available devices:' "
            "'  CUDA0: NVIDIA GeForce RTX 4060 Laptop GPU (8187 MiB)'\n"
            "fi\n",
            encoding="utf-8",
        )
        os.chmod(binary, 0o700)
        config = self._config(server_overrides={"binary": relative_binary})
        settings = settings_from_config(config)
        with mock.patch(
            "rondo_eval.local_approval.launcher._verify_runtime_closure",
            return_value="b" * 64,
        ):
            inspection = inspect_runtime(config, settings)
            self.assertEqual(inspection.status, "runtime_ready")
            self.assertEqual(inspection.capability, LLAMA_CPP_CUDA_CAPABILITY)
            binary.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = --version ]; then "
                "printf '%s\\n' 'version: 1 (0865990)'; "
                "else printf '%s\\n' 'Available devices:'; fi\n",
                encoding="utf-8",
            )
            self.assertEqual(
                inspect_runtime(config, settings).status,
                "runtime_device_unavailable",
            )

    def test_runtime_closure_mismatch_is_rejected_before_version_probe(self) -> None:
        relative_binary = "eval-data/tools/llama-b10333/llama-server"
        binary = self.root / relative_binary
        binary.parent.mkdir(parents=True)
        binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        os.chmod(binary, 0o700)
        config = self._config()
        config.data["local_model"]["server"]["binary"] = relative_binary
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


class _FakeServerProcess:
    """Minimal Popen stand-in that records how the qualification stops it."""

    def __init__(self, *, log_text: str = _CUDA_LOAD_LOG, exited: bool = False):
        self.pid = 4242
        self.log_text = log_text
        self.terminated = False
        self.killed = False
        self.stubborn = False
        self.unkillable = False
        self._exited = exited

    def __call__(self, command, **kwargs):
        descriptor = kwargs.get("stdout")
        if isinstance(descriptor, int):
            os.write(descriptor, self.log_text.encode("utf-8"))
        self.command = list(command)
        return self

    def poll(self):
        return 0 if self._exited else None

    def terminate(self):
        self.terminated = True
        if not self.stubborn:
            self._exited = True

    def kill(self):
        self.killed = True
        if not self.unkillable:
            self._exited = True

    def wait(self, timeout=None):
        if not self._exited:
            raise subprocess.TimeoutExpired(cmd="llama-server", timeout=timeout or 0)
        return 0


class _FakeGpuSampler:
    def __init__(self, *, used: list[int] | None = None, compute_pids: list[int] | None = None):
        self._used = used or [1_000 * 1024 * 1024, 6_000 * 1024 * 1024]
        self._index = 0
        self._compute_pids = compute_pids or []

    def used_bytes(self) -> int:
        value = self._used[min(self._index, len(self._used) - 1)]
        self._index += 1
        return value

    def compute_process_pids(self) -> list[int]:
        return list(self._compute_pids)


class _FailingGpuSampler:
    """Samples cleanly at first, then breaks or reports a foreign GPU user."""

    def __init__(self, *, fail_after: int | None = None, foreign_after: int | None = None):
        self.calls = 0
        self._fail_after = fail_after
        self._foreign_after = foreign_after

    def used_bytes(self) -> int:
        self.calls += 1
        if self._fail_after is not None and self.calls > self._fail_after:
            raise OSError("nvidia-smi is unavailable")
        return (1_000 + 1_000 * self.calls) * 1024 * 1024

    def compute_process_pids(self) -> list[int]:
        if self._foreign_after is not None and self.calls > self._foreign_after:
            return [999_999]
        return []


class _NeverJoiningThread:
    def join(self, timeout: float | None = None) -> None:
        return None

    def is_alive(self) -> bool:
        return True


class ModelBackedQualificationTests(unittest.TestCase):
    """Failure classes for the restricted 4k qualification and its evidence."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        _install_template_fixture(self.root)
        (self.root / "rondo.secrets.example.env").write_text(
            "RONDO_LOCAL_MODEL_API_KEY=\n", encoding="utf-8"
        )
        self.model = self.root / "eval-data/models/fixture.gguf"
        self.model.parent.mkdir(parents=True)
        self.model.write_bytes(b"GGUFqualification-fixture")
        self.model_sha256 = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.run_id = "20260812-370000005-tb-rondo-r1"
        self.review_id = "e2759768-bb16-4230-9f9a-7f4890af51c6"
        self.evidence_relative = (
            f"eval-data/runs/{self.run_id}/guardian-evidence/0003/E_final.json"
        )
        self.install_evidence_bundle()
        patcher = mock.patch.multiple(
            model_backed,
            MODEL_RELATIVE_PATH="eval-data/models/fixture.gguf",
            MODEL_SIZE_BYTES=self.model.stat().st_size,
            MODEL_SHA256=self.model_sha256,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def install_evidence_bundle(
        self, *, e_final: bytes | None = None, meta: dict | None = None
    ) -> None:
        """Install a production-shaped bundle and the tracked records binding it."""

        source = self.root / self.evidence_relative
        if source.parent.is_symlink():
            source.parent.unlink()
        source.parent.mkdir(parents=True, exist_ok=True)
        e_final_bytes = e_final if e_final is not None else json.dumps(
            {
                "instructions": "frozen guardian policy fixture",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "approve this fixture action?"}
                        ],
                    }
                ],
            }
        ).encode("utf-8")
        meta_bytes = json.dumps(
            meta
            if meta is not None
            else {
                "review_id": self.review_id,
                "guardian_source_baseline": "rust-v0.147.0",
                "guardian_source_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                "evidence": "e_final",
                "decision": "approved",
                "terminal_status": "approved",
                "failure_reason": None,
                "attempt_count": 1,
                "duration_ms": 4029,
                "guardian_thread_id": "019ff83b-f1b0-71e2-a97e-09bf33d6970a",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "low",
                "token_usage": {
                    "input_tokens": 11616,
                    "cached_input_tokens": 9984,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 60,
                    "reasoning_output_tokens": 0,
                    "total_tokens": 11676,
                },
                "time_to_first_token_ms": 3182,
            }
        ).encode("utf-8")
        source.write_bytes(e_final_bytes)
        (source.parent / "meta.json").write_bytes(meta_bytes)

        selector = self.root / qualification.SELECTOR_RELATIVE_PATH
        selector.parent.mkdir(parents=True, exist_ok=True)
        selector.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "purpose": "qualification fixture",
                    "run_id": self.run_id,
                    "run_artifacts_relative_path": f"eval-data/runs/{self.run_id}",
                    "relative_path": self.evidence_relative,
                    "review_id": self.review_id,
                    "e_final_sha256": hashlib.sha256(e_final_bytes).hexdigest(),
                    "e_final_size_bytes": len(e_final_bytes),
                    "meta_sha256": hashlib.sha256(meta_bytes).hexdigest(),
                    "meta_size_bytes": len(meta_bytes),
                    "guardian_source_baseline": "rust-v0.147.0",
                    "guardian_source_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                    "expected_guardian_model": "gpt-5.6-sol",
                    "expected_guardian_effort": "low",
                    "request_shape": "standard",
                }
            ),
            encoding="utf-8",
        )
        ledger = self.root / "eval/results/runs.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "artifacts": f"eval-data/runs/{self.run_id}",
                    "outcome": "completed",
                    "config": {
                        "effective_guardian_model": "gpt-5.6-sol",
                        "guardian_effort": "low",
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _config(self, *, server_overrides: dict | None = None) -> RuntimeConfig:
        overrides = {"binary": model_backed.CUDA_SERVER_RELATIVE_PATH}
        overrides.update(server_overrides or {})
        return RuntimeConfig(
            self.paths,
            _local_data(
                f"http://127.0.0.1:{self._free_port()}/v1",
                model_path_value="eval-data/models/fixture.gguf",
                model_sha256_value=self.model_sha256,
                server_overrides=overrides,
            ),
            "0" * 64,
        )

    @staticmethod
    def _cuda_runtime(_config: RuntimeConfig, _settings: object) -> RuntimeInspection:
        return RuntimeInspection(
            "runtime_ready",
            Path("/fake/llama-server"),
            "fixture CUDA runtime",
            "b" * 64,
            LLAMA_CPP_CUDA_CAPABILITY,
            model_backed.MODEL_BACKED_NOT_RUN,
        )

    @staticmethod
    def _http(props: dict | None = None, slots: object = None):
        default_props = {
            "build_info": model_backed.CUDA_SERVICE_BUILD_INFO,
            "default_generation_settings": {"n_ctx": 4096},
            "total_slots": 1,
        }
        default_slots = [{"is_processing": True, "next_token": [{"n_decoded": 3}]}]

        def get(url: str, *, timeout: float):
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/props"):
                return default_props if props is None else props
            if url.endswith("/slots"):
                return default_slots if slots is None else slots
            raise AssertionError(f"unexpected qualification probe: {url}")

        return get

    def _run(self, config: RuntimeConfig, **overrides):
        lease = runtime_bridge.WatchdogLease(token="e" * 48)
        guard = mock.Mock()
        guard.is_held.return_value = True
        arguments = {
            "evidence_relative_path": self.evidence_relative,
            "popen": _FakeServerProcess(),
            "watchdog_factory": lambda: runtime_bridge.WatchdogProof(lease=lease, guard=guard),
            "gpu_sampler": _FakeGpuSampler(),
            "identity_publisher": mock.Mock(return_value=mock.sentinel.identity),
            "identity_clearer": mock.Mock(),
            "verify_identity": mock.Mock(),
            "decide": lambda _config, _payload: {
                "outcome": "deny",
                "rationale": "fixture rationale",
                "risk_tags": ["fixture"],
            },
            "http_get": self._http(),
            "today": lambda: "2026-08-14",
        }
        arguments.update(overrides)
        with mock.patch(
            "rondo_eval.local_approval.qualification.inspect_runtime",
            side_effect=self._cuda_runtime,
        ):
            return qualification.run_qualification(config, **arguments)

    def _promoted_capability(self, config: RuntimeConfig) -> tuple[str, str]:
        return _model_backed_capability(
            config, settings_from_config(config), "b" * 64
        )

    def test_successful_qualification_publishes_evidence_and_promotes_capability(self) -> None:
        config = self._config()
        process = _FakeServerProcess()
        summary = self._run(config, popen=process)

        self.assertEqual(summary["status"], "qualified")
        self.assertEqual(summary["gpu_offloaded_layers"], 33)
        self.assertEqual(summary["effective_context_size"], 4096)
        self.assertGreater(summary["time_to_first_token_ms"], 0)
        self.assertLessEqual(summary["time_to_first_token_ms"], summary["total_decision_ms"])
        self.assertTrue(all(summary["cleanup"].values()))
        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)

        evidence_path = self.root / model_backed.EVIDENCE_RELATIVE_PATH
        raw = evidence_path.read_text(encoding="utf-8")
        self.assertNotIn("rationale", raw.replace('"rationale_non_empty"', ""))
        self.assertNotIn("fixture rationale", raw)
        self.assertNotIn("guardian policy", raw)
        document = json.loads(raw)
        self.assertEqual(document["capability"], "gpu_model_serving_validated")
        self.assertEqual(document["identity"]["context_size"], 4096)
        self.assertEqual(
            document["observed"]["evidence_source"]["relative_path"], self.evidence_relative
        )
        self.assertEqual(
            self._promoted_capability(config),
            ("gpu_model_serving_validated", model_backed.MODEL_BACKED_VALIDATED),
        )
        self.assertEqual(
            list((self.root / "eval-data/local-approval").glob("qualification-*")), []
        )

    def test_second_qualification_is_refused_once_evidence_exists(self) -> None:
        config = self._config()
        self._run(config)
        popen = mock.Mock()
        with self.assertRaises(qualification.QualificationError) as raised:
            self._run(config, popen=popen)
        self.assertEqual(raised.exception.code, "evidence_already_exists")
        popen.assert_not_called()

    def test_contract_violations_are_rejected_before_the_model_starts(self) -> None:
        cases = (
            {"binary": "eval-data/tools/llama-b10333/llama-server"},
            {"context_size": 8192},
            {"gpu_layers": "all"},
            {"fit": "off"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                config = self._config(server_overrides=overrides)
                popen = mock.Mock()
                with self.assertRaises(model_backed.QualificationContractError):
                    self._run(config, popen=popen)
                popen.assert_not_called()

        config = self._config()
        config.data["local_model"]["model_sha256"] = "0" * 64
        popen = mock.Mock()
        with self.assertRaises(model_backed.QualificationContractError):
            self._run(config, popen=popen)
        popen.assert_not_called()
        self.assertFalse((self.root / model_backed.EVIDENCE_RELATIVE_PATH).exists())

    def test_site_preconditions_block_the_model_before_popen(self) -> None:
        config = self._config()
        popen = mock.Mock()
        with self.assertRaises(qualification.QualificationError) as raised:
            self._run(
                config,
                popen=popen,
                watchdog_factory=mock.Mock(
                    side_effect=runtime_bridge.RuntimeBridgeError("unsupervised")
                ),
            )
        self.assertEqual(raised.exception.code, "watchdog_unavailable")

        with self.assertRaises(qualification.QualificationError) as raised:
            self._run(
                config,
                popen=popen,
                gpu_sampler=_FakeGpuSampler(compute_pids=[999]),
            )
        self.assertEqual(raised.exception.code, "gpu_not_exclusive")

        # The qualified server itself is not a foreign GPU user.
        own = _FakeServerProcess()
        own.pid = os.getpid()
        self.assertEqual(
            qualification._foreign_compute_pids(
                _FakeGpuSampler(compute_pids=[os.getpid()]), os.getpid()
            ),
            [],
        )

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            occupied = RuntimeConfig(
                self.paths,
                _local_data(
                    f"http://127.0.0.1:{listener.getsockname()[1]}/v1",
                    model_path_value="eval-data/models/fixture.gguf",
                    model_sha256_value=self.model_sha256,
                    server_overrides={"binary": model_backed.CUDA_SERVER_RELATIVE_PATH},
                ),
                "0" * 64,
            )
            with self.assertRaises(qualification.QualificationError) as raised:
                self._run(occupied, popen=popen)
        self.assertEqual(raised.exception.code, "port_already_in_use")
        popen.assert_not_called()
        self.assertFalse((self.root / model_backed.EVIDENCE_RELATIVE_PATH).exists())

    def test_service_gpu_and_response_failures_never_publish_evidence(self) -> None:
        cases = {
            "server_exited_before_ready": {
                "popen": _FakeServerProcess(exited=True),
            },
            "service_context_differs": {
                "http_get": self._http(
                    props={
                        "build_info": model_backed.CUDA_SERVICE_BUILD_INFO,
                        "default_generation_settings": {"n_ctx": 8192},
                        "total_slots": 1,
                    }
                ),
            },
            "gpu_offload_not_positive": {
                "popen": _FakeServerProcess(
                    log_text=_CUDA_LOAD_LOG.replace(
                        "offloaded 33/33 layers", "offloaded 0/33 layers"
                    )
                ),
            },
            "gpu_offload_not_reported": {
                "popen": _FakeServerProcess(log_text="starting llama-server\n"),
            },
            "first_token_not_observed": {
                "http_get": self._http(
                    slots=[{"is_processing": True, "next_token": [{"n_decoded": 0}]}]
                ),
            },
            "structured_response_invalid": {
                "decide": lambda _config, _payload: {
                    "outcome": "maybe",
                    "rationale": "",
                    "risk_tags": [],
                },
            },
        }
        for code, overrides in cases.items():
            with self.subTest(code=code):
                config = self._config()
                process = overrides.get("popen") or _FakeServerProcess()
                overrides["popen"] = process
                with self.assertRaises(qualification.QualificationError) as raised:
                    self._run(config, **overrides)
                self.assertEqual(raised.exception.code, code)
                self.assertFalse((self.root / model_backed.EVIDENCE_RELATIVE_PATH).exists())
                self.assertEqual(
                    list((self.root / "eval-data/local-approval").glob("qualification-*")),
                    [],
                )
                self.assertEqual(
                    self._promoted_capability(config),
                    (LLAMA_CPP_CUDA_CAPABILITY, model_backed.MODEL_BACKED_NOT_RUN),
                )

    def test_rejected_decision_reports_only_non_sensitive_server_counters(self) -> None:
        config = self._config()
        log = _CUDA_LOAD_LOG + (
            "srv  send_error: task id = 0, error: request (7812 tokens) exceeds "
            "the available context size (4096 tokens), try increasing it\n"
        )

        def refuse(_config: RuntimeConfig, _payload: object) -> dict[str, object]:
            raise ServiceUnavailableError("rejected")

        with self.assertRaises(qualification.QualificationError) as raised:
            self._run(config, popen=_FakeServerProcess(log_text=log), decide=refuse)
        self.assertEqual(raised.exception.code, "structured_decision_failed")
        facts = raised.exception.facts
        self.assertEqual(facts["prompt_tokens"], 7812)
        self.assertEqual(facts["context_size"], 4096)
        self.assertEqual(facts["server_error_class"], "exceeds the available context size")
        self.assertTrue(all(facts["cleanup"].values()))
        self.assertNotIn("rationale", json.dumps(facts))
        self.assertFalse((self.root / model_backed.EVIDENCE_RELATIVE_PATH).exists())

    def test_vram_sampling_gaps_block_promotion_even_after_a_positive_delta(self) -> None:
        config = self._config()
        cases = {
            "gpu_sampling_failed": _FailingGpuSampler(fail_after=2),
            "gpu_not_exclusive": _FailingGpuSampler(foreign_after=2),
        }
        for code, sampler in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(qualification.QualificationError) as raised:
                    self._run(config, gpu_sampler=sampler)
                self.assertEqual(raised.exception.code, code)
                # The window did record a real positive delta before it broke.
                self.assertGreater(sampler.calls, 1)
                self.assertFalse((self.root / model_backed.EVIDENCE_RELATIVE_PATH).exists())

    def test_sampler_that_will_not_stop_blocks_promotion(self) -> None:
        sampler = _FakeGpuSampler()
        peak = qualification._PeakSampler(sampler, 1, os.getpid())
        peak.observe()
        peak._thread = _NeverJoiningThread()
        with self.assertRaises(qualification.QualificationError) as raised:
            peak.finalize()
        self.assertEqual(raised.exception.code, "gpu_sampling_thread_stuck")

    def test_incomplete_cleanup_blocks_promotion(self) -> None:
        config = self._config()
        stubborn = _FakeServerProcess()
        stubborn.stubborn = True
        stubborn.unkillable = True
        with self.assertRaises(qualification.QualificationError) as raised:
            self._run(config, popen=stubborn)
        self.assertEqual(raised.exception.code, "cleanup_incomplete")
        self.assertTrue(stubborn.terminated)
        self.assertTrue(stubborn.killed)
        self.assertFalse((self.root / model_backed.EVIDENCE_RELATIVE_PATH).exists())

    def test_missing_invalid_and_mismatched_evidence_stay_unvalidated(self) -> None:
        config = self._config()
        self.assertEqual(
            self._promoted_capability(config),
            (LLAMA_CPP_CUDA_CAPABILITY, model_backed.MODEL_BACKED_NOT_RUN),
        )
        self._run(config)
        evidence_path = self.root / model_backed.EVIDENCE_RELATIVE_PATH
        valid = json.loads(evidence_path.read_text(encoding="utf-8"))

        mutations = {
            "not-json": lambda value: None,
            "missing-group": lambda value: value.pop("cleanup"),
            "extra-field": lambda value: value["observed"].update({"unexpected": 1}),
            "zero-offload": lambda value: value["observed"].update({"gpu_offloaded_layers": 0}),
            "incomplete-cleanup": lambda value: value["cleanup"].update({"port_released": False}),
            "foreign-context": lambda value: value["identity"].update({"context_size": 8192}),
            "wrong-capability": lambda value: value.update({"capability": "cpu_only_x64"}),
        }
        for case, mutate in mutations.items():
            with self.subTest(case=case):
                if case == "not-json":
                    evidence_path.write_text("{", encoding="utf-8")
                else:
                    value = json.loads(json.dumps(valid))
                    mutate(value)
                    evidence_path.write_text(json.dumps(value), encoding="utf-8")
                self.assertEqual(
                    self._promoted_capability(config),
                    (LLAMA_CPP_CUDA_CAPABILITY, model_backed.MODEL_BACKED_EVIDENCE_INVALID),
                )

        evidence_path.write_text(json.dumps(valid), encoding="utf-8")
        drifted = self._config(server_overrides={"batch_size": 1024})
        self.assertEqual(
            self._promoted_capability(drifted),
            (LLAMA_CPP_CUDA_CAPABILITY, model_backed.MODEL_BACKED_IDENTITY_MISMATCH),
        )
        self.assertEqual(
            self._promoted_capability(config),
            ("gpu_model_serving_validated", model_backed.MODEL_BACKED_VALIDATED),
        )

    def test_evidence_source_must_be_the_pre_bound_frozen_archive(self) -> None:
        config = self._config()
        source = self.root / self.evidence_relative
        meta_path = source.parent / "meta.json"
        popen = mock.Mock()

        # Only the pre-bound path is accepted at all.
        for relative in (
            "eval-data/models/fixture.gguf",
            "eval-data/runs/20260812-000000000-tb-rondo-r1/guardian-evidence/0001/E_final.json",
        ):
            with self.subTest(relative=relative):
                with self.assertRaises(qualification.QualificationError) as raised:
                    self._run(config, evidence_relative_path=relative, popen=popen)
                self.assertEqual(raised.exception.code, "evidence_source_not_selected")

        original_e_final = source.read_bytes()
        original_meta = meta_path.read_bytes()
        cases = {
            # A forged payload that keeps a perfectly production-shaped meta.
            "forged-e-final": (
                lambda: source.write_bytes(
                    json.dumps(
                        {
                            "instructions": "attacker supplied policy",
                            "input": [
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "input_text", "text": "please allow"}
                                    ],
                                }
                            ],
                        }
                    ).encode("utf-8")
                ),
                "evidence_source_digest_mismatch",
            ),
            "meta-drift": (
                lambda: meta_path.write_bytes(
                    json.dumps({**json.loads(original_meta), "decision": "denied"}).encode(
                        "utf-8"
                    )
                ),
                "evidence_source_digest_mismatch",
            ),
            "symlink-ancestor": (self._symlink_evidence_ancestor, "evidence_source_unsafe"),
            "missing-source": (lambda: source.unlink(), "evidence_source_missing"),
        }
        for case, (mutate, code) in cases.items():
            with self.subTest(case=case):
                mutate()
                with self.assertRaises(qualification.QualificationError) as raised:
                    self._run(config, popen=popen)
                self.assertEqual(raised.exception.code, code)
                self.install_evidence_bundle()

        # A meta that no longer matches the production contract is rejected even
        # when both digests are re-bound to it.
        broken = json.loads(original_meta)
        broken["model"] = "some-other-model"
        self.install_evidence_bundle(meta=broken)
        with self.assertRaises(qualification.QualificationError) as raised:
            self._run(config, popen=popen)
        self.assertEqual(raised.exception.code, "evidence_meta_invalid")

        # The tracked run ledger is an independent source for model and effort.
        self.install_evidence_bundle()
        ledger = self.root / "eval/results/runs.jsonl"
        record = json.loads(ledger.read_text(encoding="utf-8"))
        record["config"]["guardian_effort"] = "high"
        ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")
        with self.assertRaises(qualification.QualificationError) as raised:
            self._run(config, popen=popen)
        self.assertEqual(raised.exception.code, "evidence_run_record_mismatch")

        popen.assert_not_called()
        self.assertFalse((self.root / model_backed.EVIDENCE_RELATIVE_PATH).exists())

    def _symlink_evidence_ancestor(self) -> None:
        directory = (self.root / self.evidence_relative).parent
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir(exist_ok=True)
        for item in directory.iterdir():
            item.replace(elsewhere / item.name)
        directory.rmdir()
        directory.symlink_to(elsewhere, target_is_directory=True)

    def test_tracked_qualification_selector_matches_the_tracked_run_ledger(self) -> None:
        selector = json.loads(
            (REPO_ROOT / qualification.SELECTOR_RELATIVE_PATH).read_bytes()
        )
        record = None
        for line in (REPO_ROOT / "eval/results/runs.jsonl").read_text(
            encoding="utf-8"
        ).splitlines():
            if selector["run_id"] in line:
                candidate = json.loads(line)
                if candidate.get("run_id") == selector["run_id"]:
                    record = candidate
                    break
        self.assertIsNotNone(record)
        self.assertEqual(record["artifacts"], selector["run_artifacts_relative_path"])
        self.assertEqual(record["outcome"], "completed")
        self.assertEqual(
            record["config"]["effective_guardian_model"],
            selector["expected_guardian_model"],
        )
        self.assertEqual(
            record["config"]["guardian_effort"], selector["expected_guardian_effort"]
        )
        self.assertTrue(
            selector["relative_path"].startswith(
                f"{selector['run_artifacts_relative_path']}/guardian-evidence/"
            )
        )

    def test_service_build_identity_is_exact_for_each_frozen_backend(self) -> None:
        self.assertEqual(model_backed.CUDA_SERVICE_BUILD_INFO, "b1-0865990")
        self.assertEqual(model_backed.CPU_SERVICE_BUILD_INFO, "b10333-08659901c")
        model = self.root / "model.gguf"
        model.write_bytes(b"GGUFfake-model-fixture")
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        for binary, served, accepted in (
            (model_backed.CUDA_SERVER_RELATIVE_PATH, "b1-0865990", True),
            (model_backed.CUDA_SERVER_RELATIVE_PATH, "b10333-08659901c", False),
            ("eval-data/tools/llama-b10333/llama-server", "b10333-08659901c", True),
            ("eval-data/tools/llama-b10333/llama-server", "b1-0865990", False),
        ):
            with self.subTest(binary=binary, served=served):
                with FakeApprovalServer(
                    model_path=os.fspath(model), build_info=served
                ) as fake:
                    config = RuntimeConfig(
                        self.paths,
                        _local_data(
                            fake.base_url,
                            model_path_value=os.fspath(model),
                            model_sha256_value=digest,
                            server_overrides={"binary": binary},
                        ),
                        "0" * 64,
                    )
                    client = LocalApprovalClient(config)
                    verify = lambda: client.verify_service_identity(  # noqa: E731
                        model,
                        expected_build_info=model_backed.service_build_info(client.settings),
                    )
                    if accepted:
                        verify()
                    else:
                        with self.assertRaises(StructuredOutputError):
                            verify()


class TokenCensusTests(unittest.TestCase):
    """Input-set completeness, fit arithmetic, stable output and anchor gating.

    The reader, meta validator and serving contract already have their own
    coverage above; these cases only exercise what the census itself decides.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        _install_template_fixture(self.root)
        (self.root / "rondo.secrets.example.env").write_text(
            "RONDO_LOCAL_MODEL_API_KEY=\n", encoding="utf-8"
        )
        self.model = self.root / "eval-data/models/fixture.gguf"
        self.model.parent.mkdir(parents=True)
        self.model.write_bytes(b"GGUFcensus-fixture")
        self.model_sha256 = hashlib.sha256(self.model.read_bytes()).hexdigest()
        patcher = mock.patch.multiple(
            model_backed,
            MODEL_RELATIVE_PATH="eval-data/models/fixture.gguf",
            MODEL_SIZE_BYTES=self.model.stat().st_size,
            MODEL_SHA256=self.model_sha256,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ledger: list[dict] = []
        self.bundles: list[tuple[str, str]] = []
        for slot in range(1, 4):
            self.bundles.append(self._install_bundle(slot))
        # The anchor is the first bundle; the tracked selector binds it exactly
        # the way Plan 023 bound the single measured E_final.
        self._install_selector(*self.bundles[0])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _install_bundle(self, slot: int, *, body: bytes | None = None) -> tuple[str, str]:
        run_id = f"20260812-370000{slot:03d}-tb-rondo-r1"
        review_id = f"e2759768-bb16-4230-9f9a-7f4890af5{slot:03d}"
        e_final_bytes = body if body is not None else json.dumps(
            {
                "instructions": "frozen guardian policy fixture",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": f"approve fixture action {slot}?"}
                        ],
                    }
                ],
            }
        ).encode("utf-8")
        directory = self.root / f"eval-data/runs/{run_id}/guardian-evidence/{slot:04d}"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "E_final.json").write_bytes(e_final_bytes)
        (directory / "meta.json").write_text(
            json.dumps(
                {
                    "review_id": review_id,
                    "guardian_source_baseline": "rust-v0.147.0",
                    "guardian_source_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                    "evidence": "e_final",
                    "decision": "approved",
                    "terminal_status": "approved",
                    "failure_reason": None,
                    "attempt_count": 1,
                    "duration_ms": 4029,
                    "guardian_thread_id": None,
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "low",
                    "token_usage": None,
                    "time_to_first_token_ms": None,
                }
            ),
            encoding="utf-8",
        )
        self.ledger.append(
            {
                "run_id": run_id,
                "artifacts": f"eval-data/runs/{run_id}",
                # An infra-failed run still archived valid evidence; the census
                # must not drop it.
                "outcome": "infra_failed" if slot == 2 else "completed",
                "config": {
                    "effective_guardian_model": "gpt-5.6-sol",
                    "guardian_effort": "low",
                },
            }
        )
        self._write_ledger()
        relative = f"eval-data/runs/{run_id}/guardian-evidence/{slot:04d}/E_final.json"
        return relative, hashlib.sha256(e_final_bytes).hexdigest()

    def _write_ledger(self, records: list[dict] | None = None) -> None:
        ledger = self.root / "eval/results/runs.jsonl"
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(
            "".join(json.dumps(record) + "\n" for record in records or self.ledger),
            encoding="utf-8",
        )

    def _install_selector(self, relative: str, digest: str) -> None:
        run_id = Path(relative).parts[2]
        raw = (self.root / relative).read_bytes()
        meta_raw = (self.root / relative).with_name("meta.json").read_bytes()
        selector = self.root / qualification.SELECTOR_RELATIVE_PATH
        selector.parent.mkdir(parents=True, exist_ok=True)
        selector.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "purpose": "census anchor fixture",
                    "run_id": run_id,
                    "run_artifacts_relative_path": f"eval-data/runs/{run_id}",
                    "relative_path": relative,
                    "review_id": json.loads(meta_raw)["review_id"],
                    "e_final_sha256": digest,
                    "e_final_size_bytes": len(raw),
                    "meta_sha256": hashlib.sha256(meta_raw).hexdigest(),
                    "meta_size_bytes": len(meta_raw),
                    "guardian_source_baseline": "rust-v0.147.0",
                    "guardian_source_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                    "expected_guardian_model": "gpt-5.6-sol",
                    "expected_guardian_effort": "low",
                    "request_shape": "standard",
                }
            ),
            encoding="utf-8",
        )

    def _free_port(self) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _config(self) -> RuntimeConfig:
        return RuntimeConfig(
            self.paths,
            _local_data(
                f"http://127.0.0.1:{self._free_port()}/v1",
                model_path_value="eval-data/models/fixture.gguf",
                model_sha256_value=self.model_sha256,
                server_overrides={"binary": model_backed.CUDA_SERVER_RELATIVE_PATH},
            ),
            "0" * 64,
        )

    def _http(self):
        model = self.model.resolve()
        model_id = "rondo-local-approval"

        def get(url: str, *, timeout: float):
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/props"):
                return {
                    "build_info": model_backed.CUDA_SERVICE_BUILD_INFO,
                    "model_path": os.fspath(model),
                    "default_generation_settings": {"n_ctx": 4096},
                    "total_slots": 1,
                }
            if url.endswith("/models"):
                return {"data": [{"id": model_id}]}
            raise AssertionError(f"unexpected census probe: {url}")

        return get

    def _run(self, config: RuntimeConfig, *, output: Path, counter):
        lease = runtime_bridge.WatchdogLease(token="e" * 48)
        guard = mock.Mock()
        guard.is_held.return_value = True
        with mock.patch(
            "rondo_eval.local_approval.token_census.inspect_runtime",
            side_effect=lambda _config, _settings: RuntimeInspection(
                "runtime_ready",
                Path("/fake/llama-server"),
                "fixture CUDA runtime",
                "b" * 64,
                LLAMA_CPP_CUDA_CAPABILITY,
                model_backed.MODEL_BACKED_NOT_RUN,
            ),
        ):
            return token_census.run_census(
                config,
                output_path=output,
                popen=_FakeServerProcess(),
                watchdog_factory=lambda: runtime_bridge.WatchdogProof(
                    lease=lease, guard=guard
                ),
                gpu_sampler=_FakeGpuSampler(),
                http_get=self._http(),
                count=counter,
            )

    def test_complete_set_is_required_and_deduplicated(self) -> None:
        config = self._config()
        inputs = token_census.collect_evidence_inputs(config, expected_count=3)
        self.assertEqual(len(inputs), 3)
        self.assertEqual(len({item.e_final_sha256 for item in inputs}), 3)

        with self.assertRaises(token_census.CensusError) as extra:
            token_census.collect_evidence_inputs(config, expected_count=2)
        self.assertEqual(extra.exception.code, "evidence_set_size_unexpected")
        self.assertEqual(extra.exception.facts["found"], 3)

        # Same bytes under a different run and review id: still a duplicate.
        original = (self.root / self.bundles[0][0]).read_bytes()
        self._install_bundle(9, body=original)
        with self.assertRaises(token_census.CensusError) as duplicate:
            token_census.collect_evidence_inputs(config, expected_count=4)
        self.assertEqual(duplicate.exception.code, "evidence_duplicate_content")

    def test_evidence_without_a_tracked_run_record_is_refused(self) -> None:
        config = self._config()
        self._write_ledger(self.ledger[:-1])
        with self.assertRaises(token_census.CensusError) as error:
            token_census.collect_evidence_inputs(config, expected_count=3)
        self.assertEqual(error.exception.code, "evidence_run_record_missing")

    def test_fit_boundaries_and_declared_percentiles(self) -> None:
        self.assertEqual(token_census.CENSUS_MAX_OUTPUT_TOKENS, 512)
        self.assertEqual(token_census.fit_results(3584), {"4k": True, "8k": True})
        self.assertEqual(token_census.fit_results(3585), {"4k": False, "8k": True})
        self.assertEqual(token_census.fit_results(7680), {"4k": False, "8k": True})
        self.assertEqual(token_census.fit_results(7681), {"4k": False, "8k": False})

        counts = [100, 200, 300, 400]
        self.assertEqual(token_census.percentile(counts, 50), 200)
        self.assertEqual(token_census.percentile(counts, 90), 400)
        self.assertEqual(token_census.percentile(counts, 100), 400)

        records = [
            {"e_final_sha256": f"{index:064x}", "request_shape": "standard",
             "status": "counted", "input_tokens": tokens,
             "fits": token_census.fit_results(tokens)}
            for index, tokens in enumerate([3584, 3585, 7681])
        ]
        rejected = {
            "e_final_sha256": f"{9:064x}",
            "request_shape": "responses_lite",
            "status": "rejected",
            "rejected_by": {
                "http_status": 400,
                "error_type": "invalid_request_error",
                "message": "item['content'] is not an array",
            },
        }
        summary = token_census.summarize(records + [rejected])
        # Every archived input is reported; statistics cover the counted ones.
        self.assertEqual(summary["evidence_count"], 4)
        self.assertEqual(summary["counted"], 3)
        self.assertEqual(summary["rejected"], 1)
        self.assertEqual(
            summary["rejection_reasons"],
            {"400 invalid_request_error: item['content'] is not an array": 1},
        )
        self.assertEqual(summary["input_tokens"]["min"], 3584)
        self.assertEqual(summary["input_tokens"]["max"], 7681)
        self.assertEqual(summary["context_windows"]["4k"], {
            "context_size": 4096, "fits": 1, "does_not_fit": 2
        })
        self.assertEqual(summary["context_windows"]["8k"], {
            "context_size": 8192, "fits": 2, "does_not_fit": 1
        })
        with self.assertRaises(token_census.CensusError) as empty:
            token_census.summarize([rejected])
        self.assertEqual(empty.exception.code, "no_input_was_counted")

    def test_document_is_stable_and_rejects_colliding_records(self) -> None:
        records = [
            {"e_final_sha256": f"{index:064x}", "request_shape": "responses_lite",
             "status": "counted", "input_tokens": tokens,
             "fits": token_census.fit_results(tokens)}
            for index, tokens in enumerate([9000, 4000, 5313])
        ]
        identity = {"serve_config_sha256": "a" * 64}
        anchor = {"e_final_sha256": records[2]["e_final_sha256"], "input_tokens": 5313}
        first = token_census.build_document(
            identity=identity, anchor=anchor, records=records
        )
        second = token_census.build_document(
            identity=identity, anchor=anchor, records=list(reversed(records))
        )
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))
        without_digest = {key: value for key, value in first.items() if key != "digest"}
        self.assertEqual(first["digest"], token_census._canonical_digest(without_digest))

        with self.assertRaises(token_census.CensusError) as collision:
            token_census.build_document(
                identity=identity, anchor=anchor, records=records + [records[0]]
            )
        self.assertEqual(collision.exception.code, "record_digest_collision")

    def test_anchor_mismatch_stops_before_counting_the_set(self) -> None:
        config = self._config()
        output = self.root / "eval/results/baselines/census.json"
        calls: list[bytes] = []

        def counter(_settings, body: bytes) -> int:
            calls.append(body)
            return token_census.ANCHOR_INPUT_TOKENS - 1

        with mock.patch.object(token_census, "EXPECTED_EVIDENCE_COUNT", 3):
            with self.assertRaises(token_census.CensusError) as error:
                self._run(config, output=output, counter=counter)
        self.assertEqual(error.exception.code, "anchor_token_count_mismatch")
        self.assertEqual(error.exception.facts["observed"], 5312)
        self.assertEqual(len(calls), 1)
        self.assertFalse(output.exists())
        self.assertTrue(all(error.exception.facts["cleanup"].values()))

    def test_census_counts_the_whole_set_and_writes_a_stable_result(self) -> None:
        config = self._config()
        output = self.root / "eval/results/baselines/census.json"
        # The anchor is counted once up front and reused, so the two remaining
        # inputs receive the two remaining values.
        values = [token_census.ANCHOR_INPUT_TOKENS, 4001, 9000]
        bodies: list[bytes] = []

        def counter(_settings, body: bytes) -> int:
            payload = json.loads(body)
            self.assertEqual(payload["max_output_tokens"], 512)
            self.assertNotIn("tools", payload)
            bodies.append(body)
            return values[len(bodies) - 1]

        with mock.patch.object(token_census, "EXPECTED_EVIDENCE_COUNT", 3):
            summary = self._run(config, output=output, counter=counter)
        self.assertEqual(len(bodies), 3)
        self.assertEqual(summary["status"], "complete")
        self.assertEqual(summary["anchor_input_tokens"], token_census.ANCHOR_INPUT_TOKENS)
        self.assertTrue(all(summary["cleanup"].values()))

        document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(document["digest"], summary["digest"])
        self.assertEqual(
            [record["e_final_sha256"] for record in document["records"]],
            sorted(digest for _path, digest in self.bundles),
        )
        self.assertEqual(
            sorted(record["input_tokens"] for record in document["records"]),
            [4001, 5313, 9000],
        )
        for record in document["records"]:
            self.assertEqual(
                set(record),
                {"e_final_sha256", "request_shape", "status", "input_tokens", "fits"},
            )
        self.assertEqual(document["summary"]["context_windows"]["4k"]["fits"], 0)
        self.assertEqual(document["summary"]["context_windows"]["8k"]["fits"], 2)
        self.assertEqual(document["identity"]["generated_tokens"], 0)

    def test_a_refused_input_is_recorded_without_stopping_the_census(self) -> None:
        config = self._config()
        output = self.root / "eval/results/baselines/census.json"
        calls: list[bytes] = []

        def counter(_settings, body: bytes) -> int:
            calls.append(body)
            if len(calls) == 1:
                return token_census.ANCHOR_INPUT_TOKENS
            if len(calls) == 2:
                raise token_census.RequestRejected(
                    {
                        "http_status": 400,
                        "error_type": "invalid_request_error",
                        "message": "item['content'] is not an array",
                    }
                )
            return 4001

        with mock.patch.object(token_census, "EXPECTED_EVIDENCE_COUNT", 3):
            summary = self._run(config, output=output, counter=counter)
        self.assertEqual(summary["summary"]["evidence_count"], 3)
        self.assertEqual(summary["summary"]["counted"], 2)
        self.assertEqual(summary["summary"]["rejected"], 1)

        document = json.loads(output.read_text(encoding="utf-8"))
        statuses = sorted(record["status"] for record in document["records"])
        self.assertEqual(statuses, ["counted", "counted", "rejected"])
        refused = next(r for r in document["records"] if r["status"] == "rejected")
        self.assertNotIn("input_tokens", refused)
        self.assertEqual(refused["rejected_by"]["http_status"], 400)

    def test_a_refused_anchor_stops_the_census(self) -> None:
        config = self._config()
        output = self.root / "eval/results/baselines/census.json"

        def counter(_settings, _body: bytes) -> int:
            raise token_census.RequestRejected({"http_status": 400})

        with mock.patch.object(token_census, "EXPECTED_EVIDENCE_COUNT", 3):
            with self.assertRaises(token_census.CensusError) as error:
                self._run(config, output=output, counter=counter)
        self.assertEqual(error.exception.code, "anchor_request_rejected")
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
