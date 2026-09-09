"""Order enums and the state machine — docs/backend/01-data-model.md §6."""

from __future__ import annotations

from django.db import models


class OrderStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", "Pending payment"
    PAYMENT_FAILED = "payment_failed", "Payment failed"
    PAID = "paid", "Paid"
    PROCESSING = "processing", "Processing"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"
    RETURNED = "returned", "Returned"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    INITIATED = "initiated", "Initiated"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially refunded"


class FulfilmentStatus(models.TextChoices):
    UNFULFILLED = "unfulfilled", "Unfulfilled"
    PROCESSING = "processing", "Processing"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    RETURNED = "returned", "Returned"


class OrderSource(models.TextChoices):
    WEB = "web", "Storefront"
    ADMIN = "admin", "Staff"
    REP = "rep", "Sales rep"
    API = "api", "API"


# The only legal transitions. Anything else raises and returns 409 —
# docs/backend/01-data-model.md §6, docs/backend/03-flows.md.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    OrderStatus.PENDING_PAYMENT: {
        OrderStatus.PAID,
        OrderStatus.PAYMENT_FAILED,
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.PAYMENT_FAILED: {
        OrderStatus.PAID,  # a retry succeeded
        OrderStatus.CANCELLED,
        OrderStatus.EXPIRED,
    },
    OrderStatus.PAID: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.DISPATCHED, OrderStatus.CANCELLED},
    OrderStatus.DISPATCHED: {OrderStatus.DELIVERED, OrderStatus.RETURNED},
    OrderStatus.DELIVERED: {OrderStatus.RETURNED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.EXPIRED: set(),
    OrderStatus.RETURNED: set(),
}

# Cancellation is only offered before anything has left the warehouse.
CANCELLABLE_STATUSES = frozenset(
    {
        OrderStatus.PENDING_PAYMENT,
        OrderStatus.PAYMENT_FAILED,
        OrderStatus.PAID,
        OrderStatus.PROCESSING,
    }
)

# How the storefront labels each state — the UI vocabulary differs from the DB.
UI_STATUS_LABELS: dict[str, str] = {
    OrderStatus.PENDING_PAYMENT: "Pending Payment",
    OrderStatus.PAYMENT_FAILED: "Pending Payment",
    OrderStatus.PAID: "Processing",
    OrderStatus.PROCESSING: "Processing",
    OrderStatus.DISPATCHED: "Delivering",
    OrderStatus.DELIVERED: "Completed",
    OrderStatus.CANCELLED: "Cancelled",
    OrderStatus.EXPIRED: "Cancelled",
    OrderStatus.RETURNED: "Returned",
}


def can_transition(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())
