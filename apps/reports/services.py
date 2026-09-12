"""Shared helpers and business constants used by the report endpoints.

Report data is always computed on the fly against the current company and an
optional date window. Dates are passed as ``YYYY-MM-DD`` strings and treated
as inclusive bounds.
"""

from datetime import date, datetime

from rest_framework import serializers


# ─────────────────────────────────────────────────────────────────────────────
# Status conventions
# ─────────────────────────────────────────────────────────────────────────────

#: Order statuses counted as real sales (excludes cancellations).
SALES_STATUSES = [
    "confirmed",
    "processing",
    "packed",
    "dispatched",
    "delivered",
]

#: Invoice statuses that still carry an outstanding amount.
UNPAID_STATUSES = ["issued", "partial"]

#: Order statuses that represent a company accepted for sale-report derived
#: metrics such as average order value and discount totals.
SALES_EXCLUDED_STATUSES = ["cancelled"]

#: Invoice types treated as outward/sales supply for the GST report.
GST_SALES_INVOICE_TYPES = ["sales_invoice"]

#: Invoice types treated as inward/purchase supply for the GST report.
GST_PURCHASE_INVOICE_TYPES = ["purchase_order"]


def _parse_date(value, field_name):
    """Parse a ``YYYY-MM-DD`` query parameter or raise a 400-style error."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise serializers.ValidationError(
            {field_name: f"Invalid date '{value}'. Use YYYY-MM-DD."}
        )


def get_company(request):
    """Resolve the active company from the JWT (or agent header)."""
    return request.company or request.user.company


def get_date_range(request, field):
    """Return ``(date_from, date_to)`` from query params for ``?<field>_from=``.

    Both bounds are optional; ``date_from`` must not be after ``date_to``.
    """
    date_from = _parse_date(request.query_params.get(f"{field}_from"), f"{field}_from")
    date_to = _parse_date(request.query_params.get(f"{field}_to"), f"{field}_to")
    if date_from and date_to and date_from > date_to:
        raise serializers.ValidationError(
            {f"{field}_from": f"{field}_from must be on or before {field}_to."}
        )
    return date_from, date_to


def today():
    return date.today()