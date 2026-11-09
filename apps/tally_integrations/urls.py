from django.urls import path

from apps.tally_integrations.views import TallyLedgerMappingViewSet, TallySyncLogViewSet

app_name = "tally_integration"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # TALLY SYNC LOGS  (read-only for Admin / SubAdmin)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/tally/logs/                 List sync logs (last 200)
    #          ?direction=push|pull
    #          ?status=pending|success|failed|retry
    #          ?entity_type=invoice|payment|product|ledger
    # GET    /api/tally/logs/<pk>/            Full log detail with request/response payloads
    # GET    /api/tally/status/               Sync health summary (total synced/pending/failed)
    path(
        "tally/logs/",
        TallySyncLogViewSet.as_view({"get": "list"}),
        name="tally-log-list",
    ),
    path(
        "tally/logs/<uuid:pk>/",
        TallySyncLogViewSet.as_view({"get": "retrieve"}),
        name="tally-log-detail",
    ),
    path(
        "tally/status/",
        TallySyncLogViewSet.as_view({"get": "sync_status"}),
        name="tally-status",
    ),
    # ─────────────────────────────────────────────────────────────
    # TALLY ACTIONS  (Admin only)
    # ─────────────────────────────────────────────────────────────
    # POST   /api/tally/trigger/              Manually trigger a sync (queues Celery task)
    # POST   /api/tally/retry/                Retry one or more failed log entries
    # POST   /api/tally/test-connection/      Test Tally HTTP gateway connectivity
    path(
        "tally/trigger/",
        TallySyncLogViewSet.as_view({"post": "trigger"}),
        name="tally-trigger",
    ),
    path(
        "tally/retry/",
        TallySyncLogViewSet.as_view({"post": "retry"}),
        name="tally-retry",
    ),
    path(
        "tally/test-connection/",
        TallySyncLogViewSet.as_view({"post": "test_connection"}),
        name="tally-test-connection",
    ),
    # ─────────────────────────────────────────────────────────────
    # TALLY LEDGER MAPPINGS  (Admin maps entities to Tally ledger names)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/tally/ledger-mappings/          List all mappings
    # POST   /api/tally/ledger-mappings/          Create or update mapping (upsert)
    # DELETE /api/tally/ledger-mappings/<pk>/     Delete a mapping
    path(
        "tally/ledger-mappings/",
        TallyLedgerMappingViewSet.as_view({"get": "list", "post": "create"}),
        name="tally-ledger-mapping-list-create",
    ),
    path(
        "tally/ledger-mappings/<uuid:pk>/",
        TallyLedgerMappingViewSet.as_view({"delete": "destroy"}),
        name="tally-ledger-mapping-delete",
    ),
]
