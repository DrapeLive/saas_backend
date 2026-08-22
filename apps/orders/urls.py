# apps/orders/urls.py

from django.urls import path

from apps.accounts.permissions import IsAgent, IsAdminOrSubAdmin
from apps.orders.views import OrderViewSet

app_name = "orders"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # ORDERS  (Admin / SubAdmin / Agent)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/orders/                List orders
    #          ?status=draft|submitted|confirmed|processing|packed|ready|dispatched|delivered|cancelled|on_hold
    #          ?agent_id=   ?customer_id=   ?search=
    #          ?date_from=  ?date_to=
    #          ?pending_approval=true    (Admin approval queue)
    #          ?offline=true             (Unsynced offline orders)
    #        Agents are automatically scoped to their own orders.
    #
    # POST   /api/orders/                Create order
    #          Calculates GST, checks credit limit, reserves stock,
    #          handles offline flag, triggers approval if required.
    path(
        "orders/",
        OrderViewSet.as_view({"get": "list", "post": "create"}),
        name="order-list-create",
    ),  # ✅
    # ─────────────────────────────────────────────────────────────
    # COLLECTION-LEVEL ACTIONS
    # ─────────────────────────────────────────────────────────────
    # GET    /api/orders/kanban/         Kanban board (submitted→ready, grouped by status)
    # POST   /api/orders/sync/           Bulk offline order sync (Agent mobile app)
    path(
        "orders/kanban/",
        OrderViewSet.as_view({"get": "kanban"}, permission_classes=[IsAdminOrSubAdmin]),
        name="order-kanban",
    ),  # ✅
    path(
        "orders/sync/",
        OrderViewSet.as_view({"post": "sync_offline"}, permission_classes=[IsAgent]),
        name="order-sync-offline",
    ),  # Not checked
    # ─────────────────────────────────────────────────────────────
    # SINGLE RESOURCE
    # ─────────────────────────────────────────────────────────────
    # GET    /api/orders/<pk>/           Full detail (items + status history + signature)
    path(
        "orders/<uuid:pk>/",
        OrderViewSet.as_view({"get": "retrieve"}),
        name="order-detail",
    ),
    # ─────────────────────────────────────────────────────────────
    # RESOURCE-LEVEL ACTIONS
    # ─────────────────────────────────────────────────────────────
    # POST   /api/orders/<pk>/status/    Move order to any status (Admin / SubAdmin)
    # POST   /api/orders/<pk>/pack-items/ Record packed quantities per item (Admin / SubAdmin)
    # POST   /api/orders/<pk>/approve/   Approve or reject a pending order (Admin / SubAdmin)
    # POST   /api/orders/<pk>/cancel/    Cancel order + release reserved stock
    # POST   /api/orders/<pk>/signature/ Capture customer signature (Agent)
    path(
        "orders/<uuid:pk>/status/",
        OrderViewSet.as_view(
            {"post": "update_status"}, permission_classes=[IsAdminOrSubAdmin]
        ),
        name="order-update-status",
    ),
    path(
        "orders/<uuid:pk>/pack-items/",
        OrderViewSet.as_view(
            {"post": "pack_items"}, permission_classes=[IsAdminOrSubAdmin]
        ),
        name="order-pack-items",
    ),
    path(
        "orders/<uuid:pk>/approve/",
        OrderViewSet.as_view(
            {"post": "approve"}, permission_classes=[IsAdminOrSubAdmin]
        ),
        name="order-approve",
    ),
    path(
        "orders/<uuid:pk>/cancel/",
        OrderViewSet.as_view({"post": "cancel"}),
        name="order-cancel",
    ),
    path(
        "orders/<uuid:pk>/signature/",
        OrderViewSet.as_view(
            {"post": "capture_signature"}, permission_classes=[IsAgent]
        ),
        name="order-signature",
    ),
]
