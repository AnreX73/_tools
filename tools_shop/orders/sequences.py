"""
orders/sequences.py

Человекочитаемые номера заказов и счетов.

Номера берутся из отдельных последовательностей PostgreSQL, а не из
``max(number)+1``: последовательность не блокирует таблицу и не выдаёт
дубли при одновременных заявках. Номер счёта при этом присваивается
только в момент одобрения заявки менеджером (см. ``Invoice.issue_for``).

Формат:

* заказ  — ``З-001001``;
* счёт   — ``С-000001``.

Буква в номере не мешает сортировке: числовая часть дополнена нулями,
поэтому строки сортируются как числа.
"""
from __future__ import annotations

from django.db import connection

ORDER_NUMBER_SEQUENCE = "orders_order_number_seq"
INVOICE_NUMBER_SEQUENCE = "orders_invoice_number_seq"

ORDER_NUMBER_PREFIX = "З"
INVOICE_NUMBER_PREFIX = "С"
NUMBER_DIGITS = 6


def _nextval(sequence: str) -> int:
    """Следующее значение последовательности в текущем соединении."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s)", [sequence])
        value = cursor.fetchone()[0]
    return int(value)


def next_order_number() -> str:
    """``З-001001`` — номер новой заявки."""
    return f"{ORDER_NUMBER_PREFIX}-{_nextval(ORDER_NUMBER_SEQUENCE):0{NUMBER_DIGITS}d}"


def next_invoice_number() -> str:
    """``С-000001`` — номер первой версии счёта."""
    return f"{INVOICE_NUMBER_PREFIX}-{_nextval(INVOICE_NUMBER_SEQUENCE):0{NUMBER_DIGITS}d}"
