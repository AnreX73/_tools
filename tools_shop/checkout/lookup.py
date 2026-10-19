"""
checkout/lookup.py

Загрузка реквизитов для формы оформления.

Порядок источников:
1. активная карточка ``LegalEntity`` с тем же ИНН/КПП — источник истины;
2. если карточки нет — DaData ``findById/party``;
3. при недоступном DaData ошибка пробрасывается во вьюху, форма остаётся
   доступной для ручного заполнения.

Из карточки в форму отдаются только публичные реквизиты организации.
Контакты, банковские счета и примечания не показываем: по ИНН их может
запросить любой человек, а эти данные относятся к конкретному покупателю.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass

from django.conf import settings
from django.core.cache import cache

from companies.dadata import DadataClient, PartyRequisites
from companies.models import LegalEntity

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL = 24 * 60 * 60


@dataclass(frozen=True)
class LookupResult:
    """Результат подстановки реквизитов."""

    source: str
    initial: dict[str, str]
    notice: str
    notice_level: str = "info"
    is_verified: bool = False
    multiple_kpp: bool = False


def _company_initial(company: LegalEntity) -> dict[str, str]:
    """Только публичные реквизиты: без контактов и банковских счетов."""
    return {
        "short_name": company.short_name,
        "full_name": company.full_name,
        "legal_form": company.legal_form,
        "inn": company.inn,
        "kpp": company.kpp,
        "ogrn": company.ogrn,
        "legal_address": company.legal_address,
    }


def _lookup_database(inn: str, kpp: str) -> LookupResult | None:
    """Ищет организацию в базе; ``None`` — если карточки нет."""
    queryset = LegalEntity.objects.filter(inn=inn, is_active=True).order_by(
        "-is_verified", "-updated_at", "-pk"
    )

    if kpp:
        company = queryset.filter(kpp=kpp).first()
        if company is None:
            return None
        if company.is_verified:
            notice = (
                "Реквизиты загружены из проверенной карточки организации. "
                "Проверьте адрес доставки и контакты."
            )
        else:
            notice = (
                "Реквизиты загружены из ранее оформленной заявки. "
                "Проверьте актуальность."
            )
        return LookupResult(
            source="db",
            initial=_company_initial(company),
            notice=notice,
            is_verified=company.is_verified,
        )

    companies = list(queryset[:2])
    if not companies:
        return None
    if len(companies) > 1:
        return LookupResult(
            source="db",
            initial={},
            notice=(
                "По этому ИНН в базе найдено несколько организаций. "
                "Укажите КПП, чтобы загрузить нужные реквизиты."
            ),
            notice_level="warning",
            multiple_kpp=True,
        )

    company = companies[0]
    if company.is_verified:
        notice = (
            "Реквизиты загружены из проверенной карточки организации. "
            "Проверьте адрес доставки и контакты."
        )
    else:
        notice = (
            "Реквизиты загружены из ранее оформленной заявки. "
            "Проверьте актуальность."
        )
    return LookupResult(
        source="db",
        initial=_company_initial(company),
        notice=notice,
        is_verified=company.is_verified,
    )


def _cache_key(inn: str, kpp: str) -> str:
    return f"dadata:party:{inn}:{kpp or 'main'}"


def _fetch_party(inn: str, kpp: str) -> PartyRequisites:
    """Возвращает реквизиты из кэша или запрашивает DaData."""
    ttl = int(getattr(settings, "DADATA_CACHE_TTL", DEFAULT_CACHE_TTL) or 0)
    key = _cache_key(inn, kpp)

    if ttl > 0:
        try:
            cached = cache.get(key)
        except Exception:
            logger.warning("Не удалось прочитать кэш DaData", exc_info=True)
            cached = None
        if isinstance(cached, dict):
            try:
                return PartyRequisites(**cached)
            except TypeError:
                logger.warning("В кэше DaData лежит устаревшая структура")

    party = DadataClient().find_party(inn, kpp)

    if ttl > 0:
        try:
            cache.set(key, asdict(party), ttl)
        except Exception:
            logger.warning("Не удалось сохранить ответ DaData в кэш", exc_info=True)
    return party


def lookup_requisites(inn: str, kpp: str = "") -> LookupResult:
    """
    Подбирает реквизиты: сначала база, затем DaData.

    :raises companies.dadata.DadataNotFound: организация не найдена;
    :raises companies.dadata.DadataNotConfigured: не задан API-ключ;
    :raises companies.dadata.DadataUnavailable: DaData недоступен.
    """
    inn = str(inn or "").strip()
    kpp = str(kpp or "").strip()

    database_result = _lookup_database(inn, kpp)
    if database_result is not None:
        return database_result

    party = _fetch_party(inn, kpp)
    notice = (
        "Организация найдена в ЕГРЮЛ/ЕГРИП. "
        "Проверьте юридический адрес и банковские реквизиты."
    )
    notice_level = "info"
    if party.warnings:
        notice = f"{notice} {' '.join(party.warnings)}"
        notice_level = "warning"

    return LookupResult(
        source="dadata",
        initial=party.to_form_initial(),
        notice=notice,
        notice_level=notice_level,
    )
