"""
companies/dadata.py

Клиент DaData Suggestions API для подсказок реквизитов по ИНН.

Модуль не ходит в базу и не знает про checkout: он только вызывает
``findById/party``, проверяет ответ и переводит его в поля формы.
Ключ API читается из настроек и никогда не попадает в браузер.

Документация API: https://dadata.ru/api/find-party/
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests
from django.conf import settings

from .models import LegalEntity

logger = logging.getLogger(__name__)

DEFAULT_SUGGEST_URL = (
    "https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party"
)

STATUS_LABELS: dict[str, str] = {
    "ACTIVE": "действующая",
    "LIQUIDATING": "ликвидируется",
    "LIQUIDATED": "ликвидирована",
    "BANKRUPT": "банкротство",
    "REORGANIZING": "в процессе реорганизации",
}


class DadataError(Exception):
    """Базовая ошибка интеграции с DaData."""


class DadataNotConfigured(DadataError):
    """Не задан API-ключ: подсказки для новых клиентов недоступны."""


class DadataUnavailable(DadataError):
    """DaData временно недоступен или вернул некорректный ответ."""


class DadataNotFound(DadataError):
    """Организация по указанным ИНН/КПП не найдена."""


@dataclass(frozen=True)
class PartyRequisites:
    """Нормализованные реквизиты организации из ответа DaData."""

    short_name: str
    full_name: str
    legal_form: str
    inn: str
    kpp: str
    ogrn: str
    legal_address: str
    status: str = ""
    status_text: str = ""
    is_invalid: bool = False
    branch_type: str = ""
    warnings: tuple[str, ...] = ()

    def to_form_initial(self) -> dict[str, str]:
        """Поля checkout-формы, которые можно безопасно заполнить."""
        return {
            "short_name": self.short_name,
            "full_name": self.full_name,
            "legal_form": self.legal_form,
            "inn": self.inn,
            "kpp": self.kpp,
            "ogrn": self.ogrn,
            "legal_address": self.legal_address,
        }


def _text(value: Any) -> str:
    """Строка без пробелов по краям; ``None`` превращается в пустую строку."""
    if value is None:
        return ""
    return str(value).strip()


def _mapping(value: Any) -> dict:
    """Словарь из ответа API или пустой словарь для неожиданного типа."""
    return value if isinstance(value, dict) else {}


def _legal_form(data: dict) -> str:
    """ОПФ DaData -> значение ``LegalEntity.LegalForm``."""
    if _text(data.get("type")).upper() == "INDIVIDUAL":
        return LegalEntity.LegalForm.IP

    opf = _mapping(data.get("opf"))
    short = _text(opf.get("short")).upper()
    if "ПАО" in short:
        return LegalEntity.LegalForm.PAO
    if "ООО" in short:
        return LegalEntity.LegalForm.OOO
    if any(token in short for token in ("АО", "ЗАО", "ОАО", "НАО")):
        return LegalEntity.LegalForm.AO
    if "ИП" in short:
        return LegalEntity.LegalForm.IP
    return LegalEntity.LegalForm.OTHER


def map_party(
    suggestion: dict,
    query_inn: str = "",
    query_kpp: str = "",
) -> PartyRequisites:
    """
    Переводит один элемент ``suggestions`` в ``PartyRequisites``.

    :raises DadataNotFound: если в ответе нет данных или наименования.
    """
    data = _mapping(suggestion.get("data"))
    if not data:
        raise DadataNotFound("DaData не вернул данные организации.")

    name = _mapping(data.get("name"))
    short_name = _text(
        name.get("short_with_opf")
        or name.get("short")
        or suggestion.get("value")
    )
    full_name = _text(name.get("full_with_opf") or name.get("full")) or short_name
    if not short_name and not full_name:
        raise DadataNotFound("DaData не вернул наименование организации.")

    address = _mapping(data.get("address"))
    legal_address = _text(
        address.get("unrestricted_value") or address.get("value")
    )

    state = _mapping(data.get("state"))
    status = _text(state.get("status"))
    status_text = STATUS_LABELS.get(status, status)
    is_invalid = data.get("invalid") is True
    branch_type = _text(data.get("branch_type"))

    warnings: list[str] = []
    if status and status != "ACTIVE":
        warnings.append(f"Статус в ЕГРЮЛ: {status_text}.")
    if is_invalid:
        warnings.append("В ЕГРЮЛ есть отметка о недостоверных сведениях.")
    address_data = _mapping(address.get("data"))
    if address_data.get("qc") in (1, 3):
        warnings.append("Адрес в ЕГРЮЛ требует ручной проверки.")

    return PartyRequisites(
        short_name=short_name,
        full_name=full_name,
        legal_form=_legal_form(data),
        inn=_text(data.get("inn")) or query_inn,
        kpp=_text(data.get("kpp")) or query_kpp,
        ogrn=_text(data.get("ogrn")),
        legal_address=legal_address,
        status=status,
        status_text=status_text,
        is_invalid=is_invalid,
        branch_type=branch_type,
        warnings=tuple(warnings),
    )


class DadataClient:
    """HTTP-клиент DaData Suggestions API."""

    def __init__(self) -> None:
        self.api_key = _text(getattr(settings, "DADATA_API_KEY", ""))
        self.secret_key = _text(getattr(settings, "DADATA_SECRET_KEY", ""))
        self.url = _text(
            getattr(settings, "DADATA_SUGGEST_URL", DEFAULT_SUGGEST_URL)
        ) or DEFAULT_SUGGEST_URL
        try:
            self.timeout = float(getattr(settings, "DADATA_TIMEOUT", 5) or 5)
        except (TypeError, ValueError):
            self.timeout = 5.0
        if self.timeout <= 0:
            self.timeout = 5.0

    @property
    def is_configured(self) -> bool:
        """Можно ли выполнять запросы к DaData."""
        return bool(self.api_key)

    def find_party(self, inn: str, kpp: str = "") -> PartyRequisites:
        """
        Ищет организацию по ИНН/КПП.

        Если КПП не указан, запрашивается головная организация. Если указан —
        DaData ищет конкретный филиал. Ответ маппится в ``PartyRequisites``.

        :raises DadataNotConfigured: нет API-ключа;
        :raises DadataNotFound: организация не найдена;
        :raises DadataUnavailable: сеть, HTTP-ошибка или плохой JSON.
        """
        if not self.api_key:
            raise DadataNotConfigured("DADATA_API_KEY не задан.")

        payload: dict[str, str] = {"query": inn}
        if kpp:
            payload["kpp"] = kpp
        else:
            payload["branch_type"] = "MAIN"

        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Token {self.api_key}",
        }
        if self.secret_key:
            headers["X-Secret"] = self.secret_key

        try:
            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DadataUnavailable("DaData недоступен.") from exc

        if response.status_code != 200:
            # Тело ответа не логируем: там могут быть пользовательские данные.
            logger.warning("DaData вернул HTTP %s", response.status_code)
            raise DadataUnavailable(
                f"DaData вернул HTTP {response.status_code}."
            )

        try:
            payload_json = response.json()
        except ValueError as exc:
            raise DadataUnavailable("DaData вернул некорректный JSON.") from exc

        suggestions = (
            payload_json.get("suggestions")
            if isinstance(payload_json, dict)
            else None
        )
        if not isinstance(suggestions, list):
            raise DadataUnavailable("В ответе DaData нет списка suggestions.")

        suggestions = [item for item in suggestions if isinstance(item, dict)]
        if not suggestions:
            raise DadataNotFound("Организация не найдена.")

        chosen = self._choose(suggestions, kpp)
        if chosen is None:
            raise DadataNotFound("Организация с указанным КПП не найдена.")

        return map_party(chosen, query_inn=inn, query_kpp=kpp)

    @staticmethod
    def _choose(suggestions: list[dict], kpp: str) -> dict | None:
        """Выбирает головную организацию или точное совпадение по КПП."""
        if kpp:
            for item in suggestions:
                data = _mapping(item.get("data"))
                if _text(data.get("kpp")) == kpp:
                    return item
            return None

        for item in suggestions:
            data = _mapping(item.get("data"))
            if _text(data.get("branch_type")).upper() == "MAIN":
                return item
        return suggestions[0]
