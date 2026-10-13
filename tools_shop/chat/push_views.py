import base64
import json
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST

from .consumers import can_reply
from .models import Conversation, PushSubscription
from .push import configured


@require_GET
def service_worker(request):
    worker_path = finders.find("js/sw.js")
    if not isinstance(worker_path, str):
        raise Http404
    try:
        source = Path(worker_path).read_bytes()
    except OSError as exc:
        raise Http404 from exc
    response = HttpResponse(source, content_type="application/javascript")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def public_key(request):
    response = JsonResponse({"public_key": settings.VAPID_PUBLIC_KEY, "enabled": configured()})
    response["Cache-Control"] = "no-store"
    return response


def valid_key(value, length):
    if not isinstance(value, str) or len(value) > 128:
        return False
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        return len(decoded) == length and (length != 65 or decoded[0] == 4)
    except (ValueError, TypeError):
        return False


@require_POST
def subscribe(request):
    if not configured():
        return JsonResponse({"error": "Push пока не настроен на сервере."}, status=503)
    if len(request.body) > 4096:
        return JsonResponse({"error": "Слишком большой запрос."}, status=400)
    try:
        data = json.loads(request.body)["subscription"]
        endpoint = data["endpoint"]
        auth, p256dh = data["keys"]["auth"], data["keys"]["p256dh"]
        parsed = urlsplit(endpoint)
        # Only browser push services may receive server-side HTTP requests.
        host = parsed.hostname or ""
        allowed = host == "fcm.googleapis.com" or host == "updates.push.services.mozilla.com" or host.endswith(".notify.windows.com") or host == "web.push.apple.com"
        if (not allowed or parsed.scheme != "https" or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.fragment or len(endpoint) > 500
                or not valid_key(auth, 16) or not valid_key(p256dh, 65)):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        return JsonResponse({"error": "Некорректная push-подписка."}, status=400)
    conversation = None
    user = None
    if can_reply(request.user):
        user = request.user
    else:
        conversation = Conversation.objects.filter(pk=request.session.get("chat_conversation")).first()
        if conversation is None:
            return JsonResponse({"error": "Сначала откройте чат."}, status=403)
    if not request.session.session_key:
        request.session.save()
    existing = PushSubscription.objects.filter(endpoint=endpoint).first()
    if existing and str(existing.session_key) != request.session.session_key:
        return JsonResponse({"error": "Подписка принадлежит другой сессии. Переключите уведомления."}, status=409)
    PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={
        "auth": auth, "p256dh": p256dh, "session_key": request.session.session_key,
        "user": user, "conversation": conversation,
    })
    return JsonResponse({"ok": True})


@require_POST
def unsubscribe(request):
    PushSubscription.objects.filter(session_key=request.session.session_key).delete()
    return JsonResponse({"ok": True})
