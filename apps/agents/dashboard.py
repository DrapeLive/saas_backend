"""Agent home dashboard + broadcast management views.

The agent home endpoints are company-scoped. The active company is resolved
from the JWT `company_id` claim or the `X-Company-Id` header via
``CustomJWTAuthentication`` (exposed as ``request.company``). Agents can belong
to multiple companies, so every endpoint reads ``request.company`` rather than
``request.user.company``.
"""

from datetime import timedelta

from django.db.models import DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils.timesince import timesince
from django.utils.timezone import now
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import CompanyApproved, IsAdmin, IsAgent
from apps.agents.models import BroadcastMessage
from apps.agents.serializers import (
    AgentHomeRecentOrderSerializer,
    AgentHomeSerializer,
    AgentHomeSummarySerializer,
    BroadcastCreateUpdateSerializer,
    BroadcastListSerializer,
    BroadcastSerializer,
)
from apps.core.openapi import (
    COMPANY_HEADER_PARAM,
    RESPONSE_400,
    RESPONSE_403,
    RESPONSE_404,
)
from apps.orders.models import Order, OrderStatus

CANCELLED_LIKE = (
    OrderStatus.CANCELLED,
    OrderStatus.DRAFT,
)

QUICK_ACTIONS = [
    {
        "key": "scan_qr",
        "label": "Scan QR & Order",
        "endpoint": "/api/products/scan/{qr_code}/",
        "method": "get",
        "enabled": True,
    },
    {
        "key": "new_customer",
        "label": "New Customer",
        "endpoint": "/api/customers/",
        "method": "post",
        "enabled": True,
    },
    {
        "key": "my_orders",
        "label": "My Orders",
        "endpoint": "/api/orders/",
        "method": "get",
        "enabled": True,
    },
    {
        "key": "browse_catalog",
        "label": "Browse Catalog",
        "endpoint": "/api/products/",
        "method": "get",
        "enabled": True,
    },
]


def _active_broadcasts(company):
    """Visible broadcasts for a company (active + within schedule window)."""
    at = now()
    qs = BroadcastMessage.objects.filter(company=company)
    visible = []
    for bc in qs:
        if bc.is_visible(at):
            visible.append(bc)
    return visible


