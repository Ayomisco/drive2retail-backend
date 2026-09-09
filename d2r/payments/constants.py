"""Payment enums — docs/backend/01-data-model.md §7."""

from __future__ import annotations

from django.db import models


class PaymentProvider(models.TextChoices):
    PAYSTACK = "paystack", "Paystack"
    FLUTTERWAVE = "flutterwave", "Flutterwave"
    BANK_TRANSFER = "bank_transfer", "Bank transfer"
    CASH_ON_DELIVERY = "cash_on_delivery", "Cash on delivery"


class PaymentAttemptStatus(models.TextChoices):
    INITIATED = "initiated", "Initiated"
    PENDING = "pending", "Pending"
    SUCCESSFUL = "successful", "Successful"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"
    ABANDONED = "abandoned", "Abandoned"


class WebhookStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"
    IGNORED = "ignored", "Ignored"


class RefundStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    PROCESSING = "processing", "Processing"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ISSUED = "issued", "Issued"
    PAID = "paid", "Paid"
    VOID = "void", "Void"


# Paystack transacts in kobo; conversion happens only in the gateway adapter.
CURRENCY_MINOR_UNITS = {"NGN": 100, "USD": 100, "GHS": 100, "ZAR": 100, "KES": 100}
