from django.db import models

from apps.core.models import TimeStampedModel, UUIDModel


class NotificationChannel(models.TextChoices):
    WHATSAPP = "whatsapp", "WhatsApp"
    EMAIL = "email", "Email"
    PUSH = "push", "Push Notification"
    IN_APP = "in_app", "In-App"
    SMS = "sms", "SMS"


class NotificationStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    SENT = "sent", "Sent"
    DELIVERED = "delivered", "Delivered"
    FAILED = "failed", "Failed"
    READ = "read", "Read"


class NotificationTemplate(UUIDModel, TimeStampedModel):
    class EventType(models.TextChoices):
        ORDER_SUBMITTED = "order_submitted", "Order Submitted"
        ORDER_CONFIRMED = "order_confirmed", "Order Confirmed"
        ORDER_DISPATCHED = "order_dispatched", "Order Dispatched"
        ORDER_DELIVERED = "order_delivered", "Order Delivered"
        ORDER_CANCELLED = "order_cancelled", "Order Cancelled"
        PAYMENT_RECEIVED = "payment_received", "Payment Received"
        PAYMENT_REMINDER = "payment_reminder", "Payment Reminder"
        LOW_STOCK_ALERT = "low_stock_alert", "Low Stock Alert"
        SUBSCRIPTION_EXPIRY = "subscription_expiry", "Subscription Expiry"
        AGENT_INVITATION = "agent_invitation", "Agent Invitation"
        COMMISSION_SETTLED = "commission_settled", "Commission Settled"

    company = models.ForeignKey(
        "companies.Company", null=True, blank=True, on_delete=models.CASCADE
    )
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    channel = models.CharField(max_length=15, choices=NotificationChannel.choices)
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    whatsapp_template_name = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "notifications_template"
        unique_together = [("company", "event_type", "channel")]


class Notification(UUIDModel):
    company = models.ForeignKey(
        "companies.Company", null=True, blank=True, on_delete=models.CASCADE
    )
    recipient = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL
    )
    recipient_phone = models.CharField(max_length=15, blank=True)
    recipient_email = models.EmailField(blank=True)
    channel = models.CharField(max_length=15, choices=NotificationChannel.choices)
    template = models.ForeignKey(
        NotificationTemplate, null=True, blank=True, on_delete=models.SET_NULL
    )
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    status = models.CharField(
        max_length=15,
        choices=NotificationStatus.choices,
        default=NotificationStatus.QUEUED,
    )
    external_id = models.CharField(
        max_length=200, blank=True
    )  # WhatsApp message ID / email ID
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications_notification"
        indexes = [
            models.Index(fields=["recipient", "status", "created_at"]),
            models.Index(fields=["channel", "status"]),
        ]
