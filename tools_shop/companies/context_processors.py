"""Контекст-процессоры приложения companies."""
from __future__ import annotations

from django.http import HttpRequest

from .seller import get_seller


def seller(request: HttpRequest) -> dict:
    """
    Реквизиты продавца для подвала и страниц оформления/заявки.

    В админке и htmx-фрагментах они не нужны: там нет подвала и блоков,
    которые эти данные отображают. Это экономит один запрос на служебных
    страницах.
    """
    if request.path.startswith("/admin/") or request.headers.get("HX-Request"):
        return {}
    return {"seller": get_seller()}
