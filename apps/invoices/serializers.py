from typing import ClassVar

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.invoices.models import Invoice, InvoiceItem, InvoiceStatus, InvoiceType


class InvoiceItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields: ClassVar = [
            "id",
            "description",
            "hsn_code",
            "quantity",
            "unit_price",
            "discount_pct",
            "gst_rate",
            "taxable_amount",
            "gst_amount",
            "line_total",
        ]


class InvoiceItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceItem
        fields: ClassVar = [
            "description",
            "hsn_code",
            "quantity",
            "unit_price",
            "discount_pct",
            "gst_rate",
        ]

    def validate_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError("Quantity must be at least 1.")
        return value

    def validate_unit_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Unit price cannot be negative.")
        return value


class InvoiceListSerializer(serializers.ModelSerializer):
    """Lightweight — used in invoice table / outstanding list."""

    customer_name = serializers.CharField(
        source="customer.business_name", read_only=True
    )
    days_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields: ClassVar = [
            "id",
            "invoice_type",
            "invoice_number",
            "customer",
            "customer_name",
            "status",
            "invoice_date",
            "due_date",
            "total_amount",
            "amount_paid",
            "amount_due",
            "days_overdue",
            "tally_synced_at",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_days_overdue(self, obj):
        from django.utils import timezone

        if obj.due_date and obj.status in [InvoiceStatus.OVERDUE, InvoiceStatus.ISSUED]:
            delta = timezone.now().date() - obj.due_date
            return max(0, delta.days)
        return 0


class InvoiceDetailSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source="customer.business_name", read_only=True
    )
    customer_gstin = serializers.CharField(
        source="customer.gstin", read_only=True, default=""
    )
    items = InvoiceItemSerializer(many=True, read_only=True)
    days_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields: ClassVar = [
            "id",
            "invoice_type",
            "invoice_number",
            "order",
            "customer",
            "customer_name",
            "customer_gstin",
            "status",
            "invoice_date",
            "due_date",
            # Amount breakdown
            "subtotal",
            "discount_amount",
            "taxable_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_amount",
            "amount_paid",
            "amount_due",
            "days_overdue",
            # GST context
            "is_interstate",
            "reverse_charge",
            "place_of_supply",
            # Files
            "pdf_file",
            "pdf_generated_at",
            # Tally
            "tally_voucher_id",
            "tally_synced_at",
            "notes",
            # Nested
            "items",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_days_overdue(self, obj):
        from django.utils import timezone

        if obj.due_date and obj.status in [InvoiceStatus.OVERDUE, InvoiceStatus.ISSUED]:
            delta = timezone.now().date() - obj.due_date
            return max(0, delta.days)
        return 0


class InvoiceCreateSerializer(serializers.ModelSerializer):
    """
    Manual invoice creation (credit notes, debit notes, manual sales invoices).
    Auto-generated invoices (on dispatch) are created by the service layer, not this serializer.
    """

    items = InvoiceItemCreateSerializer(many=True, min_length=1)

    class Meta:
        model = Invoice
        fields: ClassVar = [
            "invoice_type",
            "order",
            "customer",
            "invoice_date",
            "due_date",
            "is_interstate",
            "reverse_charge",
            "place_of_supply",
            "notes",
            "items",
        ]

    def validate_invoice_type(self, value):
        auto_generated = [InvoiceType.SALES_INVOICE, InvoiceType.PURCHASE_ORDER]
        if value in auto_generated:
            raise serializers.ValidationError(
                f"'{value}' invoices are auto-generated from orders. "
                "Use credit_note or debit_note for manual creation."
            )
        return value

    def validate(self, attrs):
        if attrs.get("invoice_type") == InvoiceType.CREDIT_NOTE:
            if not attrs.get("order"):
                raise serializers.ValidationError(
                    {"order": "Credit notes must reference the original order."}
                )
        return attrs


class InvoiceStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=InvoiceStatus.choices)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_status(self, value):
        # Void is irreversible — handled in the view, but flag it here too
        if value == InvoiceStatus.VOID:
            raise serializers.ValidationError(
                "Use the dedicated void endpoint to void an invoice."
            )
        return value


class InvoiceVoidSerializer(serializers.Serializer):
    reason = serializers.CharField(min_length=5, max_length=500)


class InvoicePDFRegenerateSerializer(serializers.Serializer):
    """Triggers a background task to regenerate the invoice PDF."""

    force = serializers.BooleanField(default=False)


class InvoiceDownloadResponseSerializer(serializers.Serializer):
    """Absolute URL of the generated invoice PDF."""

    pdf_url = serializers.URLField()


class InvoicePDFQueuedSerializer(serializers.Serializer):
    """Confirmation that PDF regeneration was queued."""

    detail = serializers.CharField()
    invoice_id = serializers.UUIDField()
