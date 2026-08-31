from decimal import Decimal

from django.db.models import Sum

from apps.agents.models import AgentCreditLimit
from apps.invoices.models import Invoice

# Invoice statuses that mean the customer still owes money.
UNPAID_INVOICE_STATUSES = ("issued", "partial", "overdue")


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
        ).aggregate(total=Sum("amount_due"))["total"]
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
