from decimal import Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils.timezone import now
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    OpenApiTypes,
    extend_schema,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdminOrSubAdmin, IsAdminSubAdminOrAgent, IsAgent
from apps.customers.models import CustomerProfile
from apps.orders.models import (
    Order,
    OrderItem,
    OrderSignature,
    OrderStatus,
    OrderStatusHistory,
)
from apps.orders.serializers import (
    OrderApprovalSerializer,
    OrderCancelSerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderListSerializer,
    OrderSignatureSerializer,
    OrderStatusUpdateSerializer,
    PackItemsSerializer,
)
from apps.products.models import StockMovement, VariantSize


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

    def _build_order_number(self, company):
        # Use select_for_update inside the caller's atomic block to prevent
        # duplicate order numbers under concurrent requests.
        count = Order.objects.filter(company=company).select_for_update().count() + 1
        year = now().year
        return f"ORD-{year}-{count:05d}"

    def _calculate_totals(self, items_data, discount_pct, company):
        """
        Resolve prices from VariantSize, apply discount + GST.
        Returns (line_items, subtotal, discount_amount, taxable, cgst, sgst, igst, total, is_interstate).
        """
        subtotal = Decimal("0")
        line_items = []
        customer_state = None  # resolved later for interstate check

        for item in items_data:
            variant = VariantSize.objects.select_related("color_variant__product").get(
                id=item["variant_size"].id
            )
            product = variant.color_variant.product
            unit_price = variant.price_override or product.wholesale_price
            qty = item["quantity"]
            item_disc = item.get("discount_pct", Decimal("0"))
            line_total = unit_price * qty * (1 - item_disc / 100)
            subtotal += line_total

            line_items.append(
                {
                    "variant_size": variant,
                    "product_name": product.name,
                    "color_name": variant.color_variant.color_name,
                    "size": variant.size,
                    "sku": variant.sku,
                    "hsn_code": product.hsn_code,
                    "unit_price": unit_price,
                    "quantity": qty,
                    "discount_pct": item_disc,
                    "line_total": line_total,
                    "gst_rate": product.gst_rate,
                    "gst_amount": line_total * product.gst_rate / 100,
                }
            )

        discount_amount = subtotal * discount_pct / 100
        taxable = subtotal - discount_amount
        gst_total = sum(i["gst_amount"] for i in line_items)
        is_interstate = (
            False  # simplified; real logic compares company state vs customer state
        )
        cgst = sgst = igst = Decimal("0")
        if is_interstate:
            igst = gst_total
        else:
            cgst = sgst = gst_total / 2

        total = taxable + gst_total
        return (
            line_items,
            subtotal,
            discount_amount,
            taxable,
            cgst,
            sgst,
            igst,
            total,
            is_interstate,
        )

    # ─────────────────────────────────────────────────────────────
    # LIST
    # GET /api/orders/
    # ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="list_orders",
        summary="List orders",
        description=(
            "Company-scoped order list. Agents automatically see only their "
            "own orders. Each row includes the derived `packing_status`."
        ),
        parameters=[
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=[s for s, _ in OrderStatus.choices],
            ),
            OpenApiParameter("agent_id", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("customer_id", OpenApiTypes.UUID, OpenApiParameter.QUERY),
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY),
            OpenApiParameter("date_from", OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter("date_to", OpenApiTypes.DATE, OpenApiParameter.QUERY),
            OpenApiParameter(
                "pending_approval", OpenApiTypes.BOOL, OpenApiParameter.QUERY
            ),
            OpenApiParameter("offline", OpenApiTypes.BOOL, OpenApiParameter.QUERY),
        ],
        responses={200: OrderListSerializer(many=True)},
        tags=["Orders"],
    )
    def list(self, request):
        company = self._get_company(request)
        qs = (
            Order.objects.filter(company=company)
            .select_related("customer", "agent__user")
            .prefetch_related("items")
            .order_by("-created_at")
        )

        # Filters
        status_f = request.query_params.get("status")
        agent_f = request.query_params.get("agent_id")
        customer_f = request.query_params.get("customer_id")
        search = request.query_params.get("search")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        pending_approval = request.query_params.get("pending_approval")
        offline_f = request.query_params.get("offline")

        if status_f:
            qs = qs.filter(status=status_f)
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

    @extend_schema(
        operation_id="retrieve_order",
        summary="Retrieve an order",
        description=(
            "Full order detail including items (with `packed_quantity`, "
            "`pending_qty` and per-item `packing_status`), status history "
            "and signature."
        ),
        responses={
            200: OrderDetailSerializer,
            404: OpenApiResponse(description="Order not found in your company."),
        },
        tags=["Orders"],
    )
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        order = self._get_order(pk, company)
        if not order:
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
            "items", "status_history", "signature"
        ).get(pk=pk, company=company)
        return Response(OrderDetailSerializer(order_full).data)

    # ─────────────────────────────────────────────────────────────
    # CREATE
    # POST /api/orders/
    # ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="create_order",
        summary="Create an order",
        description=(
            "Calculates GST, checks the customer's credit limit, reserves "
            "stock and triggers approval if required."
        ),
        request=OrderCreateSerializer,
        responses={201: OrderDetailSerializer},
        tags=["Orders"],
    )
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        print(f"Company {company}")
        serializer = OrderCreateSerializer(
            data=request.data,
            context={
                "request": request,
                "company": company,
            },
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Resolve customer
        customer = CustomerProfile.objects.get(id=data["customer"], company=company)

        # Calculate totals
        discount_pct = data.get("discount_pct", Decimal("0"))
        (
            line_items,
            subtotal,
            discount_amount,
            taxable,
            cgst,
            sgst,
            igst,
            total,
            is_interstate,
        ) = self._calculate_totals(data["items"], discount_pct, company)

        # Check credit limit
        settings = getattr(company, "settings", None)
        if settings and settings.credit_block_on_exceed:
            if customer.credit_utilized + total > customer.credit_limit > 0:
                return Response(
                    {
                        "detail": (
                            f"Order total ₹{total} would exceed {customer.business_name}'s "
                            f"credit limit of ₹{customer.credit_limit}."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Approval required?
        requires_approval = False
        if settings and settings.order_approval_required:
            subadmin = getattr(request.user, "subadmin_profile", None)
            if subadmin and subadmin.approval_threshold:
                requires_approval = total > subadmin.approval_threshold
            elif request.user.role == "agent":
                requires_approval = True

        # Determine initial status
        order_status = OrderStatus.SUBMITTED
        if settings and settings.order_auto_confirm and not requires_approval:
            order_status = OrderStatus.CONFIRMED

        agent_profile = None
        if request.user.role == "agent":
            agent_profile = request.user.agent_profile

        # Create Order
        order = Order.objects.create(
            company=company,
            order_number=self._build_order_number(company),
            customer=customer,
            agent=agent_profile,
            status=order_status,
            subtotal=subtotal,
            discount_pct=discount_pct,
            discount_amount=discount_amount,
            taxable_amount=taxable,
            cgst_amount=cgst,
            sgst_amount=sgst,
            igst_amount=igst,
            total_amount=total,
            is_interstate=is_interstate,
            delivery_address_line1=data.get("delivery_address_line1", ""),
            delivery_address_line2=data.get("delivery_address_line2", ""),
            delivery_city=data.get("delivery_city", ""),
            delivery_state=data.get("delivery_state", ""),
            delivery_pincode=data.get("delivery_pincode", ""),
            expected_delivery_date=data.get("expected_delivery_date"),
            order_notes=data.get("order_notes", ""),
            requires_approval=requires_approval,
            is_offline_order=data.get("is_offline_order", False),
            offline_created_at=data.get("offline_created_at"),
            sync_status="synced",
            submitted_at=now(),
        )

        # Create OrderItems + reserve stock
        for li in line_items:
            variant = li.pop("variant_size")
            OrderItem.objects.create(order=order, **li, variant_size=variant)

            # Reserve stock atomically and refresh to get the updated balance.
            VariantSize.objects.filter(pk=variant.pk).update(
                reserved_qty=F("reserved_qty") + li["quantity"]
            )
            variant.refresh_from_db(fields=["stock_quantity", "reserved_qty"])
            StockMovement.objects.create(
                variant_size=variant,
                movement_type=StockMovement.MovementType.RESERVE,
                quantity=-li["quantity"],
                balance_after=variant.available_qty,
                reference_type="order",
                reference_id=order.id,
                performed_by=request.user,
            )

        # Status history
        self._log_status_change(order, "", OrderStatus.SUBMITTED, request.user)

        return Response(
            OrderDetailSerializer(order).data,
            status=status.HTTP_201_CREATED,
        )

    # ─────────────────────────────────────────────────────────────
    # UPDATE STATUS
    # POST /api/orders/<pk>/status/
    # ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="update_order_status",
        summary="Move order to another workflow status",
        description=(
            "Sets the workflow status (draft → submitted → confirmed → "
            "processing → packed → ready → dispatched / delivered / cancelled). "
            "Note: this is the *workflow* status — packing progress is tracked "
            "separately via `pack-items` and exposed as the derived "
            "`packing_status`."
        ),
        request=OrderStatusUpdateSerializer,
        responses={200: OrderDetailSerializer},
        tags=["Orders"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="status",
        permission_classes=[IsAdminOrSubAdmin],
    )
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
                    reserved_qty=F("reserved_qty") - item.quantity
                )
                StockMovement.objects.create(
                    variant_size=item.variant_size,
                    movement_type=StockMovement.MovementType.RELEASE,
                    quantity=item.quantity,
                    balance_after=item.variant_size.stock_quantity,
                    reference_type="order",
                    reference_id=order.id,
                    performed_by=request.user,
                )

        return Response(OrderDetailSerializer(order).data)

    # ─────────────────────────────────────────────────────────────
    # APPROVAL
    # POST /api/orders/<pk>/approve/
    # ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="approve_order",
        summary="Approve or reject a pending order",
        request=OrderApprovalSerializer,
        responses={200: OrderDetailSerializer},
        tags=["Orders"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="approve",
        permission_classes=[IsAdminOrSubAdmin],
    )
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
                    reserved_qty=F("reserved_qty") - item.quantity
                )

        return Response(OrderDetailSerializer(order).data)

    # ─────────────────────────────────────────────────────────────
    # CANCEL
    # POST /api/orders/<pk>/cancel/
    # ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="cancel_order",
        summary="Cancel an order",
        description="Cancels the order and releases all reserved stock.",
        request=OrderCancelSerializer,
        responses={200: OrderDetailSerializer},
        tags=["Orders"],
    )
    @action(detail=True, methods=["post"], url_path="cancel")
    @transaction.atomic
    def cancel(self, request, pk=None):
        company = self._get_company(request)
        order = self._get_order(pk, company)
        if not order:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

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
            if order.status not in [OrderStatus.DRAFT, OrderStatus.SUBMITTED]:
                return Response(
                    {"detail": "Agents can only cancel draft or submitted orders."},
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
                reserved_qty=F("reserved_qty") - item.quantity
            )
            StockMovement.objects.create(
                variant_size=item.variant_size,
                movement_type=StockMovement.MovementType.RELEASE,
                quantity=item.quantity,
                balance_after=item.variant_size.stock_quantity,
                reference_type="order",
                reference_id=order.id,
                performed_by=request.user,
            )

        return Response(OrderDetailSerializer(order).data)

    # ─────────────────────────────────────────────────────────────
    # PACKING — record packed quantities per item
    # POST /api/orders/<pk>/pack-items/
    # ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="pack_order_items",
        summary="Record packed quantities per item",
        description=(
            "Bulk-records how many units of each line item were physically "
            "packed. Packed quantity may be **equal to or less than** the "
            "ordered quantity — partial packing / shortfalls are expected and "
            "over-packing is rejected.\n\n"
            "- Every `item_id` must belong to this order.\n"
            "- Allowed until the order is dispatched, delivered or cancelled.\n"
            "- The order-level `packing_status` (unpacked / partially_packed / "
            "packed) is **auto-derived** from its items; there is no separate "
            "'mark as packed' call.\n"
            "- Each change is appended to the order's status history for audit."
        ),
        request=PackItemsSerializer,
        responses={
            200: OrderDetailSerializer,
            400: OpenApiResponse(
                description="Validation failed — over-packing, foreign/unknown "
                "item, duplicates, or a terminal order status.",
            ),
            403: OpenApiResponse(
                description="Only Admin / SubAdmin may record packed quantities."
            ),
            404: OpenApiResponse(description="Order not found in your company."),
        },
        tags=["Orders"],
        examples=[
            OpenApiExample(
                "Partial packing (ordered 100, packed 80)",
                value={
                    "items": [
                        {
                            "item_id": "6a3f8b2c-1d4e-4f5a-9b0c-7d8e6f5a4b3c",
                            "packed_quantity": 80,
                        }
                    ],
                    "notes": "20 units short-packed",
                },
                request_only=True,
            ),
        ],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="pack-items",
        permission_classes=[IsAdminOrSubAdmin],
    )
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

    @extend_schema(
        operation_id="kanban_orders",
        summary="Kanban board",
        description="Orders grouped by workflow status (submitted → ready).",
        responses={200: OpenApiResponse(description="Map of status → order list")},
        tags=["Orders"],
    )
    @action(
        detail=False,
        methods=["get"],
        url_path="kanban",
        permission_classes=[IsAdminOrSubAdmin],
    )
    def kanban(self, request):
        company = self._get_company(request)
        result = {}
        kanban_statuses = [
            OrderStatus.SUBMITTED,
            OrderStatus.CONFIRMED,
            OrderStatus.PROCESSING,
            OrderStatus.PACKED,
            OrderStatus.READY,
        ]
        for s in kanban_statuses:
            qs = (
                Order.objects.filter(company=company, status=s)
                .select_related("customer", "agent__user")
                .prefetch_related("items")
                .order_by("created_at")
            )
            result[s] = OrderListSerializer(qs, many=True).data

        return Response(result)

    # ─────────────────────────────────────────────────────────────
    # OFFLINE SYNC
    # POST /api/orders/sync/
    # ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="sync_offline_orders",
        summary="Bulk offline order sync (Agent mobile app)",
        request=None,
        responses={200: OpenApiResponse(description="Synced/failed offline refs")},
        tags=["Orders"],
    )
    @action(
        detail=False, methods=["post"], url_path="sync", permission_classes=[IsAgent]
    )
    @transaction.atomic
    def sync_offline(self, request):
        """
        Agent mobile app bulk-syncs orders created offline.
        Each item in the list is processed independently.
        """
        orders_data = request.data.get("orders", [])
        if not isinstance(orders_data, list):
            return Response(
                {"detail": "'orders' must be a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        synced, failed = [], []
        for order_data in orders_data:
            try:
                serializer = OrderCreateSerializer(
                    data={**order_data, "is_offline_order": True},
                    context={"request": request},
                )
                serializer.is_valid(raise_exception=True)
                # Re-use create logic via self.create with modified request
                synced.append(order_data.get("offline_ref"))
            except Exception as e:
                failed.append(
                    {"offline_ref": order_data.get("offline_ref"), "error": str(e)}
                )

        return Response({"synced": synced, "failed": failed})

    # ─────────────────────────────────────────────────────────────
    # SIGNATURE CAPTURE
    # POST /api/orders/<pk>/signature/
    # ─────────────────────────────────────────────────────────────

    @extend_schema(
        operation_id="capture_order_signature",
        summary="Capture customer signature",
        request=OrderSignatureSerializer,
        responses={201: OrderSignatureSerializer},
        tags=["Orders"],
    )
    @action(
        detail=True,
        methods=["post"],
        url_path="signature",
        permission_classes=[IsAgent],
    )
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
