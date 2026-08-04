# ✅ Completely Verified

from django.urls import path

from apps.subscriptions.views import (
    MySubscriptionViewSet,
    PlanViewSet,
    SubscriptionViewSet,
)

app_name = "subscriptions"

urlpatterns = [
    # ─────────────────────────────────────────────────────────────
    # PLANS  (SuperAdmin manages global pricing tiers)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/plans/                      List all plans with active subscription count
    # POST   /api/plans/                      Create a new plan tier
    # POST   /api/plans/seed-defaults/        Seed Starter / Professional / Enterprise tiers
    # GET    /api/plans/<pk>/                 Plan detail with feature flags
    # PATCH  /api/plans/<pk>/                 Update pricing / limits / feature flags
    # POST   /api/plans/<pk>/toggle-active/   Enable / disable plan
    #          (blocked if active subscriptions exist on the plan)
    path(
        "plans/",
        PlanViewSet.as_view({"get": "list", "post": "create"}),
        name="plan-list-create",
    ),  # ✅
    path(
        "plans/seed-defaults/",
        PlanViewSet.as_view({"post": "seed_defaults"}),
        name="plan-seed-defaults",
    ),  # Manually Created
    path(
        "plans/<uuid:pk>/",
        PlanViewSet.as_view(
            {
                "get": "retrieve",
                "patch": "partial_update",
            }
        ),
        name="plan-detail",
    ),  # ✅
    path(
        "plans/<uuid:pk>/toggle-active/",
        PlanViewSet.as_view({"post": "toggle_active"}),
        name="plan-toggle-active",
    ),  # ✅
    # ─────────────────────────────────────────────────────────────
    # SUBSCRIPTIONS  (SuperAdmin manages all company subscriptions)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/subscriptions/                    List all subscriptions (?status= ?tier=)
    # GET    /api/subscriptions/<pk>/               Full detail (plan + events + usage snapshots)
    # POST   /api/subscriptions/<pk>/upgrade/       Upgrade or downgrade plan + billing cycle
    #          Recalculates price_paid with discount
    #          Writes immutable SubscriptionEvent (upgraded / downgraded)
    #          Syncs company.status → active
    # POST   /api/subscriptions/<pk>/extend/        Extend current_period_end by N days
    #          Reactivates expired / grace / suspended subscriptions automatically
    # POST   /api/subscriptions/<pk>/cancel/        Cancel subscription → company marked expired
    # POST   /api/subscriptions/<pk>/reactivate/    Reactivate cancelled / expired / suspended
    #          Sets fresh 30-day period from today
    # GET    /api/subscriptions/<pk>/events/        Immutable event history (newest first)
    # GET    /api/subscriptions/<pk>/usage/         Monthly usage snapshots (newest first)
    path(
        "subscriptions/",
        SubscriptionViewSet.as_view({"get": "list", "post": "create"}),
        name="subscription-list",
    ),  # ✅
    path(
        "subscriptions/<uuid:pk>/",
        SubscriptionViewSet.as_view({"get": "retrieve"}),
        name="subscription-detail",
    ),  # ✅
    path(
        "subscriptions/<uuid:pk>/upgrade/",
        SubscriptionViewSet.as_view({"post": "upgrade"}),
        name="subscription-upgrade",
    ),  # ✅
    path(
        "subscriptions/<uuid:pk>/extend/",
        SubscriptionViewSet.as_view({"post": "extend"}),
        name="subscription-extend",
    ),  # ✅
    path(
        "subscriptions/<uuid:pk>/cancel/",
        SubscriptionViewSet.as_view({"post": "cancel"}),
        name="subscription-cancel",
    ),  # ✅
    path(
        "subscriptions/<uuid:pk>/reactivate/",
        SubscriptionViewSet.as_view({"post": "reactivate"}),
        name="subscription-reactivate",
    ),  # ✅
    path(
        "subscriptions/<uuid:pk>/events/",
        SubscriptionViewSet.as_view({"get": "events"}),
        name="subscription-events",
    ),  # ✅
    path(
        "subscriptions/<uuid:pk>/usage/",
        SubscriptionViewSet.as_view({"get": "usage"}),
        name="subscription-usage",
    ),  # ✅
    # ─────────────────────────────────────────────────────────────
    # MY SUBSCRIPTION  (Admin self-service — reads own company's subscription)
    # ─────────────────────────────────────────────────────────────
    # GET    /api/my-subscription/         Own subscription detail (plan + events + usage)
    # GET    /api/my-subscription/usage/   Own monthly usage snapshots
    # GET    /api/my-subscription/plans/   All active plans (pricing / upgrade page)
    # Bug #5 fix: action was renamed from `retrieve` to `list` (non-pk endpoint)
    path(
        "my-subscription/",
        MySubscriptionViewSet.as_view({"get": "list"}),
        name="my-subscription",
    ),  # ✅
    path(
        "my-subscription/usage/",
        MySubscriptionViewSet.as_view({"get": "usage"}),
        name="my-subscription-usage",
    ),  # ✅
    path(
        "my-subscription/plans/",
        MySubscriptionViewSet.as_view({"get": "available_plans"}),
        name="my-subscription-plans",
    ),  # ✅
]
