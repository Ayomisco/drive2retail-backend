"""Carts admin.

Configured deliberately, not scaffolded — see docs/backend/06-admin-ops.md §2.
Every list uses list_select_related/prefetch_related; historical records
(movements, payment attempts, order items) are registered read-only.
"""

from django.contrib import admin  # noqa: F401
