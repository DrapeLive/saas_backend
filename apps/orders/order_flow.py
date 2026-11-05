"""Business logic for the agent draft-order flow.

This module is the single source of truth used by both the REST views and the
WebSocket consumer. Keeping stock reservation, size-range resolution and draft
lifecycle here guarantees that both transports behave identically.
"""

import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils.timezone import now

from apps.customers.models import CustomerProfile
from apps.orders.exceptions import OrderFlowError
from apps.orders.models import (
    Order,
    OrderItem,
    OrderSequence,
    OrderStatus,
    OrderStatusHistory,
)
from apps.products.models import ColorVariant, StockMovement, VariantSize

DRAFT_TTL_SECONDS = getattr(settings, "ORDER_DRAFT_TTL_SECONDS", 2700)
EMPTY_DRAFT_TTL_SECONDS = getattr(settings, "ORDER_EMPTY_DRAFT_TTL_SECONDS", 2700)

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _company_settings(company):
    return getattr(company, "settings", None)


def _gst_rate(company):
    settings_obj = _company_settings(company)
    value = getattr(settings_obj, "default_gst_rate", None)
    if value in (None, ""):
        return Decimal("5.00")
    return Decimal(str(value))


def _is_interstate(company_state, customer_state):
    if not company_state or not customer_state:
        return False
    return company_state.strip().lower() != customer_state.strip().lower()


def _draft_ttl_for(order):
    return DRAFT_TTL_SECONDS if order.items.exists() else EMPTY_DRAFT_TTL_SECONDS


def _set_draft_expiry(order):
    order.draft_expires_at = now() + timedelta(seconds=_draft_ttl_for(order))


def refresh_draft_expiry(order):
    """Public helper for views that update draft metadata."""
    _set_draft_expiry(order)


def _log_status(order, from_status, to_status, user=None, notes=""):
    OrderStatusHistory.objects.create(
        order=order,
        from_status=from_status,
        to_status=to_status,
        changed_by=user,
        notes=notes,
    )


def _decimal(value, field="value", default=ZERO):
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OrderFlowError(
            f"{field} must be a valid number.",
            code="INVALID_NUMBER",
            fields={field: "Invalid number."},
        ) from exc


def next_order_number(company):
    """Allocate the next order number, serialized per company.

    Locks the company row so concurrent drafts cannot receive the same number.
    """
    with transaction.atomic():
        type(company).objects.select_for_update().get(pk=company.pk)
        year = now().year
        sequence, _ = OrderSequence.objects.get_or_create(
            company=company,
            year=year,
            defaults={"last_number": 0},
        )
        if sequence.last_number == 0:
            prefix = f"ORD-{year}-"
            existing = Order.objects.filter(
                company=company, order_number__startswith=prefix
            ).values_list("order_number", flat=True)
            for number in existing:
                try:
                    sequence.last_number = max(
                        sequence.last_number, int(number.rsplit("-", 1)[1])
                    )
                except (IndexError, TypeError, ValueError):
                    continue
        sequence.last_number += 1
        sequence.save(update_fields=["last_number", "updated_at"])
        return f"ORD-{year}-{sequence.last_number:05d}"


def get_agent_order(order_id, company, agent):
    try:
        order = (
            Order.objects.select_related("customer", "agent__user", "company")
            .prefetch_related("items")
            .get(pk=order_id, company=company)
        )
    except (Order.DoesNotExist, ValueError, ValidationError):
        raise OrderFlowError(
            "Order not found.", code="ORDER_NOT_FOUND", status_code=404
        ) from None
    if agent is not None and order.agent_id != agent.id:
        raise OrderFlowError(
            "Order not found.", code="ORDER_NOT_FOUND", status_code=404
        )
    return order


def _lock_order(order):
    """Reload and lock an order so concurrent mutations serialize."""
    return (
        Order.objects.select_for_update(of=("self",))
        .select_related("company", "customer", "agent__user")
        .get(pk=order.pk)
    )


def _require_draft(order):
    if order.status != OrderStatus.DRAFT:
        raise OrderFlowError(
            "Only DRAFT orders can be modified.",
            code="ORDER_NOT_DRAFT",
            fields={"status": order.status},
        )
    if order.draft_expires_at and order.draft_expires_at <= now():
        raise OrderFlowError(
            "This draft order has expired.",
            code="DRAFT_EXPIRED",
            fields={"draft_expires_at": "The draft expiration time has passed."},
            status_code=409,
        )


