"""Shared fixtures."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

User = get_user_model()


@pytest.fixture
def api() -> APIClient:
    return APIClient()


@pytest.fixture
def customer(db):
    return User.objects.create_user(
        email="buyer@adeolastores.ng",
        password="correct-horse-battery",
        first_name="Adeola",
        last_name="Okonkwo",
        is_email_verified=True,
    )


@pytest.fixture
def staff(db):
    from d2r.accounts.constants import UserType

    return User.objects.create_user(
        email="ops@drive2retail.com",
        password="correct-horse-battery",
        first_name="Ops",
        last_name="Staff",
        user_type=UserType.STAFF,
        is_staff=True,
        is_email_verified=True,
    )


@pytest.fixture
def business_account(db, customer):
    from d2r.accounts.constants import AccountStatus, BusinessType, MemberRole
    from d2r.accounts.models import BusinessAccount, BusinessAccountMember

    account = BusinessAccount.objects.create(
        account_number="D2R-C-00001",
        business_name="Adeola Stores Ltd",
        business_type=BusinessType.RETAILER,
        primary_contact_name="Adeola Okonkwo",
        primary_email="buyer@adeolastores.ng",
        primary_phone="+2348012345678",
        status=AccountStatus.APPROVED,
        can_view_prices=True,
        can_order=True,
    )
    BusinessAccountMember.objects.create(
        business_account=account, user=customer, role=MemberRole.OWNER, is_default=True
    )
    return account
