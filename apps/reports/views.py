"""Read-only report endpoints.

Every report is scoped to the requesting company and composed from the
existing Order, Invoice, Payment, CustomerProfile, AgentProfile, VariantSize
and StockMovement data. No new tables are written.
"""

from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import CompanyApproved, IsAdminOrSubAdmin
from apps.core.pagination import DefaultPageNumberPagination
from apps.commissions.models import CommissionEntry
from apps.agents.models import AgentCompanyMembership, AgentProfile, AgentVisitLog
from apps.customers.models import CustomerProfile
from apps.invoices.models import Invoice
from apps.orders.models import Order
from apps.products.models import VariantSize
from apps.reports.serializers import (
    AgentReportRowSerializer,
    CustomerReportRowSerializer,
    GSTReportRowSerializer,
    InventoryReportRowSerializer,
    OrderReportRowSerializer,
    SalesReportRowSerializer,
)
from apps.reports.services import (
    SALES_STATUSES,
    get_company,
    get_date_range,
)

_MONEY = DecimalField(max_digits=14, decimal_places=2)
_COUNT = IntegerField()


class ReportsViewSet(GenericViewSet):
    """Shared authentication/permissions/pagination for all report endpoints."""

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated, CompanyApproved, IsAdminOrSubAdmin)
    pagination_class = DefaultPageNumberPagination

    def _company(self, request):
        return get_company(request)


# ─────────────────────────────────────────────────────────────────────────────
# 1. SALES REPORT
# ─────────────────────────────────────────────────────────────────────────────