def assert_draft_available(order):
    """Validate that a draft can still be opened or mutated."""
    _require_draft(order)


# ---------------------------------------------------------------------------
# Draft creation / listing
# ---------------------------------------------------------------------------


@transaction.atomic
def create_draft_order(company, agent, user, payload):
    customer_id = payload.get("customer") or payload.get("customer_id")
    if not customer_id:
        raise OrderFlowError(
            "Customer is required.",
            code="CUSTOMER_REQUIRED",
            fields={"customer": "This field is required."},
        )

    try:
        customer = CustomerProfile.objects.get(id=customer_id, company=company)
    except (CustomerProfile.DoesNotExist, ValueError, ValidationError):
        raise OrderFlowError(
            "Customer not found.",
            code="CUSTOMER_NOT_FOUND",
            fields={"customer": "Customer not found."},
            status_code=404,
        ) from None

    if customer.status == CustomerProfile.CustomerStatus.BLOCKED or customer.is_credit_blocked:
        raise OrderFlowError(
            "Customer is blocked due to credit limit. Resolve outstanding before placing an order.",
            code="CUSTOMER_BLOCKED",
            fields={"customer": "Customer is blocked."},
        )

    order = Order.objects.create(
        company=company,
        order_number=next_order_number(company),
        customer=customer,
        agent=agent,
        status=OrderStatus.DRAFT,
        delivery_address_line1=payload.get("delivery_address_line1", ""),
        delivery_address_line2=payload.get("delivery_address_line2", ""),
        delivery_city=payload.get("delivery_city", ""),
        delivery_state=payload.get("delivery_state", ""),
        delivery_pincode=payload.get("delivery_pincode", ""),
        expected_delivery_date=payload.get("expected_delivery_date") or None,
        order_notes=payload.get("order_notes", ""),
        discount_pct=_decimal(payload.get("discount_pct"), "discount_pct"),
        is_offline_order=bool(payload.get("is_offline_order", False)),
        offline_created_at=payload.get("offline_created_at") or None,
        draft_expires_at=now() + timedelta(seconds=EMPTY_DRAFT_TTL_SECONDS),
    )
    _log_status(order, "", OrderStatus.DRAFT, user, "Draft created")
    return order


def list_draft_orders(company, agent):
    return (
        Order.objects.filter(
            company=company,
            agent=agent,
            status=OrderStatus.DRAFT,
        )
        .select_related("customer", "agent__user")
        .prefetch_related("items")
        .order_by("-updated_at")
    )


# ---------------------------------------------------------------------------
# Size resolution
# ---------------------------------------------------------------------------


def _order_creation_maps(product):
    chart = getattr(product, "size_chart", None)
    if not chart or not isinstance(chart.sizes, list):
        return []
    maps = []
    for entry in chart.sizes:
        if isinstance(entry, dict):
            mapping = entry.get("order_creation")
            if isinstance(mapping, dict) and mapping:
                maps.append(mapping)
    return maps


def resolve_range_sizes(product, size_range):
    maps = _order_creation_maps(product)
    if not maps:
        raise OrderFlowError(
            "This product has no order size chart configured.",
            code="SIZE_CHART_MISSING",
            fields={"size_range": "No order size chart for this product."},
        )

    allowed = sorted({key for mapping in maps for key in mapping})
    for mapping in maps:
        sizes = mapping.get(size_range)
        if isinstance(sizes, list) and sizes:
            return [str(size) for size in sizes]

    raise OrderFlowError(
        f"'{size_range}' is not a valid size range for this product.",
        code="INVALID_SIZE_RANGE",
        fields={"size_range": allowed},
    )


def _fetch_variant_sizes(color_variant, sizes):
    variant_sizes = list(
        VariantSize.objects.select_related(
            "color_variant__product__category",
            "color_variant__product__size_chart",
        ).filter(color_variant=color_variant, size__in=sizes)
    )
    by_size = {variant.size: variant for variant in variant_sizes}
    missing = [size for size in sizes if size not in by_size]
    if missing:
        raise OrderFlowError(
            f"Sizes not found for this item: {', '.join(missing)}.",
            code="VARIANT_SIZE_MISSING",
            fields={"size_range": f"Missing sizes: {', '.join(missing)}"},
        )
    return [by_size[size] for size in sizes]


