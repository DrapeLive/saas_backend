from datetime import timedelta

from django.utils.timezone import now
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsSuperAdmin
from apps.audits.models import AuditLog
from apps.companies.models import Company
from apps.companies.serializers import (
    CompanyListSerializer,
    CompanySerializer,
    CompanyStatusChangeResponseSerializer,
    CompanyStatusUpdateSerializer,
    ExtendTrialSerializer,
    ImpersonateResponseSerializer,
    TrialExtensionResponseSerializer,
)
from apps.subscriptions.models import SubscriptionEvent
from apps.core.openapi import (
    RESPONSE_400,
    RESPONSE_403,
    RESPONSE_404,
    RESPONSE_409,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Companies"],
        summary="List all companies",
        description=(
            "Super-admin only. Lists every tenant company on the platform with "
            "subscription plan/tier/trial details, newest first."
        ),
        responses={200: CompanyListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Companies"],
        summary="Get company details",
        responses={200: CompanySerializer, 404: RESPONSE_404},
    ),
    update_status=extend_schema(
        tags=["Companies"],
        summary="Change company status",
        description=(
            "Super-admin only. Transitions a company between pending, trial, "
            "active, suspended, expired and grace."
        ),
        request=CompanyStatusUpdateSerializer,
        responses={
            200: CompanyStatusChangeResponseSerializer,
            400: RESPONSE_400,
            404: RESPONSE_404,
        },
    ),
    suspend=extend_schema(
        tags=["Companies"],
        summary="Suspend company",
        responses={
            200: CompanyStatusChangeResponseSerializer,
            400: RESPONSE_400,
            404: RESPONSE_404,
        },
    ),
    activate=extend_schema(
        tags=["Companies"],
        summary="Activate suspended company",
        responses={
            200: CompanyStatusChangeResponseSerializer,
            400: RESPONSE_400,
            404: RESPONSE_404,
        },
    ),
    extend_trial=extend_schema(
        tags=["Companies"],
        summary="Extend trial period",
        description="Extends the trial end date of a company currently in `trial` status.",
        request=ExtendTrialSerializer,
        responses={
            200: TrialExtensionResponseSerializer,
            400: RESPONSE_400,
            404: RESPONSE_404,
        },
    ),
    impersonate=extend_schema(
        tags=["Companies"],
        summary="Impersonate company admin",
        description=(
            "Issues a 30-minute access token for the company's first admin, "
            "flagged with the `impersonating` claim. Used by support."
        ),
        responses={
            200: ImpersonateResponseSerializer,
            400: RESPONSE_400,
            404: RESPONSE_404,
        },
    ),
    destroy=extend_schema(
        tags=["Companies"],
        summary="Soft-delete company",
        description=(
            "Marks a company as deleted (only allowed when not on an active "
            "subscription). Returns 204 on success."
        ),
        responses={204: None, 404: RESPONSE_404, 409: RESPONSE_409},
    ),
)
class SuperAdminCompanyViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsSuperAdmin,)

    def get_serializer_class(self):
        if self.action == "update_status":
            return CompanyStatusUpdateSerializer
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
