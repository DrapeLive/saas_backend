import uuid

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
from apps.invoices.models import Invoice

OVERVIEW_URL = "/api/admin/customers/overview/"
LIST_URL = "/api/admin/customers/"


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


class CustomerOverviewAuthTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def test_requires_authentication(self):
        resp = self.client.get(OVERVIEW_URL)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_admin_can_access(self):
        resp = self.client.get(OVERVIEW_URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class CustomerOverviewTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def test_empty_company_returns_zeroes(self):
        resp = self.client.get(OVERVIEW_URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(
            resp.data,
            {
                "active_customer_count": 0,
                "total_outstanding_receivable": "0.00",
            },
        )

    def test_active_count_excludes_non_active_statuses(self):
        create_customer(self.company, trade_name="Active", status="active")
        create_customer(self.company, trade_name="Inactive", status="inactive")
        create_customer(self.company, trade_name="Blocked", status="blocked")
        create_customer(self.company, trade_name="Prospect", status="prospect")

        resp = self.client.get(OVERVIEW_URL, **get_jwt_headers(self.admin))
        self.assertEqual(resp.data["active_customer_count"], 1)

    def test_total_sums_only_unpaid_invoice_statuses(self):
        customer = create_customer(self.company)
        create_invoice(self.company, customer, status="issued", amount_due="500.00")
        create_invoice(self.company, customer, status="partial", amount_due="250.00")
        create_invoice(self.company, customer, status="overdue", amount_due="100.00")
        # Excluded statuses
        create_invoice(self.company, customer, status="draft", amount_due="70.00")
        create_invoice(self.company, customer, status="paid", amount_due="80.00")
        create_invoice(self.company, customer, status="void", amount_due="90.00")

        resp = self.client.get(OVERVIEW_URL, **get_jwt_headers(self.admin))
        self.assertEqual(str(resp.data["total_outstanding_receivable"]), "850.00")


class CustomerListPaginationTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def test_paginated_envelope_and_page_size(self):
        for i in range(3):
            create_customer(self.company, trade_name=f"Customer {i}")

        resp = self.client.get(LIST_URL + "?page_size=2", **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.data
        self.assertEqual(set(data.keys()), {"count", "next", "previous", "results"})
        self.assertEqual(data["count"], 3)
        self.assertIsNone(data["previous"])
        self.assertIsNotNone(data["next"])
        self.assertEqual(len(data["results"]), 2)

    def test_default_page_size_is_20(self):
        for i in range(23):
            create_customer(self.company, trade_name=f"Customer {i:02d}")

        resp = self.client.get(LIST_URL, **get_jwt_headers(self.admin))
        data = resp.data
        self.assertEqual(data["count"], 23)
        self.assertEqual(len(data["results"]), 20)
        self.assertIsNotNone(data["next"])


class CustomerOrderingTests(TestCase):
    def setUp(self):
        self.company = create_company(status="active")
        self.admin = create_user(role=RoleType.ADMIN, company=self.company)

    def _list_ids(self, query=""):
        resp = self.client.get(LIST_URL + query, **get_jwt_headers(self.admin))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        return [row["id"] for row in resp.data["results"]]

    def test_invalid_ordering_falls_back_to_created_desc(self):
        first = create_customer(self.company, trade_name="Alpha")
        second = create_customer(self.company, trade_name="Beta")

        ids = self._list_ids("?ordering=evil_field")
        self.assertEqual(ids, [str(second.id), str(first.id)])

    def test_ordering_by_total_outstanding_desc(self):
        rich = create_customer(self.company, trade_name="Rich")
        poor = create_customer(self.company, trade_name="Poor")
        create_invoice(self.company, rich, status="issued", amount_due="500.00")
        create_invoice(self.company, poor, status="issued", amount_due="50.00")

        ids = self._list_ids("?ordering=-total_outstanding")
        self.assertEqual(ids[0], str(rich.id))
        self.assertEqual(ids[-1], str(poor.id))


class CustomerOverviewScopingTests(TestCase):
    def test_other_company_data_excluded(self):
        mine = create_company(name="Mine", status="active")
        theirs = create_company(name="Theirs", status="active")
        admin = create_user(role=RoleType.ADMIN, company=mine)
        their_customer = create_customer(theirs, trade_name="Foreign")
        create_invoice(theirs, their_customer, status="issued", amount_due="999.00")

        resp = self.client.get(OVERVIEW_URL, **get_jwt_headers(admin))
        self.assertEqual(resp.data["active_customer_count"], 0)
        self.assertEqual(str(resp.data["total_outstanding_receivable"]), "0.00")
