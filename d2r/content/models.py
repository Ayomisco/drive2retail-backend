"""Content models.

Reviews, wishlists, notifications, banners.

Specified in docs/backend/01-data-model.md §9; executable DDL in docs/backend/schema.sql.
"""

from django.db import models  # noqa: F401

from d2r.core.models import BaseModel, TimeStampedModel  # noqa: F401
