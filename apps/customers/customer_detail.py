from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.invoices.models import Invoice, InvoiceStatus
from apps.orders.models import Order, OrderStatus
from apps.payments.models import Payment

UNPAID_STATUSES = (
    InvoiceStatus.ISSUED,
    InvoiceStatus.PARTIAL,
    InvoiceStatus.OVERDUE,
)

# Order statuses that represent a real, counted sale / active pipeline entry.
OPEN_ORDER_STATUSES = (
    OrderStatus.SUBMITTED,
    OrderStatus.CONFIRMED,
    OrderStatus.PROCESSING,
    OrderStatus.PACKED,
    OrderStatus.READY,
    OrderStatus.DISPATCHED,
    OrderStatus.DELIVERED,
    OrderStatus.ON_HOLD,
)


def _unpaid_invoices(customer):
    return Invoice.objects.filter(customer=customer, status__in=UNPAID_STATUSES)


def _aging_buckets(customer, today=None):
    """Return bucket amounts and percentages for 0-30 / 31-60 / 60+ days."""
    today = today or date.today()
    invoices = _unpaid_invoices(customer)
    buckets = {
        "days_0_30": Decimal("0.00"),
        "days_31_60": Decimal("0.00"),
        "days_60_plus": Decimal("0.00"),
    }
    for inv in invoices:
        if not inv.due_date:
            continue
        days = (today - inv.due_date).days
        if days < 0:
            continue
        if days <= 30:
            buckets["days_0_30"] += inv.amount_due
        elif days <= 60:
            buckets["days_31_60"] += inv.amount_due
        else:
            buckets["days_60_plus"] += inv.amount_due
    total = sum(buckets.values(), Decimal("0.00"))
    pct = (
        {
            key: round((amount / total) * 100, 1) if total > 0 else 0
            for key, amount in buckets.items()
        }
        if total > 0
        else {key: 0 for key in buckets}
    )
    return {
        "buckets": [
            {"bucket": "0-30", "amount": buckets["days_0_30"], "percentage": pct["days_0_30"]},
            {"bucket": "31-60", "amount": buckets["days_31_60"], "percentage": pct["days_31_60"]},
            {"bucket": "60+", "amount": buckets["days_60_plus"], "percentage": pct["days_60_plus"]},
        ],
        "total_outstanding": total,
        "credit_utilization_pct": customer.credit_utilization_pct,
        "credit_utilized": customer.credit_utilized,
        "credit_limit": customer.credit_limit,
        "available_limit": max(
            Decimal("0.00"), customer.credit_limit - customer.credit_utilized
        ),
    }


def _recent_activity(customer, limit=10):
    """Merge communication logs and agent visit logs, newest first."""
    from apps.customers.models import CustomerCommunicationLog

    entries = []
    for log in CustomerCommunicationLog.objects.filter(customer=customer)[:limit]:
        entries.append(
            {
                "type": "follow_up",
                "channel": log.channel,
                "text": log.message,
                "subject": log.subject,
                "date": log.created_at.date(),
            }
        )
    for visit in customer.agent_visits.all()[:limit]:
        entries.append(
            {
                "type": "agent_note",
                "channel": "visit",
                "text": visit.notes or "",
                "subject": "Agent visit",
                "date": visit.visit_date,
            }
        )
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:limit]


def _recent_payments(customer, limit=5):
    return [
        {
            "id": str(p.id),
            "date": p.payment_date,
            "amount": p.amount,
            "tally_sync_status": "synced" if p.is_from_tally else "pending",
        }
        for p in Payment.objects.filter(customer=customer).order_by("-payment_date")[:limit]
    ]


# ---------------------------------------------------------------------------
# Summary page
# ---------------------------------------------------------------------------
def customer_summary(customer):
    aging = _aging_buckets(customer)
    return {
        "id": str(customer.id),
        "name": customer.trade_name or customer.legal_name,
        "owner_name": customer.owner_name,
        "email": customer.email,
        "billing_address": {
            "line1": customer.billing_address_line1,
            "line2": customer.billing_address_line2,
            "city": customer.billing_city,
            "state": customer.billing_state,
            "pincode": customer.billing_pincode,
        },
        "shipping_address": {
            "line1": customer.shipping_address_line1,
            "line2": customer.shipping_address_line2,
            "city": customer.shipping_city,
            "state": customer.shipping_state,
            "pincode": customer.shipping_pincode,
            "same_as_billing": customer.same_as_billing,
        },
        "phone": customer.phone,
        "whatsapp_number": customer.whatsapp_number,
        "credit_utilization_pct": aging["credit_utilization_pct"],
        "credit_utilized": aging["credit_utilized"],
        "credit_limit": aging["credit_limit"],
        "available_limit": aging["available_limit"],
        "outstanding": {
            "buckets": aging["buckets"],
            "total_outstanding": aging["total_outstanding"],
        },
        "recent_activity": _recent_activity(customer),
        "recent_payments": _recent_payments(customer),
    }


