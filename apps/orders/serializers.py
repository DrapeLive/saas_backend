from typing import ClassVar

from rest_framework import serializers

from apps.orders.models import (
    Order,
    OrderItem,
    OrderSignature,
    OrderStatus,
    OrderStatusHistory,
)


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
    class Meta:
        model = OrderItem
        fields: ClassVar = [
            "id",
            "variant_size",
            "product_name",
            "color_name",
            "size",
            "sku",
            "hsn_code",
            "unit_price",
            "quantity",
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
        product = variant.color_variant.product
        if qty % product.order_in_multiples != 0:
            raise serializers.ValidationError(
                {
                    "quantity": (
                        f"Quantity must be a multiple of {product.order_in_multiples}."
                    )
                }
            )
        if qty < product.minimum_order_qty:
            raise serializers.ValidationError(
                {
                    "quantity": (
                        f"Minimum order quantity is {product.minimum_order_qty}."
                    )
                }
            )
        return attrs


class OrderListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source="customer.business_name", read_only=True
    )
    agent_name = serializers.CharField(
        source="agent.user.full_name", read_only=True, default=None
    )
    item_count = serializers.IntegerField(source="items.count", read_only=True)

    class Meta:
        model = Order
        fields: ClassVar = [
            "id",
            "order_number",
            "po_number",
            "customer",
            "customer_name",
            "agent",
            "agent_name",
            "status",
            "total_amount",
            "item_count",
            "is_offline_order",
            "sync_status",
            "requires_approval",
            "submitted_at",
            "created_at",
        ]


class OrderDetailSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source="customer.business_name", read_only=True
    )
    agent_name = serializers.CharField(
        source="agent.user.full_name", read_only=True, default=None
    )
    approved_by_name = serializers.CharField(
        source="approved_by.full_name", read_only=True, default=None
    )
    items = OrderItemSerializer(many=True, read_only=True)
    status_history = OrderStatusHistorySerializer(many=True, read_only=True)
    signature = OrderSignatureSerializer(read_only=True)

    class Meta:
        model = Order
        fields: ClassVar = [
            "id",
            "order_number",
            "po_number",
            "customer",
            "customer_name",
            "agent",
            "agent_name",
            "status",
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
            "confirmed_at",
            "dispatched_at",
            "delivered_at",
            "cancelled_at",
            "created_at",
            "updated_at",
            # Nested
            "items",
            "status_history",
            "signature",
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