class SalesReportViewSet(ReportsViewSet):
    """Aggregated sales figures and per-order sales lines."""

    serializer_class = SalesReportRowSerializer

    def _orders(self, request):
        company = self._company(request)
        date_from, date_to = get_date_range(request, "date")

        qs = Order.objects.filter(company=company, status__in=SALES_STATUSES)
        if date_from:
            qs = qs.filter(submitted_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(submitted_at__date__lte=date_to)

        agent_id = request.query_params.get("agent_id")
        customer_id = request.query_params.get("customer_id")
        status_f = request.query_params.get("status")
        if agent_id:
            qs = qs.filter(agent_id=agent_id)
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        if status_f:
            qs = qs.filter(status=status_f)
        return qs

    # GET /api/reports/sales/
    def list(self, request, *args, **kwargs):
        qs = self._orders(request).select_related("customer", "agent__user")
        qs = qs.order_by("-submitted_at", "-created_at")

        rows = []
        for o in qs:
            rows.append(
                {
                    "order_id": o.id,
                    "order_number": o.order_number,
                    "order_date": o.submitted_at or o.created_at,
                    "customer_id": o.customer_id,
                    "customer_name": o.customer.trade_name,
                    "agent_id": o.agent_id,
                    "agent_name": o.agent.user.full_name if o.agent_id else None,
                    "status": o.status,
                    "subtotal": o.subtotal,
                    "discount_amount": o.discount_amount,
                    "taxable_amount": o.taxable_amount,
                    "cgst_amount": o.cgst_amount,
                    "sgst_amount": o.sgst_amount,
                    "igst_amount": o.igst_amount,
                    "total_amount": o.total_amount,
                }
            )

        page = self.paginate_queryset(rows)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    # GET /api/reports/sales/summary/
    def summary(self, request):
        qs = self._orders(request)

        agg = qs.aggregate(
            total_sales=Coalesce(Sum("total_amount"), Value(0), output_field=_MONEY),
            total_subtotal=Coalesce(Sum("subtotal"), Value(0), output_field=_MONEY),
            total_discount=Coalesce(
                Sum("discount_amount"), Value(0), output_field=_MONEY
            ),
            total_taxable=Coalesce(Sum("taxable_amount"), Value(0), output_field=_MONEY),
            total_cgst=Coalesce(Sum("cgst_amount"), Value(0), output_field=_MONEY),
            total_sgst=Coalesce(Sum("sgst_amount"), Value(0), output_field=_MONEY),
            total_igst=Coalesce(Sum("igst_amount"), Value(0), output_field=_MONEY),
            order_count=Count("id"),
        )

        order_count = agg["order_count"]
        agg["average_order_value"] = (
            round(agg["total_sales"] / order_count, 2) if order_count else 0
        )
        agg["total_tax"] = (
            agg["total_cgst"] + agg["total_sgst"] + agg["total_igst"]
        )
        return Response(agg)


# ─────────────────────────────────────────────────────────────────────────────
# 2. ORDER REPORT
# ─────────────────────────────────────────────────────────────────────────────


class OrderReportViewSet(ReportsViewSet):
    """Operational order list with per-order line counts and status summary."""

    serializer_class = OrderReportRowSerializer

    def _orders(self, request):
        company = self._company(request)
        date_from, date_to = get_date_range(request, "date")

        qs = Order.objects.filter(company=company)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        status_f = request.query_params.get("status")
        agent_id = request.query_params.get("agent_id")
        customer_id = request.query_params.get("customer_id")
        search = request.query_params.get("search")
        if status_f:
            qs = qs.filter(status=status_f)
        if agent_id:
            qs = qs.filter(agent_id=agent_id)
        if customer_id:
            qs = qs.filter(customer_id=customer_id)
        if search:
            qs = qs.filter(
                Q(order_number__icontains=search) | Q(po_number__icontains=search)
            )
        return qs

    # GET /api/reports/orders/
    def list(self, request, *args, **kwargs):
        qs = (
            self._orders(request)
            .select_related("customer", "agent__user")
            .annotate(
                items_count=Count("items"),
                total_quantity=Coalesce(
                    Sum("items__quantity"), Value(0), output_field=_COUNT
                ),
            )
            .order_by("-created_at")
        )

        rows = []
        for o in qs:
            rows.append(
                {
                    "order_id": o.id,
                    "order_number": o.order_number,
                    "po_number": o.po_number,
                    "order_date": o.created_at,
                    "customer_id": o.customer_id,
                    "customer_name": o.customer.trade_name,
                    "agent_id": o.agent_id,
                    "agent_name": o.agent.user.full_name if o.agent_id else None,
                    "status": o.status,
                    "subtotal": o.subtotal,
                    "discount_amount": o.discount_amount,
                    "total_amount": o.total_amount,
                    "items_count": o.items_count,
                    "total_quantity": o.total_quantity,
                }
            )

        page = self.paginate_queryset(rows)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    # GET /api/reports/orders/summary/
    def summary(self, request):
        qs = self._orders(request)

        agg = qs.aggregate(
            total_orders=Count("id"),
            total_order_value=Coalesce(
                Sum("total_amount"), Value(0), output_field=_MONEY
            ),
            total_discount=Coalesce(
                Sum("discount_amount"), Value(0), output_field=_MONEY
            ),
        )

        agg["average_order_value"] = (
            round(agg["total_order_value"] / agg["total_orders"], 2)
            if agg["total_orders"]
            else 0
        )
        agg["status_breakdown"] = dict(
            qs.values_list("status").annotate(count=Count("id")).values_list("status", "count")
        )
        return Response(agg)


# ─────────────────────────────────────────────────────────────────────────────
# 3. CUSTOMER REPORT
# ─────────────────────────────────────────────────────────────────────────────


class CustomerReportViewSet(ReportsViewSet):
    """Customers with lifetime order aggregates and outstanding/credit state."""

    serializer_class = CustomerReportRowSerializer

    def _customers(self, request):
        company = self._company(request)
        date_from, date_to = get_date_range(request, "date")

        qs = CustomerProfile.objects.filter(company=company)
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        segment = request.query_params.get("segment")
        status_f = request.query_params.get("status")
        agent_id = request.query_params.get("agent_id")
        search = request.query_params.get("search")
        if segment:
            qs = qs.filter(segment=segment)
        if status_f:
            qs = qs.filter(status=status_f)
        if agent_id:
            qs = qs.filter(assigned_agent_id=agent_id)
        if search:
            qs = qs.filter(
                Q(trade_name__icontains=search)
                | Q(legal_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(gstin__icontains=search)
            )
        return qs

    # GET /api/reports/customers/
    def list(self, request, *args, **kwargs):
        orders = Order.objects.filter(
            company=self._company(request), status__in=SALES_STATUSES
        )

        qs = (
            self._customers(request)
            .select_related("assigned_agent__user")
            .annotate(
                total_sales=Coalesce(
                    Subquery(
                        orders.values("customer")
                        .annotate(value=Sum("total_amount"))
                        .values("value")[:1]
                    ),
                    Value(0),
                    output_field=_MONEY,
                ),
                total_orders=Coalesce(
                    Subquery(
                        orders.values("customer")
                        .annotate(value=Count("id"))
                        .values("value")[:1]
                    ),
                    Value(0),
                    output_field=_COUNT,
                ),
            )
            .order_by("-total_sales")
        )

        rows = []
        for c in qs:
            rows.append(
                {
                    "customer_id": c.id,
                    "trade_name": c.trade_name or c.legal_name or c.phone,
                    "phone": c.phone,
                    "email": c.email,
                    "segment": c.segment,
                    "status": c.status,
                    "assigned_agent_id": c.assigned_agent_id,
                    "assigned_agent_name": (
                        c.assigned_agent.user.full_name if c.assigned_agent_id else None
                    ),
                    "created_at": c.created_at,
                    "total_orders": c.total_orders,
                    "total_sales": c.total_sales,
                    "total_outstanding": c.total_outstanding,
                    "overdue_outstanding": c.overdue_outstanding,
                    "credit_limit": c.credit_limit,
                    "credit_utilized": c.credit_utilized,
                }
            )

        page = self.paginate_queryset(rows)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    # GET /api/reports/customers/summary/
    def summary(self, request):
        qs = self._customers(request)

        agg = qs.aggregate(
            total_customers=Count("id"),
            active_customers=Count("id", filter=Q(status="active")),
            inactive_customers=Count("id", filter=Q(status="inactive")),
            blocked_customers=Count("id", filter=Q(status="blocked")),
            prospect_customers=Count("id", filter=Q(status="prospect")),
            total_outstanding=Coalesce(
                Sum("total_outstanding"), Value(0), output_field=_MONEY
            ),
            overdue_outstanding=Coalesce(
                Sum("overdue_outstanding"), Value(0), output_field=_MONEY
            ),
        )
        agg["segment_breakdown"] = dict(
            qs.values_list("segment")
            .annotate(count=Count("id"))
            .values_list("segment", "count")
        )
        return Response(agg)


# ─────────────────────────────────────────────────────────────────────────────
# 4. AGENT REPORT
# ─────────────────────────────────────────────────────────────────────────────


class AgentReportViewSet(ReportsViewSet):
    """Per-agent performance: orders, sales, visits, assigned customers."""

    serializer_class = AgentReportRowSerializer

    def _orders(self, request):
        company = self._company(request)
        date_from, date_to = get_date_range(request, "date")

        qs = Order.objects.filter(company=company, status__in=SALES_STATUSES)
        if date_from:
            qs = qs.filter(submitted_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(submitted_at__date__lte=date_to)
        return qs

    def _agents(self, request):
        company = self._company(request)
        agents = (
            AgentProfile.objects.filter(
                memberships__company=company, memberships__status="active"
            )
            .select_related("user")
            .prefetch_related(
                Prefetch(
                    "memberships",
                    queryset=AgentCompanyMembership.objects.filter(
                        company=company, status="active"
                    ),
                    to_attr="active_memberships",
                )
            )
            .distinct()
            .order_by("user__full_name")
        )

        agent_id = request.query_params.get("agent_id")
        if agent_id:
            agents = agents.filter(id=agent_id)
        return agents

    # GET /api/reports/agents/
    def list(self, request, *args, **kwargs):
        company = self._company(request)
        date_from, date_to = get_date_range(request, "date")

        orders = self._orders(request)
        order_stats = {
            str(row["agent_id"]): row
            for row in orders.values("agent_id").annotate(
                total_sales=Coalesce(Sum("total_amount"), Value(0), output_field=_MONEY),
                total_orders=Count("id"),
            )
            if row["agent_id"]
        }

        visits_qs = AgentVisitLog.objects.filter(company=company)
        if date_from:
            visits_qs = visits_qs.filter(visit_date__gte=date_from)
        if date_to:
            visits_qs = visits_qs.filter(visit_date__lte=date_to)
        visit_counts = {
            str(row["agent_id"]): row["count"]
            for row in visits_qs.values("agent_id").annotate(count=Count("id"))
        }

        assigned_counts = {
            str(row["assigned_agent_id"]): row["count"]
            for row in CustomerProfile.objects.filter(
                company=company, assigned_agent__isnull=False
            )
            .values("assigned_agent_id")
            .annotate(count=Count("id"))
        }

        pending_commission = {
            str(row["agent_id"]): row["total"]
            for row in CommissionEntry.objects.filter(company=company, status="pending")
            .values("agent_id")
            .annotate(total=Coalesce(Sum("commission_amount"), Value(0), output_field=_MONEY))
        }

        rows = []
        for agent in self._agents(request):
            stats = order_stats.get(str(agent.id)) or {}
            total_sales = stats.get("total_sales") or 0
            total_orders = stats.get("total_orders") or 0
            membership = (
                agent.active_memberships[0]
                if hasattr(agent, "active_memberships") and agent.active_memberships
                else None
            )
            rows.append(
                {
                    "agent_id": agent.id,
                    "agent_name": agent.user.full_name,
                    "phone": agent.user.phone or "",
                    "employee_code": agent.employee_code,
                    "territory": membership.territory if membership else "",
                    "total_orders": total_orders,
                    "total_sales": total_sales,
                    "average_order_value": (
                        round(total_sales / total_orders, 2) if total_orders else 0
                    ),
                    "visits_count": visit_counts.get(str(agent.id), 0),
                    "assigned_customers_count": assigned_counts.get(
                        str(agent.id), 0
                    ),
                    "pending_commission": pending_commission.get(str(agent.id), 0),
                }
            )

        page = self.paginate_queryset(rows)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    # GET /api/reports/agents/summary/
    def summary(self, request):
        company = self._company(request)
        date_from, date_to = get_date_range(request, "date")

        orders = self._orders(request)
        totals = orders.aggregate(
            total_sales=Coalesce(Sum("total_amount"), Value(0), output_field=_MONEY),
            total_orders=Count("id"),
        )

        visits_qs = AgentVisitLog.objects.filter(company=company)
        if date_from:
            visits_qs = visits_qs.filter(visit_date__gte=date_from)
        if date_to:
            visits_qs = visits_qs.filter(visit_date__lte=date_to)

        active_agents = (
            AgentProfile.objects.filter(
                memberships__company=company, memberships__status="active"
            )
            .distinct()
            .count()
        )

        top = (
            orders.exclude(agent_id=None)
            .values("agent_id")
            .annotate(total=Coalesce(Sum("total_amount"), Value(0), output_field=_MONEY))
            .order_by("-total")
            .first()
        )
        top_agent = None
        if top:
            agent = AgentProfile.objects.filter(id=top["agent_id"]).select_related("user").first()
            top_agent = {
                "agent_id": str(top["agent_id"]),
                "agent_name": agent.user.full_name if agent else None,
                "total_sales": top["total"],
            }

        result = {
            "total_agents": active_agents,
            "total_orders": totals["total_orders"],
            "total_sales": totals["total_sales"],
            "average_order_value": (
                round(totals["total_sales"] / totals["total_orders"], 2)
                if totals["total_orders"]
                else 0
            ),
            "total_visits": visits_qs.count(),
            "top_agent": top_agent,
        }
        return Response(result)


# ─────────────────────────────────────────────────────────────────────────────
# 5. INVENTORY REPORT
# ─────────────────────────────────────────────────────────────────────────────


class InventoryReportViewSet(ReportsViewSet):
    """Stock levels per variant size with low/out-of-stock flags and value."""

    serializer_class = InventoryReportRowSerializer

    def _variants(self, request):
        company = self._company(request)

        qs = (
            VariantSize.objects.select_related(
                "color_variant__product", "color_variant__product__category"
            )
            .filter(color_variant__product__company=company)
            .order_by(
                "color_variant__product__name",
                "color_variant__color_name",
                "size",
            )
        )

        category_id = request.query_params.get("category_id")
        product_id = request.query_params.get("product_id")
        low_stock_only = request.query_params.get("low_stock_only")
        search = request.query_params.get("search")
        if category_id:
            qs = qs.filter(color_variant__product__category_id=category_id)
        if product_id:
            qs = qs.filter(color_variant__product_id=product_id)
        if low_stock_only and low_stock_only.lower() == "true":
            qs = qs.filter(stock_quantity__lte=F("reorder_level") + F("reserved_qty"))
        if search:
            qs = qs.filter(
                Q(color_variant__product__name__icontains=search)
                | Q(sku__icontains=search)
                | Q(color_variant__product__sku_prefix__icontains=search)
            )
        return qs

    @staticmethod
    def _row(vs):
        product = vs.color_variant.product
        available = max(0, vs.stock_quantity - vs.reserved_qty)
        unit_price = vs.price_override if vs.price_override else product.wholesale_price or 0
        return {
            "variant_size_id": vs.id,
            "product_id": product.id,
            "product_name": product.name,
            "color_name": vs.color_variant.color_name,
            "color_hex": vs.color_variant.color_hex,
            "size": vs.size,
            "sku": vs.sku,
            "category_name": product.category.name if product.category_id else None,
            "hsn_code": product.hsn_code,
            "stock_quantity": vs.stock_quantity,
            "reserved_qty": vs.reserved_qty,
            "available_qty": available,
            "reorder_level": vs.reorder_level,
            "is_low_stock": available <= vs.reorder_level,
            "unit_price": unit_price,
            "stock_value": round(Decimal(available) * Decimal(unit_price), 2),
        }

    # GET /api/reports/inventory/
    def list(self, request, *args, **kwargs):
        qs = self._variants(request)
        qs = self.paginate_queryset(qs)
        serializer = self.get_serializer([self._row(v) for v in qs], many=True)
        return self.get_paginated_response(serializer.data)

    # GET /api/reports/inventory/summary/
    def summary(self, request):
        qs = self._variants(request)

        totals = qs.aggregate(
            total_variant_sizes=Count("id"),
            total_products=Count("color_variant__product_id", distinct=True),
            total_stock_units=Coalesce(
                Sum("stock_quantity"), Value(0), output_field=_COUNT
            ),
            total_reserved=Coalesce(Sum("reserved_qty"), Value(0), output_field=_COUNT),
        )

        low_stock_count = 0
        out_of_stock_count = 0
        total_available = 0
        total_stock_value = Decimal("0.00")
        for vs in qs:
            available = max(0, vs.stock_quantity - vs.reserved_qty)
            total_available += available
            if available == 0:
                out_of_stock_count += 1
            if available <= vs.reorder_level:
                low_stock_count += 1
            unit_price = (
                vs.price_override
                if vs.price_override
                else vs.color_variant.product.wholesale_price or 0
            )
            total_stock_value += Decimal(available) * Decimal(unit_price)

        totals.update(
            {
                "total_available": total_available,
                "low_stock_count": low_stock_count,
                "out_of_stock_count": out_of_stock_count,
                "total_stock_value": round(total_stock_value, 2),
            }
        )
        return Response(totals)


# ─────────────────────────────────────────────────────────────────────────────
# 6. GST REPORT
# ─────────────────────────────────────────────────────────────────────────────


class GSTReportViewSet(ReportsViewSet):
    """GST register — outward/inward invoices with tax (CGST/SGST/IGST) split."""

    serializer_class = GSTReportRowSerializer

    def _invoices(self, request):
        company = self._company(request)
        date_from, date_to = get_date_range(request, "date")

        qs = Invoice.objects.filter(company=company).exclude(
            status__in=["draft", "void"]
        )
        if date_from:
            qs = qs.filter(invoice_date__gte=date_from)
        if date_to:
            qs = qs.filter(invoice_date__lte=date_to)

        type_f = request.query_params.get("type")
        gstin = request.query_params.get("gstin")
        is_interstate = request.query_params.get("is_interstate")
        if type_f:
            qs = qs.filter(invoice_type=type_f)
        if gstin:
            qs = qs.filter(customer__gstin__icontains=gstin)
        if is_interstate is not None and is_interstate.lower() in ("true", "false"):
            qs = qs.filter(is_interstate=is_interstate.lower() == "true")
        return qs

    # GET /api/reports/gst/
    def list(self, request, *args, **kwargs):
        qs = self._invoices(request).select_related("customer").order_by("-invoice_date")

        rows = []
        for inv in qs:
            cgst = inv.cgst_amount or 0
            sgst = inv.sgst_amount or 0
            igst = inv.igst_amount or 0
            rows.append(
                {
                    "invoice_id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "invoice_date": inv.invoice_date,
                    "invoice_type": inv.invoice_type,
                    "status": inv.status,
                    "customer_id": inv.customer_id,
                    "customer_name": inv.customer.trade_name,
                    "gstin": inv.customer.gstin or "",
                    "place_of_supply": inv.place_of_supply,
                    "is_interstate": inv.is_interstate,
                    "taxable_amount": inv.taxable_amount,
                    "cgst_amount": inv.cgst_amount,
                    "sgst_amount": inv.sgst_amount,
                    "igst_amount": inv.igst_amount,
                    "total_tax": cgst + sgst + igst,
                    "total_amount": inv.total_amount,
                }
            )

        page = self.paginate_queryset(rows)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    # GET /api/reports/gst/summary/
    def summary(self, request):
        qs = self._invoices(request)

        agg = qs.aggregate(
            total_invoices=Count("id"),
            total_taxable=Coalesce(Sum("taxable_amount"), Value(0), output_field=_MONEY),
            total_cgst=Coalesce(Sum("cgst_amount"), Value(0), output_field=_MONEY),
            total_sgst=Coalesce(Sum("sgst_amount"), Value(0), output_field=_MONEY),
            total_igst=Coalesce(Sum("igst_amount"), Value(0), output_field=_MONEY),
            total_amount=Coalesce(Sum("total_amount"), Value(0), output_field=_MONEY),
        )
        agg["total_tax"] = agg["total_cgst"] + agg["total_sgst"] + agg["total_igst"]
        agg["interstate_total"] = (
            qs.filter(is_interstate=True).aggregate(
                total=Coalesce(Sum("taxable_amount"), Value(0), output_field=_MONEY)
            )["total"]
        )
        agg["intrastate_total"] = (
            qs.filter(is_interstate=False).aggregate(
                total=Coalesce(Sum("taxable_amount"), Value(0), output_field=_MONEY)
            )["total"]
        )
        return Response(agg)