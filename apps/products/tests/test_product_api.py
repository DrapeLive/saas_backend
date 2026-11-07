import base64
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import RoleType, User
from apps.companies.models import Company, CompanySettings
from apps.products.models import Category, ColorVariant, Product, SizeChart


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _png(name="variant.png"):
    return SimpleUploadedFile(name, io.BytesIO(PNG_1X1).read(), "image/png")


class ProductApiTests(TestCase):
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
        self.user = User.objects.create_user(
            email="admin@example.com",
            password="secret",
            full_name="Admin One",
            role=RoleType.ADMIN,
            company=self.company,
        )
        self.category = Category.objects.create(
            company=self.company, name="Mens", hsn_code="6109"
        )
        self.chart = SizeChart.objects.create(
            company=self.company,
            name="Mens Shirt",
            sizes=["S", "M", "L"],
        )
        token = AccessToken.for_user(self.user)
        self.client = APIClient()
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_COMPANY_ID=str(self.company.id),
        )

    def _json_payload(self):
        return {
            "category": str(self.category.id),
            "name": "Classic Polo",
            "description": "Soft cotton",
            "size_chart": str(self.chart.id),
            "mrp": "1199.00",
            "wholesale_price": "780.50",
            "status": "active",
            "color_variants": [
                {
                    "color_name": "Navy",
                    "is_primary": True,
                    "sizes": [
                        {"size": "M", "stock_quantity": 12, "reorder_level": 4},
                        {"size": "L", "stock_quantity": 8, "reorder_level": 2},
                    ],
                }
            ],
        }

    def test_create_product_with_nested_json(self):
        response = self.client.post(
            "/api/products/", self._json_payload(), format="json"
        )

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["mrp"], "1199.00")
        self.assertEqual(response.data["wholesale_price"], "780.50")
        self.assertEqual(response.data["total_stock"], 20)
        self.assertEqual(response.data["available_stock"], 20)

        variants = response.data["color_variants"]
        self.assertEqual(len(variants), 1)
        self.assertEqual(variants[0]["color_name"], "Navy")
        sizes = {size["size"]: size for size in variants[0]["sizes"]}
        self.assertEqual(set(sizes), {"M", "L"})
        self.assertEqual(sizes["M"]["stock_quantity"], 12)
        self.assertEqual(sizes["M"]["available_qty"], 12)
        self.assertTrue(sizes["M"]["sku"])
        self.assertTrue(variants[0]["qr_code"])

    def test_create_product_with_nested_multipart_image(self):
        image = _png()
        data = {
            "category": str(self.category.id),
            "name": "Multipart Polo",
            "description": "Uploaded in one request",
            "size_chart": str(self.chart.id),
            "mrp": "999.00",
            "wholesale_price": "600.00",
            "status": "active",
            "color_variants[0][color_name]": "Olive",
            "color_variants[0][is_primary]": "true",
            "color_variants[0][sizes][0][size]": "S",
            "color_variants[0][sizes][0][stock_quantity]": "5",
            "color_variants[0][sizes][0][reorder_level]": "1",
            "color_variants[0][image]": image,
        }

        response = self.client.post("/api/products/", data, format="multipart")

        self.assertEqual(response.status_code, 201, response.data)
        product = Product.objects.get(pk=response.data["id"])
        variant = product.color_variants.get()
        self.assertEqual(variant.color_name, "Olive")
        self.assertTrue(variant.is_primary)
        self.assertTrue(variant.image)
        self.assertEqual(variant.sizes.get().size, "S")
        self.assertEqual(product.total_stock, 5)

    def test_patch_product_clears_nullable_fields(self):
        product = Product.objects.create(
            company=self.company,
            category=self.category,
            name="Editable",
            size_chart=self.chart,
            mrp="500.00",
            wholesale_price="400.00",
        )

        response = self.client.patch(
            f"/api/products/{product.id}/",
            {"mrp": None, "size_chart": None},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        product.refresh_from_db()
        self.assertIsNone(product.mrp)
        self.assertIsNone(product.size_chart)

    def test_patch_variant_removes_image(self):
        product = Product.objects.create(
            company=self.company,
            category=self.category,
            name="With Image",
            wholesale_price="100.00",
        )
        variant = ColorVariant.objects.create(
            product=product,
            color_name="Navy",
            image=_png("navy.png"),
        )

        response = self.client.patch(
            f"/api/products/{product.id}/variants/{variant.id}/",
            {"image": None},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        variant.refresh_from_db()
        self.assertFalse(variant.image)

    def test_agent_can_read_but_not_write(self):
        agent = User.objects.create_user(
            email="agent@example.com",
            password="secret",
            full_name="Agent One",
            role=RoleType.AGENT,
            company=self.company,
        )
        token = AccessToken.for_user(agent)
        agent_client = APIClient()
        agent_client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_COMPANY_ID=str(self.company.id),
        )

        listing = agent_client.get("/api/products/")
        self.assertEqual(listing.status_code, 200, listing.data)

        created = agent_client.post(
            "/api/products/", self._json_payload(), format="json"
        )
        self.assertEqual(created.status_code, 403, created.data)