# ---------------------------------------------------------------------------
# Orders page
# ---------------------------------------------------------------------------
def customer_orders(customer):
    counted = Order.objects.filter(
        customer=customer,
        status__in=OPEN_ORDER_STATUSES,
    )
    pending = counted.exclude(status=OrderStatus.DELIVERED)
    total_life = counted.exclude(status=OrderStatus.ON_HOLD).aggregate(
        s=Sum("total_amount")
    )["s"] or Decimal("0.00")

    life_orders = counted.exclude(status=OrderStatus.ON_HOLD)
    order_count = life_orders.count()
    avg_value = round(total_life / order_count, 2) if order_count else Decimal("0.00")

    recent = [
        {
            "id": str(o.id),
            "order_number": o.order_number,
            "date": o.created_at.date(),
            "amount": o.total_amount,
            "status": o.status,
            "sync_status": o.sync_status,
            "tally_synced_at": o.tally_synced_at,
        }
        for o in counted.order_by("-created_at")[:10]
    ]

    return {
        "lifetime_value": total_life,
        "pending_orders": pending.count(),
        "avg_order_value": avg_value,
        "recent_orders": recent,
        "tally_sync_status": {
            status: counted.filter(sync_status=status).count()
            for status in ("synced", "pending", "failed")
        },
    }


# ---------------------------------------------------------------------------
# Payments page
# ---------------------------------------------------------------------------
def _year_paid(customer, year):
    return (
        Payment.objects.filter(customer=customer, payment_date__year=year).aggregate(
            s=Sum("amount")
        )["s"]
        or Decimal("0.00")
    )


def customer_payments(customer, today=None):
    today = today or date.today()
    ytd = _year_paid(customer, today.year)

    # Compare YTD window only: prior-year same number of elapsed days is
    # approximated as full prior year amount scaled is overkill; report the
    # prior year-to-date by filtering to the same day-of-year for simplicity.
    start_prior = date(today.year - 1, 1, 1)
    prior_ytd = (
        Payment.objects.filter(
            customer=customer,
            payment_date__gte=start_prior,
            payment_date__lte=date(today.year - 1, today.month, today.day),
        ).aggregate(s=Sum("amount"))["s"]
        or Decimal("0.00")
    )

    if prior_ytd > 0:
        change_pct = round(((ytd - prior_ytd) / prior_ytd) * 100, 1)
    else:
        change_pct = None

    outstanding = (
        _unpaid_invoices(customer).aggregate(s=Sum("amount_due"))["s"]
        or Decimal("0.00")
    )

    recent = [
        {
            "id": str(p.id),
            "date": p.payment_date,
            "amount": p.amount,
            "type": p.mode,
            "tally_sync_status": "synced" if p.is_from_tally else "pending",
        }
        for p in Payment.objects.filter(customer=customer).order_by("-payment_date")[:10]
    ]

    upcoming = _upcoming_payment(customer, today)

    return {
        "total_paid": ytd,
        "paid_change_pct": change_pct,
        "outstanding": outstanding,
        "recent_transactions": recent,
        "upcoming_payment": upcoming,
    }


def _upcoming_payment(customer, today=None):
    today = today or date.today()
    inv = (
        _unpaid_invoices(customer)
        .filter(due_date__isnull=False)
        .order_by("due_date")
        .first()
    )
    if not inv:
        return None
    return {
        "invoice_id": str(inv.id),
        "invoice_number": inv.invoice_number,
        "amount": inv.amount_due,
        "due_date": inv.due_date,
        "days_overdue": max(0, (today - inv.due_date).days) if inv.due_date < today else 0,
    }


# ---------------------------------------------------------------------------
# Outstanding page
# ---------------------------------------------------------------------------
def customer_outstanding(customer, today=None):
    today = today or date.today()

    total_paid_ytd = (
        Payment.objects.filter(customer=customer, payment_date__year=today.year).aggregate(
            s=Sum("amount")
        )["s"]
        or Decimal("0.00")
    )

    last_payment = Payment.objects.filter(customer=customer).order_by(
        "-payment_date"
    ).first()

    aging = _aging_buckets(customer, today)

    # Average pay days: mean of (payment_date - invoice_date) for payments
    # that reference an invoice (computed in Python for cross-backend safety).
    pay_days = [
        (p.payment_date - p.invoice.invoice_date).days
        for p in Payment.objects.filter(
            customer=customer, invoice__isnull=False
        ).select_related("invoice")
    ]
    avg_pay_days = round(sum(pay_days) / len(pay_days)) if pay_days else 0

    critical = []
    for inv in _unpaid_invoices(customer).filter(due_date__lt=today).order_by("due_date"):
        critical.append(
            {
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "amount": inv.amount_due,
                "due_date": inv.due_date,
                "days_past_due": (today - inv.due_date).days,
            }
        )

    return {
        "total_paid_ytd": total_paid_ytd,
        "total_outstanding": aging["total_outstanding"],
        "last_payment_date": last_payment.payment_date if last_payment else None,
        "credit_utilization_pct": aging["credit_utilization_pct"],
        "available_limit": aging["available_limit"],
        "avg_pay_days": avg_pay_days,
        "aging_analysis": aging["buckets"],
        "critical_invoices": critical,
    }
