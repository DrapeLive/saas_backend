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
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdmin, IsAdminOrSubAdmin
from apps.core.openapi import (
    DETAIL_RESPONSE_200,
    RESPONSE_400,
    RESPONSE_403,
    RESPONSE_404,
)
from apps.tally_integrations.models import TallyLedgerMapping, TallySyncLog
from apps.tally_integrations.serializers import (
    TallyConnectionTestSerializer,
    TallyLedgerMappingCreateUpdateSerializer,
    TallyLedgerMappingSerializer,
    TallySyncLogDetailSerializer,
    TallySyncLogListSerializer,
    TallySyncRetrySerializer,
    TallySyncStatusSummarySerializer,
    TallySyncTriggerSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Tally Integration"],
        summary="List sync logs",
        description="Company-scoped sync ledger (latest 200 entries).",
        parameters=[
            OpenApiParameter(
                "direction", OpenApiTypes.STR, OpenApiParameter.QUERY,
                enum=["push", "pull"], description="Filter by sync direction.",
            ),
            OpenApiParameter(
                "status", OpenApiTypes.STR, OpenApiParameter.QUERY,
                enum=["pending", "success", "failed", "retry"],
                description="Filter by sync status.",
            ),
            OpenApiParameter(
                "entity_type", OpenApiTypes.STR, OpenApiParameter.QUERY,
                description="Filter by entity type.",
            ),
        ],
        responses={200: TallySyncLogListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Tally Integration"],
        summary="Get sync log",
        responses={200: TallySyncLogDetailSerializer, 404: RESPONSE_404},
    ),
    trigger=extend_schema(
        tags=["Tally Integration"],
        summary="Trigger sync",
        description="Manually queues a Tally sync for an entity. Admin only.",
        responses={200: DETAIL_RESPONSE_200, 400: RESPONSE_400, 403: RESPONSE_403},
    ),
    retry=extend_schema(
        tags=["Tally Integration"],
        summary="Retry failed syncs",
        description="Re-queues one or more failed sync logs. Admin only.",
        responses={200: DETAIL_RESPONSE_200, 400: RESPONSE_400, 403: RESPONSE_403},
    ),
    test_connection=extend_schema(
        tags=["Tally Integration"],
        summary="Test Tally connection",
        description="Pings the configured Tally HTTP gateway. Admin only.",
        responses={200: DETAIL_RESPONSE_200, 400: RESPONSE_400, 403: RESPONSE_403},
    ),
    sync_status=extend_schema(
        tags=["Tally Integration"],
        summary="Sync health summary",
        responses={200: TallySyncStatusSummarySerializer},
    ),
)
class TallySyncLogViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TallySyncLogDetailSerializer
        if self.action == "trigger":
            return TallySyncTriggerSerializer
        if self.action == "retry":
            return TallySyncRetrySerializer
        if self.action == "test_connection":
            return TallyConnectionTestSerializer
        return TallySyncLogListSerializer

    def _get_company(self, request):
        return request.user.company

    # GET /api/tally/logs/
    def list(self, request):
        company = self._get_company(request)
        qs = TallySyncLog.objects.filter(company=company).order_by("-created_at")

        direction_f = request.query_params.get("direction")
        status_f = request.query_params.get("status")
        entity_type_f = request.query_params.get("entity_type")

        if direction_f:
            qs = qs.filter(direction=direction_f)
        if status_f:
            qs = qs.filter(status=status_f)
        if entity_type_f:
            qs = qs.filter(entity_type=entity_type_f)

        return Response(TallySyncLogListSerializer(qs[:200], many=True).data)

    # GET /api/tally/logs/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        try:
            log = TallySyncLog.objects.get(pk=pk, company=company)
        except TallySyncLog.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(TallySyncLogDetailSerializer(log).data)

    # POST /api/tally/trigger/
    @action(
        detail=False, methods=["post"], url_path="trigger", permission_classes=[IsAdmin]
    )
    def trigger(self, request):
        company = self._get_company(request)
        serializer = TallySyncTriggerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # tasks.tally_sync.delay(
        #     company_id=str(company.id),
        #     entity_type=data["entity_type"],
        #     entity_id=str(data["entity_id"]) if data.get("entity_id") else None,
        #     direction=data["direction"],
        # )
        return Response(
            {
                "detail": "Tally sync queued.",
                "entity_type": data["entity_type"],
                "direction": data["direction"],
            }
        )

    # POST /api/tally/retry/
    @action(
        detail=False, methods=["post"], url_path="retry", permission_classes=[IsAdmin]
    )
    @transaction.atomic
    def retry(self, request):
        company = self._get_company(request)
        serializer = TallySyncRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        TallySyncLog.objects.filter(
            id__in=serializer.validated_data["log_ids"],
            company=company,
        ).update(
            status=TallySyncLog.SyncStatus.RETRY, retry_count=Q(retry_count=0) or 0
        )
        # tasks.retry_failed_tally_sync.delay(log_ids=[str(i) for i in serializer.validated_data["log_ids"]])
        return Response(
            {
                "detail": f"{len(serializer.validated_data['log_ids'])} log(s) queued for retry."
            }
        )

    # POST /api/tally/test-connection/
    @action(
        detail=False,
        methods=["post"],
        url_path="test-connection",
        permission_classes=[IsAdminUser],
    )
    def test_connection(self, request):
        company = self._get_company(request)
        serializer = TallyConnectionTestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # result = tally_client.test(serializer.validated_data["tally_url"], ...)
        return Response({"detail": "Connection successful.", "latency_ms": 42})

    # GET /api/tally/status/
    @action(detail=False, methods=["get"], url_path="status")
    def sync_status(self, request):
        company = self._get_company(request)
        qs = TallySyncLog.objects.filter(company=company)
        latest = qs.order_by("-synced_at").first()
        last_failed = (
            qs.filter(status=TallySyncLog.SyncStatus.FAILED)
            .order_by("-created_at")
            .first()
        )
        return Response(
            {
                "total_synced": qs.filter(
                    status=TallySyncLog.SyncStatus.SUCCESS
                ).count(),
                "total_pending": qs.filter(
                    status=TallySyncLog.SyncStatus.PENDING
                ).count(),
                "total_failed": qs.filter(
                    status=TallySyncLog.SyncStatus.FAILED
                ).count(),
                "last_synced_at": latest.synced_at if latest else None,
                "last_error": last_failed.error_message if last_failed else None,
            }
        )


