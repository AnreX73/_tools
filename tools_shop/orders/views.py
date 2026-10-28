"""
orders/views.py

Публичная страница статуса заявки.

Доступ только по UUID: последовательный id наружу не отдаём, авторизация не
требуется. Комментарии менеджеров и служебные поля на страницу не попадают.
"""
from __future__ import annotations

from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache

from companies.models import LegalEntity
from companies.seller import get_seller

from .models import Invoice, Order
from .statuses import OrderStatus

STATUS_HINTS: dict[str, str] = {
    OrderStatus.NEW: (
        "Заявка принята. Менеджер проверит наличие товара и пришлёт счёт "
        "на указанный email."
    ),
    OrderStatus.REVIEW: (
        "Заявка на проверке. Менеджер уточняет наличие и условия поставки."
    ),
    OrderStatus.INVOICED: (
        "Счёт выставлен. Проверьте его и оплатите — после оплаты менеджер "
        "отметит заказ."
    ),
    OrderStatus.PAID: "Оплата получена. Заказ готовится к отгрузке.",
    OrderStatus.SHIPPED: "Заказ отгружен.",
    OrderStatus.DONE: "Заказ завершён. Спасибо за покупку!",
    OrderStatus.CANCELLED: (
        "Заказ отменён. Если это ошибка, свяжитесь с менеджером."
    ),
    OrderStatus.REJECTED: (
        "Заявка отклонена. Свяжитесь с менеджером, чтобы обсудить детали."
    ),
}


@never_cache
def detail(request, uuid):
    """Статус заявки по публичному UUID."""
    order = get_object_or_404(
        Order.objects.select_related("company").prefetch_related(
            "items",
            "status_log",
            Prefetch(
                "invoices",
                queryset=Invoice.objects.filter(is_current=True),
                to_attr="current_invoices",
            ),
        ),
        uuid=uuid,
    )
    current_invoice = order.current_invoices[0] if order.current_invoices else None
    snapshot = order.requisites_snapshot or {}
    # Для заявки со счётом показываем продавца из снимка документа: если
    # реквизиты поменяются, страница останется согласованной со счётом.
    order_seller = (
        current_invoice.seller_snapshot
        if current_invoice is not None and current_invoice.seller_snapshot
        else get_seller()
    )
    legal_form_label = dict(LegalEntity.LegalForm.choices).get(
        str(snapshot.get("legal_form", ""))
    )
    heading = (
        "Заявка принята"
        if order.status == OrderStatus.NEW
        else f"Заявка № {order.number}"
    )

    response = render(
        request,
        "orders/order_detail.html",
        {
            "title": f"Заявка № {order.number}",
            "order": order,
            "snapshot": snapshot,
            "order_seller": order_seller,
            "legal_form_label": legal_form_label,
            "current_invoice": current_invoice,
            "heading": heading,
            "status_hint": STATUS_HINTS.get(
                order.status, "Статус заявки обновляется менеджером."
            ),
        },
    )
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
