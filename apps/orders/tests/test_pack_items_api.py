from decimal import Decimal

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import RoleType
from apps.orders.models import (
    OrderStatus,
    OrderStatusHistory,
    PackingStatus,
)
from apps.orders.tests.base import PackingTestBase, authenticate

PACK_ITEMS_URL = "/api/orders/{order_id}/pack-items/"


class PackItemsAPITests(APITestCase, PackingTestBase):
    @classmethod
    def setUpTestData(cls):
        cls.company = cls.create_company()
        cls.other_company = cls.create_company(slug="other-co")
        cls.admin = cls.create_user("admin@acme.com", RoleType.ADMIN, cls.company)
        cls.subadmin = cls.create_user(
            "subadmin@acme.com", RoleType.SUB_ADMIN, cls.company
        )
        cls.agent = cls.create_user("agent@acme.com", RoleType.AGENT, None)
        cls.customer = cls.create_customer(cls.company)
        cls.variant_a = cls.create_variant(cls.company, sku="POLO-BLK-M", stock=100)
        cls.variant_b = cls.create_variant(cls.company, sku="POLO-BLK-L", stock=100)

    def setUp(self):
        self.client = self.client_class()

    def _create_order(self, status=OrderStatus.PROCESSING):
        return self.create_order(
            self.company,
            self.customer,
            [(self.variant_a, 10), (self.variant_b, 20)],
            status=status,
        )

    def _payload(self, order, entries):
        return {
            "items": [
                {"item_id": str(item.id), "packed_quantity": qty}
                for item, qty in entries
            ]
        }

    # ── happy paths ────────────────────────────────────────────────

    def test_admin_packs_partial_quantity(self):
        """Core requirement: packed qty may be less than ordered qty."""
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        item_b = order.items.get(variant_size=self.variant_b)

        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 6), (item_b, 20)]),
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item_a.refresh_from_db()
        item_b.refresh_from_db()
        self.assertEqual(item_a.packed_quantity, 6)
        self.assertEqual(item_b.packed_quantity, 20)
        self.assertEqual(item_a.packing_status, PackingStatus.PARTIALLY_PACKED)
        self.assertEqual(item_b.packing_status, PackingStatus.PACKED)

        body = response.json()
        self.assertEqual(body["packing_status"], PackingStatus.PARTIALLY_PACKED)
        items_by_sku = {i["sku"]: i for i in body["items"]}
        self.assertEqual(items_by_sku[item_a.sku]["pending_qty"], 4)
        self.assertEqual(items_by_sku[item_a.sku]["packing_status"], "partially_packed")

    def test_full_pack_of_all_items(self):
        order = self._create_order()
        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(
                order,
                [(item, item.quantity) for item in order.items.all()],
            ),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["packing_status"], PackingStatus.PACKED)

    def test_workflow_status_unchanged_after_packing(self):
        order = self._create_order(status=OrderStatus.CONFIRMED)
        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(
                order,
                [(item, item.quantity) for item in order.items.all()],
            ),
        )
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
        self.assertEqual(response.json()["status"], OrderStatus.CONFIRMED)

    def test_subadmin_can_pack(self):
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        authenticate(self.client, self.subadmin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 10)]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_correction_reduce_packed_quantity(self):
        """Packed quantities can be corrected downwards before dispatch."""
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        item_a.packed_quantity = 8
        item_a.save(update_fields=["packed_quantity"])

        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 3)]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item_a.refresh_from_db()
        self.assertEqual(item_a.packed_quantity, 3)

    def test_packing_zero_allowed(self):
        """Resetting an item's packed quantity back to zero is valid."""
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        item_a.packed_quantity = 8
        item_a.save(update_fields=["packed_quantity"])

        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 0)]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item_a.refresh_from_db()
        self.assertEqual(item_a.packed_quantity, 0)
        self.assertEqual(item_a.packing_status, PackingStatus.UNPACKED)

    def test_partial_update_leaves_other_items_untouched(self):
        """Only the submitted items are modified (per-item granularity)."""
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        item_b = order.items.get(variant_size=self.variant_b)
        item_b.packed_quantity = 15
        item_b.save(update_fields=["packed_quantity"])

        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 2)]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        item_b.refresh_from_db()
        self.assertEqual(item_b.packed_quantity, 15)

    # ── validation failures ────────────────────────────────────────

    def test_over_packing_rejected(self):
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 11)]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        item_a.refresh_from_db()
        self.assertEqual(item_a.packed_quantity, 0)
        self.assertIn("cannot exceed", str(response.json()))

    def test_negative_packed_quantity_rejected(self):
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            {"items": [{"item_id": str(item_a.id), "packed_quantity": -1}]},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_item_id_rejected(self):
        order = self._create_order()
        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            {
                "items": [
                    {
                        "item_id": "00000000-0000-0000-0000-000000000000",
                        "packed_quantity": 1,
                    }
                ]
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not found on this order", str(response.json()))

    def test_empty_items_list_rejected(self):
        order = self._create_order()
        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id), {"items": []}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_item_entries_rejected(self):
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 1), (item_a, 2)]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_item_from_another_order_rejected(self):
        order = self._create_order()
        other_order = self._create_order()
        foreign_item = other_order.items.first()

        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(foreign_item, 1)]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("not found on this order", str(response.json()))

    def test_packing_rejected_for_terminal_statuses(self):
        for bad_status in (
            OrderStatus.DISPATCHED,
            OrderStatus.DELIVERED,
            OrderStatus.CANCELLED,
        ):
            with self.subTest(status=bad_status):
                order = self._create_order(status=bad_status)
                item_a = order.items.get(variant_size=self.variant_a)
                authenticate(self.client, self.admin, self.company)
                response = self.client.post(
                    PACK_ITEMS_URL.format(order_id=order.id),
                    self._payload(order, [(item_a, 5)]),
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── permissions / scoping ──────────────────────────────────────

    def test_agent_forbidden(self):
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        authenticate(self.client, self.agent)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 5)]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_unauthorized(self):
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 5)]),
        )
        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )

    def test_cross_company_order_not_found(self):
        """An order from another company must not be reachable."""
        other_customer = self.create_customer(self.other_company)
        other_variant = self.create_variant(self.other_company, sku="OTHER-X", stock=50)
        order = self.create_order(
            self.other_company,
            other_customer,
            [(other_variant, 5)],
        )
        item = order.items.get()

        authenticate(self.client, self.admin, self.company)
        response = self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item, 1)]),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ── audit trail ────────────────────────────────────────────────

    def test_status_history_logged_on_change(self):
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        before = OrderStatusHistory.objects.filter(order=order).count()

        authenticate(self.client, self.admin, self.company)
        self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(
                order, [(item_a, 6), (order.items.get(variant_size=self.variant_b), 20)]
            ),
        )

        entry = OrderStatusHistory.objects.filter(order=order).first()
        self.assertEqual(
            OrderStatusHistory.objects.filter(order=order).count(), before + 1
        )
        self.assertEqual(entry.from_status, PackingStatus.UNPACKED)
        self.assertEqual(entry.to_status, PackingStatus.PARTIALLY_PACKED)
        self.assertIn("Packing update", entry.notes)

    def test_no_history_entry_when_nothing_changed(self):
        order = self._create_order()
        item_a = order.items.get(variant_size=self.variant_a)
        item_a.packed_quantity = 6
        item_a.save(update_fields=["packed_quantity"])
        before = OrderStatusHistory.objects.filter(order=order).count()

        authenticate(self.client, self.admin, self.company)
        self.client.post(
            PACK_ITEMS_URL.format(order_id=order.id),
            self._payload(order, [(item_a, 6)]),
        )
        self.assertEqual(OrderStatusHistory.objects.filter(order=order).count(), before)
