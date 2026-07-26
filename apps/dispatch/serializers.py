from typing import ClassVar

from rest_framework import serializers

from apps.dispatch.models import Dispatch


class DispatchListSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer_name = serializers.CharField(
        source="order.customer.business_name", read_only=True
    )
    dispatched_by_name = serializers.CharField(
        source="dispatched_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = Dispatch
        fields: ClassVar = [
            "id",
            "order",
            "order_number",
            "customer_name",
            "lr_number",
            "transport_name",
            "dispatch_date",
            "expected_delivery",
            "actual_delivery",
            "eway_bill_no",
            "boxes_count",
            "dispatched_by_name",
        ]


class DispatchDetailSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    customer_name = serializers.CharField(
        source="order.customer.business_name", read_only=True
    )
    dispatched_by_name = serializers.CharField(
        source="dispatched_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = Dispatch
        fields: ClassVar = [
            "id",
            "order",
            "order_number",
            "customer_name",
            "lr_number",
            "transport_name",
            "vehicle_number",
            "driver_contact",
            "dispatch_date",
            "expected_delivery",
            "actual_delivery",
            "tracking_url",
            "eway_bill_no",
            "boxes_count",
            "weight_kg",
            "dispatched_by_name",
            "created_at",
            "updated_at",
        ]


class DispatchCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dispatch
        fields: ClassVar = [
            "order",
            "lr_number",
            "transport_name",
            "vehicle_number",
            "driver_contact",
            "dispatch_date",
            "expected_delivery",
            "eway_bill_no",
            "boxes_count",
            "weight_kg",
            "tracking_url",
        ]

    def validate_order(self, value):
        if value.status not in ["packed", "ready"]:
            raise serializers.ValidationError(
                "Order must be in 'Packed' or 'Ready to Dispatch' status before dispatching."
            )
        if hasattr(value, "dispatch"):
            raise serializers.ValidationError(
                "A dispatch record already exists for this order."
            )
        return value


class DispatchUpdateSerializer(serializers.ModelSerializer):
    """Used to update tracking / delivery info after dispatch."""

    class Meta:
        model = Dispatch
        fields: ClassVar = [
            "lr_number",
            "transport_name",
            "vehicle_number",
            "driver_contact",
            "expected_delivery",
            "actual_delivery",
            "tracking_url",
            "eway_bill_no",
            "boxes_count",
            "weight_kg",
        ]


class MarkDeliveredSerializer(serializers.Serializer):
    actual_delivery = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True)
