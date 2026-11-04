from datetime import date, timedelta

from django.db import transaction

from apps.companies.models import CompanyStatus
from apps.companies.services import apply_plan_to_company
from apps.subscriptions.models import (
    BillingCycle,
    Subscription,
    SubscriptionPayment,
    SubscriptionStatus,
)

COMPANY_STATUS_BY_SUBSCRIPTION = {
    SubscriptionStatus.TRIAL: CompanyStatus.TRIAL,
    SubscriptionStatus.ACTIVE: CompanyStatus.ACTIVE,
    SubscriptionStatus.GRACE: CompanyStatus.GRACE,
    SubscriptionStatus.EXPIRED: CompanyStatus.EXPIRED,
    SubscriptionStatus.CANCELLED: CompanyStatus.EXPIRED,
    SubscriptionStatus.SUSPENDED: CompanyStatus.SUSPENDED,
}


def sync_company_from_subscription(subscription: Subscription) -> None:
    """Keep the company lifecycle and plan entitlements aligned with its subscription."""
    company = subscription.company
    company.status = COMPANY_STATUS_BY_SUBSCRIPTION[subscription.status]
    company.save(update_fields=["status"])
    apply_plan_to_company(company, subscription.plan)


def set_subscription_status(
    subscription: Subscription,
    status: str,
    *,
    today: date,
    reset_period: bool = False,
) -> Subscription:
    """Apply a subscription state transition and synchronize its company."""
    subscription.status = status

    if status == SubscriptionStatus.TRIAL:
        if reset_period or not subscription.trial_start:
            subscription.trial_start = today
        if reset_period or not subscription.trial_end:
            subscription.trial_end = today + timedelta(days=subscription.plan.trial_days)
        subscription.current_period_start = subscription.trial_start
        subscription.current_period_end = subscription.trial_end
        subscription.grace_period_end = None
        subscription.cancelled_at = None
    elif status == SubscriptionStatus.ACTIVE:
        if reset_period or not subscription.current_period_end:
            subscription.current_period_start = today
            subscription.current_period_end = today + timedelta(
                days=subscription.cycle_days
            )
        subscription.trial_start = None
        subscription.trial_end = None
        subscription.grace_period_end = None
        subscription.cancelled_at = None
    elif status == SubscriptionStatus.GRACE:
        subscription.trial_start = None
        subscription.trial_end = None
        if not subscription.current_period_end:
            subscription.current_period_end = today
        subscription.grace_period_end = subscription.current_period_end + timedelta(
            days=7
        )
        subscription.cancelled_at = None
    else:
        subscription.trial_start = None
        subscription.trial_end = None
        subscription.current_period_start = None
        subscription.current_period_end = None
        subscription.grace_period_end = None
        if status == SubscriptionStatus.CANCELLED:
            from django.utils.timezone import now

            subscription.cancelled_at = now()

    subscription.save()
    sync_company_from_subscription(subscription)
    return subscription


@transaction.atomic
def transition_subscription(
    subscription_id,
    status: str,
    *,
    today: date,
    reset_period: bool = False,
) -> Subscription:
    subscription = (
        Subscription.objects.select_for_update()
        .select_related("plan", "company")
        .get(pk=subscription_id)
    )
    return set_subscription_status(
        subscription, status, today=today, reset_period=reset_period
    )


def calculate_price(subscription: Subscription) -> None:
    if subscription.billing_cycle == BillingCycle.YEARLY:
        base_price = subscription.plan.yearly_price
    else:
        base_price = subscription.plan.monthly_price
    subscription.price_paid = base_price * (
        1 - subscription.discount_pct / 100
    )


def renew_from_payment(subscription: Subscription, payment: SubscriptionPayment) -> None:
    """Grant one billing period after a successful subscription payment."""
    from django.utils.timezone import now

    today = now().date()
    subscription.price_paid = payment.amount
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.trial_start = None
    subscription.trial_end = None
    subscription.cancelled_at = None
    start = max(subscription.current_period_end or today, today)
    subscription.current_period_start = start
    subscription.current_period_end = start + timedelta(days=subscription.cycle_days)
    subscription.grace_period_end = None
    subscription.save(
        update_fields=[
            "price_paid",
            "status",
            "trial_start",
            "trial_end",
            "cancelled_at",
            "current_period_start",
            "current_period_end",
            "grace_period_end",
        ]
    )
    sync_company_from_subscription(subscription)
