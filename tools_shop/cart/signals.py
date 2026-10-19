"""
cart/signals.py

Точка расширения: слияние гостевой корзины и избранного с корзиной
авторизованного пользователя при входе.

Обработчик вызывает ``merge_guest_data_into_account``: сейчас она только
собирает снимок сессии (моделей Cart/Favorite нет), но вся логика переноса
будет жить в ``cart/merge.py``.
"""
from __future__ import annotations

from typing import Any

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .merge import merge_guest_data_into_account


@receiver(user_logged_in, dispatch_uid="cart.merge_on_login")
def merge_session_cart_on_login(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    """Переносит гостевые данные в аккаунт (пока — без записи в БД)."""
    if request is None:
        return
    merge_guest_data_into_account(request, user)
