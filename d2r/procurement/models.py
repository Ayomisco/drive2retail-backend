"""Procurement models.

Purchase orders, goods receipt, supplier invoices, three-way match.

Specified in docs/backend/09-procurement-batches.md; executable DDL in docs/backend/schema.sql.
"""

from django.db import models  # noqa: F401

from d2r.core.models import BaseModel, TimeStampedModel  # noqa: F401
