import uuid
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.urls import resolve

from apps.orders.serializers import OrderItemSerializer


class PackingGroupContractTests(SimpleTestCase):
    def test_order_item_exposes_stable_variant_identity_and_original_range(self):
        product_id = uuid.uuid4()
        color_id = uuid.uuid4()
        group_id = uuid.uuid4()
        item = SimpleNamespace(
            variant_size=SimpleNamespace(
                color_variant=SimpleNamespace(product_id=product_id),
                color_variant_id=color_id,
            ),
            group_id=group_id,
            size_range="20-36",
        )
        serializer = OrderItemSerializer()
        for field, expected in (
            ("product_id", product_id),
            ("color_variant_id", color_id),
            ("group_id", group_id),
            ("size_range", "20-36"),
        ):
            self.assertEqual(serializer.fields[field].get_attribute(item), expected)

    def test_packing_route_resolves_to_the_order_view(self):
        route = resolve(f"/api/orders/{uuid.uuid4()}/pack-items/")
        self.assertEqual(route.url_name, "order-pack-items")
