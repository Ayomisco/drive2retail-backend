"""Structured logging with request correlation and PII redaction."""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Redacted at the formatter, not at each call site, so new PII cannot leak by
# a developer forgetting — docs/backend/04-security.md §7.2
REDACTED_KEYS = frozenset(
    {
        "password",
        "token",
        "access",
        "refresh",
        "authorization",
        "secret",
        "card_number",
        "cvv",
        "security_code",
        "signature",
        "api_key",
        "mfa_secret",
        "authorization_code",
    }
)


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def redact(data: Any) -> Any:
    if isinstance(data, dict):
        return {
            k: ("[redacted]" if k.lower() in REDACTED_KEYS else redact(v)) for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data


class RequestIDFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if extra := getattr(record, "extra", None):
            payload["extra"] = redact(extra)
        return json.dumps(payload, default=str)
