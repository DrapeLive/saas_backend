from django.db import models

from apps.core.models import CompanyScopeModel, UUIDModel


class InvoiceType(models.TextChoices):
    SALES_INVOICE = "sales_invoice", "Sales Invoice"
    PURCHASE_ORDER = "purchase_order", "Purchase Order"
    CREDIT_NOTE = "credit_note", "Credit Note"
    DEBIT_NOTE = "debit_note", "Debit Note"


class InvoiceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ISSUED = "issued", "Issued"
    PAID = "paid", "Paid"
    PARTIAL = "partial", "Partially Paid"
    OVERDUE = "overdue", "Overdue"
    VOID = "void", "Void"


class Invoice(CompanyScopeModel):
    invoice_type = models.CharField(max_length=20, choices=InvoiceType.choices)
    invoice_number = models.CharField(max_length=30, unique=True)
    order = models.ForeignKey(
        "orders.Order",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="invoices",
    )
    customer = models.ForeignKey(
        "customers.CustomerProfile", on_delete=models.PROTECT, related_name="invoices"
    )
    status = models.CharField(
        max_length=15, choices=InvoiceStatus.choices, default=InvoiceStatus.DRAFT
    )

    invoice_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)

    subtotal = models.DecimalField(max_digits=14, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=14, decimal_places=2)
    cgst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    sgst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    igst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_due = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    is_interstate = models.BooleanField(default=False)
    reverse_charge = models.BooleanField(default=False)
    place_of_supply = models.CharField(max_length=100, blank=True)

    # PDF
    pdf_file = models.FileField(upload_to="invoices/pdf/%Y/%m/", null=True, blank=True)
    pdf_generated_at = models.DateTimeField(null=True, blank=True)

    tally_voucher_id = models.CharField(max_length=100, blank=True)
    tally_synced_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "invoices_invoice"
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["customer", "due_date"]),
        ]

    def __str__(self):
        return f"{self.invoice_number} — ₹{self.total_amount}"


class InvoiceItem(UUIDModel):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="items")
    description = models.CharField(max_length=300)
    hsn_code = models.CharField(max_length=10, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2)
    gst_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        db_table = "invoices_item"
