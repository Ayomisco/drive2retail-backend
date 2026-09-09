"""Delivery models — docs/backend/01-data-model.md §8."""

from __future__ import annotations

from django.db import models

from d2r.core.models import TimeStampedModel


class DeliveryZone(TimeStampedModel):
    """Seeded from the coverage axes in the D2R pitch deck."""

    code = models.CharField(max_length=20, unique=True, help_text='e.g. "LAG-IKD"')
    name = models.CharField(max_length=150, help_text='e.g. "Ikorodu Axis"')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    supports_restricted = models.BooleanField(
        default=False, help_text="Alcohol and other restricted lines may be delivered here"
    )
    cod_allowed = models.BooleanField(default=False, help_text="Cash on delivery permitted")
    sort_order = models.IntegerField(default=0)

    class Meta:
        db_table = "delivery_zone"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class DeliveryZoneArea(models.Model):
    """Matching rules. A zone is a set of areas, not a polygon — no GIS at launch."""

    class MatchType(models.TextChoices):
        CITY = "city", "City"
        STATE = "state", "State"
        POSTAL = "postal", "Postal code"
        LGA = "lga", "Local government area"

    zone = models.ForeignKey(DeliveryZone, on_delete=models.CASCADE, related_name="areas")
    match_type = models.CharField(max_length=16, choices=MatchType.choices)
    match_value = models.CharField(max_length=120)

    class Meta:
        db_table = "delivery_zone_area"
        constraints = [
            models.UniqueConstraint(fields=["zone", "match_type", "match_value"], name="uq_dza")
        ]

    def __str__(self) -> str:
        return f"{self.match_type}={self.match_value} → {self.zone.code}"


class DeliveryRate(TimeStampedModel):
    class RateType(models.TextChoices):
        FLAT = "flat", "Flat fee"
        WEIGHT = "weight", "By weight"
        ORDER_VALUE = "order_value", "By order value"
        FREE = "free", "Free"

    zone = models.ForeignKey(DeliveryZone, on_delete=models.CASCADE, related_name="rates")
    name = models.CharField(max_length=100, default="Standard")
    rate_type = models.CharField(max_length=16, choices=RateType.choices, default=RateType.FLAT)

    base_fee = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    per_kg_fee = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    min_order_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    max_order_value = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    free_above_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    estimated_days_min = models.SmallIntegerField(null=True, blank=True)
    estimated_days_max = models.SmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    priority = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "delivery_rate"
        ordering = ["zone", "priority"]

    def __str__(self) -> str:
        return f"{self.zone.code} — {self.name}"
