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
    VariantSize,
)

User = get_user_model()


def _make_token(user, company):
    token = AccessToken()
    token["user_id"] = str(user.id)
    token["role"] = user.role
    token["company_id"] = str(company.id)
    return str(token)


class ProductInventoryListingTest(TestCase):
    """Tests for GET /api/products/ — VariantSize-level inventory listing."""

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
            slug="men",
        )
        self.product = Product.objects.create(
            company=self.company,
            category=self.category,
            name="Classic T-Shirt",
            sku_prefix="TSHIRT",
            wholesale_price=Decimal("450.00"),
            mrp=Decimal("999.00"),
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

    def test_default_list_returns_200(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_response_has_pagination_fields(self):
        resp = self.client.get(self.url)
        data = resp.data
        self.assertIn("count", data)
        self.assertIn("next", data)
        self.assertIn("previous", data)
        self.assertIn("summary", data)
        self.assertIn("filters", data)
        self.assertIn("results", data)

    def test_count_reflects_variant_size_rows(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.data["count"], 3)

    def test_result_structure(self):
        resp = self.client.get(self.url)
        row = resp.data["results"][0]
        self.assertIn("id", row)
        self.assertIn("product", row)
        self.assertIn("sku", row)
        self.assertIn("category", row)
        self.assertIn("color", row)
        self.assertIn("size", row)
        self.assertIn("price_per_unit", row)
        self.assertIn("stock", row)

        self.assertEqual(row["product"]["name"], "Classic T-Shirt")
        self.assertEqual(row["category"]["name"], "Men")
        self.assertEqual(row["color"]["name"], "Black")
        self.assertEqual(row["color"]["hex"], "#000000")

    def test_stock_fields(self):
        resp = self.client.get(self.url)
        m_row = next(r for r in resp.data["results"] if r["size"] == "M")
        stock = m_row["stock"]
        self.assertEqual(stock["stock_quantity"], 100)
        self.assertEqual(stock["reserved_quantity"], 20)
        self.assertEqual(stock["available_quantity"], 80)
        self.assertEqual(stock["reorder_level"], 10)
        self.assertFalse(stock["is_low_stock"])
        self.assertFalse(stock["is_out_of_stock"])

    def test_low_stock_variant(self):
        resp = self.client.get(self.url)
        l_row = next(r for r in resp.data["results"] if r["size"] == "L")
        # available=3, reorder=10 → low stock
        self.assertTrue(l_row["stock"]["is_low_stock"])

    def test_out_of_stock_variant(self):
        resp = self.client.get(self.url)
        xl_row = next(r for r in resp.data["results"] if r["size"] == "XL")
        self.assertTrue(xl_row["stock"]["is_out_of_stock"])
        self.assertTrue(xl_row["stock"]["is_low_stock"])

    def test_price_per_unit_uses_product_wholesale(self):
        resp = self.client.get(self.url)
        m_row = next(r for r in resp.data["results"] if r["size"] == "M")
        self.assertEqual(m_row["price_per_unit"], "450.00")

    def test_price_per_unit_uses_override_when_set(self):
        self.variant_size_m.price_override = Decimal("550.00")
        self.variant_size_m.save()
        resp = self.client.get(self.url)
        m_row = next(r for r in resp.data["results"] if r["size"] == "M")
        self.assertEqual(m_row["price_per_unit"], "550.00")

    def test_summary_stock_valuation(self):
        # M: 100 × 450 = 45000, L: 5 × 450 = 2250, XL: 0 × 450 = 0
        resp = self.client.get(self.url)
        self.assertEqual(resp.data["summary"]["stock_valuation"], "47250.00")

    def test_filters_sizes(self):
        resp = self.client.get(self.url)
        self.assertEqual(sorted(resp.data["filters"]["sizes"]), ["L", "M", "XL"])

    def test_search_by_product_name(self):
        resp = self.client.get(self.url, {"search": "Classic"})
        self.assertEqual(resp.data["count"], 3)

    def test_search_by_sku(self):
        resp = self.client.get(self.url, {"search": "TSHIRT-BLACK-M"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["sku"], "TSHIRT-BLACK-M")

    def test_search_by_color_name(self):
        resp = self.client.get(self.url, {"search": "Black"})
        self.assertEqual(resp.data["count"], 3)

    def test_search_by_category_name(self):
        resp = self.client.get(self.url, {"search": "Men"})
        self.assertEqual(resp.data["count"], 3)

    def test_filter_by_category(self):
        resp = self.client.get(self.url, {"category": str(self.category.id)})
        self.assertEqual(resp.data["count"], 3)

    def test_filter_by_category_no_match(self):
        resp = self.client.get(self.url, {"category": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(resp.data["count"], 0)

    def test_filter_by_size(self):
        resp = self.client.get(self.url, {"size": "M"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["size"], "M")

    def test_filter_low_stock(self):
        resp = self.client.get(self.url, {"low_stock": "true"})
        # L (available=3 <= reorder=10) and XL (available=0 <= reorder=10)
        self.assertEqual(resp.data["count"], 2)

    def test_filter_out_of_stock(self):
        resp = self.client.get(self.url, {"out_of_stock": "true"})
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual(resp.data["results"][0]["size"], "XL")

    def test_ordering_by_name(self):
        resp = self.client.get(self.url, {"ordering": "name"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_ordering_by_stock_quantity_desc(self):
        resp = self.client.get(self.url, {"ordering": "-stock_quantity"})
        quantities = [r["stock"]["stock_quantity"] for r in resp.data["results"]]
        self.assertEqual(quantities, sorted(quantities, reverse=True))

    def test_ordering_by_price(self):
        resp = self.client.get(self.url, {"ordering": "price"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_pagination_page_size(self):
        resp = self.client.get(self.url, {"page_size": "2"})
        self.assertEqual(len(resp.data["results"]), 2)
        self.assertEqual(resp.data["count"], 3)
        self.assertIsNotNone(resp.data["next"])

    def test_pagination_page_2(self):
        resp = self.client.get(self.url, {"page_size": "2", "page": "2"})
        self.assertEqual(len(resp.data["results"]), 1)

    def test_unauthenticated_returns_401(self):
        client = APIClient()
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_inactive_variants_excluded(self):
        self.variant_size_m.is_active = False
        self.variant_size_m.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.data["count"], 2)

    def test_inactive_color_variant_excluded(self):
        self.variant.is_active = False
        self.variant.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.data["count"], 0)

    def test_deleted_product_excluded(self):
        self.product.is_deleted = True
        self.product.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.data["count"], 0)


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
