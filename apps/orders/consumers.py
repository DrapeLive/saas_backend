"""WebSocket consumer for the agent order flow.

Protocol
--------
Connect: ``/ws/orders/?token=<jwt>&company_id=<uuid>``

Request::

    {"action": "order.add_item", "request_id": "...", "payload": {...}}

Response::

    {"action": "...", "request_id": "...", "ok": true, "data": {...}}
    {"action": "...", "request_id": "...", "ok": false, "error": {...}}

The consumer only coordinates transport concerns. Every business operation is
delegated to ``apps.orders.order_flow`` so REST and WebSocket behaviour is
identical.
"""

import json
import logging
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.timezone import now

from apps.agents.models import AgentCompanyMembership
from apps.companies.models import Company
from apps.orders import order_flow
from apps.orders.exceptions import OrderFlowError
from apps.orders.models import Order, OrderStatus
from apps.orders.realtime import (
    agent_group,
    broadcast_order_expired,
    broadcast_order_updated,
    broadcast_stock_updates,
    company_group,
)
from apps.orders.serializers import OrderDetailSerializer, OrderListSerializer

logger = logging.getLogger(__name__)


class OrderConsumer(AsyncJsonWebsocketConsumer):
    @classmethod
    async def encode_json(cls, content):
        return json.dumps(content, cls=DjangoJSONEncoder)

    async def connect(self):
        self.user = None
        self.agent = None
        self.company = None
        self.created_orders = set()

        params = parse_qs(self.scope.get("query_string", b"").decode())
        token = (params.get("token") or [""])[0]
        company_id = (params.get("company_id") or [""])[0]

        try:
            self.user, self.agent, self.company = await self._authenticate(
                token, company_id
            )
        except OrderFlowError as exc:
            await self.accept()
            await self.send_json(
                {"event": "error", "ok": False, "error": exc.as_dict()}
            )
            await self.close(code=4401 if exc.status_code == 401 else 4403)
            return
        except Exception:
            logger.exception("WebSocket authentication failed")
            await self.accept()
            await self.close(code=4401)
            return

        self.agent_group_name = agent_group(self.agent.id)
        self.company_group_name = company_group(self.company.id)
        await self.channel_layer.group_add(self.agent_group_name, self.channel_name)
        await self.channel_layer.group_add(self.company_group_name, self.channel_name)
        await self.accept()

        drafts = await self._drafts_payload()
        await self.send_json(
            {
                "event": "connected",
                "data": {
                    "user_id": str(self.user.id),
                    "agent_id": str(self.agent.id),
                    "company_id": str(self.company.id),
                    "draft_ttl_seconds": settings.ORDER_DRAFT_TTL_SECONDS,
                    "empty_draft_ttl_seconds": settings.ORDER_EMPTY_DRAFT_TTL_SECONDS,
                    "drafts": drafts,
                },
            }
        )

    async def disconnect(self, code):
        if getattr(self, "agent_group_name", None):
            await self.channel_layer.group_discard(
                self.agent_group_name, self.channel_name
            )
        if getattr(self, "company_group_name", None):
            await self.channel_layer.group_discard(
                self.company_group_name, self.channel_name
            )
        if self.agent is not None and self.created_orders:
            await self._shorten_empty_drafts(list(self.created_orders))

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    @database_sync_to_async
    def _authenticate(self, token, company_id):
        from rest_framework_simplejwt.exceptions import TokenError
        from rest_framework_simplejwt.tokens import AccessToken

        if not token:
            raise OrderFlowError(
                "Authentication token is required.",
                code="TOKEN_REQUIRED",
                status_code=401,
            )
        try:
            validated = AccessToken(token)
        except TokenError as exc:
            raise OrderFlowError(
                "Invalid or expired token.",
                code="INVALID_TOKEN",
                status_code=401,
            ) from exc

        user_id = validated.get("user_id")
        User = get_user_model()
        try:
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError):
            raise OrderFlowError(
                "User not found.", code="USER_NOT_FOUND", status_code=401
            ) from None
        if not user.is_active:
            raise OrderFlowError(
                "User account is disabled.",
                code="USER_DISABLED",
                status_code=401,
            )
        if user.role != "agent":
            raise OrderFlowError(
                "Only agents can connect to the order socket.",
                code="AGENT_ONLY",
                status_code=403,
            )
        agent = getattr(user, "agent_profile", None)
        if agent is None:
            raise OrderFlowError(
                "Agent profile not found.", code="AGENT_NOT_FOUND", status_code=403
            )

        resolved_company_id = validated.get("company_id") or company_id
        if not resolved_company_id:
            raise OrderFlowError(
                "company_id is required.",
                code="COMPANY_REQUIRED",
                status_code=403,
            )
        membership = (
            AgentCompanyMembership.objects.select_related("company")
            .filter(agent=agent, company_id=resolved_company_id, status="active")
            .first()
        )
        if membership is None:
            raise OrderFlowError(
                "Agent is not an active member of this company.",
                code="COMPANY_FORBIDDEN",
                status_code=403,
            )
        company = Company.objects.get(pk=resolved_company_id)
        return user, agent, company

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @database_sync_to_async
    def _serialize_order(self, order):
        order = Order.objects.select_related(
            "customer", "agent__user", "approved_by", "company"
        ).prefetch_related("items", "status_history", "signature", "invoices").get(
            pk=order.pk
        )
        return OrderDetailSerializer(order).data

    @database_sync_to_async
    def _drafts_payload(self):
        order_flow.expire_draft_orders(
            company=self.company, agent=self.agent
        )
        queryset = order_flow.list_draft_orders(self.company, self.agent)
        return OrderDetailSerializer(queryset, many=True).data

    @database_sync_to_async
    def _get_order(self, order_id):
        return order_flow.get_agent_order(order_id, self.company, self.agent)

    @database_sync_to_async
    def _shorten_empty_drafts(self, order_ids):
        from datetime import timedelta

        Order.objects.filter(
            pk__in=order_ids,
            company=self.company,
            agent=self.agent,
            status=OrderStatus.DRAFT,
        ).filter(items__isnull=True).update(
            draft_expires_at=now() + timedelta(seconds=30)
        )

    async def _run(self, request_id, action, operation):
        try:
            data = await operation()
        except OrderFlowError as exc:
            await self.send_json(
                {
                    "action": action,
                    "request_id": request_id,
                    "ok": False,
                    "error": exc.as_dict(),
                }
            )
        except Exception:
            logger.exception("WebSocket action %s failed", action)
            await self.send_json(
                {
                    "action": action,
                    "request_id": request_id,
                    "ok": False,
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Something went wrong. Please try again.",
                        "fields": {},
                    },
                }
            )
        else:
            await self.send_json(
                {
                    "action": action,
                    "request_id": request_id,
                    "ok": True,
                    "data": data,
                }
            )

    # ------------------------------------------------------------------
    # Receive / dispatch
    # ------------------------------------------------------------------

    async def receive_json(self, content, **kwargs):
        action = content.get("action") or ""
        request_id = content.get("request_id")
        payload = content.get("payload") or {}

        handler = getattr(self, f"handle_{action.replace('.', '_')}", None)
        if handler is None:
            await self.send_json(
                {
                    "action": action,
                    "request_id": request_id,
                    "ok": False,
                    "error": {
                        "code": "UNKNOWN_ACTION",
                        "message": f"Unknown action '{action}'.",
                        "fields": {},
                    },
                }
            )
            return

        await handler(request_id, action, payload)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def handle_order_create(self, request_id, action, payload):
        async def operation():
            order = await database_sync_to_async(order_flow.create_draft_order)(
                self.company, self.agent, self.user, payload
            )
            self.created_orders.add(order.id)
            await database_sync_to_async(broadcast_order_updated)(order)
            return await self._serialize_order(order)

        await self._run(request_id, action, operation)

    async def handle_order_add_item(self, request_id, action, payload):
        async def operation():
            order_id = payload.get("order_id")
            order = await self._get_order(order_id)
            order, group_id, stock_updates, created = await database_sync_to_async(
                order_flow.add_item_to_draft
            )(order, self.user, payload)
            if created:
                await database_sync_to_async(broadcast_order_updated)(order)
                await database_sync_to_async(broadcast_stock_updates)(
                    self.company.id, stock_updates
                )
            return {
                "order": await self._serialize_order(order),
                "group_id": str(group_id),
                "stock_updates": stock_updates,
                "created": created,
            }

        await self._run(request_id, action, operation)

    async def handle_order_remove_item(self, request_id, action, payload):
        async def operation():
            order = await self._get_order(payload.get("order_id"))
            order, stock_updates = await database_sync_to_async(
                order_flow.remove_item_from_draft
            )(
                order,
                self.user,
                payload.get("item_id"),
                scope=payload.get("scope", "group"),
            )
            await database_sync_to_async(broadcast_order_updated)(order)
            await database_sync_to_async(broadcast_stock_updates)(
                self.company.id, stock_updates
            )
            return {
                "order": await self._serialize_order(order),
                "stock_updates": stock_updates,
            }

        await self._run(request_id, action, operation)

    async def handle_order_update_item(self, request_id, action, payload):
        async def operation():
            order = await self._get_order(payload.get("order_id"))
            order, stock_updates = await database_sync_to_async(
                order_flow.update_item_quantity
            )(
                order,
                self.user,
                payload.get("item_id"),
                payload.get("quantity"),
            )
            await database_sync_to_async(broadcast_order_updated)(order)
            await database_sync_to_async(broadcast_stock_updates)(
                self.company.id, stock_updates
            )
            return {
                "order": await self._serialize_order(order),
                "stock_updates": stock_updates,
            }

        await self._run(request_id, action, operation)

    async def handle_order_discard(self, request_id, action, payload):
        async def operation():
            order = await self._get_order(payload.get("order_id"))
            order_id, agent_id = await database_sync_to_async(
                order_flow.discard_draft
            )(order, self.user)
            self.created_orders.discard(order_id)
            await database_sync_to_async(broadcast_order_expired)(
                order_id, agent_id, self.company.id
            )
            return {"order_id": str(order_id)}

        await self._run(request_id, action, operation)

    async def handle_order_submit(self, request_id, action, payload):
        async def operation():
            order = await self._get_order(payload.get("order_id"))
            order = await database_sync_to_async(order_flow.submit_draft)(
                order, self.user, payload
            )
            self.created_orders.discard(order.id)
            await database_sync_to_async(broadcast_order_updated)(order)
            return await self._serialize_order(order)

        await self._run(request_id, action, operation)

    async def handle_order_get(self, request_id, action, payload):
        async def operation():
            order = await self._get_order(payload.get("order_id"))
            return await self._serialize_order(order)

        await self._run(request_id, action, operation)

    async def handle_order_drafts(self, request_id, action, payload):
        await self._run(request_id, action, self._drafts_payload)

    async def handle_order_list(self, request_id, action, payload):
        async def operation():
            return await database_sync_to_async(self._list_orders)(payload)

        await self._run(request_id, action, operation)

    def _list_orders(self, payload):
        order_flow.expire_draft_orders(company=self.company, agent=self.agent)
        queryset = Order.objects.filter(
            company=self.company, agent=self.agent
        ).select_related("customer", "agent__user").prefetch_related("items")
        status_filter = payload.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        elif not payload.get("include_drafts"):
            queryset = queryset.exclude(status=OrderStatus.DRAFT)
        return OrderListSerializer(queryset.order_by("-created_at"), many=True).data

    async def handle_order_ping(self, request_id, action, payload):
        await self.send_json(
            {
                "action": action,
                "request_id": request_id,
                "ok": True,
                "data": {"server_time": now().isoformat()},
            }
        )

    # ------------------------------------------------------------------
    # Group event relay
    # ------------------------------------------------------------------

    async def order_event(self, event):
        await self.send_json(
            {
                "event": event["event"],
                "data": event["data"],
            }
        )
