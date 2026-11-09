# Product Catalog API — VariantSize listing + stock overview

## Objective
Add two read endpoints to the existing `ProductViewSet` (additive; legacy `/api/products/` untouched):

1. `GET /api/products/catalog/` — paginated, filterable, safely-orderable **VariantSize-based rows** for the management page.
2. `GET /api/products/overview/` — `{stock_valuation, total_products, low_stock_variants, out_of_stock_variants}`.

### Locked decisions
- **Valuation formula (definitive):** `Σ(stock_quantity × Coalesce(price_override, wholesale_price))`. Rationale: orders already sell at `price_override or wholesale_price` (orders/views.py:88), so valuation reflects actual selling value.
- **Valuation scope:** everything non-deleted — all product statuses, active *and* inactive variants/sizes (total owned-inventory value).
- **Out-of-stock rule:** `available_qty <= 0` (nothing sellable, even if physical units exist but are fully reserved). Low-stock is strictly `0 < available_qty <= reorder_level` — deliberately narrower than the dashboard's `low_stock_items`, which lumps OOS into low-stock.
- **Listing display quantity:** `available_qty = max(0, stock_quantity - reserved_qty)` (operational "what can we still sell"). Reserved is a subset of on-hand — never added.
- **Price per unit display:** `price_override or product.wholesale_price`; MRP not used.
- **Pagination:** shared `DefaultPageNumberPagination` (default 20, `page_size` ≤ 100), same envelope as customers: `{count, next, previous, results}`.

### Environment constraints carried over from customers work
- Django 4.2.24, SQLite dev/test DB.
- Annotation aliases must NOT shadow real model fields → computed names prefixed `computed_*` / `effective_*`.
- No lint/typecheck configs exist in repo.

## Files to touch (4)
1. `apps/products/serializers.py` — add 2 serializers
2. `apps/products/views.py` — ProductViewSet additions + remove dead featured filter
3. `apps/products/urls.py` — 2 new paths + fix stale comments
4. `apps/products/tests/` — new package (`__init__.py`, `test_catalog_api.py`)

No model/migration changes.

---

## Step 1 — Serializers

### `ProductOverviewSerializer(serializers.Serializer)`
```python
stock_valuation = DecimalField(max_digits=14, decimal_places=2)   # str in JSON, e.g. "2450000.00"
total_products = IntegerField()
low_stock_variants = IntegerField()
out_of_stock_variants = IntegerField()
```
Instantiated with a plain dict from the view (same pattern as `CustomerOverviewSerializer`).

### `CatalogVariantSerializer(serializers.ModelSerializer)` (model=VariantSize)
Fields:
| Field | Source |
|---|---|
| `id`, `sku`, `size`, `stock_quantity`, `reserved_qty`, `reorder_level` | direct |
| `product_id` | `color_variant.product.id` |
| `product_name` | `color_variant.product.name` |
| `category_name` | `color_variant.product.category.name` |
| `color` | `color_variant.color_name` |
| `image` | SerializerMethodField — absolute URL of `color_variant.image` (reuse the `get_primary_image` URI-building pattern; null-safe) |
| `price_per_unit` | SerializerMethodField — prefer annotated `effective_price`, fallback `obj.price_override or obj.color_variant.product.wholesale_price`; quantize to 2dp |
| `available_qty` | IntegerField read_only → model property products/models.py:157 |
| `is_low_stock` | BooleanField read_only → model property products/models.py:161 |

Python properties are fine for row *display*; SQL annotations (below) power filtering/ordering with non-clashing names.

---

## Step 2 — ProductViewSet

New class attrs:
```python
pagination_class = DefaultPageNumberPagination   # inert for legacy list() (hand-rolled Response)

ORDERING_FIELDS = {"product_name", "sku", "available_qty", "stock_quantity",
                   "price_per_unit", "created_at"}
ORDERING_MAP = {
    "product_name": "color_variant__product__name",
    "sku": "sku",
    "available_qty": "computed_available",
    "stock_quantity": "stock_quantity",
    "price_per_unit": "effective_price",
    "created_at": "created_at",
}
```

Shared queryset builder `_catalog_qs(company)`:
```python
VariantSize.objects.filter(
    color_variant__product__company=company,
    color_variant__product__is_deleted=False,
).select_related("color_variant__product__category", "color_variant").annotate(
    effective_price=Coalesce("price_override",
        "color_variant__product__wholesale_price",
        output_field=DecimalField(max_digits=10, decimal_places=2)),
    computed_available=Greatest(F("stock_quantity") - F("reserved_qty"), Value(0)),
)
```
(`Greatest` compiles to `MAX()` on SQLite — safe in Django 4.2.)

