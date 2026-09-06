from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.companies.models import Company
from apps.products.models import (
    Category,
    ColorVariant,
    Product,
    SizeChart,
    VariantSize,
)

User = get_user_model()


def _make_token(user, company):
    token = AccessToken()
    token["user_id"] = str(user.id)
    token["role"] = user.role
    token["company_id"] = str(company.id)
    return str(token)


class ProductListTest(TestCase):
    """Tests for GET /api/products/ — Product-level listing with nested variants.""" 

    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(
            name="Test Corp",
            slug="test-corp",
            contact_email="test@corp.com",
            contact_phone="9999999999",
            status="active",
        )
        self.user = User.objects.create_user(
            email="admin@test.com",
            password="testpass123",
            full_name="Test Admin",
            role="admin",
            company=self.company,
        )
        self.token = _make_token(self.user, self.company)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")

        self.url = reverse("products:product-list-create")

        # Create test data
        self.category = Category.objects.create(
            company=self.company,
            name="Men",
        )
        self.size_chart = SizeChart.objects.create(
            company=self.company,
            name="Standard",
            sizes=["S", "M", "L", "XL"],
        )
        self.product = Product.objects.create(
            company=self.company,
            category=self.category,
            name="Classic T-Shirt",
            description="Comfortable cotton tee.",
            sku_prefix="TSHIRT",
            hsn_code="61091000",
            gst_rate=Decimal("5.00"),
            size_chart=self.size_chart,
            mrp=Decimal("999.00"),
            wholesale_price=Decimal("450.00"),
            minimum_order_qty=2,
            order_in_multiples=2,
            total_stock=105,
            status="active",
        )
        self.variant = ColorVariant.objects.create(
            product=self.product,
            color_name="Black",
            color_hex="#000000",
            sku="TSHIRT-BLACK",
        )
        self.variant_size_m = VariantSize.objects.create(
            color_variant=self.variant,
            size="M",
            sku="TSHIRT-BLACK-M",
            stock_quantity=100,
            reserved_qty=20,
            reorder_level=10,
        )
        self.variant_size_l = VariantSize.objects.create(
            color_variant=self.variant,
            size="L",
            sku="TSHIRT-BLACK-L",
            stock_quantity=5,
            reserved_qty=2,
            reorder_level=10,
        )
        # Out-of-stock variant
        self.variant_size_xl = VariantSize.objects.create(
            color_variant=self.variant,
            size="XL",
            sku="TSHIRT-BLACK-XL",
            stock_quantity=0,
            reserved_qty=0,
            reorder_level=10,
        )
        # Second product with no variants (e.g. draft/blank product)
        self.product_two = Product.objects.create(
            company=self.company,
            category=self.category,
            name="Formal Shirt",
            sku_prefix="FORMAL",
            wholesale_price=Decimal("700.00"),
            mrp=Decimal("1499.00"),
            status="active",
        )

    def test_default_list_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_response_has_pagination_fields(self):
        resp = self.client.get(self.url)
        data = resp.data
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("results", data)

    def test_count_reflects_products(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.data["count"], 2)

    def test_result_structure(self):
        resp = self.client.get(self.url)
        product = next(
            r for r in resp.data["results"] if r["name"] == "Classic T-Shirt"
        )
        self.assertEqual(product["id"], str(self.product.id))
        self.assertEqual(product["category"], self.category.id)
        self.assertEqual(product["category_name"], "Men")
        self.assertEqual(product["name"], "Classic T-Shirt")
        self.assertEqual(product["description"], "Comfortable cotton tee.")
        self.assertEqual(product["sku_prefix"], "TSHIRT")
        self.assertEqual(product["hsn_code"], "61091000")
        self.assertEqual(product["gst_rate"], "5.00")
        self.assertEqual(product["size_chart"], self.size_chart.id)
        self.assertEqual(product["size_chart_name"], "Standard")
        self.assertEqual(product["mrp"], "999.00")
        self.assertEqual(product["wholesale_price"], "450.00")
        self.assertEqual(product["minimum_order_qty"], 2)
        self.assertEqual(product["order_in_multiples"], 2)
        self.assertEqual(product["total_stock"], 105)
        self.assertEqual(product["status"], "active")
        self.assertIn("color_variants", product)
        self.assertIn("created_at", product)
        self.assertIn("updated_at", product)

    def test_color_variants_nested_with_sizes(self):
        resp = self.client.get(self.url)
        product = next(
            r for r in resp.data["results"] if r["name"] == "Classic T-Shirt"
        )
        variant = product["color_variants"][0]
        self.assertEqual(variant["color_name"], "Black")
        self.assertEqual(variant["color_hex"], "#000000")
        self.assertEqual(variant["sku"], "TSHIRT-BLACK")
        self.assertTrue(variant["is_active"])
        self.assertIn("qr_code", variant)
        self.assertIn("created_at", variant)
        self.assertIn("updated_at", variant)

        sizes = variant["sizes"]
        self.assertEqual(len(sizes), 3)
        m = next(s for s in sizes if s["size"] == "M")
        self.assertEqual(m["sku"], "TSHIRT-BLACK-M")
        self.assertEqual(m["stock_quantity"], 100)
        self.assertEqual(m["reserved_qty"], 20)
        self.assertEqual(m["available_qty"], 80)
        self.assertEqual(m["reorder_level"], 10)
        self.assertFalse(m["is_low_stock"])
        self.assertTrue(m["is_active"])

    def test_low_stock_state(self):
        resp = self.client.get(self.url)
        product = next(
            r for r in resp.data["results"] if r["name"] == "Classic T-Shirt"
        )
        l = next(s for s in product["color_variants"][0]["sizes"] if s["size"] == "L")
        # available=3, reorder=10 → low stock
        self.assertTrue(l["is_low_stock"])

    def test_out_of_stock_state(self):
        resp = self.client.get(self.url)
        product = next(
            r for r in resp.data["results"] if r["name"] == "Classic T-Shirt"
        )
        xl = next(s for s in product["color_variants"][0]["sizes"] if s["size"] == "XL")
        self.assertTrue(xl["is_low_stock"])

    def test_search_by_product_name(self):
        resp = self.client.get(self.url, {"search": "Classic"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["name"], "Classic T-Shirt")

    def test_search_by_sku_prefix(self):
        resp = self.client.get(self.url, {"search": "TSHIRT"})
        self.assertEqual(resp.data["count"], 1)

    def test_search_by_color_name(self):
        resp = self.client.get(self.url, {"search": "Black"})
        self.assertEqual(resp.data["count"], 1)

    def test_search_by_category_name(self):
        resp = self.client.get(self.url, {"search": "Men"})
        self.assertEqual(resp.data["count"], 2)

    def test_filter_by_category(self):
        resp = self.client.get(self.url, {"category": str(self.category.id)})
        self.assertEqual(resp.data["count"], 2)

    def test_filter_by_category_no_match(self):
        resp = self.client.get(
            self.url, {"category": "00000000-0000-0000-0000-000000000000"}
        )
        self.assertEqual(resp.data["count"], 0)

    def test_filter_by_status(self):
        self.product.status = "inactive"
        self.product.save(update_fields=["status"])
        resp = self.client.get(self.url, {"status": "inactive"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["name"], "Classic T-Shirt")

    def test_filter_by_size(self):
        resp = self.client.get(self.url, {"size": "M"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["name"], "Classic T-Shirt")

    def test_filter_by_size_no_match(self):
        resp = self.client.get(self.url, {"size": "XXL"})
        self.assertEqual(resp.data["count"], 0)

    def test_filter_low_stock(self):
        resp = self.client.get(self.url, {"low_stock": "true"})
        # L (available=3 <= reorder=10) and XL (available=0 <= reorder=10)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["name"], "Classic T-Shirt")

    def test_filter_out_of_stock(self):
        resp = self.client.get(self.url, {"out_of_stock": "true"})
        self.assertEqual(resp.data["count"], 1)

    def test_ordering_by_name(self):
        resp = self.client.get(self.url, {"ordering": "name"})
        names = [r["name"] for r in resp.data["results"]]
        self.assertEqual(names, sorted(names))

    def test_ordering_by_total_stock_desc(self):
        resp = self.client.get(self.url, {"ordering": "-total_stock"})
        self.assertEqual(resp.data["results"][0]["name"], "Classic T-Shirt")

    def test_ordering_by_mrp(self):
        resp = self.client.get(self.url, {"ordering": "mrp"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_pagination_page_size(self):
        resp = self.client.get(self.url, {"page_size": "1", "ordering": "name"})
        self.assertEqual(len(resp.data["results"]), 1)
        self.assertEqual(resp.data["count"], 2)
        self.assertIsNotNone(resp.data["next"])

    def test_pagination_page_2(self):
        resp = self.client.get(
            self.url, {"page_size": "1", "page": "2", "ordering": "name"}
        )
        self.assertEqual(len(resp.data["results"]), 1)

    def test_unauthenticated_returns_401(self):
        client = APIClient()
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_deleted_product_excluded(self):
        self.product.is_deleted = True
        self.product.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.data["count"], 1)


@override_settings(SPECTACULAR_SETTINGS={"PREPROCESSING_EXTENSIONS": []})
class ProductInventorySchemaTest(TestCase):
    """Verify DRF Spectacular generates a valid schema without crashing."""

    def setUp(self):
        self.url = reverse("products:product-list-create")

    def test_schema_generation_does_not_crash(self):
        from drf_spectacular.generators import SchemaGenerator

        generator = SchemaGenerator()
        schema = generator.get_schema()
        self.assertIsNotNone(schema)
        self.assertIn("paths", schema)
        self.assertIn("components", schema)

    def test_schema_has_at_least_one_path(self):
        from drf_spectacular.generators import SchemaGenerator

        generator = SchemaGenerator()
        schema = generator.get_schema()
        self.assertGreater(len(schema["paths"]), 0)

    def test_schema_paths_are_well_formed(self):
        from drf_spectacular.generators import SchemaGenerator

        generator = SchemaGenerator()
        schema = generator.get_schema()
        for path, methods in schema["paths"].items():
            self.assertTrue(path.startswith("/"), f"Path {path} must start with /")
            for method, operation in methods.items():
                self.assertIn(
                    method.lower(),
                    ["get", "post", "put", "patch", "delete", "head", "options"],
                )