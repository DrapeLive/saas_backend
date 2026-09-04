from datetime import timedelta

from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import CompanyApproved, IsAdmin, IsSuperAdmin
from apps.audits.models import AuditLog
from apps.companies.models import Company, CompanySettings
from apps.companies.serializers import (
    CompanyListSerializer,
    CompanySerializer,
    CompanySettingsResponseSerializer,
    CompanySettingsSerializer,
    CompanyStatusUpdateSerializer,
    CompanyUpdateSerializer,
    ExtendTrialSerializer,
)
from apps.subscriptions.models import SubscriptionEvent


class SuperAdminCompanyViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsSuperAdmin,)

    def get_serializer_class(self):
        if self.action == "update_status":
            return CompanyStatusUpdateSerializer
        if self.action == "update":
            return CompanyUpdateSerializer
        return CompanyListSerializer

    def list(self, request, *args, **kwargs):
        companies = Company.objects.all().order_by("-created_at")
        serializer = CompanyListSerializer(companies, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None, *args, **kwargs):
        try:
            company = Company.objects.get(pk=pk)
        except Company.DoesNotExist:
            return Response(
                {"detail": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        serializer = CompanySerializer(company)
        return Response(serializer.data)

    def update(self, request, pk=None, *args, **kwargs):
        company = self._get_company(pk, request)
        if company is None:
            return Response(
                {"detail": "Company not found."}, status=status.HTTP_404_NOT_FOUND
            )

        old_data = CompanySerializer(company).data
        serializer = CompanyUpdateSerializer(company, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        changed = _audit_changes(serializer, request, old_data)
        if changed:
            self._log_audit(
                request,
                company,
                "company.update",
                old_value={k: v["old"] for k, v in changed.items()},
                new_value={k: v["new"] for k, v in changed.items()},
            )
        return Response(CompanySerializer(company).data)

    @action(detail=True, methods=["post"], url_path="status")
    def update_status(self, request, pk=None, *args, **kwargs):
        try:
            company = Company.objects.get(pk=pk)
        except Company.DoesNotExist:
            return Response(
                {"detail": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = CompanyStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = company.status
        company.status = serializer.validated_data["status"]
        company.save(update_fields=["status"])

        return Response(
            {
                "detail": f"Company status changed from {old_status} to {company.status}.",
                "company": CompanySerializer(company).data,
            }
        )

    def _log_audit(self, request, company, action, old_value=None, new_value=None):
        AuditLog.objects.create(
            company=company,
            user=request.user,
            user_role=request.user.role,
            action=action,
            entity_type="Company",
            entity_id=company.pk,
            old_value=old_value,
            new_value=new_value,
            ip_address=request.META.get("REMOTE_ADDR", ""),
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )

    def _get_company(self, pk, request):
        try:
            return Company.objects.get(pk=pk)
        except Company.DoesNotExist:
            return None

    @action(detail=True, methods=["post"], url_path="suspend")
    def suspend(self, request, pk=None):
        company = self._get_company(pk, request)
        if company is None:
            return Response(
                {"detail": "Company not found."}, status=status.HTTP_404_NOT_FOUND
            )
        if company.status == "suspended":
            return Response(
                {"detail": "Company is already suspended."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old = company.status
        company.status = "suspended"
        company.save(update_fields=["status"])

        SubscriptionEvent.objects.create(
            subscription=company.subscription,
            event_type="suspended",
            performed_by=request.user,
            notes="Suspended by super admin",
        ) if company.subscription else None

        self._log_audit(
            request,
            company,
            "company.suspend",
            old_value={"status": old},
            new_value={"status": "suspended"},
        )
        return Response(
            {
                "detail": f"Company {company.name} suspended.",
                "company": CompanySerializer(company).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="activate")
    def activate(self, request, pk=None):
        company = self._get_company(pk, request)
        if company is None:
            return Response(
                {"detail": "Company not found."}, status=status.HTTP_404_NOT_FOUND
            )
        if company.status != "suspended":
            return Response(
                {"detail": "Only suspended companies can be activated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        company.status = "active"
        company.save(update_fields=["status"])

        SubscriptionEvent.objects.create(
            subscription=company.subscription,
            event_type="reactivated",
            performed_by=request.user,
            notes="Reactivated by super admin",
        ) if company.subscription else None

        self._log_audit(
            request,
            company,
            "company.activate",
            old_value={"status": "suspended"},
            new_value={"status": "active"},
        )
        return Response(
            {
                "detail": f"Company {company.name} activated.",
                "company": CompanySerializer(company).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="extend-trial")
    def extend_trial(self, request, pk=None):
        company = self._get_company(pk, request)
        if company is None:
            return Response(
                {"detail": "Company not found."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = ExtendTrialSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        days = serializer.validated_data["days"]
        reason = serializer.validated_data["reason"]

        sub = company.subscription
        if sub is None:
            return Response(
                {"detail": "Company has no subscription."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if sub.status != "trial":
            return Response(
                {"detail": "Can only extend trial period."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        old_end = sub.trial_end
        from datetime import timedelta as td

        sub.trial_end = (sub.trial_end or now().date()) + td(days=days)
        sub.save(update_fields=["trial_end"])

        SubscriptionEvent.objects.create(
            subscription=sub,
            event_type="extended",
            performed_by=request.user,
            notes=reason,
            metadata={"days": days},
        )

        self._log_audit(
            request,
            company,
            "company.extend_trial",
            old_value={"trial_end": str(old_end) if old_end else None},
            new_value={"trial_end": str(sub.trial_end), "reason": reason, "days": days},
        )
        return Response(
            {"detail": f"Trial extended by {days} days.", "trial_end": sub.trial_end}
        )

    @action(detail=True, methods=["post"], url_path="impersonate")
    def impersonate(self, request, pk=None):
        company = self._get_company(pk, request)
        if company is None:
            return Response(
                {"detail": "Company not found."}, status=status.HTTP_404_NOT_FOUND
            )

        admin = company.members.filter(role="admin").first()
        if admin is None:
            return Response(
                {"detail": "Company has no admin user."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refresh = RefreshToken.for_user(admin)
        refresh.set_exp(lifetime=timedelta(minutes=30))
        refresh["role"] = admin.role
        refresh["company_id"] = str(admin.company_id)
        refresh["is_super_admin"] = False
        refresh["impersonating"] = True

        self._log_audit(
            request,
            company,
            "superadmin.impersonate",
            new_value={"impersonated_user": str(admin.pk), "expires_in": "30m"},
        )
        return Response({"access": str(refresh.access_token), "expires_in": 1800})

    def destroy(self, request, pk=None):
        company = self._get_company(pk, request)
        if company is None:
            return Response(
                {"detail": "Company not found."}, status=status.HTTP_404_NOT_FOUND
            )
        if company.status == "active":
            return Response(
                {"detail": "Cannot delete a company with an active subscription."},
                status=status.HTTP_409_CONFLICT,
            )

        company.is_deleted = True
        company.deleted_at = now()
        company.status = "expired"
        company.save(update_fields=["is_deleted", "deleted_at", "status"])

        self._log_audit(request, company, "company.delete")
        return Response(status=status.HTTP_204_NO_CONTENT)


class CompanyDetailViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsAdmin)
    serializer_class = CompanyUpdateSerializer

    def update(self, request, *args, **kwargs):
        company = request.company
        if company is None:
            return Response(
                {"detail": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        old_data = CompanySerializer(company).data
        serializer = CompanyUpdateSerializer(company, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        changed = _audit_changes(serializer, request, old_data)
        if changed:
            AuditLog.objects.create(
                company=company,
                user=request.user,
                user_role=request.user.role,
                action="company.update",
                entity_type="Company",
                entity_id=company.pk,
                old_value={k: v["old"] for k, v in changed.items()},
                new_value={k: v["new"] for k, v in changed.items()},
                ip_address=request.META.get("REMOTE_ADDR", ""),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )
        return Response(CompanySerializer(company).data)


def _audit_changes(serializer, request, old_data):
    """Build a JSON-serializable dict of changed scalar fields for audit logs."""
    from django.core.files.uploadedfile import UploadedFile

    changed = {}
    for k, v in request.data.items():
        if k not in serializer.fields:
            continue
        if isinstance(v, (UploadedFile, dict, list)):
            continue
        if old_data.get(k) != v:
            changed[k] = {"old": old_data.get(k), "new": v}
    return changed


def _get_company_settings(company):
    settings, _ = CompanySettings.objects.get_or_create(company=company)
    return settings


class CompanySettingsViewSet(GenericViewSet):
    """
    Admin-facing view of the caller's own company settings.

    - GET   /api/admin/company/settings   → full settings (editable + plan snapshot)
    - PATCH /api/admin/company/settings   → update editable settings fields

    Plan-derived fields (limits + advanced feature flags) are read-only and are
    synced from the company's subscription plan via `apply_plan_to_company`.
    """

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsAdmin)
    queryset = CompanySettings.objects.none()

    def get_serializer_class(self):
        if self.action == "update":
            return CompanySettingsSerializer
        return CompanySettingsResponseSerializer

    def _get_settings(self, request):
        company = request.company
        if company is None:
            return None
        return _get_company_settings(company)

    def retrieve(self, request, *args, **kwargs):
        settings = self._get_settings(request)
        if settings is None:
            return Response(
                {"detail": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(CompanySettingsResponseSerializer(settings).data)

    def update(self, request, *args, **kwargs):
        settings = self._get_settings(request)
        if settings is None:
            return Response(
                {"detail": "Company not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        old_data = CompanySettingsSerializer(settings).data
        serializer = CompanySettingsSerializer(
            settings, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        changed = {
            k: {"old": old_data.get(k), "new": v}
            for k, v in request.data.items()
            if k in serializer.fields and old_data.get(k) != v
        }
        if changed:
            AuditLog.objects.create(
                company=request.company,
                user=request.user,
                user_role=request.user.role,
                action="company.settings.update",
                entity_type="CompanySettings",
                entity_id=settings.pk,
                old_value={k: v["old"] for k, v in changed.items()},
                new_value={k: v["new"] for k, v in changed.items()},
                ip_address=request.META.get("REMOTE_ADDR", ""),
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
            )
        return Response(CompanySettingsResponseSerializer(settings).data)
