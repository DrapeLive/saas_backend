# apps/subscriptions/admin.py
# Bug #10 fix: all four subscription models were unregistered.

from django.contrib import admin

from apps.subscriptions.models import (
    Plan,
    Subscription,
    SubscriptionEvent,
    UsageSnapshot,
)


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "tier",
        "monthly_price",
        "yearly_price",
        "is_active",
        "display_order",
    )
    list_filter = ("tier", "is_active")
    ordering = ("display_order",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "__str__",
        "billing_cycle",
        "status",
        "current_period_start",
        "current_period_end",
        "price_paid",
    )
    list_filter = ("status", "billing_cycle", "plan__tier")
    search_fields = ("plan__name",)
    ordering = ("-created_at",)


@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = (
        "event_type",
        "subscription",
        "from_plan",
        "to_plan",
        "performed_by",
        "created_at",
    )
    list_filter = ("event_type",)
    ordering = ("-created_at",)
    readonly_fields = ("created_at",)


@admin.register(UsageSnapshot)
class UsageSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "subscription",
        "snapshot_month",
        "agent_count",
        "customer_count",
        "product_count",
        "order_count",
        "storage_used_mb",
    )
    list_filter = ("snapshot_month",)
    ordering = ("-snapshot_month",)
