from typing import ClassVar

from rest_framework import serializers

from apps.commissions.models import (
    CategoryCommissionRate,
    CommissionEntry,
    CommissionPlan,
    CommissionSlab,
)


class CommissionSlabSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionSlab
        fields: ClassVar = [
            "id",
            "min_amount",
            "max_amount",
            "commission_pct",
        ]

    def validate(self, attrs):
        min_a = attrs.get("min_amount", 0)
        max_a = attrs.get("max_amount")
        if max_a is not None and max_a <= min_a:
            raise serializers.ValidationError(
                {"max_amount": "max_amount must be greater than min_amount."}
            )
        if attrs.get("commission_pct", 0) > 100:
            raise serializers.ValidationError(
                {"commission_pct": "Commission percentage cannot exceed 100."}
            )
        return attrs


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


class CommissionPlanListSerializer(serializers.ModelSerializer):
    slab_count = serializers.IntegerField(source="slabs.count", read_only=True)
    category_rate_count = serializers.IntegerField(
        source="category_rates.count", read_only=True
    )
    agent_count = serializers.SerializerMethodField()

    class Meta:
        model = CommissionPlan
        fields: ClassVar = [
            "id",
            "name",
            "description",
            "is_default",
            "slab_count",
            "category_rate_count",
            "agent_count",
            "created_at",
        ]

    def get_agent_count(self, obj):
        from apps.agents.models import AgentCompanyMembership

        return AgentCompanyMembership.objects.filter(
            custom_commission_plan=obj, status="active"
        ).count()


class CommissionPlanDetailSerializer(serializers.ModelSerializer):
    slabs = CommissionSlabSerializer(many=True, read_only=True)
    category_rates = CategoryCommissionRateSerializer(many=True, read_only=True)

    class Meta:
        model = CommissionPlan
        fields: ClassVar = [
            "id",
            "name",
            "description",
            "is_default",
            "slabs",
            "category_rates",
            "created_at",
            "updated_at",
        ]


class CommissionPlanCreateSerializer(serializers.ModelSerializer):
    slabs = CommissionSlabSerializer(many=True, required=False)
    category_rates = CategoryCommissionRateSerializer(many=True, required=False)

    class Meta:
        model = CommissionPlan
        fields: ClassVar = [
            "name",
            "description",
            "is_default",
            "slabs",
            "category_rates",
        ]

    def create(self, validated_data):
        slabs_data = validated_data.pop("slabs", [])
        rates_data = validated_data.pop("category_rates", [])
        plan = CommissionPlan.objects.create(**validated_data)

        for slab in slabs_data:
            CommissionSlab.objects.create(plan=plan, **slab)
        for rate in rates_data:
            CategoryCommissionRate.objects.create(plan=plan, **rate)

        return plan

    def validate(self, attrs):
        slabs = attrs.get("slabs", [])
        if slabs:
            # Ensure slabs don't overlap
            sorted_slabs = sorted(slabs, key=lambda s: s["min_amount"])
            for i in range(len(sorted_slabs) - 1):
                current_max = sorted_slabs[i].get("max_amount")
                next_min = sorted_slabs[i + 1]["min_amount"]
                if current_max is None:
                    raise serializers.ValidationError(
                        {
                            "slabs": "Only the last slab can have an open-ended max_amount."
                        }
                    )
                if current_max > next_min:
                    raise serializers.ValidationError(
                        {
                            "slabs": f"Slabs overlap: slab ending at {current_max} overlaps with slab starting at {next_min}."
                        }
                    )
        return attrs


class CommissionPlanUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionPlan
        fields: ClassVar = [
            "name",
            "description",
            "is_default",
        ]


class CommissionEntryListSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source="agent.user.full_name", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True, default=None)

    class Meta:
        model = CommissionEntry
        fields: ClassVar = [
            "id",
            "agent",
            "agent_name",
            "order",
            "order_number",
            "plan_name",
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
    plan_name = serializers.CharField(source="plan.name", read_only=True, default=None)
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
            "plan_name",
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
