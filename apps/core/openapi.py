"""Reusable OpenAPI / drf-spectacular building blocks.

These helpers centralize the project's documentation conventions so that every
ViewSet documents errors, headers and shared response shapes identically.

The API returns all validation and permission errors in a flat envelope::

    {"detail": "Human-readable error message."}

produced by ``apps.accounts.views.custom_exception_handler``. Use the
``RESPONSE_*`` constants inside ``@extend_schema(responses=...)`` so the schema
stays consistent project-wide.
"""

from drf_spectacular.openapi import OpenApiParameter, OpenApiResponse
from drf_spectacular.types import OpenApiTypes
from rest_framework import serializers


class DetailResponseSerializer(serializers.Serializer):
    """Standard message envelope returned by this API for all errors and most
    simple mutations (``{"detail": "message"}``)."""

    detail = serializers.CharField()


# HTTP error responses — documented with the flattened `detail` envelope that
# the project's custom exception handler produces.
RESPONSE_400 = OpenApiResponse(
    DetailResponseSerializer,
    description="Bad request. Field/validation errors are flattened into a single `detail` string.",
)
RESPONSE_401 = OpenApiResponse(
    DetailResponseSerializer,
    description="Unauthorized. Missing, invalid or expired bearer token.",
)
RESPONSE_403 = OpenApiResponse(
    DetailResponseSerializer,
    description="Forbidden. The authenticated user is not allowed to perform this action.",
)
RESPONSE_404 = OpenApiResponse(
    DetailResponseSerializer,
    description="Not found. The requested resource does not exist in the current company.",
)
RESPONSE_409 = OpenApiResponse(
    DetailResponseSerializer,
    description="Conflict. The operation violates a business rule.",
)
RESPONSE_429 = OpenApiResponse(
    DetailResponseSerializer,
    description="Too many requests. Rate limit exceeded.",
)

DETAIL_RESPONSE_200 = OpenApiResponse(
    DetailResponseSerializer,
    description="Success.",
)

#: Optional header honoured for agent-sourced JWTs that carry no company claim.
#: Callers can use this header to select the active company.
COMPANY_HEADER_PARAM = OpenApiParameter(
    "X-Company-Id",
    OpenApiTypes.UUID,
    OpenApiParameter.HEADER,
    description=(
        "Optional company to operate in. Agents whose JWT does not carry a "
        "`company_id` claim must pass an active membership company via this "
        "header to access company-scoped endpoints."
    ),
    required=False,
)
