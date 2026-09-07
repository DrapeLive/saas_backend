# apps/reports/urls.py

from django.urls import path

from apps.reports.views import (
    AgentReportViewSet,
    CustomerReportViewSet,
    GSTReportViewSet,
    InventoryReportViewSet,
    OrderReportViewSet,
    SalesReportViewSet,
)

app_name = "reports"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # SALES REPORT
    # GET /api/reports/sales/                Per-order sales lines (paginated)
    #   ?date_from=  ?date_to=  ?agent_id=  ?customer_id=  ?status=
    # GET /api/reports/sales/summary/        Aggregated sales totals
    # ─────────────────────────────────────────────────────────────
    path(
        "reports/sales/",
        SalesReportViewSet.as_view({"get": "list"}),
        name="report-sales",
    ),
    path(
        "reports/sales/summary/",
        SalesReportViewSet.as_view({"get": "summary"}),
        name="report-sales-summary",
    ),
    # ─────────────────────────────────────────────────────────────
    # ORDER REPORT
    # GET /api/reports/orders/               Operational order list (paginated)
    #   ?date_from=  ?date_to=  ?status=  ?agent_id=  ?customer_id=  ?search=
    # GET /api/reports/orders/summary/       Counts by status + total value
    # ─────────────────────────────────────────────────────────────
    path(
        "reports/orders/",
        OrderReportViewSet.as_view({"get": "list"}),
        name="report-orders",
    ),
    path(
        "reports/orders/summary/",
        OrderReportViewSet.as_view({"get": "summary"}),
        name="report-orders-summary",
    ),
    # ─────────────────────────────────────────────────────────────
    # CUSTOMER REPORT
    # GET /api/reports/customers/            Customer aggregates (paginated)
    #   ?segment=  ?status=  ?agent_id=  ?search=  ?date_from=  ?date_to=
    # GET /api/reports/customers/summary/    Status + segment counts, outstanding
    # ─────────────────────────────────────────────────────────────
    path(
        "reports/customers/",
        CustomerReportViewSet.as_view({"get": "list"}),
        name="report-customers",
    ),
    path(
        "reports/customers/summary/",
        CustomerReportViewSet.as_view({"get": "summary"}),
        name="report-customers-summary",
    ),
    # ─────────────────────────────────────────────────────────────
    # AGENT REPORT
    # GET /api/reports/agents/               Per-agent performance (paginated)
    #   ?agent_id=  ?date_from=  ?date_to=
    # GET /api/reports/agents/summary/       Top-line agent totals
    # ─────────────────────────────────────────────────────────────
    path(
        "reports/agents/",
        AgentReportViewSet.as_view({"get": "list"}),
        name="report-agents",
    ),
    path(
        "reports/agents/summary/",
        AgentReportViewSet.as_view({"get": "summary"}),
        name="report-agents-summary",
    ),
    # ─────────────────────────────────────────────────────────────
    # INVENTORY REPORT
    # GET /api/reports/inventory/            Stock per variant size (paginated)
    #   ?category_id=  ?product_id=  ?low_stock_only=  ?search=
    # GET /api/reports/inventory/summary/    Stock totals, low/out-of-stock counts
    # ─────────────────────────────────────────────────────────────
    path(
        "reports/inventory/",
        InventoryReportViewSet.as_view({"get": "list"}),
        name="report-inventory",
    ),
    path(
        "reports/inventory/summary/",
        InventoryReportViewSet.as_view({"get": "summary"}),
        name="report-inventory-summary",
    ),
    # ─────────────────────────────────────────────────────────────
    # GST REPORT
    # GET /api/reports/gst/                  GST register per invoice (paginated)
    #   ?date_from=  ?date_to=  ?type=  ?gstin=  ?is_interstate=
    # GET /api/reports/gst/summary/          CGST/SGST/IGST + interstate split
    # ─────────────────────────────────────────────────────────────
    path(
        "reports/gst/",
        GSTReportViewSet.as_view({"get": "list"}),
        name="report-gst",
    ),
    path(
        "reports/gst/summary/",
        GSTReportViewSet.as_view({"get": "summary"}),
        name="report-gst-summary",
    ),
]