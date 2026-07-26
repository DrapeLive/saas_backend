from typing import ClassVar

from rest_framework import serializers

from apps.products.models import (
    Category,
    ColorVariant,
    Product,
    ProductImage,
    SizeChart,
    StockMovement,
    VariantSize,
)


class CategoryListSerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(
        source="parent.name", read_only=True, default=None
    )
    product_count = serializers.IntegerField(source="products.count", read_only=True)

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
        qs = Category.objects.filter(tenant=company, slug=value, is_deleted=False)
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


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields: ClassVar = [
            "id",
            "image",
            "is_primary",
            "alt_text",
            "display_order",
        ]


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
            "color_image",
            "sku",
            "is_active",
            "total_stock",
        ]

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
            "color_image",
            "sku",
            "qr_code",
            "qr_data",
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
            "color_image",
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
    variant_count = serializers.IntegerField(
        source="color_variants.count", read_only=True
    )

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
            "is_featured",
            "primary_image",
            "variant_count",
            "created_at",
        ]

    def get_primary_image(self, obj):
        img = obj.images.filter(is_primary=True).first()
        if img:
            request = self.context.get("request")
            return (
                request.build_absolute_uri(img.image.url) if request else img.image.url
            )
        return None


class ProductDetailSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    size_chart_name = serializers.CharField(
        source="size_chart.name", read_only=True, default=None
    )
    images = ProductImageSerializer(many=True, read_only=True)
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
            "is_featured",
            "tags",
            "images",
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
            "is_featured",
            "tags",
            "color_variants",
        ]

    def validate_wholesale_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Wholesale price cannot be negative.")
        return value

    def validate(self, attrs):
        if attrs.get("wholesale_price", 0) > attrs.get("mrp", 0):
            raise serializers.ValidationError(
                {"wholesale_price": "Wholesale price cannot exceed MRP."}
            )
        return attrs

    def create(self, validated_data):
        variants_data = validated_data.pop("color_variants", [])
        product = Product.objects.create(**validated_data)
        for variant_data in variants_data:
            sizes_data = variant_data.pop("sizes", [])
            variant = ColorVariant.objects.create(product=product, **variant_data)
            for size_data in sizes_data:
                VariantSize.objects.create(color_variant=variant, **size_data)
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
            "is_featured",
            "tags",
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
