import http.client
import io
import json
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.parse import urlsplit


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.engineering.cloud_budget_proxy import (  # noqa: E402
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    CloudBudgetProxy,
    CloudBudgetProxyError,
    _NoRedirect,
)


class _FakeResponse:
    def __init__(self, body: bytes, *, status: int = 200) -> None:
        self.status = status
        self.code = status
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        self._body = io.BytesIO(body)
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        self.closed = True


class _FakeOpener:
    def __init__(self, *responses: _FakeResponse) -> None:
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def open(self, request, *, timeout: float):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if not self.responses:
            raise AssertionError("unexpected upstream call")
        return self.responses.pop(0)


class _BlockingOpener(_FakeOpener):
    def __init__(self, response: _FakeResponse) -> None:
        super().__init__(response)
        self.started = threading.Event()
        self.release = threading.Event()

    def open(self, request, *, timeout: float):
        self.started.set()
        if not self.release.wait(3):
            raise AssertionError("test did not release upstream open")
        return super().open(request, timeout=timeout)


def _request(
    proxy: CloudBudgetProxy,
    *,
    method: str = "POST",
    path: str = "/chat/completions",
    body: bytes = b'{"model":"deepseek-v4-flash","stream":false}',
    api_key: str | None = None,
    content_length: int | None = None,
) -> tuple[int, bytes]:
    endpoint = urlsplit(proxy.base_url)
    connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=3)
    headers = {
        "Authorization": f"Bearer {api_key or proxy.downstream_api_key}",
        "Content-Type": "application/json",
    }
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    result = response.status, response.read()
    connection.close()
    return result


def _success_body(*, content: str = "provider-response-marker") -> bytes:
    return json.dumps(
        {
            "id": "response-id",
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "total_tokens": 110,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 60,
            },
        },
        separators=(",", ":"),
    ).encode()


