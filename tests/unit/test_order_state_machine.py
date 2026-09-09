"""The order state machine — docs/backend/01-data-model.md §6."""

import pytest

from d2r.orders.constants import CANCELLABLE_STATUSES, OrderStatus, can_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderStatus.PENDING_PAYMENT, OrderStatus.PAID),
        (OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_FAILED),
        (OrderStatus.PAYMENT_FAILED, OrderStatus.PAID),
        (OrderStatus.PAID, OrderStatus.PROCESSING),
        (OrderStatus.PROCESSING, OrderStatus.DISPATCHED),
        (OrderStatus.DISPATCHED, OrderStatus.DELIVERED),
        (OrderStatus.DELIVERED, OrderStatus.RETURNED),
    ],
)
def test_legal_transitions(current, target):
    assert can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (OrderStatus.PENDING_PAYMENT, OrderStatus.DISPATCHED),  # cannot skip payment
        (OrderStatus.DELIVERED, OrderStatus.PAID),  # cannot go backwards
        (OrderStatus.CANCELLED, OrderStatus.PAID),  # terminal
        (OrderStatus.EXPIRED, OrderStatus.PROCESSING),  # terminal
        (OrderStatus.PAID, OrderStatus.DISPATCHED),  # must be picked first
    ],
)
def test_illegal_transitions_rejected(current, target):
    assert not can_transition(current, target)


def test_cancellation_only_before_dispatch():
    assert OrderStatus.DISPATCHED not in CANCELLABLE_STATUSES
    assert OrderStatus.DELIVERED not in CANCELLABLE_STATUSES
    assert OrderStatus.PAID in CANCELLABLE_STATUSES