### `catalog` action (`@action(detail=False, methods=["get"], url_path="catalog")`)
Filters, all DB-side:
- `search=` → `Q(product name icontains) | Q(sku icontains) | Q(color_name icontains)`
- `category=<uuid>` → `color_variant__product__category_id`
- `status=<active|inactive|discontinued>` → `color_variant__product__status` (no default filter — all statuses listed unless asked)
- `size=<str>` → `size__iexact`
- `color=<str>` → `color_variant__color_name__iexact`
- `low_stock=true` → `computed_available__gt=Value(0)` AND `computed_available__lte=F("reorder_level")` (excludes OOS by definition)
- `out_of_stock=true` → `computed_available__lte=Value(0)`

Ordering: parse `?ordering=`, strip leading `-`, whitelist via ORDERING_MAP, re-apply `-` after mapping, fallback `-created_at` (mirror customers implementation).

Respond via `self.paginate_queryset(qs)` + `self.get_paginated_response(serializer.data)`.

Row shape (matches user's spec plus link keys):
```json
{
  "id": "...", "image": null, "sku": "TSHIRT-BLACK-M",
  "product_id": "...", "product_name": "Classic T-Shirt",
  "category_name": "Men", "color": "Black", "size": "M",
  "price_per_unit": "450.00",
  "stock_quantity": 100, "reserved_qty": 20, "available_qty": 80,
  "reorder_level": 10, "is_low_stock": false
}
```

### `overview` action (`@action(detail=False, methods=["get"], url_path="overview")`)
On the same `_catalog_qs(company)` annotations:
```python
line_value = ExpressionWrapper(F("stock_quantity") * F("effective_price"),
                               output_field=DecimalField(max_digits=14, decimal_places=2))
agg = qs.aggregate(stock_valuation=Coalesce(Sum(line_value), Value(Decimal("0.00")),
                                            output_field=DecimalField(max_digits=14, decimal_places=2)))
low = qs.filter(computed_available__gt=Value(0), computed_available__lte=F("reorder_level")).count()
oos = qs.filter(computed_available__lte=Value(0)).count()
total_products = Product.objects.filter(company=company, is_deleted=False).count()
return Response(ProductOverviewSerializer({...}).data)
```
Quantize `stock_valuation` to 2dp before serializing. Same scope as valuation decision (all statuses/activity levels).

Permissions/auth: inherited from ProductViewSet (`IsAdminOrSubAdmin`) — consistent with the rest of the app.

---

## Step 3 — URLs (`apps/products/urls.py`)
Register before the `<uuid:pk>` path (cosmetic; uuid converter can't capture "catalog"/"overview" anyway):
```python
path("products/catalog/",  ProductViewSet.as_view({"get": "catalog"}),  name="product-catalog"),
path("products/overview/", ProductViewSet.as_view({"get": "overview"}), name="product-overview"),
```
Update stale PRODUCTS comment block.

---

## Step 4 — Dead-code cleanup in legacy list() (safe)
Remove `featured` param handling (products/views.py:205-206, 212-213): `?featured=` crashes today with FieldError because `Product.is_featured` doesn't exist — no working consumer can depend on it. Also drop nonexistent toggle-featured/images lines from urls.py comments (lines 70-71). Everything else in legacy list stays byte-for-byte (raw array shape preserved).

---

## Step 5 — Tests (`apps/products/tests/`)
New package: `tests/__init__.py`, `tests/test_catalog_api.py` (accounts-factories style helpers; local `create_variant(...)` helper building Product→ColorVariant→VariantSize).

Coverage:
- **Auth/scoping**: unauthenticated → 401; agent role → 403; other company's variants invisible (list + overview).
- **Rows**: exact field set; `price_per_unit` falls back to wholesale when override null; override honored; `image` null-safe; `available_qty = stock - reserved` floored at 0.
- **Boundaries**: `available == reorder_level` → `is_low_stock=true`; `== reorder_level+1` → false; fully-reserved size (available 0) flagged out_of_stock, NOT low_stock.
- **Filters**: search by sku/color/product-name; category; size; status; `low_stock=true` excludes OOS rows.
- **Ordering**: `-available_qty` correct order; invalid value falls back to `-created_at`.
- **Pagination**: envelope keys {count,next,previous,results}; default page size 20.
- **Overview**: valuation math with mixed overrides (e.g., 100@500 plain + 50@75 override ⇒ "53750.00"); empty company ⇒ zeroes `"0.00"`/0; inactive variant's stock STILL counted in valuation (scope decision); low/OOS counts; total_products counts all non-deleted statuses.
- **Legacy regression**: `/api/products/` still returns raw array; `?featured=` no longer present/crashing.

## Verification
1. `python manage.py test apps.products`
2. Full `python manage.py test` (107 baseline must stay green)
3. Confirm no lint/typecheck configs (already established none exist)

## Out-of-scope flags (report only)
- `Product.total_stock` denorm drifts: dispatch (dispatch/views.py:106) decrements sizes but never recomputes `total_stock` (only create + manual adjust do). Same family as customer `total_outstanding` sync gap.
- Dashboard `low_stock_items` (accounts/views.py:675-678) doesn't exclude soft-deleted products and lumps OOS into low-stock — new endpoints intentionally stricter; consider aligning later.
