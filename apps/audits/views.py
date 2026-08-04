from django.db import transaction
from django.db.models import Q, Sum
from django.utils.timezone import now
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
)


class AuditLogViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

    def _get_company(self, request):
        return request.user.company

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
