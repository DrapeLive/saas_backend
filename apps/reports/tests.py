from decimal import Decimal
import uuid

from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import RoleType, User
from apps.commissions.models import CommissionEntry
from apps.agents.models import (
    AgentCompanyMembership,
    AgentProfile,
    AgentVisitLog,
)
from apps.companies.models import Company
from apps.customers.models import CustomerProfile
from apps.invoices.models import Invoice, InvoiceStatus, InvoiceType
from apps.orders.models import Order, OrderStatus
from apps.products.models import Category, ColorVariant, Product, VariantSize


def authenticate(client, user, company):
    refresh = RefreshToken.for_user(user)
    refresh["company_id"] = str(company.id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


def money(value):
    """Normalize a serialized money value (str/float/Decimal) to Decimal."""
    return Decimal(str(value))


class ReportsApiTest(TestCase):
    """Smoke test covering every report endpoint under /api/reports/."""

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme Textiles",
            slug="acme-reports",
            contact_email="ops@acme.com",
            contact_phone="9876543210",
            status="active",
        )
        self.admin = User.objects.create_user(
            email="admin@acme.com",
            password="pass-12345",
            full_name="Admin Acme",
            role=RoleType.ADMIN,
            company=self.company,
        )
        self.agent_user = User.objects.create_user(
            email="agent@acme.com",
            password="pass-12345",
            full_name="Agent Alice",
            role=RoleType.AGENT,
            company=self.company,
        )
        self.agent = AgentProfile.objects.create(user=self.agent_user)
        AgentCompanyMembership.objects.create(
            agent=self.agent, company=self.company, status="active"
        )

        self.customer = CustomerProfile.objects.create(
            company=self.company,
            trade_name="Fashion Hub",
            phone="9123456780",
            gstin="27AAAAA0000A1Z5",
            assigned_agent=self.agent,
            total_outstanding=Decimal("2500.00"),
            overdue_outstanding=Decimal("500.00"),
        )

        category = Category.objects.create(company=self.company, name="Mens")
        self.product = Product.objects.create(
            company=self.company,
            category=category,
            name="Cotton Shirt",
            hsn_code="620590",
            wholesale_price=Decimal("500.00"),
        )
        color = ColorVariant.objects.create(
            product=self.product, color_name="Blue", sku="SHIRT-BLUE"
        )
        self.variant = VariantSize.objects.create(
            color_variant=color,
            size="M",
            sku="SHIRT-BLUE-M",
            stock_quantity=50,
            reserved_qty=10,
            reorder_level=15,
        )

        self.order = Order.objects.create(
            company=self.company,
            order_number="ORD-1001",
            customer=self.customer,
            agent=self.agent,
            status=OrderStatus.CONFIRMED,
            subtotal=Decimal("1000.00"),
            discount_amount=Decimal("50.00"),
            taxable_amount=Decimal("950.00"),
            cgst_amount=Decimal("47.50"),
            sgst_amount=Decimal("47.50"),
            igst_amount=Decimal("0.00"),
            total_amount=Decimal("1045.00"),
        )
        Order.objects.create(
            company=self.company,
            order_number="ORD-1002",
            customer=self.customer,
            status=OrderStatus.DRAFT,
            subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"),
        )

        self.invoice = Invoice.objects.create(
            company=self.company,
            invoice_type=InvoiceType.SALES_INVOICE,
            invoice_number="INV-1",
            customer=self.customer,
            status=InvoiceStatus.ISSUED,
            invoice_date="2026-09-01",
            subtotal=Decimal("1000.00"),
            taxable_amount=Decimal("950.00"),
            cgst_amount=Decimal("47.50"),
            sgst_amount=Decimal("47.50"),
            igst_amount=Decimal("0.00"),
            total_amount=Decimal("1045.00"),
            amount_due=Decimal("1045.00"),
        )

        CommissionEntry.objects.create(
            company=self.company,
            agent=self.agent,
            order=self.order,
            order_value=Decimal("1045.00"),
            commission_pct=Decimal("2.00"),
            commission_amount=Decimal("20.90"),
        )
        AgentVisitLog.objects.create(
            company=self.company,
            agent=self.agent,
            customer=self.customer,
            visit_date="2026-09-02",
        )

        self.client = APIClient()
        authenticate(self.client, self.admin, self.company)

    def test_sales_report(self):
        resp = self.client.get("/api/reports/sales/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(money(resp.data["results"][0]["total_amount"]), Decimal("1045.00"))

        resp = self.client.get("/api/reports/sales/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(money(resp.data["total_sales"]), Decimal("1045.00"))
        self.assertEqual(resp.data["order_count"], 1)
        self.assertEqual(money(resp.data["average_order_value"]), Decimal("1045.00"))

    def test_order_report(self):
        resp = self.client.get("/api/reports/orders/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 2)

        resp = self.client.get("/api/reports/orders/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total_orders"], 2)
        self.assertIn("status_breakdown", resp.data)

    def test_customer_report(self):
        resp = self.client.get("/api/reports/customers/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        row = resp.data["results"][0]
        self.assertEqual(money(row["total_sales"]), Decimal("1045.00"))
        self.assertEqual(row["total_orders"], 1)

        resp = self.client.get("/api/reports/customers/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total_customers"], 1)
        self.assertEqual(resp.data["active_customers"], 1)

    def test_agent_report(self):
        resp = self.client.get("/api/reports/agents/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        row = resp.data["results"][0]
        self.assertEqual(row["agent_name"], "Agent Alice")
        self.assertEqual(money(row["total_sales"]), Decimal("1045.00"))
        self.assertEqual(row["total_orders"], 1)
        self.assertEqual(row["visits_count"], 1)
        self.assertEqual(row["assigned_customers_count"], 1)
        self.assertEqual(money(row["pending_commission"]), Decimal("20.90"))

        resp = self.client.get("/api/reports/agents/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total_agents"], 1)
        self.assertEqual(money(resp.data["total_sales"]), Decimal("1045.00"))

    def test_inventory_report(self):
        resp = self.client.get("/api/reports/inventory/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        row = resp.data["results"][0]
        self.assertEqual(row["available_qty"], 40)
        self.assertFalse(row["is_low_stock"])
        self.assertEqual(money(row["stock_value"]), Decimal("20000.00"))

        resp = self.client.get("/api/reports/inventory/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total_variant_sizes"], 1)
        self.assertEqual(resp.data["total_stock_units"], 50)
        self.assertEqual(resp.data["low_stock_count"], 0)

        resp = self.client.get("/api/reports/inventory/?low_stock_only=true")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 0)

    def test_gst_report(self):
        resp = self.client.get("/api/reports/gst/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        row = resp.data["results"][0]
        self.assertEqual(row["gstin"], "27AAAAA0000A1Z5")
        self.assertEqual(money(row["total_tax"]), Decimal("95.00"))

        resp = self.client.get("/api/reports/gst/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total_invoices"], 1)
        self.assertEqual(money(resp.data["total_cgst"]), Decimal("47.50"))
        self.assertEqual(money(resp.data["total_tax"]), Decimal("95.00"))
        self.assertEqual(money(resp.data["intrastate_total"]), Decimal("950.00"))

    def test_draft_and_void_invoices_excluded_from_gst(self):
        Invoice.objects.create(
            company=self.company,
            invoice_type=InvoiceType.SALES_INVOICE,
            invoice_number="INV-DRAFT",
            customer=self.customer,
            status=InvoiceStatus.DRAFT,
            invoice_date="2026-09-01",
            subtotal=Decimal("1.00"),
            taxable_amount=Decimal("1.00"),
            total_amount=Decimal("1.00"),
        )
        resp = self.client.get("/api/reports/gst/summary/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["total_invoices"], 1)

    def test_report_requires_admin_or_subadmin(self):
        sub = User.objects.create_user(
            email="sub@acme.com",
            password="pass-12345",
            full_name="Sub Acme",
            role=RoleType.SUB_ADMIN,
            company=self.company,
        )
        authenticate(self.client, sub, self.company)
        resp = self.client.get("/api/reports/sales/summary/")
        self.assertEqual(resp.status_code, 200)

        authenticate(self.client, self.agent_user, self.company)
        resp = self.client.get("/api/reports/sales/summary/")
        self.assertEqual(resp.status_code, 403)

    def test_invalid_date_range_returns_400(self):
        resp = self.client.get("/api/reports/sales/?date_from=2026-09-10&date_to=2026-09-01")
        self.assertEqual(resp.status_code, 400)