from datetime import date, timedelta
from decimal import Decimal
import uuid

from django.test import TestCase
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_user,
    get_jwt_headers,
)
from apps.agents.models import (
    AgentCompanyMembership,
    AgentCreditLimit,
    AgentProfile,
)
from apps.commissions.models import CommissionEntry, CommissionPayout
from apps.companies.models import Company, CompanySettings
from apps.customers.models import CustomerProfile
from apps.invoices.models import Invoice
from apps.orders.models import Order
from apps.payments.models import Payment
from apps.products.models import Category, ColorVariant, Product, VariantSize


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


def create_order(company, customer, agent=None, amount="1000.00", sync_status="synced", status_="delivered"):
    return Order.objects.create(
        company=company,
        order_number=f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}",
        customer=customer,
        agent=agent,
        total_amount=amount,
        status=status_,
        sync_status=sync_status,
        submitted_at=now(),
    )


def create_invoice(company, customer, order=None, status_="issued", amount_due="1000.00", tally_synced_at=None):
    return Invoice.objects.create(
        company=company,
        invoice_type="sales_invoice",
        invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
        customer=customer,
        order=order,
        status=status_,
        invoice_date=now().date(),
        subtotal=amount_due,
        taxable_amount=amount_due,
        total_amount=amount_due,
        amount_due=amount_due,
        tally_synced_at=tally_synced_at,
    )


def create_payment(company, customer, agent=None, amount="500.00", payment_date=None, is_from_tally=False):
    return Payment.objects.create(
        company=company,
        customer=customer,
        agent=agent,
        amount=amount,
        payment_date=payment_date or now().date(),
        mode="bank",
        is_from_tally=is_from_tally,
    )


def create_commission(order, agent, amount, status_, month, adjusted=False):
    entry = CommissionEntry.objects.create(
        company=order.company,
        agent=agent,
        order=order,
        order_value=amount * 10,
        commission_pct=10.00,
        commission_amount=amount,
        status=status_,
        settlement_month=month,
        adjustment_notes="Adjusted" if (status_ == "adjusted" or adjusted) else "",
    )
    return entry


def dec(value):
    return Decimal(str(value))


class BaseAgentDetailTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.sub_admin = create_user(role=RoleType.SUB_ADMIN, company=self.company)
        self.agent = create_agent(self.company, "agent@detail.com", "Agent Detail")
        self.other_agent = create_agent(self.company, "other@detail.com", "Other Agent")
        self.membership = AgentCompanyMembership.objects.get(agent=self.agent, company=self.company)
        self.agent_user = self.agent.user

    @property
    def base(self):
        return f"/api/admin/agents/{self.membership.id}"

    def _paths(self):
        return {
            "overview": f"{self.base}/overview",
            "transactions": f"{self.base}/transactions",
            "commission": f"{self.base}/commission",
            "payouts": f"{self.base}/payouts",
            "adjustments": f"{self.base}/adjustments",
        }


