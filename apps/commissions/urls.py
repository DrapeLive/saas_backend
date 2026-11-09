# apps/commissions/urls.py

from django.urls import path

from apps.commissions.views import CommissionEntryViewSet

app_name = "commissions"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # COMMISSION ENTRIES  (auto-created on dispatch; Admin settles)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/commission-entries/              List entries (?agent_id= ?status= ?month=YYYY-MM-01)
    # GET    /api/commission-entries/summary/      Per-agent breakdown (?month=YYYY-MM-01)
    # POST   /api/commission-entries/settle/       Bulk-settle approved entries for agent + month
    # GET    /api/commission-entries/<pk>/         Entry detail
    # POST   /api/commission-entries/<pk>/status/  Update status (approve / dispute / adjust)
    path(
        "commission-entries/",
        CommissionEntryViewSet.as_view({"get": "list"}),
        name="commission-entry-list",
    ),
    path(
        "commission-entries/summary/",
        CommissionEntryViewSet.as_view({"get": "summary"}),
        name="commission-entry-summary",
    ),
    path(
        "commission-entries/settle/",
        CommissionEntryViewSet.as_view({"post": "settle"}),
        name="commission-entry-settle",
    ),
    path(
        "commission-entries/<uuid:pk>/",
        CommissionEntryViewSet.as_view({"get": "retrieve"}),
        name="commission-entry-detail",
    ),
    path(
        "commission-entries/<uuid:pk>/status/",
        CommissionEntryViewSet.as_view({"post": "update_status"}),
        name="commission-entry-status",
    ),
]
