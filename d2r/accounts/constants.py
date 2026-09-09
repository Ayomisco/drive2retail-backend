from django.db import models


class UserType(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    STAFF = "staff", "Staff"


class BusinessType(models.TextChoices):
    RETAILER = "retailer", "Retailer"
    WHOLESALER = "wholesaler", "Wholesaler"
    SUPERMARKET = "supermarket", "Supermarket"
    CHAIN = "chain", "Chain store"
    OPEN_MARKET = "open_market", "Open market"
    NEIGHBOURHOOD = "neighbourhood", "Neighbourhood store"
    OTHER = "other", "Other"


class AccountStatus(models.TextChoices):
    PENDING = "pending", "Pending approval"
    APPROVED = "approved", "Approved"
    SUSPENDED = "suspended", "Suspended"
    REJECTED = "rejected", "Rejected"
    CLOSED = "closed", "Closed"


class MemberRole(models.TextChoices):
    OWNER = "owner", "Owner"
    BUYER = "buyer", "Buyer"
    VIEWER = "viewer", "Viewer"


class AddressType(models.TextChoices):
    BILLING = "billing", "Billing"
    DELIVERY = "delivery", "Delivery"
    BOTH = "both", "Billing and delivery"


class TokenPurpose(models.TextChoices):
    REFRESH = "refresh", "Refresh"
    PASSWORD_RESET = "password_reset", "Password reset"
    EMAIL_VERIFY = "email_verify", "Email verification"
    OTP = "otp", "One-time passcode"


class StaffRoleCode(models.TextChoices):
    ADMIN = "admin", "Administrator"
    CATALOGUE = "catalogue", "Catalogue"
    INVENTORY = "inventory", "Inventory"
    OPS = "ops", "Operations"
    FINANCE = "finance", "Finance"
    SUPPORT = "support", "Customer support"
    SALES = "sales", "Sales"
