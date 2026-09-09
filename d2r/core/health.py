"""Health endpoint — docs/backend/04-security.md §8.

Checks database, cache and Celery broker. Returns 503 when any is down so the
load balancer stops routing rather than serving errors.
"""

from __future__ import annotations

from typing import Any

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from rest_framework import status


def _check_database() -> tuple[bool, str]:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)[:200]


def _check_cache() -> tuple[bool, str]:
    try:
        cache.set("health:ping", "1", timeout=5)
        return (True, "ok") if cache.get("health:ping") == "1" else (False, "readback failed")
    except Exception as exc:
        return False, str(exc)[:200]


def _check_broker() -> tuple[bool, str]:
    try:
        from config.celery import app

        conn = app.connection()
        conn.ensure_connection(max_retries=1, timeout=2)
        conn.release()
        return True, "ok"
    except Exception as exc:
        return False, str(exc)[:200]


def health(request) -> JsonResponse:
    """Full dependency check. Used by the load balancer and uptime probe."""
    checks: dict[str, Any] = {}
    for name, fn in (
        ("database", _check_database),
        ("cache", _check_cache),
        ("broker", _check_broker),
    ):
        ok, detail = fn()
        checks[name] = {"ok": ok, "detail": detail}

    healthy = all(c["ok"] for c in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )


def liveness(request) -> JsonResponse:
    """Process is up. Deliberately checks nothing external — a database blip
    must not cause the orchestrator to kill healthy application pods."""
    return JsonResponse({"status": "ok"})
