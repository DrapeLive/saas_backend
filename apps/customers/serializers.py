from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.agents.models import AgentProfile
from apps.customers.models import (
    CustomerCommunicationLog,
    CustomerDocument,
    CustomerProfile,
)


class CustomerSerializer(serializers.ModelSerializer):
    credit_utilization_pct = serializers.FloatField(read_only=True)
    assigned_agent_name = serializers.SerializerMethodField()
    total_outstanding = serializers.SerializerMethodField()
    assigned_agent = serializers.SlugRelatedField(
        slug_field="user_id",
        queryset=AgentProfile.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = CustomerProfile
        fields = [
            "id",
            "legal_name",
            "trade_name",
            "owner_name",
            "email",
            "phone",
            "whatsapp_number",
            "gstin",
            "gstin_verified",
            "gstin_legal_name",
            "gstin_status",
            "gstin_type",
            "gstin_verified_at",
            "pan",
            "tags",
            "billing_address_line1",
            "billing_address_line2",
            "billing_city",
            "billing_state",
            "billing_pincode",
            "shipping_address_line1",
            "shipping_address_line2",
            "shipping_city",
            "shipping_state",
            "shipping_pincode",
            "same_as_billing",
            "assigned_agent",
            "assigned_agent_name",
            "credit_limit",
            "credit_utilized",
            "credit_utilization_pct",
            "is_credit_blocked",
            "payment_terms_days",
            "auto_block_on_exceed",
            "total_outstanding",
            "overdue_outstanding",
            "segment",
            "status",
            "internal_notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "gstin_verified",
            "gstin_legal_name",
            "gstin_status",
            "gstin_type",
            "gstin_verified_at",
            "credit_utilized",
            "credit_utilization_pct",
            "total_outstanding",
            "overdue_outstanding",
            "segment",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_assigned_agent_name(self, obj):
        if obj.assigned_agent and obj.assigned_agent.user:
            return obj.assigned_agent.user.full_name
        return None

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=2))
    def get_total_outstanding(self, obj):
        # The list endpoint annotates a live sum of unpaid invoice balances
        # (computed_total_outstanding); fall back to the denormalized column
        # elsewhere until invoice lifecycle sync maintains it.
        return getattr(obj, "computed_total_outstanding", obj.total_outstanding)


class CustomerPageSerializer(serializers.Serializer):
    """Paginated customer list envelope."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = CustomerSerializer(many=True)


class CustomerOverviewSerializer(serializers.Serializer):
    active_customer_count = serializers.IntegerField()
    total_outstanding_receivable = serializers.DecimalField(
        max_digits=14, decimal_places=2
    )


class CustomerCreateSerializer(serializers.ModelSerializer):
    assigned_agent = serializers.SlugRelatedField(
        slug_field="user_id",
        queryset=AgentProfile.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = CustomerProfile
        fields = [
            "legal_name",
            "trade_name",
            "owner_name",
            "email",
            "phone",
            "whatsapp_number",
            "gstin",
            "pan",
            "tags",
            "billing_address_line1",
            "billing_address_line2",
            "billing_city",
            "billing_state",
            "billing_pincode",
            "shipping_address_line1",
            "shipping_address_line2",
            "shipping_city",
            "shipping_state",
            "shipping_pincode",
            "same_as_billing",
            "assigned_agent",
            "credit_limit",
            "payment_terms_days",
            "auto_block_on_exceed",
            "status",
            "internal_notes",
        ]

    def validate_tags(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Tags must be a list of strings.")
        return value


class CustomerUpdateSerializer(serializers.ModelSerializer):
    assigned_agent = serializers.SlugRelatedField(
        slug_field="user_id",
        queryset=AgentProfile.objects.all(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = CustomerProfile
        fields = [
            "legal_name",
            "trade_name",
            "owner_name",
            "email",
            "phone",
            "whatsapp_number",
            "gstin",
            "pan",
            "tags",
            "billing_address_line1",
            "billing_address_line2",
            "billing_city",
            "billing_state",
            "billing_pincode",
            "shipping_address_line1",
            "shipping_address_line2",
            "shipping_city",
            "shipping_state",
            "shipping_pincode",
            "same_as_billing",
            "assigned_agent",
            "credit_limit",
            "payment_terms_days",
            "auto_block_on_exceed",
            "status",
            "internal_notes",
        ]

    def validate_tags(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Tags must be a list of strings.")
        return value


class CustomerImportRowSerializer(serializers.Serializer):
    row_number = serializers.IntegerField()
    trade_name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=15)
    gstin = serializers.CharField(max_length=15, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    owner_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    billing_city = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    billing_state = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    errors = serializers.ListField(child=serializers.CharField(), default=list)


class CustomerImportPreviewSerializer(serializers.Serializer):
    rows = CustomerImportRowSerializer(many=True)


class ImportRowResultSerializer(serializers.Serializer):
    row_number = serializers.IntegerField()
    errors = serializers.DictField(
        child=serializers.ListField(child=serializers.CharField()), default=dict
    )


class CustomerImportPreviewResponseSerializer(serializers.Serializer):
    valid = serializers.ListField(child=serializers.DictField())
    errors = ImportRowResultSerializer(many=True)
    total = serializers.IntegerField()


class CustomerImportConfirmResponseSerializer(serializers.Serializer):
    created = CustomerSerializer(many=True)
    errors = ImportRowResultSerializer(many=True)
    total = serializers.IntegerField()


class GstinVerifyResponseSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    legal_name = serializers.CharField()
    status = serializers.CharField()
    type = serializers.CharField()
    message = serializers.CharField()


class CustomerSegmentResponseSerializer(serializers.Serializer):
    segment = serializers.CharField()


class CreditActivityResponseSerializer(serializers.Serializer):
    is_credit_blocked = serializers.BooleanField()


class CustomerImportConfirmSerializer(serializers.Serializer):
    rows = serializers.ListField(child=serializers.DictField())


class CustomerDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerDocument
        fields = [
            "id",
            "customer",
            "doc_type",
            "title",
            "file",
            "uploaded_by",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "uploaded_by", "created_at"]


class CustomerCommunicationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerCommunicationLog
        fields = [
            "id",
            "customer",
            "channel",
            "subject",
            "message",
            "performed_by",
            "created_at",
        ]
        read_only_fields = ["id", "performed_by", "created_at"]
