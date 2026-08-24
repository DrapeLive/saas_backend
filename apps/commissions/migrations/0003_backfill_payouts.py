from django.db import migrations
from django.db.models import Count, Sum


def backfill_payouts(apps, schema_editor):
    CommissionEntry = apps.get_model("commissions", "CommissionEntry")
    CommissionPayout = apps.get_model("commissions", "CommissionPayout")

    # Stamp missing settlement months from paid_at so entries and payouts agree.
    for entry in CommissionEntry.objects.filter(
        status="paid", settlement_month__isnull=True
    ).iterator():
        if entry.paid_at:
            entry.settlement_month = entry.paid_at.date().replace(day=1)
            entry.save(update_fields=["settlement_month"])

    groups = (
        CommissionEntry.objects.filter(status="paid")
        .values("company_id", "agent_id", "settlement_month")
        .annotate(total=Sum("commission_amount"), count=Count("id"))
    )

    payouts = []
    for g in groups:
        if not g["settlement_month"] or not g["count"]:
            continue
        last = (
            CommissionEntry.objects.filter(
                company_id=g["company_id"],
                agent_id=g["agent_id"],
                status="paid",
                settlement_month=g["settlement_month"],
            )
            .order_by("-paid_at", "-created_at")
            .first()
        )
        payouts.append(
            CommissionPayout(
                company_id=g["company_id"],
                agent_id=g["agent_id"],
                settlement_month=g["settlement_month"],
                amount=g["total"] or 0,
                entries_count=g["count"],
                paid_at=last.paid_at if last else None,
                paid_by_id=last.paid_by_id if last else None,
            )
        )
    CommissionPayout.objects.bulk_create(payouts)


def remove_backfilled_payouts(apps, schema_editor):
    CommissionPayout = apps.get_model("commissions", "CommissionPayout")
    CommissionPayout.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("commissions", "0002_commissionpayout"),
    ]

    operations = [
        migrations.RunPython(backfill_payouts, remove_backfilled_payouts),
    ]
