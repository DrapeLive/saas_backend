from rest_framework import serializers

from apps.accounts.models import User
from apps.agents.models import AgentCompanyMembership, AgentProfile
from apps.commissions.models import CommissionPayout


class AgentUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "phone", "is_active"]


class AgentMembershipSerializer(serializers.ModelSerializer):
    agent_id = serializers.UUIDField(read_only=True)
    user = AgentUserSerializer(source="agent.user", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    commission_plan_name = serializers.CharField(
        source="custom_commission_plan.name", read_only=True, default=None
    )
    clients_count = serializers.IntegerField(read_only=True, default=0)
    commission_total = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, default=0
    )
    commission_pending = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, default=0
    )

    class Meta:
        model = AgentCompanyMembership
        fields = [
            "id",
            "agent_id",
            "user",
            "company_name",
            "status",
            "territory",
            "clients_count",
            "commission_total",
            "commission_pending",
            "monthly_target",
            "custom_commission_plan",
            "commission_plan_name",
            "invitation_method",
            "joined_at",
            "removed_at",
            "approved_by",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "agent_id",
            "user",
            "company_name",
            "commission_plan_name",
            "status",
            "invitation_method",
            "joined_at",
            "removed_at",
            "approved_by",
            "reviewed_by",
            "reviewed_at",
            "created_at",
            "updated_at",
        ]


class AgentMembershipUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentCompanyMembership
        fields = ["territory", "monthly_target", "custom_commission_plan"]


class AgentCompanySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    logo = serializers.ImageField(read_only=True)
    membership_id = serializers.UUIDField()
    membership_status = serializers.CharField()
    territory = serializers.CharField()
    order_count = serializers.IntegerField(default=0)


class AgentPerformanceSerializer(serializers.Serializer):
    orders_this_month = serializers.IntegerField()
    sales_this_month = serializers.DecimalField(max_digits=14, decimal_places=2)
    commission_earned = serializers.DecimalField(max_digits=10, decimal_places=2)
    commission_preview = serializers.DecimalField(max_digits=10, decimal_places=2)
    leaderboard_rank = serializers.IntegerField(allow_null=True)
    target_vs_actual = serializers.FloatField(allow_null=True)
    monthly_target = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )


class AgentLeaderboardSerializer(serializers.Serializer):
    agent_id = serializers.UUIDField()
    full_name = serializers.CharField()
    email = serializers.EmailField()
    phone = serializers.CharField()
    territory = serializers.CharField()
    orders_this_month = serializers.IntegerField()
    sales_this_month = serializers.DecimalField(max_digits=14, decimal_places=2)
    rank = serializers.IntegerField()


class RecentPayoutSerializer(serializers.ModelSerializer):
    agent_name = serializers.CharField(source="agent.user.full_name", read_only=True)
    paid_by_name = serializers.CharField(
        source="paid_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = CommissionPayout
        fields = [
            "id",
            "agent_id",
            "agent_name",
            "amount",
            "entries_count",
            "settlement_month",
            "paid_at",
            "paid_by_name",
            "notes",
        ]


class AgentOverviewSummarySerializer(serializers.Serializer):
    active_agents = serializers.IntegerField()
    pending_payout_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    paid_payout_amount = serializers.DecimalField(max_digits=14, decimal_places=2)


class AgentOverviewSerializer(serializers.Serializer):
    summary = AgentOverviewSummarySerializer()
    recent_payouts = RecentPayoutSerializer(many=True)


class SwitchCompanyRequestSerializer(serializers.Serializer):
    company_id = serializers.UUIDField()


class SwitchCompanyResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    company_id = serializers.UUIDField()
    company_name = serializers.CharField()


class MembershipActionResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()
