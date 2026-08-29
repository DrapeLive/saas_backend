from typing import ClassVar

from django.db import transaction
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.products.models import (
    Category,
    ColorVariant,
    Product,
    SizeChart,
    StockMovement,
    VariantSize,
)


class CategoryListSerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(
        source="parent.name", read_only=True, default=None
    )
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields: ClassVar = [
            "id",
            "name",
            "slug",
            "parent",
            "parent_name",
            "image",
            "display_order",
            "is_active",
            "default_commission_pct",
            "product_count",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_product_count(self, obj):
        return obj.products.count()


class CategorySerializer(serializers.ModelSerializer):
    children = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields: ClassVar = [
            "id",
            "name",
            "slug",
            "parent",
            "description",
            "image",
            "display_order",
            "is_active",
            "default_commission_pct",
            "children",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(CategoryListSerializer(many=True))
    def get_children(self, obj):
        qs = obj.children.filter(is_deleted=False, is_active=True)
        return CategoryListSerializer(qs, many=True).data


class CategoryCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields: ClassVar = [
            "name",
            "slug",
            "parent",
            "description",
            "image",
            "display_order",
            "is_active",
            "default_commission_pct",
        ]

    def validate_slug(self, value):
        request = self.context.get("request")
        company = getattr(request, "company", None)
        qs = Category.objects.filter(company=company, slug=value, is_deleted=False)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(
                "A category with this slug already exists."
            )
        return value


class SizeChartSerializer(serializers.ModelSerializer):
    class Meta:
        model = SizeChart
        fields: ClassVar = [
            "id",
            "name",
            "sizes",
            "created_at",
            "updated_at",
        ]

    def validate_sizes(self, value):
        if not isinstance(value, list) or len(value) == 0:
            raise serializers.ValidationError("Sizes must be a non-empty list.")
        return value


class VariantSizeSerializer(serializers.ModelSerializer):
    available_qty = serializers.IntegerField(read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = VariantSize
        fields: ClassVar = [
            "id",
            "size",
            "sku",
            "price_override",
            "stock_quantity",
            "reserved_qty",
            "available_qty",
            "reorder_level",
            "is_low_stock",
            "is_active",
        ]


class VariantSizeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VariantSize
        fields: ClassVar = [
            "size",
            "sku",
            "price_override",
            "stock_quantity",
            "reorder_level",
            "is_active",
        ]


class ColorVariantListSerializer(serializers.ModelSerializer):
    total_stock = serializers.SerializerMethodField()

    class Meta:
        model = ColorVariant
        fields: ClassVar = [
            "id",
            "color_name",
            "color_hex",
            "image",
            "is_primary",
            "sku",
            "is_active",
            "total_stock",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_total_stock(self, obj):
        return sum(s.available_qty for s in obj.sizes.filter(is_active=True))


class ColorVariantDetailSerializer(serializers.ModelSerializer):
    sizes = VariantSizeSerializer(many=True, read_only=True)

    class Meta:
        model = ColorVariant
        fields: ClassVar = [
            "id",
            "color_name",
            "color_hex",
            "image",
            "is_primary",
            "sku",
            "qr_code",
            "is_active",
            "sizes",
            "created_at",
            "updated_at",
        ]


class ColorVariantCreateSerializer(serializers.ModelSerializer):
    sizes = VariantSizeCreateSerializer(many=True, required=False)

    class Meta:
        model = ColorVariant
        fields: ClassVar = [
            "color_name",
            "color_hex",
            "image",
            "is_primary",
            "is_active",
            "sizes",
        ]

    def create(self, validated_data):
        sizes_data = validated_data.pop("sizes", [])
        variant = ColorVariant.objects.create(**validated_data)
        for size_data in sizes_data:
            VariantSize.objects.create(color_variant=variant, **size_data)
        return variant


class ProductListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    primary_image = serializers.SerializerMethodField()
    variant_count = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields: ClassVar = [
            "id",
            "name",
            "category",
            "category_name",
            "sku_prefix",
            "hsn_code",
            "gst_rate",
            "mrp",
            "wholesale_price",
            "minimum_order_qty",
            "total_stock",
            "status",
            "primary_image",
            "variant_count",
            "created_at",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_primary_image(self, obj):
        variant = obj.color_variants.filter(is_primary=True).first()
        if not variant:
            variant = obj.color_variants.first()
        if variant and variant.image:
            request = self.context.get("request")
            return (
                request.build_absolute_uri(variant.image.url)
                if request
                else variant.image.url
            )
        return None

    @extend_schema_field(serializers.IntegerField())
    def get_variant_count(self, obj):
        return obj.color_variants.count()


class ProductDetailSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    size_chart_name = serializers.CharField(
        source="size_chart.name", read_only=True, default=None
    )
    color_variants = ColorVariantDetailSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields: ClassVar = [
            "id",
            "category",
            "category_name",
            "name",
            "description",
            "sku_prefix",
            "hsn_code",
            "gst_rate",
            "size_chart",
            "size_chart_name",
            "mrp",
            "wholesale_price",
            "minimum_order_qty",
            "order_in_multiples",
            "total_stock",
            "status",
            "color_variants",
            "created_at",
            "updated_at",
        ]


class ProductCreateSerializer(serializers.ModelSerializer):
    color_variants = ColorVariantCreateSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields: ClassVar = [
            "category",
            "name",
            "description",
            "sku_prefix",
            "hsn_code",
            "gst_rate",
            "size_chart",
            "mrp",
            "wholesale_price",
            "minimum_order_qty",
            "order_in_multiples",
            "status",
            "color_variants",
        ]

    def validate_wholesale_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Wholesale price cannot be negative.")
        return value

    def validate(self, attrs):
        wholesale = attrs.get("wholesale_price", 0)
        mrp = attrs.get("mrp")
        if mrp is not None and wholesale > mrp:
            raise serializers.ValidationError(
                {"wholesale_price": "Wholesale price cannot exceed MRP."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        variants_data = validated_data.pop("color_variants", [])

        product = Product.objects.create(**validated_data)

        total_stock = 0

        for variant_data in variants_data:
            sizes_data = variant_data.pop("sizes", [])

            color_slug = slugify(variant_data["color_name"]).upper().replace("-", "")
            variant_data.pop("sku", None)

            variant = ColorVariant.objects.create(
                product=product,
                sku=f"{product.sku_prefix}-{color_slug}",
                **variant_data,
            )

            for size_data in sizes_data:
                size_data.pop("sku", None)
                stock = size_data.get("stock_quantity", 0)

                VariantSize.objects.create(
                    color_variant=variant,
                    sku=f"{variant.sku}-{size_data['size']}",
                    **size_data,
                )

                total_stock += stock

        product.total_stock = total_stock
        product.save(update_fields=["total_stock"])

        return product


class ProductUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields: ClassVar = [
            "category",
            "name",
            "description",
            "hsn_code",
            "gst_rate",
            "size_chart",
            "mrp",
            "wholesale_price",
            "minimum_order_qty",
            "order_in_multiples",
            "status",
        ]


class StockMovementSerializer(serializers.ModelSerializer):
    performed_by_name = serializers.CharField(
        source="performed_by.full_name", read_only=True, default=None
    )
    product_name = serializers.CharField(
        source="variant_size.color_variant.product.name", read_only=True
    )
    color_name = serializers.CharField(
        source="variant_size.color_variant.color_name", read_only=True
    )
    size = serializers.CharField(source="variant_size.size", read_only=True)

    class Meta:
        model = StockMovement
        fields: ClassVar = [
            "id",
            "variant_size",
            "product_name",
            "color_name",
            "size",
            "movement_type",
            "quantity",
            "balance_after",
            "reference_type",
            "reference_id",
            "reason",
            "performed_by_name",
            "created_at",
        ]


class StockAdjustmentSerializer(serializers.Serializer):
    variant_size_id = serializers.UUIDField()
    quantity = serializers.IntegerField()  # positive = add, negative = remove
    reason = serializers.CharField(max_length=500)

    def validate_variant_size_id(self, value):
        if not VariantSize.objects.filter(id=value, is_active=True).exists():
            raise serializers.ValidationError("Variant size not found or inactive.")
        return value

    def validate_quantity(self, value):
        if value == 0:
            raise serializers.ValidationError("Quantity cannot be zero.")
        return value


# ─────────────────────────────────────────────────────────────────
# INVENTORY LISTING (VariantSize-level)
# ─────────────────────────────────────────────────────────────────


class ProductRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class CategoryRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class ColorRefSerializer(serializers.Serializer):
    name = serializers.CharField()
    hex = serializers.CharField(allow_null=True)


class StockInfoSerializer(serializers.Serializer):
    stock_quantity = serializers.IntegerField()
    reserved_quantity = serializers.IntegerField()
    available_quantity = serializers.IntegerField()
    reorder_level = serializers.IntegerField()
    is_low_stock = serializers.BooleanField()
    is_out_of_stock = serializers.BooleanField()


class ProductInventoryListSerializer(serializers.ModelSerializer):
    """One inventory row per VariantSize (SKU)."""

    product = serializers.SerializerMethodField()
    image = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    color = serializers.SerializerMethodField()
    price_per_unit = serializers.SerializerMethodField()
    stock = serializers.SerializerMethodField()

    class Meta:
        model = VariantSize
        fields = [
            "id",
            "product",
            "image",
            "sku",
            "category",
            "color",
            "size",
            "price_per_unit",
            "stock",
        ]

    @extend_schema_field(ProductRefSerializer)
    def get_product(self, obj):
        p = obj.color_variant.product
        return {"id": str(p.id), "name": p.name}

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_image(self, obj):
        image = obj.color_variant.image
        if not image:
            return None
        request = self.context.get("request")
        return request.build_absolute_uri(image.url) if request else image.url

    @extend_schema_field(CategoryRefSerializer)
    def get_category(self, obj):
        c = obj.color_variant.product.category
        return {"id": str(c.id), "name": c.name}

    @extend_schema_field(ColorRefSerializer)
    def get_color(self, obj):
        return {
            "name": obj.color_variant.color_name,
            "hex": obj.color_variant.color_hex,
        }

    @extend_schema_field(serializers.CharField())
    def get_price_per_unit(self, obj):
        price = (
            obj.price_override
            if obj.price_override is not None
            else obj.color_variant.product.wholesale_price
        )
        return str(price)

    @extend_schema_field(StockInfoSerializer)
    def get_stock(self, obj):
        return {
            "stock_quantity": obj.stock_quantity,
            "reserved_quantity": obj.reserved_qty,
            "available_quantity": obj.available_qty,
            "reorder_level": obj.reorder_level,
            "is_low_stock": obj.is_low_stock,
            "is_out_of_stock": obj.available_qty <= 0,
        }


class ProductInventorySummarySerializer(serializers.Serializer):
    """Summary stats computed over the full filtered queryset."""

    stock_valuation = serializers.DecimalField(max_digits=14, decimal_places=2)


class InventoryFiltersSerializer(serializers.Serializer):
    """Facet values available in the current filtered result set."""

    sizes = serializers.ListField(child=serializers.CharField())


class ProductInventoryPageSerializer(serializers.Serializer):
    """Paginated inventory listing envelope returned by `GET /api/products/`."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    summary = ProductInventorySummarySerializer()
    filters = InventoryFiltersSerializer()
    results = ProductInventoryListSerializer(many=True)


class ScanQRResponseSerializer(serializers.Serializer):
    """Result of scanning a variant QR code."""

    scanned_variant_id = serializers.UUIDField()
    product = ProductDetailSerializer()
