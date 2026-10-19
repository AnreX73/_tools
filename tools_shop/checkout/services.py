"""
checkout/services.py

Создание заявки из корзины.

Вся операция — одна транзакция: либо появляются заявка, её позиции и запись
в истории, либо не появляется ничего. Повторная отправка формы с тем же
``idempotency_key`` возвращает уже созданную заявку.

Организация ищется по паре (ИНН, КПП):
* если её нет — создаётся с реквизитами из формы;
* если есть — НЕ перезаписывается. Покупатель мог указать в форме другие
  реквизиты, поэтому для истории они сохраняются в
  ``Order.requisites_snapshot``, а не в карточке организации.

Фоновые задачи ставятся через ``transaction.on_commit``: письма уходят только
после того, как заявка действительно сохранена.
"""
from __future__ import annotations

import logging
from typing import Mapping

from django.db import IntegrityError, transaction
from django.utils import timezone
from django_q.tasks import async_task

from cart.services import Cart, CartLine
from companies.models import LegalEntity
from orders.models import Order, OrderItem
from orders.statuses import OrderStatus

from .forms import SNAPSHOT_FIELDS

logger = logging.getLogger(__name__)

TASK_NOTIFY_MANAGERS = "orders.tasks.notify_managers"
TASK_ACCEPTED_EMAIL = "orders.tasks.send_order_accepted_email"


class EmptyCart(Exception):
    """В корзине не осталось доступных позиций."""


def _snapshot(form_data: Mapping) -> dict[str, str]:
    """Снимок реквизитов: только поля формы, без служебных значений."""
    result: dict[str, str] = {}
    for field in SNAPSHOT_FIELDS:
        value = form_data.get(field, "")
        result[field] = "" if value is None else str(value)
    return result


def _company_defaults(form_data: Mapping) -> dict:
    """Поля новой организации. Существующая организация ими не обновляется."""
    return {
        "full_name": str(form_data.get("full_name") or ""),
        "short_name": str(form_data.get("short_name") or ""),
        "legal_form": str(form_data.get("legal_form") or LegalEntity.LegalForm.OOO),
        "legal_address": str(form_data.get("legal_address") or ""),
        "actual_address": str(form_data.get("delivery_address") or ""),
        "bank_name": str(form_data.get("bank_name") or ""),
        "bik": str(form_data.get("bik") or ""),
        "correspondent_account": str(form_data.get("correspondent_account") or ""),
        "checking_account": str(form_data.get("checking_account") or ""),
        "ogrn": str(form_data.get("ogrn") or ""),
        "email": str(form_data.get("email") or "").lower(),
        "phone": str(form_data.get("phone") or ""),
    }


def _order_items(order: Order, lines: list[CartLine]) -> list[OrderItem]:
    """Снимок позиций: название, артикул и цена фиксируются сейчас."""
    return [
        OrderItem(
            order=order,
            product=line.product,
            name=line.product.name,
            sku=line.product.sku,
            price=line.price,
            qty=line.qty,
        )
        for line in lines
    ]


def find_order_by_key(idempotency_key) -> Order | None:
    """Заявка, созданная с этим ключом (для повторной отправки формы)."""
    if not idempotency_key:
        return None
    return Order.objects.filter(idempotency_key=idempotency_key).first()


def _enqueue(task_path: str, order_id: int) -> None:
    """
    Ставит задачу django-q2, не роняя оформление при недоступной очереди.

    Заявка уже сохранена; если Redis недоступен, менеджер увидит её в админке,
    а ошибка попадёт в лог. Повторы задач настраиваются на этапе 5.
    """
    try:
        async_task(task_path, order_id)
    except Exception:
        logger.exception("Не удалось поставить задачу %s для заявки %s", task_path, order_id)


def place_order(
    cart: Cart,
    form_data: Mapping,
    idempotency_key,
    user=None,
) -> Order:
    """
    Создаёт заявку по содержимому корзины.

    :param cart: сервис корзины; позиции берутся с актуальными ценами;
    :param form_data: очищенные данные ``CheckoutForm``;
    :param idempotency_key: UUID попытки оформления;
    :param user: авторизованный пользователь или ``None``;
    :return: созданная или уже существующая заявка.

    :raises EmptyCart: если доступных позиций не осталось.
    """
    try:
        with transaction.atomic():
            # Проверка идемпотентности и все записи — в одной транзакции.
            existing = find_order_by_key(idempotency_key)
            if existing is not None:
                return existing

            lines = cart.items()
            if not lines:
                raise EmptyCart("В корзине не осталось товаров для оформления.")

            company, _created = LegalEntity.objects.get_or_create(
                inn=str(form_data["inn"]).strip(),
                kpp=str(form_data.get("kpp") or "").strip(),
                defaults=_company_defaults(form_data),
            )

            order = Order.objects.create(
                company=company,
                user=user if getattr(user, "is_authenticated", False) else None,
                contact_name=str(form_data.get("contact_name") or ""),
                contact_email=str(form_data.get("email") or ""),
                contact_phone=str(form_data.get("phone") or ""),
                delivery_address=str(form_data.get("delivery_address") or ""),
                comment=str(form_data.get("comment") or ""),
                requisites_snapshot=_snapshot(form_data),
                status=OrderStatus.NEW,
                idempotency_key=idempotency_key,
                consent_at=timezone.now(),
            )
            OrderItem.objects.bulk_create(_order_items(order, lines))
            order.log_created(comment="Заявка оформлена на сайте")

            # Письма — только после фиксации транзакции.
            transaction.on_commit(
                lambda order_id=order.pk: _enqueue(TASK_NOTIFY_MANAGERS, order_id)
            )
            transaction.on_commit(
                lambda order_id=order.pk: _enqueue(TASK_ACCEPTED_EMAIL, order_id)
            )
    except IntegrityError:
        # Параллельная отправка с тем же ключом: уникальный индекс не дал
        # создать дубль. Возвращаем заявку, которую успел создать соседний
        # запрос; прочие IntegrityError пробрасываем дальше.
        existing = find_order_by_key(idempotency_key)
        if existing is None:
            raise
        return existing

    return order
