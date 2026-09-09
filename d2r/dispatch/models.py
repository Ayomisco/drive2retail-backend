"""Dispatch & fleet models.

Drivers, vehicles, routes, trips, proof of delivery, cash reconciliation.

Specified in docs/backend/08-dispatch-delivery.md; executable DDL in docs/backend/schema.sql.
"""

from django.db import models  # noqa: F401

from d2r.core.models import BaseModel, TimeStampedModel  # noqa: F401
