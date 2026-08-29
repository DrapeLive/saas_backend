from rest_framework import serializers
from typing_extensions import ClassVar

from apps.payments.models import OutstandingAging, Payment


class PaymentListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source="customer.business_name", read_only=True
    )
    agent_name = serializers.CharField(
        source="agent.user.full_name", read_only=True, default=None
    )
    invoice_number = serializers.CharField(
        source="invoice.invoice_number", read_only=True, default=None
    )
    recorded_by_name = serializers.CharField(
        source="recorded_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = Payment
        fields: ClassVar = [
            "id",
            "invoice",
            "invoice_number",
            "customer",
            "customer_name",
            "agent_name",
            "amount",
            "payment_date",
            "mode",
            "reference_no",
            "is_from_tally",
            "recorded_by_name",
            "created_at",
        ]


class PaymentDetailSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source="customer.business_name", read_only=True
    )
    agent_name = serializers.CharField(
        source="agent.user.full_name", read_only=True, default=None
    )
    invoice_number = serializers.CharField(
        source="invoice.invoice_number", read_only=True, default=None
    )
    recorded_by_name = serializers.CharField(
        source="recorded_by.full_name", read_only=True, default=None
    )

    class Meta:
        model = Payment
        fields: ClassVar = [
            "id",
            "invoice",
            "invoice_number",
            "customer",
            "customer_name",
            "agent",
            "agent_name",
            "amount",
            "payment_date",
            "mode",
            "reference_no",
            "receipt_file",
            "notes",
            "is_from_tally",
            "tally_ref",
            "recorded_by_name",
            "created_at",
            "updated_at",
        ]


class PaymentCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields: ClassVar = [
            "invoice",
            "customer",
            "agent",
            "amount",
            "payment_date",
            "mode",
            "reference_no",
            "receipt_file",
            "notes",
        ]

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Payment amount must be greater than zero."
            )
        return value

    def validate(self, attrs):
        invoice = attrs.get("invoice")
        if invoice:
            # Customer on payment must match customer on invoice
            if attrs.get("customer") and attrs["customer"] != invoice.customer:
                raise serializers.ValidationError(
                    {"customer": "Customer does not match the invoice customer."}
                )
            # Cannot exceed outstanding balance
            if attrs["amount"] > invoice.amount_due:
                raise serializers.ValidationError(
                    {
                        "amount": (
                            f"Payment of ₹{attrs['amount']} exceeds "
                            f"invoice outstanding of ₹{invoice.amount_due}."
                        )
                    }
                )
        return attrs


class PaymentModeBreakdownSerializer(serializers.Serializer):
    """Read-only summary — used in payment analytics."""

    mode = serializers.CharField()
    total = serializers.DecimalField(max_digits=14, decimal_places=2)
    count = serializers.IntegerField()


class OutstandingAgingSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(
        source="customer.business_name", read_only=True
    )
    customer_phone = serializers.CharField(source="customer.phone", read_only=True)
    assigned_agent = serializers.CharField(
        source="customer.assigned_agent.user.full_name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = OutstandingAging
        fields: ClassVar = [
            "id",
            "customer",
            "customer_name",
            "customer_phone",
            "assigned_agent",
            "report_date",
            "current",
            "days_1_30",
            "days_31_60",
            "days_61_90",
            "days_90_plus",
            "total",
        ]


class AgingReportSummarySerializer(serializers.Serializer):
    """Aggregated aging across all customers — for the dashboard aging widget."""

    total_outstanding = serializers.DecimalField(max_digits=14, decimal_places=2)
    current = serializers.DecimalField(max_digits=14, decimal_places=2)
    days_1_30 = serializers.DecimalField(max_digits=14, decimal_places=2)
    days_31_60 = serializers.DecimalField(max_digits=14, decimal_places=2)
    days_61_90 = serializers.DecimalField(max_digits=14, decimal_places=2)
    days_90_plus = serializers.DecimalField(max_digits=14, decimal_places=2)
    customers_overdue = serializers.IntegerField()


class SendPaymentReminderSerializer(serializers.Serializer):
    customer_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    channel = serializers.ChoiceField(
        choices=["whatsapp", "email", "both"], default="whatsapp"
    )
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Custom message; leave blank to use the default template.",
    )


class PaymentReminderQueuedSerializer(serializers.Serializer):
    """Confirmation that payment reminders were queued."""

    detail = serializers.CharField()
    channel = serializers.CharField()
    customer_count = serializers.IntegerField()
