from decimal import Decimal

from django.db.models import DecimalField, Q, Sum, TextField, Value
from django.db.models.functions import Cast, Coalesce
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
from apps.accounts.models import RoleType
from apps.accounts.permissions import CompanyApproved, IsCompanyStaff
from apps.core.openapi import RESPONSE_400, RESPONSE_404
from apps.core.pagination import DefaultPageNumberPagination
from apps.customers.customer_detail import (
    customer_orders,
    customer_outstanding,
    customer_payments,
    customer_summary,
)
from apps.customers.detail_serializers import (
    CustomerOrdersSerializer,
    CustomerOutstandingSerializer,
    CustomerPaymentsSerializer,
    CustomerSummarySerializer,
)
from apps.customers.models import CustomerProfile
from apps.customers.serializers import (
    CreditActivityResponseSerializer,
    CustomerCommunicationLogSerializer,
    CustomerCreateSerializer,
    CustomerDocumentSerializer,
    CustomerImportConfirmResponseSerializer,
    CustomerImportPreviewResponseSerializer,
    CustomerOverviewSerializer,
    CustomerPageSerializer,
    CustomerSegmentResponseSerializer,
    CustomerSerializer,
    CustomerUpdateSerializer,
    GstinVerifyResponseSerializer,
)
from apps.customers.services import compute_segment, verify_gstin
from apps.invoices.models import Invoice, InvoiceStatus


class IsAdminOrSubAdmin(IsCompanyStaff):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return request.user.role in (RoleType.ADMIN, RoleType.SUB_ADMIN)


