"""Carts models.

Carts and cart items with MOQ and increment validation.

Specified in docs/backend/01-data-model.md §5; executable DDL in docs/backend/schema.sql.
"""

from django.db import models  # noqa: F401

from d2r.core.models import BaseModel, TimeStampedModel  # noqa: F401
