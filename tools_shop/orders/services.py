"""
orders/services.py

Операции над заявкой, которые затрагивают несколько моделей.

Одобрение заявки создаёт (или перевыпускает) счёт и переводит заявку в статус
«Счёт выставлен» в одной транзакции. Постановка PDF/письма в очередь делается
только через ``transaction.on_commit``: задача не должна увидеть счёт,
который ещё не закоммичен.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django_q.tasks import async_task

from .models import Invoice, InvoiceNotAllowed, Order
from .statuses import OrderStatus, TERMINAL_STATUSES

logger = logging.getLogger(__name__)

INVOICE_TASK = "orders.tasks.generate_and_send_invoice"


def _enqueue_invoice(invoice_id: int) -> None:
    """
    Ставит задачу формирования/отправки счёта.

    Ошибка Redis не должна откатывать уже выставленный счёт: менеджер увидит
    заявку, а задачу можно повторить вручную/повторной постановкой.
    """
    try:
        async_task(INVOICE_TASK, invoice_id)
    except Exception:  # noqa: BLE001 - фоновая инфраструктура не должна ломать заявку
        logger.exception("Не удалось поставить в очередь счёт %s", invoice_id)


def approve_order(
    order: Order,
    by=None,
    comment: str = "",
    *,
    enqueue: bool = True,
) -> Invoice:
    """
    Одобряет заявку: выставляет счёт и переводит её в ``invoiced``.

    * заявка должна быть на проверке (``review``) — до проверки счёт не выдаём;
    * первая версия получает номер из последовательности, повторная —
      тот же номер с ``version + 1``;
    * если переход не разрешён, транзакция откатывается целиком, и «висящего»
      счёта без статуса не остаётся;
    * после коммита ставится задача ``generate_and_send_invoice``.

    Возвращает созданный счёт.
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status != OrderStatus.REVIEW:
            raise InvoiceNotAllowed(locked.status)

        invoice = Invoice.issue_for(locked)
        locked.transition_to(
            OrderStatus.INVOICED,
            by=by,
            comment=comment or f"Выставлен счёт {invoice.number} (v{invoice.version})",
        )
        if enqueue:
            transaction.on_commit(
                lambda invoice_id=invoice.pk: _enqueue_invoice(invoice_id)
            )
    return invoice


def reissue_invoice(
    order: Order,
    by=None,
    comment: str = "",
    *,
    enqueue: bool = True,
) -> Invoice:
    """
    Перевыставляет действующий счёт новой версией.

    Статус заявки не меняется: перевыставление — исправление документа, а не
    новый переход. Старая версия остаётся в истории, новая становится
    действующей и отправляется клиенту после коммита.
    """
    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status in TERMINAL_STATUSES:
            raise InvoiceNotAllowed(locked.status)
        if not locked.invoices.current().exists():
            raise InvoiceNotAllowed(locked.status)

        invoice = Invoice.issue_for(locked)
        logger.info(
            "Счёт %s перевыставлен по заявке %s: v%s, by=%s, comment=%s",
            invoice.number,
            locked.number,
            invoice.version,
            by,
            comment,
        )
        if enqueue:
            transaction.on_commit(
                lambda invoice_id=invoice.pk: _enqueue_invoice(invoice_id)
            )
    return invoice
