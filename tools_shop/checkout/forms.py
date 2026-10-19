"""
checkout/forms.py

Форма реквизитов для оформления заявки.

Это обычная ``forms.Form``, а не ``ModelForm`` на ``LegalEntity``:
* проверка уникальности ИНН/КПП не должна срабатывать до создания заявки;
* форма не перезаписывает существующую организацию (см. ``checkout/services.py``).

Подстановка реквизитов по ИНН — отдельная вьюха и сервис
(``checkout.lookup``): она сначала ищет карточку в базе и только потом
обращается к DaData.

Все поля, которые попадут в снимок реквизитов заявки, перечислены в
``SNAPSHOT_FIELDS``. Служебные поля (согласие, honeypot, ключ идемпотентности)
в снимок не входят.
"""
from __future__ import annotations

import re

from django import forms
from django.core.validators import RegexValidator

from companies.models import LegalEntity
from companies.validators import validate_inn

#: Поля формы, которые копируются в ``Order.requisites_snapshot``.
SNAPSHOT_FIELDS: tuple[str, ...] = (
    "legal_form",
    "short_name",
    "full_name",
    "inn",
    "kpp",
    "ogrn",
    "legal_address",
    "delivery_address",
    "bank_name",
    "bik",
    "correspondent_account",
    "checking_account",
    "contact_name",
    "email",
    "phone",
    "comment",
)


class DigitsField(forms.CharField):
    """Текстовое поле, из которого перед проверкой убираются все пробелы."""

    def to_python(self, value):
        value = super().to_python(value)
        if isinstance(value, str):
            return re.sub(r"\s+", "", value)
        return value


