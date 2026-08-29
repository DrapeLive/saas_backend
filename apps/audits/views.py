from django.db import transaction
from django.db.models import Q, Sum
from django.utils.timezone import now
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdmin, IsAdminOrSubAdmin
from apps.audits.models import AuditLog
from apps.audits.serializers import (
    AuditLogDetailSerializer,
    AuditLogFilterSerializer,
    AuditLogListSerializer,
    DistinctActionsSerializer,
)
from apps.core.openapi import RESPONSE_404


@extend_schema_view(
    list=extend_schema(
        tags=["Audit Logs"],
        summary="List audit logs",
        description="Admin-only, company-scoped audit trail (latest 500 entries).",
        parameters=[
            OpenApiParameter(
                "user_id", OpenApiTypes.UUID, OpenApiParameter.QUERY, description="Filter by acting user."
            ),
            OpenApiParameter(
                "user_role", OpenApiTypes.STR, OpenApiParameter.QUERY, description="Filter by acting user role."
            ),
            OpenApiParameter(
                "action", OpenApiTypes.STR, OpenApiParameter.QUERY,
                description="Exact action string, e.g. `order.create`, `company.suspend`.",
            ),
            OpenApiParameter(
                "entity_type", OpenApiTypes.STR, OpenApiParameter.QUERY, description="Filter by entity type."
            ),
            OpenApiParameter(
                "entity_id", OpenApiTypes.UUID, OpenApiParameter.QUERY, description="Filter by entity id."
            ),
            OpenApiParameter(
                "date_from", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="Filter from date."
            ),
            OpenApiParameter(
                "date_to", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="Filter to date."
            ),
            OpenApiParameter(
                "ip_address", OpenApiTypes.STR, OpenApiParameter.QUERY, description="Filter by IP address."
            ),
        ],
        responses={200: AuditLogListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Audit Logs"],
        summary="Get audit log",
        responses={200: AuditLogDetailSerializer, 404: RESPONSE_404},
    ),
    distinct_actions=extend_schema(
        tags=["Audit Logs"],
        summary="List distinct actions",
        description="Returns all distinct action strings for the filter dropdown.",
        responses={200: DistinctActionsSerializer()},
    ),
)


class AuditLogViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

    def _get_company(self, request):
        return request.user.company

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AuditLogDetailSerializer
        return AuditLogListSerializer

    # GET /api/audit-logs/
    def list(self, request):
        company = self._get_company(request)

        # Validate filter params
        filter_serializer = AuditLogFilterSerializer(data=request.query_params)
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data

        qs = (
            AuditLog.objects.filter(company=company)
            .select_related("user")
            .order_by("-created_at")
        )

        if filters.get("user_id"):
            qs = qs.filter(user_id=filters["user_id"])
        if filters.get("user_role"):
            qs = qs.filter(user_role=filters["user_role"])
        if filters.get("action"):
            qs = qs.filter(action=filters["action"])
        if filters.get("entity_type"):
            qs = qs.filter(entity_type=filters["entity_type"])
        if filters.get("entity_id"):
            qs = qs.filter(entity_id=filters["entity_id"])
        if filters.get("date_from"):
            qs = qs.filter(created_at__date__gte=filters["date_from"])
        if filters.get("date_to"):
            qs = qs.filter(created_at__date__lte=filters["date_to"])
        if filters.get("ip_address"):
            qs = qs.filter(ip_address=filters["ip_address"])

        return Response(AuditLogListSerializer(qs[:500], many=True).data)

    # GET /api/audit-logs/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        try:
            log = AuditLog.objects.select_related("user").get(pk=pk, company=company)
        except AuditLog.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(AuditLogDetailSerializer(log).data)

    # GET /api/audit-logs/actions/
    @action(detail=False, methods=["get"], url_path="actions")
    def distinct_actions(self, request):
        """Returns all distinct action strings for the filter dropdown."""
        company = self._get_company(request)
        actions = (
            AuditLog.objects.filter(company=company)
            .values_list("action", flat=True)
            .distinct()
            .order_by("action")
        )
        return Response(list(actions))
