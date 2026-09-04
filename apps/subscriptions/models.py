from datetime import timedelta
from typing import ClassVar

from django.db import models

from apps.core.models import TimeStampedModel, UUIDModel


class PlanTier(models.TextChoices):
    FREE = "free", "Free"
    STARTER = "starter", "Starter"
    PROFESSIONAL = "professional", "Professional"
    ENTERPRISE = "enterprise", "Enterprise"


class BillingCycle(models.TextChoices):
    MONTHLY = "monthly", "Monthly"
    YEARLY = "yearly", "Yearly"
    TRIAL = "trial", "Trial"


class SubscriptionStatus(models.TextChoices):
    TRIAL = "trial", "Trial"
    ACTIVE = "active", "Active"
    GRACE = "grace", "Grace Period"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"
    SUSPENDED = "suspended", "Suspended"


class Plan(UUIDModel, TimeStampedModel):
    tier = models.CharField(max_length=20, choices=PlanTier.choices, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    monthly_price = models.DecimalField(max_digits=10, decimal_places=2)
    yearly_price = models.DecimalField(max_digits=10, decimal_places=2)
    trial_days = models.PositiveSmallIntegerField(default=14)

    max_agents = models.PositiveIntegerField(
        default=3, help_text="0 = unlimited (Enterprise)"
    )
    max_customers = models.PositiveIntegerField(default=100, help_text="0 = unlimited")
    max_products = models.PositiveIntegerField(default=500, help_text="0 = unlimited")
    max_orders_per_month = models.PositiveIntegerField(
        default=200, help_text="0 = unlimited"
    )
    storage_gb = models.PositiveIntegerField(
        default=50, help_text="Storage in GB for product images and documents"
    )

    # Feature flags (unlocked by tier)
    tally_sync_enabled = models.BooleanField(default=False)
    whatsapp_enabled = models.BooleanField(default=False)
    gst_verify_enabled = models.BooleanField(default=False)
    analytics_advanced = models.BooleanField(default=False)
    offline_mode_enabled = models.BooleanField(default=False)
    api_access_enabled = models.BooleanField(default=False)
    custom_domain_enabled = models.BooleanField(default=False)
    dedicated_support = models.BooleanField(default=False)

    is_active = models.BooleanField(default=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "subscriptions_plan"
        ordering: ClassVar[list[str]] = ["display_order"]

    def __str__(self):
        return f"{self.name} — ₹{self.monthly_price}/mo"

    @classmethod
    def get_defaults(cls):
        return [
            {
                "tier": PlanTier.FREE,
                "name": "Free",
                "monthly_price": 0,
                "yearly_price": 0,
                "trial_days": 0,
                "max_agents": 1,
                "max_customers": 50,
                "max_products": 100,
                "max_orders_per_month": 50,
                "storage_gb": 10,
                "tally_sync_enabled": False,
                "whatsapp_enabled": False,
                "display_order": 0,
            },
            {
                "tier": PlanTier.STARTER,
                "name": "Starter",
                "monthly_price": 1999,
                "yearly_price": 19990,
                "trial_days": 14,
                "max_agents": 3,
                "max_customers": 100,
                "max_products": 500,
                "max_orders_per_month": 200,
                "storage_gb": 50,
                "tally_sync_enabled": False,
                "whatsapp_enabled": False,
                "display_order": 1,
            },
            {
                "tier": PlanTier.PROFESSIONAL,
                "name": "Professional",
                "monthly_price": 4999,
                "yearly_price": 49990,
                "trial_days": 14,
                "max_agents": 10,
                "max_customers": 500,
                "max_products": 2000,
                "max_orders_per_month": 1000,
                "storage_gb": 200,
                "tally_sync_enabled": True,
                "whatsapp_enabled": True,
                "gst_verify_enabled": True,
                "analytics_advanced": True,
                "offline_mode_enabled": True,
                "display_order": 2,
            },
            {
                "tier": PlanTier.ENTERPRISE,
                "name": "Enterprise",
                "monthly_price": 9999,
                "yearly_price": 99990,
                "trial_days": 14,
                "max_agents": 0,
                "max_customers": 0,
                "max_products": 0,
                "max_orders_per_month": 0,
                "storage_gb": 1024,
                "tally_sync_enabled": True,
                "whatsapp_enabled": True,
                "gst_verify_enabled": True,
                "analytics_advanced": True,
                "offline_mode_enabled": True,
                "api_access_enabled": True,
                "custom_domain_enabled": True,
                "dedicated_support": True,
                "display_order": 3,
            },
        ]


class Subscription(UUIDModel, TimeStampedModel):
    plan = models.ForeignKey(
        Plan, on_delete=models.PROTECT, related_name="subscriptions"
    )
    billing_cycle = models.CharField(
        max_length=10, choices=BillingCycle.choices, default=BillingCycle.TRIAL
    )
    status = models.CharField(
        max_length=15,
        choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.TRIAL,
    )

    trial_start = models.DateField(null=True, blank=True)
    trial_end = models.DateField(null=True, blank=True)
    current_period_start = models.DateField(null=True, blank=True)
    current_period_end = models.DateField(null=True, blank=True)
    grace_period_end = models.DateField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    price_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)

    # Engagement score (used for trial extension decisions)
    engagement_score = models.FloatField(default=0.0)

    # Notes by SuperAdmin
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "subscriptions_subscription"
        indexes: ClassVar = [
            models.Index(fields=["status", "current_period_end"]),
        ]

    def __str__(self):
        return f"Sub [{self.plan.tier}] status={self.status}"

    @property
    def is_usable(self):
        return self.status in (
            SubscriptionStatus.TRIAL,
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.GRACE,
        )

    @property
    def cycle_days(self):
        """Number of days in the current billing cycle (30 monthly, 365 yearly)."""
        return 365 if self.billing_cycle == BillingCycle.YEARLY else 30

    def setup_periods(self, today=None):
        """
        Populate the subscription period fields from the current status, billing
        cycle and plan trial length.

        - TRIAL  → sets trial_start / trial_end (+ current period mirrors the trial)
        - ACTIVE → sets current_period_start / current_period_end from the cycle
        - GRACE  → sets current period + grace_period_end
        - others → clears all period fields
        """
        from django.utils.timezone import now

        from apps.subscriptions.models import SubscriptionStatus

        today = today or now().date()

        if self.status == SubscriptionStatus.TRIAL:
            self.trial_start = today
            self.trial_end = today + timedelta(days=self.plan.trial_days)
            self.current_period_start = today
            self.current_period_end = self.trial_end
            self.grace_period_end = None
            self.cancelled_at = None
            return

        if self.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE):
            self.trial_start = None
            self.trial_end = None
            self.current_period_start = today
            self.current_period_end = today + timedelta(days=self.cycle_days)
            if self.status == SubscriptionStatus.GRACE:
                self.grace_period_end = self.current_period_end + timedelta(days=7)
            else:
                self.grace_period_end = None
            self.cancelled_at = None
            return

        # CANCELLED / EXPIRED / SUSPENDED: clear active period fields
        self.trial_start = None
        self.trial_end = None
        self.current_period_start = None
        self.current_period_end = None
        self.grace_period_end = None


