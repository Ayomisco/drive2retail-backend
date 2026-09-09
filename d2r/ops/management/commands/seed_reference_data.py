"""Seed the reference data every environment needs.

Idempotent — safe to run repeatedly. Business data (products, customers) is
never seeded here; that arrives by import.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from d2r.accounts.constants import StaffRoleCode
from d2r.accounts.models import CustomerGroup, StaffRole
from d2r.delivery.models import DeliveryZone, DeliveryZoneArea
from d2r.ops.models import Setting

ROLES = [
    (StaffRoleCode.ADMIN, "Administrator", "Full access"),
    (StaffRoleCode.CATALOGUE, "Catalogue", "Products, prices, promotions"),
    (StaffRoleCode.INVENTORY, "Inventory", "Stock and adjustments"),
    (StaffRoleCode.OPS, "Operations", "Orders and fulfilment"),
    (StaffRoleCode.FINANCE, "Finance", "Payments, refunds, reconciliation"),
    (StaffRoleCode.SUPPORT, "Customer Support", "Read-only customer and order access"),
    (StaffRoleCode.SALES, "Sales", "Customer accounts and assisted ordering"),
]

GROUPS = [
    ("standard", "Standard", 0, 0),
    ("gold", "Gold", "2.50", 10),
    ("key_account", "Key Account", "5.00", 20),
]

# Coverage axes from the D2R pitch deck.
ZONES = [
    ("LAG-KMS", "Kosofe / Mushin / Shomolu", 1, ["Kosofe", "Mushin", "Shomolu"]),
    ("LAG-AAA", "Amuwo Odofin / Ajeromi / Apapa", 2, ["Amuwo Odofin", "Ajeromi", "Apapa"]),
    (
        "LAG-EIL",
        "Eti Osa / Ibeju Lekki / Lagos Island",
        3,
        ["Eti Osa", "Ibeju Lekki", "Lagos Island"],
    ),
    ("LAG-SYE", "Surulere / Yaba / Ebute Metta", 4, ["Surulere", "Yaba", "Ebute Metta"]),
    ("LAG-IKD", "Ikorodu Axis", 5, ["Ikorodu"]),
]

SETTINGS = [
    (
        "accounts.require_approval",
        True,
        "boolean",
        "New accounts need staff approval before ordering",
        True,
    ),
    (
        "accounts.hide_prices_until_approved",
        True,
        "boolean",
        "Hide prices from unapproved accounts",
        True,
    ),
    (
        "checkout.reservation_ttl_minutes",
        20,
        "number",
        "How long stock is held during payment",
        False,
    ),
    ("checkout.min_order_value", 0, "number", "Minimum order value in NGN", True),
    ("payment.active_gateway", "paystack", "string", "Primary payment provider", False),
    ("delivery.free_above", None, "number", "Free delivery threshold in NGN", True),
    ("tax.prices_include_tax", False, "boolean", "Whether displayed prices include VAT", True),
    (
        "restricted.require_acknowledgement",
        True,
        "boolean",
        "Require acknowledgement for restricted items",
        True,
    ),
]


class Command(BaseCommand):
    help = "Seed roles, customer groups, delivery zones and default settings"

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        for code, name, description in ROLES:
            StaffRole.objects.update_or_create(
                code=code, defaults={"name": name, "description": description, "is_system": True}
            )
        self.stdout.write(self.style.SUCCESS(f"  staff roles      {len(ROLES)}"))

        for code, name, discount, priority in GROUPS:
            CustomerGroup.objects.update_or_create(
                code=code,
                defaults={"name": name, "discount_percent": discount, "priority": priority},
            )
        self.stdout.write(self.style.SUCCESS(f"  customer groups  {len(GROUPS)}"))

        for code, name, order, cities in ZONES:
            zone, _ = DeliveryZone.objects.update_or_create(
                code=code, defaults={"name": name, "sort_order": order, "is_active": True}
            )
            for city in cities:
                DeliveryZoneArea.objects.update_or_create(
                    zone=zone, match_type=DeliveryZoneArea.MatchType.CITY, match_value=city
                )
        self.stdout.write(self.style.SUCCESS(f"  delivery zones   {len(ZONES)}"))

        for key, value, value_type, description, is_public in SETTINGS:
            Setting.objects.update_or_create(
                key=key,
                defaults={
                    "value": value,
                    "value_type": value_type,
                    "description": description,
                    "is_public": is_public,
                },
            )
        self.stdout.write(self.style.SUCCESS(f"  settings         {len(SETTINGS)}"))
        self.stdout.write(self.style.SUCCESS("Reference data seeded."))