class AgentDetailAuthTests(BaseAgentDetailTests):
    def test_unauthenticated_blocked(self):
        for name, path in self._paths().items():
            with self.subTest(page=name):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_access_all(self):
        for name, path in self._paths().items():
            with self.subTest(page=name):
                resp = self.client.get(path, **get_jwt_headers(self.admin))
                self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_sub_admin_can_access_all(self):
        for name, path in self._paths().items():
            with self.subTest(page=name):
                resp = self.client.get(path, **get_jwt_headers(self.sub_admin))
                self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_agent_blocked(self):
        for name, path in self._paths().items():
            with self.subTest(page=name):
                resp = self.client.get(path, **get_jwt_headers(self.agent_user))
                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_superadmin_blocked(self):
        from apps.accounts.tests.factories import create_super_admin

        super_admin = create_super_admin()
        for name, path in self._paths().items():
            with self.subTest(page=name):
                resp = self.client.get(path, **get_jwt_headers(super_admin))
                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_agent_404(self):
        resp = self.client.get(
            f"/api/admin/agents/{uuid.uuid4()}/overview",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_other_company_agent_404(self):
        other = create_company(name="Other", status="active")
        other_agent = create_agent(other, "foreign@x.com", "Foreign Agent")
        other_membership = AgentCompanyMembership.objects.get(
            agent=other_agent, company=other
        )
        resp = self.client.get(
            f"/api/admin/agents/{other_membership.id}/overview",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class AgentDetailOverviewTests(BaseAgentDetailTests):
    def test_empty_overview_defaults(self):
        resp = self.client.get(f"{self.base}/overview", **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(data["agent_id"], str(self.agent.id))
        self.assertEqual(data["agent_name"], "Agent Detail")
        # No credit row exists yet -> recompute creates one with zero utilized.
        self.assertEqual(dec(data["credit"]["credit_limit"]), Decimal("0.00"))
        self.assertEqual(dec(data["credit"]["credit_utilized"]), Decimal("0.00"))
        self.assertEqual(dec(data["credit"]["available_limit"]), Decimal("0.00"))
        self.assertEqual(data["credit"]["credit_utilization_pct"], 0.0)
        self.assertEqual(dec(data["total_paid_ytd"]), Decimal("0.00"))
        self.assertEqual(data["pending_sync"], {"orders": 0, "invoices": 0, "payments": 0})
        self.assertEqual(data["recent_transactions"], [])
        self.assertIsNone(data["invoice_tally"])

    def test_credit_card_from_unpaid_invoices(self):
        cust = create_customer(self.company, "Cust")
        order1 = create_order(self.company, cust, agent=self.agent)
        order2 = create_order(self.company, cust, agent=self.agent)
        AgentCreditLimit.objects.create(
            company=self.company, agent=self.agent, credit_limit=10000
        )
        # unpaid invoice worth 3000 (issued) on order1
        create_invoice(self.company, cust, order=order1, amount_due="3000.00")
        # paid invoice worth 2000 on order2 -> NOT counted
        create_invoice(
            self.company, cust, order=order2, amount_due="2000.00", status_="paid"
        )

        resp = self.client.get(f"{self.base}/overview", **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(dec(data["credit"]["credit_utilized"]), Decimal("3000.00"))
        self.assertEqual(dec(data["credit"]["available_limit"]), Decimal("7000.00"))
        self.assertEqual(data["credit"]["credit_utilization_pct"], 30.0)

    def test_total_paid_ytd(self):
        cust = create_customer(self.company, "Cust")
        other_cust = create_customer(self.company, "Other")
        today = now().date()
        # agent's payment this year
        create_payment(self.company, cust, agent=self.agent, amount="1200.00", payment_date=today)
        # another agent's payment must NOT count
        create_payment(
            self.company, other_cust, agent=self.other_agent, amount="9999.00", payment_date=today
        )
        # agent's payment last year must NOT count
        create_payment(
            self.company,
            cust,
            agent=self.agent,
            amount="5000.00",
            payment_date=today.replace(year=today.year - 1),
        )

        resp = self.client.get(f"{self.base}/overview", **get_jwt_headers(self.admin))
        self.assertEqual(dec(resp.data["total_paid_ytd"]), Decimal("1200.00"))

    def test_pending_sync_tally(self):
        cust = create_customer(self.company, "Cust")
        o_pending = create_order(self.company, cust, agent=self.agent, sync_status="pending")
        o_synced = create_order(self.company, cust, agent=self.agent, sync_status="synced")
        create_invoice(self.company, cust, order=o_pending, tally_synced_at=None)
        create_invoice(self.company, cust, order=o_synced, tally_synced_at=now())
        create_payment(self.company, cust, agent=self.agent, is_from_tally=False)
        create_payment(self.company, cust, agent=self.agent, is_from_tally=True)

        resp = self.client.get(f"{self.base}/overview", **get_jwt_headers(self.admin))
        tally = resp.data["pending_sync"]
        self.assertEqual(tally["orders"], 1)
        self.assertEqual(tally["invoices"], 1)
        self.assertEqual(tally["payments"], 1)

    def test_recent_transactions_included(self):
        cust = create_customer(self.company, "Cust")
        order = create_order(self.company, cust, agent=self.agent)
        month = date(2026, 8, 1)
        create_commission(order, self.agent, 100, "approved", month)
        CommissionPayout.objects.create(
            company=self.company,
            agent=self.agent,
            settlement_month=month,
            amount=100,
            entries_count=1,
            paid_at=now(),
        )
        resp = self.client.get(f"{self.base}/overview", **get_jwt_headers(self.admin))
        txns = resp.data["recent_transactions"]
        self.assertEqual(len(txns), 2)
        types = {t["type"] for t in txns}
        self.assertEqual(types, {"order_commission", "payout"})


class AgentDetailTransactionsTests(BaseAgentDetailTests):
    def setUp(self):
        super().setUp()
        self.cust = create_customer(self.company, "Cust")
        self.order = create_order(self.company, self.cust, agent=self.agent)
        self.month = date(2026, 8, 1)
        self.entry = create_commission(self.order, self.agent, 100, "approved", self.month)
        self.payout = CommissionPayout.objects.create(
            company=self.company,
            agent=self.agent,
            settlement_month=self.month,
            amount=100,
            entries_count=1,
            paid_at=now(),
        )

    def test_merges_payout_and_commission(self):
        resp = self.client.get(f"{self.base}/transactions", **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(len(data), 2)
        types = {t["type"] for t in data}
        self.assertEqual(types, {"payout", "order_commission"})
        commission = next(t for t in data if t["type"] == "order_commission")
        self.assertEqual(dec(commission["amount"]), Decimal("100.00"))
        payout = next(t for t in data if t["type"] == "payout")
        self.assertEqual(dec(payout["amount"]), Decimal("100.00"))

    def test_type_filter_payout(self):
        resp = self.client.get(
            f"{self.base}/transactions?type=payout", **get_jwt_headers(self.admin)
        )
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "payout")

    def test_type_filter_order_commission(self):
        resp = self.client.get(
            f"{self.base}/transactions?type=order_commission", **get_jwt_headers(self.admin)
        )
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "order_commission")

    def test_type_filter_adjustment(self):
        # only adjustment rows match
        self.entry.status = "adjusted"
        self.entry.adjustment_notes = "bonus fix"
        self.entry.save()
        resp = self.client.get(
            f"{self.base}/transactions?type=adjustment", **get_jwt_headers(self.admin)
        )
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "adjustment")

    def test_month_filter(self):
        other_month = date(2026, 7, 1)
        other_order = create_order(self.company, self.cust, agent=self.agent)
        create_commission(other_order, self.agent, 250, "approved", other_month)
        resp = self.client.get(
            f"{self.base}/transactions?month=2026-08-01", **get_jwt_headers(self.admin)
        )
        self.assertEqual(len(resp.data), 2)  # payout + entry this month only

    def test_status_filter_applies_to_commission(self):
        resp = self.client.get(
            f"{self.base}/transactions?status=paid", **get_jwt_headers(self.admin)
        )
        # commission is 'approved' -> filtered out; payout (status 'paid') remains
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "payout")


class AgentDetailCommissionTests(BaseAgentDetailTests):
    def setUp(self):
        super().setUp()
        self.cust = create_customer(self.company, "Cust")
        self.order = create_order(self.company, self.cust, agent=self.agent)
        self.month = date(2026, 8, 1)

    def test_lists_only_this_agent(self):
        create_commission(self.order, self.agent, 100, "approved", self.month)
        other_cust = create_customer(self.company, "Other")
        other_order = create_order(self.company, other_cust, agent=self.other_agent)
        create_commission(other_order, self.other_agent, 999, "approved", self.month)

        resp = self.client.get(f"{self.base}/commission", **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(dec(data[0]["commission_amount"]), Decimal("100.00"))

    def test_status_filter(self):
        o2 = create_order(self.company, self.cust, agent=self.agent)
        create_commission(self.order, self.agent, 100, "pending", self.month)
        create_commission(o2, self.agent, 200, "paid", self.month)

        resp = self.client.get(
            f"{self.base}/commission?status=paid", **get_jwt_headers(self.admin)
        )
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["status"], "paid")

    def test_month_filter(self):
        o2 = create_order(self.company, self.cust, agent=self.agent)
        create_commission(self.order, self.agent, 100, "approved", self.month)
        create_commission(o2, self.agent, 200, "approved", date(2026, 7, 1))

        resp = self.client.get(
            f"{self.base}/commission?month=2026-07-01", **get_jwt_headers(self.admin)
        )
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(dec(data[0]["commission_amount"]), Decimal("200.00"))


class AgentDetailPayoutsTests(BaseAgentDetailTests):
    def setUp(self):
        super().setUp()
        self.month = date(2026, 8, 1)

    def test_lists_only_this_agent(self):
        CommissionPayout.objects.create(
            company=self.company, agent=self.agent, settlement_month=self.month,
            amount=300, entries_count=2, paid_at=now(),
        )
        CommissionPayout.objects.create(
            company=self.company, agent=self.other_agent, settlement_month=self.month,
            amount=999, entries_count=1, paid_at=now(),
        )
        resp = self.client.get(f"{self.base}/payouts", **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(dec(data[0]["amount"]), Decimal("300.00"))


class AgentDetailAdjustmentsTests(BaseAgentDetailTests):
    def setUp(self):
        super().setUp()
        self.cust = create_customer(self.company, "Cust")
        self.order = create_order(self.company, self.cust, agent=self.agent)
        self.month = date(2026, 8, 1)

    def test_lists_only_adjusted_entries(self):
        create_commission(self.order, self.agent, 100, "adjusted", self.month)
        o2 = create_order(self.company, self.cust, agent=self.agent)
        create_commission(o2, self.agent, 200, "approved", self.month)

        resp = self.client.get(f"{self.base}/adjustments", **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["status"], "adjusted")
        self.assertEqual(dec(data[0]["commission_amount"]), Decimal("100.00"))


class AgentCreditEnforcementTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.agent = create_agent(self.company, "cred-agent@x.com", "Credit Agent")
        self.customer = create_customer(self.company, "Credit Customer")
        CompanySettings.objects.update_or_create(company=self.company)
        CompanySettings.objects.filter(company=self.company).update(
            credit_block_on_exceed=True,
            order_approval_required=False,
            order_auto_confirm=True,
        )

    def _create_variant(self, price="500.00", stock=100):
        category, _ = Category.objects.get_or_create(
            company=self.company, slug="mens", defaults={"name": "Mens"}
        )
        product = Product.objects.create(
            company=self.company,
            category=category,
            name="Cotton Shirt",
            wholesale_price=price,
            mrp="999.00",
            order_in_multiples=1,
            minimum_order_qty=1,
        )
        color = ColorVariant.objects.create(product=product, color_name="Blue", sku="BLUE-1")
        return VariantSize.objects.create(
            color_variant=color, size="M", sku="SHIRT-M", stock_quantity=stock
        )

    def _post_order(self):
        variant = self._create_variant()
        payload = {
            "customer": str(self.customer.id),
            "items": [{"variant_size": str(variant.id), "quantity": 2, "discount_pct": 0}],
        }
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=get_jwt_headers(self.agent.user)["HTTP_AUTHORIZATION"]
        )
        return client.post("/api/orders/", payload, format="json")

    def test_order_blocked_when_agent_credit_exceeded(self):
        # Existing unpaid invoices already place the agent at the limit.
        order = create_order(self.company, self.customer, agent=self.agent)
        create_invoice(self.company, self.customer, order=order, amount_due="900.00")
        AgentCreditLimit.objects.create(
            company=self.company, agent=self.agent, credit_limit=1000, auto_block_on_exceed=True
        )

        resp = self._post_order()
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("credit limit", resp.data["detail"].lower())

    def test_order_allowed_within_agent_credit(self):
        order = create_order(self.company, self.customer, agent=self.agent)
        create_invoice(self.company, self.customer, order=order, amount_due="100.00")
        AgentCreditLimit.objects.create(
            company=self.company, agent=self.agent, credit_limit=50000, auto_block_on_exceed=True
        )

        resp = self._post_order()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_order_allowed_when_block_flag_off(self):
        order = create_order(self.company, self.customer, agent=self.agent)
        create_invoice(self.company, self.customer, order=order, amount_due="900.00")
        AgentCreditLimit.objects.create(
            company=self.company, agent=self.agent, credit_limit=1000, auto_block_on_exceed=False
        )

        resp = self._post_order()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

    def test_order_not_blocked_when_utilized_zero_and_limit_zero(self):
        # Default limit of 0 means no credit cap (matches customer behavior).
        resp = self._post_order()
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
