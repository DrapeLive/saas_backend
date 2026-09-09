from django.db import models

from apps.core.models import CompanyScopeModel, TimeStampedModel, UUIDModel


class CategoryCommissionRate(CompanyScopeModel):
    """
    Commission rate for a product category within a company.
    e.g., Mens=2%, Kids=3%, Ladies=4%
    """

    category = models.ForeignKey("products.Category", on_delete=models.CASCADE)
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        db_table = "commissions_category_rate"
        unique_together = [("company", "category")]


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
        return f"{self.agent} — {self.settlement_month:%Y-%m}: {self.amount}"