def _resolve_scan_payload(order, payload):
    """Return (color_variant, sizes, size_range, quantity, discount_pct, client_ref)."""
    quantity = payload.get("quantity")
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise OrderFlowError(
            "Quantity must be a whole number.",
            code="INVALID_QUANTITY",
            fields={"quantity": "Enter a whole number."},
        ) from None
    if quantity < 1:
        raise OrderFlowError(
            "Quantity must be at least 1.",
            code="INVALID_QUANTITY",
            fields={"quantity": "Must be at least 1."},
        )

    discount_pct = _decimal(payload.get("discount_pct"), "discount_pct")
    client_ref = str(payload.get("client_ref") or "").strip()

    qr_code = payload.get("qr_code")
    color_variant_id = payload.get("color_variant") or payload.get("color_variant_id")
    variant_size_id = payload.get("variant_size") or payload.get("variant_size_id")

    if variant_size_id and not payload.get("size_range"):
        try:
            variant = VariantSize.objects.select_related(
                "color_variant__product__size_chart",
                "color_variant__product__category",
            ).get(pk=variant_size_id, color_variant__product__company=order.company)
        except (VariantSize.DoesNotExist, ValueError, ValidationError):
            raise OrderFlowError(
                "Item not found.",
                code="VARIANT_NOT_FOUND",
                status_code=404,
            ) from None
        return (
            variant.color_variant,
            [variant],
            "",
            quantity,
            discount_pct,
            client_ref,
        )

    try:
        if qr_code:
            color_variant = ColorVariant.objects.select_related(
                "product__size_chart", "product__category"
            ).get(qr_code=qr_code, product__company=order.company)
        elif color_variant_id:
            color_variant = ColorVariant.objects.select_related(
                "product__size_chart", "product__category"
            ).get(pk=color_variant_id, product__company=order.company)
        else:
            raise OrderFlowError(
                "Scan an item first.",
                code="ITEM_REQUIRED",
                fields={"qr_code": "Provide qr_code, color_variant or variant_size."},
            )
    except (ColorVariant.DoesNotExist, ValueError, ValidationError):
        raise OrderFlowError(
            "Scanned item not found.",
            code="VARIANT_NOT_FOUND",
            status_code=404,
        ) from None

    size_range = str(payload.get("size_range") or "").strip()
    if not size_range:
        raise OrderFlowError(
            "Size range is required.",
            code="SIZE_RANGE_REQUIRED",
            fields={"size_range": "Select a size range."},
        )

    sizes = resolve_range_sizes(color_variant.product, size_range)
    variant_sizes = _fetch_variant_sizes(color_variant, sizes)
    return color_variant, variant_sizes, size_range, quantity, discount_pct, client_ref


# ---------------------------------------------------------------------------
# Stock reservation / release
# ---------------------------------------------------------------------------


def _release_variants(quantities, user=None, reference_id=None, reason=""):
    """Release reserved quantities. ``quantities`` maps variant id -> qty."""
    updates = []
    if not quantities:
        return updates

    ordered_ids = sorted(quantities, key=lambda value: str(value))
    locked = {
        variant.id: variant
        for variant in VariantSize.objects.select_for_update()
        .filter(pk__in=ordered_ids)
        .order_by("pk")
    }
    for variant_id in ordered_ids:
        qty = quantities[variant_id]
        if qty <= 0:
            continue
        variant = locked.get(variant_id)
        if variant is None:
            continue
        VariantSize.objects.filter(pk=variant_id).update(
            reserved_qty=Greatest(F("reserved_qty") - qty, Value(0))
        )
        variant.refresh_from_db(fields=["stock_quantity", "reserved_qty"])
        StockMovement.objects.create(
            variant_size=variant,
            movement_type=StockMovement.MovementType.RELEASE,
            quantity=qty,
            balance_after=variant.available_qty,
            reference_type="order",
            reference_id=reference_id,
            reason=reason,
            performed_by=user,
        )
        updates.append(
            {
                "variant_size_id": str(variant.id),
                "size": variant.size,
                "stock_quantity": variant.stock_quantity,
                "reserved_qty": variant.reserved_qty,
                "available_qty": variant.available_qty,
            }
        )
    return updates


