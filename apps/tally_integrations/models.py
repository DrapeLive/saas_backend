from django.db import models

from apps.core.models import CompanyScopeModel


class TallySyncLog(CompanyScopeModel):
    class Direction(models.TextChoices):
        PUSH = "push", "Push to Tally"
        PULL = "pull", "Pull from Tally"

    class SyncStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        RETRY = "retry", "Retrying"

    direction = models.CharField(max_length=5, choices=Direction.choices)
    entity_type = models.CharField(
        max_length=50
    )  # 'invoice', 'payment', 'product', 'ledger'
    entity_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(
        max_length=10, choices=SyncStatus.choices, default=SyncStatus.PENDING
    )
    request_payload = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tally_sync_log"
        indexes = [
            models.Index(fields=["company", "status", "entity_type"]),
        ]


class TallyLedgerMapping(CompanyScopeModel):
    """Maps internal customers/accounts to Tally ledger names."""

    entity_type = models.CharField(max_length=50)  # 'customer', 'expense', 'income'
    entity_id = models.UUIDField()
    tally_ledger_name = models.CharField(max_length=200)
    tally_group = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "tally_ledger_mapping"
        unique_together = [("company", "entity_type", "entity_id")]
