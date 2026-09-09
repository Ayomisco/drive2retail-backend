"""Orders background tasks.

Dispatched with transaction.on_commit so a failed side effect never rolls
back a committed order. Schedules are declared in config/celery.py.
"""

from celery import shared_task  # noqa: F401
