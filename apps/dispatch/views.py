from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdminOrSubAdmin
from apps.dispatch.models import Dispatch
from apps.dispatch.serializers import (
    DispatchCreateSerializer,
    DispatchDetailSerializer,
    DispatchListSerializer,
    DispatchUpdateSerializer,
    MarkDeliveredSerializer,
)
from apps.orders.models import OrderStatus, OrderStatusHistory


class DispatchViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def _get_company(self, request):
        return request.user.company

    def _get_dispatch(self, pk, company):
        try:
            return Dispatch.objects.select_related(
                "order__customer", "dispatched_by"
            ).get(pk=pk, company=company)
        except Dispatch.DoesNotExist:
            return None

    # GET /api/dispatches/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            Dispatch.objects.filter(company=company)
            .select_related("order__customer", "dispatched_by")
            .order_by("-dispatch_date")
        )

        status_f = request.query_params.get("status")  # pending | delivered
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        search = request.query_params.get("search")

        if status_f == "pending":
            qs = qs.filter(actual_delivery__isnull=True)
        elif status_f == "delivered":
            qs = qs.filter(actual_delivery__isnull=False)
        if date_from:
            qs = qs.filter(dispatch_date__gte=date_from)
        if date_to:
            qs = qs.filter(dispatch_date__lte=date_to)
        if search:
            qs = qs.filter(lr_number__icontains=search) | qs.filter(
                order__order_number__icontains=search
            )

        return Response(DispatchListSerializer(qs, many=True).data)

    # GET /api/dispatches/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        dispatch = self._get_dispatch(pk, company)
        if not dispatch:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(DispatchDetailSerializer(dispatch).data)

    # POST /api/dispatches/
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = DispatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order = serializer.validated_data["order"]
        dispatch = serializer.save(company=company, dispatched_by=request.user)

        # Advance order to DISPATCHED
        old_status = order.status
        order.status = OrderStatus.DISPATCHED
        order.dispatched_at = now()
        order.save(update_fields=["status", "dispatched_at"])

        OrderStatusHistory.objects.create(
            order=order,
            from_status=old_status,
            to_status=OrderStatus.DISPATCHED,
            changed_by=request.user,
            notes=f"LR: {dispatch.lr_number}",
        )

        # Deduct stock for what was actually packed and release ALL reservations
        # (packed qty leaves stock; any unpacked remainder becomes sellable again).
        for item in order.items.all():
            from apps.products.models import StockMovement, VariantSize

            shipped_qty = item.packed_quantity
            VariantSize.objects.filter(pk=item.variant_size_id).update(
                stock_quantity=F("stock_quantity") - shipped_qty,
                reserved_qty=Greatest(F("reserved_qty") - item.quantity, Value(0)),
            )
            if shipped_qty > 0:
                item.variant_size.refresh_from_db(fields=["stock_quantity"])
                StockMovement.objects.create(
                    variant_size=item.variant_size,
                    movement_type=StockMovement.MovementType.OUT,
                    quantity=-shipped_qty,
                    balance_after=item.variant_size.stock_quantity,
                    reference_type="dispatch",
                    reference_id=dispatch.id,
                    performed_by=request.user,
                )

        # Queue: generate sales invoice + WhatsApp notification
        # tasks.generate_sales_invoice.delay(str(order.id))
        # tasks.send_dispatch_notification.delay(str(dispatch.id))

        return Response(
            DispatchDetailSerializer(dispatch).data, status=status.HTTP_201_CREATED
        )

    # PATCH /api/dispatches/<pk>/
    @transaction.atomic
    def partial_update(self, request, pk=None):
        company = self._get_company(request)
        dispatch = self._get_dispatch(pk, company)
        if not dispatch:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = DispatchUpdateSerializer(dispatch, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(DispatchDetailSerializer(dispatch).data)

    # POST /api/dispatches/<pk>/mark-delivered/
    @action(detail=True, methods=["post"], url_path="mark-delivered")
    @transaction.atomic
    def mark_delivered(self, request, pk=None):
        company = self._get_company(request)
        dispatch = self._get_dispatch(pk, company)
        if not dispatch:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if dispatch.actual_delivery:
            return Response(
                {"detail": "Order is already marked as delivered."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = MarkDeliveredSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        dispatch.actual_delivery = serializer.validated_data["actual_delivery"]
        dispatch.save(update_fields=["actual_delivery"])

        order = dispatch.order
        old_status = order.status
        order.status = OrderStatus.DELIVERED
        order.delivered_at = now()
        order.save(update_fields=["status", "delivered_at"])

        OrderStatusHistory.objects.create(
            order=order,
            from_status=old_status,
            to_status=OrderStatus.DELIVERED,
            changed_by=request.user,
            notes=serializer.validated_data.get("notes", ""),
        )

        return Response(DispatchDetailSerializer(dispatch).data)
