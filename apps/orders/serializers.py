from typing import ClassVar

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.agents.serializers import AgentUserSerializer
from apps.customers.serializers import CustomerSerializer
from apps.orders.models import (
    Order,
    OrderItem,
    OrderSignature,
    OrderStatus,
    OrderStatusHistory,
    PackingStatus,
)
from apps.products.serializers import SizeChartSerializer, VariantSizeSerializer


class OrderStatusHistorySerializer(serializers.ModelSerializer):
    changed_by_name = serializers.CharField(
        source="changed_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = OrderStatusHistory
        fields: ClassVar = [
            "id",
            "from_status",
            "to_status",
            "changed_by_name",
            "notes",
            "created_at",
        ]


class OrderSignatureSerializer(serializers.ModelSerializer):
    captured_by_name = serializers.CharField(
        source="captured_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = OrderSignature
        fields: ClassVar = [
            "id",
            "signature_image",
            "captured_at",
            "captured_by_name",
        ]


class OrderItemSerializer(serializers.ModelSerializer):
    variant_details = VariantSizeSerializer(source="variant_size", read_only=True)
    size_chart = SizeChartSerializer(
        source="variant_size.color_variant.product.size_chart",
        read_only=True,
        default=None,
    )
    pending_qty = serializers.IntegerField(
        read_only=True,
        help_text="Ordered quantity minus packed quantity.",
    )
    packing_status = serializers.ChoiceField(
        choices=PackingStatus.choices,
        read_only=True,
        help_text="Derived: unpacked | partially_packed | packed.",
    )

    class Meta:
        model = OrderItem
        fields: ClassVar = [
            "id",
            "group_id",
            "size_range",
            "variant_size",
            "variant_details",
            "size_chart",
            "product_name",
            "color_name",
            "size",
            "sku",
            "hsn_code",
            "unit_price",
            "quantity",
            "packed_quantity",
            "pending_qty",
            "packing_status",
            "discount_pct",
            "line_total",
            "gst_rate",
            "gst_amount",
        ]


class OrderItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields: ClassVar = [
            "variant_size",
            "quantity",
            "discount_pct",
        ]

    def validate_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError("Quantity must be at least 1.")
        return value

    def validate(self, attrs):
        variant = attrs["variant_size"]
        qty = attrs["quantity"]
        if variant.available_qty < qty:
            raise serializers.ValidationError(
                {
                    "quantity": (
                        f"Only {variant.available_qty} units available for "
                        f"{variant.color_variant.product.name} "
                        f"{variant.color_variant.color_name} {variant.size}."
                    )
                }
            )
        return attrs


class PackingStatusMixin(serializers.Serializer):
    packing_status = serializers.ChoiceField(
        choices=PackingStatus.choices,
        read_only=True,
        help_text=(
            "Order-level packing state, auto-derived from its items: "
            "unpacked | partially_packed | packed."
        ),
    )


class DraftExpiryMixin(serializers.Serializer):
    seconds_until_expiry = serializers.SerializerMethodField()

    @extend_schema_field(serializers.IntegerField(allow_null=True))
    def get_seconds_until_expiry(self, obj):
        from django.utils.timezone import now

        if not obj.draft_expires_at:
            return None
        return max(0, int((obj.draft_expires_at - now()).total_seconds()))


class OrderListSerializer(
    DraftExpiryMixin, PackingStatusMixin, serializers.ModelSerializer
):
    customer_name = serializers.CharField(source="customer.legal_name", read_only=True)
    agent_name = serializers.CharField(
        source="agent.user.full_name", read_only=True, default=None
    )
    item_count = serializers.SerializerMethodField()
    invoices = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields: ClassVar = [
            "id",
            "order_number",
            "customer",
            "customer_name",
            "agent",
            "agent_name",
            "status",
            "packing_status",
            "total_amount",
            "item_count",
            "invoices",
            "is_offline_order",
            "sync_status",
            "requires_approval",
            "draft_expires_at",
            "seconds_until_expiry",
            "submitted_at",
            "created_at",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_item_count(self, obj):
        return obj.items.count()

    def get_invoices(self, obj):
        return list(obj.invoices.values("id", "invoice_type"))


class OrderDetailSerializer(
    DraftExpiryMixin, PackingStatusMixin, serializers.ModelSerializer
):
    customer_details = CustomerSerializer(source="customer", read_only=True)

    agent_details = AgentUserSerializer(source="agent.user", read_only=True)
    approved_by_name = serializers.CharField(
        source="approved_by.full_name", read_only=True, default=None
    )
    items = OrderItemSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)
    signature = OrderSignatureSerializer(read_only=True)
    invoices = serializers.SerializerMethodField()

    def get_invoices(self, obj):
        return list(obj.invoices.values("id", "invoice_type"))

    class Meta:
        model = Order
        fields: ClassVar = [
            "id",
            "order_number",
            "customer",
            "customer_details",
            "agent",
            "agent_details",
            "status",
            "packing_status",
            "draft_expires_at",
            "seconds_until_expiry",
            # Pricing breakdown
            "subtotal",
            "discount_pct",
            "discount_amount",
            "taxable_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_amount",
            "is_interstate",
            # Delivery
            "delivery_address_line1",
            "delivery_address_line2",
            "delivery_city",
            "delivery_state",
            "delivery_pincode",
            "expected_delivery_date",
            # Notes
            "order_notes",
            "internal_notes",
            # Approval
            "requires_approval",
            "approved_by_name",
            "approved_at",
            "rejection_reason",
            # Offline
            "is_offline_order",
            "offline_created_at",
            "sync_status",
            # Tally
            "tally_invoice_id",
            "tally_synced_at",
            # Timestamps
            "submitted_at",
            "dispatched_at",
            "delivered_at",
            "cancelled_at",
            "created_at",
            "updated_at",
            # Nested
            "items",
            "status_history",
            "signature",
            "invoices",
        ]


class OrderCreateSerializer(serializers.Serializer):
    customer = serializers.UUIDField()
    items = OrderItemCreateSerializer(many=True, min_length=1)
    discount_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=0, min_value=0, max_value=100
    )
    delivery_address_line1 = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    delivery_address_line2 = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    delivery_city = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    delivery_state = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    delivery_pincode = serializers.CharField(
        max_length=10, required=False, allow_blank=True
    )
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    order_notes = serializers.CharField(required=False, allow_blank=True)
    is_offline_order = serializers.BooleanField(default=False)
    offline_created_at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_customer(self, value):
        from apps.customers.models import CustomerProfile

        company = self.context["company"]
        try:
            customer = CustomerProfile.objects.get(id=value, company=company)
        except CustomerProfile.DoesNotExist:
            raise serializers.ValidationError("Customer not found.")
        if customer.status == "blocked":
            raise serializers.ValidationError(
                "Customer is blocked due to credit limit. Resolve outstanding before placing an order."
            )
        return value


class OrderStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OrderStatus.choices)
    notes = serializers.CharField(required=False, allow_blank=True)


class OrderApprovalSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject"])
    rejection_reason = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["action"] == "reject" and not attrs.get("rejection_reason"):
            raise serializers.ValidationError(
                {
                    "rejection_reason": "Rejection reason is required when rejecting an order."
                }
            )
        return attrs


class OrderCancelSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=500)


class PackItemSerializer(serializers.Serializer):
    item_id = serializers.UUIDField(help_text="ID of an item on this order.")
    packed_quantity = serializers.IntegerField(
        min_value=0,
        help_text="Units physically packed. Must be ≤ the ordered quantity.",
    )


class PackItemsSerializer(serializers.Serializer):
    """
    Records packed quantities for order items. Packed quantity may be equal
    to or less than the ordered quantity — over-packing is rejected.
    """

    items = PackItemSerializer(
        many=True,
        min_length=1,
        help_text="Per-item packed quantities. Partial updates allowed.",
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional note recorded in the order's status history.",
    )

    def validate(self, attrs):
        order = self.context["order"]
        # UUIDField coerces to uuid.UUID; normalize keys to str for lookups
        requested = {
            str(entry["item_id"]): entry["packed_quantity"] for entry in attrs["items"]
        }
        if len(requested) != len(attrs["items"]):
            raise serializers.ValidationError(
                {"items": "Duplicate item_id entries are not allowed."}
            )

        order_items = {
            str(item.id): item for item in order.items.filter(id__in=requested.keys())
        }
        missing = set(requested) - set(order_items)
        if missing:
            raise serializers.ValidationError(
                {
                    "items": f"Items not found on this order: {', '.join(sorted(missing))}."
                }
            )

        for item_id, packed_qty in requested.items():
            item = order_items[item_id]
            if packed_qty > item.quantity:
                raise serializers.ValidationError(
                    {
                        "items": (
                            f"Packed quantity ({packed_qty}) cannot exceed ordered "
                            f"quantity ({item.quantity}) for '{item.sku}'."
                        )
                    }
                )
        attrs["_resolved_items"] = [
            (order_items[item_id], packed_qty)
            for item_id, packed_qty in requested.items()
        ]
        return attrs