def _release_order_items(items, user=None, reference_id=None, reason=""):
    quantities = {}
    for item in items:
        quantities[item.variant_size_id] = (
            quantities.get(item.variant_size_id, 0) + item.quantity
        )
    return _release_variants(
        quantities, user=user, reference_id=reference_id, reason=reason
    )


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def recalculate_order_totals(order):
    company = order.company
    customer = order.customer

    subtotal = ZERO
    gst_total = ZERO
    for item in order.items.select_related(
        "variant_size__color_variant__product__category"
    ):
        line_total = item.line_total or ZERO
        subtotal += line_total
        gst_total += item.gst_amount or ZERO

    discount_pct = order.discount_pct or ZERO
    discount_amount = (subtotal * discount_pct / Decimal(100)).quantize(
        Decimal("0.01")
    )
    taxable = subtotal - discount_amount
    is_interstate = _is_interstate(company.state, customer.billing_state)
    if is_interstate:
        cgst = sgst = ZERO
        igst = gst_total
    else:
        cgst = sgst = (gst_total / 2).quantize(Decimal("0.01"))
        igst = ZERO
    total = taxable + gst_total

    order.subtotal = subtotal
    order.discount_amount = discount_amount
    order.taxable_amount = taxable
    order.cgst_amount = cgst
    order.sgst_amount = sgst
    order.igst_amount = igst
    order.total_amount = total
    order.is_interstate = is_interstate
    order.save(
        update_fields=[
            "subtotal",
            "discount_amount",
            "taxable_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_amount",
            "is_interstate",
            "updated_at",
        ]
    )
    return order


def _build_order_item(
    order, variant, group_id, size_range, quantity, discount_pct, client_ref
):
    product = variant.color_variant.product
    unit_price = variant.price_override or product.wholesale_price or ZERO
    line_total = (
        unit_price
        * quantity
        * (Decimal(1) - discount_pct / Decimal(100))
    ).quantize(Decimal("0.01"))
    gst_rate = _gst_rate(order.company)
    gst_amount = (line_total * gst_rate / Decimal(100)).quantize(Decimal("0.01"))
    return OrderItem(
        order=order,
        variant_size=variant,
        group_id=group_id,
        size_range=size_range,
        client_ref=client_ref,
        product_name=product.name,
        color_name=variant.color_variant.color_name,
        size=variant.size,
        sku=variant.sku,
        hsn_code=product.category.hsn_code,
        unit_price=unit_price,
        quantity=quantity,
        discount_pct=discount_pct,
        line_total=line_total,
        gst_rate=gst_rate,
        gst_amount=gst_amount,
    )


# ---------------------------------------------------------------------------
# Add / remove / update items
# ---------------------------------------------------------------------------


@transaction.atomic
def add_item_to_draft(order, user, payload):
    order = _lock_order(order)
    _require_draft(order)
    (
        _color_variant,
        variant_sizes,
        size_range,
        quantity,
        discount_pct,
        client_ref,
    ) = _resolve_scan_payload(order, payload)

    if client_ref:
        existing = order.items.filter(client_ref=client_ref).first()
        if existing:
            return order, existing.group_id, [], False

    quantities = {variant.id: quantity for variant in variant_sizes}
    ordered_ids = sorted(quantities, key=lambda value: str(value))
    locked = {
        variant.id: variant
        for variant in VariantSize.objects.select_for_update()
        .select_related("color_variant__product__category")
        .filter(pk__in=ordered_ids)
        .order_by("pk")
    }

    insufficient = []
    for variant_id in ordered_ids:
        variant = locked.get(variant_id)
        if variant is None:
            raise OrderFlowError(
                "Item not found.", code="VARIANT_NOT_FOUND", status_code=404
            )
        if variant.available_qty < quantity:
            insufficient.append(
                {
                    "variant_size_id": str(variant.id),
                    "size": variant.size,
                    "requested": quantity,
                    "available": variant.available_qty,
                }
            )
    if insufficient:
        raise OrderFlowError(
            "Insufficient stock for the selected size range.",
            code="INSUFFICIENT_STOCK",
            fields={"items": insufficient},
            status_code=409,
        )

    group_id = uuid.uuid4()
    stock_updates = []
    for variant_id in ordered_ids:
        variant = locked[variant_id]
        item = _build_order_item(
            order,
            variant,
            group_id,
            size_range,
            quantity,
            discount_pct,
            client_ref,
        )
        item.save()

        VariantSize.objects.filter(pk=variant_id).update(
            reserved_qty=F("reserved_qty") + quantity
        )
        variant.refresh_from_db(fields=["stock_quantity", "reserved_qty"])
        StockMovement.objects.create(
            variant_size=variant,
            movement_type=StockMovement.MovementType.RESERVE,
            quantity=-quantity,
            balance_after=variant.available_qty,
            reference_type="order",
            reference_id=order.id,
            performed_by=user,
        )
        stock_updates.append(
            {
                "variant_size_id": str(variant.id),
                "size": variant.size,
                "stock_quantity": variant.stock_quantity,
                "reserved_qty": variant.reserved_qty,
                "available_qty": variant.available_qty,
            }
        )

    recalculate_order_totals(order)
    _set_draft_expiry(order)
    order.save(update_fields=["draft_expires_at", "updated_at"])
    return order, group_id, stock_updates, True


