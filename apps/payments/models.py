from django.db import models

from apps.core.models import CompanyScopeModel


class PaymentMode(models.TextChoices):
    CASH = "cash", "Cash"
    BANK = "bank", "Bank Transfer"
    UPI = "upi", "UPI"
    CHEQUE = "cheque", "Cheque"
    NEFT = "neft", "NEFT / RTGS"
    OTHER = "other", "Other"


class Payment(CompanyScopeModel):
    invoice = models.ForeignKey(
        "invoices.Invoice",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payments",
    )
    customer = models.ForeignKey(
        "customers.CustomerProfile", on_delete=models.PROTECT, related_name="payments"
    )
    agent = models.ForeignKey(
        "agents.AgentProfile", null=True, blank=True, on_delete=models.SET_NULL
    )

    amount = models.DecimalField(max_digits=14, decimal_places=2)
    payment_date = models.DateField()
    mode = models.CharField(max_length=15, choices=PaymentMode.choices)
    reference_no = models.CharField(max_length=100, blank=True)
    receipt_file = models.FileField(
        upload_to="payments/receipts/", null=True, blank=True
    )
    notes = models.TextField(blank=True)

    is_from_tally = models.BooleanField(default=False)
    tally_ref = models.CharField(max_length=100, blank=True)
    recorded_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "payments_payment"
        ordering = ["-payment_date"]


class OutstandingAging(CompanyScopeModel):
    customer = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.CASCADE,
        related_name="aging_records",
    )
    report_date = models.DateField()

    current = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    days_1_30 = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    days_31_60 = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    days_61_90 = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    days_90_plus = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        db_table = "payments_outstanding_aging"
        unique_together = [("company", "customer", "report_date")]
        ordering = ["-report_date"]
