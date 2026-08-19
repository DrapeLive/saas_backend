import json
import uuid
from io import BytesIO
from typing import ClassVar

from django.core.files import File
from django.db import models

from apps.core.models import (
    CompanyScopeModel,
    SoftDeleteModel,
    TimeStampedModel,
    UUIDModel,
)


class Category(CompanyScopeModel, SoftDeleteModel):
    """
    Product categories (Mens, Ladies, Kids, etc.)
    Used for commission rate overrides.
    Supports nested categories (parent→child).
    """

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="media/categories/", null=True, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    default_commission_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="e.g., Mens=2%, Kids=3%, Ladies=4%",
    )

    class Meta:
        db_table = "products_category"
        unique_together: ClassVar = [("company", "slug")]

    def __str__(self):
        return f"{self.name} ({self.company.name})"


class SizeChart(CompanyScopeModel):
    name = models.CharField(max_length=100)
    sizes = models.JSONField(default=list)  # ["XS","S","M","L","XL","XXL"]

    class Meta:
        db_table = "products_size_chart"

    def __str__(self):
        return self.name


class Product(CompanyScopeModel, SoftDeleteModel):
    class ProductStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        DISCONTINUED = "discontinued", "Discontinued"

    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    sku_prefix = models.CharField(max_length=20, blank=True)
    hsn_code = models.CharField(max_length=10, blank=True, help_text="HSN code for GST")
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=5.00)
    size_chart = models.ForeignKey(
        SizeChart, null=True, blank=True, on_delete=models.SET_NULL
    )

    mrp = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    minimum_order_qty = models.PositiveIntegerField(default=1)
    order_in_multiples = models.PositiveIntegerField(default=1)

    status = models.CharField(
        max_length=20, choices=ProductStatus.choices, default=ProductStatus.ACTIVE
    )

    total_stock = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "products_product"
        indexes: ClassVar = [
            models.Index(fields=["company", "status"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.company.name})"


class ColorVariant(UUIDModel, TimeStampedModel):
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="color_variants"
    )
    color_name = models.CharField(max_length=100)
    color_hex = models.CharField(max_length=7, blank=True)
    image = models.ImageField(
        upload_to="media/products/variants/", null=True, blank=True
    )
    is_primary = models.BooleanField(default=False)
    sku = models.CharField(max_length=50, unique=True)
    qr_code = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "products_color_variant"
        unique_together: ClassVar = [("product", "color_name")]

    def __str__(self):
        return f"{self.product.name} — {self.color_name}"


class VariantSize(UUIDModel, TimeStampedModel):
    color_variant = models.ForeignKey(
        ColorVariant, on_delete=models.CASCADE, related_name="sizes"
    )
    size = models.CharField(max_length=20)
    sku = models.CharField(max_length=60, unique=True)

    # Pricing override (if size-specific price differs from product price)
    price_override = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    stock_quantity = models.IntegerField(default=0)
    reserved_qty = models.IntegerField(
        default=0, help_text="Reserved for pending orders"
    )
    reorder_level = models.PositiveIntegerField(default=10)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "products_variant_size"
        unique_together: ClassVar = [("color_variant", "size")]

    def __str__(self):
        return f"{self.color_variant} / {self.size} — stock={self.stock_quantity}"

    @property
    def available_qty(self):
        return max(0, self.stock_quantity - self.reserved_qty)

    @property
    def is_low_stock(self):
        return self.available_qty <= self.reorder_level


class StockMovement(UUIDModel, TimeStampedModel):
    class MovementType(models.TextChoices):
        IN = "in", "Stock In"
        OUT = "out", "Stock Out (Sale)"
        ADJUSTMENT = "adjustment", "Manual Adjustment"
        RETURN = "return", "Customer Return"
        RESERVE = "reserve", "Reserved (Order)"
        RELEASE = "release", "Released (Cancelled)"
        DAMAGE = "damage", "Damaged/Written Off"

    variant_size = models.ForeignKey(
        VariantSize, on_delete=models.CASCADE, related_name="movements"
    )
    movement_type = models.CharField(max_length=15, choices=MovementType.choices)
    quantity = models.IntegerField(help_text="Positive = in, Negative = out")
    balance_after = models.IntegerField()
    reference_type = models.CharField(
        max_length=50, blank=True
    )  # 'order', 'manual', 'return'
    reference_id = models.UUIDField(null=True, blank=True)
    reason = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        "accounts.User", null=True, on_delete=models.SET_NULL
    )

    class Meta:
        db_table = "products_stock_movement"
        ordering: ClassVar = ["-created_at"]
        indexes: ClassVar = [models.Index(fields=["variant_size", "created_at"])]
