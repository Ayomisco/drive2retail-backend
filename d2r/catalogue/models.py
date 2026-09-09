"""Catalogue models.

Categories, brands, vendors, products, variants, images, attributes.

Specified in docs/backend/01-data-model.md §2; executable DDL in docs/backend/schema.sql.
"""

from django.db import models  # noqa: F401

from d2r.core.models import BaseModel, TimeStampedModel  # noqa: F401
