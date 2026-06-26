from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    AdminAnalyticsViewSet,
    AdminDashboardViewSet,
    AdminUserViewSet,
    AgentRegisterView,
    AuthViewSet,
    InvitationViewSet,
    LoginView,
    SignupView,
    SuperAdminDashboardViewSet,
)

urlpatterns = [
    path("auth/login", LoginView.as_view(), name="auth-login"),
    path("auth/refresh", TokenRefreshView.as_view(), name="auth-refresh"),
    path("auth/signup", SignupView.as_view({"post": "create"}), name="auth-signup"),
    path(
        "auth/agents/register",
        AgentRegisterView.as_view({"post": "create"}),
        name="auth-agent-register",
    ),
    path("auth/me", AuthViewSet.as_view({"get": "me", "patch": "me"}), name="auth-me"),
    path(
        "auth/password/change",
        AuthViewSet.as_view({"post": "password_change"}),
        name="auth-password-change",
    ),
    path(
        "auth/password/reset",
        AuthViewSet.as_view({"post": "password_reset"}),
        name="auth-password-reset",
    ),
    path(
        "auth/password/reset/confirm",
        AuthViewSet.as_view({"post": "password_reset_confirm"}),
        name="auth-password-reset-confirm",
    ),
    path(
        "auth/logout",
        AuthViewSet.as_view({"post": "logout"}),
        name="auth-logout",
    ),
    path(
        "auth/agents/join",
        AuthViewSet.as_view({"post": "join_company"}),
        name="auth-agent-join",
    ),
    # Admin endpoints
    path(
        "admin/users",
        AdminUserViewSet.as_view(
            {"get": "list", "post": "create_sub_admin"}
        ),
        name="admin-users-list",
    ),
    path(
        "admin/users/<uuid:pk>",
        AdminUserViewSet.as_view(
            {"patch": "update", "delete": "destroy"}
        ),
        name="admin-users-detail",
    ),
    path(
        "admin/invitations",
        InvitationViewSet.as_view({"get": "list", "post": "create"}),
        name="admin-invitations",
    ),
    path(
        "admin/dashboard",
        AdminDashboardViewSet.as_view({"get": "list"}),
        name="admin-dashboard",
    ),
    path(
        "admin/analytics",
        AdminAnalyticsViewSet.as_view({"get": "list"}),
        name="admin-analytics",
    ),
    path(
        "super-admin/dashboard",
        SuperAdminDashboardViewSet.as_view({"get": "list"}),
        name="super-admin-dashboard",
    ),
]
