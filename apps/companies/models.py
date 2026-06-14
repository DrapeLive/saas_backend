from django.db import models

from apps.core.models import TimeStampedModel, UUIDModel


class CompanyStatus(models.TextChoices):
    TRIAL = "trial", "Trial"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    EXPIRED = "expired", "Expired"
    GRACE = "grace", "Grace Period"


class Company(UUIDModel, TimeStampedModel):
    name = models.CharField(max_length=200)
    slug = models.CharField(unique=True, max_length=200)
    logo = models.ImageField(upload_to="company/logos", null=True, blank=True)
    tagline = models.CharField(max_length=200, blank=True)

    # Business Details
    gstin = models.CharField(max_length=15, unique=True, null=True, blank=True)
    gstin_verified = models.BooleanField(default=False)
    gstin_legal_name = models.CharField(max_length=200, blank=True)
    pan = models.CharField(max_length=10, blank=True)
    address_line1 = models.CharField(max_length=255, blank=True)
    address_line2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    pincode = models.CharField(max_length=10, blank=True)
    country = models.CharField(max_length=100, default="India")

    # Contact
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=15)
    website = models.URLField(blank=True)

    # Invoice configuration
    invoice_prefix = models.CharField(max_length=10, default="INV")
    po_prefix = models.CharField(max_length=10, default="PO")
    invoice_counter = models.PositiveIntegerField(default=0)
    po_counter = models.PositiveIntegerField(default=0)
    financial_year_start = models.DateField(null=True, blank=True)

    # Bank details
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account = models.CharField(max_length=20, blank=True)
    bank_ifsc = models.CharField(max_length=11, blank=True)
    bank_branch = models.CharField(max_length=100, blank=True)
    upi_id = models.CharField(max_length=50, blank=True)

    subscription = models.OneToOneField(
        "subscriptions.Subscription",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="company",
    )

    status = models.CharField(
        max_length=20,
        choices=CompanyStatus.choices,
        default=CompanyStatus.TRIAL,
    )

    # Tally integration config
    tally_enabled = models.BooleanField(default=False)
    tally_url = models.URLField(blank=True, help_text="Tally HTTP gateway URL")
    tally_company = models.CharField(max_length=200, blank=True)

    whatsapp_enabled = models.BooleanField(default=False)
    gst_verify_enabled = models.BooleanField(default=False)

    impersonation_token = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "companies_company"
        ordering = ["company_name"]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["gstin"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.status})"

    def get_next_invoice_number(self):
        from django.db.models import F

        Company.objects.filter(pk=self.pk).update(
            invoice_counter=F("invoice_counter") + 1
        )
        self.refresh_from_db(fields=["invoice_counter"])
        year = self.financial_year_start.year if self.financial_year_start else 2026
        return f"{self.invoice_prefix}-{year}-{self.invoice_counter:05d}"


class CompanySettings(UUIDModel, TimeStampedModel):
    company = models.OneToOneField(
        Company, on_delete=models.CASCADE, related_name="settings"
    )

    # Order workflow
    order_auto_confirm = models.BooleanField(default=False)
    order_approval_required = models.BooleanField(default=True)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    credit_block_on_exceed = models.BooleanField(default=True)

    # Notification preferences
    notify_order_whatsapp = models.BooleanField(default=True)
    notify_order_email = models.BooleanField(default=True)
    notify_low_stock = models.BooleanField(default=True)
    notify_payment_due_days = models.JSONField(default=list)

    # Commission settings
    commission_cycle = models.CharField(max_length=20, default="monthly")
    commission_pay_day = models.PositiveSmallIntegerField(default=5)

    # GST
    default_gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    reverse_charge = models.BooleanField(default=False)

    class Meta:
        db_table = "companies_settings"