class CloudBudgetProxyTest(unittest.TestCase):
    def test_forwards_with_ephemeral_key_and_persists_only_body_free_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "ledger.json"
            upstream_key = "upstream-secret-marker"
            request_marker = "publication-request-marker"
            response_marker = "provider-response-marker"
            upstream_response = _FakeResponse(
                _success_body(content=response_marker)
            )
            opener = _FakeOpener(upstream_response)
            proxy = CloudBudgetProxy(
                upstream_endpoint="https://api.deepseek.com/chat/completions",
                upstream_api_key=upstream_key,
                ledger_path=ledger_path,
                _opener=opener,
            )
            request_body = json.dumps(
                {
                    "model": "deepseek-v4-flash",
                    "stream": False,
                    "messages": [{"role": "user", "content": request_marker}],
                }
            ).encode()

            with proxy:
                self.assertEqual(urlsplit(proxy.base_url).hostname, "127.0.0.1")
                self.assertNotEqual(proxy.downstream_api_key, upstream_key)
                status, body = _request(proxy, body=request_body)

            self.assertEqual((status, body), (200, _success_body()))
            self.assertTrue(upstream_response.closed)
            self.assertEqual(len(opener.requests), 1)
            forwarded = opener.requests[0]
            self.assertEqual(
                forwarded.full_url,
                "https://api.deepseek.com/chat/completions",
            )
            self.assertEqual(forwarded.data, request_body)
            self.assertEqual(
                forwarded.get_header("Authorization"),
                f"Bearer {upstream_key}",
            )
            self.assertEqual(stat.S_IMODE(ledger_path.stat().st_mode), 0o600)
            self.assertEqual(
                proxy.snapshot(),
                {
                    "schema": "rondo-publication-critic-plan097-cloud-budget-v1",
                    "cap_rmb": "12",
                    "conservative_charged_rmb": "0.000137",
                    "remaining_rmb": "11.999863",
                    "attempts": [
                        {
                            "attempt": 1,
                            "state": "usage_priced",
                            "usage": {
                                "prompt_tokens": 100,
                                "completion_tokens": 10,
                                "cache_hit_tokens": 40,
                                "cache_miss_tokens": 60,
                            },
                            "actual_charge_rmb": "0.000137",
                            "conservative_charge_rmb": "0.000137",
                        }
                    ],
                },
            )
            ledger_text = ledger_path.read_text(encoding="utf-8")
            for forbidden in (
                upstream_key,
                proxy.downstream_api_key,
                request_marker,
                response_marker,
                "api.deepseek.com",
            ):
                self.assertNotIn(forbidden, ledger_text)

    def test_missing_and_abnormal_usage_each_charge_one_rmb(self) -> None:
        missing = _FakeResponse(json.dumps({"choices": []}).encode())
        abnormal = _FakeResponse(
            json.dumps(
                {
                    "choices": [],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 1,
                        "prompt_cache_hit_tokens": 9,
                        "prompt_cache_miss_tokens": 9,
                    },
                }
            ).encode()
        )
        opener = _FakeOpener(missing, abnormal)
        with tempfile.TemporaryDirectory() as directory:
            proxy = CloudBudgetProxy(
                upstream_endpoint="https://provider.example/chat/completions",
                upstream_api_key="upstream-key",
                ledger_path=Path(directory) / "ledger.json",
                _opener=opener,
            )
            with proxy:
                self.assertEqual(_request(proxy)[0], 200)
                self.assertEqual(_request(proxy)[0], 200)

            snapshot = proxy.snapshot()
            self.assertEqual(snapshot["conservative_charged_rmb"], "2")
            self.assertEqual(
                snapshot["attempts"],
                [
                    {
                        "attempt": 1,
                        "state": "unknown_usage_charged",
                        "usage": None,
                        "actual_charge_rmb": None,
                        "conservative_charge_rmb": "1",
                    },
                    {
                        "attempt": 2,
                        "state": "unknown_usage_charged",
                        "usage": None,
                        "actual_charge_rmb": None,
                        "conservative_charge_rmb": "1",
                    },
                ],
            )

    def test_persistent_cap_rejects_before_another_upstream_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "ledger.json"
            first_opener = _FakeOpener(
                _FakeResponse(json.dumps({"choices": []}).encode())
            )
            first = CloudBudgetProxy(
                upstream_endpoint="https://provider.example/chat/completions",
                upstream_api_key="upstream-key",
                ledger_path=ledger_path,
                cap_rmb="1",
                _opener=first_opener,
            )
            with first:
                self.assertEqual(_request(first)[0], 200)
                status, body = _request(first)
                self.assertEqual(status, 429)
                self.assertEqual(
                    json.loads(body),
                    {"error": {"code": "budget_cap_exceeded"}},
                )
            self.assertEqual(len(first_opener.requests), 1)

            second_opener = _FakeOpener()
            second = CloudBudgetProxy(
                upstream_endpoint="https://provider.example/chat/completions",
                upstream_api_key="another-in-memory-key",
                ledger_path=ledger_path,
                cap_rmb="1",
                _opener=second_opener,
            )
            with second:
                self.assertEqual(_request(second)[0], 429)
            self.assertEqual(second_opener.requests, [])

    def test_close_linearizes_before_any_new_reservation_or_upstream_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            opener = _BlockingOpener(_FakeResponse(_success_body()))
            proxy = CloudBudgetProxy(
                upstream_endpoint="https://provider.example/chat/completions",
                upstream_api_key="upstream-key",
                ledger_path=Path(directory) / "ledger.json",
                _opener=opener,
            ).start()
            first_result = []
            second_result = []
            first = threading.Thread(target=lambda: first_result.append(_request(proxy)))
            first.start()
            self.assertTrue(opener.started.wait(2))
            closer = threading.Thread(target=proxy.close)
            closer.start()
            self.assertTrue(proxy._closing.wait(2))
            second = threading.Thread(target=lambda: second_result.append(_request(proxy)))
            second.start()
            time.sleep(0.05)
            opener.release.set()
            for thread in (first, second, closer):
                thread.join(3)
                self.assertFalse(thread.is_alive())
            self.assertEqual(first_result[0][0], 200)
            self.assertEqual(second_result[0][0], 503)
            self.assertEqual(len(opener.requests), 1)
            self.assertEqual(len(proxy.snapshot()["attempts"]), 1)

    def test_non_post_wrong_path_bad_auth_and_oversize_never_reach_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            opener = _FakeOpener()
            proxy = CloudBudgetProxy(
                upstream_endpoint="https://provider.example/chat/completions",
                upstream_api_key="upstream-key",
                ledger_path=Path(directory) / "ledger.json",
                _opener=opener,
            )
            with proxy:
                self.assertEqual(_request(proxy, method="GET")[0], 405)
                self.assertEqual(_request(proxy, path="/v1/chat/completions")[0], 404)
                self.assertEqual(_request(proxy, api_key="wrong-key")[0], 401)
                self.assertEqual(
                    _request(
                        proxy,
                        body=b"{}",
                        content_length=MAX_REQUEST_BYTES + 1,
                    )[0],
                    413,
                )
            self.assertEqual(opener.requests, [])
            self.assertEqual(proxy.snapshot()["attempts"], [])

    def test_oversize_upstream_response_is_bounded_and_charged_conservatively(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            opener = _FakeOpener(_FakeResponse(b"x" * (MAX_RESPONSE_BYTES + 1)))
            proxy = CloudBudgetProxy(
                upstream_endpoint="https://provider.example/chat/completions",
                upstream_api_key="upstream-key",
                ledger_path=Path(directory) / "ledger.json",
                _opener=opener,
            )
            with proxy:
                self.assertEqual(_request(proxy)[0], 502)
            self.assertEqual(
                proxy.snapshot()["attempts"][0]["conservative_charge_rmb"], "1"
            )

    def test_requires_explicit_credential_free_https_endpoint_and_disables_redirects(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            for endpoint in (
                "http://provider.example/chat/completions",
                "https://user:secret@provider.example/chat/completions",
                "https://provider.example/another-path",
                "https://provider.example/chat/completions?redirect=1",
            ):
                with self.assertRaises(CloudBudgetProxyError):
                    CloudBudgetProxy(
                        upstream_endpoint=endpoint,
                        upstream_api_key="upstream-key",
                        ledger_path=path,
                    )
            self.assertIsNone(
                _NoRedirect().redirect_request(
                    None,
                    None,
                    302,
                    "Found",
                    {},
                    "https://redirect.example/chat/completions",
                )
            )


if __name__ == "__main__":
    unittest.main()
