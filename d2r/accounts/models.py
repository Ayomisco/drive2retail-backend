"""Identity and access — docs/backend/01-data-model.md §1."""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from d2r.core.models import ArchivableModel, BaseModel, TimeStampedModel

from .constants import (
    AccountStatus,
    AddressType,
    BusinessType,
    MemberRole,
    StaffRoleCode,
    TokenPurpose,
    UserType,
)
from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin, BaseModel):
    # Normalised to lowercase by UserManager and clean(); Django 5.2 removed
    # CIEmailField, and a non-deterministic collation would rule out index
    # lookups on this column.
    email = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=32, blank=True)

    user_type = models.CharField(
        max_length=16, choices=UserType.choices, default=UserType.CUSTOMER, db_index=True
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False, help_text="Django admin access")

    is_email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    failed_login_count = models.SmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    # Mandatory for staff — docs/backend/04-security.md §1.4
    mfa_secret = models.CharField(max_length=64, blank=True)
    mfa_enabled = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]

    class Meta:
        db_table = "user"
        indexes = [models.Index(fields=["user_type", "is_active"], name="idx_user_type_active")]

    def __str__(self) -> str:
        return self.email

    def clean(self) -> None:
        super().clean()
        if self.email:
            self.email = self.email.strip().lower()

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def is_staff_user(self) -> bool:
        return self.user_type == UserType.STAFF

    @property
    def is_locked(self) -> bool:
        return bool(self.locked_until and self.locked_until > timezone.now())

    def role_codes(self) -> set[str]:
        return set(self.staff_assignments.values_list("role__code", flat=True))

    def has_any_role(self, roles: list[str] | tuple[str, ...]) -> bool:
        codes = self.role_codes()
        return StaffRoleCode.ADMIN in codes or bool(codes & set(roles))


class CustomerGroup(TimeStampedModel):
    """Tier pricing — Phase 2, modelled now so pricing needs no migration."""

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=100)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    priority = models.SmallIntegerField(default=0)

    class Meta:
        db_table = "customer_group"
        ordering = ["-priority"]

    def __str__(self) -> str:
        return self.name


class BusinessAccount(BaseModel):
    """The wholesale customer. This is the entity that orders, not the user."""

    account_number = models.CharField(max_length=20, unique=True, editable=False)
    business_name = models.CharField(max_length=200, db_index=True)
    business_type = models.CharField(max_length=32, choices=BusinessType.choices)
    registration_number = models.CharField(max_length=64, blank=True, help_text="CAC number")
    tax_id = models.CharField(max_length=64, blank=True, help_text="TIN")

    primary_contact_name = models.CharField(max_length=150)
    primary_email = models.EmailField()
    primary_phone = models.CharField(max_length=32)

    status = models.CharField(
        max_length=16, choices=AccountStatus.choices, default=AccountStatus.PENDING, db_index=True
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="approved_accounts"
    )
    rejection_reason = models.TextField(blank=True)

    can_view_prices = models.BooleanField(default=False)
    can_order = models.BooleanField(default=False)
    restricted_products_allowed = models.BooleanField(
        default=False, help_text="Eligible to buy alcohol and other restricted lines"
    )
    cod_allowed = models.BooleanField(default=False, help_text="May pay cash on delivery")

    customer_group = models.ForeignKey(
        CustomerGroup, null=True, blank=True, on_delete=models.SET_NULL, related_name="accounts"
    )
    delivery_zone = models.ForeignKey(
        "delivery.DeliveryZone",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accounts",
    )

    # Phase 2
    credit_limit = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    payment_terms_days = models.SmallIntegerField(null=True, blank=True)
    assigned_rep = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_accounts"
    )

    internal_notes = models.TextField(
        blank=True, help_text="Staff only — never shown to the customer"
    )

    class Meta:
        db_table = "business_account"
        indexes = [
            models.Index(fields=["status"], name="idx_ba_status"),
            models.Index(fields=["customer_group"], name="idx_ba_group"),
        ]

    def __str__(self) -> str:
        return f"{self.business_name} ({self.account_number})"

    @property
    def is_approved(self) -> bool:
        return self.status == AccountStatus.APPROVED

    def approve(self, *, by: User) -> None:
        self.status = AccountStatus.APPROVED
        self.approved_at = timezone.now()
        self.approved_by = by
        self.can_view_prices = True
        self.can_order = True
        self.save(
            update_fields=[
                "status",
                "approved_at",
                "approved_by",
                "can_view_prices",
                "can_order",
                "updated_at",
            ]
        )


