"""
companies/seller.py

Единая точка получения реквизитов продавца.

Источник истины — активный ``SellerProfile``. Пока профиль не заполнен,
используется ``settings.SELLER_REQUISITES``: это нужно для тестов и первого
запуска, когда миграции уже применены, а админ ещё не открывали.

Все функции возвращают плоский словарь с ключами модели, чтобы один и тот же
объект можно было передать в шаблон, письмо и ``Invoice.seller_snapshot``.
"""
from __future__ import annotations

from typing import Mapping

from django.conf import settings

from .models import LegalEntity, SellerProfile


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _from_settings() -> dict[str, str]:
    """
    Fallback на настройки.

    Поддерживаются и новые ключи модели, и старые ``name``/``address``/
    ``director``: тесты и существующие .env могли использовать их.
    """
    raw: Mapping = getattr(settings, "SELLER_REQUISITES", {}) or {}
    return {
        "legal_form": _text(raw.get("legal_form"))
        or str(LegalEntity.LegalForm.OOO),
        "short_name": _text(raw.get("short_name")) or _text(raw.get("name")),
        "full_name": _text(raw.get("full_name")),
        "inn": _text(raw.get("inn")),
        "kpp": _text(raw.get("kpp")),
        "ogrn": _text(raw.get("ogrn")),
        "legal_address": _text(raw.get("legal_address"))
        or _text(raw.get("address")),
        "postal_address": _text(raw.get("postal_address")),
        "phone": _text(raw.get("phone")),
        "email": _text(raw.get("email")),
        "website": _text(raw.get("website")),
        "bank_name": _text(raw.get("bank_name")),
        "bik": _text(raw.get("bik")),
        "correspondent_account": _text(raw.get("correspondent_account")),
        "checking_account": _text(raw.get("checking_account")),
        "director_name": _text(raw.get("director_name"))
        or _text(raw.get("director")),
        "director_position": _text(raw.get("director_position"))
        or "Генеральный директор",
    }


def get_seller() -> dict[str, str]:
    """Активные реквизиты продавца: из БД, иначе из настроек."""
    profile = SellerProfile.get_active()
    if profile is not None:
        return profile.as_snapshot()
    return _from_settings()


def get_seller_snapshot() -> dict[str, str]:
    """Снимок для сохранения в документе (счёт, заявка)."""
    return get_seller()


def is_seller_configured(seller: Mapping | None) -> bool:
    """
    Достаточно ли данных, чтобы выпускать документ.

    Банк не обязателен: у продавца может быть оплата по счёту без указания
    банка в конкретном шаблоне, но наименование, ИНН и адрес нужны всегда.
    """
    if not seller:
        return False
    return bool(
        _text(seller.get("short_name"))
        and _text(seller.get("inn"))
        and _text(seller.get("legal_address"))
    )
