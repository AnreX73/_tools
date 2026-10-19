"""
cart/merge.py

Слияние гостевой корзины и избранного с данными авторизованного пользователя.

Сейчас корзина и избранное живут только в сессии, поэтому функция лишь
собирает снимок гостевых данных и возвращает его. Когда появятся модели
``Cart``/``Favorite`` (личный кабинет), здесь нужно:

1. Прочитать снимок до очистки сессии.
2. В одной транзакции добавить позиции к корзине пользователя,
   суммируя количества и ограничивая их ``MAX_QTY``.
3. Объединить избранное без дублей, сохранив порядок добавления.
4. Очистить сессионные ключи только после успешной записи в БД.

Сигнал ``user_logged_in`` уже подключён (см. ``cart/signals.py``), поэтому
реализация появится в одном месте и не потребует правок во вьюхах.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from django.http import HttpRequest

from .services import get_cart, get_favorites


@dataclass(frozen=True, slots=True)
class GuestSnapshot:
    """Гостевые данные, которые нужно перенести в аккаунт."""

    cart: dict[int, int] = field(default_factory=dict)
    favorites: list[int] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.cart and not self.favorites


def merge_guest_data_into_account(request: HttpRequest, user: object) -> GuestSnapshot:
    """
    Точка расширения слияния гостевой корзины с аккаунтом.

    Возвращает снимок сессионных данных. Записей в БД пока нет: моделей
    корзины и избранного для пользователя не существует. Сессия при этом
    не очищается — покупатель не теряет товары после входа.
    """
    snapshot = GuestSnapshot(
        cart=dict(get_cart(request).as_dict()),
        favorites=list(get_favorites(request).ids()),
    )
    if snapshot.is_empty:
        return snapshot

    # Когда появятся модели: здесь будет transaction.atomic() и перенос
    # snapshot.cart / snapshot.favorites, затем удаление ключей
    # CART_SESSION_KEY и FAVORITES_SESSION_KEY из request.session.
    _ = user
    return snapshot
