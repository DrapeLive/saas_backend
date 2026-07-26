from typing import ClassVar

from rest_framework import serializers

from apps.tally_integrations.models import TallyLedgerMapping, TallySyncLog


class TallySyncLogListSerializer(serializers.ModelSerializer):
    class Meta:
        model = TallySyncLog
        fields: ClassVar = [
            "id",
            "direction",
            "entity_type",
            "entity_id",
            "status",
            "retry_count",
            "synced_at",
            "created_at",
        ]


class TallySyncLogDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = TallySyncLog
        fields: ClassVar = [
            "id",
            "direction",
            "entity_type",
            "entity_id",
            "status",
            "request_payload",
            "response_payload",
            "error_message",
            "retry_count",
            "synced_at",
            "created_at",
            "updated_at",
        ]


class TallyLedgerMappingSerializer(serializers.ModelSerializer):
    class Meta:
        model = TallyLedgerMapping
        fields: ClassVar = [
            "id",
            "entity_type",
            "entity_id",
            "tally_ledger_name",
            "tally_group",
            "created_at",
            "updated_at",
        ]


class TallyLedgerMappingCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = TallyLedgerMapping
        fields: ClassVar = [
            "entity_type",
            "entity_id",
            "tally_ledger_name",
            "tally_group",
        ]

    def validate_entity_type(self, value):
        allowed = ["customer", "expense", "income", "agent"]
        if value not in allowed:
            raise serializers.ValidationError(
                f"entity_type must be one of: {', '.join(allowed)}."
            )
        return value


class TallySyncTriggerSerializer(serializers.Serializer):
    """
    Manually trigger a Tally sync for a specific entity.
    Queues a Celery task.
    """

    entity_type = serializers.ChoiceField(
        choices=["invoice", "payment", "product", "ledger", "all"]
    )
    entity_id = serializers.UUIDField(
        required=False,
        help_text="Required for all entity types except 'all'.",
    )
    direction = serializers.ChoiceField(
        choices=TallySyncLog.Direction.choices, default=TallySyncLog.Direction.PUSH
    )

    def validate(self, attrs):
        if attrs["entity_type"] != "all" and not attrs.get("entity_id"):
            raise serializers.ValidationError(
                {"entity_id": "entity_id is required when entity_type is not 'all'."}
            )
        return attrs


class TallySyncRetrySerializer(serializers.Serializer):
    """Retry one or more failed sync log entries."""

    log_ids = serializers.ListField(
        child=serializers.UUIDField(), min_length=1, max_length=50
    )

    def validate_log_ids(self, value):
        failed = TallySyncLog.objects.filter(
            id__in=value, status=TallySyncLog.SyncStatus.FAILED
        )
        if failed.count() != len(value):
            raise serializers.ValidationError(
                "One or more log IDs not found or are not in 'failed' status."
            )
        return value


class TallyConnectionTestSerializer(serializers.Serializer):
    """Test the Tally HTTP gateway connection for a company."""

    tally_url = serializers.URLField()
    tally_company = serializers.CharField(max_length=200)


class TallySyncStatusSummarySerializer(serializers.Serializer):
    """Read-only sync health summary for the Tally settings page."""

    total_synced = serializers.IntegerField()
    total_pending = serializers.IntegerField()
    total_failed = serializers.IntegerField()
    last_synced_at = serializers.DateTimeField(allow_null=True)
    last_error = serializers.CharField(allow_null=True)
