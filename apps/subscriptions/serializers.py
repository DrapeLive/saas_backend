from typing import ClassVar

from django.utils import timezone
from rest_framework import serializers

from apps.subscriptions.models import (
    BillingCycle,
    Plan,
    Subscription,
    SubscriptionEvent,
    SubscriptionStatus,
    UsageSnapshot,
)


class PlanListSerializer(serializers.ModelSerializer):
    active_subscription_count = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields: ClassVar[list[str]] = [
            "id",
            "tier",
            "name",
            "description",
            "monthly_price",
            "yearly_price",
            "trial_days",
            "max_agents",
            "max_customers",
            "max_products",
            "max_orders_per_month",
            "storage_gb",
            "tally_sync_enabled",
            "whatsapp_enabled",
            "gst_verify_enabled",
            "analytics_advanced",
            "offline_mode_enabled",
            "api_access_enabled",
            "custom_domain_enabled",
            "dedicated_support",
            "is_active",
            "display_order",
            "active_subscription_count",
        ]

    def get_active_subscription_count(self, obj):
        return obj.subscriptions.filter(
            status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]
        ).count()


class PlanCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields: ClassVar[list[str]] = [
            "tier",
            "name",
            "description",
            "monthly_price",
            "yearly_price",
            "trial_days",
            "max_agents",
            "max_customers",
            "max_products",
            "max_orders_per_month",
            "storage_gb",
            "tally_sync_enabled",
            "whatsapp_enabled",
            "gst_verify_enabled",
            "analytics_advanced",
            "offline_mode_enabled",
            "api_access_enabled",
            "custom_domain_enabled",
            "dedicated_support",
            "is_active",
            "display_order",
        ]

    def validate_monthly_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value

    def validate_yearly_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value

    def validate(self, attrs):
        monthly = attrs.get("monthly_price", 0)
        yearly = attrs.get("yearly_price", 0)
        if yearly > 0 and monthly > 0 and yearly >= monthly * 12:
            raise serializers.ValidationError(
                {
                    "yearly_price": "Yearly price should be less than 12× the monthly price (discount expected)."
                }
            )
        return attrs


class SubscriptionEventSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(
        source="performed_by.full_name", read_only=True, default=None
    )
    from_plan_name = serializers.CharField(
        source="from_plan.name", read_only=True, default=None
    )
    to_plan_name = serializers.CharField(
        source="to_plan.name", read_only=True, default=None
    )

    class Meta:
        model = SubscriptionEvent
        fields: ClassVar[list[str]] = [
            "id",
            "event_type",
            "from_plan_name",
            "to_plan_name",
            "performed_by_name",
            "notes",
            "metadata",
            "created_at",
        ]


class UsageSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageSnapshot
        fields: ClassVar[list[str]] = [
            "id",
            "snapshot_month",
            "agent_count",
            "customer_count",
            "product_count",
            "order_count",
            "storage_used_mb",
        ]


class SubscriptionListSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_tier = serializers.CharField(source="plan.tier", read_only=True)

    class Meta:
        model = Subscription
        fields: ClassVar[list[str]] = [
            "id",
            "plan_name",
            "plan_tier",
            "billing_cycle",
            "status",
            "trial_end",
            "current_period_end",
            "price_paid",
        ]


class SubscriptionDetailSerializer(serializers.ModelSerializer):
    plan = PlanListSerializer(read_only=True)
    events = SubscriptionEventSerializer(many=True, read_only=True)
    usage = UsageSnapshotSerializer(source="usage_snapshots", many=True, read_only=True)
    days_remaining = serializers.SerializerMethodField()
    is_usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = Subscription
        fields: ClassVar[list[str]] = [
            "id",
            "plan",
            "billing_cycle",
            "status",
            "trial_start",
            "trial_end",
            "current_period_start",
            "current_period_end",
            "grace_period_end",
            "cancelled_at",
            "price_paid",
            "discount_pct",
            "engagement_score",
            "notes",
            "days_remaining",
            "is_usable",
            "events",
            "usage",
        ]

    def get_days_remaining(self, obj):
        if obj.current_period_end:
            delta = obj.current_period_end - timezone.now().date()
            return max(0, delta.days)
        return None


class SubscriptionUpgradeSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField()
    billing_cycle = serializers.ChoiceField(choices=BillingCycle.choices)
    discount_pct = serializers.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_plan_id(self, value):
        if not Plan.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("Plan not found or inactive.")
        return value


class SubscriptionExtendSerializer(serializers.Serializer):
    extend_days = serializers.IntegerField(min_value=1, max_value=365)
    notes = serializers.CharField(required=False, allow_blank=True)
