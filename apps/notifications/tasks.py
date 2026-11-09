from celery import shared_task

from apps.notifications.fcm_service import send_push


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_push_notification_task(self, tokens, title, body, data=None):
    """Celery task to deliver a push notification to one or more FCM tokens."""
    send_push(tokens, title, body, data)
