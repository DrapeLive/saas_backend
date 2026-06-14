from django.db import models

from apps.core.models import CompanyScopeModel


class Dispatch(CompanyScopeModel):
    """
    Dispatch/shipment record created when order is marked 'Dispatched'.
    Triggers: Sales Invoice generation + Tally sync + WhatsApp notification.
    """

    order = models.OneToOneField(
        "orders.Order", on_delete=models.CASCADE, related_name="dispatch"
    )
    lr_number = models.CharField(max_length=50, blank=True)
    transport_name = models.CharField(max_length=200, blank=True)
    vehicle_number = models.CharField(max_length=20, blank=True)
    driver_contact = models.CharField(max_length=15, blank=True)
    dispatch_date = models.DateField()
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
