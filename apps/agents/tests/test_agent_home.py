"""Tests for the agent UI home dashboard APIs.

Covers the consolidated `/api/agent/home` payload (summary cards, agent name,
quick actions, recent orders, broadcast messages), the focused sub-endpoints
(`/summary`, `/recent-orders`, `/broadcast`), and the admin broadcast
management endpoint. Also verifies multi-company isolation and agent access
to catalog / customer / order resources used by the quick actions.
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_customer,
    create_user,
    get_jwt_headers,
)
from apps.agents.models import (
    AgentCompanyMembership,
    AgentProfile,
    BroadcastMessage,
)
from apps.customers.models import CustomerProfile
from apps.orders.models import Order, OrderStatus
from apps.products.models import Category, ColorVariant, Product, SizeChart, VariantSize


def create_agent(company, email, full_name, employee_code="AG-HOME"):
    # Agents are not bound to a single company in the User model; they join
    # companies via membership and select the active one with X-Company-Id.
    user = create_user(
        role=RoleType.AGENT,
        company=None,
        email=email,
        full_name=full_name,
    )
    profile = AgentProfile.objects.create(user=user, employee_code=employee_code)
    AgentCompanyMembership.objects.create(
        agent=profile,
        company=company,
        status=AgentCompanyMembership.MembershipStatus.ACTIVE,
        territory="North",
    )
    return profile


def create_order(
    company, customer, agent=None, total_amount="100.00", status_=OrderStatus.CONFIRMED
):
    return Order.objects.create(
        company=company,
        order_number=f"ORD-{uuid.uuid4().hex[:8].upper()}",
        customer=customer,
        agent=agent,
        status=status_,
        total_amount=total_amount,
        submitted_at=now(),
        created_at=now(),
    )


def create_broadcast(company, message, created_by=None, active=True):
    return BroadcastMessage.objects.create(
        company=company,
        message=message,
        is_active=active,
        created_by=created_by,
    )


def agent_headers(company_id):
    """Extra kwargs carrying the X-Company-Id header for a request."""
    return {"HTTP_X_COMPANY_ID": str(company_id)}


class AgentHomeSummaryTests(TestCase):
    """Summary cards: orders today + sales today, scoped to the agent + company."""

    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.other_company = create_company(name="Other Co", status="active")
        self.agent = create_agent(self.company, "agent@home.com", "Home Agent")
        # Agent also belongs to the other company
        AgentCompanyMembership.objects.create(
            agent=self.agent,
            company=self.other_company,
            status=AgentCompanyMembership.MembershipStatus.ACTIVE,
        )
        self.customer = create_customer(self.company, "Customer A")
        self.other_customer = create_customer(self.other_company, "Customer B")
        self.client.credentials(**get_jwt_headers(self.agent.user))

    def test_home_returns_summary_cards_for_active_company(self):
        create_order(
            self.company, self.customer, agent=self.agent, total_amount="250.00"
        )
        create_order(
            self.company, self.customer, agent=self.agent, total_amount="150.00"
        )
        # cancelled orders should NOT count toward sales
        create_order(
            self.company,
            self.customer,
            agent=self.agent,
            total_amount="99999.00",
            status_=OrderStatus.CANCELLED,
        )
        # another agent's order should not count
        other_agent = create_agent(
            self.company, "other@home.com", "Other Agent", "AG-2"
        )
        create_order(
            self.company, self.customer, agent=other_agent, total_amount="5000.00"
        )

        resp = self.client.get("/api/agent/home", **agent_headers(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

        summary = resp.data["summary"]
        self.assertEqual(summary["orders_today"], 2)
        self.assertEqual(summary["sales_today"], "400.00")

    def test_home_summary_scoped_to_company(self):
        create_order(
            self.company, self.customer, agent=self.agent, total_amount="100.00"
        )

        resp = self.client.get(
            "/api/agent/home", **agent_headers(self.other_company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # The other company has no orders from this agent
        self.assertEqual(resp.data["summary"]["orders_today"], 0)
        self.assertEqual(resp.data["summary"]["sales_today"], "0.00")

    def test_home_returns_agent_name_and_company_name(self):
        resp = self.client.get("/api/agent/home", **agent_headers(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["agent_name"], "Home Agent")
        self.assertEqual(resp.data["company_name"], self.company.name)

    def test_home_requires_company_context(self):
        resp = self.client.get("/api/agent/home")
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_summary_focused_endpoint(self):
        create_order(
            self.company, self.customer, agent=self.agent, total_amount="75.00"
        )
        resp = self.client.get(
            "/api/agent/home/summary", **agent_headers(self.company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["orders_today"], 1)
        self.assertEqual(resp.data["sales_today"], "75.00")


class AgentHomeQuickActionsTests(TestCase):
    """Quick actions are stubs listing available intents / target endpoints."""

    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.agent = create_agent(self.company, "qa@home.com", "QA Agent")
        self.client.credentials(**get_jwt_headers(self.agent.user))

    def test_home_lists_quick_actions(self):
        resp = self.client.get("/api/agent/home", **agent_headers(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        actions = resp.data["quick_actions"]
        keys = {a["key"] for a in actions}
        self.assertIn("scan_qr", keys)
        self.assertIn("new_customer", keys)
        self.assertIn("my_orders", keys)
        self.assertIn("browse_catalog", keys)


class AgentHomeRecentOrdersTests(TestCase):
    """Recent orders listing with order id, customer, amount, status, time-since."""

    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.other_company = create_company(name="Other Co", status="active")
        self.agent = create_agent(self.company, "recent@home.com", "Recent Agent")
        AgentCompanyMembership.objects.create(
            agent=self.agent,
            company=self.other_company,
            status=AgentCompanyMembership.MembershipStatus.ACTIVE,
        )
        self.customer = create_customer(self.company, "Customer A")
        self.client.credentials(**get_jwt_headers(self.agent.user))

    def test_recent_orders_include_expected_fields(self):
        created = now() - timedelta(minutes=30)
        order = Order.objects.create(
            company=self.company,
            order_number="ORD-RECENT-001",
            customer=self.customer,
            agent=self.agent,
            status=OrderStatus.CONFIRMED,
            total_amount="320.50",
            submitted_at=now(),
            created_at=created,
        )
        resp = self.client.get(
            "/api/agent/home/recent-orders", **agent_headers(self.company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        row = resp.data[0]
        self.assertEqual(row["order_id"], str(order.id))
        self.assertEqual(row["order_number"], "ORD-RECENT-001")
        self.assertEqual(row["customer_name"], "Customer A")
        self.assertEqual(row["amount"], "320.50")
        self.assertEqual(row["status"], OrderStatus.CONFIRMED)
        self.assertEqual(row["customer_id"], str(self.customer.id))
        self.assertIn("created_at", row)
        self.assertIn("time_ago", row)
        self.assertNotEqual(row["time_ago"], "")

    def test_recent_orders_only_own_orders(self):
        other_agent = create_agent(self.company, "other@recent.com", "Other", "AG-X")
        Order.objects.create(
            company=self.company,
            order_number="ORD-OTHER-001",
            customer=self.customer,
            agent=other_agent,
            status=OrderStatus.CONFIRMED,
            total_amount="999.00",
            submitted_at=now(),
        )
        Order.objects.create(
            company=self.company,
            order_number="ORD-MINE-001",
            customer=self.customer,
            agent=self.agent,
            status=OrderStatus.DRAFT,
            total_amount="10.00",
        )
        resp = self.client.get(
            "/api/agent/home/recent-orders", **agent_headers(self.company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        numbers = [r["order_number"] for r in resp.data]
        self.assertNotIn("ORD-OTHER-001", numbers)
        self.assertIn("ORD-MINE-001", numbers)

    def test_recent_orders_scoped_to_company(self):
        resp = self.client.get(
            "/api/agent/home/recent-orders", **agent_headers(self.other_company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data, [])


class AgentHomeBroadcastTests(TestCase):
    """Broadcast messages returned to agents with the active company window."""

    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.other_company = create_company(name="Other Co", status="active")
        self.admin = create_user(
            role=RoleType.ADMIN, company=self.company, email="admin@home.com"
        )
        self.agent = create_agent(self.company, "broadcast@home.com", "Broadcast Agent")
        AgentCompanyMembership.objects.create(
            agent=self.agent,
            company=self.other_company,
            status=AgentCompanyMembership.MembershipStatus.ACTIVE,
        )
        self.client.credentials(**get_jwt_headers(self.agent.user))

    def test_home_includes_active_broadcast(self):
        create_broadcast(
            self.company, "Welcome to the platform!", created_by=self.admin
        )
        resp = self.client.get("/api/agent/home", **agent_headers(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        messages = resp.data["broadcast"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["message"], "Welcome to the platform!")

    def test_inactive_broadcast_excluded(self):
        create_broadcast(
            self.company, "Old message", created_by=self.admin, active=False
        )
        resp = self.client.get("/api/agent/home", **agent_headers(self.company.id))
        self.assertEqual(resp.data["broadcast"], [])

    def test_broadcast_scoped_to_company(self):
        create_broadcast(self.company, "Company A message", created_by=self.admin)
        resp = self.client.get(
            "/api/agent/home", **agent_headers(self.other_company.id)
        )
        self.assertEqual(resp.data["broadcast"], [])

    def test_focused_broadcast_endpoint(self):
        create_broadcast(self.company, "Focused message", created_by=self.admin)
        resp = self.client.get(
            "/api/agent/home/broadcast", **agent_headers(self.company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)
        self.assertEqual(resp.data[0]["message"], "Focused message")


class AdminBroadcastTests(TestCase):
    """Admin manage broadcast messages; agents cannot create them."""

    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.admin = create_user(
            role=RoleType.ADMIN,
            company=self.company,
            email="admin@bc.com",
            full_name="Admin BC",
        )
        self.agent = create_agent(self.company, "abc@bc.com", "Agent BC")

    def test_admin_can_create_broadcast(self):
        self.client.credentials(**get_jwt_headers(self.admin))
        resp = self.client.post(
            "/api/admin/broadcast/",
            {"message": "New offer"},
            HTTP_X_COMPANY_ID=str(self.company.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data["message"], "New offer")
        self.assertTrue(resp.data["is_active"])
        self.assertEqual(
            BroadcastMessage.objects.filter(company=self.company).count(), 1
        )

    def test_admin_can_list_broadcast(self):
        create_broadcast(self.company, "One", created_by=self.admin)
        create_broadcast(self.company, "Two", created_by=self.admin)
        self.client.credentials(**get_jwt_headers(self.admin))
        resp = self.client.get(
            "/api/admin/broadcast/", **agent_headers(self.company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 2)

    def test_admin_can_deactivate_broadcast(self):
        bc = create_broadcast(self.company, "Disable me", created_by=self.admin)
        self.client.credentials(**get_jwt_headers(self.admin))
        resp = self.client.patch(
            f"/api/admin/broadcast/{bc.id}/",
            {"is_active": False},
            HTTP_X_COMPANY_ID=str(self.company.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data["is_active"])
        bc.refresh_from_db()
        self.assertFalse(bc.is_active)

    def test_agent_cannot_create_broadcast(self):
        self.client.credentials(**get_jwt_headers(self.agent.user))
        resp = self.client.post(
            "/api/admin/broadcast/",
            {"message": "Hack"},
            HTTP_X_COMPANY_ID=str(self.company.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class AgentCatalogAccessTests(TestCase):
    """Agents can browse the catalog and scan QR (quick actions)."""

    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.agent = create_agent(self.company, "catalog@home.com", "Catalog Agent")
        self.client.credentials(**get_jwt_headers(self.agent.user))

        self.category = Category.objects.create(company=self.company, name="Shirts")
        self.size_chart = SizeChart.objects.create(
            company=self.company, name="Men", sizes=["S", "M"]
        )
        self.product = Product.objects.create(
            company=self.company,
            category=self.category,
            name="Cotton Shirt",
            wholesale_price="250.00",
            gst_rate=5,
            size_chart=self.size_chart,
        )
        self.variant = ColorVariant.objects.create(
            product=self.product, color_name="Blue", qr_code=uuid.uuid4()
        )
        self.variant_size = VariantSize.objects.create(
            color_variant=self.variant, size="M", stock_quantity=10
        )

    def test_agent_can_list_catalog(self):
        resp = self.client.get("/api/products/", **agent_headers(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("results", resp.data)
        self.assertGreaterEqual(len(resp.data["results"]), 1)

    def test_agent_can_retrieve_product(self):
        resp = self.client.get(
            f"/api/products/{self.product.id}/", **agent_headers(self.company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["name"], "Cotton Shirt")

    def test_agent_can_scan_qr(self):
        resp = self.client.get(
            f"/api/products/scan/{self.variant.qr_code}/",
            **agent_headers(self.company.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data["scanned_variant_id"], str(self.variant.id))

    def test_agent_cannot_create_product(self):
        resp = self.client.post(
            "/api/products/",
            {"name": "Sneak", "category": str(self.category.id)},
            **agent_headers(self.company.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class AgentCustomerAccessTests(TestCase):
    """Agents can create and list customers (quick action: new customer)."""

    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.agent = create_agent(self.company, "cust@home.com", "Cust Agent")
        self.client.credentials(**get_jwt_headers(self.agent.user))

    def test_agent_can_create_customer(self):
        resp = self.client.post(
            "/api/customers/",
            {
                "legal_name": "New Customer Pvt Ltd",
                "trade_name": "New Customer",
                "phone": "9123456780",
            },
            **agent_headers(self.company.id),
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            CustomerProfile.objects.filter(company=self.company).count(), 1
        )

    def test_agent_can_list_customers(self):
        create_customer(self.company, "Existing Co")
        resp = self.client.get(
            "/api/admin/customers/", **agent_headers(self.company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data["results"]), 1)

    def test_agent_customer_scoped_to_company(self):
        other_company = create_company(name="Other Co", status="active")
        create_customer(self.company, "Mine")
        create_customer(other_company, "Theirs")
        resp = self.client.get(
            "/api/admin/customers/", **agent_headers(self.company.id)
        )
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["results"][0]["trade_name"], "Mine")

    def test_agent_cannot_delete_customer(self):
        customer = create_customer(self.company, "Keep Me")
        resp = self.client.delete(
            f"/api/admin/customers/{customer.id}/", **agent_headers(self.company.id)
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class AgentOrderAccessTests(TestCase):
    """My-orders quick action: agents see only their own orders in the company."""

    def setUp(self):
        self.client = APIClient()
        self.company = create_company(status="active")
        self.agent = create_agent(self.company, "orders@home.com", "Order Agent")
        other_agent = create_agent(self.company, "other@o.com", "Other O", "AG-O")
        self.customer = create_customer(self.company, "Customer A")
        self.client.credentials(**get_jwt_headers(self.agent.user))
        Order.objects.create(
            company=self.company,
            order_number="ORD-OWN-001",
            customer=self.customer,
            agent=self.agent,
            status=OrderStatus.CONFIRMED,
            total_amount="100.00",
            submitted_at=now(),
        )
        Order.objects.create(
            company=self.company,
            order_number="ORD-SOMEONE-001",
            customer=self.customer,
            agent=other_agent,
            status=OrderStatus.CONFIRMED,
            total_amount="100.00",
            submitted_at=now(),
        )

    def test_agent_only_sees_own_orders(self):
        resp = self.client.get("/api/orders/", **agent_headers(self.company.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        numbers = [o["order_number"] for o in resp.data]
        self.assertIn("ORD-OWN-001", numbers)
        self.assertNotIn("ORD-SOMEONE-001", numbers)
