from typing import ClassVar

from rest_framework import serializers

from apps.audits.models import AuditLog


class AuditLogListSerializer(serializers.ModelSerializer):
    """Lightweight — used in the audit trail table."""

    user_name = serializers.CharField(
        source="user.full_name", read_only=True, default=None
    )
    company_name = serializers.CharField(
        source="tenant.name", read_only=True, default=None
    )

    class Meta:
        model = AuditLog
        fields: ClassVar = [
            "id",
            "company_name",
            "user_name",
            "user_role",
            "action",
            "entity_type",
            "entity_id",
            "ip_address",
            "created_at",
        ]


class AuditLogDetailSerializer(serializers.ModelSerializer):
    """Full detail including old/new value diff."""

    user_name = serializers.CharField(
        source="user.full_name", read_only=True, default=None
    )
    user_email = serializers.CharField(
        source="user.email", read_only=True, default=None
    )
    company_name = serializers.CharField(
        source="tenant.name", read_only=True, default=None
    )

    class Meta:
        model = AuditLog
        fields: ClassVar = [
            "id",
            "tenant",
            "company_name",
            "user",
            "user_name",
            "user_email",
            "user_role",
            "action",
            "entity_type",
            "entity_id",
            "old_value",
            "new_value",
            "ip_address",
            "user_agent",
            "created_at",
        ]


class AuditLogFilterSerializer(serializers.Serializer):
    """
    Query parameter validation for the audit log filter panel.
    All fields are optional — any combination is valid.
    """

    user_id = serializers.UUIDField(required=False)
    user_role = serializers.CharField(required=False)
    action = serializers.CharField(
        required=False,
        help_text="Exact action string, e.g. 'order.create', 'company.suspend'.",
    )
    entity_type = serializers.CharField(required=False)
    entity_id = serializers.UUIDField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    ip_address = serializers.IPAddressField(required=False)

    def validate(self, attrs):
        date_from = attrs.get("date_from")
        date_to = attrs.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(
                {"date_from": "date_from cannot be after date_to."}
            )
        return attrs
