from datetime import timedelta

from django.test import TestCase
from django.urls import resolve
from django.utils.timezone import now
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import status as http_status

from apps.accounts.models import RoleType, User
from apps.companies.models import Company
from apps.customers.models import CustomerProfile
from apps.orders.models import Order, OrderStatus


class RecentOrdersApiTests(TestCase):
    """Tests for GET /api/admin/dashboard/recent-orders."""

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme Apparel",
            slug="acme-apparel",
            contact_email="acme@example.com",
            contact_phone="9999999999",
            state="Maharashtra",
        )
        self.other_company = Company.objects.create(
            name="Other Co",
            slug="other-co",
            contact_email="other@example.com",
            contact_phone="8888888888",
            state="Karnataka",
        )
        self.admin_user = User.objects.create_user(
            email="admin@example.com",
            password="secret",
            full_name="Admin One",
            role=RoleType.ADMIN,
            company=self.company,
        )
        self.customer = CustomerProfile.objects.create(
            company=self.company,
            trade_name="Corner Shop",
            phone="8888888888",
            billing_state="Maharashtra",
        )
        self.other_customer = CustomerProfile.objects.create(
            company=self.other_company,
            trade_name="Foreign Shop",
            phone="7777777777",
            billing_state="Karnataka",
        )
        self.client = APIClient()

    def _access_token(self, user):
        refresh = RefreshToken.for_user(user)
        refresh["company_id"] = str(user.company_id)
        return str(refresh.access_token)

    def _authenticate_admin(self):
        token = self._access_token(self.admin_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def _create_order(self, company, customer, number, status, total, created_at):
        return Order.objects.create(
            company=company,
            customer=customer,
            order_number=number,
            status=status,
            total_amount=total,
            created_at=created_at,
        )

    def test_recent_orders_url_resolves(self):
        resolver = resolve("/api/admin/dashboard/recent-orders")
        self.assertEqual(resolver.url_name, "admin-dashboard-recent-orders")

    def test_recent_orders_returns_200_for_authorized_admin(self):
        base = now()
        self._create_order(
            self.company, self.customer, "ORD-001", OrderStatus.SUBMITTED,
            "100.00", base - timedelta(days=2),
        )
        self._authenticate_admin()
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)

    def test_recent_orders_returns_valid_json_list(self):
        self._create_order(
            self.company, self.customer, "ORD-001", OrderStatus.SUBMITTED,
            "100.00", now() - timedelta(days=1),
        )
        self._authenticate_admin()
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)

    def test_recent_orders_sorted_newest_first(self):
        base = now()
        self._create_order(
            self.company, self.customer, "ORD-OLD", OrderStatus.SUBMITTED,
            "10.00", base - timedelta(days=5),
        )
        self._create_order(
            self.company, self.customer, "ORD-NEW", OrderStatus.SUBMITTED,
            "20.00", base - timedelta(days=1),
        )
        self._create_order(
            self.company, self.customer, "ORD-MID", OrderStatus.SUBMITTED,
            "30.00", base - timedelta(days=3),
        )
        self._authenticate_admin()
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        numbers = [item["order_name"] for item in response.data]
        self.assertEqual(numbers, ["ORD-NEW", "ORD-MID", "ORD-OLD"])

    def test_recent_orders_respects_limit_of_three(self):
        base = now()
        for i in range(5):
            self._create_order(
                self.company, self.customer, f"ORD-{i:02d}",
                OrderStatus.SUBMITTED, "10.00", base - timedelta(days=i),
            )
        self._authenticate_admin()
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)

    def test_recent_orders_excludes_other_company_orders(self):
        self._create_order(
            self.company, self.customer, "ORD-OWN", OrderStatus.SUBMITTED,
            "100.00", now() - timedelta(days=1),
        )
        self._create_order(
            self.other_company, self.other_customer, "ORD-FOREIGN",
            OrderStatus.SUBMITTED, "999.00", now() - timedelta(hours=1),
        )
        self._authenticate_admin()
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        numbers = [item["order_name"] for item in response.data]
        self.assertIn("ORD-OWN", numbers)
        self.assertNotIn("ORD-FOREIGN", numbers)

    def test_recent_orders_excludes_draft_orders(self):
        self._create_order(
            self.company, self.customer, "ORD-DRAFT", OrderStatus.DRAFT,
            "50.00", now() - timedelta(hours=1),
        )
        self._create_order(
            self.company, self.customer, "ORD-SUBMITTED",
            OrderStatus.SUBMITTED, "75.00", now() - timedelta(days=1),
        )
        self._authenticate_admin()
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        numbers = [item["order_name"] for item in response.data]
        self.assertNotIn("ORD-DRAFT", numbers)
        self.assertIn("ORD-SUBMITTED", numbers)

    def test_recent_orders_unauthorized_rejected(self):
        self._create_order(
            self.company, self.customer, "ORD-001", OrderStatus.SUBMITTED,
            "100.00", now() - timedelta(days=1),
        )
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_401_UNAUTHORIZED)

    def test_recent_orders_empty_list_returns_200(self):
        self._authenticate_admin()
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_recent_orders_contains_required_fields(self):
        self._create_order(
            self.company, self.customer, "ORD-001", OrderStatus.PROCESSING,
            "1250.50", now() - timedelta(days=1),
        )
        self._authenticate_admin()
        response = self.client.get("/api/admin/dashboard/recent-orders")
        self.assertEqual(response.status_code, http_status.HTTP_200_OK)
        item = response.data[0]
        self.assertIn("id", item)
        self.assertEqual(item["order_name"], "ORD-001")
        self.assertEqual(item["customer_name"], "Corner Shop")
        self.assertEqual(item["payment"], 1250.50)
        self.assertEqual(item["status"], OrderStatus.PROCESSING)

    def test_recent_orders_get_does_not_modify_records(self):
        self._create_order(
            self.company, self.customer, "ORD-001", OrderStatus.SUBMITTED,
            "100.00", now() - timedelta(days=1),
        )
        before_count = Order.objects.filter(company=self.company).count()
        before_ids = set(
            Order.objects.filter(company=self.company).values_list("id", flat=True)
        )
        self._authenticate_admin()
        self.client.get("/api/admin/dashboard/recent-orders")
        after_count = Order.objects.filter(company=self.company).count()
        after_ids = set(
            Order.objects.filter(company=self.company).values_list("id", flat=True)
        )
        self.assertEqual(before_count, after_count)
        self.assertEqual(before_ids, after_ids)
