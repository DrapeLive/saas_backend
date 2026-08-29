import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils.timezone import now
from rest_framework import status

from apps.accounts.models import RoleType
from apps.accounts.tests.factories import (
    create_company,
    create_customer,
    create_user,
    get_jwt_headers,
)
from apps.customers.models import CustomerCommunicationLog
from apps.invoices.models import Invoice
from apps.orders.models import Order
from apps.payments.models import Payment


def create_invoice(company, customer, status="issued", due_date=None, amount_due="1000.00", invoice_date=None):
    return Invoice.objects.create(
        company=company,
        invoice_type="sales_invoice",
        invoice_number=f"INV-{uuid.uuid4().hex[:10].upper()}",
        customer=customer,
        status=status,
        invoice_date=invoice_date or now().date(),
        due_date=due_date,
        subtotal=amount_due,
        taxable_amount=amount_due,
        total_amount=amount_due,
        amount_due=amount_due,
    )


def create_payment(company, customer, amount="500.00", payment_date=None, mode="bank", is_from_tally=False, invoice=None):
    return Payment.objects.create(
        company=company,
        customer=customer,
        invoice=invoice,
        amount=amount,
        payment_date=payment_date or now().date(),
        mode=mode,
        is_from_tally=is_from_tally,
    )


def create_order(company, customer, status="delivered", amount="2000.00", sync_status="synced", created_at=None):
    order = Order.objects.create(
        company=company,
        order_number=f"ORD-{uuid.uuid4().hex[:10].upper()}",
        customer=customer,
        status=status,
        total_amount=amount,
        sync_status=sync_status,
    )
    if created_at:
        Order.objects.filter(pk=order.pk).update(created_at=created_at)
        order.refresh_from_db()
    return order


class CustomerDetailAuthTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.agent_user = create_user(role=RoleType.AGENT, company=self.company, email="agent@detail.com")
        self.customer = create_customer(self.company, trade_name="Detail Co")

    def _paths(self, customer_id):
        return {
            "summary": f"/api/admin/customers/{customer_id}/summary/",
            "orders": f"/api/admin/customers/{customer_id}/orders/",
            "payments": f"/api/admin/customers/{customer_id}/payments/",
            "outstanding": f"/api/admin/customers/{customer_id}/outstanding/",
        }

    def test_unauthenticated_blocked(self):
        paths = self._paths(self.customer.id)
        for name, path in paths.items():
            with self.subTest(page=name):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_access_all(self):
        paths = self._paths(self.customer.id)
        for name, path in paths.items():
            with self.subTest(page=name):
                resp = self.client.get(path, **get_jwt_headers(self.admin))
                self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_agent_blocked(self):
        paths = self._paths(self.customer.id)
        for name, path in paths.items():
            with self.subTest(page=name):
                resp = self.client.get(path, **get_jwt_headers(self.agent_user))
                self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_customer_404(self):
        resp = self.client.get(
            f"/api/admin/customers/{uuid.uuid4()}/summary/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)


class CustomerSummaryTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(
            self.company,
            trade_name="Summary Co",
            phone="1111111111",
            whatsapp_number="1111111111",
            billing_address_line1="1 Main St",
            billing_city="Mumbai",
            credit_limit=100000,
            credit_utilized=40000,
        )
        self.today = now().date()
        self.url = f"/api/admin/customers/{self.customer.id}/summary/"

    def test_empty_summary_defaults(self):
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(data["name"], "Summary Co")
        self.assertEqual(data["phone"], "1111111111")
        self.assertEqual(data["whatsapp_number"], "1111111111")
        self.assertEqual(data["billing_address"]["city"], "Mumbai")
        self.assertEqual(str(data["credit_limit"]), "100000.00")
        self.assertEqual(data["credit_utilization_pct"], 40.0)
        self.assertEqual(str(data["available_limit"]), "60000.00")
        self.assertEqual(data["recent_activity"], [])
        self.assertEqual(data["recent_payments"], [])

    def test_aging_buckets_and_percentages(self):
        create_invoice(
            self.company,
            self.customer,
            due_date=self.today - timedelta(days=10),
            amount_due="400.00",
        )
        create_invoice(
            self.company,
            self.customer,
            due_date=self.today - timedelta(days=45),
            amount_due="350.00",
        )
        create_invoice(
            self.company,
            self.customer,
            due_date=self.today - timedelta(days=100),
            amount_due="250.00",
        )
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        buckets = data["outstanding"]["buckets"]
        by_bucket = {b["bucket"]: b for b in buckets}
        self.assertEqual(str(by_bucket["0-30"]["amount"]), "400.00")
        self.assertEqual(str(by_bucket["31-60"]["amount"]), "350.00")
        self.assertEqual(str(by_bucket["60+"]["amount"]), "250.00")
        self.assertEqual(str(data["outstanding"]["total_outstanding"]), "1000.00")
        self.assertEqual(by_bucket["0-30"]["percentage"], 40.0)
        self.assertEqual(by_bucket["31-60"]["percentage"], 35.0)
        self.assertEqual(by_bucket["60+"]["percentage"], 25.0)

    def test_recent_activity_merges_and_sorts(self):
        CustomerCommunicationLog.objects.create(
            company=self.company,
            customer=self.customer,
            channel="whatsapp",
            subject="Invoice follow up",
            message="INV-123 sent on 10 aug",
        )
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        activity = resp.data["recent_activity"]
        self.assertEqual(len(activity), 1)
        self.assertEqual(activity[0]["type"], "follow_up")
        self.assertEqual(activity[0]["subject"], "Invoice follow up")

    def test_recent_payments_with_tally_status(self):
        create_payment(self.company, self.customer, amount="100.00", is_from_tally=True)
        create_payment(self.company, self.customer, amount="50.00", is_from_tally=False)
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        payments = resp.data["recent_payments"]
        self.assertEqual(len(payments), 2)
        statuses = {p["tally_sync_status"] for p in payments}
        self.assertEqual(statuses, {"synced", "pending"})


class CustomerOrdersTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(self.company, trade_name="Orders Co")
        self.url = f"/api/admin/customers/{self.customer.id}/orders/"

    def test_empty_orders_defaults(self):
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(str(data["lifetime_value"]), "0.00")
        self.assertEqual(data["pending_orders"], 0)
        self.assertEqual(str(data["avg_order_value"]), "0.00")
        self.assertEqual(data["recent_orders"], [])

    def test_lifetime_pending_and_avg(self):
        create_order(self.company, self.customer, status="delivered", amount="2000.00")
        create_order(self.company, self.customer, status="delivered", amount="4000.00")
        create_order(self.company, self.customer, status="processing", amount="1000.00")
        create_order(self.company, self.customer, status="cancelled", amount="9999.00")
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(str(data["lifetime_value"]), "7000.00")
        self.assertEqual(str(data["avg_order_value"]), "2333.33")
        # pending = submitted..on_hold (not delivered, not cancelled): only processing
        self.assertEqual(data["pending_orders"], 1)

    def test_recent_orders_and_tally_status(self):
        create_order(self.company, self.customer, status="delivered", amount="2000.00", sync_status="synced")
        create_order(self.company, self.customer, status="processing", amount="1000.00", sync_status="pending")
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(len(data["recent_orders"]), 2)
        self.assertEqual(data["recent_orders"][0]["status"], "processing")
        self.assertEqual(data["tally_sync_status"]["synced"], 1)
        self.assertEqual(data["tally_sync_status"]["pending"], 1)


class CustomerPaymentsTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(self.company, trade_name="Pay Co")
        self.today = now().date()
        self.url = f"/api/admin/customers/{self.customer.id}/payments/"

    def test_empty_payments_defaults(self):
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(str(data["total_paid"]), "0.00")
        self.assertIsNone(data["paid_change_pct"])
        self.assertEqual(str(data["outstanding"]), "0.00")
        self.assertEqual(data["recent_transactions"], [])
        self.assertIsNone(data["upcoming_payment"])

    def test_total_paid_and_change_pct(self):
        jan1 = self.today.replace(month=1, day=1)
        create_payment(self.company, self.customer, amount="1000.00", payment_date=jan1)
        # Prior year same window
        prior_year = self.today.replace(year=self.today.year - 1, month=1, day=1)
        create_payment(
            self.company,
            self.customer,
            amount="500.00",
            payment_date=prior_year + timedelta(days=5),
        )
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(str(data["total_paid"]), "1000.00")
        # ytd=1000, prior same-window=500 -> +100%
        self.assertEqual(data["paid_change_pct"], 100.0)

    def test_outstanding_and_upcoming(self):
        future = self.today + timedelta(days=10)
        create_invoice(self.company, self.customer, due_date=future, amount_due="750.00")
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(str(data["outstanding"]), "750.00")
        self.assertEqual(data["upcoming_payment"]["invoice_number"], data["upcoming_payment"]["invoice_number"])
        self.assertEqual(str(data["upcoming_payment"]["amount"]), "750.00")

    def test_recent_transactions(self):
        create_payment(self.company, self.customer, amount="200.00", mode="upi")
        create_payment(self.company, self.customer, amount="300.00", mode="bank")
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        txn = resp.data["recent_transactions"]
        self.assertEqual(len(txn), 2)
        self.assertEqual({t["type"] for t in txn}, {"upi", "bank"})


class CustomerOutstandingTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)
        self.customer = create_customer(
            self.company,
            trade_name="Outstanding Co",
            credit_limit=100000,
            credit_utilized=30000,
        )
        self.today = now().date()
        self.url = f"/api/admin/customers/{self.customer.id}/outstanding/"

    def test_empty_outstanding_defaults(self):
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(str(data["total_paid_ytd"]), "0.00")
        self.assertEqual(str(data["total_outstanding"]), "0.00")
        self.assertIsNone(data["last_payment_date"])
        self.assertEqual(data["credit_utilization_pct"], 30.0)
        self.assertEqual(str(data["available_limit"]), "70000.00")
        self.assertEqual(data["avg_pay_days"], 0)
        self.assertEqual(data["critical_invoices"], [])

    def test_ytd_last_payment_and_critical(self):
        create_payment(self.company, self.customer, amount="500.00", payment_date=self.today - timedelta(days=3))
        # overdue invoice -> critical
        create_invoice(
            self.company,
            self.customer,
            due_date=self.today - timedelta(days=20),
            amount_due="900.00",
        )
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(str(data["total_paid_ytd"]), "500.00")
        self.assertEqual(str(data["total_outstanding"]), "900.00")
        self.assertEqual(data["last_payment_date"], (self.today - timedelta(days=3)).isoformat())
        self.assertEqual(len(data["critical_invoices"]), 1)
        self.assertEqual(data["critical_invoices"][0]["days_past_due"], 20)
        self.assertEqual(str(data["critical_invoices"][0]["amount"]), "900.00")

    def test_aging_analysis(self):
        create_invoice(
            self.company,
            self.customer,
            due_date=self.today - timedelta(days=10),
            amount_due="700.00",
        )
        create_invoice(
            self.company,
            self.customer,
            due_date=self.today - timedelta(days=100),
            amount_due="300.00",
        )
        resp = self.client.get(self.url, **get_jwt_headers(self.admin))
        buckets = resp.data["aging_analysis"]
        by_bucket = {b["bucket"]: b for b in buckets}
        self.assertEqual(str(by_bucket["0-30"]["amount"]), "700.00")
        self.assertEqual(str(by_bucket["60+"]["amount"]), "300.00")


class CustomerDetailIsolationTests(TestCase):
    def setUp(self):
        self.mine = create_company(name="Mine", status="active")
        self.theirs = create_company(name="Theirs", status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.mine)
        self.their_customer = create_customer(self.theirs, trade_name="Foreign")

    def test_other_company_customer_not_accessible(self):
        resp = self.client.get(
            f"/api/admin/customers/{self.their_customer.id}/summary/",
            **get_jwt_headers(self.admin),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)
