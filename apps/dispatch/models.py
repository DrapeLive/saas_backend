from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.models import CompanyScopeModel


class Transport(CompanyScopeModel):
    """Company-specific transport company used in the dispatch form."""

    name = models.CharField(max_length=200)
    tracking_url = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "dispatch_transport"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                "company",
                name="uniq_transport_company_name_ci",
            )
        ]

    def __str__(self):
        return self.name


class Dispatch(CompanyScopeModel):
    """
    Dispatch/shipment record created when order is marked 'Dispatched'.
    Triggers: Sales Invoice generation + Tally sync + WhatsApp notification.
    """

    order = models.OneToOneField(
        "orders.Order", on_delete=models.CASCADE, related_name="dispatch"
    )
    transport = models.ForeignKey(
        Transport,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="dispatches",
    )
    lr_number = models.CharField(max_length=50, blank=True)
    transport_name = models.CharField(max_length=200, blank=True)
    vehicle_number = models.CharField(max_length=20, blank=True)
    driver_contact = models.CharField(max_length=15, blank=True)
    dispatch_date = models.DateField(default=timezone.localdate)
    expected_delivery = models.DateField(null=True, blank=True)
    actual_delivery = models.DateField(null=True, blank=True)
    tracking_url = models.URLField(blank=True)
    eway_bill_no = models.CharField(max_length=20, blank=True)
    boxes_count = models.PositiveIntegerField(default=0)
    weight_kg = models.DecimalField(
        max_digits=8, decimal_places=2, null=True, blank=True
    )
    dispatched_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "dispatch_dispatch"
