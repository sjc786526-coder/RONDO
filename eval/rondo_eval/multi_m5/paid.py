"""Fail-closed authorization for M-5 paid API and Docker.

The paid functions exist and are wired. They still refuse to load secrets or
open an upstream unless the frozen phrase is supplied after user approval.
"""

from __future__ import annotations

from dataclasses import dataclass

PAID_API_PHRASE = "I authorize Plan 044 M-5 phase B paid API"
PAID_DOCKER_PHRASE = "I authorize Plan 044 M-5 phase B Docker"


class PaidAuthError(RuntimeError):
    """Paid M-5 execution was requested without the frozen authorization phrase."""


@dataclass(frozen=True)
class PaidAuthorization:
    real_api: bool
    docker: bool

    def require_api(self) -> None:
        if not self.real_api:
            raise PaidAuthError("paid gate 1 is not authorized")

    def require_api_and_docker(self) -> None:
        if not self.real_api or not self.docker:
            raise PaidAuthError("paid gate 2 requires API and Docker authorization")


def authorization_from_phrases(
    *,
    api_phrase: str | None,
    docker_phrase: str | None = None,
) -> PaidAuthorization:
    """Construct authorization only from the exact frozen phrases. No secrets."""

    if api_phrase != PAID_API_PHRASE:
        raise PaidAuthError("paid M-5 API is not authorized")
    docker = docker_phrase == PAID_DOCKER_PHRASE
    if docker_phrase is not None and not docker:
        raise PaidAuthError("paid M-5 Docker is not authorized")
    return PaidAuthorization(real_api=True, docker=docker)
