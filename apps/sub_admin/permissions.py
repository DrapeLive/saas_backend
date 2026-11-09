from rest_framework.permissions import BasePermission

from apps.accounts.models import RoleType
from apps.sub_admin.services import can_manage_module


class IsSubAdmin(BasePermission):
    """Only subadmin users are allowed (admins excluded)."""

    message = "Only sub-admins can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated and request.user.role == RoleType.SUB_ADMIN
        )


class HasModulePermission(BasePermission):
    """
    RBAC gate for a specific module. Admins always pass; subadmins must have
    the module's `can_view` in their RoleTemplate or custom permissions.
    """

    module = None

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return can_manage_module(request.user, self.module)