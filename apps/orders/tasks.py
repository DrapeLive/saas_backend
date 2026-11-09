import logging

from celery import shared_task

from apps.orders.order_flow import expire_draft_orders
from apps.orders.realtime import broadcast_order_expired

logger = logging.getLogger(__name__)


@shared_task
def expire_drafts_task(batch_size=500):
    """Delete expired DRAFT orders and notify connected agents."""
    expired = expire_draft_orders(batch_size=batch_size)
    for order_id, agent_id, company_id in expired:
        broadcast_order_expired(order_id, agent_id, company_id)
    if expired:
        logger.info("Expired %s draft order(s)", len(expired))
    return len(expired)
