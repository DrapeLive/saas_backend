# -*- coding: utf-8 -*-
from django.db import migrations


def convert_old_statuses(apps, schema_editor):
    CommissionEntry = apps.get_model("commissions", "CommissionEntry")
    # Map all legacy statuses to the new two-value set.
    CommissionEntry.objects.filter(
        status__in=["pending", "approved", "disputed", "adjusted"]
    ).update(status="not_paid")


def reverse_convert_old_statuses(apps, schema_editor):
    # Reverse is intentionally a no-op: we cannot reliably reconstruct
    # the original five-way status from the simplified two-value set.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("commissions", "0005_simplify_commission_status"),
    ]

    operations = [
        migrations.RunPython(convert_old_statuses, reverse_convert_old_statuses),
    ]
