"""
cart/context_processors.py

Счётчики корзины и избранного для шапки сайта.

Процессор не делает запросов к БД на служебных страницах (админка,
live-reload) и не подмешивает лишнее в htmx-фрагменты: бейдж обновляется
отдельным запросом по событию ``cart-updated``.
"""
from __future__ import annotations

from django.http import HttpRequest

from .services import get_cart, get_favorites


def cart_counters(request: HttpRequest) -> dict[str, int]:
    path = request.path
    if path.startswith("/admin/") or path.startswith("/__reload__/"):
        return {}
    if request.headers.get("HX-Request"):
        # Фрагменты не содержат шапку; счётчики им не нужны.
        return {}
    return {
        "cart_count": get_cart(request).count(),
        "favorites_count": get_favorites(request).count(),
    }
