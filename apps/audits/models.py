from django.db import models

from apps.core.models import UUIDModel


class AuditLog(UUIDModel):
    """
    Immutable audit trail for all significant actions.
    Written by middleware + signals; never edited or deleted.
    """

    company = models.ForeignKey(
        "companies.Company", null=True, blank=True, on_delete=models.SET_NULL
    )
    user = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL)
    user_role = models.CharField(max_length=20, blank=True)
    action = models.CharField(
        max_length=100
    )  # 'order.create', 'permission.update', etc.
    entity_type = models.CharField(max_length=100, blank=True)
    entity_id = models.UUIDField(null=True, blank=True)
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["company", "action", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]
