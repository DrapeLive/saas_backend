from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import RoleType, User
from apps.companies.models import Company, CompanySettings
from apps.customers.models import CustomerProfile
from apps.orders.models import Order, OrderStatus
from apps.products.models import (
    Category,
    ColorVariant,
    Product,
    SizeChart,
    VariantSize,
)


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc3\x89\x00\x00\x00\nIDATx\x9cc\xf8\x0f"
    b"\x00\x00\x01\x01\x00\x05\xff\x03\xfe\xde\x20\xd5\x36\xdb\x00\x00\x00"
    b"\x00IEND\xaeB\x60\x82"
)


class OrderItemImageUrlTests(TestCase):
    """Tests that order items expose the color variant image URL."""

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
        self.admin = User.objects.create_user(
            email="admin@acme.test",
            password="testpass123",
            full_name="Admin",
            role=RoleType.ADMIN,
            company=self.company,
        )
        self.customer = CustomerProfile.objects.create(
            company=self.company,
            trade_name="Corner Shop",
            phone="9999999999",
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
            wholesale_price=100.00,
            size_chart=self.chart,
        )
        self.color = ColorVariant.objects.create(
            product=self.product,
            color_name="Blue",
            image=SimpleUploadedFile("blue.png", PNG_1X1, content_type="image/png"),
        )
        self.variant = VariantSize.objects.create(
            color_variant=self.color,
            size="M",
            sku="SKU-M",
            stock_quantity=10,
        )
        self.order = Order.objects.create(
            company=self.company,
            customer=self.customer,
            order_number="ORD-IMG-001",
            status=OrderStatus.PACKED,
            total_amount=200.00,
        )
        from apps.orders.models import OrderItem

        self.order_item = OrderItem.objects.create(
            order=self.order,
            variant_size=self.variant,
            product_name=self.product.name,
            color_name=self.color.color_name,
            size=self.variant.size,
            sku=self.variant.sku,
            unit_price=100.00,
            quantity=2,
            line_total=200.00,
        )
        self.client = APIClient()
        token = AccessToken.for_user(self.admin)
        token["company_id"] = str(self.company.id)
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_COMPANY_ID=str(self.company.id),
        )

    def test_order_detail_includes_image_url(self):
        response = self.client.get(f"/api/orders/{self.order.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        items = response.data["items"]
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertIn("image_url", item)
        self.assertIsNotNone(item["image_url"])
        self.assertTrue(item["image_url"].endswith("/media/variants/blue.png"))

    def test_order_detail_image_url_is_null_when_no_image(self):
        # Create another color variant without an image
        color_no_img = ColorVariant.objects.create(
            product=self.product, color_name="Red"
        )
        variant_no_img = VariantSize.objects.create(
            color_variant=color_no_img,
            size="L",
            sku="SKU-L",
            stock_quantity=5,
        )
        OrderItem.objects.create(
            order=self.order,
            variant_size=variant_no_img,
            product_name=self.product.name,
            color_name=color_no_img.color_name,
            size=variant_no_img.size,
            sku=variant_no_img.sku,
            unit_price=100.00,
            quantity=1,
            line_total=100.00,
        )
        response = self.client.get(f"/api/orders/{self.order.id}/")
        self.assertEqual(response.status_code, 200, response.data)
        items = response.data["items"]
        # Find the item without an image
        no_img_item = next(
            i for i in items if i["color_name"] == "Red"
        )
        self.assertIsNone(no_img_item["image_url"])
