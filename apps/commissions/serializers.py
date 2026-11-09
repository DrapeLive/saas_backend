from typing import ClassVar

from rest_framework import serializers

from apps.commissions.models import CategoryCommissionRate, CommissionEntry


class CategoryCommissionRateSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = CategoryCommissionRate
        fields: ClassVar = [
            "id",
            "category",
            "category_name",
            "commission_pct",
        ]

    def validate_commission_pct(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError(
                "Commission percentage must be between 0 and 100."
            )
        return value


class CommissionEntryListSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source="agent.user.full_name", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = CommissionEntry
        fields: ClassVar = [
            "id",
            "agent",
            "agent_name",
            "order",
            "order_number",
            "order_value",
            "commission_pct",
            "commission_amount",
            "status",
            "settlement_month",
            "paid_at",
        ]


class CommissionEntryDetailSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source="agent.user.full_name", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    paid_by_name = serializers.CharField(
        source="paid_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = CommissionEntry
        fields: ClassVar = [
            "id",
            "agent",
            "agent_name",
            "order",
            "order_number",
            "order_value",
            "commission_pct",
            "commission_amount",
            "status",
            "settlement_month",
            "paid_at",
            "paid_by_name",
            "dispute_reason",
            "adjustment_notes",
            "created_at",
            "updated_at",
        ]


class CommissionEntryStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=CommissionEntry.EntryStatus.choices)
    dispute_reason = serializers.CharField(required=False, allow_blank=True)
    adjustment_notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs["status"] == CommissionEntry.EntryStatus.DISPUTED:
            if not attrs.get("dispute_reason"):
                raise serializers.ValidationError(
                    {
                        "dispute_reason": "Dispute reason is required when marking as disputed."
                    }
                )
        return attrs


class CommissionSettlementSerializer(serializers.Serializer):
    """Bulk-settle commission entries for a given month."""

    agent_id = serializers.UUIDField()
    settlement_month = serializers.DateField(
        help_text="First day of the settlement month (YYYY-MM-01)."
    )
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_settlement_month(self, value):
        if value.day != 1:
            raise serializers.ValidationError(
                "settlement_month must be the first day of the month (YYYY-MM-01)."
            )
        return value


class AgentCommissionSummarySerializer(serializers.Serializer):
    """Read-only summary per agent for the commission dashboard."""

    agent_id = serializers.UUIDField()
    agent_name = serializers.CharField()
    pending_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    approved_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    disputed_count = serializers.IntegerField()
    period = serializers.DateField()


class CommissionSettledSerializer(serializers.Serializer):
    """Confirmation for a bulk commission settlement run."""

    detail = serializers.CharField()
    total_paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    agent_id = serializers.UUIDField()
    settlement_month = serializers.DateField()