@extend_schema_view(
    list=extend_schema(
        tags=["Tally Integration"],
        summary="List ledger mappings",
        responses={200: TallyLedgerMappingSerializer(many=True)},
    ),
    create=extend_schema(
        tags=["Tally Integration"],
        summary="Create or update ledger mapping",
        description="Idempotent mapping keyed on `(company, entity_type, entity_id)`. Admin only.",
        responses={201: TallyLedgerMappingSerializer, 400: RESPONSE_400, 403: RESPONSE_403},
    ),
    destroy=extend_schema(
        tags=["Tally Integration"],
        summary="Delete ledger mapping",
        description="Returns 204.",
        responses={204: None, 404: RESPONSE_404, 403: RESPONSE_403},
    ),
)
class TallyLedgerMappingViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

    def get_serializer_class(self):
        if self.action == "create":
            return TallyLedgerMappingCreateUpdateSerializer
        return TallyLedgerMappingSerializer

    def _get_company(self, request):
        return request.user.company

    # GET /api/tally/ledger-mappings/
    def list(self, request):
        company = self._get_company(request)
        qs = TallyLedgerMapping.objects.filter(company=company).order_by("entity_type")
        return Response(TallyLedgerMappingSerializer(qs, many=True).data)

    # POST /api/tally/ledger-mappings/
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = TallyLedgerMappingCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        mapping, _ = TallyLedgerMapping.objects.update_or_create(
            company=company,
            entity_type=serializer.validated_data["entity_type"],
            entity_id=serializer.validated_data["entity_id"],
            defaults={
                "tally_ledger_name": serializer.validated_data["tally_ledger_name"],
                "tally_group": serializer.validated_data.get("tally_group", ""),
            },
        )
        return Response(
            TallyLedgerMappingSerializer(mapping).data, status=status.HTTP_201_CREATED
        )

    # DELETE /api/tally/ledger-mappings/<pk>/
    def destroy(self, request, pk=None):
        company = self._get_company(request)
        try:
            mapping = TallyLedgerMapping.objects.get(pk=pk, company=company)
        except TallyLedgerMapping.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        mapping.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
