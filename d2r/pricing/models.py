"""Pricing & tax models.

Tax classes, price lists with group and volume breaks, promotions.

Specified in docs/backend/01-data-model.md §3; executable DDL in docs/backend/schema.sql.
"""

from django.db import models  # noqa: F401

from d2r.core.models import BaseModel, TimeStampedModel  # noqa: F401
