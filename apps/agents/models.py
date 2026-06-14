from django.db import models

from apps.core.models import CompanyScopeModel, TimeStampedModel, UUIDModel


class AgentProfile(UUIDModel, TimeStampedModel):
    user = models.OneToOneField(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="agent_profile",
        limit_choices_to={"role": "agent"},
    )
    employee_code = models.CharField(max_length=20, blank=True)
    profile_bio = models.TextField(blank=True)

    # Performance meta
    total_sales = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total_orders = models.PositiveIntegerField(default=0)
    leaderboard_rank = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "agents_profile"

    def __str__(self):
        return f"Agent: {self.user.full_name}"


class AgentCompanyMembership(UUIDModel, TimeStampedModel):
    class MembershipStatus(models.TextChoices):
        PENDING = "pending", "Pending Approval"
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        REMOVED = "removed", "Removed"

    agent = models.ForeignKey(
        AgentProfile, on_delete=models.CASCADE, related_name="memberships"
    )
    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="agent_memberships"
    )
    status = models.CharField(
        max_length=15,
        choices=MembershipStatus.choices,
        default=MembershipStatus.PENDING,
    )

    custom_commission_plan = models.ForeignKey(
        "commissions.CommissionPlan",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )

    territory = models.CharField(max_length=200, blank=True)

    # Performance targets (set per company per agent)
    monthly_target = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    joined_at = models.DateTimeField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "agents_company_membership"
        unique_together = [("agent", "company")]
        indexes = [models.Index(fields=["status", "company"])]

    def __str__(self):
        return f"{self.agent.user.full_name} @ {self.company.name} [{self.status}]"


class AgentInvitation(UUIDModel, TimeStampedModel):
    class InviteStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        EXPIRED = "expired", "Expired"
        REVOKED = "revoked", "Revoked"

    class DeliveryMethod(models.TextChoices):
        WHATSAPP = "whatsapp", "WhatsApp"
        EMAIL = "email", "Email"
        QR_CODE = "qr_code", "QR Code"
        IN_APP = "in_app", "In-App"

    company = models.ForeignKey(
        "companies.Company", on_delete=models.CASCADE, related_name="agent_invitations"
    )
    invited_by = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="+"
    )
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=15, blank=True)
    token = models.CharField(max_length=64, unique=True)
    status = models.CharField(
        max_length=15, choices=InviteStatus.choices, default=InviteStatus.PENDING
    )
    delivery_method = models.CharField(max_length=15, choices=DeliveryMethod.choices)
    expires_at = models.DateTimeField()
    accepted_by = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_invitations",
    )

    class Meta:
        db_table = "agents_invitation"
        indexes = [models.Index(fields=["token", "status"])]


class AgentVisitLog(CompanyScopeModel):
    """
    Tracks agent customer visits for performance and activity monitoring.
    """

    agent = models.ForeignKey(
        AgentProfile, on_delete=models.CASCADE, related_name="visit_logs"
    )
    customer = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.CASCADE,
        related_name="agent_visits",
    )
    visit_date = models.DateField()
    notes = models.TextField(blank=True)
    order_placed = models.BooleanField(default=False)
    location_lat = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )
    location_lng = models.DecimalField(
        max_digits=10, decimal_places=7, null=True, blank=True
    )

    class Meta:
        db_table = "agents_visit_log"
        ordering = ["-visit_date"]
