"""
orders/pdf.py

Формирование PDF счёта из HTML-шаблона через WeasyPrint.

Почему отдельный модуль:
* шаблон и рендер не зависят от django-q2 и админки;
* в тестах можно подменить ``_html_class`` и не требовать системных
  библиотек Pango/GTK;
* при отсутствии WeasyPrint ошибка понятная, а задача django-q2 получает
  исключение и уходит на повтор.

Все данные покупателя подставляются в шаблон обычными ``{{ ... }}``:
Django экранирует их, поэтому ``|safe`` здесь не нужен и запрещён.
"""
from __future__ import annotations

from django.conf import settings
from django.template.loader import render_to_string

from companies.models import LegalEntity
from companies.seller import get_seller, is_seller_configured

from .models import Invoice


class InvoicePDFError(Exception):
    """PDF счёта сформировать не удалось."""


def _html_class():
    """
    Ленивый импорт WeasyPrint.

    На Windows без GTK3/Pango импорт падает с OSError; приложение не должно
    падать целиком из-за этого — ошибка возникнет только при генерации PDF.
    """
    from weasyprint import HTML

    return HTML


def _legal_form_label(value: str) -> str:
    return dict(LegalEntity.LegalForm.choices).get(str(value or ""), str(value or ""))


def render_invoice_pdf(invoice: Invoice) -> bytes:
    """
    Возвращает PDF счёта как bytes.

    Реквизиты продавца берутся из снимка счёта (``Invoice.seller_snapshot``).
    Для старых счетов без снимка — из активного профиля продавца. Реквизиты
    покупателя — из снимка заявки, а не из текущей карточки организации:
    счёт должен соответствовать тому, что покупатель указал при оформлении.
    """
    seller = invoice.seller_snapshot or get_seller()
    if not is_seller_configured(seller):
        raise InvoicePDFError(
            "Реквизиты продавца не заполнены. Откройте «Реквизиты продавца» "
            "в админке и укажите наименование, ИНН и юридический адрес."
        )
    order = invoice.order
    buyer = order.requisites_snapshot or {}

    html = render_to_string(
        "orders/invoice_pdf.html",
        {
            "invoice": invoice,
            "order": order,
            "seller": seller,
            "buyer": buyer,
            "buyer_legal_form": _legal_form_label(
                str(buyer.get("legal_form", ""))
            ),
        },
    )

    try:
        html_class = _html_class()
        return html_class(
            string=html,
            base_url=str(settings.BASE_DIR),
        ).write_pdf()
    except Exception as exc:  # noqa: BLE001 - наружу нужна понятная ошибка
        raise InvoicePDFError(
            "Не удалось сформировать PDF счёта. Проверьте установку "
            "WeasyPrint и системных библиотек Pango/GTK."
        ) from exc
