from typing import ClassVar

from django.utils.text import slugify
from rest_framework import serializers

from apps.companies.models import Company, CompanySettings, CompanyStatus
from apps.subscriptions.models import BillingCycle, Plan, Subscription


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


class CompanyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=200)
    slug = serializers.SlugField(max_length=200, required=False)
    gstin = serializers.CharField(max_length=15, required=False, allow_blank=True)
    contact_email = serializers.EmailField()
    contact_phone = serializers.CharField(max_length=15)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    country = serializers.CharField(max_length=100, default="India")

    # Admin user
    admin_full_name = serializers.CharField(max_length=150)
    admin_email = serializers.EmailField()
    admin_password = serializers.CharField(write_only=True, min_length=8)
    admin_phone = serializers.CharField(max_length=15, required=False, allow_blank=True)

    # Subscription
    plan_id = serializers.UUIDField(required=False)
    billing_cycle = serializers.ChoiceField(
        choices=BillingCycle.choices, default=BillingCycle.TRIAL
    )
    discount_pct = serializers.DecimalField(
        max_digits=5, decimal_places=2, default=0, required=False
    )

    def validate_slug(self, value):
        if Company.objects.filter(slug=value).exists():
            raise serializers.ValidationError("This slug is already taken.")
        return value

    def validate_gstin(self, value):
        if value and Company.objects.filter(gstin=value).exists():
            raise serializers.ValidationError(
                "A company with this GSTIN already exists."
            )
        return value

    def validate_admin_email(self, value):
        from apps.accounts.models import User

        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_plan_id(self, value):
        if not Plan.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("Plan not found or inactive.")
        return value

    def validate(self, attrs):
        if not attrs.get("slug"):
            base_slug = slugify(attrs["name"])
            slug, counter = base_slug, 1
            while Company.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            attrs["slug"] = slug
        return attrs


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


class CompanyStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=CompanyStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True)


class ExtendTrialSerializer(serializers.Serializer):
    days = serializers.IntegerField(min_value=1, max_value=90)
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True)
