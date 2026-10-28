"""
checkout/lookup.py

Совместимый реэкспорт сервиса подстановки реквизитов.

Сама логика живёт в ``companies.lookup``: её используют и оформление заказа,
и админка. Модуль оставлен, чтобы существующие импорты
(``from .lookup import lookup_requisites``) продолжали работать.
"""
from companies.lookup import (  # noqa: F401
    DEFAULT_CACHE_TTL,
    LookupResult,
    lookup_requisites,
)

__all__ = ["DEFAULT_CACHE_TTL", "LookupResult", "lookup_requisites"]
