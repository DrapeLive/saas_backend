# apps/subscriptions/views.py

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils.timezone import now
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.authentication import CustomJWTAuthentication
from apps.accounts.permissions import IsAdmin, IsSuperAdmin
from apps.subscriptions.models import (
    BillingCycle,
    Plan,
    PlanTier,
    Subscription,
    SubscriptionEvent,
    SubscriptionStatus,
    UsageSnapshot,
)
from apps.subscriptions.serializers import (
    PlanCreateUpdateSerializer,
    PlanListSerializer,
    SubscriptionCreateSerializer,
    SubscriptionDetailSerializer,
    SubscriptionEventSerializer,
    SubscriptionExtendSerializer,
    SubscriptionListSerializer,
    SubscriptionUpgradeSerializer,
    UsageSnapshotSerializer,
)

# ─────────────────────────────────────────────────────────────────
# PLAN VIEWSET  (SuperAdmin only)
# ─────────────────────────────────────────────────────────────────


class PlanViewSet(GenericViewSet):
    """
    SuperAdmin manages the 3 pricing tiers and their feature flags.
    Plans are global (not company-scoped).
    """

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsSuperAdmin,)

    def _get_plan(self, pk):
        try:
            return Plan.objects.get(pk=pk)
        except Plan.DoesNotExist:
            return None

    # GET /api/plans/
    def list(self, request):
        qs = Plan.objects.all().order_by("display_order")
        return Response(PlanListSerializer(qs, many=True).data)

    # GET /api/plans/<pk>/
    def retrieve(self, request, pk=None):
        plan = self._get_plan(pk)
        if not plan:
            return Response(
                {"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(PlanListSerializer(plan).data)

    # POST /api/plans/
    @transaction.atomic
    def create(self, request):
        serializer = PlanCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if Plan.objects.filter(tier=serializer.validated_data["tier"]).exists():
            return Response(
                {
                    "detail": f"A plan with tier '{serializer.validated_data['tier']}' already exists."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan = serializer.save()
        return Response(PlanListSerializer(plan).data, status=status.HTTP_201_CREATED)

    # PATCH /api/plans/<pk>/
    @transaction.atomic
    def partial_update(self, request, pk=None):
        plan = self._get_plan(pk)
        if not plan:
            return Response(
                {"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = PlanCreateUpdateSerializer(plan, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Bug #1 fix: use serializer.instance (updated object), not the stale local variable
        return Response(PlanListSerializer(serializer.instance).data)

    # POST /api/plans/<pk>/toggle-active/
    @action(detail=True, methods=["post"], url_path="toggle-active")
    def toggle_active(self, request, pk=None):
        plan = self._get_plan(pk)
        if not plan:
            return Response(
                {"detail": "Plan not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Prevent deactivating a plan that has active subscriptions
        if plan.is_active:
            active_count = plan.subscriptions.filter(
                status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]
            ).count()
            if active_count > 0:
                return Response(
                    {
                        "detail": (
                            f"Cannot deactivate plan '{plan.name}' — "
                            f"{active_count} active subscription(s) are on this plan. "
                            "Migrate companies to another plan first."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        plan.is_active = not plan.is_active
        plan.save(update_fields=["is_active"])
        return Response(
            {
                "id": str(plan.id),
                "tier": plan.tier,
                "name": plan.name,
                "is_active": plan.is_active,
                "detail": f"Plan '{plan.name}' {'activated' if plan.is_active else 'deactivated'}.",
            }
        )

    # POST /api/plans/seed-defaults/
    # Bug #7 fix: @transaction.atomic was bypassed by @action wrapping it.
    # Use a context manager inside the method body instead.
    @action(detail=False, methods=["post"], url_path="seed-defaults")
    def seed_defaults(self, request):
        """
        Seeds the 3 default tiers (Starter / Professional / Enterprise)
        if they don't already exist. Safe to call multiple times.
        """
        created = []
        with transaction.atomic():
            for defaults in Plan.get_defaults():
                _, was_created = Plan.objects.get_or_create(
                    tier=defaults["tier"], defaults=defaults
                )
                if was_created:
                    created.append(defaults["tier"])

        return Response(
            {
                "created": created,
                "detail": (
                    f"{len(created)} plan(s) seeded."
                    if created
                    else "All 3 default plans already exist."
                ),
            }
        )


# ─────────────────────────────────────────────────────────────────
# SUBSCRIPTION VIEWSET  (SuperAdmin manages; Admin reads own)
# ─────────────────────────────────────────────────────────────────


class SubscriptionViewSet(GenericViewSet):
    """
    SuperAdmin: full read + lifecycle management of any company's subscription.
    Admin:      read-only access to their own company's subscription.
    """

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsSuperAdmin,)

    def _get_subscription(self, pk):
        try:
            return (
                Subscription.objects.select_related("plan")
                .prefetch_related("events", "usage_snapshots")
                .get(pk=pk)
            )
        except Subscription.DoesNotExist:
            return None

    # GET /api/subscriptions/
    def list(self, request):
        qs = Subscription.objects.select_related("plan", "company").order_by(
            "-created_at"
        )

        status_f = request.query_params.get("status")
        tier_f = request.query_params.get("tier")

        if status_f:
            qs = qs.filter(status=status_f)
        if tier_f:
            qs = qs.filter(plan__tier=tier_f)

        return Response(SubscriptionListSerializer(qs, many=True).data)

    # POST /api/subscriptions/
    @transaction.atomic
    def create(self, request):
        serializer = SubscriptionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        company = serializer.context["company"]
        plan = serializer.context["plan"]
        billing_cycle = serializer.validated_data["billing_cycle"]

        status_val = (
            SubscriptionStatus.TRIAL
            if billing_cycle == BillingCycle.TRIAL
            else SubscriptionStatus.ACTIVE
        )

        subscription = Subscription.objects.create(
            plan=plan,
            billing_cycle=billing_cycle,
            status=status_val,
        )

        company.subscription = subscription
        company.save(update_fields=["subscription"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            event_type=SubscriptionEvent.EventType.CREATED,
            performed_by=request.user,
            to_plan=plan,
            notes=f"Created via API for {company.name}",
        )

        return Response(
            SubscriptionDetailSerializer(subscription).data,
            status=status.HTTP_201_CREATED,
        )

    # GET /api/subscriptions/<pk>/
    def retrieve(self, request, pk=None):
        subscription = self._get_subscription(pk)
        if not subscription:
            return Response(
                {"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(SubscriptionDetailSerializer(subscription).data)

    # POST /api/subscriptions/<pk>/upgrade/
    @action(detail=True, methods=["post"], url_path="upgrade")
    @transaction.atomic
    def upgrade(self, request, pk=None):
        """
        Upgrade or downgrade a company's subscription plan.
        Updates billing cycle, recalculates price_paid with discount,
        and writes an immutable SubscriptionEvent.
        """
        subscription = self._get_subscription(pk)
        if not subscription:
            return Response(
                {"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = SubscriptionUpgradeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        old_plan = subscription.plan
        try:
            new_plan = Plan.objects.get(id=data["plan_id"])
        except Plan.DoesNotExist:
            return Response(
                {"detail": "Plan not found or has been removed."},
                status=status.HTTP_404_NOT_FOUND,
            )
        billing_cycle = data["billing_cycle"]
        discount_pct = data.get("discount_pct", Decimal("0"))

        base_price = (
            new_plan.yearly_price
            if billing_cycle == BillingCycle.YEARLY
            else new_plan.monthly_price
        )
        price_paid = base_price * (1 - discount_pct / 100)
        is_upgrade = new_plan.monthly_price >= old_plan.monthly_price

        today = now().date()
        subscription.plan = new_plan
        subscription.billing_cycle = billing_cycle
        subscription.discount_pct = discount_pct
        subscription.price_paid = price_paid
        subscription.status = SubscriptionStatus.ACTIVE

        if billing_cycle == BillingCycle.YEARLY:
            subscription.current_period_end = today + timedelta(days=365)
        else:
            subscription.current_period_end = today + timedelta(days=30)

        subscription.current_period_start = today
        subscription.save()

        SubscriptionEvent.objects.create(
            subscription=subscription,
            event_type=(
                SubscriptionEvent.EventType.UPGRADED
                if is_upgrade
                else SubscriptionEvent.EventType.DOWNGRADED
            ),
            from_plan=old_plan,
            to_plan=new_plan,
            performed_by=request.user,
            notes=data.get("notes", ""),
            metadata={
                "billing_cycle": billing_cycle,
                "discount_pct": str(discount_pct),
                "price_paid": str(price_paid),
            },
        )

        try:
            from apps.companies.models import CompanyStatus

            subscription.company.status = CompanyStatus.ACTIVE
            subscription.company.save(update_fields=["status"])
        except Exception:
            pass

        return Response(SubscriptionDetailSerializer(subscription).data)

    # POST /api/subscriptions/<pk>/extend/
    @action(detail=True, methods=["post"], url_path="extend")
    @transaction.atomic
    def extend(self, request, pk=None):
        """
        Manually extend a subscription's current_period_end.
        Used for trial extensions, goodwill extensions, or support resolutions.
        Reactivates the subscription if it was expired or in grace period.
        """
        subscription = self._get_subscription(pk)
        if not subscription:
            return Response(
                {"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND
            )

        serializer = SubscriptionExtendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        extend_days = serializer.validated_data["extend_days"]
        notes = serializer.validated_data.get("notes", "")

        base_date = subscription.current_period_end or now().date()
        subscription.current_period_end = base_date + timedelta(days=extend_days)

        if subscription.status in [
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.GRACE,
            SubscriptionStatus.SUSPENDED,
        ]:
            subscription.status = SubscriptionStatus.ACTIVE

        subscription.save(update_fields=["current_period_end", "status"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            event_type=SubscriptionEvent.EventType.EXTENDED,
            performed_by=request.user,
            notes=notes,
            metadata={
                "extend_days": extend_days,
                "new_period_end": str(subscription.current_period_end),
            },
        )

        return Response(SubscriptionDetailSerializer(subscription).data)

    # POST /api/subscriptions/<pk>/cancel/
    @action(detail=True, methods=["post"], url_path="cancel")
    @transaction.atomic
    def cancel(self, request, pk=None):
        """
        Cancel a subscription immediately.
        Marks company as expired and writes a CANCELLED event.
        """
        subscription = self._get_subscription(pk)
        if not subscription:
            return Response(
                {"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if subscription.status == SubscriptionStatus.CANCELLED:
            return Response(
                {"detail": "Subscription is already cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = now()
        subscription.save(update_fields=["status", "cancelled_at"])

        SubscriptionEvent.objects.create(
            subscription=subscription,
            event_type=SubscriptionEvent.EventType.CANCELLED,
            performed_by=request.user,
            notes=request.data.get("notes", ""),
        )

        # Bug #4 fix: same hasattr-always-True issue; use try/except
        try:
            from apps.companies.models import CompanyStatus

            subscription.company.status = CompanyStatus.EXPIRED
            subscription.company.save(update_fields=["status"])
        except Exception:
            pass

        return Response(SubscriptionDetailSerializer(subscription).data)

    # POST /api/subscriptions/<pk>/reactivate/
    @action(detail=True, methods=["post"], url_path="reactivate")
    @transaction.atomic
    def reactivate(self, request, pk=None):
        """
        Reactivate a cancelled, expired, or suspended subscription.
        Sets a fresh 30-day period from today.
        """
        subscription = self._get_subscription(pk)
        if not subscription:
            return Response(
                {"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND
            )

        reactivatable = [
            SubscriptionStatus.CANCELLED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.SUSPENDED,
            SubscriptionStatus.GRACE,
        ]
        if subscription.status not in reactivatable:
            return Response(
                {
                    "detail": f"Subscription with status '{subscription.status}' cannot be reactivated."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        today = now().date()
        # Bug #8 fix: honour the existing billing cycle instead of always granting 30 days
        period_days = 365 if subscription.billing_cycle == BillingCycle.YEARLY else 30
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.current_period_start = today
        subscription.current_period_end = today + timedelta(days=period_days)
        subscription.cancelled_at = None
        subscription.save(
            update_fields=[
                "status",
                "current_period_start",
                "current_period_end",
                "cancelled_at",
            ]
        )

        SubscriptionEvent.objects.create(
            subscription=subscription,
            event_type=SubscriptionEvent.EventType.REACTIVATED,
            performed_by=request.user,
            notes=request.data.get("notes", ""),
        )

        # Bug #4 fix: use try/except instead of hasattr (always True for reverse OneToOne)
        try:
            from apps.companies.models import CompanyStatus

            subscription.company.status = CompanyStatus.ACTIVE
            subscription.company.save(update_fields=["status"])
        except Exception:
            pass

        return Response(SubscriptionDetailSerializer(subscription).data)

    # GET /api/subscriptions/<pk>/events/
    @action(detail=True, methods=["get"], url_path="events")
    def events(self, request, pk=None):
        """Full immutable event history for a subscription."""
        subscription = self._get_subscription(pk)
        if not subscription:
            return Response(
                {"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND
            )

        events = (
            SubscriptionEvent.objects.filter(subscription=subscription)
            .select_related("from_plan", "to_plan", "performed_by")
            .order_by("-created_at")
        )

        return Response(SubscriptionEventSerializer(events, many=True).data)

    # GET /api/subscriptions/<pk>/usage/
    @action(detail=True, methods=["get"], url_path="usage")
    def usage(self, request, pk=None):
        """Monthly usage snapshots for a subscription (newest first)."""
        subscription = self._get_subscription(pk)
        if not subscription:
            return Response(
                {"detail": "Subscription not found."}, status=status.HTTP_404_NOT_FOUND
            )

        snapshots = UsageSnapshot.objects.filter(subscription=subscription).order_by(
            "-snapshot_month"
        )

        return Response(UsageSnapshotSerializer(snapshots, many=True).data)


# ─────────────────────────────────────────────────────────────────
# COMPANY SELF-SERVICE  (Admin reads own subscription)
# ─────────────────────────────────────────────────────────────────


class MySubscriptionViewSet(GenericViewSet):
    """
    Admin-facing read-only subscription view.
    Returns the current company's own subscription — no SuperAdmin required.
    """

    authentication_classes = (CustomJWTAuthentication,)
    permission_classes = (IsAdmin,)

    def _get_subscription(self, request):
        company = getattr(request.user, "company", None)
        if not company:
            return None
        # Company.subscription is a OneToOne; use try/except to avoid RelatedObjectDoesNotExist
        try:
            return company.subscription
        except Exception:
            return None

    # GET /api/my-subscription/
    # Bug #5 fix: renamed from `retrieve` to `list` — this is a non-pk endpoint and
    # DRF's `retrieve` contract requires a pk argument. `list` is the correct action name.
    def list(self, request):
        subscription = self._get_subscription(request)
        if not subscription:
            return Response(
                {"detail": "No subscription found for your company."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(SubscriptionDetailSerializer(subscription).data)

    # GET /api/my-subscription/usage/
    @action(detail=False, methods=["get"], url_path="usage")
    def usage(self, request):
        """Usage snapshots for the current company's subscription."""
        subscription = self._get_subscription(request)
        if not subscription:
            return Response(
                {"detail": "No subscription found for your company."},
                status=status.HTTP_404_NOT_FOUND,
            )
        snapshots = UsageSnapshot.objects.filter(subscription=subscription).order_by(
            "-snapshot_month"
        )
        return Response(UsageSnapshotSerializer(snapshots, many=True).data)

    # GET /api/my-subscription/plans/
    @action(detail=False, methods=["get"], url_path="plans")
    def available_plans(self, request):
        """
        Returns all active plans for the pricing / upgrade page.
        Available to any authenticated Admin — no SuperAdmin required.
        """
        qs = Plan.objects.filter(is_active=True).order_by("display_order")
        return Response(PlanListSerializer(qs, many=True).data)
