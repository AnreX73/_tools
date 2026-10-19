"""
checkout/draft.py

Черновик формы и ключ идемпотентности в сессии.

Зачем черновик: если форма не прошла проверку, покупатель не должен заново
вводить реквизиты. В сессии хранятся только строки формы; пароли, файлы и
служебные поля туда не попадают. Черновик живёт ограниченное время, чтобы
персональные данные не лежали в сессии бессрочно.

Ключ идемпотентности создаётся при показе формы, передаётся в скрытом поле и
хранится в сессии. ``place_order`` по этому ключу понимает, что форма уже
отправлена, и не создаёт вторую заявку.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.http import HttpRequest
from django.utils import timezone

from .forms import CheckoutForm

DRAFT_SESSION_KEY = "checkout_draft"
IDEMPOTENCY_SESSION_KEY = "checkout_idempotency_key"
DRAFT_TTL = timedelta(days=7)

#: Поля, которые нельзя хранить в черновике.
DRAFT_EXCLUDED = frozenset(
    {"csrfmiddlewaretoken", "honeypot", "idempotency_key", "consent"}
)
#: В сессию попадают только поля формы, а не произвольные ключи из POST.
DRAFT_FIELDS = frozenset(CheckoutForm.base_fields) - DRAFT_EXCLUDED


def _clean_data(data) -> dict[str, str]:
    """Оставляет только строковые значения полей формы."""
    result: dict[str, str] = {}
    for key, value in data.items():
        if key in DRAFT_EXCLUDED or key not in DRAFT_FIELDS:
            continue
        # QueryDict может отдать список; в форме нет множественного выбора,
        # поэтому берём последнее значение.
        if isinstance(value, (list, tuple)):
            value = value[-1] if value else ""
        result[str(key)] = "" if value is None else str(value)
    return result


def load_draft(request: HttpRequest) -> dict[str, str]:
    """Возвращает сохранённый черновик, если он не устарел."""
    payload = request.session.get(DRAFT_SESSION_KEY)
    if not isinstance(payload, dict):
        return {}
    saved_at = payload.get("saved_at")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(saved_at, str):
        request.session.pop(DRAFT_SESSION_KEY, None)
        return {}
    try:
        saved = datetime.fromisoformat(saved_at)
    except ValueError:
        request.session.pop(DRAFT_SESSION_KEY, None)
        return {}
    if saved.tzinfo is None:
        saved = timezone.make_aware(saved, timezone.get_current_timezone())
    if timezone.now() - saved > DRAFT_TTL:
        request.session.pop(DRAFT_SESSION_KEY, None)
        return {}
    return {str(key): str(value) for key, value in data.items()}


def save_draft(request: HttpRequest, data) -> None:
    """Сохраняет введённые значения, чтобы не потерять их при ошибке."""
    request.session[DRAFT_SESSION_KEY] = {
        "data": _clean_data(data),
        "saved_at": timezone.now().isoformat(),
    }


def clear_draft(request: HttpRequest) -> None:
    request.session.pop(DRAFT_SESSION_KEY, None)


def ensure_idempotency_key(request: HttpRequest) -> str:
    """Возвращает ключ текущей попытки оформления, создавая его при показе формы."""
    key = request.session.get(IDEMPOTENCY_SESSION_KEY)
    if isinstance(key, str) and key:
        try:
            UUID(key)
        except ValueError:
            key = ""
    if not key:
        key = str(uuid4())
        request.session[IDEMPOTENCY_SESSION_KEY] = key
    return key


def clear_checkout_state(request: HttpRequest) -> None:
    """Убирает черновик и ключ после успешной заявки."""
    request.session.pop(DRAFT_SESSION_KEY, None)
    request.session.pop(IDEMPOTENCY_SESSION_KEY, None)
