from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

# ✅ Completely Verified
from apps.accounts.views import (
    AdminAnalyticsViewSet,
    AdminDashboardViewSet,
    AdminUserViewSet,
    AgentRegisterView,
    AuthViewSet,
    BusinessStatsViewSet,
    CompanySetupViewSet,
    InvitationViewSet,
    LoginView,
    SignupView,
    SuperAdminDashboardViewSet,
)

app_name = "accounts"

urlpatterns = [
    path("auth/login", LoginView.as_view(), name="auth-login"),  # ✅
    path("auth/refresh", TokenRefreshView.as_view(), name="auth-refresh"),  # ✅
    path(
        "auth/signup", SignupView.as_view({"post": "create"}), name="auth-signup"
    ),  # ✅
    path(
        "auth/agents/register",
        AgentRegisterView.as_view({"post": "create"}),
        name="auth-agent-register",
    ),  # ✅
    path(
        "auth/me", AuthViewSet.as_view({"get": "me", "patch": "me"}), name="auth-me"
    ),  # ✅
    path(
        "auth/password/change",
        AuthViewSet.as_view({"post": "password_change"}),
        name="auth-password-change",
    ),  # ✅
    path(
        "auth/password/reset",
        AuthViewSet.as_view({"post": "password_reset"}),
        name="auth-password-reset",
    ),  # ✅
    path(
        "auth/password/reset/confirm",
        AuthViewSet.as_view({"post": "password_reset_confirm"}),
        name="auth-password-reset-confirm",
    ),  # ✅
    path(
        "auth/logout",
        AuthViewSet.as_view({"post": "logout"}),
        name="auth-logout",
    ),  # ✅
    path(
        "auth/agents/join",
        AuthViewSet.as_view({"post": "join_company"}),
        name="auth-agent-join",
    ),  # ✅
    # Admin endpoints
    path(
        "admin/users",
        AdminUserViewSet.as_view({"get": "list", "post": "create_sub_admin"}),
        name="admin-users-list",
    ),  # ✅
    path(
        "admin/users/<uuid:pk>",
        AdminUserViewSet.as_view({"patch": "update", "delete": "destroy"}),
        name="admin-users-detail",
    ),  # ✅
    path(
        "admin/invitations",
        InvitationViewSet.as_view({"get": "list", "post": "create"}),
        name="admin-invitations",
    ),  # ✅
    path(
        "admin/dashboard",
        AdminDashboardViewSet.as_view({"get": "list"}),
        name="admin-dashboard",
    ),  # ✅
    path(
        "admin/dashboard/recent-orders",
        AdminDashboardViewSet.as_view({"get": "recent_orders"}),
        name="admin-dashboard-recent-orders",
    ),  # ✅
    path(
        "admin/dashboard/low-stock-items",
        AdminDashboardViewSet.as_view({"get": "low_stock_items"}),
        name="admin-dashboard-low-stock-items",
    ),  # ✅
    path(
        "admin/dashboard/top-agents",
        AdminDashboardViewSet.as_view({"get": "top_agents"}),
        name="admin-dashboard-top-agents",
    ),  # ✅
    path(
        "admin/analytics",
        AdminAnalyticsViewSet.as_view({"get": "list"}),
        name="admin-analytics",
    ),  # ✅
    path(
        "business/stats",
        BusinessStatsViewSet.as_view({"get": "list"}),
        name="business-stats",
    ),  # ✅
    path(
        "super-admin/dashboard",
        SuperAdminDashboardViewSet.as_view({"get": "list"}),
        name="super-admin-dashboard",
    ),  # ✅
    # Setup wizard
    path(
        "admin/setup/profile",
        CompanySetupViewSet.as_view({"patch": "update_profile"}),
        name="admin-setup-profile",
    ),  # ✅
    path(
        "admin/setup/bank",
        CompanySetupViewSet.as_view({"patch": "update_bank"}),
        name="admin-setup-bank",
    ),  # ✅
    path(
        "admin/setup/invoice",
        CompanySetupViewSet.as_view({"patch": "update_invoice"}),
        name="admin-setup-invoice",
    ),  # ✅
    path(
        "admin/setup/tax",
        CompanySetupViewSet.as_view({"patch": "update_tax"}),
        name="admin-setup-tax",
    ),  # ✅
    path(
        "admin/setup/notifications",
        CompanySetupViewSet.as_view({"patch": "update_notifications"}),
        name="admin-setup-notifications",
    ),  # ✅
]
