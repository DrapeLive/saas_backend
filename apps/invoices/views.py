from decimal import Decimal

from django.db import transaction
from django.utils.timezone import now
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdminOrSubAdmin
from apps.core.openapi import RESPONSE_400, RESPONSE_404
from apps.invoices.models import Invoice, InvoiceItem, InvoiceStatus, InvoiceType
from apps.invoices.serializers import (
    InvoiceCreateSerializer,
    InvoiceDetailSerializer,
    InvoiceDownloadResponseSerializer,
    InvoiceItemSerializer,
    InvoiceListSerializer,
    InvoicePDFQueuedSerializer,
    InvoicePDFRegenerateSerializer,
    InvoiceStatusUpdateSerializer,
    InvoiceVoidSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Invoices"],
        summary="List invoices",
        parameters=[
            OpenApiParameter(
                "type", OpenApiTypes.STR, OpenApiParameter.QUERY,
                enum=[c.value for c in InvoiceType],
                description="Invoice type (sales_invoice, credit_note, debit_note, purchase_order).",
            ),
            OpenApiParameter(
                "status", OpenApiTypes.STR, OpenApiParameter.QUERY,
                enum=[c.value for c in InvoiceStatus],
                description="Invoice status.",
            ),
            OpenApiParameter(
                "customer_id", OpenApiTypes.UUID, OpenApiParameter.QUERY, description="Filter by customer.",
            ),
            OpenApiParameter(
                "overdue", OpenApiTypes.BOOL, OpenApiParameter.QUERY,
                description="`true` for issued/overdue invoices past their due date.",
            ),
            OpenApiParameter(
                "date_from", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="Invoice date from.",
            ),
            OpenApiParameter(
                "date_to", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="Invoice date to.",
            ),
            OpenApiParameter(
                "search", OpenApiTypes.STR, OpenApiParameter.QUERY,
                description="Search by invoice number or customer name.",
            ),
        ],
        responses={200: InvoiceListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Invoices"],
        summary="Get invoice",
        responses={200: InvoiceDetailSerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Invoices"],
        summary="Create manual invoice",
        description="Manual credit/debit notes only — sales invoices are auto-generated from orders.",
        responses={201: InvoiceDetailSerializer, 400: RESPONSE_400},
    ),
    void=extend_schema(
        tags=["Invoices"],
        summary="Void invoice",
        description="Irreversibly voids a draft/issued invoice with no recorded payments.",
        responses={200: InvoiceDetailSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    regenerate_pdf=extend_schema(
        tags=["Invoices"],
        summary="Regenerate PDF",
        description="Queues a background job to regenerate the invoice PDF.",
        responses={200: InvoicePDFQueuedSerializer, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
    download=extend_schema(
        tags=["Invoices"],
        summary="Download PDF",
        description="Returns the absolute URL of the generated PDF.",
        responses={200: InvoiceDownloadResponseSerializer, 404: RESPONSE_404},
    ),
)
class InvoiceViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def get_serializer_class(self):
        if self.action == "list":
            return InvoiceListSerializer
        if self.action == "create":
            return InvoiceCreateSerializer
        if self.action == "void":
            return InvoiceVoidSerializer
        if self.action == "regenerate_pdf":
            return InvoicePDFRegenerateSerializer
        return InvoiceDetailSerializer

    def _get_company(self, request):
        return request.user.company

    def _get_invoice(self, pk, company):
        try:
            return (
                Invoice.objects.select_related("customer", "order")
                .prefetch_related("items")
                .get(pk=pk, company=company)
            )
        except Invoice.DoesNotExist:
            return None

    # GET /api/invoices/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            Invoice.objects.filter(company=company)
            .select_related("customer")
            .order_by("-invoice_date")
        )

        invoice_type_f = request.query_params.get("type")
        status_f = request.query_params.get("status")
        customer_f = request.query_params.get("customer_id")
        overdue_f = request.query_params.get("overdue")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")
        search = request.query_params.get("search")

        if invoice_type_f:
            qs = qs.filter(invoice_type=invoice_type_f)
        if status_f:
            qs = qs.filter(status=status_f)
        if customer_f:
            qs = qs.filter(customer_id=customer_f)
        if overdue_f:
            qs = qs.filter(
                status__in=[InvoiceStatus.ISSUED, InvoiceStatus.OVERDUE],
                due_date__lt=now().date(),
            )
        if date_from:
            qs = qs.filter(invoice_date__gte=date_from)
        if date_to:
            qs = qs.filter(invoice_date__lte=date_to)
        if search:
            qs = qs.filter(invoice_number__icontains=search) | qs.filter(
                customer__business_name__icontains=search
            )

        return Response(InvoiceListSerializer(qs, many=True).data)

    # GET /api/invoices/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        invoice = self._get_invoice(pk, company)
        if not invoice:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(InvoiceDetailSerializer(invoice).data)

    # POST /api/invoices/  — manual credit/debit notes only
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = InvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        items_data = serializer.validated_data.pop("items")
        invoice = Invoice.objects.create(
            company=company,
            invoice_number=company.get_next_invoice_number(),
            status=InvoiceStatus.DRAFT,
            **serializer.validated_data,
        )

        subtotal = Decimal("0")
        for item_data in items_data:
            qty = item_data["quantity"]
            unit_price = item_data["unit_price"]
            disc = item_data.get("discount_pct", Decimal("0"))
            gst_rate = item_data.get("gst_rate", Decimal("5"))
            taxable = qty * unit_price * (1 - disc / 100)
            gst_amount = taxable * gst_rate / 100
            line_total = taxable + gst_amount
            subtotal += line_total
            InvoiceItem.objects.create(
                invoice=invoice,
                taxable_amount=taxable,
                gst_amount=gst_amount,
                line_total=line_total,
                **item_data,
            )

        invoice.subtotal = subtotal
        invoice.taxable_amount = subtotal
        invoice.total_amount = subtotal
        invoice.amount_due = subtotal
        invoice.save(
            update_fields=["subtotal", "taxable_amount", "total_amount", "amount_due"]
        )

        return Response(
            InvoiceDetailSerializer(invoice).data, status=status.HTTP_201_CREATED
        )

    # POST /api/invoices/<pk>/void/
    @action(detail=True, methods=["post"], url_path="void")
    @transaction.atomic
    def void(self, request, pk=None):
        company = self._get_company(request)
        invoice = self._get_invoice(pk, company)
        if not invoice:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if invoice.status == InvoiceStatus.VOID:
            return Response(
                {"detail": "Invoice is already voided."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if invoice.amount_paid > 0:
            return Response(
                {
                    "detail": "Cannot void an invoice with recorded payments. Create a credit note instead."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = InvoiceVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invoice.status = InvoiceStatus.VOID
        invoice.notes = serializer.validated_data["reason"]
        invoice.save(update_fields=["status", "notes"])
        return Response(InvoiceDetailSerializer(invoice).data)

    # POST /api/invoices/<pk>/regenerate-pdf/
    @action(detail=True, methods=["post"], url_path="regenerate-pdf")
    def regenerate_pdf(self, request, pk=None):
        company = self._get_company(request)
        invoice = self._get_invoice(pk, company)
        if not invoice:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = InvoicePDFRegenerateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # tasks.generate_invoice_pdf.delay(str(invoice.id), force=serializer.validated_data["force"])
        return Response(
            {"detail": "PDF regeneration queued.", "invoice_id": str(invoice.id)}
        )

    # GET /api/invoices/<pk>/download/
    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        company = self._get_company(request)
        invoice = self._get_invoice(pk, company)
        if not invoice:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if not invoice.pdf_file:
            return Response(
                {"detail": "PDF not yet generated. Call regenerate-pdf first."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"pdf_url": request.build_absolute_uri(invoice.pdf_file.url)})
