from rest_framework import serializers

from apps.commissions.models import CommissionEntry, CommissionPayout


class AgentCreditSerializer(serializers.Serializer):
    credit_limit = serializers.DecimalField(max_digits=14, decimal_places=2)
    credit_utilized = serializers.DecimalField(max_digits=14, decimal_places=2)
    available_limit = serializers.DecimalField(max_digits=14, decimal_places=2)
    credit_utilization_pct = serializers.FloatField()
    is_credit_blocked = serializers.BooleanField()


class PendingSyncSerializer(serializers.Serializer):
    orders = serializers.IntegerField()
    invoices = serializers.IntegerField()
    payments = serializers.IntegerField()


class AgentTransactionSerializer(serializers.Serializer):
    type = serializers.ChoiceField(
        choices=["payout", "order_commission", "adjustment"]
    )
    id = serializers.CharField()
    date = serializers.DateField(allow_null=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    status = serializers.CharField(allow_null=True)
    reference = serializers.CharField(allow_null=True, required=False)
    settlement_month = serializers.DateField(allow_null=True, required=False)


class AgentOverviewDetailSerializer(serializers.Serializer):
    agent_id = serializers.CharField()
    agent_name = serializers.CharField()
    credit = AgentCreditSerializer()
    total_paid_ytd = serializers.DecimalField(max_digits=16, decimal_places=2)
    pending_sync = PendingSyncSerializer()
    recent_transactions = AgentTransactionSerializer(many=True)
    invoice_tally = serializers.JSONField(required=False, allow_null=True)


class AgentCommissionSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source="agent.user.full_name", read_only=True)
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = CommissionEntry
        fields = [
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
            "adjustment_notes",
            "created_at",
        ]


class AgentPayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommissionPayout
        fields = [
            "id",
            "settlement_month",
            "amount",
            "entries_count",
            "paid_at",
            "notes",
        ]


class AgentAdjustmentSerializer(serializers.ModelSerializer):
    order_number = serializers.CharField(source="order.order_number", read_only=True)

    class Meta:
        model = CommissionEntry
        fields = [
            "id",
            "order",
            "order_number",
            "order_value",
            "commission_amount",
            "status",
            "adjustment_notes",
            "settlement_month",
            "created_at",
        ]


class AgentPayCommissionSerializer(serializers.Serializer):
    """Request to pay an agent's approved commission for a settlement month."""

    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    notes = serializers.CharField(required=False, allow_blank=True)
    settlement_month = serializers.DateField(
        help_text="First day of the settlement month (YYYY-MM-01)."
    )

    def validate_settlement_month(self, value):
        if value.day != 1:
            raise serializers.ValidationError(
                "settlement_month must be the first day of the month (YYYY-MM-01)."
            )
        return value


class AgentPayCommissionResponseSerializer(serializers.Serializer):
    """Confirmation that an agent commission was paid."""

    detail = serializers.CharField()
    total_paid = serializers.DecimalField(max_digits=12, decimal_places=2)
    agent_id = serializers.UUIDField()
    settlement_month = serializers.DateField()
    payout_id = serializers.UUIDField(allow_null=True)
