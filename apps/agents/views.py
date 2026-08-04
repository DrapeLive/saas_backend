from django.db.models import (
    Count,
    DecimalField,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import (
    CanManageUsers,
    CompanyApproved,
    IsAdmin,
    IsAgent,
    IsCompanyAdminOrAbove,
)
from apps.agents.models import AgentCompanyMembership, AgentProfile
from apps.agents.serializers import (
    AgentCompanySerializer,
    AgentLeaderboardSerializer,
    AgentMembershipSerializer,
    AgentMembershipUpdateSerializer,
    AgentPerformanceSerializer,
)
from apps.commissions.models import CommissionEntry
from apps.orders.models import Order


class AgentMembershipViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        return AgentCompanyMembership.objects.select_related(
            "agent__user",
            "company",
            "custom_commission_plan",
            "approved_by",
            "reviewed_by",
        )

    def get_permissions(self):
        if self.action in (
            "list",
            "retrieve",
            "partial_update",
            "destroy",
            "approve",
            "reject",
            "suspend",
            "reactivate",
            "agent_performance",
            "leaderboard",
        ):
            return [IsAuthenticated(), CompanyApproved(), CanManageUsers()]
        if self.action in (
            "my_companies",
            "switch_company",
            "my_performance",
        ):
            return [IsAuthenticated(), IsAgent()]
        return super().get_permissions()

    def get_serializer_class(self):
        if self.action == "partial_update":
            return AgentMembershipUpdateSerializer
        if self.action in ("list", "retrieve"):
            return AgentMembershipSerializer
        return AgentMembershipSerializer

    def list(self, request, *args, **kwargs):
        if request.user.role == "superadmin":
            memberships = self.get_queryset()
        else:
            memberships = self.get_queryset().filter(company=request.user.company)
        serializer = AgentMembershipSerializer(memberships, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if request.user.role != "superadmin" and membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only view agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = AgentMembershipSerializer(membership)
        return Response(serializer.data)

    def partial_update(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if request.user.role != "superadmin" and membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only manage agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )
        serializer = AgentMembershipUpdateSerializer(
            membership, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(AgentMembershipSerializer(membership).data)

    def destroy(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if request.user.role != "superadmin" and membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only manage agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )
        membership.status = AgentCompanyMembership.MembershipStatus.REMOVED
        membership.removed_at = now()
        membership.save(update_fields=["status", "removed_at"])
        membership.agent.user.is_active = False
        membership.agent.user.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only approve agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if membership.status not in ("pending", "reviewed"):
            return Response(
                {
                    "detail": f"Cannot approve membership with status '{membership.status}'."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership.status = AgentCompanyMembership.MembershipStatus.ACTIVE
        membership.approved_by = request.user
        membership.joined_at = now()
        membership.save(update_fields=["status", "approved_by", "joined_at"])
        return Response(AgentMembershipSerializer(membership).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only reject agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if membership.status != "pending":
            return Response(
                {
                    "detail": f"Cannot reject membership with status '{membership.status}'."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership.status = AgentCompanyMembership.MembershipStatus.REMOVED
        membership.removed_at = now()
        membership.save(update_fields=["status", "removed_at"])
        return Response(
            {"detail": "Agent membership rejected and removed."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only manage agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if membership.status != "active":
            return Response(
                {
                    "detail": f"Cannot suspend membership with status '{membership.status}'."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership.status = AgentCompanyMembership.MembershipStatus.SUSPENDED
        membership.save(update_fields=["status"])
        return Response(AgentMembershipSerializer(membership).data)

    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only manage agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if membership.status != "suspended":
            return Response(
                {
                    "detail": f"Cannot reactivate membership with status '{membership.status}'."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership.status = AgentCompanyMembership.MembershipStatus.ACTIVE
        membership.save(update_fields=["status"])
        return Response(AgentMembershipSerializer(membership).data)

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only review agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )
        if membership.status != "pending":
            return Response(
                {
                    "detail": f"Cannot review membership with status '{membership.status}'."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership.status = AgentCompanyMembership.MembershipStatus.REVIEWED
        membership.reviewed_by = request.user
        membership.reviewed_at = now()
        membership.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        return Response(AgentMembershipSerializer(membership).data)

    # --- Multi-Company Support ---

    @action(detail=False, methods=["get"], url_path="my-companies")
    def my_companies(self, request, *args, **kwargs):
        agent_profile = getattr(request.user, "agent_profile", None)
        if not agent_profile:
            return Response(
                {"detail": "Agent profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        today = now()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        memberships = (
            AgentCompanyMembership.objects.filter(
                agent=agent_profile,
            )
            .select_related("company")
            .order_by("-created_at")
        )

        data = []
        for m in memberships:
            order_count = Order.objects.filter(
                company=m.company,
                agent=agent_profile,
                submitted_at__gte=month_start,
            ).count()

            data.append(
                {
                    "id": str(m.company.id),
                    "name": m.company.name,
                    "logo": None,
                    "membership_id": str(m.id),
                    "membership_status": m.status,
                    "territory": m.territory,
                    "order_count": order_count,
                }
            )

        return Response(AgentCompanySerializer(data, many=True).data)

    @action(detail=False, methods=["post"], url_path="switch-company")
    def switch_company(self, request, *args, **kwargs):
        company_id = request.data.get("company_id")
        if not company_id:
            return Response(
                {"detail": "company_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        agent_profile = getattr(request.user, "agent_profile", None)
        if not agent_profile:
            return Response(
                {"detail": "Agent profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        membership = AgentCompanyMembership.objects.filter(
            agent=agent_profile,
            company_id=company_id,
            status="active",
        ).first()

        if not membership:
            return Response(
                {"detail": "You do not have an active membership in this company."},
                status=status.HTTP_403_FORBIDDEN,
            )

        from rest_framework_simplejwt.tokens import RefreshToken

        refresh = RefreshToken.for_user(request.user)
        refresh["role"] = request.user.role
        refresh["company_id"] = str(company_id)
        refresh["is_super_admin"] = False

        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "company_id": str(company_id),
                "company_name": membership.company.name,
            }
        )

    # --- Agent Performance ---

    def _compute_performance(self, agent_profile, company):
        today = now()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        base_orders = Order.objects.filter(
            company=company,
            agent=agent_profile,
            submitted_at__isnull=False,
        )

        orders_this_month = base_orders.filter(
            submitted_at__gte=month_start,
        ).count()

        sales_this_month = (
            base_orders.filter(
                submitted_at__gte=month_start,
            ).aggregate(total=Sum("total_amount"))["total"]
            or 0
        )

        commission_earned = (
            CommissionEntry.objects.filter(
                agent=agent_profile,
                order__company=company,
                settlement_month__gte=month_start,
                status__in=["approved", "paid"],
            ).aggregate(total=Sum("commission_amount"))["total"]
            or 0
        )

        commission_preview = (
            CommissionEntry.objects.filter(
                agent=agent_profile,
                order__company=company,
                order__status="draft",
            ).aggregate(total=Sum("commission_amount"))["total"]
            or 0
        )

        membership = AgentCompanyMembership.objects.filter(
            agent=agent_profile, company=company
        ).first()

        monthly_target = membership.monthly_target if membership else None
        leaderboard_rank = agent_profile.leaderboard_rank

        mtd_sales_by_agent = (
            Order.objects.filter(
                company=company,
                agent__isnull=False,
                submitted_at__gte=month_start,
            )
            .values("agent_id")
            .annotate(mtd_sales=Sum("total_amount"))
            .order_by("-mtd_sales")
        )

        rank = None
        for i, entry in enumerate(mtd_sales_by_agent, start=1):
            if entry["agent_id"] == agent_profile.id:
                rank = i
                break

        target_vs_actual = None
        if monthly_target and monthly_target > 0:
            target_vs_actual = float(sales_this_month) / float(monthly_target) * 100

        return {
            "orders_this_month": orders_this_month,
            "sales_this_month": sales_this_month,
            "commission_earned": commission_earned,
            "commission_preview": commission_preview,
            "leaderboard_rank": rank,
            "target_vs_actual": round(target_vs_actual, 1)
            if target_vs_actual is not None
            else None,
            "monthly_target": monthly_target,
        }

    @action(detail=False, methods=["get"], url_path="my-performance")
    def my_performance(self, request, *args, **kwargs):
        agent_profile = getattr(request.user, "agent_profile", None)
        if not agent_profile:
            return Response(
                {"detail": "Agent profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        company = getattr(request, "company", None)
        if not company:
            return Response(
                {
                    "detail": "No active company context. Use X-Company-Id header or switch company."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = self._compute_performance(agent_profile, company)
        return Response(AgentPerformanceSerializer(data).data)

    @action(detail=True, methods=["get"], url_path="performance")
    def agent_performance(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if (
            request.user.role != "superadmin"
            and membership.company_id != request.user.company_id
        ):
            return Response(
                {"detail": "You can only view agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = self._compute_performance(membership.agent, membership.company)
        return Response(AgentPerformanceSerializer(data).data)

    @action(detail=False, methods=["get"])
    def leaderboard(self, request, *args, **kwargs):
        if request.user.role == "superadmin":
            company_id = request.query_params.get("company_id")
            if not company_id:
                return Response(
                    {
                        "detail": "company_id query parameter is required for super admin."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            company_id = request.user.company_id

        today = now()
        month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        mtd_sales = (
            Order.objects.filter(
                company_id=company_id,
                agent__isnull=False,
                submitted_at__gte=month_start,
            )
            .values("agent_id")
            .annotate(
                sales_this_month=Coalesce(
                    Sum("total_amount"),
                    Value(0, output_field=DecimalField()),
                ),
                orders_this_month=Count("id"),
            )
            .order_by("-sales_this_month")
        )

        memberships = AgentCompanyMembership.objects.filter(
            company_id=company_id,
            status="active",
        ).select_related("agent__user")

        membership_map = {str(m.agent_id): m for m in memberships}

        result = []
        for rank, entry in enumerate(mtd_sales, start=1):
            agent_id = entry["agent_id"]
            membership = membership_map.get(str(agent_id))
            if not membership:
                continue
            result.append(
                {
                    "agent_id": agent_id,
                    "full_name": membership.agent.user.full_name,
                    "email": membership.agent.user.email,
                    "phone": membership.agent.user.phone,
                    "territory": membership.territory,
                    "orders_this_month": entry["orders_this_month"],
                    "sales_this_month": entry["sales_this_month"],
                    "rank": rank,
                }
            )

        return Response(AgentLeaderboardSerializer(result, many=True).data)
