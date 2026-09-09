"""Request correlation and audit context."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from django.http import HttpRequest, HttpResponse

from .logging import set_request_id

# A mutable default would be shared across every context, so default to None.
_audit_context: ContextVar[dict[str, Any] | None] = ContextVar("audit_context", default=None)


def get_audit_context() -> dict[str, Any]:
    return _audit_context.get() or {}


class RequestIDMiddleware:
    """Accepts or mints X-Request-ID and echoes it, so a client error report
    can be traced through the API into Celery."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.request_id = request_id  # type: ignore[attr-defined]
        set_request_id(request_id)
        response = self.get_response(request)
        response["X-Request-ID"] = request_id
        return response


class AuditContextMiddleware:
    """Captures actor and origin once, so audit_log rows do not need the request
    passed down through every service call."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = getattr(request, "user", None)
        _audit_context.set(
            {
                "actor_id": user.pk if user and user.is_authenticated else None,
                "ip_address": self._client_ip(request),
                "user_agent": request.headers.get("User-Agent", "")[:300],
                "request_id": getattr(request, "request_id", None),
            }
        )
        return self.get_response(request)

    @staticmethod
    def _client_ip(request: HttpRequest) -> str | None:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR")