class CheckoutForm(forms.Form):
    """Реквизиты организации и контакты для заявки."""

    legal_form = forms.ChoiceField(
        label="Организационно-правовая форма",
        choices=LegalEntity.LegalForm.choices,
        initial=LegalEntity.LegalForm.OOO,
        widget=forms.Select(attrs={"autocomplete": "organization"}),
    )
    short_name = forms.CharField(
        label="Краткое наименование",
        max_length=255,
        widget=forms.TextInput(
            attrs={"autocomplete": "organization", "placeholder": 'ООО "ПК ИНСТРУМЕНТ"'}
        ),
    )
    full_name = forms.CharField(
        label="Полное наименование",
        max_length=512,
        widget=forms.TextInput(
            attrs={
                "autocomplete": "organization",
                "placeholder": 'ООО "Производственная компания ИНСТРУМЕНТ"',
            }
        ),
    )
    inn = DigitsField(
        label="ИНН",
        max_length=12,
        validators=[validate_inn],
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "off",
                "maxlength": "12",
                "placeholder": "10 или 12 цифр",
            }
        ),
        help_text="10 цифр для юридического лица, 12 — для ИП.",
    )
    kpp = DigitsField(
        label="КПП",
        max_length=9,
        required=False,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "off",
                "maxlength": "9",
                "placeholder": "9 цифр",
            }
        ),
        help_text="Обязателен для ИНН из 10 цифр. У ИП КПП нет.",
    )
    ogrn = DigitsField(
        label="ОГРН/ОГРНИП",
        max_length=15,
        required=False,
        validators=[
            RegexValidator(r"^\d{13}(\d{2})?$", "ОГРН — 13 или 15 цифр.")
        ],
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "off",
                "maxlength": "15",
                "placeholder": "13 или 15 цифр",
            }
        ),
        help_text="Можно заполнить автоматически по ИНН.",
    )
    legal_address = forms.CharField(
        label="Юридический адрес",
        widget=forms.Textarea(attrs={"rows": 2, "autocomplete": "street-address"}),
    )
    delivery_address = forms.CharField(
        label="Адрес доставки",
        widget=forms.Textarea(
            attrs={"rows": 2, "autocomplete": "shipping street-address"}
        ),
        help_text="Улица, дом, город, индекс; при необходимости — до склада ТК.",
    )

    bank_name = forms.CharField(
        label="Наименование банка",
        max_length=255,
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    bik = DigitsField(
        label="БИК",
        max_length=9,
        required=False,
        validators=[RegexValidator(r"^\d{9}$", "БИК должен содержать 9 цифр.")],
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "off", "maxlength": "9"}
        ),
    )
    correspondent_account = DigitsField(
        label="Корр. счёт",
        max_length=20,
        required=False,
        validators=[
            RegexValidator(r"^\d{20}$", "Корр. счёт должен содержать 20 цифр.")
        ],
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "off", "maxlength": "20"}
        ),
    )
    checking_account = DigitsField(
        label="Расчётный счёт",
        max_length=20,
        required=False,
        validators=[
            RegexValidator(r"^\d{20}$", "Расчётный счёт должен содержать 20 цифр.")
        ],
        widget=forms.TextInput(
            attrs={"inputmode": "numeric", "autocomplete": "off", "maxlength": "20"}
        ),
    )

    contact_name = forms.CharField(
        label="Контактное лицо",
        max_length=255,
        widget=forms.TextInput(attrs={"autocomplete": "name"}),
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(
            attrs={"autocomplete": "email", "inputmode": "email"}
        ),
        help_text="На этот адрес менеджер пришлёт счёт.",
    )
    phone = forms.CharField(
        label="Телефон",
        max_length=30,
        required=False,
        widget=forms.TextInput(
            attrs={"autocomplete": "tel", "inputmode": "tel", "placeholder": "+7 ..."}
        ),
    )
    comment = forms.CharField(
        label="Комментарий",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Например, удобное время доставки"}
        ),
    )

    consent = forms.BooleanField(
        label="Согласен на обработку персональных данных",
        error_messages={
            "required": "Без согласия на обработку персональных данных "
            "оформить заявку нельзя."
        },
    )
    honeypot = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={"autocomplete": "off", "tabindex": "-1", "aria-hidden": "true"}
        ),
    )
    idempotency_key = forms.UUIDField(
        widget=forms.HiddenInput,
        error_messages={
            "required": "Не удалось определить сессию оформления. "
            "Обновите страницу и попробуйте снова.",
            "invalid": "Некорректный ключ оформления. Обновите страницу.",
        },
    )

    # ---- проверки отдельных полей ----------------------------------------
    def clean_inn(self) -> str:
        return self.cleaned_data["inn"]

    def clean_kpp(self) -> str:
        value = self.cleaned_data.get("kpp") or ""
        if value and not re.fullmatch(r"\d{9}", value):
            raise forms.ValidationError("КПП должен содержать 9 цифр.")
        return value

    def clean_email(self) -> str:
        # Домены и адреса сравниваем без учёта регистра.
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        cleaned = super().clean()

        # Honeypot: скрытое поле человек не видит и не заполняет.
        if cleaned.get("honeypot"):
            raise forms.ValidationError(
                "Не удалось отправить форму. Проверьте данные и попробуйте ещё раз."
            )

        inn = cleaned.get("inn") or ""
        kpp = cleaned.get("kpp") or ""
        if len(inn) == 10 and not kpp:
            self.add_error("kpp", "Для ИНН из 10 цифр КПП обязателен.")
        elif len(inn) == 12 and kpp:
            self.add_error("kpp", "Для ИНН из 12 цифр (ИП) КПП не заполняется.")

        # Банковские реквизиты необязательны, но если их начали заполнять,
        # требуем минимально достаточный набор — иначе счёт не выставить.
        bank_fields = {
            "bank_name": cleaned.get("bank_name") or "",
            "bik": cleaned.get("bik") or "",
            "correspondent_account": cleaned.get("correspondent_account") or "",
            "checking_account": cleaned.get("checking_account") or "",
        }
        if any(bank_fields.values()):
            if not bank_fields["bank_name"]:
                self.add_error("bank_name", "Укажите наименование банка.")
            if not bank_fields["bik"]:
                self.add_error("bik", "Укажите БИК банка.")
            if not bank_fields["checking_account"]:
                self.add_error("checking_account", "Укажите расчётный счёт.")

        return cleaned
