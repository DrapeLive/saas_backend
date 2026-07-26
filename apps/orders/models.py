from typing import ClassVar

from django.db import models

from apps.core.models import CompanyScopeModel, TimeStampedModel, UUIDModel


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft (Cart)"
    SUBMITTED = "submitted", "Submitted"
    CONFIRMED = "confirmed", "Confirmed"
    PROCESSING = "processing", "Processing"
    PACKED = "packed", "Packed"
    READY = "ready", "Ready to Dispatch"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"
    ON_HOLD = "on_hold", "On Hold"


class Order(CompanyScopeModel):
    order_number = models.CharField(max_length=30, unique=True, blank=True)
    po_number = models.CharField(max_length=30, blank=True, db_index=True)

    customer = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.PROTECT,
        related_name="orders",
    )
    agent = models.ForeignKey(
        "agents.AgentProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="orders",
    )

    status = models.CharField(
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.DRAFT,
    )

    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    cgst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    is_interstate = models.BooleanField(default=False)

    # Delivery
    delivery_address_line1 = models.CharField(max_length=255, blank=True)
    delivery_address_line2 = models.CharField(max_length=255, blank=True)
    delivery_city = models.CharField(max_length=100, blank=True)
    delivery_state = models.CharField(max_length=100, blank=True)
    delivery_pincode = models.CharField(max_length=10, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)

    # Notes
    order_notes = models.TextField(blank=True)
    internal_notes = models.TextField(blank=True)

    # Approval workflow
    requires_approval = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approved_orders",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    is_offline_order = models.BooleanField(default=False)
    offline_created_at = models.DateTimeField(null=True, blank=True)
    sync_status = models.CharField(
        max_length=20, default="synced"
    )  # synced / pending / failed

    tally_invoice_id = models.CharField(max_length=100, blank=True)
    tally_synced_at = models.DateTimeField(null=True, blank=True)

    # Timestamps
    submitted_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orders_order"
        ordering: ClassVar = ["-created_at"]
        indexes: ClassVar = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["customer", "status"]),
            models.Index(fields=["agent", "submitted_at"]),
        ]

    def __str__(self):
        return f"{self.order_number} — {self.customer.business_name} [{self.status}]"


class OrderItem(UUIDModel, TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant_size = models.ForeignKey(
        "products.VariantSize",
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    product_name = models.CharField(max_length=200)
    color_name = models.CharField(max_length=100)
    size = models.CharField(max_length=20)
    sku = models.CharField(max_length=60)
    hsn_code = models.CharField(max_length=10, blank=True)

    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = "orders_item"

    def __str__(self):
        return f"{self.order.order_number}: {self.product_name} {self.color_name} {self.size} ×{self.quantity}"


class OrderStatusHistory(UUIDModel):
    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name="status_history"
    )
    from_status = models.CharField(
        max_length=20, choices=OrderStatus.choices, blank=True
    )
    to_status = models.CharField(max_length=20, choices=OrderStatus.choices)
    changed_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "orders_status_history"
        ordering: ClassVar = ["-created_at"]


class OrderSignature(UUIDModel):
    order = models.OneToOneField(
        Order, on_delete=models.CASCADE, related_name="signature"
    )
    signature_image = models.ImageField(upload_to="orders/signatures/")
    captured_at = models.DateTimeField(auto_now_add=True)
    captured_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "orders_signature"
