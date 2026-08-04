# apps/commissions/urls.py

from django.urls import path

from apps.commissions.views import CommissionEntryViewSet, CommissionPlanViewSet

app_name = "commissions"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # COMMISSION PLANS  (Admin manages)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/commission-plans/                          List plans
    # POST   /api/commission-plans/                          Create plan (with slabs + category rates)
    # GET    /api/commission-plans/<pk>/                     Plan detail
    # PATCH  /api/commission-plans/<pk>/                     Update plan name / description / default flag
    # DELETE /api/commission-plans/<pk>/                     Delete (blocked if default or agents assigned)
    # POST   /api/commission-plans/<pk>/slabs/               Add a slab to the plan
    # DELETE /api/commission-plans/<pk>/slabs/<slab_pk>/     Remove a slab
    # POST   /api/commission-plans/<pk>/category-rates/      Add / overwrite category rate
    path(
        "commission-plans/",
        CommissionPlanViewSet.as_view({"get": "list", "post": "create"}),
        name="commission-plan-list-create",
    ),
    path(
        "commission-plans/<uuid:pk>/",
        CommissionPlanViewSet.as_view(
            {
                "get": "retrieve",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="commission-plan-detail",
    ),
    path(
        "commission-plans/<uuid:pk>/slabs/",
        CommissionPlanViewSet.as_view({"post": "add_slab"}),
        name="commission-plan-add-slab",
    ),
    path(
        "commission-plans/<uuid:pk>/slabs/<uuid:slab_pk>/",
        CommissionPlanViewSet.as_view({"delete": "remove_slab"}),
        name="commission-plan-remove-slab",
    ),
    path(
        "commission-plans/<uuid:pk>/category-rates/",
        CommissionPlanViewSet.as_view({"post": "add_category_rate"}),
        name="commission-plan-add-category-rate",
    ),
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
