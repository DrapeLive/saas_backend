# not completely verified

from django.urls import path

from apps.agents.views import AgentMembershipViewSet

app_name = "agents"

urlpatterns = [
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
]
