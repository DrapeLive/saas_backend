import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils.timezone import now
from rest_framework import status

from apps.accounts.models import RoleType, User
from apps.accounts.tests.factories import (
    create_company,
    create_customer,
    create_user,
    get_jwt_headers,
)
from apps.agents.models import AgentCompanyMembership, AgentProfile, AgentVisitLog
from apps.invoices.models import Invoice
from apps.orders.models import Order

URL = "/api/business/stats"


def create_agent(company, email=None):
    user = create_user(email=email, role=RoleType.AGENT, company=company)
    profile = AgentProfile.objects.create(user=user)
    AgentCompanyMembership.objects.create(
        agent=profile, company=company, status="active", joined_at=now()
    )
    return profile


def create_invoice(
    company, customer, status="issued", due_date=None, amount_due="1000.00"
):
    return Invoice.objects.create(
        company=company,
        invoice_type="sales_invoice",
        invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
        customer=customer,
        status=status,
        invoice_date=now().date(),
        due_date=due_date,
        subtotal=amount_due,
        taxable_amount=amount_due,
        total_amount=amount_due,
        amount_due=amount_due,
    )


def create_order(company, customer, agent=None):
    return Order.objects.create(
        company=company,
        order_number=f"ORD-{uuid.uuid4().hex[:10].upper()}",
        customer=customer,
        agent=agent,
    )


class BusinessStatsAuthTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def test_requires_authentication(self):
        resp = self.client.get(URL)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_access(self):
        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class BusinessStatsEmptyTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def test_empty_company_returns_zeroes(self):
        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp.data,
            {
                "total_customers": 0,
                "overdue_customers": 0,
                "overdue_invoices": 0,
                "total_agents": 0,
                "active_agents_today": 0,
                "outstanding_total": "0.00",
                "overdue_total": "0.00",
            },
        )


class BusinessStatsCustomerTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def test_total_customers_counts_active_only(self):
        create_customer(self.company, trade_name="Active One", status="active")
        create_customer(self.company, trade_name="Inactive One", status="inactive")
        create_customer(self.company, trade_name="Prospect", status="prospect")
        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["total_customers"], 1)


class BusinessStatsOverdueTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.today = now().date()

    def test_overdue_boundary_and_amounts(self):
        c1 = create_customer(self.company, trade_name="Alpha")
        c2 = create_customer(self.company, trade_name="Beta")

        # Overdue: issued + partial invoices past due date (two for Alpha -> distinct customers)
        create_invoice(
            self.company,
            c1,
            status="issued",
            due_date=self.today - timedelta(days=1),
            amount_due="500.00",
        )
        create_invoice(
            self.company,
            c1,
            status="partial",
            due_date=self.today - timedelta(days=10),
            amount_due="250.00",
        )
        create_invoice(
            self.company,
            c2,
            status="overdue",
            due_date=self.today - timedelta(days=30),
            amount_due="1000.00",
        )

        # Not overdue: due today, paid with past due date, draft, void
        create_invoice(
            self.company, c2, status="issued", due_date=self.today, amount_due="700.00"
        )
        create_invoice(
            self.company,
            c2,
            status="paid",
            due_date=self.today - timedelta(days=5),
            amount_due="900.00",
        )
        create_invoice(
            self.company,
            c2,
            status="draft",
            due_date=self.today - timedelta(days=5),
            amount_due="50.00",
        )
        create_invoice(
            self.company,
            c2,
            status="void",
            due_date=self.today - timedelta(days=5),
            amount_due="60.00",
        )

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        data = resp.data

        # overdue: 3 invoices across 2 customers, total = 500 + 250 + 1000
        self.assertEqual(data["overdue_invoices"], 3)
        self.assertEqual(data["overdue_customers"], 2)
        self.assertEqual(str(data["overdue_total"]), "1750.00")

        # outstanding includes all unpaid (issued/partial/overdue): 500+250+1000+700
        self.assertEqual(str(data["outstanding_total"]), "2450.00")


class BusinessStatsAgentTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(self.company)
        self.today = now().date()

    def test_total_agents_counts_active_memberships_only(self):
        create_agent(self.company)
        suspended = create_agent(self.company)
        pending = create_agent(self.company)
        AgentCompanyMembership.objects.filter(agent=suspended).update(
            status="suspended"
        )
        AgentCompanyMembership.objects.filter(agent=pending).update(status="pending")

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["total_agents"], 1)

    def test_active_agent_via_login_today(self):
        agent = create_agent(self.company)
        User.objects.filter(pk=agent.user.pk).update(last_login=now())

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_agents_today"], 1)

    def test_login_yesterday_not_active(self):
        agent = create_agent(self.company)
        User.objects.filter(pk=agent.user.pk).update(
            last_login=now() - timedelta(days=1)
        )

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_agents_today"], 0)

    def test_active_agent_via_visit_log_today(self):
        agent = create_agent(self.company)
        AgentVisitLog.objects.create(
            company=self.company,
            agent=agent,
            customer=self.customer,
            visit_date=self.today,
        )

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_agents_today"], 1)

    def test_visit_yesterday_not_active(self):
        agent = create_agent(self.company)
        AgentVisitLog.objects.create(
            company=self.company,
            agent=agent,
            customer=self.customer,
            visit_date=self.today - timedelta(days=1),
        )

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_agents_today"], 0)

    def test_active_agent_via_order_today(self):
        agent = create_agent(self.company)
        create_order(self.company, self.customer, agent=agent)

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_agents_today"], 1)

    def test_order_without_agent_not_counted(self):
        create_order(self.company, self.customer)

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_agents_today"], 0)

    def test_activity_union_deduplicates_agent(self):
        agent = create_agent(self.company)
        User.objects.filter(pk=agent.user.pk).update(last_login=now())
        AgentVisitLog.objects.create(
            company=self.company,
            agent=agent,
            customer=self.customer,
            visit_date=self.today,
        )
        create_order(self.company, self.customer, agent=agent)

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_agents_today"], 1)

    def test_two_active_agents_sum_distinctly(self):
        a1 = create_agent(self.company)
        a2 = create_agent(self.company)
        AgentVisitLog.objects.create(
            company=self.company,
            agent=a1,
            customer=self.customer,
            visit_date=self.today,
        )
        create_order(self.company, self.customer, agent=a2)

        resp = self.client.get(URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_agents_today"], 2)


class BusinessStatsScopingTests(TestCase):
    def test_other_company_data_excluded(self):
        mine = create_company(name="Mine", status="active")
        theirs = create_company(name="Theirs", status="active")
        admin = create_user(role=RoleType.ADMIN, company=mine)

        their_customer = create_customer(theirs, trade_name="Foreign")
        create_invoice(
            theirs,
            their_customer,
            status="issued",
            due_date=now().date() - timedelta(days=1),
            amount_due="999.00",
        )
        foreign_agent = create_agent(theirs)
        AgentVisitLog.objects.create(
            company=theirs,
            agent=foreign_agent,
            customer=their_customer,
            visit_date=now().date(),
        )

        resp = self.client.get(URL, **get_jwt_headers(admin))
        data = resp.data
        self.assertEqual(data["total_customers"], 0)
        self.assertEqual(data["overdue_customers"], 0)
        self.assertEqual(data["overdue_invoices"], 0)
        self.assertEqual(data["total_agents"], 0)
        self.assertEqual(data["active_agents_today"], 0)
        self.assertEqual(str(data["overdue_total"]), "0.00")
