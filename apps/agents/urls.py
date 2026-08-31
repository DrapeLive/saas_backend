# not completely verified

from django.urls import path

from apps.agents.views import AgentMembershipViewSet
from apps.agents.dashboard import AgentHomeViewSet, BroadcastViewSet

app_name = "agents"

urlpatterns = [
    # Agent home dashboard (agent UI)
    path(
        "agent/home",
        AgentHomeViewSet.as_view({"get": "home"}),
        name="agent-home",
    ),
    path(
        "agent/home/summary",
        AgentHomeViewSet.as_view({"get": "summary"}),
        name="agent-home-summary",
    ),
    path(
        "agent/home/recent-orders",
        AgentHomeViewSet.as_view({"get": "recent_orders"}),
        name="agent-home-recent-orders",
    ),
    path(
        "agent/home/broadcast",
        AgentHomeViewSet.as_view({"get": "broadcast"}),
        name="agent-home-broadcast",
    ),
    # Admin broadcast management
    path(
        "admin/broadcast/",
        BroadcastViewSet.as_view({"get": "list", "post": "create"}),
        name="admin-broadcast-list-create",
    ),
    path(
        "admin/broadcast/<uuid:pk>/",
        BroadcastViewSet.as_view({"patch": "partial_update", "delete": "destroy"}),
        name="admin-broadcast-detail",
    ),
    # Agent-facing (auth/*)
    path(
        "auth/agents/companies",
        AgentMembershipViewSet.as_view({"get": "my_companies"}),
        name="auth-agent-companies",
    ),  # ✅
    path(
        "auth/agents/switch-company",
        AgentMembershipViewSet.as_view({"post": "switch_company"}),
        name="auth-agent-switch-company",
    ),  # Not Verified
    path(
        "auth/agents/performance",
        AgentMembershipViewSet.as_view({"get": "my_performance"}),
        name="auth-agent-performance",
    ),  # No active company context. Use X-Company-Id header or switch company."
    # Admin-facing (admin/agents/*)
    path(
        "admin/agents",
        AgentMembershipViewSet.as_view({"get": "list"}),
        name="admin-agents-list",
    ),  # ✅
    path(
        "admin/agents/overview",
        AgentMembershipViewSet.as_view({"get": "overview"}),
        name="admin-agents-overview",
    ),
    path(
        "admin/agents/leaderboard",
        AgentMembershipViewSet.as_view({"get": "leaderboard"}),
        name="admin-agents-leaderboard",
    ),  # ✅
    path(
        "admin/agents/<uuid:pk>",
        AgentMembershipViewSet.as_view(
            {"get": "retrieve", "patch": "partial_update", "delete": "destroy"}
        ),
        name="admin-agents-detail",
    ),  # ✅
    path(
        "admin/agents/<uuid:pk>/approve",
        AgentMembershipViewSet.as_view({"post": "approve"}),
        name="admin-agents-approve",
    ),  # ✅
    path(
        "admin/agents/<uuid:pk>/reject",
        AgentMembershipViewSet.as_view({"post": "reject"}),
        name="admin-agents-reject",
    ),  # ✅
    path(
        "admin/agents/<uuid:pk>/suspend",
        AgentMembershipViewSet.as_view({"post": "suspend"}),
        name="admin-agents-suspend",
    ),  # ✅
    path(
        "admin/agents/<uuid:pk>/reactivate",
        AgentMembershipViewSet.as_view({"post": "reactivate"}),
        name="admin-agents-reactivate",
    ),  # ✅
    path(
        "admin/agents/<uuid:pk>/review",
        AgentMembershipViewSet.as_view({"post": "review"}),
        name="admin-agents-review",
    ),  # ✅
    path(
        "admin/agents/<uuid:pk>/performance",
        AgentMembershipViewSet.as_view({"get": "agent_performance"}),
        name="admin-agents-performance",
    ),  # ✅
    # Individual agent detail page (admin / sub-admin)
    path(
        "admin/agents/<uuid:pk>/overview",
        AgentMembershipViewSet.as_view({"get": "agent_detail"}),
        name="admin-agents-detail-overview",
    ),
    path(
        "admin/agents/<uuid:pk>/transactions",
        AgentMembershipViewSet.as_view({"get": "agent_transactions"}),
        name="admin-agents-detail-transactions",
    ),
    path(
        "admin/agents/<uuid:pk>/commission",
        AgentMembershipViewSet.as_view({"get": "agent_commission"}),
        name="admin-agents-detail-commission",
    ),
    path(
        "admin/agents/<uuid:pk>/payouts",
        AgentMembershipViewSet.as_view({"get": "agent_payouts"}),
        name="admin-agents-detail-payouts",
    ),
    path(
        "admin/agents/<uuid:pk>/adjustments",
        AgentMembershipViewSet.as_view({"get": "agent_adjustments"}),
        name="admin-agents-detail-adjustments",
    ),
]
