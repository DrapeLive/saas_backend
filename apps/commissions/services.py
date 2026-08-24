from django.db.models import Count, Sum
from django.utils.timezone import now

from apps.commissions.models import CommissionEntry, CommissionPayout


def settlement_month_for(entry):
    """
    Resolve the payout month for a commission entry: the explicit
    settlement_month, or the calendar month of paid_at as fallback.
    Returns None when neither is available.
    """
    if entry.settlement_month:
        return entry.settlement_month
    if entry.paid_at:
        return entry.paid_at.date().replace(day=1)
    return None


def upsert_payout(agent_id, company_id, month, paid_by=None, notes=None):
    """
    Rebuild the monthly CommissionPayout snapshot for an agent from the
    PAID commission entries of that month. Safe to call repeatedly.
    """
    if month is None:
        return None

    paid_entries = CommissionEntry.objects.filter(
        company_id=company_id,
        agent_id=agent_id,
        status=CommissionEntry.EntryStatus.PAID,
        settlement_month=month,
    )
    agg = paid_entries.aggregate(
        total=Sum("commission_amount"), count=Count("id")
    )
    last_paid = paid_entries.order_by("-paid_at").first()

    if not agg["count"]:
        # No paid entries left in this month — drop the stale payout record.
        CommissionPayout.objects.filter(
            company_id=company_id, agent_id=agent_id, settlement_month=month
        ).delete()
        return None

    defaults = {
        "amount": agg["total"] or 0,
        "entries_count": agg["count"],
        "paid_at": last_paid.paid_at or now(),
    }
    if paid_by is not None:
        defaults["paid_by"] = paid_by
    elif last_paid.paid_by is not None:
        defaults["paid_by"] = last_paid.paid_by
    if notes:
        defaults["notes"] = notes

    payout, _ = CommissionPayout.objects.update_or_create(
        company_id=company_id,
        agent_id=agent_id,
        settlement_month=month,
        defaults=defaults,
    )
    return payout
