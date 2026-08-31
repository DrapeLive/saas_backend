from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.agents.services import recompute_agent_credit
from apps.commissions.models import CommissionEntry, CommissionPayout
from apps.invoices.models import Invoice
from apps.orders.models import Order
from apps.payments.models import Payment


def _paid_ytd(agent, company, today):
    return (
        Payment.objects.filter(
            agent=agent, company=company, payment_date__year=today.year
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0.00")
    )


def _agent_order_ids(agent, company):
    return Order.objects.filter(agent=agent, company=company).values_list(
        "pk", flat=True
    )


def agent_overview(agent, company, today=None):
    """All tab: credit cards + recent transactions + invoice tally placeholder."""
    today = today or date.today()

    credit = recompute_agent_credit(agent.id, company.id)
    paid_total = _paid_ytd(agent, company, today)

    orders = Order.objects.filter(agent=agent, company=company)
    order_ids = _agent_order_ids(agent, company)

    pending_orders = orders.exclude(sync_status="synced").count()
    pending_invoices = (
        Invoice.objects.filter(company=company, order_id__in=order_ids)
        .exclude(status__in=("paid", "void"))
        .filter(tally_synced_at__isnull=True)
        .count()
    )
    pending_payments = (
        Payment.objects.filter(agent=agent, company=company, is_from_tally=False).count()
    )

    return {
        "agent_id": str(agent.id),
        "agent_name": agent.user.full_name,
        "credit": {
            "credit_limit": credit.credit_limit,
            "credit_utilized": credit.credit_utilized,
            "available_limit": max(
                Decimal("0.00"), credit.credit_limit - credit.credit_utilized
            ),
            "credit_utilization_pct": credit.credit_utilization_pct,
            "is_credit_blocked": credit.is_credit_blocked,
        },
        "total_paid_ytd": paid_total,
        "pending_sync": {
            "orders": pending_orders,
            "invoices": pending_invoices,
            "payments": pending_payments,
        },
        "recent_transactions": agent_transactions(agent, company, limit=15),
        "invoice_tally": None,
    }


def agent_transactions(agent, company, type=None, month=None, status=None, limit=50):
    """Merged feed of payouts + commission entries (incl. adjustments)."""
    entries = []

    payouts = CommissionPayout.objects.filter(agent=agent, company=company)
    if month:
        payouts = payouts.filter(settlement_month=month)
    for p in payouts:
        if type and type != "payout":
            continue
        entries.append(
            {
                "type": "payout",
                "id": str(p.id),
                "date": (p.paid_at.date() if p.paid_at else p.settlement_month),
                "amount": p.amount,
                "status": "paid",
                "reference": p.settlement_month.isoformat(),
                "settlement_month": p.settlement_month,
            }
        )

    commissions = CommissionEntry.objects.filter(
        agent=agent, company=company
    ).select_related("order")
    if month:
        commissions = commissions.filter(settlement_month=month)
    if status:
        commissions = commissions.filter(status=status)

    for c in commissions:
        txn_type = "order_commission"
        if c.status == CommissionEntry.EntryStatus.ADJUSTED:
            txn_type = "adjustment"
        if type and type != txn_type:
            continue
        entries.append(
            {
                "type": txn_type,
                "id": str(c.id),
                "date": (c.created_at.date() if c.created_at else c.settlement_month),
                "amount": c.commission_amount,
                "status": c.status,
                "reference": c.order.order_number if c.order else None,
                "settlement_month": c.settlement_month,
            }
        )

    def sort_key(e):
        return (e["date"] or date.min, e["id"])

    entries.sort(key=sort_key, reverse=True)
    return entries[:limit]


def agent_commission(agent, company, month=None, status=None):
    qs = CommissionEntry.objects.filter(agent=agent, company=company).select_related(
        "order", "plan"
    )
    if month:
        qs = qs.filter(settlement_month=month)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("-created_at")


def agent_payouts(agent, company):
    return CommissionPayout.objects.filter(agent=agent, company=company).order_by(
        "-paid_at", "-created_at"
    )


def agent_adjustments(agent, company):
    return (
        CommissionEntry.objects.filter(
            agent=agent,
            company=company,
            status=CommissionEntry.EntryStatus.ADJUSTED,
        )
        .select_related("order")
        .order_by("-created_at")
    )
