"""Web Push delivery runs in the existing Django Q worker."""
import json
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.utils import timezone
from django_q.tasks import async_task
from pywebpush import WebPushException, webpush

from .models import Message, PushSubscription

logger = logging.getLogger(__name__)


def configured():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY and settings.VAPID_SUBJECT)


def enqueue_message_push(message_id):
    if not configured():
        return
    try:
        async_task("chat.push.send_message_push", message_id)
    except Exception:
        logger.exception("Could not enqueue chat push")


def send_message_push(message_id):
    message = Message.objects.filter(pk=message_id).first()
    if message is None or not configured():
        return
    if message.is_staff:
        subscriptions = PushSubscription.objects.filter(conversation_id=message.conversation_id)
        url = "/?chat=open"
    else:
        users = get_user_model().objects.filter(is_active=True, is_staff=True)
        operator_ids = [user.pk for user in users if user.has_perm("chat.reply_conversation")]
        subscriptions = PushSubscription.objects.filter(user_id__in=operator_ids, conversation__isnull=True)
        url = f"/chat/operator/{message.conversation_id}/"
    payload = json.dumps({
        "title": "Ответ оператора" if message.is_staff else "Новое сообщение посетителя",
        "body": message.text[:160],
        "tag": f"chat-{message.conversation_id}",
        "data": {"url": url},
    }, ensure_ascii=False)
    for subscription in subscriptions.iterator():
        session = Session.objects.filter(session_key=subscription.session_key, expire_date__gt=timezone.now()).first()
        session_data = session.get_decoded() if session else {}
        if message.is_staff:
            valid = session_data.get("chat_conversation") == str(message.conversation_id)
        else:
            valid = session_data.get("_auth_user_id") == str(subscription.user_id)
        if not valid:
            subscription.delete()
            continue
        try:
            webpush(
                subscription_info={"endpoint": subscription.endpoint,
                                   "keys": {"auth": subscription.auth, "p256dh": subscription.p256dh}},
                data=payload, vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT}, timeout=10, ttl=3600,
            )
        except WebPushException as exc:
            if exc.response is not None and exc.response.status_code in (404, 410):
                subscription.delete()
            else:
                logger.warning("Chat push delivery failed for subscription %s", subscription.pk)
        except Exception:
            logger.warning("Chat push delivery failed for subscription %s", subscription.pk)
