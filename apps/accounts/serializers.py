from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from apps.accounts.models import RoleType, User
from apps.companies.models import Company, CompanySettings


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    company_name = serializers.CharField(max_length=200)
    company_slug = serializers.SlugField(max_length=200)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_company_slug(self, value):
        if Company.objects.filter(slug__iexact=value).exists():
            raise serializers.ValidationError(
                "A company with this slug already exists."
            )
        return value

    def create(self, validated_data):
        from django.db import transaction

        company_data = {
            "name": validated_data.pop("company_name"),
            "slug": validated_data.pop("company_slug"),
            "contact_email": validated_data.get("email"),
            "contact_phone": validated_data.get("phone", ""),
            "status": "pending",
        }

        with transaction.atomic():
            company = Company.objects.create(**company_data)
            user = User.objects.create_user(
                email=validated_data["email"],
                password=validated_data["password"],
                full_name=validated_data["full_name"],
                phone=validated_data.get("phone", ""),
                role=RoleType.ADMIN,
                company=company,
            )
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class AgentRegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def create(self, validated_data):
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            full_name=validated_data["full_name"],
            phone=validated_data.get("phone", ""),
            role=RoleType.AGENT,
            company=None,
        )
        return user


class AgentJoinSerializer(serializers.Serializer):
    invite_code = serializers.CharField(max_length=64)

    def validate_invite_code(self, value):
        from django.utils import timezone

        from apps.agents.models import AgentInvitation

        try:
            invitation = AgentInvitation.objects.get(token=value, status="pending")
        except AgentInvitation.DoesNotExist:
            raise serializers.ValidationError("Invalid or expired invitation code.")

        if invitation.expires_at < timezone.now():
            invitation.status = "expired"
            invitation.save(update_fields=["status"])
            raise serializers.ValidationError("Invitation code has expired.")

        if invitation.used_count >= invitation.max_uses:
            invitation.status = "expired"
            invitation.save(update_fields=["status"])
            raise serializers.ValidationError(
                "This invitation has reached its maximum uses."
            )

        self.context["invitation"] = invitation
        return value


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value


class PasswordResetSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        try:
            user = User.objects.get(email__iexact=value, is_active=True)
            self.context["reset_user"] = user
        except User.DoesNotExist:
            pass
        return value.lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    token = serializers.CharField()
    uid = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )


class UserProfileSerializer(serializers.ModelSerializer):
    company_name = serializers.SerializerMethodField()
    company_status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "company",
            "company_name",
            "company_status",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "email",
            "role",
            "company",
            "company_name",
            "company_status",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def get_company_name(self, obj):
        if obj.company_id:
            return obj.company.name
        return None

    def get_company_status(self, obj):
        if obj.company_id:
            return obj.company.status
        return None


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["full_name", "phone"]

    def validate_full_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Full name cannot be empty.")
        return value.strip()


class UserAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "role",
            "company",
            "is_active",
            "last_login",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "email",
            "last_login",
            "created_at",
        ]


class CreateSubAdminSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    full_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=15, required=False, allow_blank=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def create(self, validated_data):
        company = self.context["company"]
        user = User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            full_name=validated_data["full_name"],
            phone=validated_data.get("phone", ""),
            role=RoleType.SUB_ADMIN,
            company=company,
        )
        return user


class SuperAdminDashboardSerializer(serializers.Serializer):
    total_companies = serializers.IntegerField()
    active_companies = serializers.IntegerField()
    trial_companies = serializers.IntegerField()
    expired_companies = serializers.IntegerField()
    mrr = serializers.DecimalField(max_digits=12, decimal_places=2)
    arr = serializers.DecimalField(max_digits=12, decimal_places=2)
    churn_rate = serializers.FloatField()
    ltv = serializers.DecimalField(max_digits=12, decimal_places=2)


class ReceivablesAgeingSerializer(serializers.Serializer):
    _0_30 = serializers.DecimalField(
        source="0_30",
        max_digits=14,
        decimal_places=2,
    )
    _31_60 = serializers.DecimalField(
        source="31_60",
        max_digits=14,
        decimal_places=2,
    )
    _60_plus = serializers.DecimalField(
        source="60_plus",
        max_digits=14,
        decimal_places=2,
    )


class TallySyncSerializer(serializers.Serializer):
    status = serializers.CharField()
    last_synced_at = serializers.DateTimeField(allow_null=True)


class AdminDashboardSerializer(serializers.Serializer):
    sales_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    orders_pending = serializers.IntegerField()

    outstanding_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    overdue_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
    )

    receivables_ageing = ReceivablesAgeingSerializer()
    tally_sync = TallySyncSerializer()


class BusinessStatsSerializer(serializers.Serializer):
    total_customers = serializers.IntegerField()
    overdue_customers = serializers.IntegerField()
    overdue_invoices = serializers.IntegerField()
    total_agents = serializers.IntegerField()
    active_agents_today = serializers.IntegerField()
    outstanding_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
    )
    overdue_total = serializers.DecimalField(
        max_digits=14,
        decimal_places=2,
    )


class AdminAnalyticsSerializer(serializers.Serializer):
    sales_trend = serializers.ListField(child=serializers.DictField())
    top_products = serializers.ListField(child=serializers.DictField())
    agent_comparison = serializers.ListField(child=serializers.DictField())
    outstanding_aging = serializers.DictField()
    customer_acquisition = serializers.DictField()


class SetupProfileSerializer(serializers.ModelSerializer):
    gstin = serializers.CharField(max_length=15, required=False, allow_blank=True)

    class Meta:
        model = Company
        fields = [
            "name",
            "logo",
            "tagline",
            "gstin",
            "address_line1",
            "address_line2",
            "city",
            "state",
            "pincode",
            "country",
        ]


class SetupBankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["bank_name", "bank_account", "bank_ifsc", "bank_branch", "upi_id"]


class SetupInvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = ["invoice_prefix", "po_prefix", "financial_year_start"]


class SetupTaxSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanySettings
        fields = ["default_gst_rate", "reverse_charge"]


class SetupNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanySettings
        fields = [
            "notify_order_whatsapp",
            "notify_order_email",
            "notify_low_stock",
            "notify_payment_due_days",
        ]
