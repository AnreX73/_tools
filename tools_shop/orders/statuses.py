"""
orders/statuses.py

Статусы заявки и явная таблица допустимых переходов.

Таблица живёт в одном месте: и модель (``Order.transition_to``), и будущие
админ-действия, и тесты используют ``can_transition``/``allowed_transitions``,
поэтому «забыть» про правило в отдельной вьюхе невозможно.

Переходы намеренно консервативные:

* ``new`` и ``review`` можно отменить или отклонить;
* счёт выставляется только из ``review`` (менеджер сначала проверил заявку);
* оплаченный заказ можно отменить (возврат средств — вне системы);
* из ``shipped`` только ``done``: отгруженный заказ не отменяем;
* ``done``, ``cancelled``, ``rejected`` — терминальные.
"""
from __future__ import annotations

from django.db import models


class OrderStatus(models.TextChoices):
    NEW = "new", "Новая заявка"  # type: ignore[assignment]
    REVIEW = "review", "На проверке"  # type: ignore[assignment]
    INVOICED = "invoiced", "Счёт выставлен"  # type: ignore[assignment]
    PAID = "paid", "Оплачен"  # type: ignore[assignment]
    SHIPPED = "shipped", "Отгружен"  # type: ignore[assignment]
    DONE = "done", "Завершён"  # type: ignore[assignment]
    CANCELLED = "cancelled", "Отменён"  # type: ignore[assignment]
    REJECTED = "rejected", "Отклонён"  # type: ignore[assignment]


#: Полная карта переходов. Ключ и значения — строковые значения OrderStatus.
TRANSITIONS: dict[str, frozenset[str]] = {
    OrderStatus.NEW: frozenset(
        {OrderStatus.REVIEW, OrderStatus.CANCELLED, OrderStatus.REJECTED}
    ),
    OrderStatus.REVIEW: frozenset(
        {OrderStatus.INVOICED, OrderStatus.CANCELLED, OrderStatus.REJECTED}
    ),
    OrderStatus.INVOICED: frozenset({OrderStatus.PAID, OrderStatus.CANCELLED}),
    OrderStatus.PAID: frozenset({OrderStatus.SHIPPED, OrderStatus.CANCELLED}),
    OrderStatus.SHIPPED: frozenset({OrderStatus.DONE}),
    OrderStatus.DONE: frozenset(),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
}

#: Статусы, из которых заявка уже не двигается.
TERMINAL_STATUSES = frozenset(
    {OrderStatus.DONE, OrderStatus.CANCELLED, OrderStatus.REJECTED}
)

#: Статусы, в которых менеджер ещё может править состав заказа.
EDITABLE_STATUSES = frozenset({OrderStatus.NEW, OrderStatus.REVIEW})


def allowed_transitions(status: str) -> frozenset[str]:
    """Допустимые следующие статусы; неизвестный статус — пустое множество."""
    return TRANSITIONS.get(status, frozenset())


def can_transition(from_status: str, to_status: str) -> bool:
    """Можно ли перевести заявку из ``from_status`` в ``to_status``."""
    return to_status in allowed_transitions(from_status)


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES
