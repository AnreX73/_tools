"""
companies/admin_views.py

JSON-подсказка реквизитов по ИНН для админки.

Отдельный эндпоинт, а не переиспользование htmx-вьюхи оформления: админке
нужен JSON, чтобы заполнить поля формы без перезагрузки страницы.

Доступ закрыт обёрткой ``admin.site.admin_view``: анонимных отправляет на
страницу входа, остальным без прав отдаёт редирект/403. Лимит запросов
отдельный (``DADATA_ADMIN_RATE_LIMIT``): менеджер проверяет несколько
контрагентов подряд, клиентский лимит в 10 запросов в минуту ему мал.
"""
from __future__ import annotations

import logging
import re

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from checkout.ratelimit import is_rate_limited, retry_after

from .dadata import (
    DadataError,
    DadataNotConfigured,
    DadataNotFound,
    DadataUnavailable,
)
from .lookup import lookup_requisites
from .validators import is_valid_inn

logger = logging.getLogger(__name__)


def _error(message: str, *, status: int, level: str = "error") -> JsonResponse:
    return JsonResponse(
        {"ok": False, "error": message, "level": level},
        status=status,
    )


@never_cache
@require_POST
def inn_lookup(request: HttpRequest) -> JsonResponse:
    """Возвращает реквизиты организации по ИНН/КПП в виде JSON."""
    inn = re.sub(r"\s+", "", request.POST.get("inn", "") or "")
    kpp = re.sub(r"\s+", "", request.POST.get("kpp", "") or "")

    if not is_valid_inn(inn):
        return _error(
            "Проверьте ИНН: нужно 10 цифр для юрлица или 12 для ИП, "
            "контрольная сумма должна совпадать.",
            status=400,
        )
    if kpp and not re.fullmatch(r"\d{9}", kpp):
        return _error("Проверьте КПП: он должен содержать 9 цифр.", status=400)
    if len(inn) == 12 and kpp:
        return _error("Для ИНН из 12 цифр (ИП) КПП не заполняется.", status=400)

    limit = int(getattr(settings, "DADATA_ADMIN_RATE_LIMIT", 30))
    window = int(getattr(settings, "DADATA_RATE_WINDOW", 60))
    try:
        limited = is_rate_limited(
            request,
            scope="dadata-admin",
            limit=limit,
            window=window,
        )
    except Exception:
        # Кэш/Redis недоступен: лучше показать подсказку, чем уронить форму.
        logger.warning("Не удалось проверить лимит подсказок DaData", exc_info=True)
        limited = False

    if limited:
        response = _error(
            "Слишком много запросов на проверку ИНН. Попробуйте немного позже.",
            status=429,
            level="warning",
        )
        response["Retry-After"] = str(retry_after(window=window))
        return response

    try:
        result = lookup_requisites(inn, kpp)
    except DadataNotFound:
        return _error(
            "Организация по указанному ИНН/КПП не найдена. "
            "Проверьте номер и заполните реквизиты вручную.",
            status=404,
        )
    except DadataNotConfigured:
        return _error(
            "Автозаполнение по ИНН не настроено: не задан DADATA_API_KEY.",
            status=503,
        )
    except DadataUnavailable as exc:
        logger.warning("DaData временно недоступен: %s", exc)
        return _error(
            "Сервис проверки временно недоступен. Заполните реквизиты вручную.",
            status=503,
        )
    except DadataError as exc:
        logger.warning("Ошибка интеграции с DaData: %s", exc)
        return _error(
            "Не удалось получить реквизиты. Заполните их вручную.",
            status=502,
        )

    if result.multiple_kpp:
        return _error(result.notice, status=409, level=result.notice_level)

    return JsonResponse(
        {
            "ok": True,
            "fields": result.initial,
            "notice": result.notice,
            "level": result.notice_level,
            "source": result.source,
        }
    )