class SubscriptionEvent(UUIDModel):
    class EventType(models.TextChoices):
        CREATED = "created", "Created"
        UPGRADED = "upgraded", "Upgraded"
        DOWNGRADED = "downgraded", "Downgraded"
        RENEWED = "renewed", "Renewed"
        SUSPENDED = "suspended", "Suspended"
        GRACE = "grace", "Grace Period Started"
        EXPIRED = "expired", "Expired"
        CANCELLED = "cancelled", "Cancelled"
        EXTENDED = "extended", "Extended (Manual)"
        REACTIVATED = "reactivated", "Reactivated"

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    from_plan = models.ForeignKey(
        Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    to_plan = models.ForeignKey(
        Plan, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    performed_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )
    notes = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "subscriptions_event"
        ordering: ClassVar = ["-created_at"]


class UsageSnapshot(UUIDModel):
    """
    Monthly usage snapshot per company for limit enforcement and analytics.
    Captured via Celery task on 1st of every month.
    """

    subscription = models.ForeignKey(
        Subscription, on_delete=models.CASCADE, related_name="usage_snapshots"
    )
    snapshot_month = models.DateField(help_text="First day of the month")
    agent_count = models.PositiveIntegerField(default=0)
    customer_count = models.PositiveIntegerField(default=0)
    product_count = models.PositiveIntegerField(default=0)
    order_count = models.PositiveIntegerField(default=0)
    storage_used_mb = models.FloatField(default=0.0)

    class Meta:
        db_table = "subscriptions_usage_snapshot"
        unique_together: ClassVar = [("subscription", "snapshot_month")]
        ordering: ClassVar = ["-snapshot_month"]
