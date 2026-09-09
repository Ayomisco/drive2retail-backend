"""Permission classes implementing the RBAC matrix in docs/backend/04-security.md §2."""

from __future__ import annotations

from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.views import APIView


class IsStaff(permissions.BasePermission):
    message = "Staff access required."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(user and user.is_authenticated and user.is_staff_user)


class HasStaffRole(permissions.BasePermission):
    """Checks `required_roles` on the view against the user's staff roles."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not (user and user.is_authenticated and user.is_staff_user):
            return False
        required = getattr(view, "required_roles", None)
        if not required:
            return True
        return user.has_any_role(required)


class IsApprovedCustomer(permissions.BasePermission):
    """Gate on the *business account*, not the user.

    Returns 403 rather than 404 so the customer learns they are awaiting
    approval instead of thinking the catalogue does not exist.
    """

    message = "Your account is awaiting approval for wholesale purchasing."

    def has_permission(self, request: Request, view: APIView) -> bool:
        account = getattr(request, "account", None)
        return bool(account and account.can_order)


class CanViewPrices(permissions.BasePermission):
    message = "Prices are visible once your account is approved."

    def has_permission(self, request: Request, view: APIView) -> bool:
        account = getattr(request, "account", None)
        return bool(account and account.can_view_prices)


class ReadOnly(permissions.BasePermission):
    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.method in permissions.SAFE_METHODS
