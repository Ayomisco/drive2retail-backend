"""One error shape for the whole API — docs/backend/02-api.md §1.2."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .logging import get_request_id


class ErrorCode:
    """Closed set, exported in the OpenAPI schema so clients can switch on it."""

    INVALID_CREDENTIALS = "invalid_credentials"
    ACCOUNT_PENDING_APPROVAL = "account_pending_approval"
    ACCOUNT_SUSPENDED = "account_suspended"
    BELOW_MOQ = "below_moq"
    INVALID_ORDER_INCREMENT = "invalid_order_increment"
    INSUFFICIENT_STOCK = "insufficient_stock"
    PRICE_CHANGED = "price_changed"
    CART_EXPIRED = "cart_expired"
    UNSUPPORTED_DELIVERY_AREA = "unsupported_delivery_area"
    RESTRICTED_NOT_PERMITTED = "restricted_not_permitted"
    RESTRICTED_ACK_REQUIRED = "restricted_ack_required"
    PROMOTION_INVALID = "promotion_invalid"
    PAYMENT_VERIFICATION_FAILED = "payment_verification_failed"
    DUPLICATE_REQUEST = "duplicate_request"
    INVALID_STATE_TRANSITION = "invalid_state_transition"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    PERMISSION_DENIED = "permission_denied"
    THROTTLED = "throttled"
    SERVER_ERROR = "server_error"


class APIError(Exception):
    """Base for business-rule failures. `message` is safe to show a customer."""

    status_code = status.HTTP_400_BAD_REQUEST
    code = ErrorCode.VALIDATION_ERROR
    message = "The request could not be completed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        detail: list[dict[str, Any]] | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.detail = detail or []
        self.status_code = status_code or self.status_code
        super().__init__(self.message)


class BusinessRuleError(APIError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class StateConflictError(APIError):
    status_code = status.HTTP_409_CONFLICT
    code = ErrorCode.INVALID_STATE_TRANSITION


class InsufficientStockError(StateConflictError):
    code = ErrorCode.INSUFFICIENT_STOCK
    message = "There is not enough stock for one or more items in your cart."


class PriceChangedError(StateConflictError):
    code = ErrorCode.PRICE_CHANGED
    message = "Prices changed while you were checking out. Please review your cart."


class CartExpiredError(APIError):
    status_code = status.HTTP_410_GONE
    code = ErrorCode.CART_EXPIRED
    message = "Your cart has expired. Please start again."


class AccountNotApprovedError(APIError):
    status_code = status.HTTP_403_FORBIDDEN
    code = ErrorCode.ACCOUNT_PENDING_APPROVAL
    message = "Your account is awaiting approval for wholesale purchasing."


def _envelope(code: str, message: str, detail: list[Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "detail": detail or [],
            "request_id": get_request_id(),
        }
    }


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Normalise every failure into the documented envelope."""
    if isinstance(exc, APIError):
        return Response(_envelope(exc.code, exc.message, exc.detail), status=exc.status_code)

    if isinstance(exc, DjangoValidationError):
        return Response(
            _envelope(ErrorCode.VALIDATION_ERROR, "Validation failed.", exc.messages),
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, IntegrityError):
        # A database constraint caught what application logic missed. This is the
        # oversell / double-spend guard firing; never leak the constraint name.
        return Response(
            _envelope(
                ErrorCode.INVALID_STATE_TRANSITION, "The request conflicts with current data."
            ),
            status=status.HTTP_409_CONFLICT,
        )

    response = drf_exception_handler(exc, context)
    if response is None:
        return None

    code_map = {
        401: ErrorCode.INVALID_CREDENTIALS,
        403: ErrorCode.PERMISSION_DENIED,
        404: ErrorCode.NOT_FOUND,
        429: ErrorCode.THROTTLED,
    }
    code = code_map.get(response.status_code, ErrorCode.VALIDATION_ERROR)

    data = response.data
    if isinstance(data, dict) and "detail" in data:
        message, detail = str(data["detail"]), []
    elif isinstance(data, dict):
        message = "Validation failed."
        detail = [
            {"field": f, "code": ErrorCode.VALIDATION_ERROR, "message": " ".join(map(str, m))}
            for f, m in data.items()
        ]
    else:
        message, detail = "The request could not be completed.", []

    response.data = _envelope(code, message, detail)
    return response
