# apps/dispatch/urls.py

from django.urls import path

from apps.dispatch.views import DispatchViewSet

app_name = "dispatch"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # DISPATCHES
    # ─────────────────────────────────────────────────────────────
    # GET    /api/dispatches/                      List dispatches
    #          ?status=pending|delivered
    #          ?date_from=  ?date_to=  ?search=<lr_number|order_number>
    # POST   /api/dispatches/                      Create dispatch record
    #          Advances order → DISPATCHED
    #          Converts reserved stock → OUT movement
    #          Queues: sales invoice generation + WhatsApp notification
    #
    # GET    /api/dispatches/<pk>/                 Dispatch detail
    # PATCH  /api/dispatches/<pk>/                 Update tracking / logistics info
    # POST   /api/dispatches/<pk>/mark-delivered/  Mark as delivered → order → DELIVERED
    path(
        "dispatches/",
        DispatchViewSet.as_view({"get": "list", "post": "create"}),
        name="dispatch-list-create",
    ),
    path(
        "dispatches/<uuid:pk>/",
        DispatchViewSet.as_view(
            {
                "get": "retrieve",
                "patch": "partial_update",
            }
        ),
        name="dispatch-detail",
    ),
    path(
        "dispatches/<uuid:pk>/mark-delivered/",
        DispatchViewSet.as_view({"post": "mark_delivered"}),
        name="dispatch-mark-delivered",
    ),
]
