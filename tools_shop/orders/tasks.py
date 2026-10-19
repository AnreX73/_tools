"""
orders/tasks.py

Фоновые задачи по заявкам.

* ``notify_managers`` — диспетчер уведомлений менеджерам. Сейчас канал один
  (email), но новые каналы добавляются внутри этой функции, а вызывающий код
  не меняется.
* ``send_order_accepted_email`` — подтверждение покупателю.
* ``generate_and_send_invoice`` — WeasyPrint PDF, письмо с вложением и
  отметка ``sent_at``. Задача идемпотентна: повторный запуск после успешной
  отправки ничего не делает.

Ошибки не глотаются: django-q2 должен увидеть исключение и повторить задачу
(``Q_CLUSTER["max_attempts"]``).
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage, send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import Invoice, Order
from .pdf import render_invoice_pdf

logger = logging.getLogger(__name__)


def _site_url() -> str:
    return str(getattr(settings, "SITE_URL", "http://localhost:8002")).rstrip("/") + "/"


def _public_order_url(order: Order) -> str:
    path = reverse("orders:detail", args=[order.uuid])
    return urljoin(_site_url(), path.lstrip("/"))


def _admin_order_url(order: Order) -> str:
    path = reverse("admin:orders_order_change", args=[order.pk])
    return urljoin(_site_url(), path.lstrip("/"))


def _recipients() -> list[str]:
    raw = getattr(settings, "MANAGER_NOTIFY_EMAILS", [])
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item).strip() for item in raw if str(item).strip()]


def _load_order(order_id: int) -> Order | None:
    return (
        Order.objects.select_related("company")
        .prefetch_related("items")
        .filter(pk=order_id)
        .first()
    )


def _manager_email_body(order: Order) -> str:
    items = "\n".join(
        f"— {item.name} ({item.sku}): {item.qty} × {item.price} = {item.line_total}"
        for item in order.items.all()
    )
    body = (
        f"Новая заявка № {order.number} от {order.created_at:%d.%m.%Y %H:%M}.\n\n"
        f"Организация: {order.requisites_snapshot.get('short_name', order.company.short_name)}\n"
        f"ИНН/КПП: {order.requisites_snapshot.get('inn', '')} / "
        f"{order.requisites_snapshot.get('kpp', '')}\n"
        f"Контакт: {order.contact_name}, {order.contact_email}, "
        f"{order.contact_phone or 'телефон не указан'}\n"
        f"Адрес доставки: {order.delivery_address}\n\n"
        f"Позиции:\n{items}\n\n"
        f"Итого: {order.items_total}\n"
        f"Заявка в админке: {_admin_order_url(order)}\n"
        f"Публичная страница заявки: {_public_order_url(order)}\n"
    )
    if order.comment:
        body += f"\nКомментарий покупателя:\n{order.comment}\n"
    return body


def notify_managers(order: Order | int) -> int:
    """
    Диспетчер уведомлений менеджерам о новой заявке.

    Принимает как объект ``Order``, так и id — django-q2 передаёт аргументы
    через сериализацию, поэтому из очереди приходит id.

    Возвращает число отправленных писем.
    """
    if not isinstance(order, Order):
        loaded = _load_order(int(order))
        if loaded is None:
            logger.warning("notify_managers: заявка %s не найдена", order)
            return 0
        order = loaded

    recipients = _recipients()
    if not recipients:
        logger.info("notify_managers: MANAGER_NOTIFY_EMAILS не задан, письмо пропущено")
        return 0

    send_mail(
        f"Новая заявка {order.number}",
        _manager_email_body(order),
        settings.DEFAULT_FROM_EMAIL,
        recipients,
        fail_silently=False,
    )
    return 1


def send_order_accepted_email(order_id: int) -> int:
    """Письмо покупателю: заявка принята. Возвращает число писем."""
    order = _load_order(order_id)
    if order is None:
        logger.warning("send_order_accepted_email: заявка %s не найдена", order_id)
        return 0
    if not order.contact_email:
        logger.info("send_order_accepted_email: у заявки %s нет email", order.number)
        return 0

    body = (
        f"Здравствуйте!\n\n"
        f"Ваша заявка № {order.number} принята.\n"
        f"Менеджер проверит наличие товара и пришлёт счёт на этот адрес.\n\n"
        f"Состав заявки:\n"
        + "\n".join(
            f"— {item.name} ({item.sku}): {item.qty} × {item.price} = {item.line_total}"
            for item in order.items.all()
        )
        + f"\n\nИтого: {order.items_total}\n"
        f"Статус заявки: {_public_order_url(order)}\n\n"
        f"Если вы не оформляли заявку, просто проигнорируйте это письмо.\n"
    )
    send_mail(
        f"Заявка {order.number} принята",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [order.contact_email],
        fail_silently=False,
    )
    return 1


def _invoice_email_body(invoice: Invoice) -> str:
    order = invoice.order
    return (
        f"Здравствуйте, {order.contact_name}!\n\n"
        f"Направляем счёт № {invoice.number} от {invoice.issued_at:%d.%m.%Y} "
        f"по заявке № {order.number}.\n"
        f"Сумма к оплате: {order.items_total} руб.\n\n"
        f"Счёт приложен к письму в формате PDF.\n"
        f"Статус заявки: {_public_order_url(order)}\n\n"
        f"Если у вас есть вопросы, ответьте на это письмо.\n"
    )


def generate_and_send_invoice(invoice_id: int) -> int:
    """
    Формирует PDF счёта, сохраняет его в ``Invoice.pdf`` и отправляет клиенту.

    Идемпотентность:
    * если ``sent_at`` уже заполнен — письмо повторно не отправляется;
    * если счёт не действующий (старая версия) — задача ничего не делает;
    * строка счёта блокируется на время работы, чтобы два воркера не
      отправили один и тот же счёт.

    Возвращает 1 при отправке и 0, если отправка не требовалась.
    """
    with transaction.atomic():
        invoice = (
            Invoice.objects.select_for_update()
            .select_related("order__company")
            .prefetch_related("order__items")
            .filter(pk=invoice_id)
            .first()
        )
        if invoice is None:
            logger.warning("generate_and_send_invoice: счёт %s не найден", invoice_id)
            return 0
        if invoice.sent_at is not None:
            logger.info(
                "generate_and_send_invoice: счёт %s уже отправлен %s",
                invoice.number,
                invoice.sent_at,
            )
            return 0
        if not invoice.is_current:
            logger.warning(
                "generate_and_send_invoice: счёт %s (v%s) не действующий",
                invoice.number,
                invoice.version,
            )
            return 0

        order = invoice.order
        if not order.contact_email:
            logger.warning(
                "generate_and_send_invoice: у заявки %s нет email", order.number
            )
            return 0

        pdf_bytes = render_invoice_pdf(invoice)
        filename = f"invoice-{invoice.pk}-v{invoice.version}.pdf"
        invoice.pdf.save(filename, ContentFile(pdf_bytes), save=False)

        message = EmailMessage(
            f"Счёт № {invoice.number} по заявке {order.number}",
            _invoice_email_body(invoice),
            settings.DEFAULT_FROM_EMAIL,
            [order.contact_email],
        )
        message.attach(filename, pdf_bytes, "application/pdf")
        message.send(fail_silently=False)

        invoice.sent_at = timezone.now()
        invoice.save(update_fields=["pdf", "sent_at"])

    return 1
