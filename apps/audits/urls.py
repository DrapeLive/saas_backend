from django.urls import path

from apps.audits.views import AuditLogViewSet

app_name = "audit"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # AUDIT LOGS  (read-only — Admin only)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/audit-logs/              List audit logs (last 500)
    #          ?user_id=        Filter by user
    #          ?user_role=      Filter by role (admin|subadmin|agent|customer|superadmin)
    #          ?action=         Exact action string (e.g. "order.create", "company.suspend")
    #          ?entity_type=    e.g. "Order", "Company", "Customer"
    #          ?entity_id=      UUID of the specific entity
    #          ?date_from=      YYYY-MM-DD
    #          ?date_to=        YYYY-MM-DD
    #          ?ip_address=     Filter by IP
    #
    # GET    /api/audit-logs/<pk>/         Full log detail (old_value + new_value JSON diff)
    # GET    /api/audit-logs/actions/      Distinct action strings for filter dropdown
    path(
        "audit-logs/",
        AuditLogViewSet.as_view({"get": "list"}),
        name="audit-log-list",
    ),
    path(
        "audit-logs/actions/",
        AuditLogViewSet.as_view({"get": "distinct_actions"}),
        name="audit-log-actions",
    ),
    path(
        "audit-logs/<uuid:pk>/",
        AuditLogViewSet.as_view({"get": "retrieve"}),
        name="audit-log-detail",
    ),
]