class KanbanStatusColumnSerializer(serializers.Serializer):
    submitted = OrderListSerializer(many=True)
    confirmed = OrderListSerializer(many=True)
    processing = OrderListSerializer(many=True)
    packed = OrderListSerializer(many=True)


class OfflineSyncRequestSerializer(serializers.Serializer):
    orders = serializers.ListField(
        child=serializers.DictField(),
        help_text="Order create payloads (as in POST /api/orders/) produced offline by the agent app.",
    )


class OfflineSyncFailedEntrySerializer(serializers.Serializer):
    offline_ref = serializers.CharField(default="")
    error = serializers.CharField(default="")


class OfflineSyncResponseSerializer(serializers.Serializer):
    synced = serializers.ListField(child=serializers.CharField())
    failed = OfflineSyncFailedEntrySerializer(many=True)


class OrderDraftCreateSerializer(serializers.Serializer):
    customer = serializers.UUIDField(
        help_text="Customer selected by the agent before scanning items."
    )
    delivery_address_line1 = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    delivery_address_line2 = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    delivery_city = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    delivery_state = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    delivery_pincode = serializers.CharField(
        max_length=10, required=False, allow_blank=True
    )
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    order_notes = serializers.CharField(required=False, allow_blank=True)
    discount_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=0, min_value=0, max_value=100
    )
    is_offline_order = serializers.BooleanField(default=False)
    offline_created_at = serializers.DateTimeField(required=False, allow_null=True)


class OrderAddItemSerializer(serializers.Serializer):
    qr_code = serializers.UUIDField(required=False, allow_null=True)
    color_variant = serializers.UUIDField(required=False, allow_null=True)
    variant_size = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Use for a single-size item. Requires no size_range.",
    )
    size_range = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Key from the product size chart's order_creation map.",
    )
    quantity = serializers.IntegerField(min_value=1)
    discount_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=0, min_value=0, max_value=100
    )
    client_ref = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=100,
        help_text="Optional idempotency key to prevent duplicate scans.",
    )

    def validate(self, attrs):
        if not attrs.get("qr_code") and not attrs.get("color_variant") and not attrs.get("variant_size"):
            raise serializers.ValidationError(
                {
                    "qr_code": (
                        "Provide qr_code, color_variant or variant_size."
                    )
                }
            )
        if (
            not attrs.get("variant_size")
            and (attrs.get("qr_code") or attrs.get("color_variant"))
            and not attrs.get("size_range")
        ):
            raise serializers.ValidationError(
                {"size_range": "Select a size range before adding this item."}
            )
        return attrs


class OrderUpdateItemSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1)


class OrderDraftUpdateSerializer(serializers.Serializer):
    delivery_address_line1 = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    delivery_address_line2 = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    delivery_city = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    delivery_state = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    delivery_pincode = serializers.CharField(
        max_length=10, required=False, allow_blank=True
    )
    expected_delivery_date = serializers.DateField(required=False, allow_null=True)
    order_notes = serializers.CharField(required=False, allow_blank=True)
    discount_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, min_value=0, max_value=100
    )


class OrderSubmitSerializer(OrderDraftUpdateSerializer):
    pass
