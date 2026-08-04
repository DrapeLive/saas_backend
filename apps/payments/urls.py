# apps/payments/urls.py

from django.urls import path

from apps.payments.views import OutstandingAgingViewSet, PaymentViewSet

app_name = "payments"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # PAYMENTS
    # ─────────────────────────────────────────────────────────────
    # GET    /api/payments/              List payments
    #          ?customer_id=  ?agent_id=  ?mode=cash|bank|upi|cheque|neft|other
    #          ?date_from=    ?date_to=
    # POST   /api/payments/              Record a payment
    #          Updates invoice amount_paid / amount_due / status
    #          Updates customer credit_utilized + total_outstanding
    #          Queues WhatsApp receipt notification
    #
    # GET    /api/payments/<pk>/         Payment detail
    # DELETE /api/payments/<pk>/         Delete (Tally-synced payments blocked)
    path(
        "payments/",
        PaymentViewSet.as_view({"get": "list", "post": "create"}),
        name="payment-list-create",
    ),
    path(
        "payments/<uuid:pk>/",
        PaymentViewSet.as_view(
            {
                "get": "retrieve",
                "delete": "destroy",
            }
        ),
        name="payment-detail",
    ),
    # ─────────────────────────────────────────────────────────────
    # OUTSTANDING AGING
    # ─────────────────────────────────────────────────────────────
    # GET    /api/outstanding/                    Aging per customer
    #          ?agent_id=   ?overdue_only=true   ?segment=
    # GET    /api/outstanding/summary/            Aggregated aging dashboard widget
    # POST   /api/outstanding/send-reminder/      Bulk WhatsApp / email reminder
    path(
        "outstanding/",
        OutstandingAgingViewSet.as_view({"get": "list"}),
        name="outstanding-list",
    ),
    path(
        "outstanding/summary/",
        OutstandingAgingViewSet.as_view({"get": "summary"}),
        name="outstanding-summary",
    ),
    path(
        "outstanding/send-reminder/",
        OutstandingAgingViewSet.as_view({"post": "send_reminder"}),
        name="outstanding-send-reminder",
    ),
]
