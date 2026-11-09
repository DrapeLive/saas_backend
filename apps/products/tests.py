from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import RoleType, User
from apps.companies.models import Company
from apps.products.models import Category, ColorVariant, Product, SizeChart, VariantSize


class SizeChartApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(
            name="Size Chart Company",
            slug="size-chart-company",
            contact_email="admin@example.com",
            contact_phone="1234567890",
            status="active",
        )
        self.other_company = Company.objects.create(
            name="Other Company",
            slug="other-company",
            contact_email="other@example.com",
            contact_phone="0987654321",
            status="active",
        )
        self.admin = User.objects.create_user(
            email="admin@example.com",
            password="Password123!",
            full_name="Company Admin",
            role=RoleType.ADMIN,
            company=self.company,
        )
        self.sub_admin = User.objects.create_user(
            email="subadmin@example.com",
            password="Password123!",
            full_name="Company Sub Admin",
            role=RoleType.SUB_ADMIN,
            company=self.company,
        )
        self.agent = User.objects.create_user(
            email="agent@example.com",
            password="Password123!",
            full_name="Company Agent",
            role=RoleType.AGENT,
            company=self.company,
        )
        self.other_admin = User.objects.create_user(
            email="other-admin@example.com",
            password="Password123!",
            full_name="Other Admin",
            role=RoleType.ADMIN,
            company=self.other_company,
        )

    def authenticate(self, user):
        self.client.force_authenticate(user=user)

    def test_admin_can_create_and_update_size_chart(self):
        self.authenticate(self.admin)

        create_response = self.client.post(
            "/api/size-charts/",
            {"name": "Adult", "sizes": ["S", "M", "L"]},
            format="json",
        )

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        chart = SizeChart.objects.get(pk=create_response.data["id"])
        self.assertEqual(chart.company_id, self.company.id)
        self.assertEqual(chart.sizes, ["S", "M", "L"])

        update_response = self.client.patch(
            f"/api/size-charts/{chart.id}/",
            {"name": "Adult Updated", "sizes": ["S", "M", "L", "XL"]},
            format="json",
        )

        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        chart.refresh_from_db()
        self.assertEqual(chart.name, "Adult Updated")
        self.assertEqual(chart.sizes, ["S", "M", "L", "XL"])

    def test_sub_admin_can_create_and_update_size_chart(self):
        self.authenticate(self.sub_admin)
        chart = SizeChart.objects.create(
            company=self.company,
            name="Kids",
            sizes=["2Y", "3Y"],
        )

        response = self.client.patch(
            f"/api/size-charts/{chart.id}/",
            {"sizes": ["2Y", "3Y", "4Y"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        chart.refresh_from_db()
        self.assertEqual(chart.sizes, ["2Y", "3Y", "4Y"])

    def test_update_preserves_inventory_and_order_ranges(self):
        self.authenticate(self.admin)
        chart = SizeChart.objects.create(
            company=self.company,
            name="Kids",
            sizes=["2Y", "3Y", "4Y"],
        )

        response = self.client.patch(
            f"/api/size-charts/{chart.id}/",
            {
                "sizes": [
                    {
                        "item_creation": {"2-4Y": ["2Y", "3Y", "4Y"]},
                        "order_creation": {"S": ["2Y", "3Y"]},
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        chart.refresh_from_db()
        self.assertEqual(chart.sizes[0]["item_creation"]["2-4Y"], ["2Y", "3Y", "4Y"])
        self.assertEqual(chart.sizes[0]["order_creation"]["S"], ["2Y", "3Y"])

    def test_invalid_size_chart_payload_is_rejected(self):
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/size-charts/",
            {"name": "Empty", "sizes": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["detail"], "Sizes must be a non-empty list.")

    def test_other_company_cannot_update_chart(self):
        chart = SizeChart.objects.create(
            company=self.company,
            name="Adult",
            sizes=["S", "M"],
        )
        self.authenticate(self.other_admin)

        response = self.client.patch(
            f"/api/size-charts/{chart.id}/",
            {"name": "Stolen", "sizes": ["X"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        chart.refresh_from_db()
        self.assertEqual(chart.name, "Adult")
        self.assertEqual(chart.sizes, ["S", "M"])

    def test_agent_cannot_modify_size_chart(self):
        self.authenticate(self.agent)

        response = self.client.post(
            "/api/size-charts/",
            {"name": "Agent Chart", "sizes": ["S"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_updating_chart_preserves_product_association(self):
        category = Category.objects.create(
            company=self.company,
            name="Clothing",
            slug="clothing",
        )
        chart = SizeChart.objects.create(
            company=self.company,
            name="Adult",
            sizes=["S", "M"],
        )
        product = Product.objects.create(
            company=self.company,
            category=category,
            name="T-Shirt",
            size_chart=chart,
        )
        self.authenticate(self.admin)

        response = self.client.patch(
            f"/api/size-charts/{chart.id}/",
            {"sizes": ["S", "M", "L"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        product.refresh_from_db()
        self.assertEqual(product.size_chart_id, chart.id)

    def test_product_status_is_removed_without_losing_product_data(self):
        category = Category.objects.create(
            company=self.company,
            name="Clothing",
            slug="clothing",
        )
        self.authenticate(self.admin)

        response = self.client.post(
            "/api/products/",
            {
                "category": str(category.id),
                "name": "Polo",
                "mrp": "100.00",
                "wholesale_price": "70.00",
                "status": "inactive",  # Legacy clients may still send this.
                "color_variants": [
                    {
                        "color_name": "Navy",
                        "is_primary": True,
                        "sizes": [
                            {
                                "size": "M",
                                "sku": "POLO-NAVY-M",
                                "stock_quantity": 4,
                                "reorder_level": 1,
                            }
                        ],
                    }
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertNotIn("status", response.data)
        product = Product.objects.get(pk=response.data["id"])
        self.assertEqual(product.name, "Polo")
        self.assertEqual(product.total_stock, 4)
        self.assertEqual(product.category_id, category.id)
        self.assertEqual(product.color_variants.count(), 1)

        update_response = self.client.patch(
            f"/api/products/{product.id}/",
            {"name": "Polo Updated", "status": "discontinued"},
            format="json",
        )
        self.assertEqual(update_response.status_code, status.HTTP_200_OK)
        self.assertNotIn("status", update_response.data)

        product.refresh_from_db()
        self.assertEqual(product.name, "Polo Updated")
        self.assertEqual(product.total_stock, 4)
        self.assertEqual(product.color_variants.first().sizes.first().stock_quantity, 4)

        list_response = self.client.get("/api/products/?status=inactive")
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(list_response.data), 1)
        self.assertNotIn("status", list_response.data[0])

        self.client.force_authenticate(user=self.other_admin)
        other_response = self.client.get(f"/api/products/{product.id}/")
        self.assertEqual(other_response.status_code, status.HTTP_404_NOT_FOUND)

    def test_low_stock_dashboard_returns_size_rows_with_product_color_ids(self):
        category = Category.objects.create(
            company=self.company,
            name="Clothing",
            slug="clothing",
        )
        product = Product.objects.create(
            company=self.company,
            category=category,
            name="Premium Cotton Madras Plaid",
        )
        blue = ColorVariant.objects.create(
            product=product,
            color_name="Blue",
            sku="PLAID-BLUE",
        )
        red = ColorVariant.objects.create(
            product=product,
            color_name="Red",
            sku="PLAID-RED",
        )
        VariantSize.objects.create(
            color_variant=blue,
            size="S",
            sku="PLAID-BLUE-S",
            stock_quantity=2,
            reorder_level=5,
        )
        VariantSize.objects.create(
            color_variant=blue,
            size="M",
            sku="PLAID-BLUE-M",
            stock_quantity=3,
            reorder_level=5,
        )
        VariantSize.objects.create(
            color_variant=blue,
            size="L",
            sku="PLAID-BLUE-L",
            stock_quantity=20,
            reorder_level=5,
        )
        VariantSize.objects.create(
            color_variant=red,
            size="S",
            sku="PLAID-RED-S",
            stock_quantity=1,
            reorder_level=5,
        )

        self.authenticate(self.admin)
        response = self.client.get("/api/admin/dashboard/low-stock-items")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_low_stock_items"], 3)
        self.assertEqual(
            {(row["product_id"], row["color_variant_id"]) for row in response.data["items"]},
            {(str(product.id), str(blue.id)), (str(product.id), str(red.id))},
        )
        self.assertEqual(
            sum(row["color_variant_id"] == str(blue.id) for row in response.data["items"]),
            2,
        )
