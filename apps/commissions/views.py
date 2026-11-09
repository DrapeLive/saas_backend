from django.db import transaction
from django.db.models import Sum
from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdmin, IsAdminOrSubAdmin
from apps.commissions.models import CommissionEntry
from apps.commissions.serializers import (
    AgentCommissionSummarySerializer,
    CommissionEntryDetailSerializer,
    CommissionEntryListSerializer,
    CommissionEntryStatusSerializer,
    CommissionSettledSerializer,
    CommissionSettlementSerializer,
)
from apps.commissions.services import settlement_month_for, upsert_payout


class CommissionEntryViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def get_serializer_class(self):
        if self.action == "list":
            return CommissionEntryListSerializer
        if self.action == "update_status":
            return CommissionEntryStatusSerializer
        if self.action == "settle":
            return CommissionSettlementSerializer
        return CommissionEntryDetailSerializer

    def _get_company(self, request):
        return request.user.company

    def _get_entry(self, pk, company):
        try:
            return CommissionEntry.objects.select_related(
                "agent__user", "order", "paid_by"
            ).get(pk=pk, company=company)
        except CommissionEntry.DoesNotExist:
            return None

    # GET /api/commission-entries/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            CommissionEntry.objects.filter(company=company)
            .select_related("agent__user", "order")
            .order_by("-created_at")
        )

        agent_f = request.query_params.get("agent_id")
        status_f = request.query_params.get("status")
        month_f = request.query_params.get("month")  # YYYY-MM-01

        if agent_f:
            qs = qs.filter(agent_id=agent_f)
        if status_f:
            qs = qs.filter(status=status_f)
        if month_f:
            qs = qs.filter(settlement_month=month_f)

        return Response(CommissionEntryListSerializer(qs, many=True).data)

    # GET /api/commission-entries/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        entry = self._get_entry(pk, company)
        if not entry:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CommissionEntryDetailSerializer(entry).data)

    # POST /api/commission-entries/<pk>/status/
    @action(
        detail=True, methods=["post"], url_path="status", permission_classes=[IsAdmin]
    )
    @transaction.atomic
    def update_status(self, request, pk=None):
        company = self._get_company(request)
        entry = self._get_entry(pk, company)
        if not entry:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = CommissionEntryStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        old_status = entry.status
        old_month = entry.settlement_month

        entry.status = data["status"]
        if data.get("dispute_reason"):
            entry.dispute_reason = data["dispute_reason"]
        if data.get("adjustment_notes"):
            entry.adjustment_notes = data["adjustment_notes"]
        if data["status"] == CommissionEntry.EntryStatus.PAID:
            entry.paid_at = now()
            entry.paid_by = request.user
            if entry.settlement_month is None:
                entry.settlement_month = settlement_month_for(entry)
        entry.save()

        # Keep the monthly payout ledger in sync for any affected month.
        affected_months = set()
        if old_status == CommissionEntry.EntryStatus.PAID:
            affected_months.add(old_month or settlement_month_for(entry))
        if entry.status == CommissionEntry.EntryStatus.PAID:
            affected_months.add(entry.settlement_month)
        for month in affected_months:
            if month is not None:
                upsert_payout(
                    agent_id=entry.agent_id,
                    company_id=company.id,
                    month=month,
                    paid_by=request.user,
                )

        return Response(CommissionEntryDetailSerializer(entry).data)

    # POST /api/commission-entries/settle/
    @action(
        detail=False, methods=["post"], url_path="settle", permission_classes=[IsAdmin]
    )
    @transaction.atomic
    def settle(self, request):
        company = self._get_company(request)
        serializer = CommissionSettlementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        entries = CommissionEntry.objects.filter(
            company=company,
            agent_id=data["agent_id"],
            settlement_month=data["settlement_month"],
            status=CommissionEntry.EntryStatus.APPROVED,
        )
        count = entries.count()
        if count == 0:
            return Response(
                {"detail": "No approved entries found for the given agent and month."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        total = entries.aggregate(total=Sum("commission_amount"))["total"]
        entries.update(
            status=CommissionEntry.EntryStatus.PAID,
            paid_at=now(),
            paid_by=request.user,
            adjustment_notes=data.get("notes", ""),
        )
        upsert_payout(
            agent_id=data["agent_id"],
            company_id=company.id,
            month=data["settlement_month"],
            paid_by=request.user,
            notes=data.get("notes"),
        )
        return Response(
            {
                "detail": f"{count} entries settled.",
                "total_paid": total,
                "agent_id": str(data["agent_id"]),
                "settlement_month": str(data["settlement_month"]),
            }
        )

    # GET /api/commission-entries/summary/
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        company = self._get_company(request)
        month = request.query_params.get("month")

        qs = CommissionEntry.objects.filter(company=company)
        if month:
            qs = qs.filter(settlement_month=month)

        from apps.agents.models import AgentProfile

        agents = (
            AgentProfile.objects.filter(
                memberships__company=company, memberships__status="active"
            )
            .select_related("user")
            .distinct()
        )

        result = []
        for agent in agents:
            agent_qs = qs.filter(agent=agent)
            result.append(
                {
                    "agent_id": str(agent.id),
                    "agent_name": agent.user.full_name,
                    "pending_amount": agent_qs.filter(status="pending").aggregate(
                        t=Sum("commission_amount")
                    )["t"]
                    or 0,
                    "approved_amount": agent_qs.filter(status="approved").aggregate(
                        t=Sum("commission_amount")
                    )["t"]
                    or 0,
                    "paid_amount": agent_qs.filter(status="paid").aggregate(
                        t=Sum("commission_amount")
                    )["t"]
                    or 0,
                    "disputed_count": agent_qs.filter(status="disputed").count(),
                    "period": month,
                }
            )
        return Response(result)
