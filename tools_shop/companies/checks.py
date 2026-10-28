"""Системные проверки приложения companies."""
from __future__ import annotations

from django.core.checks import Warning, register
from django.db import OperationalError, ProgrammingError

from .seller import get_seller, is_seller_configured


@register()
def seller_profile_configured(app_configs, **kwargs):
    """
    Предупреждает, если реквизиты продавца не заполнены.

    Без них счёт не сформируется, а подвал и страница заявки останутся без
    юридической информации. Проверка терпит отсутствие таблицы: она запускается
    и до применения миграций.
    """
    try:
        configured = is_seller_configured(get_seller())
    except (OperationalError, ProgrammingError):
        return []

    if configured:
        return []

    return [
        Warning(
            "Реквизиты продавца не заполнены.",
            hint="Откройте в админке «Реквизиты продавца» и укажите "
            "наименование, ИНН и юридический адрес. Иначе счёт не сформируется.",
            id="companies.W001",
        )
    ]