class BusinessAccountMember(TimeStampedModel):
    """A shop may have an owner, a buyer and an accountant on one account."""

    business_account = models.ForeignKey(
        BusinessAccount, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=MemberRole.choices, default=MemberRole.BUYER)
    is_default = models.BooleanField(default=False, help_text="The user's active account")
    invited_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="sent_invitations"
    )

    class Meta:
        db_table = "business_account_member"
        constraints = [
            models.UniqueConstraint(fields=["business_account", "user"], name="uq_bam"),
        ]
        indexes = [models.Index(fields=["user"], name="idx_bam_user")]

    def __str__(self) -> str:
        return f"{self.user.email} — {self.get_role_display()}"

    @property
    def can_order(self) -> bool:
        return self.role in {MemberRole.OWNER, MemberRole.BUYER}


class Address(BaseModel, ArchivableModel):
    business_account = models.ForeignKey(
        BusinessAccount, on_delete=models.CASCADE, related_name="addresses"
    )
    label = models.CharField(max_length=60, blank=True, help_text='e.g. "Ikorodu shop"')
    address_type = models.CharField(
        max_length=16, choices=AddressType.choices, default=AddressType.DELIVERY
    )

    contact_name = models.CharField(max_length=150)
    contact_phone = models.CharField(max_length=32)
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=2, default="NG")

    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    delivery_zone = models.ForeignKey(
        "delivery.DeliveryZone",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="addresses",
        help_text="Resolved on save from city/state",
    )
    delivery_instructions = models.TextField(blank=True)

    is_default_billing = models.BooleanField(default=False)
    is_default_delivery = models.BooleanField(default=False)

    class Meta:
        db_table = "address"
        verbose_name_plural = "addresses"
        constraints = [
            # Exactly one default of each kind, without a trigger.
            models.UniqueConstraint(
                fields=["business_account"],
                condition=models.Q(is_default_billing=True),
                name="uq_addr_default_billing",
            ),
            models.UniqueConstraint(
                fields=["business_account"],
                condition=models.Q(is_default_delivery=True),
                name="uq_addr_default_delivery",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.line1}, {self.city}"

    @property
    def single_line(self) -> str:
        parts = [self.line1, self.line2, self.city, self.state, self.country]
        return ", ".join(p for p in parts if p)


class StaffRole(TimeStampedModel):
    code = models.CharField(max_length=40, unique=True, choices=StaffRoleCode.choices)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(default=False, help_text="Cannot be deleted")

    class Meta:
        db_table = "staff_role"

    def __str__(self) -> str:
        return self.name


class StaffAssignment(TimeStampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="staff_assignments")
    role = models.ForeignKey(StaffRole, on_delete=models.CASCADE, related_name="assignments")
    granted_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="granted_roles"
    )

    class Meta:
        db_table = "staff_assignment"
        constraints = [models.UniqueConstraint(fields=["user", "role"], name="uq_staff_assignment")]

    def __str__(self) -> str:
        return f"{self.user.email} → {self.role.code}"


class AuthToken(TimeStampedModel):
    """Refresh, reset, verification and OTP tokens.

    Only the SHA-256 hash is stored — a database leak never yields usable tokens.
    """

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="auth_tokens")
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    purpose = models.CharField(max_length=24, choices=TokenPurpose.choices)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    rotated_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="rotations"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "auth_token"
        indexes = [
            models.Index(
                fields=["user", "purpose"],
                condition=models.Q(revoked_at__isnull=True),
                name="idx_token_user_purpose",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} — {self.purpose}"

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and self.used_at is None and self.expires_at > timezone.now()
