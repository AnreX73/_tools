"""
shop/templatetags/shop_money.py

Форматирование денежных значений (Decimal) для шаблонов.

Цены хранятся как Decimal(12,2). Показывать «120.00 ₽» не нужно:
целые рубли выводятся без копеек, дробные — с запятой и двумя знаками.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def format_money(value: Decimal | int | float | str | None) -> str:
    """120.00 -> «120», 120.50 -> «120,50», None -> «»."""
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if amount == amount.to_integral_value():
        return str(amount.quantize(Decimal("1")))
    return f"{amount:.2f}".replace(".", ",")


@register.filter(name="money")
def money(value: Decimal | int | float | str | None) -> str:
    return format_money(value)


@register.filter(name="money_rub")
def money_rub(value: Decimal | int | float | str | None) -> str:
    """Денежное значение с символом рубля; для пустого — «Цена по запросу»."""
    text = format_money(value)
    return f"{text} ₽" if text else "Цена по запросу"
