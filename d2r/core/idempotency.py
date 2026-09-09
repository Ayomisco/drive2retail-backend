"""Idempotency for unsafe writes — docs/backend/02-api.md §8.

A client generates one key per user intent and reuses it across retries, so a
flaky connection during checkout can never create two orders.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.response import Response

from .exceptions import APIError, ErrorCode


class DuplicateRequestError(APIError):
    status_code = 409
    code = ErrorCode.DUPLICATE_REQUEST
    message = "This request is already being processed. Please wait and try again."


def hash_request(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def idempotent(endpoint: str):
    """Decorator for DRF view methods that must not double-execute.

    Usage:
        @idempotent("checkout.initiate")
        def post(self, request): ...
    """

    def decorator(view_method):
        def wrapper(self, request, *args, **kwargs):
            from d2r.ops.models import IdempotencyKey

            key = request.headers.get("Idempotency-Key")
            if not key:
                raise APIError(
                    "This endpoint requires an Idempotency-Key header.",
                    code=ErrorCode.VALIDATION_ERROR,
                )

            request_hash = hash_request(request.data)

            try:
                with transaction.atomic():
                    record = IdempotencyKey.objects.create(
                        key=key,
                        endpoint=endpoint,
                        request_hash=request_hash,
                        user=request.user if request.user.is_authenticated else None,
                        status=IdempotencyKey.Status.IN_PROGRESS,
                    )
            except IntegrityError:
                existing = IdempotencyKey.objects.get(key=key, endpoint=endpoint)
                if existing.request_hash != request_hash:
                    raise APIError(
                        "This Idempotency-Key was already used with a different request body.",
                        code=ErrorCode.VALIDATION_ERROR,
                        status_code=422,
                    ) from None
                if existing.status == IdempotencyKey.Status.IN_PROGRESS:
                    raise DuplicateRequestError from None
                # Completed: replay the stored response verbatim.
                return Response(existing.response_body, status=existing.response_status)

            response = view_method(self, request, *args, **kwargs)

            record.response_status = response.status_code
            record.response_body = response.data
            record.status = IdempotencyKey.Status.COMPLETED
            record.completed_at = timezone.now()
            record.save(
                update_fields=["response_status", "response_body", "status", "completed_at"]
            )
            return response

        return wrapper

    return decorator
