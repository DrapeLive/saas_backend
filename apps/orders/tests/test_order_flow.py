from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils.timezone import now

from apps.accounts.models import RoleType, User
from apps.agents.models import AgentCompanyMembership, AgentProfile
from apps.companies.models import Company, CompanySettings
from apps.customers.models import CustomerProfile
from apps.orders import order_flow
from apps.orders.exceptions import OrderFlowError
from apps.orders.models import Order, OrderStatus
from apps.products.models import (
    Category,
    ColorVariant,
    Product,
    SizeChart,
    StockMovement,
    VariantSize,
)


class OrderFixtureMixin:
    def setUp(self):
        self.company = Company.objects.create(
            name="Acme Apparel",
            slug="acme-apparel",
            contact_email="acme@example.com",
            contact_phone="9999999999",
            state="Maharashtra",
        )
        CompanySettings.objects.create(
            company=self.company,
            order_approval_required=False,
            order_auto_confirm=False,
            credit_block_on_exceed=False,
        )
        self.agent_user = User.objects.create_user(
            email="agent@example.com",
            password="secret",
            full_name="Agent One",
            role=RoleType.AGENT,
        )
        self.agent = AgentProfile.objects.create(user=self.agent_user)
        AgentCompanyMembership.objects.create(
            agent=self.agent,
            company=self.company,
            status=AgentCompanyMembership.MembershipStatus.ACTIVE,
        )
        self.customer = CustomerProfile.objects.create(
            company=self.company,
            trade_name="Corner Shop",
            phone="8888888888",
            billing_state="Maharashtra",
        )
        self.category = Category.objects.create(
            company=self.company, name="Mens", hsn_code="6109"
        )
        self.chart = SizeChart.objects.create(
            company=self.company,
            name="Mens Shirt",
            sizes=[{"order_creation": {"20-24": ["20", "22", "24"]}}],
        )
        self.product = Product.objects.create(
            company=self.company,
            category=self.category,
            name="Cotton Shirt",
            wholesale_price=Decimal("100.00"),
            size_chart=self.chart,
        )
        self.color = ColorVariant.objects.create(
            product=self.product, color_name="Blue"
        )
        self.sizes = {
            size: VariantSize.objects.create(
                color_variant=self.color,
                size=size,
                sku=f"SKU-{size}",
                stock_quantity=10,
            )
            for size in ("20", "22", "24")
        }

    def create_draft(self):
        return order_flow.create_draft_order(
            self.company,
            self.agent,
            self.agent_user,
            {"customer": self.customer.id},
        )

    def add_range(self, order, quantity=1, **overrides):
        payload = {
            "color_variant": self.color.id,
            "size_range": "20-24",
            "quantity": quantity,
        }
        payload.update(overrides)
        return order_flow.add_item_to_draft(order, self.agent_user, payload)

    def assert_reserved(self, expected):
        for size in ("20", "22", "24"):
            self.sizes[size].refresh_from_db()
            self.assertEqual(self.sizes[size].reserved_qty, expected, size)
            self.assertEqual(
                self.sizes[size].available_qty,
                self.sizes[size].stock_quantity - expected,
                size,
            )


class OrderFlowTestBase(OrderFixtureMixin, TestCase):
    pass


