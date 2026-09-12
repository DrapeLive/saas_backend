from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils.timezone import now

from apps.commissions.models import CategoryCommissionRate, CommissionEntry
from apps.invoices.models import Invoice, InvoiceItem, InvoiceStatus, InvoiceType
from apps.notifications.models import Notification, NotificationStatus
from apps.products.models import VariantSize

# Invoice statuses that mean the customer still owes money.
UNPAID_INVOICE_STATUSES = ("issued", "partial")


def get_order_items_with_category(order):
    """
    Return all OrderItems with their resolved product `category_id` available
    on the row. Uses select_related to avoid N+1 queries.
    """
    return (
        order.items.select_related("variant_size__color_variant__product__category")
        .all()
    )


def compute_commission_for_order(company, order):
    """
    Compute the weighted commission for an order based on the per-category
    commission rates configured for the company.

    Each line's taxable value (line_total - its GST portion isn't relevant;
    we use the discounted taxable line value) is weighted by the commission
    rate of its product's category. The order-level commission rate is the
    weighted average of category rates; the amount is that rate applied to the
    order's taxable amount.

    Returns a tuple (commission_pct, commission_amount) as Decimals.
    """
    rates = {
        r.category_id: r.commission_pct
        for r in CategoryCommissionRate.objects.filter(company=company)
    }

    weighted_total = Decimal("0")
    value_total = Decimal("0")
    for item in get_order_items_with_category(order):
        line_value = item.line_total
        category_id = item.variant_size.color_variant.product.category_id
        rate = rates.get(category_id, Decimal("0"))
        weighted_total += line_value * rate
        value_total += line_value

    if value_total == 0:
        return Decimal("0"), Decimal("0")

    weighted_pct = weighted_total / value_total
    commission_amount = (order.taxable_amount * weighted_pct) / Decimal("100")
    return weighted_pct, commission_amount


@transaction.atomic
def create_commission_entry(company, order, performed_by=None):
    """
    Create a commission entry for an order's agent (if any). The commission is
    category-based (see `compute_commission_for_order`) and is created when the
    order is booked. Idempotent: won't overwrite an existing entry for the order.
    """
    if not order.agent:
        return None

    existing = CommissionEntry.objects.filter(order=order).first()
    if existing:
        return existing

    commission_pct, commission_amount = compute_commission_for_order(company, order)
    entry = CommissionEntry.objects.create(
        company=company,
        agent=order.agent,
        order=order,
        order_value=order.taxable_amount,
        commission_pct=commission_pct,
        commission_amount=commission_amount,
    )
    return entry


@transaction.atomic
def generate_sales_invoice(company, order):
    """
    Generate a sales invoice for a dispatched order. Duplicate invoices are
    avoided by checking for an existing sales invoice linked to the order.
    Returns the Invoice (existing or newly created).
    """
    existing = Invoice.objects.filter(
        company=company, order=order, invoice_type=InvoiceType.SALES_INVOICE
    ).first()
    if existing:
        return existing

    customer = order.customer
    invoice = Invoice.objects.create(
        company=company,
        invoice_type=InvoiceType.SALES_INVOICE,
        invoice_number=company.get_next_invoice_number(),
        order=order,
        customer=customer,
        status=InvoiceStatus.ISSUED,
        invoice_date=now().date(),
        due_date=(
            (now() + timedelta(days=customer.payment_terms_days)).date()
            if customer.payment_terms_days
            else None
        ),
        subtotal=order.subtotal,
        discount_amount=order.discount_amount,
        taxable_amount=order.taxable_amount,
        cgst_amount=order.cgst_amount,
        sgst_amount=order.sgst_amount,
        igst_amount=order.igst_amount,
        total_amount=order.total_amount,
        amount_paid=Decimal("0"),
        amount_due=order.total_amount,
        is_interstate=order.is_interstate,
        place_of_supply=order.delivery_state or "",
        notes=f"Auto-generated from order {order.order_number}",
    )
    _create_invoice_items(invoice, order)

    update_customer_outstanding(customer)
    return invoice


