from django.db.models import Count, Sum

from apps.customers.models import CustomerProfile, GstStatus


def verify_gstin(gstin: str) -> dict:
    return {
        "valid": False,
        "legal_name": "",
        "status": GstStatus.UNVERIFIED,
        "type": "",
        "message": "GST verification service not configured",
    }


def compute_segment(customer: CustomerProfile) -> str:
    from apps.orders.models import Order

    order_data = Order.objects.filter(customer=customer).aggregate(
        total_spent=Sum("total_amount"),
        order_count=Count("id"),
    )
    total_spent = order_data["total_spent"] or 0
    order_count = order_data["order_count"] or 0

    if total_spent > 500000 or order_count > 50:
        return CustomerProfile.CustomerSegment.PLATINUM
    if total_spent > 200000 or order_count > 20:
        return CustomerProfile.CustomerSegment.GOLD
    if total_spent > 50000 or order_count > 5:
        return CustomerProfile.CustomerSegment.SILVER
    return CustomerProfile.CustomerSegment.BRONZE
