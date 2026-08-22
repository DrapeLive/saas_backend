from datetime import date

from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import RoleType
from apps.orders.models import OrderStatus
from apps.orders.tests.base import PackingTestBase, authenticate
from apps.products.models import StockMovement, VariantSize

DISPATCH_URL = "/api/dispatches/"


class DispatchWithPartialPackingTests(APITestCase, PackingTestBase):
    """
    Dispatch must ship what was actually packed:
    stock -= packed_quantity, reservations fully released.
    """

    @classmethod
    def setUpTestData(cls):
        cls.company = cls.create_company(slug="dispatch-co")
        cls.admin = cls.create_user("admin@dispatchco.com", RoleType.ADMIN, cls.company)
        cls.customer = cls.create_customer(cls.company)
        cls.variant_a = cls.create_variant(cls.company, sku="DENIM-BLU-32", stock=100)
        cls.variant_b = cls.create_variant(cls.company, sku="DENIM-GRY-34", stock=100)

    def setUp(self):
        self.client = self.client_class()
        authenticate(self.client, self.admin, self.company)

    def _create_packed_order(self, qty_a=10, qty_b=20, pack_a=None, pack_b=None):
        order = self.create_order(
            self.company,
            self.customer,
            [(self.variant_a, qty_a), (self.variant_b, qty_b)],
            status=OrderStatus.PACKED,
        )
        packs = {}
        if pack_a is not None:
            order.items.filter(variant_size=self.variant_a).update(packed_quantity=pack_a)
            packs[self.variant_a.sku] = pack_a
        if pack_b is not None:
            order.items.filter(variant_size=self.variant_b).update(packed_quantity=pack_b)
            packs[self.variant_b.sku] = pack_b
        order.refresh_from_db()
        return order

    def _create_dispatch(self, order):
        return self.client.post(
            DISPATCH_URL,
            {
                "order": str(order.id),
                "lr_number": "LR-1001",
                "transport_name": "BlueDart",
                "dispatch_date": str(date.today()),
            },
        )

    def test_partial_pack_dispatch_ships_only_packed_qty(self):
        """Ordered 30, packed 25 → stock drops by 25, all 30 reservations freed."""
        order = self._create_packed_order(qty_a=10, pack_a=10, qty_b=20, pack_b=15)

        response = self._create_dispatch(order)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)

        va = VariantSize.objects.get(pk=self.variant_a.pk)
        vb = VariantSize.objects.get(pk=self.variant_b.pk)
        # Fully packed item: stock -10, reservation -10
        self.assertEqual(va.stock_quantity, 90)
        self.assertEqual(va.reserved_qty, 0)
        # Short-packed item: stock -15 (not -20), reservation fully released
        self.assertEqual(vb.stock_quantity, 85)
        self.assertEqual(vb.reserved_qty, 0)

    def test_fully_packed_order_dispatch_normal(self):
        """No shortfall behaves exactly like the legacy full-fulfilment flow."""
        order = self._create_packed_order(qty_a=10, pack_a=10, qty_b=20, pack_b=20)
        response = self._create_dispatch(order)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        va = VariantSize.objects.get(pk=self.variant_a.pk)
        vb = VariantSize.objects.get(pk=self.variant_b.pk)
        self.assertEqual((va.stock_quantity, vb.stock_quantity), (90, 80))
        self.assertEqual((va.reserved_qty, vb.reserved_qty), (0, 0))

    def test_stock_movements_record_actual_packed_qty(self):
        order = self._create_packed_order(qty_a=10, pack_a=4, qty_b=20, pack_b=0)
        response = self._create_dispatch(order)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        movements = list(
            StockMovement.objects.filter(reference_type="dispatch").order_by(
                "variant_size__sku"
            )
        )
        # Only the item with packed_quantity > 0 generates an OUT movement
        self.assertEqual(len(movements), 1)
        self.assertEqual(movements[0].quantity, -4)
        self.assertEqual(movements[0].variant_size_id, self.variant_a.id)

    def test_order_status_advanced_to_dispatched(self):
        order = self._create_packed_order(pack_a=5, pack_b=5)
        response = self._create_dispatch(order)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.DISPATCHED)
