"""In-app notifications. A notification is only reported as created when the DB write succeeds."""
import logging

from django.db import DatabaseError

from .models import Notification

logger = logging.getLogger(__name__)


def notify(user, title, message="", url="", level="info", product=None, dedupe_key=""):
    """Create an in-app notification. Returns the Notification, or None if skipped or failed."""
    if user is None or not user.is_active:
        return None
    if dedupe_key and Notification.objects.filter(user=user, dedupe_key=dedupe_key).exists():
        return None
    try:
        return Notification.objects.create(
            user=user, title=title[:200], message=message, url=url[:500], level=level, product=product,
            dedupe_key=dedupe_key[:120],
        )
    except DatabaseError:
        logger.exception("Failed to create notification for %s", user)
        return None


def notify_assignment(record, assignee, actor):
    if assignee is None or assignee == actor:
        return None
    resource = record.resource
    return notify(
        assignee,
        f"{resource.label} assigned to you",
        f"{actor.get_full_name() or actor.username} assigned “{record}” ({record.product}) to you.",
        url=record.get_absolute_url(),
        product=record.product,
    )
