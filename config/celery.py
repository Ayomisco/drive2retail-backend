"""Celery application.

Queue routing lives in settings (CELERY_TASK_ROUTES) so payment work never
queues behind a bulk import. Beat schedules are declared here.
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

app = Celery("d2r")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Release stock held by carts that never paid — docs/backend/03-flows.md §6
    "release-expired-reservations": {
        "task": "d2r.inventory.tasks.release_expired_reservations",
        "schedule": 60.0,
        "options": {"queue": "critical"},
    },
    # Actively verify payments whose webhook never arrived
    "sweep-stale-payments": {
        "task": "d2r.payments.tasks.sweep_stale_payments",
        "schedule": 300.0,
        "options": {"queue": "critical"},
    },
    # Retry webhook events that failed processing
    "retry-failed-webhooks": {
        "task": "d2r.payments.tasks.retry_failed_webhooks",
        "schedule": 300.0,
        "options": {"queue": "critical"},
    },
    # Expire batches and raise short-shelf-life alerts — 09-procurement-batches.md
    "expire-stock-batches": {
        "task": "d2r.inventory.tasks.expire_batches",
        "schedule": crontab(hour=2, minute=0),
    },
    "low-stock-alerts": {
        "task": "d2r.inventory.tasks.low_stock_alerts",
        "schedule": crontab(hour=7, minute=0),
    },
    "refresh-category-counts": {
        "task": "d2r.catalogue.tasks.refresh_category_counts",
        "schedule": 900.0,
    },
    "purge-expired-tokens": {
        "task": "d2r.accounts.tasks.purge_expired_tokens",
        "schedule": crontab(hour=3, minute=30),
    },
    "abandon-stale-carts": {
        "task": "d2r.carts.tasks.abandon_stale_carts",
        "schedule": crontab(hour=4, minute=0),
    },
}
