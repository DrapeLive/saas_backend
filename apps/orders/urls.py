# apps/orders/urls.py

from django.urls import path

from apps.accounts.permissions import IsAdminOrSubAdmin, IsAgent
from apps.orders.views import OrderViewSet

app_name = "orders"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # ORDERS  (Admin / SubAdmin / Agent)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/orders/                List orders
    #          ?status=submitted|confirmed|processing|packed|dispatched|delivered|cancelled
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
    # GET    /api/orders/drafts/         Agent's resumable DRAFT orders
    path(
        "orders/drafts/",
        OrderViewSet.as_view({"get": "drafts"}),
        name="order-drafts",
    ),
    # ─────────────────────────────────────────────────────────────
    # DRAFT ORDER FLOW (Agent only)
    # ─────────────────────────────────────────────────────────────
    # POST   /api/orders/<pk>/items/           Add a scanned size range
    # GET    /api/orders/<pk>/items/           (not supported, use order detail)
    # PATCH  /api/orders/<pk>/items/<item_id>/ Change a scan group quantity
    # DELETE /api/orders/<pk>/items/<item_id>/ Remove a scan group
    path(
        "orders/<uuid:pk>/items/",
        OrderViewSet.as_view({"post": "add_item"}),
        name="order-add-item",
    ),
    path(
        "orders/<uuid:pk>/add-item/",
        OrderViewSet.as_view({"post": "add_item"}),
        name="order-add-item-explicit",
    ),
    path(
        "orders/<uuid:pk>/items/<uuid:item_id>/",
        OrderViewSet.as_view(
            {"patch": "update_item", "delete": "remove_item"}
        ),
        name="order-item-detail",
    ),
    path(
        "orders/<uuid:pk>/remove-item/<uuid:item_id>/",
        OrderViewSet.as_view({"delete": "remove_item"}),
        name="order-remove-item-explicit",
    ),
    # POST   /api/orders/<pk>/submit/   Submit a DRAFT
    path(
        "orders/<uuid:pk>/submit/",
        OrderViewSet.as_view({"post": "submit"}),
        name="order-submit",
    ),
    path(
        "orders/<uuid:pk>/continue/",
        OrderViewSet.as_view({"get": "continue_order"}),
        name="order-continue",
    ),
    # ─────────────────────────────────────────────────────────────
    # COLLECTION-LEVEL ACTIONS
    # ─────────────────────────────────────────────────────────────
    # GET    /api/orders/kanban/         Kanban board (submitted→packed, grouped by status)
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
    # PATCH  /api/orders/<pk>/           Update a DRAFT's delivery/notes/discount
    # DELETE /api/orders/<pk>/           Discard a DRAFT and release its stock
    path(
        "orders/<uuid:pk>/",
        OrderViewSet.as_view(
            {"get": "retrieve", "patch": "partial_update", "delete": "discard"}
        ),
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
