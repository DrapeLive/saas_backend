"""Response serializers for the reports app.

Row serializers describe the paginated detail rows returned by each report
``list`` action. Summary endpoints return plain dictionaries, matching the
convention used by the existing dashboard/analytics endpoints.
"""

from rest_framework import serializers


# ─────────────────────────────────────────────────────────────────────────────
# Sales report
# ─────────────────────────────────────────────────────────────────────────────


class SalesReportRowSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    order_number = serializers.CharField()
    order_date = serializers.DateTimeField()
    customer_id = serializers.UUIDField()
    customer_name = serializers.CharField(allow_null=True, default=None)
    agent_id = serializers.UUIDField(allow_null=True, default=None)
    agent_name = serializers.CharField(allow_null=True, default=None)
    status = serializers.CharField()
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    taxable_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    cgst_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    sgst_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    igst_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)


# ─────────────────────────────────────────────────────────────────────────────
# Order report
# ─────────────────────────────────────────────────────────────────────────────


class OrderReportRowSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    order_number = serializers.CharField()
    po_number = serializers.CharField(allow_blank=True, default="")
    order_date = serializers.DateTimeField()
    customer_id = serializers.UUIDField()
    customer_name = serializers.CharField(allow_null=True, default=None)
    agent_id = serializers.UUIDField(allow_null=True, default=None)
    agent_name = serializers.CharField(allow_null=True, default=None)
    status = serializers.CharField()
    subtotal = serializers.DecimalField(max_digits=14, decimal_places=2)
    discount_amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    items_count = serializers.IntegerField()
    total_quantity = serializers.IntegerField()


# ─────────────────────────────────────────────────────────────────────────────
# Customer report
# ─────────────────────────────────────────────────────────────────────────────


class CustomerReportRowSerializer(serializers.Serializer):
    customer_id = serializers.UUIDField()
    trade_name = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.EmailField(allow_blank=True, default="")
    segment = serializers.CharField()
    status = serializers.CharField()
    assigned_agent_id = serializers.UUIDField(allow_null=True, default=None)
    assigned_agent_name = serializers.CharField(allow_null=True, default=None)
    created_at = serializers.DateTimeField()
    total_orders = serializers.IntegerField()
    total_sales = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_outstanding = serializers.DecimalField(max_digits=14, decimal_places=2)
    overdue_outstanding = serializers.DecimalField(max_digits=14, decimal_places=2)
    credit_limit = serializers.DecimalField(max_digits=12, decimal_places=2)
    credit_utilized = serializers.DecimalField(max_digits=12, decimal_places=2)


# ─────────────────────────────────────────────────────────────────────────────
# Agent report
# ─────────────────────────────────────────────────────────────────────────────


class AgentReportRowSerializer(serializers.Serializer):
    agent_id = serializers.UUIDField()
    agent_name = serializers.CharField()
    phone = serializers.CharField(allow_blank=True, default="")
    employee_code = serializers.CharField(allow_blank=True, default="")
    territory = serializers.CharField(allow_blank=True, default="")
    total_orders = serializers.IntegerField()
    total_sales = serializers.DecimalField(max_digits=14, decimal_places=2)
    average_order_value = serializers.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )
    visits_count = serializers.IntegerField()
    assigned_customers_count = serializers.IntegerField()
    pending_commission = serializers.DecimalField(max_digits=10, decimal_places=2)


# ─────────────────────────────────────────────────────────────────────────────
# Inventory report
# ─────────────────────────────────────────────────────────────────────────────


class InventoryReportRowSerializer(serializers.Serializer):
    variant_size_id = serializers.UUIDField()
    product_id = serializers.UUIDField()
    product_name = serializers.CharField()
    color_name = serializers.CharField()
    color_hex = serializers.CharField(allow_blank=True, default="")
    size = serializers.CharField()
    sku = serializers.CharField()
    category_name = serializers.CharField(allow_null=True, default=None)
    hsn_code = serializers.CharField(allow_blank=True, default="")
    stock_quantity = serializers.IntegerField()
    reserved_qty = serializers.IntegerField()
    available_qty = serializers.IntegerField()
    reorder_level = serializers.IntegerField()
    is_low_stock = serializers.BooleanField()
    unit_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    stock_value = serializers.DecimalField(max_digits=14, decimal_places=2)


# ─────────────────────────────────────────────────────────────────────────────
# GST report
# ─────────────────────────────────────────────────────────────────────────────


class GSTReportRowSerializer(serializers.Serializer):
    invoice_id = serializers.UUIDField()
    invoice_number = serializers.CharField()
    invoice_date = serializers.DateField()
    invoice_type = serializers.CharField()
    status = serializers.CharField()
    customer_id = serializers.UUIDField()
    customer_name = serializers.CharField(allow_null=True, default=None)
    gstin = serializers.CharField(allow_blank=True, default="")
    place_of_supply = serializers.CharField(allow_blank=True, default="")
    is_interstate = serializers.BooleanField()
    taxable_amount = serializers.DecimalField(max_digits=14, decimal_places=2)
    cgst_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    sgst_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    igst_amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_tax = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2)