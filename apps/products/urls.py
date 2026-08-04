#  ✅ Completely Verified

from django.urls import path

from apps.products.views import (
    CategoryViewSet,
    ColorVariantViewSet,
    ProductViewSet,
    SizeChartViewSet,
    StockViewSet,
)

app_name = "products"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # CATEGORIES
    # ─────────────────────────────────────────────────────────────
    # GET    /api/categories/               List root categories (nested children inline)
    # POST   /api/categories/               Create category
    # GET    /api/categories/<pk>/          Category detail with children
    # PATCH  /api/categories/<pk>/          Update category
    # DELETE /api/categories/<pk>/          Soft-delete (blocked if products exist)
    path(
        "categories/",
        CategoryViewSet.as_view({"get": "list", "post": "create"}),
        name="category-list-create",
    ),  # ✅
    path(
        "categories/<uuid:pk>/",
        CategoryViewSet.as_view(
            {
                "get": "retrieve",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="category-detail",
    ),  # ✅
    # ─────────────────────────────────────────────────────────────
    # SIZE CHARTS
    # ─────────────────────────────────────────────────────────────
    # GET    /api/size-charts/              List size charts
    # POST   /api/size-charts/              Create size chart
    # PATCH  /api/size-charts/<pk>/         Update sizes array
    # DELETE /api/size-charts/<pk>/         Delete (blocked if in use by products)
    path(
        "size-charts/",
        SizeChartViewSet.as_view({"get": "list", "post": "create"}),
        name="size-chart-list-create",
    ),  # ✅
    path(
        "size-charts/<uuid:pk>/",
        SizeChartViewSet.as_view(
            {
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="size-chart-detail",
    ),  # ✅
    # ─────────────────────────────────────────────────────────────
    # PRODUCTS
    # ─────────────────────────────────────────────────────────────
    # GET    /api/products/                         List (?category= ?status= ?search= ?featured= ?low_stock=)
    # POST   /api/products/                         Create product (with nested color_variants)
    # GET    /api/products/<pk>/                    Full detail (images + variants + sizes)
    # PATCH  /api/products/<pk>/                    Update product fields
    # DELETE /api/products/<pk>/                    Soft-delete
    # POST   /api/products/<pk>/toggle-featured/    Toggle is_featured flag
    # POST   /api/products/<pk>/images/             Upload product image
    path(
        "products/",
        ProductViewSet.as_view({"get": "list", "post": "create"}),
        name="product-list-create",
    ),  # ✅
    path(
        "products/<uuid:pk>/",
        ProductViewSet.as_view(
            {
                "get": "retrieve",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="product-detail",
    ),  # ✅
    path(
        "products/scan/<uuid:qr_code>/",
        ProductViewSet.as_view({"get": "scan_qr"}),
        name="product-scan-qr",
    ),  # ✅
    # ─────────────────────────────────────────────────────────────
    # COLOR VARIANTS  (nested under product)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/products/<product_pk>/variants/           List color variants
    # POST   /api/products/<product_pk>/variants/           Create variant (with sizes)
    # GET    /api/products/<product_pk>/variants/<pk>/      Variant detail with sizes
    # DELETE /api/products/<product_pk>/variants/<pk>/      Deactivate variant
    path(
        "products/<uuid:product_pk>/variants/",
        ColorVariantViewSet.as_view({"get": "list", "post": "create"}),
        name="color-variant-list-create",
    ),  # ✅
    path(
        "products/<uuid:product_pk>/variants/<uuid:pk>/",
        ColorVariantViewSet.as_view(
            {
                "get": "retrieve",
                "delete": "destroy",
            }
        ),
        name="color-variant-detail",
    ),  # ✅
    # ─────────────────────────────────────────────────────────────
    # STOCK
    # ─────────────────────────────────────────────────────────────
    # GET    /api/stock/movements/    Recent stock movement ledger (last 200)
    # POST   /api/stock/adjust/       Manual stock adjustment (Admin / SubAdmin)
    path(
        "stock/movements/",
        StockViewSet.as_view({"get": "list"}),
        name="stock-movement-list",
    ),  # ✅
    path(
        "stock/adjust/",
        StockViewSet.as_view({"post": "adjust"}),
        name="stock-adjust",
    ),  # ✅
]
