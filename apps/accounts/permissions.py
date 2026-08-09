from rest_framework.permissions import BasePermission

from apps.accounts.models import RoleType


class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated and request.user.role == RoleType.SUPER_ADMIN
        )


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role == RoleType.ADMIN
            and request.user.company_id is not None
        )


class IsCompanyAdminOrAbove(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in (
            RoleType.SUPER_ADMIN,
            RoleType.ADMIN,
        )


class IsCompanyStaff(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in (
            RoleType.SUPER_ADMIN,
            RoleType.ADMIN,
            RoleType.SUB_ADMIN,
            RoleType.AGENT,
        )


class IsAgent(BasePermission):
    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated and request.user.role == RoleType.AGENT
        )


class IsSelf(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request is None:
            return getattr(obj, "company_id", None) is not None
        return obj.pk == request.user.pk


class CompanyApproved(BasePermission):
    message = "Company is pending approval. Access denied."

    def has_permission(self, request, view=None):
        if not request.user.is_authenticated:
            return False
        if request.user.role == RoleType.SUPER_ADMIN:
            return True
        if request.user.company_id is None:
            return True
        company = getattr(request, "company", None)
        if company is None:
            from apps.companies.models import Company

            try:
                company = Company.objects.get(pk=request.user.company_id)
            except Company.DoesNotExist:
                return False
        return company.status not in ("pending",)


class CanManageUsers(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.user.role == RoleType.SUPER_ADMIN:
            return True
        if request.user.role == RoleType.ADMIN:
            return True
        return False


class IsAdminOrSubAdmin(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in (
            RoleType.SUB_ADMIN,
            RoleType.ADMIN,
        )


class IsAdminSubAdminOrAgent(BasePermission):
    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        return request.user.role in (
            RoleType.ADMIN,
            RoleType.SUB_ADMIN,
            RoleType.AGENT,
        )