class DraftLifecycleTests(OrderFlowTestBase):
    def test_create_draft_is_empty_and_expires_quickly(self):
        order = self.create_draft()

        self.assertEqual(order.status, OrderStatus.DRAFT)
        self.assertTrue(order.order_number.startswith(f"ORD-{now().year}-"))
        self.assertEqual(order.items.count(), 0)
        self.assertIsNotNone(order.draft_expires_at)
        self.assertLessEqual(
            order.draft_expires_at, now() + timedelta(seconds=121)
        )

    def test_order_numbers_are_not_reused_after_draft_deletion(self):
        first = self.create_draft()
        second = self.create_draft()
        self.assertNotEqual(first.order_number, second.order_number)

        order_flow.discard_draft(first, self.agent_user)
        third = self.create_draft()
        self.assertGreater(
            int(third.order_number.rsplit("-", 1)[1]),
            int(second.order_number.rsplit("-", 1)[1]),
        )

    def test_sequence_continues_after_existing_order_numbers(self):
        existing = Order.objects.create(
            company=self.company,
            customer=self.customer,
            order_number=f"ORD-{now().year}-00007",
            status=OrderStatus.SUBMITTED,
        )

        draft = self.create_draft()

        self.assertGreater(
            int(draft.order_number.rsplit("-", 1)[1]),
            int(existing.order_number.rsplit("-", 1)[1]),
        )

    def test_discard_releases_stock_and_deletes_draft(self):
        order = self.create_draft()
        self.add_range(order, quantity=2)
        order_id = order.id

        order_flow.discard_draft(order, self.agent_user)

        self.assertFalse(Order.objects.filter(pk=order_id).exists())
        self.assert_reserved(0)

    def test_expiry_only_deletes_expired_drafts(self):
        expired = self.create_draft()
        self.add_range(expired, quantity=2)
        active = self.create_draft()
        self.add_range(active, quantity=1)

        Order.objects.filter(pk=expired.pk).update(
            draft_expires_at=now() - timedelta(seconds=1)
        )
        Order.objects.filter(pk=active.pk).update(
            draft_expires_at=now() + timedelta(minutes=10)
        )

        expired_rows = order_flow.expire_draft_orders(company=self.company)

        self.assertEqual(len(expired_rows), 1)
        self.assertFalse(Order.objects.filter(pk=expired.pk).exists())
        self.assertTrue(Order.objects.filter(pk=active.pk).exists())
        for size in ("20", "22", "24"):
            self.sizes[size].refresh_from_db()
            self.assertEqual(self.sizes[size].reserved_qty, 1, size)


class AddItemTests(OrderFlowTestBase):
    def test_size_range_quantity_applies_per_size(self):
        order = self.create_draft()

        order, group_id, stock_updates, created = self.add_range(
            order, quantity=3
        )

        self.assertTrue(created)
        self.assertEqual(len(stock_updates), 3)
        items = list(order.items.order_by("size"))
        self.assertEqual(len(items), 3)
        self.assertEqual([item.size for item in items], ["20", "22", "24"])
        self.assertEqual([item.quantity for item in items], [3, 3, 3])
        self.assertEqual({item.group_id for item in items}, {group_id})
        self.assertEqual({item.size_range for item in items}, {"20-24"})
        self.assert_reserved(3)
        self.assertTrue(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.RESERVE,
                reference_id=order.id,
            ).exists()
        )

    def test_single_variant_size_does_not_require_range(self):
        order = self.create_draft()

        order, group_id, _, created = order_flow.add_item_to_draft(
            order,
            self.agent_user,
            {"variant_size": self.sizes["22"].id, "quantity": 2},
        )

        self.assertTrue(created)
        item = order.items.get(group_id=group_id)
        self.assertEqual(item.size, "22")
        self.assertEqual(item.size_range, "")
        self.sizes["22"].refresh_from_db()
        self.assertEqual(self.sizes["22"].reserved_qty, 2)

    def test_insufficient_stock_rolls_back_the_whole_range(self):
        self.sizes["22"].stock_quantity = 2
        self.sizes["22"].save(update_fields=["stock_quantity"])
        order = self.create_draft()

        with self.assertRaises(OrderFlowError) as ctx:
            self.add_range(order, quantity=3)

        self.assertEqual(ctx.exception.code, "INSUFFICIENT_STOCK")
        self.assertEqual(order.items.count(), 0)
        self.assert_reserved(0)

    def test_cumulative_reservations_across_orders_are_enforced(self):
        first = self.create_draft()
        self.add_range(first, quantity=6)
        self.assert_reserved(6)

        second = self.create_draft()
        with self.assertRaises(OrderFlowError) as ctx:
            self.add_range(second, quantity=5)
        self.assertEqual(ctx.exception.code, "INSUFFICIENT_STOCK")

        self.add_range(second, quantity=4)
        self.assert_reserved(10)

    def test_client_ref_is_idempotent(self):
        order = self.create_draft()

        self.add_range(order, quantity=2, client_ref="scan-1")
        order, _, _, created = self.add_range(
            order, quantity=2, client_ref="scan-1"
        )

        self.assertFalse(created)
        self.assertEqual(order.items.count(), 3)
        self.assert_reserved(2)

    def test_invalid_size_range_is_rejected(self):
        order = self.create_draft()

        with self.assertRaises(OrderFlowError) as ctx:
            self.add_range(order, size_range="30-34")

        self.assertEqual(ctx.exception.code, "INVALID_SIZE_RANGE")

    def test_malformed_identifiers_return_business_errors(self):
        order = self.create_draft()

        with self.assertRaises(OrderFlowError) as ctx:
            self.add_range(order, color_variant="not-a-uuid")
        self.assertEqual(ctx.exception.code, "VARIANT_NOT_FOUND")

        with self.assertRaises(OrderFlowError) as ctx:
            order_flow.create_draft_order(
                self.company,
                self.agent,
                self.agent_user,
                {"customer": "not-a-uuid"},
            )
        self.assertEqual(ctx.exception.code, "CUSTOMER_NOT_FOUND")


