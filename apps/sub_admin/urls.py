from django.urls import path

from apps.sub_admin.views import RoleTemplateViewSet, SubAdminViewSet

app_name = "sub_admin"

urlpatterns = [
    path(
        "admin/sub-admins",
        SubAdminViewSet.as_view({"get": "list", "post": "create"}),
        name="sub-admin-list",
    ),
    path(
        "admin/sub-admins/<uuid:pk>",
        SubAdminViewSet.as_view(
            {
                "get": "retrieve",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="sub-admin-detail",
    ),
    path(
        "admin/sub-admins/<uuid:pk>/restrict-agents",
        SubAdminViewSet.as_view({"post": "restrict_agents"}),
        name="sub-admin-restrict-agents",
    ),
    path(
        "admin/sub-admins/<uuid:pk>/restrict-categories",
        SubAdminViewSet.as_view({"post": "restrict_categories"}),
        name="sub-admin-restrict-categories",
    ),
    path(
        "admin/role-templates",
        RoleTemplateViewSet.as_view({"get": "list", "post": "create"}),
        name="role-template-list",
    ),
    path(
        "admin/role-templates/<uuid:pk>",
        RoleTemplateViewSet.as_view(
            {
                "get": "retrieve",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="role-template-detail",
    ),
]