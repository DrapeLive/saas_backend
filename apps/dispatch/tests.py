from unittest.mock import patch

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import RoleType, User
from apps.companies.models import Company, CompanyStatus
from apps.customers.models import CustomerProfile
from apps.dispatch.models import Dispatch, Transport
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.products.models import Category, ColorVariant, Product, VariantSize


class DispatchTransportTestCase(TestCase):
    def setUp(self):
        self.company = self._company("acme", "Acme")
        self.other_company = self._company("globex", "Globex")
        self.admin = self._admin(self.company, "admin@acme.test")
        self.other_admin = self._admin(self.other_company, "admin@globex.test")
        self.transport = Transport.objects.create(
            company=self.company,
            name="Blue Dart",
            tracking_url="https://track.bluedart.com/awb",
        )
        self.order, self.variant = self._order(self.company, "acme")
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def _company(self, slug, name):
        return Company.objects.create(
            name=name,
            slug=slug,
            contact_email=f"{slug}@example.com",
            contact_phone="9999999999",
            status=CompanyStatus.ACTIVE,
        )

    def _admin(self, company, email):
        return User.objects.create_user(
            email=email,
            password="testpass123",
            full_name="Admin",
            role=RoleType.ADMIN,
            company=company,
        )

    def _user(self, company, email, role):
        return User.objects.create_user(
            email=email,
            password="testpass123",
            full_name=role,
            role=role,
            company=company,
        )

    def _order(self, company, suffix):
        customer = CustomerProfile.objects.create(
            company=company,
            legal_name=f"Customer {suffix}",
            trade_name=f"Customer {suffix}",
            phone="9999999999",
        )
        category = Category.objects.create(
            company=company, name=f"Mens {suffix}", slug=f"mens-{suffix}"
        )
        product = Product.objects.create(
            company=company, category=category, name=f"Shirt {suffix}", total_stock=10
        )
        color = ColorVariant.objects.create(
            product=product, color_name="Blue", sku=f"SKU-{suffix}"
        )
        variant = VariantSize.objects.create(
            color_variant=color,
            size="M",
            sku=f"SKU-{suffix}-M",
            stock_quantity=10,
            reserved_qty=2,
        )
        order = Order.objects.create(
            company=company,
            customer=customer,
            order_number=f"ORD-{suffix}",
            status=OrderStatus.PACKED,
            total_amount=200,
        )
        OrderItem.objects.create(
            order=order,
            variant_size=variant,
            product_name=f"Shirt {suffix}",
            color_name="Blue",
            size="M",
            sku=variant.sku,
            unit_price=100,
            quantity=2,
            line_total=200,
        )
        return order, variant

    def _dispatch_payload(self, **overrides):
        payload = {
            "order": str(self.order.id),
            "transport_id": str(self.transport.id),
            "lr_number": "LR-001",
            "boxes_count": 2,
            "weight_kg": "1.50",
        }
        payload.update(overrides)
        return payload

    # ── Transport management ────────────────────────────────────────

    def test_transport_list_is_tenant_scoped(self):
        Transport.objects.create(company=self.other_company, name="Other Transport")

        response = self.client.get("/api/transports/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["name"], "Blue Dart")

    def test_transport_list_filters_active(self):
        Transport.objects.create(
            company=self.company, name="Inactive Transport", is_active=False
        )

        response = self.client.get("/api/transports/?active=true")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([t["name"] for t in response.data], ["Blue Dart"])

    def test_transport_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.get("/api/transports/")

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_create_transport_trims_name(self):
        response = self.client.post(
            "/api/transports/",
            {"name": "  Delhivery  ", "tracking_url": "https://delhivery.com/track"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        transport = Transport.objects.get(pk=response.data["id"])
        self.assertEqual(transport.name, "Delhivery")
        self.assertEqual(transport.company, self.company)

    def test_create_transport_requires_non_blank_name(self):
        for name in ("", "   "):
            with self.subTest(name=name):
                response = self.client.post(
                    "/api/transports/", {"name": name}, format="json"
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertIn("detail", response.data)

    def test_create_transport_allows_empty_tracking_url(self):
        response = self.client.post(
            "/api/transports/", {"name": "No Tracking"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["tracking_url"], "")

    def test_create_transport_rejects_name_over_model_limit(self):
        response = self.client.post(
            "/api/transports/", {"name": "x" * 201}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("200 characters", response.data["detail"])

    def test_database_constraint_blocks_case_insensitive_duplicates(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Transport.objects.create(company=self.company, name="BLUE DART")

    def test_create_transport_handles_duplicate_race_as_bad_request(self):
        with patch(
            "apps.dispatch.views.TransportSerializer.save",
            side_effect=IntegrityError("duplicate key"),
        ):
            response = self.client.post(
                "/api/transports/", {"name": "Racing Carrier"}, format="json"
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.data["detail"])

    def test_subadmin_can_list_transports_but_cannot_write(self):
        subadmin = self._user(self.company, "sub@acme.test", RoleType.SUB_ADMIN)
        self.client.force_authenticate(user=subadmin)

        self.assertEqual(
            self.client.get("/api/transports/").status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(
                "/api/transports/", {"name": "Blocked"}, format="json"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/transports/{self.transport.id}/",
                {"name": "Blocked"},
                format="json",
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.delete(
                f"/api/transports/{self.transport.id}/"
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_agent_cannot_create_transport(self):
        agent = self._user(self.company, "agent@acme.test", RoleType.AGENT)
        self.client.force_authenticate(user=agent)

        response = self.client.post(
            "/api/transports/", {"name": "Blocked"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_transport_detail_is_tenant_scoped(self):
        self.client.force_authenticate(user=self.other_admin)

        self.assertEqual(
            self.client.get(
                f"/api/transports/{self.transport.id}/"
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/transports/{self.transport.id}/",
                {"name": "Hijacked"},
                format="json",
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_transport_name_is_unique_per_company_case_insensitively(self):
        response = self.client.post(
            "/api/transports/", {"name": " blue dart "}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already exists", response.data["detail"])

    def test_same_transport_name_allowed_in_another_company(self):
        self.client.force_authenticate(user=self.other_admin)

        response = self.client.post(
            "/api/transports/", {"name": "Blue Dart"}, format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_tracking_url_must_be_https(self):
        for url in ("http://example.com/track", "javascript:alert(1)", "file:///etc/passwd"):
            with self.subTest(url=url):
                response = self.client.post(
                    "/api/transports/",
                    {"name": f"Transport {url}", "tracking_url": url},
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_transport(self):
        response = self.client.patch(
            f"/api/transports/{self.transport.id}/",
            {"name": "Blue Dart Express", "is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.transport.refresh_from_db()
        self.assertEqual(self.transport.name, "Blue Dart Express")
        self.assertFalse(self.transport.is_active)

    def test_delete_unreferenced_transport_hard_deletes(self):
        response = self.client.delete(f"/api/transports/{self.transport.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Transport.objects.filter(pk=self.transport.id).exists())

    def test_delete_referenced_transport_deactivates(self):
        self.client.post("/api/dispatches/", self._dispatch_payload(), format="json")

        response = self.client.delete(f"/api/transports/{self.transport.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.transport.refresh_from_db()
        self.assertFalse(self.transport.is_active)

    # ── Dispatch creation ───────────────────────────────────────────

    def test_dispatch_snapshots_transport_and_uses_server_date(self):
        response = self.client.post(
            "/api/dispatches/", self._dispatch_payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dispatch = Dispatch.objects.get(pk=response.data["id"])
        self.assertEqual(dispatch.transport, self.transport)
        self.assertEqual(dispatch.transport_name, "Blue Dart")
        self.assertEqual(dispatch.tracking_url, "https://track.bluedart.com/awb")
        self.assertEqual(dispatch.dispatch_date, timezone.localdate())
        self.assertEqual(str(response.data["transport"]), str(self.transport.id))

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.DISPATCHED)
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_quantity, 8)
        self.assertEqual(self.variant.reserved_qty, 0)

    def test_dispatch_ignores_removed_client_fields(self):
        response = self.client.post(
            "/api/dispatches/",
            self._dispatch_payload(
                vehicle_number="KA01AB1234",
                driver_contact="9876543210",
                dispatch_date="2020-01-01",
                expected_delivery="2020-01-05",
                tracking_url="https://evil.example.com/track",
            ),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dispatch = Dispatch.objects.get(pk=response.data["id"])
        self.assertEqual(dispatch.vehicle_number, "")
        self.assertEqual(dispatch.driver_contact, "")
        self.assertEqual(dispatch.dispatch_date, timezone.localdate())
        self.assertIsNone(dispatch.expected_delivery)
        self.assertEqual(dispatch.tracking_url, "https://track.bluedart.com/awb")

    def test_dispatch_rejects_inactive_transport(self):
        self.transport.is_active = False
        self.transport.save(update_fields=["is_active"])

        response = self.client.post(
            "/api/dispatches/", self._dispatch_payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_dispatch_rejects_transport_from_another_company(self):
        other_transport = Transport.objects.create(
            company=self.other_company, name="Other Transport"
        )

        response = self.client.post(
            "/api/dispatches/",
            self._dispatch_payload(transport_id=str(other_transport.id)),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_dispatch_accepts_legacy_transport_name(self):
        payload = self._dispatch_payload()
        payload.pop("transport_id")
        payload["transport_name"] = " blue dart "

        response = self.client.post("/api/dispatches/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        dispatch = Dispatch.objects.get(pk=response.data["id"])
        self.assertEqual(dispatch.transport, self.transport)
        self.assertEqual(dispatch.transport_name, "Blue Dart")
        self.assertEqual(dispatch.tracking_url, "https://track.bluedart.com/awb")

    def test_dispatch_requires_a_transport(self):
        payload = self._dispatch_payload()
        payload.pop("transport_id")

        response = self.client.post("/api/dispatches/", payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_dispatch_requires_packed_order(self):
        self.order.status = OrderStatus.CONFIRMED
        self.order.save(update_fields=["status"])

        response = self.client.post(
            "/api/dispatches/", self._dispatch_payload(), format="json"
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
