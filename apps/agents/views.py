from django.db.models import (
    Count,
    DecimalField,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.utils.timezone import now
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
from apps.accounts.permissions import (
    CanManageUsers,
    CompanyApproved,
    IsAdmin,
    IsAdminOrSubAdmin,
    IsAgent,
)
from apps.agents import agent_detail as agent_detail_service
from apps.agents.detail_serializers import (
    AgentAdjustmentSerializer,
    AgentCommissionSerializer,
    AgentOverviewDetailSerializer,
    AgentPayoutSerializer,
    AgentTransactionSerializer,
)
from apps.agents.models import AgentCompanyMembership, AgentProfile
from apps.agents.serializers import (
    AgentCompanySerializer,
    AgentLeaderboardSerializer,
    AgentMembershipSerializer,
    AgentMembershipUpdateSerializer,
    AgentOverviewSerializer,
    AgentPerformanceSerializer,
    SwitchCompanyRequestSerializer,
    SwitchCompanyResponseSerializer,
)
from apps.commissions.models import CommissionEntry, CommissionPayout
from apps.core.openapi import (
    COMPANY_HEADER_PARAM,
    RESPONSE_400,
    RESPONSE_403,
    RESPONSE_404,
    DetailResponseSerializer,
)
from apps.core.pagination import DefaultPageNumberPagination
from apps.orders.models import Order


@extend_schema_view(
    list=extend_schema(
        tags=["Agents"],
        summary="List agent memberships",
        description=(
            "Company admin/sub-admin: lists agent memberships for the caller's "
            "company, newest first. Paginated; supports `status`, `search`, "
            "`page` and `page_size`."
        ),
        parameters=[
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description=(
                    "Filter by membership status: pending | reviewed | active | "
                    "suspended | removed."
                ),
                required=False,
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Search by agent full name, email or employee code.",
                required=False,
            ),
        ],
        responses={200: AgentMembershipSerializer(many=True), 401: RESPONSE_400},
    ),
    overview=extend_schema(
        tags=["Agents"],
        summary="Agents dashboard overview",
        description="Headline agent metrics and the 10 most recent payouts.",
        responses={200: AgentOverviewSerializer},
    ),
    leaderboard=extend_schema(
        tags=["Agents"],
        summary="Agent leaderboard",
        description="Agents ranked by month-to-date sales for the caller's company.",
        responses={200: AgentLeaderboardSerializer(many=True)},
    ),
    retrieve=extend_schema(
        tags=["Agents"],
        summary="Get agent membership",
        responses={
            200: AgentMembershipSerializer,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    partial_update=extend_schema(
        tags=["Agents"],
        summary="Update agent membership",
        description="Updates `territory`, `monthly_target` or `custom_commission_plan`.",
        responses={
            200: AgentMembershipSerializer,
            400: RESPONSE_400,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    destroy=extend_schema(
        tags=["Agents"],
        summary="Remove agent from company",
        description=(
            "Marks the membership `removed` and deactivates the agent's login. "
            "Returns 204 on success."
        ),
        responses={204: None, 403: RESPONSE_403, 404: RESPONSE_404},
    ),
    approve=extend_schema(
        tags=["Agents"],
        summary="Approve agent membership",
        responses={
            200: AgentMembershipSerializer,
            400: RESPONSE_400,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    reject=extend_schema(
        tags=["Agents"],
        summary="Reject agent membership",
        responses={
            200: DetailResponseSerializer,
            400: RESPONSE_400,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    suspend=extend_schema(
        tags=["Agents"],
        summary="Suspend agent",
        responses={
            200: AgentMembershipSerializer,
            400: RESPONSE_400,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    reactivate=extend_schema(
        tags=["Agents"],
        summary="Reactivate agent",
        responses={
            200: AgentMembershipSerializer,
            400: RESPONSE_400,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    review=extend_schema(
        tags=["Agents"],
        summary="Mark agent for review",
        responses={
            200: AgentMembershipSerializer,
            400: RESPONSE_400,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    my_companies=extend_schema(
        tags=["Agents"],
        summary="My companies (agent)",
        description="Agent-facing. Lists the companies the agent belongs to with this month's order counts.",
        parameters=[COMPANY_HEADER_PARAM],
        responses={200: AgentCompanySerializer(many=True)},
    ),
    switch_company=extend_schema(
        tags=["Agents"],
        summary="Switch active company (agent)",
        description=(
            "Agent-facing. Issues a fresh JWT scoped to a different company the "
            "agent has an active membership in."
        ),
        parameters=[COMPANY_HEADER_PARAM],
        request=SwitchCompanyRequestSerializer,
        responses={
            200: SwitchCompanyResponseSerializer,
            400: RESPONSE_400,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    my_performance=extend_schema(
        tags=["Agents"],
        summary="My performance (agent)",
        description=(
            "Agent-facing. Performance for the current company selected via JWT "
            "`company_id` claim or `X-Company-Id` header."
        ),
        parameters=[COMPANY_HEADER_PARAM],
        responses={200: AgentPerformanceSerializer, 400: RESPONSE_400},
    ),
    agent_performance=extend_schema(
        tags=["Agents"],
        summary="Agent performance",
        responses={
            200: AgentPerformanceSerializer,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    agent_detail=extend_schema(
        tags=["Agents"],
        summary="Agent detail (All tab)",
        description=(
            "Admin/sub-admin. Cards (credit balance, total paid YTD, pending sync), "
            "recent transactions and the invoice tally placeholder for one agent."
        ),
        responses={
            200: AgentOverviewDetailSerializer,
            403: RESPONSE_403,
            404: RESPONSE_404,
        },
    ),
    agent_transactions=extend_schema(
        tags=["Agents"],
        summary="Agent recent transactions",
        description="Merged payout + commission feed for one agent.",
        parameters=[
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                enum=["payout", "order_commission", "adjustment"],
                description="Filter by transaction type.",
            ),
            OpenApiParameter(
                "month",
                OpenApiTypes.DATE,
                OpenApiParameter.QUERY,
                description="Settlement month (YYYY-MM-01).",
            ),
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Filter by entry status (commission/payout).",
            ),
        ],
        responses={200: AgentTransactionSerializer(many=True)},
    ),
    agent_commission=extend_schema(
        tags=["Agents"],
        summary="Agent commissions",
        parameters=[
            OpenApiParameter(
                "month",
                OpenApiTypes.DATE,
                OpenApiParameter.QUERY,
                description="Settlement month (YYYY-MM-01).",
            ),
            OpenApiParameter(
                "status",
                OpenApiTypes.STR,
                OpenApiParameter.QUERY,
                description="Filter by entry status: pending|approved|paid|disputed|adjusted.",
            ),
        ],
        responses={200: AgentCommissionSerializer(many=True)},
    ),
    agent_payouts=extend_schema(
        tags=["Agents"],
        summary="Agent payouts",
        responses={200: AgentPayoutSerializer(many=True)},
    ),
    agent_adjustments=extend_schema(
        tags=["Agents"],
        summary="Agent adjustments",
        description="Commission entries marked as `adjusted` for one agent.",
        responses={200: AgentAdjustmentSerializer(many=True)},
    ),
)
class AgentMembershipViewSet(GenericViewSet):
    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAuthenticated,)
    pagination_class = DefaultPageNumberPagination

    def get_serializer_class(self):
        if self.action == "partial_update":
            return AgentMembershipUpdateSerializer
        if self.action == "overview":
            return AgentOverviewSerializer
        if self.action == "my_performance":
            return AgentPerformanceSerializer
        return AgentMembershipSerializer

    def get_queryset(self):
        return AgentCompanyMembership.objects.select_related(
            "agent__user",
            "company",
            "custom_commission_plan",
            "approved_by",
            "reviewed_by",
        )

    @staticmethod
    def _agent_stats_annotations():
        """
        Subquery-based aggregates so multi-join annotations never
        multiply rows across each other.
        """
        commissions = CommissionEntry.objects.filter(
            agent=OuterRef("agent"),
            company=OuterRef("company"),
        )
        clients = (
            Order.objects.filter(
                agent=OuterRef("agent"),
                company=OuterRef("company"),
            )
            .values("agent")
            .annotate(c=Count("customer", distinct=True))
            .values("c")[:1]
        )

        def total_subquery(extra_filter=None):
            qs = commissions
            if extra_filter is not None:
                qs = qs.filter(extra_filter)
            return Coalesce(
                Subquery(
                    qs.values("agent")
                    .annotate(t=Sum("commission_amount"))
                    .values("t")[:1]
                ),
                Value(0),
                output_field=DecimalField(),
            )

        return {
            "clients_count": Subquery(clients, output_field=IntegerField()),
            "commission_total": total_subquery(),
            "commission_pending": total_subquery(Q(status__in=["pending", "approved"])),
        }

    def get_permissions(self):
        if self.action in (
            "list",
            "memberships",
            "overview",
            "agent_detail",
            "agent_transactions",
            "agent_commission",
            "agent_payouts",
            "agent_adjustments",
        ):
            return [IsAuthenticated(), CompanyApproved(), IsAdminOrSubAdmin()]
        if self.action in (
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

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset().filter(company=request.user.company)

        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(agent__user__full_name__icontains=search)
                | Q(agent__user__email__icontains=search)
                | Q(agent__employee_code__icontains=search)
            )

        queryset = queryset.annotate(**self._agent_stats_annotations()).order_by(
            "-created_at"
        )

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = AgentMembershipSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = AgentMembershipSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="agent-memberships")
    def memberships(self, request, *args, **kwargs):
        queryset = (
            self.get_queryset()
            .filter(company=request.user.company)
            .order_by("-created_at")
        )

        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = AgentMembershipSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = AgentMembershipSerializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="overview")
    def overview(self, request, *args, **kwargs):
        company = request.user.company

        active_agents = AgentCompanyMembership.objects.filter(
            company=company,
            status=AgentCompanyMembership.MembershipStatus.ACTIVE,
        ).count()

        pending_amount = CommissionEntry.objects.filter(company=company).aggregate(
            total=Coalesce(
                Sum(
                    "commission_amount",
                    filter=Q(status__in=["pending", "approved"]),
                ),
                Value(0),
                output_field=DecimalField(),
            )
        )["total"]

        paid_amount = CommissionPayout.objects.filter(company=company).aggregate(
            total=Coalesce(Sum("amount"), Value(0), output_field=DecimalField())
        )["total"]

        recent_payouts = (
            CommissionPayout.objects.filter(company=company)
            .select_related("agent__user", "paid_by")
            .order_by("-paid_at", "-created_at")[:10]
        )

        data = {
            "summary": {
                "active_agents": active_agents,
                "pending_payout_amount": pending_amount,
                "paid_payout_amount": paid_amount,
            },
            "recent_payouts": recent_payouts,
        }
        return Response(AgentOverviewSerializer(data).data)

    def retrieve(self, request, pk=None, *args, **kwargs):
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return Response(
                {"detail": "Membership not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        if membership.company_id != request.user.company_id:
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
        if membership.company_id != request.user.company_id:
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
        if membership.company_id != request.user.company_id:
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
        if membership.company_id != request.user.company_id:
            return Response(
                {"detail": "You can only view agents in your company."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = self._compute_performance(membership.agent, membership.company)
        return Response(AgentPerformanceSerializer(data).data)

    @action(detail=False, methods=["get"])
    def leaderboard(self, request, *args, **kwargs):
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

    # ─────────────────────────────────────────────────────────────
    # Individual agent detail page (admin / sub-admin)
    # ─────────────────────────────────────────────────────────────

    def _get_admin_membership(self, request, pk):
        """Resolve a membership within the caller's company, or None."""
        try:
            membership = self.get_queryset().get(pk=pk)
        except AgentCompanyMembership.DoesNotExist:
            return None
        if membership.company_id != request.user.company_id:
            return None
        return membership

    def _txn_params(self, request):
        return {
            "type": request.query_params.get("type"),
            "month": request.query_params.get("month"),
            "status": request.query_params.get("status"),
        }

    # GET /api/admin/agents/<pk>/overview/
    @action(detail=True, methods=["get"], url_path="overview")
    def agent_detail(self, request, pk=None, *args, **kwargs):
        membership = self._get_admin_membership(request, pk)
        if not membership:
            return Response(
                {"detail": "Agent not found."}, status=status.HTTP_404_NOT_FOUND
            )
        data = agent_detail_service.agent_overview(membership.agent, membership.company)
        return Response(AgentOverviewDetailSerializer(data).data)

    # GET /api/admin/agents/<pk>/transactions/
    @action(detail=True, methods=["get"], url_path="transactions")
    def agent_transactions(self, request, pk=None, *args, **kwargs):
        membership = self._get_admin_membership(request, pk)
        if not membership:
            return Response(
                {"detail": "Agent not found."}, status=status.HTTP_404_NOT_FOUND
            )
        params = self._txn_params(request)
        data = agent_detail_service.agent_transactions(
            membership.agent, membership.company, **params
        )
        return Response(AgentTransactionSerializer(data, many=True).data)

    # GET /api/admin/agents/<pk>/commission/
    @action(detail=True, methods=["get"], url_path="commission")
    def agent_commission(self, request, pk=None, *args, **kwargs):
        membership = self._get_admin_membership(request, pk)
        if not membership:
            return Response(
                {"detail": "Agent not found."}, status=status.HTTP_404_NOT_FOUND
            )
        qs = agent_detail_service.agent_commission(
            membership.agent,
            membership.company,
            month=request.query_params.get("month"),
            status=request.query_params.get("status"),
        )
        return Response(AgentCommissionSerializer(qs, many=True).data)

    # GET /api/admin/agents/<pk>/payouts/
    @action(detail=True, methods=["get"], url_path="payouts")
    def agent_payouts(self, request, pk=None, *args, **kwargs):
        membership = self._get_admin_membership(request, pk)
        if not membership:
            return Response(
                {"detail": "Agent not found."}, status=status.HTTP_404_NOT_FOUND
            )
        qs = agent_detail_service.agent_payouts(membership.agent, membership.company)
        return Response(AgentPayoutSerializer(qs, many=True).data)

    # GET /api/admin/agents/<pk>/adjustments/
    @action(detail=True, methods=["get"], url_path="adjustments")
    def agent_adjustments(self, request, pk=None, *args, **kwargs):
        membership = self._get_admin_membership(request, pk)
        if not membership:
            return Response(
                {"detail": "Agent not found."}, status=status.HTTP_404_NOT_FOUND
            )
        qs = agent_detail_service.agent_adjustments(
            membership.agent, membership.company
        )
        return Response(AgentAdjustmentSerializer(qs, many=True).data)