@transaction.atomic
def remove_item_from_draft(order, user, item_id, scope="group"):
    order = _lock_order(order)
    _require_draft(order)
    try:
        item = order.items.get(pk=item_id)
    except (OrderItem.DoesNotExist, ValueError, ValidationError):
        raise OrderFlowError(
            "Order item not found.", code="ITEM_NOT_FOUND", status_code=404
        ) from None

    if scope == "single" or not item.group_id:
        items = [item]
    else:
        items = list(order.items.filter(group_id=item.group_id))

    stock_updates = _release_order_items(
        items,
        user=user,
        reference_id=order.id,
        reason="Removed from draft order",
    )
    OrderItem.objects.filter(pk__in=[entry.pk for entry in items]).delete()

    recalculate_order_totals(order)
    if not order.items.exists():
        order_pk = order.pk
        order.delete()
        # Keep a lightweight deleted snapshot usable by callers that broadcast
        # the update or serialize the final empty state.
        order.pk = order_pk
        return order, stock_updates

    _set_draft_expiry(order)
    order.save(update_fields=["draft_expires_at", "updated_at"])
    return order, stock_updates


@transaction.atomic
def update_item_quantity(order, user, item_id, quantity):
    order = _lock_order(order)
    _require_draft(order)
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise OrderFlowError(
            "Quantity must be a whole number.",
            code="INVALID_QUANTITY",
            fields={"quantity": "Enter a whole number."},
        ) from None
    if quantity < 1:
        raise OrderFlowError(
            "Quantity must be at least 1.",
            code="INVALID_QUANTITY",
            fields={"quantity": "Must be at least 1."},
        )

    try:
        item = order.items.get(pk=item_id)
    except (OrderItem.DoesNotExist, ValueError, ValidationError):
        raise OrderFlowError(
            "Order item not found.", code="ITEM_NOT_FOUND", status_code=404
        ) from None

    items = (
        list(order.items.filter(group_id=item.group_id))
        if item.group_id
        else [item]
    )
    deltas = {}
    for entry in items:
        deltas[entry.variant_size_id] = deltas.get(entry.variant_size_id, 0) + (
            quantity - entry.quantity
        )

    ordered_ids = sorted(deltas, key=lambda value: str(value))
    locked = {
        variant.id: variant
        for variant in VariantSize.objects.select_for_update()
        .filter(pk__in=ordered_ids)
        .order_by("pk")
    }
    insufficient = []
    for variant_id in ordered_ids:
        delta = deltas[variant_id]
        if delta <= 0:
            continue
        variant = locked[variant_id]
        if variant.available_qty < delta:
            insufficient.append(
                {
                    "variant_size_id": str(variant.id),
                    "size": variant.size,
                    "requested": delta,
                    "available": variant.available_qty,
                }
            )
    if insufficient:
        raise OrderFlowError(
            "Insufficient stock to increase this quantity.",
            code="INSUFFICIENT_STOCK",
            fields={"items": insufficient},
            status_code=409,
        )

    stock_updates = []
    for entry in items:
        old_qty = entry.quantity
        entry.quantity = quantity
        entry.line_total = (
            entry.unit_price
            * quantity
            * (Decimal(1) - entry.discount_pct / Decimal(100))
        ).quantize(Decimal("0.01"))
        entry.gst_amount = (
            entry.line_total * entry.gst_rate / Decimal(100)
        ).quantize(Decimal("0.01"))
        entry.save(
            update_fields=[
                "quantity",
                "line_total",
                "gst_amount",
                "updated_at",
            ]
        )
        delta = quantity - old_qty
        if delta == 0:
            continue
        variant_id = entry.variant_size_id
        variant = locked[variant_id]
        if delta > 0:
            VariantSize.objects.filter(pk=variant_id).update(
                reserved_qty=F("reserved_qty") + delta
            )
            movement = StockMovement.MovementType.RESERVE
        else:
            VariantSize.objects.filter(pk=variant_id).update(
                reserved_qty=Greatest(F("reserved_qty") + delta, Value(0))
            )
            movement = StockMovement.MovementType.RELEASE
        variant.refresh_from_db(fields=["stock_quantity", "reserved_qty"])
        StockMovement.objects.create(
            variant_size=variant,
            movement_type=movement,
            quantity=-delta if delta > 0 else abs(delta),
            balance_after=variant.available_qty,
            reference_type="order",
            reference_id=order.id,
            performed_by=user,
        )
        stock_updates.append(
            {
                "variant_size_id": str(variant.id),
                "size": variant.size,
                "stock_quantity": variant.stock_quantity,
                "reserved_qty": variant.reserved_qty,
                "available_qty": variant.available_qty,
            }
        )

    recalculate_order_totals(order)
    _set_draft_expiry(order)
    order.save(update_fields=["draft_expires_at", "updated_at"])
    return order, stock_updates


