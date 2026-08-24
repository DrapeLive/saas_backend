from django.db.models import F
from django.test import TestCase

from apps.orders.models import OrderStatus, PackingStatus
from apps.orders.tests.base import PackingTestBase


class OrderItemPackingStatusTests(TestCase, PackingTestBase):
    @classmethod
    def setUpTestData(cls):
        cls.company = cls.create_company()
        cls.customer = cls.create_customer(cls.company)
        cls.variant_a = cls.create_variant(cls.company, sku="SHIRT-BLU-M", stock=100)
        cls.variant_b = cls.create_variant(cls.company, sku="SHIRT-RED-L", stock=100)

    def test_new_item_is_unpacked(self):
        order = self.create_order(self.company, self.customer, [(self.variant_a, 10)])
        item = order.items.get()
        self.assertEqual(item.packed_quantity, 0)
        self.assertEqual(item.packing_status, PackingStatus.UNPACKED)
        self.assertEqual(item.pending_qty, 10)

    def test_partial_pack_derives_partially_packed(self):
        order = self.create_order(self.company, self.customer, [(self.variant_a, 10)])
        item = order.items.get()
        item.packed_quantity = 4
        item.save()
        self.assertEqual(item.packing_status, PackingStatus.PARTIALLY_PACKED)
        self.assertEqual(item.pending_qty, 6)

    def test_full_pack_derives_packed(self):
        order = self.create_order(self.company, self.customer, [(self.variant_a, 10)])
        item = order.items.get()
        item.packed_quantity = 10
        item.save()
        self.assertEqual(item.packing_status, PackingStatus.PACKED)
        self.assertEqual(item.pending_qty, 0)

    def test_zero_ordered_item_counts_as_unpacked(self):
        """Edge case: a zero-quantity line can never be partially packed."""
        order = self.create_order(self.company, self.customer, [(self.variant_a, 0)])
        item = order.items.get()
        self.assertEqual(item.packing_status, PackingStatus.UNPACKED)


class OrderPackingStatusTests(TestCase, PackingTestBase):
    @classmethod
    def setUpTestData(cls):
        cls.company = cls.create_company(slug="packing-order-tests")
        cls.customer = cls.create_customer(cls.company)
        cls.variant_a = cls.create_variant(cls.company, sku="KURTA-WHT-S", stock=200)
        cls.variant_b = cls.create_variant(cls.company, sku="KURTA-WHT-M", stock=200)

    def test_order_with_no_items_is_unpacked(self):
        order = self.create_order(self.company, self.customer, [])
        self.assertEqual(order.packing_status, PackingStatus.UNPACKED)

    def test_all_items_unpacked(self):
        order = self.create_order(
            self.company,
            self.customer,
            [(self.variant_a, 5), (self.variant_b, 7)],
        )
        self.assertEqual(order.packing_status, PackingStatus.UNPACKED)

    def test_mixed_items_are_partially_packed(self):
        order = self.create_order(
            self.company,
            self.customer,
            [(self.variant_a, 5), (self.variant_b, 7)],
        )
        order.items.filter(variant_size=self.variant_a).update(packed_quantity=5)
        self.assertEqual(order.packing_status, PackingStatus.PARTIALLY_PACKED)

    def test_all_items_fully_packed(self):
        order = self.create_order(
            self.company,
            self.customer,
            [(self.variant_a, 5), (self.variant_b, 7)],
        )
        order.items.update(packed_quantity=F("quantity"))
        self.assertEqual(order.packing_status, PackingStatus.PACKED)

    def test_single_shortfall_keeps_order_partially_packed(self):
        order = self.create_order(
            self.company,
            self.customer,
            [(self.variant_a, 5), (self.variant_b, 7)],
        )
        # A fully packed, B short by one
        order.items.filter(variant_size=self.variant_a).update(packed_quantity=5)
        order.items.filter(variant_size=self.variant_b).update(packed_quantity=6)
        self.assertEqual(order.packing_status, PackingStatus.PARTIALLY_PACKED)

    def test_workflow_status_independent_of_packing(self):
        """Packing derivation must not touch the workflow status field."""
        order = self.create_order(
            self.company,
            self.customer,
            [(self.variant_a, 5)],
            status=OrderStatus.CONFIRMED,
        )
        order.items.update(packed_quantity=F("quantity"))
        order.refresh_from_db()
        self.assertEqual(order.packing_status, PackingStatus.PACKED)
        self.assertEqual(order.status, OrderStatus.CONFIRMED)
