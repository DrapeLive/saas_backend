from rest_framework import serializers

from apps.customers.models import (
    CustomerCommunicationLog,
    CustomerDocument,
    CustomerProfile,
)


class CustomerSerializer(serializers.ModelSerializer):
    credit_utilization_pct = serializers.ReadOnlyField()
    assigned_agent_name = serializers.SerializerMethodField()
    total_outstanding = serializers.SerializerMethodField()

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

    def get_assigned_agent_name(self, obj):
        if obj.assigned_agent and obj.assigned_agent.user:
            return obj.assigned_agent.user.full_name
        return None

    def get_total_outstanding(self, obj):
        # The list endpoint annotates a live sum of unpaid invoice balances
        # (computed_total_outstanding); fall back to the denormalized column
        # elsewhere until invoice lifecycle sync maintains it.
        return getattr(obj, "computed_total_outstanding", obj.total_outstanding)


class CustomerOverviewSerializer(serializers.Serializer):
    active_customer_count = serializers.IntegerField()
    total_outstanding_receivable = serializers.DecimalField(
        max_digits=14, decimal_places=2
    )


class CustomerCreateSerializer(serializers.ModelSerializer):
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
