from typing import ClassVar

from rest_framework import serializers

from apps.companies.models import Company, CompanySettings, CompanyStatus
from apps.subscriptions.models import Subscription


class CompanySettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanySettings
        fields: ClassVar = [
            "order_auto_confirm",
            "order_approval_required",
            "low_stock_threshold",
            "credit_block_on_exceed",
            "notify_order_whatsapp",
            "notify_order_email",
            "notify_low_stock",
            "notify_payment_due_days",
            "commission_cycle",
            "commission_pay_day",
            "default_gst_rate",
            "reverse_charge",
        ]


class CompanySettingsResponseSerializer(serializers.ModelSerializer):
    company_id = serializers.UUIDField(source="company.id", read_only=True)

    class Meta:
        model = CompanySettings
        fields: ClassVar = [
            "company_id",
            "order_auto_confirm",
            "order_approval_required",
            "low_stock_threshold",
            "credit_block_on_exceed",
            "notify_order_whatsapp",
            "notify_order_email",
            "notify_low_stock",
            "notify_payment_due_days",
            "commission_cycle",
            "commission_pay_day",
            "default_gst_rate",
            "reverse_charge",
            "current_plan_tier",
            "current_plan_name",
            "plan_max_agents",
            "plan_max_customers",
            "plan_max_products",
            "plan_max_orders_per_month",
            "plan_storage_gb",
            "analytics_advanced",
            "offline_mode_enabled",
            "api_access_enabled",
            "custom_domain_enabled",
            "dedicated_support",
        ]
        read_only_fields: ClassVar = [
            "company_id",
            "current_plan_tier",
            "current_plan_name",
            "plan_max_agents",
            "plan_max_customers",
            "plan_max_products",
            "plan_max_orders_per_month",
            "plan_storage_gb",
            "analytics_advanced",
            "offline_mode_enabled",
            "api_access_enabled",
            "custom_domain_enabled",
            "dedicated_support",
        ]


class SubscriptionInlineSerializer(serializers.ModelSerializer):
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    plan_tier = serializers.CharField(source="plan.tier", read_only=True)
    plan_price = serializers.DecimalField(
        source="plan.monthly_price", max_digits=10, decimal_places=2, read_only=True
    )

    class Meta:
        model = Subscription
        fields: ClassVar = [
            "id",
            "plan_name",
            "plan_tier",
            "plan_price",
            "billing_cycle",
            "status",
            "trial_start",
            "trial_end",
            "current_period_start",
            "current_period_end",
            "grace_period_end",
            "price_paid",
            "discount_pct",
            "engagement_score",
        ]


class CompanyListSerializer(serializers.ModelSerializer):
    plan_tier = serializers.CharField(
        source="subscription.plan.tier", read_only=True, default=None
    )
    subscription_status = serializers.CharField(
        source="subscription.status", read_only=True, default=None
    )
    trial_end = serializers.DateField(
        source="subscription.trial_end", read_only=True, default=None
    )
    period_end = serializers.DateField(
        source="subscription.current_period_end", read_only=True, default=None
    )

    class Meta:
        model = Company
        fields: ClassVar = [
            "id",
            "name",
            "slug",
            "logo",
            "gstin",
            "gstin_verified",
            "contact_email",
            "contact_phone",
            "city",
            "state",
            "status",
            "plan_tier",
            "subscription_status",
            "trial_end",
            "period_end",
            "tally_enabled",
            "whatsapp_enabled",
            "setup_completed",
            "created_at",
            "updated_at",
        ]


class CompanySerializer(serializers.ModelSerializer):
    subscription = SubscriptionInlineSerializer(read_only=True)
    settings = CompanySettingsSerializer(read_only=True)

    class Meta:
        model = Company
        fields: ClassVar = [
            "id",
            "name",
            "slug",
            "logo",
            "tagline",
            "gstin",
            "gstin_verified",
            "gstin_legal_name",
            "pan",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "pincode",
            "country",
            "contact_email",
            "contact_phone",
            "website",
            "invoice_prefix",
            "po_prefix",
            "invoice_counter",
            "po_counter",
            "financial_year_start",
            "bank_name",
            "bank_account",
            "bank_ifsc",
            "bank_branch",
            "upi_id",
            "tally_enabled",
            "tally_url",
            "tally_company",
            "whatsapp_enabled",
            "gst_verify_enabled",
            "status",
            "setup_completed",
            "subscription",
            "settings",
            "created_at",
            "updated_at",
        ]


class CompanyUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields: ClassVar = [
            "name",
            "logo",
            "tagline",
            "contact_email",
            "contact_phone",
            "website",
            "pan",
            "gstin",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "pincode",
            "country",
            "invoice_prefix",
            "po_prefix",
            "bank_name",
            "bank_account",
            "bank_ifsc",
            "bank_branch",
            "upi_id",
            "tally_enabled",
            "tally_url",
            "tally_company",
            "whatsapp_enabled",
            "gst_verify_enabled",
        ]
        read_only_fields: ClassVar = ["slug", "status"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        protected = {"slug", "status"} & set(attrs)
        if protected:
            raise serializers.ValidationError(
                {field: "This field cannot be updated." for field in protected}
            )
        return attrs


class CompanyStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=CompanyStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True)


class ExtendTrialSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=90)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