@extend_schema_view(
    home=extend_schema(
        tags=["Agent Home"],
        summary="Agent home dashboard",
        description=(
            "Consolidated payload for the agent home screen: agent name, active "
            "company, summary cards (orders/sales today), quick-action stubs, "
            "recent orders, and active broadcast messages."
        ),
        parameters=[COMPANY_HEADER_PARAM],
        responses={200: AgentHomeSerializer, 400: RESPONSE_400},
    ),
    summary=extend_schema(
        tags=["Agent Home"],
        summary="Agent summary cards",
        description="Orders and sales recorded today by the agent in the active company.",
        parameters=[COMPANY_HEADER_PARAM],
        responses={200: AgentHomeSummarySerializer, 400: RESPONSE_400},
    ),
    recent_orders=extend_schema(
        tags=["Agent Home"],
        summary="Agent recent orders",
        description=(
            "The agent's most recent orders in the active company: order id, "
            "customer, amount, status, created time and human time-since."
        ),
        parameters=[
            COMPANY_HEADER_PARAM,
        ],
        responses={200: AgentHomeRecentOrderSerializer(many=True), 400: RESPONSE_400},
    ),
    broadcast=extend_schema(
        tags=["Agent Home"],
        summary="Agent broadcast messages",
        description="Active broadcast messages for the active company.",
        parameters=[COMPANY_HEADER_PARAM],
        responses={200: BroadcastSerializer(many=True), 400: RESPONSE_400},
    ),
)
class AgentHomeViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsAgent)
    serializer_class = AgentHomeSerializer

    def get_serializer_class(self):
        if self.action == "summary":
            return AgentHomeSummarySerializer
        if self.action == "recent_orders":
            return AgentHomeRecentOrderSerializer
        if self.action == "broadcast":
            return BroadcastSerializer
        return AgentHomeSerializer

    def _company(self, request):
        return request.company

    def _agent_profile(self, request):
        return getattr(request.user, "agent_profile", None)

    def _resolve_company(self, request):
        company = self._company(request)
        if company is None:
            raise ValueError(
                "No active company context. Use X-Company-Id header or switch company."
            )
        return company

    def _summary_data(self, agent_profile, company):
        today = now()
        base = Order.objects.filter(
            company=company,
            agent=agent_profile,
        )
        # Orders placed today (draft carts and cancellations excluded).
        orders_today = (
            base.filter(created_at__date=today.date())
            .exclude(status__in=CANCELLED_LIKE)
            .count()
        )
        sales_today = (
            base.filter(
                created_at__date=today.date(),
            )
            .exclude(status__in=CANCELLED_LIKE)
            .aggregate(
                total=Coalesce(
                    Sum("total_amount"),
                    Value(0),
                    output_field=DecimalField(max_digits=14, decimal_places=2),
                )
            )["total"]
        )
        return {
            "orders_today": orders_today,
            "sales_today": sales_today,
        }

    def _recent_orders(self, agent_profile, company, limit=10):
        orders = (
            Order.objects.filter(
                company=company,
                agent=agent_profile,
            )
            .select_related("customer")
            .order_by("-created_at")[:limit]
        )
        data = []
        for o in orders:
            data.append(
                {
                    "order_id": o.id,
                    "order_number": o.order_number,
                    "customer_id": o.customer_id,
                    "customer_name": o.customer.trade_name or o.customer.legal_name,
                    "amount": o.total_amount,
                    "status": o.status,
                    "created_at": o.created_at,
                    "time_ago": timesince(o.created_at, now()),
                }
            )
        return data

    @action(detail=False, methods=["get"], url_path="home")
    def home(self, request, *args, **kwargs):
        agent_profile = self._agent_profile(request)
        if agent_profile is None:
            return Response(
                {"detail": "Agent profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            company = self._resolve_company(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        data = {
            "agent_name": request.user.full_name,
            "company_name": company.name,
            "summary": self._summary_data(agent_profile, company),
            "quick_actions": QUICK_ACTIONS,
            "recent_orders": self._recent_orders(agent_profile, company),
            "broadcast": _active_broadcasts(company),
        }
        return Response(AgentHomeSerializer(data).data)

    @action(detail=False, methods=["get"], url_path="home/summary")
    def summary(self, request, *args, **kwargs):
        agent_profile = self._agent_profile(request)
        if agent_profile is None:
            return Response(
                {"detail": "Agent profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            company = self._resolve_company(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            AgentHomeSummarySerializer(self._summary_data(agent_profile, company)).data
        )

    @action(detail=False, methods=["get"], url_path="home/recent-orders")
    def recent_orders(self, request, *args, **kwargs):
        agent_profile = self._agent_profile(request)
        if agent_profile is None:
            return Response(
                {"detail": "Agent profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        try:
            company = self._resolve_company(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        data = self._recent_orders(agent_profile, company)
        return Response(AgentHomeRecentOrderSerializer(data, many=True).data)

    @action(detail=False, methods=["get"], url_path="home/broadcast")
    def broadcast(self, request, *args, **kwargs):
        try:
            company = self._resolve_company(request)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        data = _active_broadcasts(company)
        return Response(BroadcastSerializer(data, many=True).data)


@extend_schema_view(
    list=extend_schema(
        tags=["Broadcast"],
        summary="List broadcasts",
        description="Company-scoped broadcast messages, newest first. Admin only.",
        parameters=[COMPANY_HEADER_PARAM],
        responses={200: BroadcastListSerializer(many=True)},
    ),
    create=extend_schema(
        tags=["Broadcast"],
        summary="Create broadcast",
        description="Creates a company broadcast message. Admin only.",
        parameters=[COMPANY_HEADER_PARAM],
        request=BroadcastCreateUpdateSerializer,
        responses={201: BroadcastListSerializer, 400: RESPONSE_400, 403: RESPONSE_403},
    ),
    partial_update=extend_schema(
        tags=["Broadcast"],
        summary="Update broadcast",
        description="Updates message, active flag or schedule window. Admin only.",
        parameters=[COMPANY_HEADER_PARAM],
        request=BroadcastCreateUpdateSerializer,
        responses={
            200: BroadcastListSerializer,
            400: RESPONSE_400,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    destroy=extend_schema(
        tags=["Broadcast"],
        summary="Delete broadcast",
        description="Deletes a broadcast. Admin only.",
        parameters=[COMPANY_HEADER_PARAM],
        responses={204: None, 403: RESPONSE_403, 404: RESPONSE_404},
    ),
)
class BroadcastViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsAdmin)
    serializer_class = BroadcastListSerializer

    def get_serializer_class(self):
        if self.action in ("create", "partial_update"):
            return BroadcastCreateUpdateSerializer
        return BroadcastListSerializer

    def _company(self, request):
        return request.company or request.user.company

    def _get_broadcast(self, pk, company):
        try:
            return BroadcastMessage.objects.get(pk=pk, company=company)
        except BroadcastMessage.DoesNotExist:
            return None

    def list(self, request, *args, **kwargs):
        company = self._company(request)
        qs = BroadcastMessage.objects.filter(company=company).select_related(
            "created_by"
        )
        return Response(BroadcastListSerializer(qs, many=True).data)

    def create(self, request, *args, **kwargs):
        company = self._company(request)
        serializer = BroadcastCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bc = serializer.save(company=company, created_by=request.user)
        return Response(
            BroadcastListSerializer(bc).data, status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, pk=None, *args, **kwargs):
        bc = self._get_broadcast(pk, self._company(request))
        if bc is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = BroadcastCreateUpdateSerializer(
            bc, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(BroadcastListSerializer(bc).data)

    def destroy(self, request, pk=None, *args, **kwargs):
        bc = self._get_broadcast(pk, self._company(request))
        if bc is None:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        bc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
