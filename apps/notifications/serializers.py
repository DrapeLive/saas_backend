from typing import ClassVar

from rest_framework import serializers

from apps.notifications.models import (
    Notification,
    NotificationChannel,
    NotificationStatus,
    NotificationTemplate,
)


class NotificationTemplateListSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields: ClassVar = [
            "id",
            "event_type",
            "channel",
            "subject",
            "is_active",
            "created_at",
        ]


class NotificationTemplateDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields: ClassVar = [
            "id",
            "company",
            "event_type",
            "channel",
            "subject",
            "body",
            "whatsapp_template_name",
            "is_active",
            "created_at",
            "updated_at",
        ]


class NotificationTemplateCreateUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationTemplate
        fields: ClassVar = [
            "event_type",
            "channel",
            "subject",
            "body",
            "whatsapp_template_name",
            "is_active",
        ]

    def validate(self, attrs):
        channel = attrs.get("channel")
        if channel == NotificationChannel.WHATSAPP:
            if not attrs.get("whatsapp_template_name"):
                raise serializers.ValidationError(
                    {
                        "whatsapp_template_name": (
                            "whatsapp_template_name is required for WhatsApp templates "
                            "(must match the approved template name in Meta Business Manager)."
                        )
                    }
                )
        if channel == NotificationChannel.EMAIL:
            if not attrs.get("subject"):
                raise serializers.ValidationError(
                    {"subject": "subject is required for email templates."}
                )
        return attrs


class NotificationListSerializer(serializers.ModelSerializer):
    recipient_name = serializers.CharField(
        source="recipient.full_name", read_only=True, default=None
    )

    class Meta:
        model = Notification
        fields: ClassVar = [
            "id",
            "recipient",
            "recipient_name",
            "recipient_phone",
            "recipient_email",
            "channel",
            "subject",
            "status",
            "sent_at",
            "delivered_at",
            "read_at",
            "retry_count",
            "created_at",
        ]


class NotificationDetailSerializer(serializers.ModelSerializer):
    recipient_name = serializers.CharField(
        source="recipient.full_name", read_only=True, default=None
    )

    class Meta:
        model = Notification
        fields: ClassVar = [
            "id",
            "company",
            "recipient",
            "recipient_name",
            "recipient_phone",
            "recipient_email",
            "channel",
            "template",
            "subject",
            "body",
            "status",
            "external_id",
            "sent_at",
            "delivered_at",
            "read_at",
            "error_message",
            "retry_count",
            "created_at",
        ]


class NotificationSendSerializer(serializers.Serializer):
    """
    Manually send a notification to one or more recipients.
    Used by Admin to send ad-hoc WhatsApp / email messages.
    """

    recipient_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="List of User IDs. Provide either recipient_ids or recipient_phones.",
    )
    recipient_phones = serializers.ListField(
        child=serializers.CharField(max_length=15),
        required=False,
        help_text="List of phone numbers for WhatsApp sends without a user account.",
    )
    channel = serializers.ChoiceField(choices=NotificationChannel.choices)
    template_id = serializers.UUIDField(
        required=False,
        help_text="Use a saved template; overrides subject/body if provided.",
    )
    subject = serializers.CharField(required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("recipient_ids") and not attrs.get("recipient_phones"):
            raise serializers.ValidationError(
                "Provide at least one of recipient_ids or recipient_phones."
            )
        if not attrs.get("template_id") and not attrs.get("body"):
            raise serializers.ValidationError("Provide either a template_id or a body.")
        channel = attrs.get("channel")
        if channel == NotificationChannel.EMAIL and not attrs.get("subject"):
            raise serializers.ValidationError(
                {"subject": "subject is required for email notifications."}
            )
        return attrs


class NotificationRetrySerializer(serializers.Serializer):
    """Retry a single failed notification."""

    notification_id = serializers.UUIDField()

    def validate_notification_id(self, value):
        try:
            notif = Notification.objects.get(id=value)
        except Notification.DoesNotExist:
            raise serializers.ValidationError("Notification not found.")
        if notif.status != NotificationStatus.FAILED:
            raise serializers.ValidationError(
                "Only failed notifications can be retried."
            )
        if notif.retry_count >= 5:
            raise serializers.ValidationError("Maximum retry attempts (5) reached.")
        return value


class NotificationPreferenceSerializer(serializers.Serializer):
    """Per-user notification preference settings."""

    whatsapp_enabled = serializers.BooleanField(default=True)
    email_enabled = serializers.BooleanField(default=True)
    push_enabled = serializers.BooleanField(default=True)
    order_updates = serializers.BooleanField(default=True)
    payment_reminders = serializers.BooleanField(default=True)
    low_stock_alerts = serializers.BooleanField(default=True)
