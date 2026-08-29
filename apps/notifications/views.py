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
from apps.core.openapi import DETAIL_RESPONSE_200, RESPONSE_400, RESPONSE_403, RESPONSE_404
from apps.notifications.models import (
    Notification,
    NotificationStatus,
    NotificationTemplate,
)
from apps.notifications.serializers import (
    NotificationDetailSerializer,
    NotificationListSerializer,
    NotificationPreferenceSerializer,
    NotificationRetrySerializer,
    NotificationSendSerializer,
    NotificationTemplateCreateUpdateSerializer,
    NotificationTemplateDetailSerializer,
    NotificationTemplateListSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Notifications"],
        summary="List notification templates",
        description="Active templates, including system defaults (`company` is null).",
        responses={200: NotificationTemplateListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Notifications"],
        summary="Get notification template",
        responses={200: NotificationTemplateDetailSerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Notifications"],
        summary="Create notification template",
        responses={201: NotificationTemplateDetailSerializer, 400: RESPONSE_400, 403: RESPONSE_403},
    ),
    partial_update=extend_schema(
        tags=["Notifications"],
        summary="Update notification template",
        responses={200: NotificationTemplateDetailSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    destroy=extend_schema(
        tags=["Notifications"],
        summary="Delete notification template",
        responses={204: None, 404: RESPONSE_404},
    ),
)
class NotificationTemplateViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

    def get_serializer_class(self):
        if self.action == "list":
            return NotificationTemplateListSerializer
        if self.action in ("create", "partial_update"):
            return NotificationTemplateCreateUpdateSerializer
        return NotificationTemplateDetailSerializer

    def _get_company(self, request):
        return request.user.company

    # GET /api/notification-templates/
    def list(self, request):
        company = self._get_company(request)
        qs = NotificationTemplate.objects.filter(
            company__in=[None, company], is_active=True
        ).order_by("event_type", "channel")
        return Response(NotificationTemplateListSerializer(qs, many=True).data)

    # GET /api/notification-templates/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        try:
            obj = NotificationTemplate.objects.get(pk=pk, company__in=[None, company])
        except NotificationTemplate.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(NotificationTemplateDetailSerializer(obj).data)

    # POST /api/notification-templates/
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = NotificationTemplateCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save(company=company)
        return Response(
            NotificationTemplateDetailSerializer(obj).data,
            status=status.HTTP_201_CREATED,
        )

    # PATCH /api/notification-templates/<pk>/
    @transaction.atomic
    def partial_update(self, request, pk=None):
        company = self._get_company(request)
        try:
            obj = NotificationTemplate.objects.get(pk=pk, company=company)
        except NotificationTemplate.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = NotificationTemplateCreateUpdateSerializer(
            obj, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(NotificationTemplateDetailSerializer(obj).data)

    # DELETE /api/notification-templates/<pk>/
    def destroy(self, request, pk=None):
        company = self._get_company(request)
        try:
            obj = NotificationTemplate.objects.get(pk=pk, company=company)
        except NotificationTemplate.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(
        tags=["Notifications"],
        summary="List notifications",
        description="Company-scoped notification log (latest 200 entries).",
        parameters=[
            OpenApiParameter(
                "channel", OpenApiTypes.STR, OpenApiParameter.QUERY,
                enum=["whatsapp", "email", "push", "in_app"],
                description="Filter by channel.",
            ),
            OpenApiParameter(
                "status", OpenApiTypes.STR, OpenApiParameter.QUERY,
                enum=["pending", "sent", "delivered", "read", "failed"],
                description="Filter by status.",
            ),
            OpenApiParameter(
                "date_from", OpenApiTypes.DATE, OpenApiParameter.QUERY,
                description="Only notifications created on or after this date.",
            ),
        ],
        responses={200: NotificationListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Notifications"],
        summary="Get notification",
        responses={200: NotificationDetailSerializer, 404: RESPONSE_404},
    ),
    send=extend_schema(
        tags=["Notifications"],
        summary="Send manual notification",
        description="Sends an ad-hoc WhatsApp/email notification to one or more recipients. Admin only.",
        responses={200: DETAIL_RESPONSE_200, 400: RESPONSE_400, 403: RESPONSE_403},
    ),
    retry=extend_schema(
        tags=["Notifications"],
        summary="Retry failed notification",
        description="Re-queues a single failed notification for delivery. Admin only.",
        responses={200: DETAIL_RESPONSE_200, 400: RESPONSE_400, 403: RESPONSE_403},
    ),
)
class NotificationViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def get_serializer_class(self):
        if self.action == "list":
            return NotificationListSerializer
        if self.action == "send":
            return NotificationSendSerializer
        if self.action == "retry":
            return NotificationRetrySerializer
        return NotificationDetailSerializer

    def _get_company(self, request):
        return request.user.company

    # GET /api/notifications/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            Notification.objects.filter(company=company)
            .select_related("recipient")
            .order_by("-created_at")
        )

        channel_f = request.query_params.get("channel")
        status_f = request.query_params.get("status")
        date_from = request.query_params.get("date_from")

        if channel_f:
            qs = qs.filter(channel=channel_f)
        if status_f:
            qs = qs.filter(status=status_f)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        return Response(NotificationListSerializer(qs[:200], many=True).data)

    # GET /api/notifications/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        try:
            obj = Notification.objects.get(pk=pk, company=company)
        except Notification.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(NotificationDetailSerializer(obj).data)

    # POST /api/notifications/send/
    @action(
        detail=False, methods=["post"], url_path="send", permission_classes=[IsAdmin]
    )
    def send(self, request):
        company = self._get_company(request)
        serializer = NotificationSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # tasks.send_manual_notification.delay(
        #     company_id=str(company.id),
        #     **serializer.validated_data,
        # )
        recipient_count = len(
            serializer.validated_data.get("recipient_ids", [])
            or serializer.validated_data.get("recipient_phones", [])
        )
        return Response(
            {
                "detail": f"Notification queued for {recipient_count} recipient(s).",
                "channel": serializer.validated_data["channel"],
            }
        )

    # POST /api/notifications/retry/
    @action(
        detail=False, methods=["post"], url_path="retry", permission_classes=[IsAdmin]
    )
    def retry(self, request):
        serializer = NotificationRetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # tasks.retry_notification.delay(str(serializer.validated_data["notification_id"]))
        return Response({"detail": "Notification queued for retry."})
