from typing import ClassVar
from urllib.parse import urlparse

from rest_framework import serializers

from apps.dispatch.models import Dispatch, Transport


class TransportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transport
        fields: ClassVar = [
            "id",
            "name",
            "tracking_url",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields: ClassVar = ["id", "created_at", "updated_at"]

    def validate_name(self, value):
        name = value.strip()
        if not name:
            raise serializers.ValidationError("Transport name is required.")
        request = self.context.get("request")
        company = request.user.company if request else None
        qs = Transport.objects.filter(company=company, name__iexact=name)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A transport with this name already exists."
            )
        return name

    def validate_tracking_url(self, value):
        url = (value or "").strip()
        if not url:
            return ""
        parsed = urlparse(url)
        if parsed.scheme.lower() != "https" or not parsed.netloc:
            raise serializers.ValidationError(
                "Tracking URL must be a valid HTTPS URL."
            )
        return url


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
            "transport",
            "transport_name",
            "lr_number",
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
    transport_id = serializers.UUIDField(
        required=False, allow_null=True, write_only=True
    )

    class Meta:
        model = Dispatch
        fields: ClassVar = [
            "order",
            "transport_id",
            "transport_name",
            "lr_number",
            "eway_bill_no",
            "boxes_count",
            "weight_kg",
        ]

    def validate(self, attrs):
        request = self.context.get("request")
        company = request.user.company if request else None
        if company is None:
            raise serializers.ValidationError(
                "A company is required to create a dispatch."
            )

        transport = None
        transport_id = attrs.pop("transport_id", None)
        if transport_id:
            try:
                transport = Transport.objects.get(pk=transport_id, company=company)
            except Transport.DoesNotExist:
                raise serializers.ValidationError(
                    {"transport_id": "Transport not found for this company."}
                )
            if not transport.is_active:
                raise serializers.ValidationError(
                    {"transport_id": "This transport is inactive."}
                )
        else:
            name = (attrs.get("transport_name") or "").strip()
            if not name:
                raise serializers.ValidationError(
                    {"transport_id": "Select a transport."}
                )
            transport = Transport.objects.filter(
                company=company, name__iexact=name
            ).first()

        attrs["transport"] = transport
        if transport is not None:
            attrs["transport_name"] = transport.name
            attrs["tracking_url"] = transport.tracking_url
        return attrs

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