@transaction.atomic
def generate_purchase_order(company, order):
    """
    Generate a purchase order when a order is booked. Idempotent: skips if a
    purchase order already exists for the order. Not a receivable — it is
    excluded from outstanding/credit calculations.
    """
    existing = Invoice.objects.filter(
        company=company, order=order, invoice_type=InvoiceType.PURCHASE_ORDER
    ).first()
    if existing:
        return existing

    invoice = Invoice.objects.create(
        company=company,
        invoice_type=InvoiceType.PURCHASE_ORDER,
        invoice_number=company.get_next_invoice_number(),
        order=order,
        customer=order.customer,
        status=InvoiceStatus.ISSUED,
        invoice_date=now().date(),
        due_date=None,
        subtotal=order.subtotal,
        discount_amount=order.discount_amount,
        taxable_amount=order.taxable_amount,
        cgst_amount=order.cgst_amount,
        sgst_amount=order.sgst_amount,
        igst_amount=order.igst_amount,
        total_amount=order.total_amount,
        amount_paid=Decimal("0"),
        amount_due=order.total_amount,
        is_interstate=order.is_interstate,
        place_of_supply=order.delivery_state or "",
        notes=f"Auto-generated purchase order from order {order.order_number}",
    )
    _create_invoice_items(invoice, order)
    return invoice


def _create_invoice_items(invoice, order):
    """Snapshot the order's line items as invoice items."""
    for item in get_order_items_with_category(order):
        InvoiceItem.objects.create(
            invoice=invoice,
            description=item.product_name,
            hsn_code=item.hsn_code,
            quantity=item.quantity,
            unit_price=item.unit_price,
            discount_pct=item.discount_pct,
            gst_rate=item.gst_rate,
            taxable_amount=item.line_total * (1 - item.discount_pct / 100),
            gst_amount=item.gst_amount,
            line_total=item.line_total,
        )


@transaction.atomic
def update_customer_outstanding(customer):
    """
    Recompute a customer's total outstanding and credit utilization from their
    live unpaid invoices. Call after invoice creation/payment.
    """
    agg = (
        Invoice.objects.filter(
            company=customer.company,
            customer=customer,
            status__in=UNPAID_INVOICE_STATUSES,
        )
        .exclude(invoice_type=InvoiceType.PURCHASE_ORDER)
        .aggregate(total=Sum("amount_due"))["total"]
        or Decimal("0.00")
    )
    fields = []
    if customer.total_outstanding != agg:
        customer.total_outstanding = agg
        fields.append("total_outstanding")
    if customer.credit_utilized != agg:
        customer.credit_utilized = agg
        fields.append("credit_utilized")
    if fields:
        customer.save(update_fields=fields)
    return agg


def send_order_notification(company, order, event_type, recipient):
    """
    Record an outbound order notification (in-app/WhatsApp placeholder).
    Creates a `Notification` row scoped to the company/recipient so it can be
    delivered by the async worker later. Returns the Notification.
    """
    mapping = {
        "order_submitted": (
            "Order Submitted",
            f"Your order {order.order_number} has been submitted.",
        ),
        "order_confirmed": (
            "Order Confirmed",
            f"Your order {order.order_number} has been confirmed.",
        ),
        "order_dispatched": (
            "Order Dispatched",
            f"Your order {order.order_number} has been dispatched.",
        ),
        "order_delivered": (
            "Order Delivered",
            f"Your order {order.order_number} has been delivered.",
        ),
        "order_cancelled": (
            "Order Cancelled",
            f"Your order {order.order_number} has been cancelled.",
        ),
    }
    subject, body = mapping.get(event_type, (event_type, event_type))

    if recipient is not None and getattr(recipient, "role", None) == "agent":
        recipient_user = recipient.user
        recipient_phone = recipient.user.phone
        recipient_email = recipient.user.email
    else:
        recipient_user = recipient
        recipient_phone = ""
        recipient_email = ""

    notification = Notification.objects.create(
        company=company,
        recipient=recipient_user,
        recipient_phone=recipient_phone,
        recipient_email=recipient_email,
        channel="whatsapp",
        subject=subject,
        body=body,
        status=NotificationStatus.QUEUED,
    )
    return notification
