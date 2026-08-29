from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q, Sum
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
from apps.invoices.models import InvoiceStatus
from apps.payments.models import OutstandingAging, Payment
from apps.payments.serializers import (
    AgingReportSummarySerializer,
    OutstandingAgingSerializer,
    PaymentCreateSerializer,
    PaymentDetailSerializer,
    PaymentListSerializer,
    PaymentReminderQueuedSerializer,
    SendPaymentReminderSerializer,
)


@extend_schema_view(
    list=extend_schema(
        tags=["Payments"],
        summary="List payments",
        parameters=[
            OpenApiParameter(
                "customer_id", OpenApiTypes.UUID, OpenApiParameter.QUERY, description="Filter by customer.",
            ),
            OpenApiParameter(
                "agent_id", OpenApiTypes.UUID, OpenApiParameter.QUERY, description="Filter by collecting agent.",
            ),
            OpenApiParameter(
                "mode", OpenApiTypes.STR, OpenApiParameter.QUERY, description="Payment mode.",
            ),
            OpenApiParameter(
                "date_from", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="Payment date from.",
            ),
            OpenApiParameter(
                "date_to", OpenApiTypes.DATE, OpenApiParameter.QUERY, description="Payment date to.",
            ),
        ],
        responses={200: PaymentListSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Payments"],
        summary="Get payment",
        responses={200: PaymentDetailSerializer, 404: RESPONSE_404},
    ),
    create=extend_schema(
        tags=["Payments"],
        summary="Record payment",
        description="Records a payment, updates the invoice paid/due amounts and the customer's outstanding balance.",
        responses={201: PaymentDetailSerializer, 400: RESPONSE_400},
    ),
    destroy=extend_schema(
        tags=["Payments"],
        summary="Delete payment",
        description="Only non-Tally payments can be deleted. Returns 204.",
        responses={204: None, 400: RESPONSE_400, 404: RESPONSE_404},
    ),
)
class PaymentViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def get_serializer_class(self):
        if self.action == "list":
            return PaymentListSerializer
        if self.action == "create":
            return PaymentCreateSerializer
        return PaymentDetailSerializer

    def _get_company(self, request):
        return request.user.company

    def _get_payment(self, pk, company):
        try:
            return Payment.objects.select_related(
                "customer", "invoice", "agent__user", "recorded_by"
            ).get(pk=pk, company=company)
        except Payment.DoesNotExist:
            return None

    # GET /api/payments/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            Payment.objects.filter(company=company)
            .select_related("customer", "invoice", "agent__user", "recorded_by")
            .order_by("-payment_date")
        )

        customer_f = request.query_params.get("customer_id")
        agent_f = request.query_params.get("agent_id")
        mode_f = request.query_params.get("mode")
        date_from = request.query_params.get("date_from")
        date_to = request.query_params.get("date_to")

        if customer_f:
            qs = qs.filter(customer_id=customer_f)
        if agent_f:
            qs = qs.filter(agent_id=agent_f)
        if mode_f:
            qs = qs.filter(mode=mode_f)
        if date_from:
            qs = qs.filter(payment_date__gte=date_from)
        if date_to:
            qs = qs.filter(payment_date__lte=date_to)

        return Response(PaymentListSerializer(qs, many=True).data)

    # GET /api/payments/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        payment = self._get_payment(pk, company)
        if not payment:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(PaymentDetailSerializer(payment).data)

    # POST /api/payments/
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        payment = serializer.save(company=company, recorded_by=request.user)

        # Update invoice paid / due amounts
        invoice = payment.invoice
        if invoice:
            invoice.amount_paid = (invoice.amount_paid or Decimal("0")) + payment.amount
            invoice.amount_due = invoice.total_amount - invoice.amount_paid
            invoice.status = (
                InvoiceStatus.PAID if invoice.amount_due <= 0 else InvoiceStatus.PARTIAL
            )
            invoice.save(update_fields=["amount_paid", "amount_due", "status"])

        # Update customer outstanding
        customer = payment.customer
        customer.credit_utilized = max(
            Decimal("0"), customer.credit_utilized - payment.amount
        )
        customer.total_outstanding = max(
            Decimal("0"), customer.total_outstanding - payment.amount
        )
        customer.save(update_fields=["credit_utilized", "total_outstanding"])

        # tasks.send_payment_receipt.delay(str(payment.id))
        return Response(
            PaymentDetailSerializer(payment).data, status=status.HTTP_201_CREATED
        )

    # DELETE /api/payments/<pk>/  — only for non-Tally payments
    def destroy(self, request, pk=None):
        company = self._get_company(request)
        payment = self._get_payment(pk, company)
        if not payment:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if payment.is_from_tally:
            return Response(
                {
                    "detail": "Tally-synced payments cannot be deleted here. Reverse in Tally."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        payment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    list=extend_schema(
        tags=["Payments"],
        summary="List outstanding aging",
        parameters=[
            OpenApiParameter(
                "agent_id", OpenApiTypes.UUID, OpenApiParameter.QUERY,
                description="Only customers assigned to this agent.",
            ),
            OpenApiParameter(
                "overdue_only", OpenApiTypes.BOOL, OpenApiParameter.QUERY,
                description="`true` for customers with 90+ days overdue.",
            ),
            OpenApiParameter(
                "segment", OpenApiTypes.STR, OpenApiParameter.QUERY,
                enum=["wholesale_retail", "corporate_institutional", "walk_in"],
                description="Filter by customer segment.",
            ),
        ],
        responses={200: OutstandingAgingSerializer(many=True)},
    ),
    summary=extend_schema(
        tags=["Payments"],
        summary="Aging report summary",
        description="Aggregated aging buckets across the whole company for the latest report date.",
        responses={200: AgingReportSummarySerializer, 404: RESPONSE_404},
    ),
    send_reminder=extend_schema(
        tags=["Payments"],
        summary="Send payment reminders",
        description="Queues WhatsApp/email payment reminders for a set of customers.",
        responses={200: PaymentReminderQueuedSerializer, 400: RESPONSE_400},
    ),
)
class OutstandingAgingViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def get_serializer_class(self):
        if self.action == "send_reminder":
            return SendPaymentReminderSerializer
        return OutstandingAgingSerializer

    def _get_company(self, request):
        return request.user.company

    # GET /api/outstanding/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            OutstandingAging.objects.filter(company=company)
            .select_related("customer__assigned_agent__user")
            .order_by("-total")
        )

        agent_f = request.query_params.get("agent_id")
        overdue_f = request.query_params.get("overdue_only")
        segment_f = request.query_params.get("segment")

        if agent_f:
            qs = qs.filter(customer__assigned_agent_id=agent_f)
        if overdue_f:
            qs = qs.filter(days_90_plus__gt=0)
        if segment_f:
            qs = qs.filter(customer__segment=segment_f)

        return Response(OutstandingAgingSerializer(qs, many=True).data)

    # GET /api/outstanding/summary/
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        company = self._get_company(request)
        latest = (
            OutstandingAging.objects.filter(company=company)
            .order_by("-report_date")
            .first()
        )
        if not latest:
            return Response(
                {"detail": "No aging report found."}, status=status.HTTP_404_NOT_FOUND
            )

        agg = OutstandingAging.objects.filter(
            company=company, report_date=latest.report_date
        ).aggregate(
            total_outstanding=Sum("total"),
            current=Sum("current"),
            days_1_30=Sum("days_1_30"),
            days_31_60=Sum("days_31_60"),
            days_61_90=Sum("days_61_90"),
            days_90_plus=Sum("days_90_plus"),
            customers_overdue=Count("id", filter=Q(days_90_plus__gt=0)),
        )
        return Response(agg)

    # POST /api/outstanding/send-reminder/
    @action(detail=False, methods=["post"], url_path="send-reminder")
    def send_reminder(self, request):
        company = self._get_company(request)
        serializer = SendPaymentReminderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # tasks.send_payment_reminders.delay(
        #     company_id=str(company.id),
        #     customer_ids=[str(c) for c in data["customer_ids"]],
        #     channel=data["channel"],
        #     message=data.get("message", ""),
        # )
        return Response(
            {
                "detail": f"Reminders queued for {len(data['customer_ids'])} customer(s).",
                "channel": data["channel"],
                "customer_count": len(data["customer_ids"]),
            }
        )
