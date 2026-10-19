"""
checkout/ratelimit.py

Ограничение частоты POST-запросов: оформление заявки и подсказки DaData.

Счётчик живёт в Redis (``CACHES["default"]`` в настройках), поэтому ограничение
общее для всех процессов. Ключ — IP клиента; за прокси берём ``REMOTE_ADDR``,
а не подделываемый клиентом ``X-Forwarded-For`` (при необходимости доверенный
прокси настраивается отдельно). Для разных сценариев используются разные
``scope``, чтобы запросы подсказок не расходовали лимит оформления.
"""
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

DEFAULT_LIMIT = 5
DEFAULT_WINDOW = 60 * 60  # час


def client_ip(request: HttpRequest) -> str:
    """
    IP клиента для ключа счётчика.

    Если сайт стоит за доверенным прокси и ``USE_X_FORWARDED_FOR`` включён,
    берём первый адрес из ``X-Forwarded-For``. По умолчанию доверяем только
    ``REMOTE_ADDR``: заголовок легко подделать на клиенте.
    """
    if getattr(settings, "USE_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return (request.META.get("REMOTE_ADDR") or "unknown").strip() or "unknown"


def _key(ip: str, scope: str) -> str:
    # Для оформления сохраняем прежний ключ, чтобы не сбрасывать счётчики
    # при обновлении кода; остальные сценарии получают отдельное пространство.
    if scope == "checkout":
        return f"checkout:rate:{ip}"
    return f"checkout:rate:{scope}:{ip}"


def hit(
    request: HttpRequest,
    *,
    scope: str = "checkout",
    window: int | None = None,
) -> int:
    """
    Учитывает попытку и возвращает число попыток за окно.

    ``cache.add`` атомарно создаёт счётчик; ``cache.incr`` атомарно увеличивает
    его в Redis. Если ключ успел истечь между операциями — начинаем заново.
    """
    if window is None:
        window = int(getattr(settings, "CHECKOUT_RATE_WINDOW", DEFAULT_WINDOW))
    key = _key(client_ip(request), scope)

    if cache.add(key, 1, window):
        return 1
    try:
        return int(cache.incr(key))
    except ValueError:
        # Ключ исчез между add и incr (истёк/сброшен) — начинаем окно заново.
        cache.set(key, 1, window)
        return 1


def is_rate_limited(
    request: HttpRequest,
    *,
    scope: str = "checkout",
    limit: int | None = None,
    window: int | None = None,
) -> bool:
    """True, если лимит попыток уже исчерпан."""
    if limit is None:
        if scope == "checkout":
            limit = int(
                getattr(settings, "CHECKOUT_RATE_LIMIT", DEFAULT_LIMIT)
            )
        else:
            limit = DEFAULT_LIMIT
    return hit(request, scope=scope, window=window) > limit


def retry_after(*, window: int | None = None) -> int:
    """Сколько секунд ждать до следующей попытки (для заголовка Retry-After)."""
    if window is None:
        window = int(getattr(settings, "CHECKOUT_RATE_WINDOW", DEFAULT_WINDOW))
    return int(window)
