from django.db import models

from apps.core.models import CompanyScopeModel


class CustomerProfile(CompanyScopeModel):
    class CustomerStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        BLOCKED = "blocked", "Blocked"
        PROSPECTS = "prospect", "Prospect"

    class CustomerSegment(models.TextChoices):
        PLATINUM = "platinum", "Platinum"
        GOLD = "gold", "Gold"
        SILVER = "silver", "Silver"
        BRONZE = "bronze", "Bronze"

    user = models.OneToOneField(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customer_profile",
        limit_choices_to={"role": "customer"},
    )

    # Business identity
    business_name = models.CharField(max_length=200)
    owner_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=15)
    whatsapp_number = models.CharField(max_length=15, blank=True)

    # GST details (auto-populated via GSTN API)
    gstin = models.CharField(max_length=15, blank=True, db_index=True)
    gstin_verified = models.BooleanField(default=False)
    gstin_legal_name = models.CharField(max_length=200, blank=True)
    gstin_status = models.CharField(max_length=50, blank=True)  # Active / Cancelled
    gstin_type = models.CharField(max_length=50, blank=True)  # Regular / Composition
    gstin_verified_at = models.DateTimeField(null=True, blank=True)

    pan = models.CharField(max_length=10, blank=True)

    # Address
    billing_address_line1 = models.CharField(max_length=255, blank=True)
    billing_address_line2 = models.CharField(max_length=255, blank=True)
    billing_city = models.CharField(max_length=100, blank=True)
    billing_state = models.CharField(max_length=100, blank=True)
    billing_pincode = models.CharField(max_length=10, blank=True)
    shipping_address_line1 = models.CharField(max_length=255, blank=True)
    shipping_address_line2 = models.CharField(max_length=255, blank=True)
    shipping_city = models.CharField(max_length=100, blank=True)
    shipping_state = models.CharField(max_length=100, blank=True)
    shipping_pincode = models.CharField(max_length=10, blank=True)
    same_as_billing = models.BooleanField(default=True)

    assigned_agent = models.ForeignKey(
        "agents.AgentProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_customers",
    )

    # Credit management
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    credit_utilized = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_terms_days = models.PositiveSmallIntegerField(default=30)
    auto_block_on_exceed = models.BooleanField(default=True)

    # Outstanding (denormalized for performance)
    total_outstanding = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    overdue_outstanding = models.DecimalField(
        max_digits=14, decimal_places=2, default=0
    )

    # Segmentation (auto-computed via periodic task)
    segment = models.CharField(
        max_length=15, choices=CustomerSegment.choices, default=CustomerSegment.BRONZE
    )
    status = models.CharField(
        max_length=15, choices=CustomerStatus.choices, default=CustomerStatus.ACTIVE
    )

    internal_notes = models.TextField(blank=True)

    class Meta:
        db_table = "customers_profile"
        indexes = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["gstin"]),
            models.Index(fields=["assigned_agent"]),
        ]

    def __str__(self):
        return f"{self.business_name} ({self.company.name})"

    @property
    def credit_utilization_pct(self):
        if self.credit_limit > 0:
            return round((self.credit_utilized / self.credit_limit) * 100, 1)
        return 0


class CustomerDocument(CompanyScopeModel):
    class DocType(models.TextChoices):
        GST_CERT = "gst_cert", "GST Certificate"
        PAN_CARD = "pan_card", "PAN Card"
        AADHAR = "aadhar", "Aadhar Card"
        TRADE_LIC = "trade_lic", "Trade License"
        OTHER = "other", "Other"

    customer = models.ForeignKey(
        CustomerProfile, on_delete=models.CASCADE, related_name="documents"
    )
    doc_type = models.CharField(max_length=20, choices=DocType.choices)
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="customer/docs/%Y/%m/")
    uploaded_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "customers_document"


class CustomerCommunicationLog(CompanyScopeModel):
    class ChannelType(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "Email"
        CALL = "call", "Phone Call"
        VISIT = "visit", "Visit"
        SMS = "sms", "SMS"

    customer = models.ForeignKey(
        CustomerProfile, on_delete=models.CASCADE, related_name="communication_logs"
    )
    channel = models.CharField(max_length=15, choices=ChannelType.choices)
    subject = models.CharField(max_length=200, blank=True)
    message = models.TextField()
    performed_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL, null=True
    )

    class Meta:
        db_table = "customers_communication_log"
        ordering = ["-created_at"]
