from django.urls import path

from apps.companies.views import SuperAdminCompanyViewSet

urlpatterns = [
    path(
        "super-admin/companies",
        SuperAdminCompanyViewSet.as_view({"get": "list"}),
        name="super-admin-companies-list",
    ),
    path(
        "super-admin/companies/<uuid:pk>",
        SuperAdminCompanyViewSet.as_view({"get": "retrieve"}),
        name="super-admin-companies-detail",
    ),
    path(
        "super-admin/companies/<uuid:pk>/status",
        SuperAdminCompanyViewSet.as_view({"post": "update_status"}),
        name="super-admin-companies-status",
    ),
]
