# apps/notifications/urls.py

from django.urls import path

from apps.notifications.views import NotificationTemplateViewSet, NotificationViewSet

app_name = "notifications"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # NOTIFICATION TEMPLATES  (Admin manages)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/notification-templates/          List (company + platform defaults)
    # POST   /api/notification-templates/          Create custom template
    # GET    /api/notification-templates/<pk>/     Template detail
    # PATCH  /api/notification-templates/<pk>/     Update template body / subject
    # DELETE /api/notification-templates/<pk>/     Delete (company-owned only)
    path(
        "notification-templates/",
        NotificationTemplateViewSet.as_view({"get": "list", "post": "create"}),
        name="notification-template-list-create",
    ),
    path(
        "notification-templates/<uuid:pk>/",
        NotificationTemplateViewSet.as_view(
            {
                "get": "retrieve",
                "patch": "partial_update",
                "delete": "destroy",
            }
        ),
        name="notification-template-detail",
    ),
    # ─────────────────────────────────────────────────────────────
    # NOTIFICATIONS  (Admin / SubAdmin)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/notifications/          List notification dispatch records
    #          ?channel=whatsapp|email|push|in_app|sms
    #          ?status=queued|sent|delivered|failed|read
    #          ?date_from=
    # GET    /api/notifications/<pk>/     Notification detail with delivery timestamps
    # POST   /api/notifications/send/     Send ad-hoc notification (Admin only)
    # POST   /api/notifications/retry/    Retry a failed notification (Admin only)
    path(
        "notifications/",
        NotificationViewSet.as_view({"get": "list"}),
        name="notification-list",
    ),
    path(
        "notifications/<uuid:pk>/",
        NotificationViewSet.as_view({"get": "retrieve"}),
        name="notification-detail",
    ),
    path(
        "notifications/send/",
        NotificationViewSet.as_view({"post": "send"}),
        name="notification-send",
    ),
    path(
        "notifications/retry/",
        NotificationViewSet.as_view({"post": "retry"}),
        name="notification-retry",
    ),
]