# ---------------------------------------------------------------------------
# Submit / discard / expiry
# ---------------------------------------------------------------------------


def _check_credit(order, user):
    company = order.company
    settings_obj = _company_settings(company)
    if not settings_obj or not getattr(settings_obj, "credit_block_on_exceed", False):
        return

    customer = order.customer
    total = order.total_amount
    if customer.credit_limit > 0 and customer.credit_utilized + total > customer.credit_limit:
        raise OrderFlowError(
            (
                f"Order total ₹{total} would exceed {customer.trade_name}'s "
                f"credit limit of ₹{customer.credit_limit}."
            ),
            code="CUSTOMER_CREDIT_EXCEEDED",
            fields={"customer": "Credit limit exceeded."},
        )

    agent = order.agent
    if not agent:
        return
    from apps.agents.services import recompute_agent_credit

    agent_credit = recompute_agent_credit(agent.id, company.id)
    if (
        agent_credit.auto_block_on_exceed
        and not agent_credit.is_credit_blocked
        and agent_credit.credit_limit > 0
        and agent_credit.credit_utilized + total > agent_credit.credit_limit
    ):
        raise OrderFlowError(
            (
                f"Order total ₹{total} would exceed agent "
                f"{user.full_name}'s credit limit of ₹{agent_credit.credit_limit}."
            ),
            code="AGENT_CREDIT_EXCEEDED",
            fields={"agent": "Credit limit exceeded."},
        )


def _requires_approval(order, user):
    company = order.company
    settings_obj = _company_settings(company)
    if not settings_obj or not getattr(settings_obj, "order_approval_required", False):
        return False
    subadmin = getattr(user, "subadmin_profile", None)
    if subadmin and subadmin.approval_threshold:
        return order.total_amount > subadmin.approval_threshold
    return user.role == "agent"