@extend_schema_view(
    list=extend_schema(
        tags=["Customers"],
        summary="List customers",
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
                description="Page size (default 10).",
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Search trade name, legal name, phone, GSTIN or email.",
            ),
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=["active", "inactive", "blocked"],
                description="Filter by customer status.",
            ),
            OpenApiParameter(
                "segment",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=["bronze", "silver", "gold", "platinum"],
                description="Filter by computed segment.",
            ),
            OpenApiParameter(
                "assigned_agent",
                OpenApiTypes.UUID,
                OpenApiParameter.QUERY,
                description="Filter by assigned agent id.",
            ),
            OpenApiParameter(
                "tag",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Filter by a single tag string.",
            ),
            OpenApiParameter(
                "ordering",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=[
                    "trade_name",
                    "created_at",
                    "total_outstanding",
                    "overdue_outstanding",
                ],
                description="Sort field. Prefix with `-` for descending (default `-created_at`).",
            ),
        ],
        responses={200: CustomerPageSerializer},
    ),
    overview=extend_schema(
        tags=["Customers"],
        summary="Customer overview",
        description="Company-level active customer count and total outstanding receivable.",
        responses={200: CustomerOverviewSerializer},
    ),
    retrieve=extend_schema(
        tags=["Customers"],
        summary="Get customer",
        responses={200: CustomerSerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Customers"],
        summary="Create customer",
        description="Creates a customer and kicks off GSTIN verification when a GSTIN is provided.",
        responses={201: CustomerSerializer, 400: RESPONSE_400},
    ),
    partial_update=extend_schema(
        tags=["Customers"],
        summary="Update customer",
        responses={200: CustomerSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    destroy=extend_schema(
        tags=["Customers"],
        summary="Delete customer",
        description="Returns 204.",
        responses={204: None, 404: RESPONSE_404},
    ),
    import_preview=extend_schema(
        tags=["Customers"],
        summary="Preview customer import",
        description="Validates each row of a customer bulk-import payload without persisting.",
        responses={200: CustomerImportPreviewResponseSerializer, 400: RESPONSE_400},
    ),
    import_confirm=extend_schema(
        tags=["Customers"],
        summary="Confirm customer import",
        description="Persists validated import rows and returns created customers plus per-row errors.",
        responses={201: CustomerImportConfirmResponseSerializer, 400: RESPONSE_400},
    ),
    verify_gstin=extend_schema(
        tags=["Customers"],
        summary="Verify GSTIN",
        description="Re-runs GSTIN verification for a customer and persists verified fields on success.",
        responses={
            200: GstinVerifyResponseSerializer,
            400: RESPONSE_400,
            404: RESPONSE_404,
        },
    ),
    compute_segment=extend_schema(
        tags=["Customers"],
        summary="Recompute segment",
        description="Recomputes the customer's tier from order history.",
        responses={200: CustomerSegmentResponseSerializer, 404: RESPONSE_404},
    ),
    credit_block=extend_schema(
        tags=["Customers"],
        summary="Block customer credit",
        responses={200: CreditActivityResponseSerializer, 404: RESPONSE_404},
    ),
    credit_unblock=extend_schema(
        tags=["Customers"],
        summary="Unblock customer credit",
        responses={200: CreditActivityResponseSerializer, 404: RESPONSE_404},
    ),
    documents=extend_schema(
        tags=["Customers"],
        summary="List or upload documents",
        description="GET lists the customer's documents; POST uploads a new one (multipart).",
        responses={
            200: CustomerDocumentSerializer(many=True),
            201: CustomerDocumentSerializer,
            400: RESPONSE_400,
            404: RESPONSE_404,
        },
    ),
    communication_logs=extend_schema(
        tags=["Customers"],
        summary="List communication logs",
        responses={
            200: CustomerCommunicationLogSerializer(many=True),
            404: RESPONSE_404,
        },
    ),
    summary=extend_schema(
        tags=["Customers"],
        summary="Customer summary",
        description="Overview card: addresses, credit position, outstanding aging, recent activity.",
        responses={200: CustomerSummarySerializer, 404: RESPONSE_404},
    ),
    orders=extend_schema(
        tags=["Customers"],
        summary="Customer orders",
        description="Lifetime value, pending orders and recent order history.",
        responses={200: CustomerOrdersSerializer, 404: RESPONSE_404},
    ),
    payments=extend_schema(
        tags=["Customers"],
        summary="Customer payments",
        description="Total paid, outstanding, recent transactions and next due payment.",
        responses={200: CustomerPaymentsSerializer, 404: RESPONSE_404},
    ),
    outstanding=extend_schema(
        tags=["Customers"],
        summary="Customer outstanding",
        description="YTD paid, aging analysis and critical invoices.",
        responses={200: CustomerOutstandingSerializer, 404: RESPONSE_404},
    ),
)
class CustomerViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    pagination_class = DefaultPageNumberPagination

    # Invoice statuses whose remaining balance counts as outstanding receivable.
    UNPAID_STATUSES = (
        InvoiceStatus.ISSUED,
        InvoiceStatus.PARTIAL,
        InvoiceStatus.OVERDUE,
    )

    ORDERING_FIELDS = {
        "trade_name",
        "created_at",
        "total_outstanding",
        "overdue_outstanding",
    }

    def get_serializer_class(self):
        if self.action == "create":
            return CustomerCreateSerializer
        if self.action in ("partial_update", "update"):
            return CustomerUpdateSerializer
        if self.action == "documents":
            return CustomerDocumentSerializer
        if self.action == "communication_logs":
            return CustomerCommunicationLogSerializer
        return CustomerSerializer

    def get_permissions(self):
        if self.action in (
            "import_preview",
            "import_confirm",
            "verify_gstin",
            "compute_segment",
            "credit_block",
            "credit_unblock",
        ):
            return [IsAuthenticated(), CompanyApproved(), IsAdminOrSubAdmin()]
        if self.action in (
            "list",
            "retrieve",
            "create",
            "update",
            "documents",
            "partial_update",
            "destroy",
            "communication_logs",
        ):
            return [IsAuthenticated(), CompanyApproved(), IsCompanyStaff()]
        return [IsAuthenticated(), CompanyApproved(), IsAdminOrSubAdmin()]

    def get_queryset(self):
        return CustomerProfile.objects.select_related(
            "company", "assigned_agent__user", "user"
        )

    def _get_company(self, request):
        return request.company or request.user.company

    def list(self, request, *args, **kwargs):
        id = self._get_company(request)

        customers = self.get_queryset().filter(company=id)

        search = request.query_params.get("search")
        if search:
            customers = customers.filter(
                Q(trade_name__icontains=search)
                | Q(legal_name__icontains=search)
                | Q(phone__icontains=search)
                | Q(gstin__icontains=search)
                | Q(email__icontains=search)
            )

        status_filter = request.query_params.get("status")
        if status_filter:
            customers = customers.filter(status=status_filter)

        segment_filter = request.query_params.get("segment")
        if segment_filter:
            customers = customers.filter(segment=segment_filter)

        assigned_agent = request.query_params.get("assigned_agent")
        if assigned_agent:
            customers = customers.filter(assigned_agent_id=assigned_agent)

        tag = request.query_params.get("tag")
        if tag:
            customers = customers.annotate(
                tags_text=Cast("tags", output_field=TextField()),
            ).filter(tags_text__icontains=f'"{tag}"')

        ordering = request.query_params.get("ordering", "-created_at")
        descending = ordering.startswith("-")
        ordering_field = ordering.lstrip("-")
        if ordering_field not in self.ORDERING_FIELDS:
            descending, ordering_field = True, "created_at"
        # Client-facing total_outstanding maps to the annotated live sum.
        if ordering_field == "total_outstanding":
            ordering_field = "computed_total_outstanding"

        # Temporary: computed_total_outstanding is a live sum of unpaid
        # invoice balances, because the denormalized total_outstanding column
        # is not yet maintained on invoice creation/status changes. Remove
        # this annotation (and the serializer bridge) once sync lands.
        customers = customers.annotate(
            computed_total_outstanding=Coalesce(
                Sum(
                    "invoices__amount_due",
                    filter=Q(invoices__status__in=self.UNPAID_STATUSES),
                ),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ).order_by(f"-{ordering_field}" if descending else ordering_field)

        page = self.paginate_queryset(customers)
        serializer = CustomerSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request):
        company = self._get_company(request)
        active_count = CustomerProfile.objects.filter(
            company=company,
            status=CustomerProfile.CustomerStatus.ACTIVE,
        ).count()
        total_outstanding_receivable = Invoice.objects.filter(
            company=company,
            status__in=self.UNPAID_STATUSES,
        ).aggregate(
            total=Coalesce(
                Sum("amount_due"),
                Value(Decimal("0.00")),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        )["total"]
        data = CustomerOverviewSerializer(
            {
                "active_customer_count": active_count,
                "total_outstanding_receivable": total_outstanding_receivable,
            }
        ).data
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        try:
            customer = self.get_queryset().get(
                pk=kwargs.get(self.lookup_field),
                company=self._get_company(request),
            )
        except CustomerProfile.DoesNotExist:
            return self._not_found()
        serializer = CustomerSerializer(customer)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        company = self._get_company(request)
        gstin = request.data.get("gstin", "")
        if (
            gstin
            and CustomerProfile.objects.filter(company=company, gstin=gstin).exists()
        ):
            return Response(
                {"gstin": ["Customer with this GSTIN already exists in your company."]},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = CustomerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save(company=company)
        if customer.gstin:
            result = verify_gstin(customer.gstin)
            if result["valid"]:
                customer.gstin_verified = True
                customer.gstin_legal_name = result["legal_name"]
                customer.gstin_status = result["status"]
                customer.gstin_type = result["type"]
                customer.save(
                    update_fields=[
                        "gstin_verified",
                        "gstin_legal_name",
                        "gstin_status",
                        "gstin_type",
                    ]
                )
        return Response(
            CustomerSerializer(customer).data, status=status.HTTP_201_CREATED
        )

    def partial_update(self, request, *args, **kwargs):
        customer = self.get_object()
        serializer = CustomerUpdateSerializer(customer, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        customer = serializer.save()
        if "gstin" in request.data and customer.gstin:
            result = verify_gstin(customer.gstin)
            if result["valid"]:
                customer.gstin_verified = True
                customer.gstin_legal_name = result["legal_name"]
                customer.gstin_status = result["status"]
                customer.gstin_type = result["type"]
                customer.save(
                    update_fields=[
                        "gstin_verified",
                        "gstin_legal_name",
                        "gstin_status",
                        "gstin_type",
                    ]
                )
        return Response(CustomerSerializer(customer).data)

    def destroy(self, request, *args, **kwargs):
        customer = self.get_object()
        customer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="import-preview")
    def import_preview(self, request, *args, **kwargs):
        rows = request.data.get("rows", []) if isinstance(request.data, dict) else []
        validated = []
        errors = []
        for i, row in enumerate(rows, start=1):
            row_serializer = CustomerCreateSerializer(data=row)
            if row_serializer.is_valid():
                validated.append({"row_number": i, **row})
            else:
                errors.append({"row_number": i, "errors": row_serializer.errors})
        return Response({"valid": validated, "errors": errors, "total": len(rows)})

    @action(detail=False, methods=["post"], url_path="import-confirm")
    def import_confirm(self, request, *args, **kwargs):
        company = self._get_company(request)
        rows = request.data.get("rows", []) if isinstance(request.data, dict) else []
        created = []
        errors = []
        for i, row in enumerate(rows, start=1):
            row_serializer = CustomerCreateSerializer(data=row)
            if row_serializer.is_valid():
                customer = row_serializer.save(company=company)
                created.append(CustomerSerializer(customer).data)
            else:
                errors.append({"row_number": i, "errors": row_serializer.errors})
        return Response(
            {"created": created, "errors": errors, "total": len(rows)},
            status=status.HTTP_201_CREATED if created else status.HTTP_400_BAD_REQUEST,
        )

    @action(detail=True, methods=["post"], url_path="verify-gstin")
    def verify_gstin(self, request, *args, **kwargs):
        customer = self.get_object()
        if not customer.gstin:
            return Response(
                {"error": "Customer has no GSTIN"}, status=status.HTTP_400_BAD_REQUEST
            )
        result = verify_gstin(customer.gstin)
        if result["valid"]:
            customer.gstin_verified = True
            customer.gstin_legal_name = result["legal_name"]
            customer.gstin_status = result["status"]
            customer.gstin_type = result["type"]
            customer.save(
                update_fields=[
                    "gstin_verified",
                    "gstin_legal_name",
                    "gstin_status",
                    "gstin_type",
                ]
            )
        return Response(result)

    @action(detail=True, methods=["post"], url_path="compute-segment")
    def compute_segment(self, request, *args, **kwargs):
        customer = self.get_object()
        segment = compute_segment(customer)
        customer.segment = segment
        customer.save(update_fields=["segment"])
        return Response({"segment": segment})

    @action(detail=True, methods=["post"], url_path="credit-block")
    def credit_block(self, request, *args, **kwargs):
        customer = self.get_object()
        customer.is_credit_blocked = True
        customer.save(update_fields=["is_credit_blocked"])
        return Response({"is_credit_blocked": True})

    @action(detail=True, methods=["post"], url_path="credit-unblock")
    def credit_unblock(self, request, *args, **kwargs):
        customer = self.get_object()
        customer.is_credit_blocked = False
        customer.save(update_fields=["is_credit_blocked"])
        return Response({"is_credit_blocked": False})

    @action(detail=True, methods=["get", "post"], url_path="documents")
    def documents(self, request, *args, **kwargs):
        customer = self.get_object()
        if request.method == "GET":
            docs = customer.documents.all()
            serializer = CustomerDocumentSerializer(docs, many=True)
            return Response(serializer.data)
        serializer = CustomerDocumentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        doc = serializer.save(customer=customer, uploaded_by=request.user)
        return Response(
            CustomerDocumentSerializer(doc).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["get"], url_path="communication-logs")
    def communication_logs(self, request, *args, **kwargs):
        customer = self.get_object()
        logs = customer.communication_logs.all()
        serializer = CustomerCommunicationLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, *args, **kwargs):
        customer = self._get_detail_customer(request)
        if not customer:
            return self._not_found()
        serializer = CustomerSummarySerializer(customer_summary(customer))
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="orders")
    def orders(self, request, *args, **kwargs):
        customer = self._get_detail_customer(request)
        if not customer:
            return self._not_found()
        serializer = CustomerOrdersSerializer(customer_orders(customer))
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="payments")
    def payments(self, request, *args, **kwargs):
        customer = self._get_detail_customer(request)
        if not customer:
            return self._not_found()
        serializer = CustomerPaymentsSerializer(customer_payments(customer))
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="outstanding")
    def outstanding(self, request, *args, **kwargs):
        customer = self._get_detail_customer(request)
        if not customer:
            return self._not_found()
        serializer = CustomerOutstandingSerializer(customer_outstanding(customer))
        return Response(serializer.data)

    def _get_detail_customer(self, request):
        kwargs = self.kwargs
        pk = kwargs.get(self.lookup_field)
        qs = self.get_queryset()
        company = self._get_company(request)
        if company:
            qs = qs.filter(company=company)
        try:
            return qs.get(pk=pk)
        except (CustomerProfile.DoesNotExist, CustomerProfile.MultipleObjectsReturned):
            return None

    def _not_found(self):
        return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
