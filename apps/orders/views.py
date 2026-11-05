from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils.timezone import now
from rest_framework import status
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdminSubAdminOrAgent
from apps.orders import order_flow
from apps.orders.exceptions import OrderFlowError
from apps.orders.models import (
    Order,
    OrderSignature,
    OrderStatus,
    OrderStatusHistory,
    PackingStatus,
)
from apps.orders.realtime import (
    broadcast_order_expired,
    broadcast_order_updated,
    broadcast_stock_updates,
)
from apps.orders.serializers import (
    OrderAddItemSerializer,
    OrderApprovalSerializer,
    OrderCancelSerializer,
    OrderDetailSerializer,
    OrderDraftCreateSerializer,
    OrderDraftUpdateSerializer,
    OrderListSerializer,
    OrderSignatureSerializer,
    OrderStatusUpdateSerializer,
    OrderSubmitSerializer,
    OrderUpdateItemSerializer,
    PackItemsSerializer,
)
from apps.orders.services import send_order_notification
from apps.products.models import StockMovement, VariantSize
from apps.sub_admin.services import scope_order_queryset


class OrderViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminSubAdminOrAgent,)

    def _get_company(self, request):
        # Use request.company which is set by CustomJWTAuthentication and
        # correctly resolves the company for agents using X-Company-Id header.
        return request.company or request.user.company

    def _get_order(self, pk, company):
        try:
            return Order.objects.select_related(
                "customer", "agent__user", "approved_by"
            ).get(pk=pk, company=company)
        except Order.DoesNotExist:
            return None

    def _log_status_change(self, order, from_status, to_status, user, notes=""):
        OrderStatusHistory.objects.create(
            order=order,
            from_status=from_status,
            to_status=to_status,
            changed_by=user,
            notes=notes,
        )

    def _advance_status(self, order, new_status, user, notes=""):
        """Set a new order status and record the transition in status history."""
        old_status = order.status
        if old_status == new_status:
            return
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])
        self._log_status_change(order, old_status, new_status, user, notes or "")

    # ─────────────────────────────────────────────────────────────
    # LIST
    # GET /api/orders/
    # ─────────────────────────────────────────────────────────────

    def list(self, request):
        company = self._get_company(request)
        qs = (
            Order.objects.filter(company=company)
            .select_related("customer", "agent__user")
            .prefetch_related("items")
            .order_by("-created_at")
        )
        qs = scope_order_queryset(request.user, qs)

        # Filters
        status_f = request.query_params.get("status")
        agent_f = request.query_params.get("agent_id")
        customer_f = request.query_params.get("customer_id")
        search = request.query_params.get("search")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        pending_approval = request.query_params.get("pending_approval")
        offline_f = request.query_params.get("offline")

        include_drafts = request.query_params.get("include_drafts") in (
            "1",
            "true",
            "True",
        )
        if status_f:
            qs = qs.filter(status=status_f)
        elif not include_drafts:
            qs = qs.exclude(status=OrderStatus.DRAFT)
        if agent_f:
            qs = qs.filter(agent_id=agent_f)
        if customer_f:
            qs = qs.filter(customer_id=customer_f)
        if search:
            qs = qs.filter(order_number__icontains=search) | qs.filter(
                customer__trade_name__icontains=search
            )
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if pending_approval:
            qs = qs.filter(requires_approval=True, status=OrderStatus.SUBMITTED)
        if offline_f:
            qs = qs.filter(is_offline_order=True, sync_status="pending")

        # Agents only see their own orders
        if request.user.role == "agent":
            agent_profile = getattr(request.user, "agent_profile", None)
            qs = qs.filter(agent=agent_profile) if agent_profile else qs.none()

        return Response(OrderListSerializer(qs, many=True).data)

    # ─────────────────────────────────────────────────────────────
    # RETRIEVE
    # GET /api/orders/<pk>/
    # ─────────────────────────────────────────────────────────────

    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        order = self._get_order(pk, company)
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        scoped_ids = set(
            scope_order_queryset(request.user, Order.objects.all()).values_list(
                "id", flat=True
            )
        )
        if scoped_ids and order.id not in scoped_ids:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        # Agents can only see their own orders
        if request.user.role == "agent":
            agent_profile = getattr(request.user, "agent_profile", None)
            if order.agent != agent_profile:
                return Response(
                    {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
                )

        # Re-fetch with nested relations scoped to company to prevent cross-company leak.
        order_full = Order.objects.prefetch_related(
            "items", "status_history", "signature", "invoices"
        ).get(pk=pk, company=company)
        return Response(OrderDetailSerializer(order_full).data)

    # ─────────────────────────────────────────────────────────────
    # CREATE
    # POST /api/orders/
    # ─────────────────────────────────────────────────────────────

    @transaction.atomic
    def create(self, request):
        """Create an empty DRAFT order after the agent selects a customer."""
        company = self._get_company(request)
        if request.data.get("items"):
            return Response(
                {
                    "detail": (
                        "Items cannot be sent while creating an order. Create the "
                        "draft first, then add items via POST /api/orders/<id>/items/."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = OrderDraftCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        agent = self._get_agent(request)
        try:
            order = order_flow.create_draft_order(
                company, agent, request.user, serializer.validated_data
            )
        except OrderFlowError as exc:
            return self._flow_error(exc)

        order = self._reload_order(order.pk, company)
        broadcast_order_updated(order)
        return Response(
            OrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )

    # ─────────────────────────────────────────────────────────────
    # DRAFT ORDER FLOW
    # ─────────────────────────────────────────────────────────────

    def _get_agent(self, request):
        from rest_framework.exceptions import PermissionDenied

        agent = getattr(request.user, "agent_profile", None)
        if request.user.role != "agent" or agent is None:
            raise PermissionDenied(
                "Only agents can use the order draft flow."
            )
        return agent

    def _reload_order(self, pk, company):
        return (
            Order.objects.select_related(
                "customer", "agent__user", "approved_by", "company"
            )
            .prefetch_related("items", "status_history", "signature", "invoices")
            .get(pk=pk, company=company)
        )

    def _flow_error(self, exc):
        return Response(
            {"detail": exc.message, "code": exc.code, "fields": exc.fields},
            status=exc.status_code,
        )

    def _agent_draft(self, request):
        self._get_agent(request)
        company = self._get_company(request)
        order_flow.expire_draft_orders(
            company=company, agent=request.user.agent_profile
        )
        return company, request.user.agent_profile

    def drafts(self, request):
        """GET /api/orders/drafts/ — current agent's resumable drafts."""
        company, agent = self._agent_draft(request)
        queryset = order_flow.list_draft_orders(company, agent)
        return Response(OrderDetailSerializer(queryset, many=True).data)

    @transaction.atomic
    def add_item(self, request, pk=None):
        """POST /api/orders/<pk>/items/ — add a scanned size range to a draft."""
        company = self._get_company(request)
        agent = self._get_agent(request)
        order = order_flow.get_agent_order(pk, company, agent)
        serializer = OrderAddItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order, group_id, stock_updates, created = order_flow.add_item_to_draft(
                order, request.user, serializer.validated_data
            )
        except OrderFlowError as exc:
            return self._flow_error(exc)

        order = self._reload_order(order.pk, company)
        broadcast_order_updated(order)
        if created:
            broadcast_stock_updates(company.id, stock_updates)
        return Response(
            {
                "order": OrderDetailSerializer(order).data,
                "group_id": str(group_id),
                "stock_updates": stock_updates,
                "created": created,
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @transaction.atomic
    def remove_item(self, request, pk=None, item_id=None):
        """DELETE /api/orders/<pk>/items/<item_id>/ — remove a scan group."""
        company = self._get_company(request)
        agent = self._get_agent(request)
        order = order_flow.get_agent_order(pk, company, agent)
        scope = request.query_params.get("scope", "group")
        try:
            order, stock_updates = order_flow.remove_item_from_draft(
                order, request.user, item_id, scope=scope
            )
        except OrderFlowError as exc:
            return self._flow_error(exc)

        if not Order.objects.filter(pk=order.pk, company=company).exists():
            broadcast_order_updated(order)
            broadcast_stock_updates(company.id, stock_updates)
            return Response(
                {
                    "order": OrderDetailSerializer(order).data,
                    "stock_updates": stock_updates,
                },
                status=status.HTTP_200_OK,
            )
        order = self._reload_order(order.pk, company)
        broadcast_order_updated(order)
        broadcast_stock_updates(company.id, stock_updates)
        return Response(
            {
                "order": OrderDetailSerializer(order).data,
                "stock_updates": stock_updates,
            }
        )

    def continue_order(self, request, pk=None):
        """GET /api/orders/<pk>/continue/ — resume an unexpired draft."""
        company = self._get_company(request)
        agent = self._get_agent(request)
        order = order_flow.get_agent_order(pk, company, agent)
        try:
            order_flow.assert_draft_available(order)
        except OrderFlowError as exc:
            return self._flow_error(exc)
        order = self._reload_order(order.pk, company)
        return Response(OrderDetailSerializer(order).data)

    @transaction.atomic
    def update_item(self, request, pk=None, item_id=None):
        """PATCH /api/orders/<pk>/items/<item_id>/ — change group quantity."""
        company = self._get_company(request)
        agent = self._get_agent(request)
        order = order_flow.get_agent_order(pk, company, agent)
        serializer = OrderUpdateItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order, stock_updates = order_flow.update_item_quantity(
                order, request.user, item_id, serializer.validated_data["quantity"]
            )
        except OrderFlowError as exc:
            return self._flow_error(exc)

        order = self._reload_order(order.pk, company)
        broadcast_order_updated(order)
        broadcast_stock_updates(company.id, stock_updates)
        return Response(
            {
                "order": OrderDetailSerializer(order).data,
                "stock_updates": stock_updates,
            }
        )

    @transaction.atomic
    def partial_update(self, request, pk=None):
        """PATCH /api/orders/<pk>/ — update draft delivery/notes/discount."""
        company = self._get_company(request)
        agent = self._get_agent(request)
        order = order_flow.get_agent_order(pk, company, agent)
        if order.status != OrderStatus.DRAFT:
            return Response(
                {"detail": "Only DRAFT orders can be updated."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = OrderDraftUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(order, field, value)
        order.save()
        order_flow.recalculate_order_totals(order)
        order_flow.refresh_draft_expiry(order)
        order.save(update_fields=["draft_expires_at", "updated_at"])
        order = self._reload_order(order.pk, company)
        broadcast_order_updated(order)
        return Response(OrderDetailSerializer(order).data)

    @transaction.atomic
    def discard(self, request, pk=None):
        """DELETE /api/orders/<pk>/ — discard a draft and release stock."""
        company = self._get_company(request)
        agent = self._get_agent(request)
        order = order_flow.get_agent_order(pk, company, agent)
        try:
            order_id, agent_id = order_flow.discard_draft(order, request.user)
        except OrderFlowError as exc:
            return self._flow_error(exc)
        broadcast_order_expired(order_id, agent_id, company.id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @transaction.atomic
    def submit(self, request, pk=None):
        """POST /api/orders/<pk>/submit/ — convert a DRAFT into a real order."""
        company = self._get_company(request)
        agent = self._get_agent(request)
        order = order_flow.get_agent_order(pk, company, agent)
        serializer = OrderSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            order = order_flow.submit_draft(
                order, request.user, serializer.validated_data
            )
        except OrderFlowError as exc:
            return self._flow_error(exc)
        order = self._reload_order(order.pk, company)
        broadcast_order_updated(order)
        return Response(OrderDetailSerializer(order).data)

    def _create_order(self, company, request, payload):
        """Legacy helper retained for the offline sync path.

        Creates a draft, adds each item and submits it in one transaction.
        Returns ``(order, error_response)``.
        """
        items = payload.get("items") or []
        order_payload = {
            key: value for key, value in payload.items() if key != "items"
        }
        agent = getattr(request.user, "agent_profile", None)
        try:
            with transaction.atomic():
                order = order_flow.create_draft_order(
                    company, agent, request.user, order_payload
                )
                for item in items:
                    order_flow.add_item_to_draft(order, request.user, item)
                order = order_flow.submit_draft(order, request.user, order_payload)
            return order, None
        except OrderFlowError as exc:
            return None, self._flow_error(exc)

    # ─────────────────────────────────────────────────────────────
    # UPDATE STATUS
    # POST /api/orders/<pk>/status/
    # ─────────────────────────────────────────────────────────────

    @transaction.atomic
    def update_status(self, request, pk=None):
        company = self._get_company(request)
        order = self._get_order(pk, company)
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = OrderStatusUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data["status"]
        notes = serializer.validated_data.get("notes", "")

        old_status = order.status
        order.status = new_status

        timestamp_map = {
            OrderStatus.CONFIRMED: "confirmed_at",
            OrderStatus.DISPATCHED: "dispatched_at",
            OrderStatus.DELIVERED: "delivered_at",
            OrderStatus.CANCELLED: "cancelled_at",
        }
        if new_status in timestamp_map:
            setattr(order, timestamp_map[new_status], now())

        order.save()
        self._log_status_change(order, old_status, new_status, request.user, notes)

        # Release reserved stock on cancellation
        if new_status == OrderStatus.CANCELLED:
            for item in order.items.all():
                VariantSize.objects.filter(pk=item.variant_size_id).update(
                    reserved_qty=Greatest(
                        F("reserved_qty") - item.quantity, Value(0)
                    )
                )
                item.variant_size.refresh_from_db(
                    fields=["stock_quantity", "reserved_qty"]
                )
                StockMovement.objects.create(
                    variant_size=item.variant_size,
                    movement_type=StockMovement.MovementType.RELEASE,
                    quantity=item.quantity,
                    balance_after=item.variant_size.available_qty,
                    reference_type="order",
                    reference_id=order.id,
                    performed_by=request.user,
                )
            event = "order_cancelled"
        elif new_status == OrderStatus.CONFIRMED:
            event = "order_confirmed"
        elif new_status == OrderStatus.DISPATCHED:
            event = "order_dispatched"
            # Direct status update bypasses the dispatch app: generate the
            # sales invoice + commission so the ledger stays consistent.
            from apps.orders.services import (
                create_commission_entry,
                generate_sales_invoice,
            )

            generate_sales_invoice(company, order)
            if order.agent:
                create_commission_entry(company, order, performed_by=request.user)
        elif new_status == OrderStatus.DELIVERED:
            event = "order_delivered"
        else:
            event = None

        if event and order.customer.user:
            send_order_notification(company, order, event, order.customer.user)

        return Response(OrderDetailSerializer(order).data)

    # ─────────────────────────────────────────────────────────────
    # APPROVAL
    # POST /api/orders/<pk>/approve/
    # ─────────────────────────────────────────────────────────────

    @transaction.atomic
    def approve(self, request, pk=None):
        company = self._get_company(request)
        order = self._get_order(pk, company)
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if not order.requires_approval:
            return Response(
                {"detail": "This order does not require approval."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if order.status != OrderStatus.SUBMITTED:
            return Response(
                {"detail": "Only submitted orders can be approved or rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = OrderApprovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action_val = serializer.validated_data["action"]

        if action_val == "approve":
            old_status = order.status
            order.status = OrderStatus.CONFIRMED
            order.approved_by = request.user
            order.approved_at = now()
            order.confirmed_at = now()
            order.save(
                update_fields=["status", "approved_by", "approved_at", "confirmed_at"]
            )
            self._log_status_change(
                order, old_status, OrderStatus.CONFIRMED, request.user, "Approved"
            )
        else:
            old_status = order.status
            order.status = OrderStatus.CANCELLED
            order.rejection_reason = serializer.validated_data["rejection_reason"]
            order.cancelled_at = now()
            order.save(update_fields=["status", "rejection_reason", "cancelled_at"])
            self._log_status_change(
                order,
                old_status,
                OrderStatus.CANCELLED,
                request.user,
                f"Rejected: {order.rejection_reason}",
            )
            # Release reserved stock
            for item in order.items.all():
                VariantSize.objects.filter(pk=item.variant_size_id).update(
                    reserved_qty=Greatest(
                        F("reserved_qty") - item.quantity, Value(0)
                    )
                )
                item.variant_size.refresh_from_db(
                    fields=["stock_quantity", "reserved_qty"]
                )
                StockMovement.objects.create(
                    variant_size=item.variant_size,
                    movement_type=StockMovement.MovementType.RELEASE,
                    quantity=item.quantity,
                    balance_after=item.variant_size.available_qty,
                    reference_type="order",
                    reference_id=order.id,
                    performed_by=request.user,
                )
            if order.customer.user:
                send_order_notification(
                    company, order, "order_cancelled", order.customer.user
                )
            return Response(OrderDetailSerializer(order).data)

        if order.customer.user:
            send_order_notification(
                company, order, "order_confirmed", order.customer.user
            )

        return Response(OrderDetailSerializer(order).data)

    # ─────────────────────────────────────────────────────────────
    # CANCEL
    # POST /api/orders/<pk>/cancel/
    # ─────────────────────────────────────────────────────────────

    @transaction.atomic
    def cancel(self, request, pk=None):
        company = self._get_company(request)
        order = self._get_order(pk, company)
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if order.status == OrderStatus.DRAFT:
            return Response(
                {"detail": "Use DELETE /api/orders/<id>/ to discard a draft."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        non_cancellable = [
            OrderStatus.DISPATCHED,
            OrderStatus.DELIVERED,
            OrderStatus.CANCELLED,
        ]
        if order.status in non_cancellable:
            return Response(
                {"detail": f"Cannot cancel an order with status '{order.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Agents can only cancel their own draft/submitted orders
        if request.user.role == "agent":
            if order.agent != request.user.agent_profile:
                return Response(
                    {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
                )
            if order.status not in [OrderStatus.SUBMITTED]:
                return Response(
                    {"detail": "Agents can only cancel submitted orders."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        serializer = OrderCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        old_status = order.status
        order.status = OrderStatus.CANCELLED
        order.cancelled_at = now()
        order.internal_notes = serializer.validated_data["reason"]
        order.save(update_fields=["status", "cancelled_at", "internal_notes"])

        self._log_status_change(
            order,
            old_status,
            OrderStatus.CANCELLED,
            request.user,
            serializer.validated_data["reason"],
        )

        # Release reserved stock
        for item in order.items.all():
            VariantSize.objects.filter(pk=item.variant_size_id).update(
                reserved_qty=Greatest(F("reserved_qty") - item.quantity, Value(0))
            )
            item.variant_size.refresh_from_db(
                fields=["stock_quantity", "reserved_qty"]
            )
            StockMovement.objects.create(
                variant_size=item.variant_size,
                movement_type=StockMovement.MovementType.RELEASE,
                quantity=item.quantity,
                balance_after=item.variant_size.available_qty,
                reference_type="order",
                reference_id=order.id,
                performed_by=request.user,
            )

        if order.customer.user:
            send_order_notification(
                company, order, "order_cancelled", order.customer.user
            )

        return Response(OrderDetailSerializer(order).data)

    # ─────────────────────────────────────────────────────────────
    # PACKING — record packed quantities per item
    # POST /api/orders/<pk>/pack-items/
    # ─────────────────────────────────────────────────────────────
    @transaction.atomic
    def pack_items(self, request, pk=None):
        company = self._get_company(request)
        order = self._get_order(pk, company)
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        if order.status in (
            OrderStatus.DISPATCHED,
            OrderStatus.DELIVERED,
            OrderStatus.CANCELLED,
        ):
            return Response(
                {
                    "detail": (
                        f"Packing cannot be updated for an order with status "
                        f"'{order.status}'."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = PackItemsSerializer(data=request.data, context={"order": order})
        serializer.is_valid(raise_exception=True)
        resolved = serializer.validated_data["_resolved_items"]
        notes = serializer.validated_data.get("notes", "")

        previous_packing_status = order.packing_status
        changes = []
        for item, packed_qty in resolved:
            if item.packed_quantity != packed_qty:
                changes.append(f"{item.sku}: {item.packed_quantity}→{packed_qty}")
            item.packed_quantity = packed_qty
            item.save(update_fields=["packed_quantity", "updated_at"])

        order.refresh_from_db()
        new_packing_status = order.packing_status

        # Auto-advance the order status based on the derived packing state.
        # PROGRESS_STATUS_TRANSITIONS:
        #   - PARTIALLY_PACKED -> PROCESSING (order moved to the packing stage)
        #   - PACKED          -> PACKED (final pre-dispatch state; sticky once set)
        # The order only advances forward from CONFIRMED/PROCESSING; once PACKED
        # it is never downgraded even if packed quantities are later reduced.
        if order.status in (OrderStatus.CONFIRMED, OrderStatus.PROCESSING):
            if (
                order.status == OrderStatus.CONFIRMED
                and new_packing_status == PackingStatus.PARTIALLY_PACKED
            ):
                self._advance_status(order, OrderStatus.PROCESSING, request.user, notes)
                order.refresh_from_db()
            if (
                order.status in (OrderStatus.CONFIRMED, OrderStatus.PROCESSING)
                and new_packing_status == PackingStatus.PACKED
            ):
                self._advance_status(order, OrderStatus.PACKED, request.user, notes)

        if changes:
            self._log_status_change(
                order,
                previous_packing_status,
                new_packing_status,
                request.user,
                notes or f"Packing update: {'; '.join(changes)}",
            )

        return Response(OrderDetailSerializer(order).data)

    # ─────────────────────────────────────────────────────────────
    # KANBAN BOARD
    # GET /api/orders/kanban/
    # ─────────────────────────────────────────────────────────────

    def kanban(self, request):
        company = self._get_company(request)
        result = {}
        kanban_statuses = [
            OrderStatus.SUBMITTED,
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
            OrderStatus.PACKED,
        ]
        for s in kanban_statuses:
            qs = (
                Order.objects.filter(company=company, status=s)
                .select_related("customer", "agent__user")
                .prefetch_related("items")
                .order_by("created_at")
            )
            qs = scope_order_queryset(request.user, qs)
            result[s] = OrderListSerializer(qs, many=True).data

        return Response(result)

    # ─────────────────────────────────────────────────────────────
    # OFFLINE SYNC
    # POST /api/orders/sync/
    # ─────────────────────────────────────────────────────────────
    @transaction.atomic
    def sync_offline(self, request):
        """
        Agent mobile app bulk-syncs orders created offline.
        Each payload is persisted independently inside its own savepoint so a
        single failure doesn't roll back the rest of the batch.
        """
        company = self._get_company(request)
        orders_data = request.data.get("orders", [])
        if not isinstance(orders_data, list):
            return Response(
                {"detail": "'orders' must be a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        synced, failed = [], []
        for order_data in orders_data:
            offline_ref = order_data.get("offline_ref")
            try:
                with transaction.atomic():
                    _, error_response = self._create_order(
                        company, request, {**order_data, "is_offline_order": True}
                    )
                if error_response is not None:
                    failed.append(
                        {
                            "offline_ref": offline_ref,
                            "error": str(error_response.data),
                        }
                    )
                else:
                    synced.append(offline_ref)
            except Exception as e:  # noqa: BLE001 - isolate each offline item
                failed.append({"offline_ref": offline_ref, "error": str(e)})

        return Response({"synced": synced, "failed": failed})

    # ─────────────────────────────────────────────────────────────
    # SIGNATURE CAPTURE
    # POST /api/orders/<pk>/signature/
    # ─────────────────────────────────────────────────────────────
    @transaction.atomic
    def capture_signature(self, request, pk=None):
        company = self._get_company(request)
        order = self._get_order(pk, company)
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        # hasattr() on a reverse OneToOneField descriptor always returns True;
        # use try/except to correctly detect an existing signature.
        try:
            _ = order.signature
            return Response(
                {"detail": "Signature already captured for this order."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except OrderSignature.DoesNotExist:
            pass
        serializer = OrderSignatureSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sig = serializer.save(order=order, captured_by=request.user)
        return Response(
            OrderSignatureSerializer(sig).data, status=status.HTTP_201_CREATED
        )
