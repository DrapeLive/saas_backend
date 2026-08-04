from django.db import transaction
from django.db.models import Q, Sum
from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdmin, IsAdminOrSubAdmin
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


class NotificationTemplateViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

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


class NotificationViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

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
