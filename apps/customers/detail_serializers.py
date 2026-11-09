from rest_framework import serializers


class AddressSerializer(serializers.Serializer):
    line1 = serializers.CharField(default="", allow_blank=True)
    line2 = serializers.CharField(default="", allow_blank=True)
    city = serializers.CharField(default="", allow_blank=True)
    state = serializers.CharField(default="", allow_blank=True)
    pincode = serializers.CharField(default="", allow_blank=True)
    same_as_billing = serializers.BooleanField(default=True)


class AgingBucketSerializer(serializers.Serializer):
    bucket = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    percentage = serializers.FloatField()


class OutstandingBlockSerializer(serializers.Serializer):
    buckets = AgingBucketSerializer(many=True)
    total_outstanding = serializers.DecimalField(max_digits=14, decimal_places=2)


class ActivityEntrySerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["follow_up", "agent_note"])
    channel = serializers.CharField()
    text = serializers.CharField(default="", allow_blank=True)
    subject = serializers.CharField(default="", allow_blank=True)
    date = serializers.DateField()


class PaymentEntrySerializer(serializers.Serializer):
    id = serializers.CharField()
    date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    type = serializers.CharField(required=False, allow_blank=True)
    tally_sync_status = serializers.ChoiceField(
        choices=["synced", "pending", "failed"]
    )


class CustomerSummarySerializer(serializers.Serializer):
    id = serializers.CharField()
    name = serializers.CharField()
    owner_name = serializers.CharField(default="", allow_blank=True)
    email = serializers.EmailField(default="", allow_blank=True)
    billing_address = AddressSerializer()
    shipping_address = AddressSerializer()
    phone = serializers.CharField()
    whatsapp_number = serializers.CharField(default="", allow_blank=True)
    credit_utilization_pct = serializers.FloatField()
    credit_utilized = serializers.DecimalField(max_digits=14, decimal_places=2)
    credit_limit = serializers.DecimalField(max_digits=14, decimal_places=2)
    available_limit = serializers.DecimalField(max_digits=14, decimal_places=2)
    outstanding = OutstandingBlockSerializer()
    recent_activity = ActivityEntrySerializer(many=True)
    recent_payments = PaymentEntrySerializer(many=True)


class RecentOrderSerializer(serializers.Serializer):
    id = serializers.CharField()
    order_number = serializers.CharField()
    date = serializers.DateField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    status = serializers.CharField()
    sync_status = serializers.CharField(default="synced")
    tally_synced_at = serializers.DateTimeField(allow_null=True, required=False)


class CustomerOrdersSerializer(serializers.Serializer):
    lifetime_value = serializers.DecimalField(max_digits=16, decimal_places=2)
    pending_orders = serializers.IntegerField()
    avg_order_value = serializers.DecimalField(max_digits=16, decimal_places=2)
    recent_orders = RecentOrderSerializer(many=True)
    tally_sync_status = serializers.DictField(child=serializers.IntegerField())


class UpcomingPaymentSerializer(serializers.Serializer):
    invoice_id = serializers.CharField()
    invoice_number = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    due_date = serializers.DateField()
    days_overdue = serializers.IntegerField()


class CustomerPaymentsSerializer(serializers.Serializer):
    total_paid = serializers.DecimalField(max_digits=16, decimal_places=2)
    paid_change_pct = serializers.FloatField(allow_null=True)
    outstanding = serializers.DecimalField(max_digits=16, decimal_places=2)
    recent_transactions = PaymentEntrySerializer(many=True)
    upcoming_payment = UpcomingPaymentSerializer(allow_null=True)


class CriticalInvoiceSerializer(serializers.Serializer):
    id = serializers.CharField()
    invoice_number = serializers.CharField()
    amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    due_date = serializers.DateField()
    days_past_due = serializers.IntegerField()


class CustomerOutstandingSerializer(serializers.Serializer):
    total_paid_ytd = serializers.DecimalField(max_digits=16, decimal_places=2)
    total_outstanding = serializers.DecimalField(max_digits=16, decimal_places=2)
    last_payment_date = serializers.DateField(allow_null=True)
    credit_utilization_pct = serializers.FloatField()
    available_limit = serializers.DecimalField(max_digits=14, decimal_places=2)
    avg_pay_days = serializers.IntegerField()
    aging_analysis = AgingBucketSerializer(many=True)
    critical_invoices = CriticalInvoiceSerializer(many=True)
