"""Operations models — docs/backend/01-data-model.md §11.

Audit log, import jobs, idempotency keys and runtime settings.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

from d2r.core.models import BaseModel, TimeStampedModel


class AuditLog(models.Model):
    """Append-only. No update or delete grant on this table in production."""

    class ActorType(models.TextChoices):
        STAFF = "staff", "Staff"
        CUSTOMER = "customer", "Customer"
        SYSTEM = "system", "System"
        WEBHOOK = "webhook", "Webhook"

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_entries",
    )
    actor_type = models.CharField(
        max_length=16, choices=ActorType.choices, default=ActorType.SYSTEM
    )
    action = models.CharField(max_length=60, db_index=True, help_text='e.g. "order.status_changed"')
    object_type = models.CharField(max_length=60)
    object_id = models.BigIntegerField()
    object_repr = models.CharField(max_length=200, blank=True, help_text="Human label at the time")
    changes = models.JSONField(
        null=True, blank=True, help_text='{"status": ["paid", "processing"]}'
    )
    reason = models.CharField(max_length=300, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    request_id = models.UUIDField(null=True, blank=True, help_text="Ties to application logs")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_log"
        indexes = [
            models.Index(
                fields=["object_type", "object_id", "-created_at"], name="idx_audit_object"
            ),
            models.Index(fields=["actor", "-created_at"], name="idx_audit_actor"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.object_type}#{self.object_id}"


class ImportJob(BaseModel):
    """Two-phase import — validate and report, then apply on confirmation.

    A half-applied 5,000-row price file is unrecoverable without a restore.
    """

    class JobType(models.TextChoices):
        PRODUCTS = "products", "Products"
        PRICES = "prices", "Prices"
        INVENTORY = "inventory", "Inventory"
        CUSTOMERS = "customers", "Customers"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        VALIDATING = "validating", "Validating"
        READY = "ready", "Ready to apply"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    job_type = models.CharField(max_length=24, choices=JobType.choices)
    file_url = models.CharField(max_length=500)
    file_name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    total_rows = models.IntegerField(default=0)
    processed_rows = models.IntegerField(default=0)
    success_rows = models.IntegerField(default=0)
    error_rows = models.IntegerField(default=0)
    errors = models.JSONField(null=True, blank=True, help_text="Row-level errors, downloadable")

    dry_run = models.BooleanField(default=True, help_text="Validate without writing")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="import_jobs",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "import_job"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.job_type} — {self.file_name}"


class IdempotencyKey(TimeStampedModel):
    """Protects client retries on unsafe writes — docs/backend/02-api.md §8."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In progress"
        COMPLETED = "completed", "Completed"

    key = models.CharField(max_length=120)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="idempotency_keys",
    )
    endpoint = models.CharField(max_length=120)
    request_hash = models.CharField(max_length=64)
    response_status = models.SmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    completed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "idempotency_key"
        constraints = [
            # The whole mechanism: insert first, execute second.
            models.UniqueConstraint(fields=["key", "endpoint"], name="uq_idem"),
        ]

    def __str__(self) -> str:
        return f"{self.endpoint}:{self.key}"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            from datetime import timedelta

            from django.utils import timezone

            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)


class Setting(TimeStampedModel):
    """Runtime configuration so staff change behaviour without a deploy.

    Several of these are the PRD §17 open questions — making them settings means
    launch is not blocked on a final answer.
    """

    key = models.CharField(max_length=80, unique=True)
    value = models.JSONField()
    value_type = models.CharField(max_length=16, default="string")
    description = models.TextField(blank=True)
    is_public = models.BooleanField(default=False, help_text="Exposed to the storefront")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="setting_changes",
    )

    class Meta:
        db_table = "setting"
        ordering = ["key"]

    def __str__(self) -> str:
        return self.key
