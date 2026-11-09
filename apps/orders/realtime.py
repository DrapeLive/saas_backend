"""Channel-layer broadcasts for the order flow.

Broadcasts are best-effort: when no channel layer is configured (for example
during unit tests) they become no-ops instead of breaking the request.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


def _group_name(prefix, value):
    return f"{prefix}_{str(value).replace('-', '')}"


def agent_group(agent_id):
    return _group_name("agent", agent_id)


def company_group(company_id):
    return _group_name("company", company_id)


def _send(group, event, data):
    layer = get_channel_layer()
    if layer is None:
        return
    try:
        async_to_sync(layer.group_send)(
            group,
            {
                "type": "order.event",
                "event": event,
                "data": data,
            },
        )
    except Exception:  # pragma: no cover - realtime must never break a request
        logger.exception("Failed to broadcast %s to %s", event, group)


def broadcast_to_agent(agent_id, event, data):
    if agent_id:
        _send(agent_group(agent_id), event, data)


def broadcast_to_company(company_id, event, data):
    if company_id:
        _send(company_group(company_id), event, data)


def broadcast_stock_updates(company_id, stock_updates):
    if stock_updates:
        broadcast_to_company(
            company_id, "stock.updated", {"updates": stock_updates}
        )


def broadcast_order_updated(order):
    payload = {
        "order_id": str(order.id),
        "status": order.status,
        "total_amount": str(order.total_amount),
        "item_count": order.items.count(),
        "draft_expires_at": order.draft_expires_at.isoformat()
        if order.draft_expires_at
        else None,
    }
    broadcast_to_agent(order.agent_id, "order.updated", payload)
    broadcast_to_company(order.company_id, "order.updated", payload)


def broadcast_order_expired(order_id, agent_id, company_id):
    payload = {"order_id": str(order_id)}
    broadcast_to_agent(agent_id, "order.expired", payload)
    broadcast_to_company(company_id, "order.expired", payload)
