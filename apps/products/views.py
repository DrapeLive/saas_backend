# apps/products/views.py

from django.db import transaction
from django.db.models import F
from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdminOrSubAdmin
from apps.products.models import (
    Category,
    ColorVariant,
    Product,
    SizeChart,
    StockMovement,
    VariantSize,
)
from apps.products.serializers import (
    CategoryCreateUpdateSerializer,
    CategoryListSerializer,
    CategorySerializer,
    ColorVariantCreateSerializer,
    ColorVariantDetailSerializer,
    ColorVariantListSerializer,
    ProductCreateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductUpdateSerializer,
    SizeChartSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
    VariantSizeSerializer,
)

# ─────────────────────────────────────────────────────────────────
# CATEGORY
# ─────────────────────────────────────────────────────────────────


class CategoryViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def _get_company(self, request):
        return request.user.company

    def _get_obj(self, pk, company):
        try:
            return Category.objects.get(pk=pk, company=company, is_deleted=False)
        except Category.DoesNotExist:
            return None

    # GET /api/categories/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            Category.objects.filter(company=company, is_deleted=False, parent=None)
            .prefetch_related("children")
            .order_by("display_order", "name")
        )
        return Response(CategoryListSerializer(qs, many=True).data)

    # GET /api/categories/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        obj = self._get_obj(pk, company)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CategorySerializer(obj).data)

    # POST /api/categories/
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = CategoryCreateUpdateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        category = serializer.save(company=company)
        return Response(
            CategorySerializer(category).data, status=status.HTTP_201_CREATED
        )

    # PATCH /api/categories/<pk>/
    @transaction.atomic
    def partial_update(self, request, pk=None):
        company = self._get_company(request)
        obj = self._get_obj(pk, company)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = CategoryCreateUpdateSerializer(
            obj, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CategorySerializer(serializer.instance).data)

    # DELETE /api/categories/<pk>/
    def destroy(self, request, pk=None):
        company = self._get_company(request)
        obj = self._get_obj(pk, company)
        if not obj:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if obj.products.filter(is_deleted=False).exists():
            return Response(
                {"detail": "Cannot delete a category that has products."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        obj.is_deleted = True
        obj.deleted_at = now()
        obj.save(update_fields=["is_deleted", "deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────
# SIZE CHART
# ─────────────────────────────────────────────────────────────────


class SizeChartViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def _get_company(self, request):
        return request.user.company

    # GET /api/size-charts/
    def list(self, request):
        company = self._get_company(request)
        qs = SizeChart.objects.filter(company=company).order_by("name")
        return Response(SizeChartSerializer(qs, many=True).data)

    # POST /api/size-charts/
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = SizeChartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        chart = serializer.save(company=company)
        return Response(SizeChartSerializer(chart).data, status=status.HTTP_201_CREATED)

    # PATCH /api/size-charts/<pk>/
    @transaction.atomic
    def partial_update(self, request, pk=None):
        company = self._get_company(request)
        try:
            chart = SizeChart.objects.get(pk=pk, company=company)
        except SizeChart.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = SizeChartSerializer(chart, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    # DELETE /api/size-charts/<pk>/
    def destroy(self, request, pk=None):
        company = self._get_company(request)
        try:
            chart = SizeChart.objects.get(pk=pk, company=company)
        except SizeChart.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if Product.objects.filter(size_chart=chart, is_deleted=False).exists():
            return Response(
                {"detail": "Cannot delete a size chart that is in use."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        chart.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────
# PRODUCT
# ─────────────────────────────────────────────────────────────────


class ProductViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def _get_company(self, request):
        return request.user.company

    def _get_product(self, pk, company):
        try:
            return Product.objects.get(pk=pk, company=company, is_deleted=False)
        except Product.DoesNotExist:
            return None

    # GET /api/products/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            Product.objects.filter(company=company, is_deleted=False)
            .select_related("category")
            .prefetch_related("color_variants")
            .order_by("name")
        )

        category_f = request.query_params.get("category")
        status_f = request.query_params.get("status")
        search = request.query_params.get("search")
        featured = request.query_params.get("featured")
        low_stock = request.query_params.get("low_stock")

        if category_f:
            qs = qs.filter(category_id=category_f)
        if status_f:
            qs = qs.filter(status=status_f)
        if featured:
            qs = qs.filter(is_featured=True)
        if low_stock:
            qs = qs.filter(
                total_stock__lte=F("color_variants__sizes__reorder_level")
            ).distinct()
        if search:
            qs = qs.filter(name__icontains=search) | qs.filter(
                sku_prefix__icontains=search
            )

        return Response(
            ProductListSerializer(qs, many=True, context={"request": request}).data
        )

    # GET /api/products/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        product = self._get_product(pk, company)
        if not product:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        product_qs = Product.objects.prefetch_related("color_variants__sizes").get(
            pk=pk
        )
        return Response(
            ProductDetailSerializer(product_qs, context={"request": request}).data
        )

    # POST /api/products/
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = ProductCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save(company=company)
        return Response(
            ProductDetailSerializer(product, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    # PATCH /api/products/<pk>/
    @transaction.atomic
    def partial_update(self, request, pk=None):
        company = self._get_company(request)
        product = self._get_product(pk, company)
        if not product:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = ProductUpdateSerializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            ProductDetailSerializer(
                serializer.instance, context={"request": request}
            ).data
        )

    # DELETE /api/products/<pk>/
    def destroy(self, request, pk=None):
        company = self._get_company(request)
        product = self._get_product(pk, company)
        if not product:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        product.is_deleted = True
        product.deleted_at = now()
        product.save(update_fields=["is_deleted", "deleted_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    # GET /api/products/scan/<qr_code>/
    @action(detail=False, methods=["get"], url_path=r"scan/(?P<qr_code>[0-9a-f-]+)")
    def scan_qr(self, request, qr_code=None):
        company = self._get_company(request)
        try:
            variant = ColorVariant.objects.get(
                qr_code=qr_code, product__company=company, product__is_deleted=False
            )
        except ColorVariant.DoesNotExist:
            return Response(
                {"detail": "Variant not found."}, status=status.HTTP_404_NOT_FOUND
            )

        product_qs = Product.objects.prefetch_related("color_variants__sizes").get(
            pk=variant.product_id
        )

        data = ProductDetailSerializer(product_qs, context={"request": request}).data
        return Response({"scanned_variant_id": str(variant.id), "product": data})


# ─────────────────────────────────────────────────────────────────
# COLOR VARIANT
# ─────────────────────────────────────────────────────────────────


class ColorVariantViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def _get_product(self, product_pk, company):
        try:
            return Product.objects.get(pk=product_pk, company=company, is_deleted=False)
        except Product.DoesNotExist:
            return None

    # GET /api/products/<product_pk>/variants/
    def list(self, request, product_pk=None):
        company = request.user.company
        product = self._get_product(product_pk, company)
        if not product:
            return Response(
                {"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND
            )
        qs = ColorVariant.objects.filter(product=product).prefetch_related("sizes")
        return Response(ColorVariantListSerializer(qs, many=True).data)

    # GET /api/products/<product_pk>/variants/<pk>/
    def retrieve(self, request, product_pk=None, pk=None):
        company = request.user.company
        product = self._get_product(product_pk, company)
        if not product:
            return Response(
                {"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            variant = ColorVariant.objects.prefetch_related("sizes").get(
                pk=pk, product=product
            )
        except ColorVariant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(ColorVariantDetailSerializer(variant).data)

    # POST /api/products/<product_pk>/variants/
    @transaction.atomic
    def create(self, request, product_pk=None):
        company = request.user.company
        product = self._get_product(product_pk, company)
        if not product:
            return Response(
                {"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND
            )
        serializer = ColorVariantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        variant = serializer.save(product=product)
        return Response(
            ColorVariantDetailSerializer(variant).data, status=status.HTTP_201_CREATED
        )

    # DELETE /api/products/<product_pk>/variants/<pk>/
    def destroy(self, request, product_pk=None, pk=None):
        company = request.user.company
        product = self._get_product(product_pk, company)
        if not product:
            return Response(
                {"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            variant = ColorVariant.objects.get(pk=pk, product=product)
        except ColorVariant.DoesNotExist:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        variant.is_active = False
        variant.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────
# STOCK ADJUSTMENT
# ─────────────────────────────────────────────────────────────────


class StockViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    # GET /api/stock/movements/
    def list(self, request):
        company = request.user.company
        qs = (
            StockMovement.objects.filter(
                variant_size__color_variant__product__company=company
            )
            .select_related(
                "variant_size__color_variant__product",
                "performed_by",
            )
            .order_by("-created_at")[:200]
        )
        return Response(StockMovementSerializer(qs, many=True).data)

    # POST /api/stock/adjust/
    @transaction.atomic
    def adjust(self, request):
        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        variant = VariantSize.objects.select_for_update().get(
            id=data["variant_size_id"]
        )
        qty = data["quantity"]

        if qty < 0 and variant.available_qty < abs(qty):
            return Response(
                {"detail": f"Insufficient stock. Available: {variant.available_qty}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        variant.stock_quantity = F("stock_quantity") + qty
        variant.save(update_fields=["stock_quantity"])
        variant.refresh_from_db(fields=["stock_quantity"])

        StockMovement.objects.create(
            variant_size=variant,
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            quantity=qty,
            balance_after=variant.stock_quantity,
            reason=data["reason"],
            performed_by=request.user,
        )

        # Update parent product total_stock
        product = variant.color_variant.product
        from django.db.models import Sum as DSum

        total = VariantSize.objects.filter(color_variant__product=product).aggregate(
            total=DSum("stock_quantity")
        )
        Product.objects.filter(pk=product.pk).update(total_stock=total["total"] or 0)

        return Response(VariantSizeSerializer(variant).data)