@transaction.atomic
def submit_draft(order, user, payload=None):
    payload = payload or {}
    order = Order.objects.select_for_update(of=("self",)).select_related(
        "customer", "agent__user", "company"
    ).get(pk=order.pk)
    _require_draft(order)

    if not order.items.exists():
        raise OrderFlowError(
            "Add at least one item before submitting the order.",
            code="EMPTY_ORDER",
            fields={"items": "At least one item is required."},
        )

    for field in (
        "delivery_address_line1",
        "delivery_address_line2",
        "delivery_city",
        "delivery_state",
        "delivery_pincode",
        "order_notes",
    ):
        if field in payload and payload[field] is not None:
            setattr(order, field, payload[field])
    if payload.get("expected_delivery_date") is not None:
        order.expected_delivery_date = payload["expected_delivery_date"] or None
    if payload.get("discount_pct") is not None:
        order.discount_pct = _decimal(payload["discount_pct"], "discount_pct")
    order.save()

    recalculate_order_totals(order)
    _check_credit(order, user)

    requires_approval = _requires_approval(order, user)
    settings_obj = _company_settings(order.company)
    if (
        settings_obj
        and getattr(settings_obj, "order_auto_confirm", False)
        and not requires_approval
    ):
        new_status = OrderStatus.CONFIRMED
    else:
        new_status = OrderStatus.SUBMITTED

    order.status = new_status
    order.requires_approval = requires_approval
    order.submitted_at = now()
    order.confirmed_at = now() if new_status == OrderStatus.CONFIRMED else None
    order.draft_expires_at = None
    order.save(
        update_fields=[
            "status",
            "requires_approval",
            "submitted_at",
            "confirmed_at",
            "draft_expires_at",
            "subtotal",
            "discount_pct",
            "discount_amount",
            "taxable_amount",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "total_amount",
            "is_interstate",
            "delivery_address_line1",
            "delivery_address_line2",
            "delivery_city",
            "delivery_state",
            "delivery_pincode",
            "expected_delivery_date",
            "order_notes",
            "updated_at",
        ]
    )
    _log_status(order, OrderStatus.DRAFT, new_status, user, "Draft submitted")

    from apps.orders.services import (
        create_commission_entry,
        generate_purchase_order,
        send_order_notification,
    )

    generate_purchase_order(order.company, order)
    if order.agent:
        create_commission_entry(order.company, order, performed_by=user)
        from apps.agents.services import recompute_agent_metrics

        recompute_agent_metrics(order.agent, company=order.company)
    if order.customer.user:
        event = (
            "order_confirmed"
            if new_status == OrderStatus.CONFIRMED
            else "order_submitted"
        )
        send_order_notification(order.company, order, event, order.customer.user)

    return order


@transaction.atomic
def discard_draft(order, user=None):
    order = _lock_order(order)
    _require_draft(order)
    order_id = order.id
    agent_id = order.agent_id
    _release_order_items(
        list(order.items.all()),
        user=user,
        reference_id=order.id,
        reason="Draft discarded",
    )
    order.delete()
    return order_id, agent_id


def _release_and_delete(order, user=None, reason="Draft expired"):
    order_id = order.id
    agent_id = order.agent_id
    company_id = order.company_id
    _release_order_items(
        list(order.items.all()),
        user=user,
        reference_id=order.id,
        reason=reason,
    )
    order.delete()
    return order_id, agent_id, company_id


def expire_draft_orders(company=None, agent=None, batch_size=500):
    """Delete expired DRAFT orders and release their reservations.

    Returns a list of ``(order_id, agent_id, company_id)`` tuples for expired
    orders so callers can broadcast realtime events.
    """
    queryset = Order.objects.filter(
        status=OrderStatus.DRAFT,
        draft_expires_at__isnull=False,
        draft_expires_at__lte=now(),
    )
    if company is not None:
        queryset = queryset.filter(company=company)
    if agent is not None:
        queryset = queryset.filter(agent=agent)

    expired = []
    order_ids = list(queryset.values_list("id", flat=True)[:batch_size])
    for order_id in order_ids:
        with transaction.atomic():
            order = (
                Order.objects.select_for_update()
                .filter(pk=order_id, status=OrderStatus.DRAFT)
                .first()
            )
            if order is None or order.draft_expires_at is None:
                continue
            if order.draft_expires_at > now():
                continue
            expired.append(_release_and_delete(order))

    return expired


def get_order_snapshot(order):
    """Small helper used by realtime payloads."""
    return {
        "order_id": str(order.id),
        "status": order.status,
        "total_amount": str(order.total_amount),
        "draft_expires_at": order.draft_expires_at.isoformat()
        if order.draft_expires_at
        else None,
    }


__all__ = [
    "add_item_to_draft",
    "create_draft_order",
    "discard_draft",
    "expire_draft_orders",
    "get_agent_order",
    "get_order_snapshot",
    "list_draft_orders",
    "next_order_number",
    "recalculate_order_totals",
    "refresh_draft_expiry",
    "remove_item_from_draft",
    "resolve_range_sizes",
    "submit_draft",
    "update_item_quantity",
]
