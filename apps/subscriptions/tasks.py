import logging

from celery import shared_task
from django.db import transaction
from django.utils.timezone import localdate

from apps.subscriptions.models import (
    Subscription,
    SubscriptionEvent,
    SubscriptionStatus,
)
from apps.subscriptions.services import set_subscription_status

logger = logging.getLogger(__name__)


@shared_task
def transition_expired_subscriptions():
    """Move elapsed subscriptions through grace and expiry once per day."""
    today = localdate()
    transitioned = 0

    for subscription_id in Subscription.objects.filter(
        status__in=[SubscriptionStatus.TRIAL, SubscriptionStatus.ACTIVE],
        current_period_end__lt=today,
    ).values_list("id", flat=True):
        with transaction.atomic():
            subscription = (
                Subscription.objects.select_for_update()
                .select_related("plan", "company")
                .get(pk=subscription_id)
            )
            if (
                subscription.status not in (
                    SubscriptionStatus.TRIAL,
                    SubscriptionStatus.ACTIVE,
                )
                or not subscription.current_period_end
                or subscription.current_period_end >= today
            ):
                continue
            set_subscription_status(
                subscription, SubscriptionStatus.GRACE, today=today
            )
            SubscriptionEvent.objects.create(
                subscription=subscription,
                event_type=SubscriptionEvent.EventType.GRACE,
                notes="Automatically moved to grace period after period expiry.",
            )
            transitioned += 1

    for subscription_id in Subscription.objects.filter(
        status=SubscriptionStatus.GRACE,
        grace_period_end__lt=today,
    ).values_list("id", flat=True):
        with transaction.atomic():
            subscription = (
                Subscription.objects.select_for_update()
                .select_related("plan", "company")
                .get(pk=subscription_id)
            )
            if (
                subscription.status != SubscriptionStatus.GRACE
                or not subscription.grace_period_end
                or subscription.grace_period_end >= today
            ):
                continue
            set_subscription_status(
                subscription, SubscriptionStatus.EXPIRED, today=today
            )
            SubscriptionEvent.objects.create(
                subscription=subscription,
                event_type=SubscriptionEvent.EventType.EXPIRED,
                notes="Automatically expired after grace period ended.",
            )
            transitioned += 1

    if transitioned:
        logger.info("Transitioned %s subscription(s)", transitioned)
    return transitioned