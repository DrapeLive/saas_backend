from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.orders.models import OrderStatus
from apps.orders.tests.test_order_flow import OrderFixtureMixin


class OrderApiTests(OrderFixtureMixin, TestCase):
    def setUp(self):
        super().setUp()
        token = AccessToken.for_user(self.agent_user)
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_COMPANY_ID=str(self.company.id),
        )

    def _create_draft(self):
        response = self.client.post(
            "/api/orders/",
            {"customer": str(self.customer.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def _add_range(self, order_id, quantity=2):
        response = self.client.post(
            f"/api/orders/{order_id}/items/",
            {
                "color_variant": str(self.color.id),
                "size_range": "20-24",
                "quantity": quantity,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_create_add_and_submit_draft(self):
        draft = self._create_draft()
        self.assertEqual(draft["status"], OrderStatus.DRAFT)
        self.assertEqual(draft["items"], [])

        added = self._add_range(draft["id"], quantity=3)
        self.assertTrue(added["created"])
        self.assertEqual(len(added["order"]["items"]), 3)
        self.assertEqual(len(added["stock_updates"]), 3)

        response = self.client.post(
            f"/api/orders/{draft['id']}/submit/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], OrderStatus.SUBMITTED)
        self.assertIsNone(response.data["draft_expires_at"])

        drafts = self.client.get("/api/orders/drafts/")
        self.assertEqual(drafts.status_code, 200)
        self.assertEqual(drafts.data, [])

    def test_create_with_items_is_rejected(self):
        response = self.client.post(
            "/api/orders/",
            {
                "customer": str(self.customer.id),
                "items": [{"variant_size": str(self.sizes["20"].id), "quantity": 1}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_delete_draft_releases_reservations(self):
        draft = self._create_draft()
        self._add_range(draft["id"], quantity=2)

        response = self.client.delete(f"/api/orders/{draft['id']}/")
        self.assertEqual(response.status_code, 204, response.data)
        self.assert_reserved(0)

    def test_insufficient_stock_returns_409(self):
        draft = self._create_draft()
        self.sizes["22"].stock_quantity = 1
        self.sizes["22"].save(update_fields=["stock_quantity"])

        response = self.client.post(
            f"/api/orders/{draft['id']}/items/",
            {
                "color_variant": str(self.color.id),
                "size_range": "20-24",
                "quantity": 2,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 409, response.data)
        self.assertEqual(response.data["code"], "INSUFFICIENT_STOCK")
        self.assertEqual(len(response.data["fields"]["items"]), 1)

    def test_patch_metadata_and_item_quantity(self):
        draft = self._create_draft()
        added = self._add_range(draft["id"], quantity=1)
        item_id = added["order"]["items"][0]["id"]

        response = self.client.patch(
            f"/api/orders/{draft['id']}/",
            {"order_notes": "Deliver after 5pm", "discount_pct": "10.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["order_notes"], "Deliver after 5pm")
        self.assertEqual(response.data["discount_pct"], "10.00")

        response = self.client.patch(
            f"/api/orders/{draft['id']}/items/{item_id}/",
            {"quantity": 3},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            {item["quantity"] for item in response.data["order"]["items"]}, {3}
        )
        self.assert_reserved(3)

        response = self.client.delete(
            f"/api/orders/{draft['id']}/items/{item_id}/"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["order"]["items"], [])
        self.assert_reserved(0)
