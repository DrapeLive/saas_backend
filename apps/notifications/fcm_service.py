"""Firebase Cloud Messaging service using the Admin SDK.

Initialises the Firebase Admin app lazily from service-account credentials
provided either via the ``FIREBASE_CREDENTIALS_JSON`` environment variable (the
full service-account JSON) or the ``FIREBASE_CREDENTIALS_PATH`` file path.
Provides a best-effort ``send_push`` helper that never raises so notification
failures never break the request/response cycle.
"""

import json
import logging
import os
from typing import Optional

import firebase_admin
from firebase_admin import credentials, messaging

from django.conf import settings

logger = logging.getLogger(__name__)

_app: Optional[firebase_admin.App] = None


def _get_app() -> Optional[firebase_admin.App]:
    """Return the Firebase Admin app, initialising it on first use."""
    global _app
    if _app is not None:
        return _app
    if not getattr(settings, "NOTIFICATIONS_PUSH_ENABLED", True):
        return None
    try:
        creds_json = getattr(settings, "FIREBASE_CREDENTIALS_JSON", None)
        if creds_json:
            cred = credentials.Certificate(
                json.loads(creds_json) if isinstance(creds_json, str) else creds_json
            )
        else:
            creds_path = getattr(settings, "FIREBASE_CREDENTIALS_PATH", None)
            if not creds_path or not os.path.exists(creds_path):
                logger.warning(
                    "Firebase credentials not configured (set FIREBASE_CREDENTIALS_JSON "
                    "or FIREBASE_CREDENTIALS_PATH); push notifications disabled.",
                )
                return None
            cred = credentials.Certificate(creds_path)
        _app = firebase_admin.initialize_app(cred)
        return _app
    except Exception:  # pragma: no cover - push must never break a request
        logger.exception("Failed to initialise Firebase Admin SDK")
        return None


def send_push(
    tokens: list[str],
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> int:
    """Send a push notification to one or more FCM tokens.

    Returns the number of successfully sent messages. Invalid/unregistered
    tokens are silently skipped so callers never have to handle exceptions.
    """
    app = _get_app()
    if app is None:
        logger.warning("Firebase Admin app not available; push notification dropped.")
        return 0

    valid_tokens = [t for t in tokens if t and isinstance(t, str)]
    if not valid_tokens:
        return 0

    try:
        multicast = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            tokens=valid_tokens,
        )
        response = messaging.send_multicast(multicast, app=app)
        return response.success_count
    except Exception:  # pragma: no cover - push must never break a request
        logger.exception("Failed to send FCM multicast push notification")
        return 0


def send_push_to_token(
    token: str,
    title: str,
    body: str,
    data: Optional[dict] = None,
) -> bool:
    """Send a push notification to a single FCM token."""
    return send_push([token], title, body, data) > 0
