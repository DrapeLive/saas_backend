from django.db import transaction
from django.db.models import Q, Sum
from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdmin, IsAdminOrSubAdmin
from apps.commissions.models import (
    CategoryCommissionRate,
    CommissionEntry,
    CommissionPlan,
    CommissionSlab,
)
from apps.commissions.serializers import (
    AgentCommissionSummarySerializer,
    CategoryCommissionRateSerializer,
    CommissionEntryDetailSerializer,
    CommissionEntryListSerializer,
    CommissionEntryStatusSerializer,
    CommissionPlanCreateSerializer,
    CommissionPlanDetailSerializer,
    CommissionPlanListSerializer,
    CommissionPlanUpdateSerializer,
    CommissionSettlementSerializer,
    CommissionSlabSerializer,
)


class CommissionPlanViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

    def _get_company(self, request):
        return request.user.company

    def _get_plan(self, pk, company):
        try:
            return CommissionPlan.objects.prefetch_related(
                "slabs", "category_rates__category"
            ).get(pk=pk, company=company)
        except CommissionPlan.DoesNotExist:
            return None

    # GET /api/commission-plans/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            CommissionPlan.objects.filter(company=company)
            .prefetch_related("slabs", "category_rates")
            .order_by("name")
        )
        return Response(CommissionPlanListSerializer(qs, many=True).data)

    # GET /api/commission-plans/<pk>/
    def retrieve(self, request, pk=None):
        company = self._get_company(request)
        plan = self._get_plan(pk, company)
        if not plan:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(CommissionPlanDetailSerializer(plan).data)

    # POST /api/commission-plans/
    @transaction.atomic
    def create(self, request):
        company = self._get_company(request)
        serializer = CommissionPlanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # If marked as default, unmark existing defaults
        if serializer.validated_data.get("is_default"):
            CommissionPlan.objects.filter(company=company, is_default=True).update(
                is_default=False
            )

        plan = serializer.save(company=company)
        return Response(
            CommissionPlanDetailSerializer(plan).data, status=status.HTTP_201_CREATED
        )

    # PATCH /api/commission-plans/<pk>/
    @transaction.atomic
    def partial_update(self, request, pk=None):
        company = self._get_company(request)
        plan = self._get_plan(pk, company)
        if not plan:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = CommissionPlanUpdateSerializer(
            plan, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data.get("is_default"):
            CommissionPlan.objects.filter(company=company, is_default=True).exclude(
                pk=plan.pk
            ).update(is_default=False)

        serializer.save()
        return Response(CommissionPlanDetailSerializer(serializer.instance).data)

    # DELETE /api/commission-plans/<pk>/
    def destroy(self, request, pk=None):
        company = self._get_company(request)
        plan = self._get_plan(pk, company)
        if not plan:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        if plan.is_default:
            return Response(
                {"detail": "Cannot delete the default commission plan."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from apps.agents.models import AgentCompanyMembership

        if AgentCompanyMembership.objects.filter(
            custom_commission_plan=plan, status="active"
        ).exists():
            return Response(
                {"detail": "Cannot delete a plan that is assigned to active agents."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        plan.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # POST /api/commission-plans/<pk>/slabs/
    @action(detail=True, methods=["post"], url_path="slabs")
    @transaction.atomic
    def add_slab(self, request, pk=None):
        company = self._get_company(request)
        plan = self._get_plan(pk, company)
        if not plan:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = CommissionSlabSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        slab = serializer.save(plan=plan)
        return Response(
            CommissionSlabSerializer(slab).data, status=status.HTTP_201_CREATED
        )

    # DELETE /api/commission-plans/<pk>/slabs/<slab_pk>/
    @action(detail=True, methods=["delete"], url_path="slabs/(?P<slab_pk>[^/.]+)")
    def remove_slab(self, request, pk=None, slab_pk=None):
        company = self._get_company(request)
        plan = self._get_plan(pk, company)
        if not plan:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            slab = CommissionSlab.objects.get(pk=slab_pk, plan=plan)
        except CommissionSlab.DoesNotExist:
            return Response(
                {"detail": "Slab not found."}, status=status.HTTP_404_NOT_FOUND
            )
        slab.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    # POST /api/commission-plans/<pk>/category-rates/
    @action(detail=True, methods=["post"], url_path="category-rates")
    @transaction.atomic
    def add_category_rate(self, request, pk=None):
        company = self._get_company(request)
        plan = self._get_plan(pk, company)
        if not plan:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = CategoryCommissionRateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rate = serializer.save(plan=plan)
        return Response(
            CategoryCommissionRateSerializer(rate).data, status=status.HTTP_201_CREATED
        )


class CommissionEntryViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdminOrSubAdmin,)

    def _get_company(self, request):
        return request.user.company

    def _get_entry(self, pk, company):
        try:
            return CommissionEntry.objects.select_related(
                "agent__user", "order", "plan", "paid_by"
            ).get(pk=pk, tenant=company)
        except CommissionEntry.DoesNotExist:
            return None

    # GET /api/commission-entries/
    def list(self, request):
        company = self._get_company(request)
        qs = (
            CommissionEntry.objects.filter(company=company)
            .select_related("agent__user", "order", "plan")
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

        entry.status = data["status"]
        if data.get("dispute_reason"):
            entry.dispute_reason = data["dispute_reason"]
        if data.get("adjustment_notes"):
            entry.adjustment_notes = data["adjustment_notes"]
        if data["status"] == CommissionEntry.EntryStatus.PAID:
            entry.paid_at = now()
            entry.paid_by = request.user
        entry.save()

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
