# ✅ Completely Verified

from django.urls import path

from apps.companies.views import (
    CompanyDetailViewSet,
    CompanySettingsViewSet,
    SuperAdminCompanyViewSet,
)

app_name = "companies"

urlpatterns = [
    path(
        "admin/company",
        CompanyDetailViewSet.as_view({"patch": "update"}),
        name="admin-company-update",
    ),  # ✅
    path(
        "admin/company/settings",
        CompanySettingsViewSet.as_view({"get": "retrieve", "patch": "update"}),
        name="admin-company-settings",
    ),  # ✅
    path(
        "super-admin/companies",
        SuperAdminCompanyViewSet.as_view({"get": "list"}),
        name="super-admin-companies-list",
    ),  # ✅
    path(
        "super-admin/companies/<uuid:pk>",
        SuperAdminCompanyViewSet.as_view(
            {"get": "retrieve", "patch": "update", "delete": "destroy"}
        ),
        name="super-admin-companies-detail",
    ),  # ✅
    path(
        "super-admin/companies/<uuid:pk>/status",
        SuperAdminCompanyViewSet.as_view({"post": "update_status"}),
        name="super-admin-companies-status",
    ),  # ✅
    path(
        "super-admin/companies/<uuid:pk>/suspend",
        SuperAdminCompanyViewSet.as_view({"post": "suspend"}),
        name="super-admin-companies-suspend",
    ),  # ✅
    path(
        "super-admin/companies/<uuid:pk>/activate",
        SuperAdminCompanyViewSet.as_view({"post": "activate"}),
        name="super-admin-companies-activate",
    ),  # ✅
    path(
        "super-admin/companies/<uuid:pk>/extend-trial",
        SuperAdminCompanyViewSet.as_view({"post": "extend_trial"}),
        name="super-admin-companies-extend-trial",
    ),  # ✅
    path(
        "super-admin/companies/<uuid:pk>/impersonate",
        SuperAdminCompanyViewSet.as_view({"post": "impersonate"}),
        name="super-admin-companies-impersonate",
    ),  # ✅
]
