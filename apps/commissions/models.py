from django.db import models

from apps.core.models import CompanyScopeModel, TimeStampedModel, UUIDModel


class CommissionPlan(CompanyScopeModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "commissions_plan"

    def __str__(self):
        return f"{self.name} ({self.company.name})"


class CommissionSlab(UUIDModel, TimeStampedModel):
    """
    Tiered slab within a CommissionPlan.
    e.g., 0–₹1L → 2%, ₹1L–₹5L → 3%, Above ₹5L → 5%
    """

    plan = models.ForeignKey(
        CommissionPlan, on_delete=models.CASCADE, related_name="slabs"
    )
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        db_table = "commissions_slab"
        ordering = ["min_amount"]


class CategoryCommissionRate(UUIDModel, TimeStampedModel):
    """
    Category-specific commission override within a plan.
    e.g., Mens=2%, Kids=3%, Ladies=4%
    """

    plan = models.ForeignKey(
        CommissionPlan, on_delete=models.CASCADE, related_name="category_rates"
    )
    category = models.ForeignKey("products.Category", on_delete=models.CASCADE)
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        db_table = "commissions_category_rate"
        unique_together = [("plan", "category")]


class CommissionEntry(CompanyScopeModel):
    """
    Commission earned per order per agent.
    Created when order is dispatched; settled monthly.
    """

    class EntryStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        PAID = "paid", "Paid"
        DISPUTED = "disputed", "Disputed"
        ADJUSTED = "adjusted", "Adjusted"

    agent = models.ForeignKey(
        "agents.AgentProfile", on_delete=models.CASCADE, related_name="commissions"
    )
    order = models.OneToOneField(
        "orders.Order", on_delete=models.CASCADE, related_name="commission"
    )
    plan = models.ForeignKey(CommissionPlan, null=True, on_delete=models.SET_NULL)

    order_value = models.DecimalField(max_digits=14, decimal_places=2)
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=15, choices=EntryStatus.choices, default=EntryStatus.PENDING
    )

    settlement_month = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )

    dispute_reason = models.TextField(blank=True)
    adjustment_notes = models.TextField(blank=True)

    class Meta:
        db_table = "commissions_entry"
        indexes = [
            models.Index(fields=["agent", "status", "settlement_month"]),
        ]


class CommissionPayout(CompanyScopeModel):
    """
    Monthly payout snapshot per agent. Created/updated automatically
    whenever commission entries are marked PAID for a settlement month.
    """

    agent = models.ForeignKey(
        "agents.AgentProfile", on_delete=models.CASCADE, related_name="payouts"
    )
    settlement_month = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    entries_count = models.PositiveIntegerField(default=0)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "commissions_payout"
        ordering = ["-paid_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "agent", "settlement_month"],
                name="unique_payout_per_agent_month",
            )
        ]
        indexes = [
            models.Index(fields=["company", "paid_at"]),
        ]

    def __str__(self):
        return (
            f"{self.agent} — {self.settlement_month:%Y-%m}: {self.amount}"
        )
