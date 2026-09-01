# apps/products/views.py

from collections import OrderedDict
from decimal import Decimal

from django.db import models, transaction
from django.db.models import Case, F, Q, Sum, When
from django.utils.timezone import now
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import CompanyApproved, IsAdminOrSubAdmin, IsCompanyStaff
from apps.core.openapi import RESPONSE_400, RESPONSE_404
from apps.core.pagination import DefaultPageNumberPagination
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
    ProductInventoryListSerializer,
    ProductInventoryPageSerializer,
    ProductListSerializer,
    ProductUpdateSerializer,
    ScanQRResponseSerializer,
    SizeChartSerializer,
    StockAdjustmentSerializer,
    StockMovementSerializer,
    VariantSizeSerializer,
)

# ─────────────────────────────────────────────────────────────────
# CATEGORY
# ─────────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(
        tags=["Categories"],
        summary="List root categories",
        description="Lists top-level categories with their active children nested inline.",
        responses={200: CategoryListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Categories"],
        summary="Get category",
        responses={200: CategorySerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Categories"],
        summary="Create category",
        responses={201: CategorySerializer, 400: RESPONSE_400},
    ),
    partial_update=extend_schema(
        tags=["Categories"],
        summary="Update category",
        responses={200: CategorySerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    destroy=extend_schema(
        tags=["Categories"],
        summary="Delete category (soft)",
        description="Soft-deletes a root/child category. Blocked if products are still attached. Returns 204.",
        responses={204: None, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
)
class CategoryViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)

    def get_permissions(self):
        if self.action == "list":
            permission_classes = [IsCompanyStaff]
        elif self.action == "retrieve":
            permission_classes = [IsCompanyStaff]
        elif self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrSubAdmin]
        else:
            permission_classes = [IsAdminOrSubAdmin]

        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "list":
            return CategoryListSerializer
        if self.action in ("create", "partial_update"):
            return CategoryCreateUpdateSerializer
        return CategorySerializer

    def _get_company(self, request):
        return request.company or request.user.company

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


@extend_schema_view(
    list=extend_schema(
        tags=["Size Charts"],
        summary="List size charts",
        responses={200: SizeChartSerializer(many=True)},
    ),
    create=extend_schema(
        tags=["Size Charts"],
        summary="Create size chart",
        responses={201: SizeChartSerializer, 400: RESPONSE_400},
    ),
    partial_update=extend_schema(
        tags=["Size Charts"],
        summary="Update size chart",
        responses={200: SizeChartSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    destroy=extend_schema(
        tags=["Size Charts"],
        summary="Delete size chart",
        description="Blocked while any product references the chart. Returns 204.",
        responses={204: None, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
)
class SizeChartViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    serializer_class = SizeChartSerializer

    def get_permissions(self):
        if self.action == "list":
            permission_classes = [IsCompanyStaff]
        elif self.action == "retrieve":
            permission_classes = [IsCompanyStaff]
        elif self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrSubAdmin]
        else:
            permission_classes = [IsAdminOrSubAdmin]

        return [permission() for permission in permission_classes]

    def _get_company(self, request):
        return request.company or request.user.company

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


@extend_schema_view(
    list=extend_schema(
        tags=["Products"],
        summary="Inventory listing",
        description=(
            "Paginated SKU-level inventory with search, filters, ordering, live "
            "stock summary and facet values. Each row is a `VariantSize` (SKU)."
        ),
        parameters=[
            OpenApiParameter(
                "page",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                description="Page number (default 1).",
            ),
            OpenApiParameter(
                "page_size",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                description="Page size (default 20, max 100).",
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Search product name, SKU, color name or category name.",
            ),
            OpenApiParameter(
                "category",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                description="Filter by category id.",
            ),
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=["active", "inactive", "discontinued"],
                description="Filter by product status.",
            ),
            OpenApiParameter(
                "size",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Filter by size label.",
            ),
            OpenApiParameter(
                "low_stock",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                description="`true` to show items at or below reorder level.",
            ),
            OpenApiParameter(
                "out_of_stock",
                OpenApiTypes.BOOL,
                OpenApiParameter.QUERY,
                description="`true` to show items with zero available quantity.",
            ),
            OpenApiParameter(
                "ordering",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=[
                    "name",
                    "-name",
                    "sku",
                    "-sku",
                    "price",
                    "-price",
                    "stock_quantity",
                    "-stock_quantity",
                    "created_at",
                    "-created_at",
                ],
                description="Sort order (default `name`).",
            ),
        ],
        responses={200: ProductInventoryPageSerializer},
    ),
    retrieve=extend_schema(
        tags=["Products"],
        summary="Get product details",
        description="Full product record including images, color variants and per-size stock.",
        responses={200: ProductDetailSerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Products"],
        summary="Create product",
        description="Creates a product with optional nested `color_variants` (each with `sizes`).",
        responses={201: ProductDetailSerializer, 400: RESPONSE_400},
    ),
    partial_update=extend_schema(
        tags=["Products"],
        summary="Update product",
        responses={200: ProductDetailSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    destroy=extend_schema(
        tags=["Products"],
        summary="Delete product (soft)",
        description="Soft-deletes a product. Returns 204.",
        responses={204: None, 404: RESPONSE_404},
    ),
    scan_qr=extend_schema(
        tags=["Products"],
        summary="Look up variant by QR code",
        description=(
            "Resolves a variant QR code to the full product payload plus the "
            "scanned `scanned_variant_id`."
        ),
        parameters=[
            OpenApiParameter(
                "qr_code",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
                description="Variant QR code.",
            )
        ],
        responses={200: ScanQRResponseSerializer, 404: RESPONSE_404},
    ),
)
class ProductViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)

    def get_serializer_class(self):
        if self.action == "list":
            return ProductInventoryListSerializer
        if self.action == "create":
            return ProductCreateSerializer
        if self.action == "partial_update":
            return ProductUpdateSerializer
        return ProductDetailSerializer

    def get_permissions(self):
        # Agents (quick action: browse catalog, scan QR) may read; only
        # admin/sub-admin may mutate catalog data.
        if self.action in ("create", "partial_update", "destroy"):
            return [IsAuthenticated(), CompanyApproved(), IsAdminOrSubAdmin()]
        return [IsAuthenticated(), CompanyApproved(), IsCompanyStaff()]

    def _get_company(self, request):
        return request.company or request.user.company

    def _get_product(self, pk, company):
        try:
            return Product.objects.get(pk=pk, company=company, is_deleted=False)
        except Product.DoesNotExist:
            return None

    def get_paginated_response(self, data):
        assert self.paginator is not None
        return Response(
            OrderedDict(
                [
                    ("count", self.paginator.page.paginator.count),
                    ("next", self.paginator.get_next_link()),
                    ("previous", self.paginator.get_previous_link()),
                    ("summary", data.get("summary")),
                    ("filters", data.get("filters")),
                    ("results", data.get("results")),
                ]
            )
        )

    # GET /api/products/
    def list(self, request):
        company = self._get_company(request)

        qs = (
            VariantSize.objects.filter(
                color_variant__product__company=company,
                color_variant__product__is_deleted=False,
                color_variant__is_active=True,
                is_active=True,
            )
            .select_related(
                "color_variant",
                "color_variant__product",
                "color_variant__product__category",
            )
            .order_by(
                "color_variant__product__name",
                "color_variant__color_name",
                "size",
            )
        )

        # Search: product name, SKU, color name, category name
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(color_variant__product__name__icontains=search)
                | Q(sku__icontains=search)
                | Q(color_variant__color_name__icontains=search)
                | Q(color_variant__product__category__name__icontains=search)
            )

        # Category filter (UUID)
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(color_variant__product__category_id=category)

        # Status filter (active/inactive/discontinued)
        status_f = request.query_params.get("status")
        if status_f:
            qs = qs.filter(color_variant__product__status=status_f)

        # Size filter
        size = request.query_params.get("size")
        if size:
            qs = qs.filter(size=size)

        # Low stock: available_qty <= reorder_level
        low_stock = request.query_params.get("low_stock")
        if low_stock and low_stock.lower() == "true":
            qs = qs.filter(stock_quantity__lte=F("reorder_level") + F("reserved_qty"))

        # Out of stock: available_qty <= 0
        out_of_stock = request.query_params.get("out_of_stock")
        if out_of_stock and out_of_stock.lower() == "true":
            qs = qs.filter(stock_quantity__lte=F("reserved_qty"))

        # Ordering (whitelist)
        ALLOWED_ORDERING = {
            "name": "color_variant__product__name",
            "-name": "-color_variant__product__name",
            "sku": "sku",
            "-sku": "-sku",
            "price": "price_override",
            "-price": "-price_override",
            "stock_quantity": "stock_quantity",
            "-stock_quantity": "-stock_quantity",
            "created_at": "created_at",
            "-created_at": "-created_at",
        }
        ordering = request.query_params.get("ordering", "name")
        if ordering in ALLOWED_ORDERING:
            qs = qs.order_by(ALLOWED_ORDERING[ordering])

        # Summary: stock valuation over full filtered queryset (before pagination)
        valuation = qs.aggregate(
            total=Sum(
                Case(
                    When(
                        price_override__isnull=False,
                        then=F("price_override") * F("stock_quantity"),
                    ),
                    default=F("color_variant__product__wholesale_price")
                    * F("stock_quantity"),
                    output_field=models.DecimalField(max_digits=14, decimal_places=2),
                )
            )
        )
        stock_valuation = valuation["total"] or Decimal("0.00")
        stock_valuation = stock_valuation.quantize(Decimal("0.01"))

        # Filter facets: available sizes in current result set
        available_sizes = list(
            qs.values_list("size", flat=True).distinct().order_by("size")
        )

        # Paginate and serialize
        self.pagination_class = DefaultPageNumberPagination
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ProductInventoryListSerializer(
                page, many=True, context={"request": request}
            )
            return self.get_paginated_response(
                {
                    "summary": {"stock_valuation": str(stock_valuation)},
                    "filters": {"sizes": available_sizes},
                    "results": serializer.data,
                }
            )

        serializer = ProductInventoryListSerializer(
            qs, many=True, context={"request": request}
        )
        return Response(
            {
                "count": qs.count(),
                "summary": {"stock_valuation": str(stock_valuation)},
                "filters": {"sizes": available_sizes},
                "results": serializer.data,
            }
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


@extend_schema_view(
    list=extend_schema(
        tags=["Products"],
        summary="List color variants",
        description="Lists every color variant (with sizes) for a product.",
        responses={200: ColorVariantListSerializer(many=True), 404: RESPONSE_404},
    ),
    retrieve=extend_schema(
        tags=["Products"],
        summary="Get color variant",
        responses={200: ColorVariantDetailSerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Products"],
        summary="Add color variant",
        description="Adds a color variant to a product, with optional nested `sizes`.",
        responses={
            201: ColorVariantDetailSerializer,
            400: RESPONSE_400,
            404: RESPONSE_404,
        },
    ),
    destroy=extend_schema(
        tags=["Products"],
        summary="Deactivate color variant",
        description="Mark a variant inactive (soft). Returns 204.",
        responses={204: None, 404: RESPONSE_404},
    ),
)
class ColorVariantViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)

    def get_permissions(self):
        if self.action == "list":
            permission_classes = [IsCompanyStaff]
        elif self.action == "retrieve":
            permission_classes = [IsCompanyStaff]
        elif self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrSubAdmin]
        else:
            permission_classes = [IsAdminOrSubAdmin]

        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "create":
            return ColorVariantCreateSerializer
        if self.action == "retrieve":
            return ColorVariantDetailSerializer
        return ColorVariantListSerializer

    def _get_company(self, request):
        return request.company or request.user.company

    def _get_product(self, product_pk, company):
        try:
            return Product.objects.get(pk=product_pk, company=company, is_deleted=False)
        except Product.DoesNotExist:
            return None

    # GET /api/products/<product_pk>/variants/
    def list(self, request, product_pk=None):
        company = self._get_company(request)
        product = self._get_product(product_pk, company)
        if not product:
            return Response(
                {"detail": "Product not found."}, status=status.HTTP_404_NOT_FOUND
            )
        qs = ColorVariant.objects.filter(product=product).prefetch_related("sizes")
        return Response(ColorVariantListSerializer(qs, many=True).data)

    # GET /api/products/<product_pk>/variants/<pk>/
    def retrieve(self, request, product_pk=None, pk=None):
        company = self._get_company(request)
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
        company = self._get_company(request)
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
        company = self._get_company(request)
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


@extend_schema_view(
    list=extend_schema(
        tags=["Stock"],
        summary="Stock movement ledger",
        description="Recent stock movements (last 200), newest first.",
        responses={200: StockMovementSerializer(many=True)},
    ),
    adjust=extend_schema(
        tags=["Stock"],
        summary="Adjust stock manually",
        description=(
            "Adds or removes quantity on a variant size (`quantity` positive to "
            "add, negative to remove). Denied if removal exceeds available stock. "
            "Writes a `StockMovement` ledger entry and recomputes product totals."
        ),
        responses={
            200: VariantSizeSerializer,
            400: RESPONSE_400,
        },
    ),
)
class StockViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)

    def get_permissions(self):
        if self.action == "list":
            permission_classes = [IsCompanyStaff]
        elif self.action == "retrieve":
            permission_classes = [IsCompanyStaff]
        elif self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsAdminOrSubAdmin]
        else:
            permission_classes = [IsAdminOrSubAdmin]

        return [permission() for permission in permission_classes]

    def get_serializer_class(self):
        if self.action == "adjust":
            return StockAdjustmentSerializer
        return StockMovementSerializer

    def _get_company(self, request):
        return request.company or request.user.company

    # GET /api/stock/movements/
    def list(self, request):
        company = self._get_company(request)
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
    @action(detail=False, methods=["post"])
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
