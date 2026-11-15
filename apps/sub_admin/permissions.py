from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from apps.accounts.models import RoleType
from apps.sub_admin.services import can_manage_module

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
ACTION_BY_METHOD = {
    "POST": "add",
    "PUT": "edit",
    "PATCH": "edit",
    "DELETE": "delete",
}
DEFAULT_ACTIONS = {
    "list": "view",
    "retrieve": "view",
    "create": "add",
    "update": "edit",
    "partial_update": "edit",
    "destroy": "delete",
}
ACTION_LABELS = {
    "view": "view",
    "add": "create",
    "edit": "edit",
    "delete": "delete",
    "export": "export",
}


class IsSubAdmin(BasePermission):
    """Only subadmin users are allowed (admins excluded)."""

    message = "Only sub-admins can perform this action."

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated and request.user.role == RoleType.SUB_ADMIN
        )


class ModulePermission(BasePermission):
    """
    Reusable module/action gate for sub-admins.

    Admins and superadmins always pass. Agents and customers are left to the
    existing role permission classes so their self-service endpoints keep
    working. Sub-admins need the exact module + action flag.
    """

    module = None

    def _resolve_module(self, view):
        return getattr(view, "permission_module", None) or self.module

    def _resolve_action(self, request, view):
        explicit = getattr(view, "permission_action", None)
        if explicit:
            return explicit

        action_map = getattr(view, "permission_action_map", {}) or {}
        view_action = getattr(view, "action", None)
        if view_action in action_map:
            return action_map[view_action]
        if view_action in DEFAULT_ACTIONS:
            return DEFAULT_ACTIONS[view_action]
        if request.method in SAFE_METHODS:
            return "view"
        return ACTION_BY_METHOD.get(request.method, "view")

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False

        module = self._resolve_module(view)
        if not module:
            return True

        action = self._resolve_action(request, view)
        if can_manage_module(request.user, module, action):
            return True

        label = ACTION_LABELS.get(action, action)
        raise PermissionDenied(
            f"You do not have permission to {label} {module.replace('_', ' ')}."
        )


# Backwards-compatible name for code that imported the old class.
class HasModulePermission(ModulePermission):
    pass