class RemoveAndUpdateTests(OrderFlowTestBase):
    def test_remove_group_releases_every_size(self):
        order = self.create_draft()
        order, group_id, _, _ = self.add_range(order, quantity=2)
        item = order.items.filter(group_id=group_id).first()

        order, stock_updates = order_flow.remove_item_from_draft(
            order, self.agent_user, item.id
        )

        self.assertEqual(len(stock_updates), 3)
        self.assertEqual(order.items.count(), 0)
        self.assert_reserved(0)
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.RELEASE,
                reference_id=order.id,
            ).count(),
            3,
        )

    def test_update_group_quantity_reserves_and_releases(self):
        order = self.create_draft()
        order, group_id, _, _ = self.add_range(order, quantity=1)
        item = order.items.filter(group_id=group_id).first()

        order, _ = order_flow.update_item_quantity(
            order, self.agent_user, item.id, 4
        )
        self.assert_reserved(4)
        self.assertEqual(
            sorted(order.items.values_list("quantity", flat=True)), [4, 4, 4]
        )

        order, _ = order_flow.update_item_quantity(
            order, self.agent_user, item.id, 2
        )
        self.assert_reserved(2)

    def test_update_above_available_stock_is_rejected_without_changes(self):
        order = self.create_draft()
        order, group_id, _, _ = self.add_range(order, quantity=2)
        item = order.items.filter(group_id=group_id).first()

        with self.assertRaises(OrderFlowError) as ctx:
            order_flow.update_item_quantity(order, self.agent_user, item.id, 11)

        self.assertEqual(ctx.exception.code, "INSUFFICIENT_STOCK")
        self.assert_reserved(2)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 2)

    def test_non_draft_cannot_be_modified(self):
        order = self.create_draft()
        self.add_range(order, quantity=1)
        order_flow.submit_draft(order, self.agent_user, {})

        with self.assertRaises(OrderFlowError) as ctx:
            self.add_range(order, quantity=1)
        self.assertEqual(ctx.exception.code, "ORDER_NOT_DRAFT")


class SubmitTests(OrderFlowTestBase):
    def test_submit_converts_draft_and_keeps_reservations(self):
        order = self.create_draft()
        self.add_range(order, quantity=2)

        order = order_flow.submit_draft(order, self.agent_user, {})

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.SUBMITTED)
        self.assertIsNotNone(order.submitted_at)
        self.assertIsNone(order.draft_expires_at)
        self.assertEqual(order.items.count(), 3)
        self.assert_reserved(2)
        self.assertTrue(
            order.invoices.filter(invoice_type="purchase_order").exists()
        )

    def test_submit_rejects_empty_draft(self):
        order = self.create_draft()

        with self.assertRaises(OrderFlowError) as ctx:
            order_flow.submit_draft(order, self.agent_user, {})

        self.assertEqual(ctx.exception.code, "EMPTY_ORDER")

    def test_submit_applies_totals_and_gst(self):
        order = self.create_draft()
        self.add_range(order, quantity=1)

        order = order_flow.submit_draft(order, self.agent_user, {})

        order.refresh_from_db()
        self.assertEqual(order.subtotal, Decimal("300.00"))
        self.assertEqual(order.cgst_amount, Decimal("7.50"))
        self.assertEqual(order.sgst_amount, Decimal("7.50"))
        self.assertEqual(order.total_amount, Decimal("315.00"))
        self.assertFalse(order.is_interstate)
