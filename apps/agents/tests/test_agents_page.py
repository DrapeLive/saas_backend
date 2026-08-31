from datetime import date
from decimal import Decimal
import uuid

from django.test import TestCase
from django.utils.timezone import now
from rest_framework import status

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_user,
    get_jwt_headers,
)
from apps.agents.models import AgentCompanyMembership, AgentProfile
from apps.commissions.models import CommissionEntry, CommissionPayout
from apps.customers.models import CustomerProfile
from apps.orders.models import Order


def create_agent(company, email, full_name):
    user = create_user(
        role=RoleType.AGENT, company=company, email=email, full_name=full_name
    )
    profile = AgentProfile.objects.create(user=user, employee_code=f"AG-{email}")
    AgentCompanyMembership.objects.create(
        agent=profile,
        company=company,
        status=AgentCompanyMembership.MembershipStatus.ACTIVE,
        territory="North",
    )
    return profile


def create_customer(company, trade_name):
    return CustomerProfile.objects.create(
        company=company,
        trade_name=trade_name,
        legal_name=f"{trade_name} Pvt Ltd",
        phone="9123456780",
    )


def create_order(company, customer, agent=None):
    return Order.objects.create(
        company=company,
        order_number=f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}",
        customer=customer,
        agent=agent,
        status="dispatched",
    )


def dec(value):
    return Decimal(str(value))


def create_commission(order, agent_profile, amount, status_, month):
    return CommissionEntry.objects.create(
        company=order.company,
        agent=agent_profile,
        order=order,
        order_value=amount * 10,
        commission_pct=10.00,
        commission_amount=amount,
        status=status_,
        settlement_month=month,
    )


class AgentOverviewTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.agent = create_agent(self.company, "agent1@x.com", "Agent One")
        self.url = "/api/admin/agents/overview"

    def test_summary_counts_and_amounts(self):
        c1 = create_customer(self.company, "Customer One")
        o1 = create_order(self.company, c1, agent=self.agent)
        o2 = create_order(self.company, c1, agent=self.agent)
        month = date(2026, 8, 1)
        create_commission(o1, self.agent, 100, "pending", month)
        create_commission(o2, self.agent, 200, "approved", month)
        paid_order = create_order(self.company, c1, agent=self.agent)
        entry = create_commission(paid_order, self.agent, 500, "paid", month)
        CommissionPayout.objects.create(
            company=self.company,
            agent=self.agent,
            settlement_month=month,
            amount=entry.commission_amount,
            entries_count=1,
            paid_at=now(),
        )

        resp = self.client.get(self.url, **get_jwt_headers(self.admin))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        summary = resp.data["summary"]
        self.assertEqual(summary["active_agents"], 1)
        self.assertEqual(dec(summary["pending_payout_amount"]), Decimal("300"))
        self.assertEqual(dec(summary["paid_payout_amount"]), Decimal("500"))

    def test_recent_payouts_listed_newest_first(self):
        c1 = create_customer(self.company, "Customer One")
        older_month, newer_month = date(2026, 6, 1), date(2026, 7, 1)
        CommissionPayout.objects.create(
            company=self.company,
            agent=self.agent,
            settlement_month=older_month,
            amount=100,
            entries_count=1,
            paid_at=now().replace(day=1, month=6),
        )
        CommissionPayout.objects.create(
            company=self.company,
            agent=self.agent,
            settlement_month=newer_month,
            amount=250,
            entries_count=2,
            paid_at=now(),
        )

        resp = self.client.get(self.url, **get_jwt_headers(self.admin))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        payouts = resp.data["recent_payouts"]
        self.assertEqual(len(payouts), 2)
        self.assertEqual(dec(payouts[0]["amount"]), Decimal("250"))
        self.assertEqual(payouts[0]["agent_name"], self.agent.user.full_name)
        self.assertIn("entries_count", payouts[0])

    def test_requires_auth(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class AgentListPageTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.url = "/api/admin/agents"
        self.agent_a = create_agent(self.company, "a@x.com", "Alpha Agent")
        self.agent_b = create_agent(self.company, "b@x.com", "Beta Agent")

    def test_rows_include_clients_and_commission_columns(self):
        cust1 = create_customer(self.company, "Cust One")
        cust2 = create_customer(self.company, "Cust Two")
        o1 = create_order(self.company, cust1, agent=self.agent_a)
        o2 = create_order(self.company, cust2, agent=self.agent_a)  # same agent
        o3 = create_order(self.company, cust1, agent=self.agent_a)  # same customer
        month = date(2026, 8, 1)
        create_commission(o1, self.agent_a, 100, "pending", month)
        create_commission(o2, self.agent_a, 50, "approved", month)
        create_commission(o3, self.agent_a, 400, "paid", month)

        other_cust = create_customer(self.company, "Other Cust")
        other_order = create_order(self.company, other_cust, agent=self.agent_b)
        create_commission(other_order, self.agent_b, 999, "paid", month)

        resp = self.client.get(self.url, **get_jwt_headers(self.admin))

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        rows = {r["user"]["id"]: r for r in resp.data["results"]}
        row_a = rows[str(self.agent_a.user_id)]
        row_b = rows[str(self.agent_b.user_id)]

        # Alpha: 2 distinct customers (cust1 shared across orders counts once)
        self.assertEqual(row_a["clients_count"], 2)
        self.assertEqual(dec(row_a["commission_total"]), Decimal("550"))
        self.assertEqual(dec(row_a["commission_pending"]), Decimal("150"))

        self.assertEqual(row_b["clients_count"], 1)
        self.assertEqual(dec(row_b["commission_total"]), Decimal("999"))
        self.assertEqual(dec(row_b["commission_pending"]), Decimal("0"))

    def test_pagination_envelope(self):
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn("count", resp.data)
        self.assertIn("results", resp.data)
        self.assertEqual(resp.data["count"], 2)

    def test_search_filter(self):
        resp = self.client.get(f"{self.url}?search=Beta", **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["user"]["full_name"], "Beta Agent")

    def test_status_filter(self):
        AgentCompanyMembership.objects.filter(agent=self.agent_b).update(
            status="suspended"
        )

        resp = self.client.get(
            f"{self.url}?status=suspended", **get_jwt_headers(self.admin)
        )
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["status"], "suspended")

    def test_company_isolation(self):
        other = create_company(name="Other Co", slug="other-co", status="active")
        other_admin = create_user(role=RoleType.ADMIN, company=other)
        create_agent(other, "other-agent@x.com", "Other Agent")

        resp = self.client.get(f"{self.url}", **get_jwt_headers(other_admin))
        self.assertEqual(resp.data["count"], 1)

        resp = self.client.get(f"{self.url}", **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["count"], 2)

    def test_superadmin_blocked_from_list(self):
        from apps.accounts.tests.factories import create_super_admin

        resp = self.client.get(self.url, **get_jwt_headers(create_super_admin()))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
