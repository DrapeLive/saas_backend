from decimal import Decimal

from django.db.models import DecimalField, Sum, Value
from django.db.models.functions import Coalesce

from apps.agents.models import AgentCreditLimit
from apps.invoices.models import Invoice, InvoiceType
from apps.orders.models import Order, OrderStatus

# Invoice statuses that mean the customer still owes money.
UNPAID_INVOICE_STATUSES = ("issued", "partial")


def compute_agent_credit_utilized(agent_id, company_id):
    """
    Aggregate amount the agent's customers still owe across orders the agent
    booked: SUM(invoice.amount_due) for unpaid invoices on those orders.
    Returns Decimal.
    """
    agg = (
        Invoice.objects.filter(
            company_id=company_id,
            order__agent_id=agent_id,
            status__in=UNPAID_INVOICE_STATUSES,
        )
        .exclude(invoice_type=InvoiceType.PURCHASE_ORDER)
        .aggregate(total=Sum("amount_due"))["total"]
        or Decimal("0.00")
    )
    return agg


def get_or_create_agent_credit(agent_id, company_id):
    agent_credit, _ = AgentCreditLimit.objects.get_or_create(
        company_id=company_id, agent_id=agent_id
    )
    return agent_credit


def recompute_agent_credit(agent_id, company_id):
    """
    Rebuild the agent's credit_utilized from live unpaid invoices and return
    the AgentCreditLimit row (creating it if it does not exist).
    """
    agent_credit = get_or_create_agent_credit(agent_id, company_id)
    utilized = compute_agent_credit_utilized(agent_id, company_id)
    if agent_credit.credit_utilized != utilized:
        agent_credit.credit_utilized = utilized
        agent_credit.save(update_fields=["credit_utilized", "updated_at"])
    return agent_credit


def recompute_agent_metrics(agent_profile, company=None):
    """
    Rebuild an agent's denormalized performance fields from their live orders
    (cancellations excluded):

    - total_sales: lifetime sum of order totals across all companies.
    - total_orders: lifetime count of non-cancelled orders.
    - leaderboard_rank: rank within `company` by lifetime sales (1-based),
      or left untouched when no company context is given.

    Call after order creation/cancellation.
    """
    orders = Order.objects.filter(agent=agent_profile).exclude(
        status=OrderStatus.CANCELLED
    )
    total_sales = (
        orders.aggregate(
            total=Coalesce(
                Sum("total_amount"),
                Value(0),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )["total"]
        or Decimal("0.00")
    )
    total_orders = orders.count()

    fields = []
    if agent_profile.total_sales != total_sales:
        agent_profile.total_sales = total_sales
        fields.append("total_sales")
    if agent_profile.total_orders != total_orders:
        agent_profile.total_orders = total_orders
        fields.append("total_orders")

    if company is not None:
        rank = _agent_leaderboard_rank(agent_profile.id, company)
        if agent_profile.leaderboard_rank != rank:
            agent_profile.leaderboard_rank = rank
            fields.append("leaderboard_rank")

    if fields:
        agent_profile.save(update_fields=[*fields, "updated_at"])
    return agent_profile


def _agent_leaderboard_rank(agent_id, company):
    """Return the 1-based rank of the agent within the company by lifetime
    sales (cancellations excluded), or None if the agent has no orders."""
    ranking = (
        Order.objects.filter(company=company, agent__isnull=False)
        .exclude(status=OrderStatus.CANCELLED)
        .values("agent_id")
        .annotate(
            total=Coalesce(
                Sum("total_amount"),
                Value(0),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )
        .order_by("-total")
    )
    for i, entry in enumerate(ranking, start=1):
        if entry["agent_id"] == agent_id:
            return i
    return None
