from decimal import Decimal
import uuid

from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import RoleType, User
from apps.companies.models import Company
from apps.customers.models import CustomerProfile
from apps.orders.models import Order, OrderItem, OrderStatus
from apps.products.models import Category, ColorVariant, Product, VariantSize


def authenticate(client: APIClient, user: User, company: Company | None = None):
    """Issue a real JWT so CustomJWTAuthentication resolves request.company."""
    refresh = RefreshToken.for_user(user)
    if company is not None:
        refresh["company_id"] = str(company.id)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class PackingTestBase:
    """Shared fixtures for packing tests."""

    @classmethod
    def create_company(cls, slug="acme-textiles") -> Company:
        return Company.objects.create(
            name="Acme Textiles",
            slug=slug,
            contact_email=f"ops@{slug}.com",
            contact_phone="9876543210",
        )

    @classmethod
    def create_user(cls, email, role, company=None) -> User:
        return User.objects.create_user(
            email=email,
            password="pass-12345",
            full_name=email.split("@")[0].title(),
            role=role,
            company=company,
        )

    @classmethod
    def create_customer(cls, company: Company) -> CustomerProfile:
        return CustomerProfile.objects.create(
            company=company,
            trade_name="Fashion Hub",
            legal_name="Fashion Hub Retail Pvt Ltd",
            phone="9123456780",
        )

    @classmethod
    def create_variant(cls, company: Company, sku: str, stock: int = 100) -> VariantSize:
        category, _ = Category.objects.get_or_create(
            company=company,
            slug="mens",
            defaults={"name": "Mens"},
        )
        product = Product.objects.create(
            company=company,
            category=category,
            name="Cotton Shirt",
            wholesale_price=Decimal("500.00"),
            mrp=Decimal("999.00"),
        )
        color = ColorVariant.objects.create(
            product=product, color_name="Blue", sku=f"{sku}-BLUE"
        )
        return VariantSize.objects.create(
            color_variant=color, size="M", sku=sku, stock_quantity=stock
        )

    @classmethod
    def create_order(
        cls,
        company: Company,
        customer: CustomerProfile,
        items: list[tuple[VariantSize, int]],
        status: str = OrderStatus.PROCESSING,
        reserve: bool = True,
    ) -> Order:
        order = Order.objects.create(
            company=company,
            order_number=f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}",
            customer=customer,
            status=status,
        )
        for variant, qty in items:
            OrderItem.objects.create(
                order=order,
                variant_size=variant,
                product_name=variant.color_variant.product.name,
                color_name=variant.color_variant.color_name,
                size=variant.size,
                sku=variant.sku,
                unit_price=Decimal("500.00"),
                quantity=qty,
                line_total=Decimal("500.00") * qty,
            )
            if reserve:
                VariantSize.objects.filter(pk=variant.pk).update(
                    reserved_qty=qty  # test variants start with no other reservations
                )
                variant.refresh_from_db(fields=["reserved_qty"])
        return order
