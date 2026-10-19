"""
cart/templatetags/cart_tags.py

Состояние товара в корзине и избранном для шаблонов витрины.

Реализовано фильтрами (``product.pk|in_cart_qty:request``), чтобы значение
можно было передать в ``{% include ... with ... %}``. Сервисы кэшируются
в пределах запроса, поэтому лишних обращений к БД нет.
"""
from __future__ import annotations

from django import template
from django.http import HttpRequest

from cart.services import get_cart, get_favorites

register = template.Library()


@register.filter(name="in_cart_qty")
def in_cart_qty(product_id: int, request: HttpRequest | None) -> int:
    if request is None:
        return 0
    return get_cart(request).qty_of(product_id)


@register.filter(name="is_favorite")
def is_favorite(product_id: int, request: HttpRequest | None) -> bool:
    if request is None:
        return False
    return get_favorites(request).contains(product_id)
