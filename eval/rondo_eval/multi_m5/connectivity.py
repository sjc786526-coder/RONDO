"""Zero-cost provider reachability gate for formal M-5 entries.

The check deliberately sends no credentials and no inference payload.  Its only
job is to prove that the *current process boundary* can reach the frozen base
URL before a receipt, ledger, run id, capture, or secret is created.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


class ProviderConnectivityError(ValueError):
    """The frozen provider cannot be reached without creating formal state."""


UrlOpener = Callable[..., Any]


def require_provider_connectivity(
    base_url: str,
    *,
    timeout_seconds: float = 15.0,
    opener: UrlOpener | None = None,
) -> dict[str, Any]:
    """Accept any HTTP response, but reject DNS/socket/TLS/sandbox failures.

    A 401, 404, 405, or 5xx still proves that the configured HTTP service is
    reachable.  No status proves provider health or model availability; the
    paid request remains the only such observation.  Redirects and environment
    proxies are disabled so this request tests only the frozen endpoint.
    """

    if not isinstance(base_url, str) or not base_url.startswith("https://"):
        raise ProviderConnectivityError("provider connectivity URL is not frozen HTTPS")
    if timeout_seconds <= 0:
        raise ProviderConnectivityError("provider connectivity timeout is invalid")
    request = Request(
        base_url.rstrip("/") + "/",
        headers={
            "Accept": "application/json",
            "User-Agent": "rondo-m5-zero-cost-connectivity/1",
        },
        method="GET",
    )
    response = None
    try:
        response = (opener or _open_direct)(request, timeout=timeout_seconds)
        status = getattr(response, "status", None)
    except HTTPError as exc:
        # HTTPError means the server was reached and returned a complete HTTP
        # response.  That is sufficient for this narrow transport check.
        status = exc.code
        exc.close()
    except (URLError, TimeoutError, OSError) as exc:
        raise ProviderConnectivityError(
            "provider connectivity preflight failed before formal state"
        ) from exc
    finally:
        if response is not None:
            response.close()
    if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
        raise ProviderConnectivityError(
            "provider connectivity preflight returned no HTTP status"
        )
    return {
        "ok": True,
        "authenticated": False,
        "method": "GET",
        "http_status": status,
    }


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        return None


def _open_direct(request: Request, *, timeout: float) -> Any:
    # Do not inherit host proxy variables or follow the provider to a second
    # address.  The exact frozen endpoint is the boundary being checked.
    return build_opener(ProxyHandler({}), _NoRedirect()).open(
        request,
        timeout=timeout,
    )
