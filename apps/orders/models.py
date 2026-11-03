import uuid
from typing import ClassVar

from django.db import models

from apps.core.models import CompanyScopeModel, TimeStampedModel, UUIDModel


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    CONFIRMED = "confirmed", "Confirmed"
    PROCESSING = "processing", "Processing"
    PACKED = "packed", "Packed"
    DISPATCHED = "dispatched", "Dispatched"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"


class PackingStatus(models.TextChoices):
    UNPACKED = "unpacked", "Unpacked"
    PARTIALLY_PACKED = "partially_packed", "Partially Packed"
    PACKED = "packed", "Packed"


class Order(CompanyScopeModel):
    order_number = models.CharField(max_length=30, blank=True)

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
        default=OrderStatus.SUBMITTED,
    )

    # Draft lifecycle: a DRAFT order is deleted (and its stock reservations
    # released) once this timestamp passes. Refreshed on every activity.
    draft_expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

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
            models.Index(fields=["status", "draft_expires_at"]),
        ]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["company", "order_number"],
                name="uniq_order_number_per_company",
            ),
        ]

    def __str__(self):
        return f"{self.order_number} — {self.customer.trade_name} [{self.status}]"

    @property
    def packing_status(self):
        """
        Derived from items: 'unpacked' when nothing is packed, 'packed' when
        every item is fully packed, otherwise 'partially_packed'.
        """
        items = self.items.all()
        if not items:
            return PackingStatus.UNPACKED
        statuses = {i.packing_status for i in items}
        if statuses == {PackingStatus.PACKED}:
            return PackingStatus.PACKED
        if statuses == {PackingStatus.UNPACKED}:
            return PackingStatus.UNPACKED
        return PackingStatus.PARTIALLY_PACKED


class OrderItem(UUIDModel, TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    variant_size = models.ForeignKey(
        "products.VariantSize",
        on_delete=models.PROTECT,
        related_name="order_items",
    )

    # Every scan/add operation creates one group. A size range such as
    # "20-24" produces one OrderItem per size, all sharing the same group_id
    # so the whole scan can be removed with a single delete.
    group_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True)
    size_range = models.CharField(max_length=50, blank=True)
    # Optional client idempotency key, unique per order.
    client_ref = models.CharField(max_length=100, blank=True, db_index=True)

    product_name = models.CharField(max_length=200)
    color_name = models.CharField(max_length=100)
    size = models.CharField(max_length=20)
    sku = models.CharField(max_length=60)
    hsn_code = models.CharField(max_length=10, blank=True)

    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    packed_quantity = models.PositiveIntegerField(
        default=0,
        help_text="Quantity actually packed. May be less than ordered quantity.",
    )
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        db_table = "orders_item"

    def __str__(self):
        return f"{self.order.order_number}: {self.product_name} {self.color_name} {self.size} ×{self.quantity}"

    @property
    def pending_qty(self):
        """Ordered quantity not yet packed."""
        return max(0, self.quantity - self.packed_quantity)

    @property
    def packing_status(self):
        if self.packed_quantity <= 0:
            return PackingStatus.UNPACKED
        if self.packed_quantity < self.quantity:
            return PackingStatus.PARTIALLY_PACKED
        return PackingStatus.PACKED


class OrderSequence(CompanyScopeModel):
    """Per-company, per-year monotonic counter used to generate order numbers.

    Draft orders are deleted frequently, so deriving the next number from
    ``Order.objects.count()`` is unsafe (it reuses numbers and races under
    concurrency). This row is locked while allocating the next number.
    """

    year = models.PositiveSmallIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "orders_sequence"
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["company", "year"],
                name="uniq_order_sequence_per_company_year",
            ),
        ]

    def __str__(self):
        return f"{self.company_id} / {self.year}: {self.last_number}"


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
    signature_image = models.ImageField(upload_to="signatures/")
    captured_at = models.DateTimeField(auto_now_add=True)
    captured_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "orders_signature"
