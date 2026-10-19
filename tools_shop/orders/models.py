"""
orders/models.py

Заявка (Order), её позиции и история статусов, а также счёт (Invoice).

Ключевые решения
----------------
* Публичная ссылка на заявку — только ``Order.uuid``: последовательные id
  наружу не отдаём.
* Номер заявки и номер счёта берутся из последовательностей PostgreSQL
  (``orders/sequences.py``), поэтому параллельные заявки не получают дублей.
* Позиции заказа — снимок: название, артикул и цена фиксируются на момент
  оформления. ``product`` нужен только для ссылки на карточку и может стать
  ``NULL``, если товар удалят.
* Допустимые переходы статусов описаны одной таблицей в
  ``orders/statuses.py``; ``Order.transition_to`` — единственный способ
  сменить статус, он же пишет ``OrderStatusLog``.
* Счёт получает номер только при одобрении заявки. При перевыставлении
  создаётся новая версия с тем же номером: клиенту привычнее видеть один
  номер счёта, а ``version`` отличает редакции. Предыдущая версия остаётся
  в истории с ``is_current=False``.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from .sequences import next_invoice_number, next_order_number
from .statuses import (
    EDITABLE_STATUSES,
    OrderStatus,
    TERMINAL_STATUSES,
    allowed_transitions,
    can_transition,
    is_terminal,
)

MONEY_PLACES = Decimal("0.01")


def normalize_email_lower(value: str) -> str:
    """Email храним целиком в нижнем регистре: поиск и сравнение без сюрпризов."""
    return (value or "").strip().lower()


def invoice_pdf_path(instance: "Invoice", filename: str) -> str:
    """Путь PDF: по uuid заказа, а не по публичному номеру (номер может смениться)."""
    issued = instance.issued_at or timezone.now()
    return f"invoices/{issued:%Y/%m}/{instance.order.uuid}-v{instance.version}.pdf"


class InvalidTransition(Exception):
    """Переход статуса запрещён таблицей переходов."""

    def __init__(self, from_status: str, to_status: str) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Нельзя перевести заявку из статуса «{OrderStatus(from_status).label}» "
            f"в «{OrderStatus(to_status).label}»."
        )


class InvoiceNotAllowed(Exception):
    """Счёт можно выставить только проверенной заявке."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(
            "Счёт выставляется только после проверки заявки менеджером. "
            f"Текущий статус: «{OrderStatus(status).label}»."
        )


class OrderQuerySet(models.QuerySet):
    def with_relations(self):
        """Список заявок без N+1: компания, автор и позиции."""
        return self.select_related("company", "user").prefetch_related("items")

    def open(self):
        return self.exclude(status__in=TERMINAL_STATUSES)

    def for_email(self, email: str):
        return self.filter(contact_email=normalize_email_lower(email))


class Order(models.Model):
    """Заявка покупателя. Создаётся на checkout, дальше живёт в админке."""

    uuid = models.UUIDField(
        "Публичный идентификатор",
        default=uuid4,
        unique=True,
        editable=False,
    )
    number = models.CharField(
        "Номер заявки",
        max_length=32,
        unique=True,
        editable=False,
        help_text="Присваивается автоматически из последовательности PostgreSQL.",
    )
    company = models.ForeignKey(
        "companies.LegalEntity",
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Организация",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
        verbose_name="Пользователь",
        help_text="Заполняется, когда появится личный кабинет.",
    )

    # ---- контакты ----
    contact_name = models.CharField("Контактное лицо", max_length=255)
    contact_email = models.EmailField("Email", db_index=True)
    contact_phone = models.CharField("Телефон", max_length=30, blank=True)

    # ---- доставка и комментарий ----
    delivery_address = models.TextField("Адрес доставки")
    comment = models.TextField("Комментарий", blank=True)

    # ---- реквизиты на момент заявки ----
    requisites_snapshot = models.JSONField(
        "Реквизиты на момент заявки",
        default=dict,
        blank=True,
        help_text="Копия полей формы checkout: организация не перезаписывается "
        "при повторных заявках, поэтому история хранится здесь.",
    )

    # ---- служебное ----
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=OrderStatus.choices,
        default=OrderStatus.NEW,
        db_index=True,
    )
    idempotency_key = models.UUIDField(
        "Ключ идемпотентности",
        default=uuid4,
        unique=True,
        editable=False,
        help_text="Защита от двойной отправки формы оформления.",
    )
    consent_at = models.DateTimeField(
        "Согласие на обработку персональных данных",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Изменена", auto_now=True)

    objects = OrderQuerySet.as_manager()

    class Meta:
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="order_status_created_idx"),
            models.Index(fields=["company", "created_at"], name="order_company_created_idx"),
        ]

    def __str__(self) -> str:
        return self.number

    # ---- сохранение -------------------------------------------------------
    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_order_number()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = {*update_fields, "number"}
        self.contact_email = normalize_email_lower(self.contact_email)
        super().save(*args, **kwargs)

    # ---- агрегаты ---------------------------------------------------------
    @property
    def items_total(self) -> Decimal:
        """Сумма позиций с точностью до копейки."""
        total = sum((item.line_total for item in self.items.all()), Decimal("0"))
        return total.quantize(MONEY_PLACES)

    @property
    def is_editable(self) -> bool:
        """Состав заказа можно править только до выставления счёта."""
        return self.status in EDITABLE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return is_terminal(self.status)

    def allowed_transitions(self) -> frozenset[str]:
        return allowed_transitions(self.status)

    def log_created(self, by=None, comment: str = "") -> "OrderStatusLog":
        """
        Первая запись в истории: заявка создана.

        ``from_status`` пустой — перехода не было. Вызывается из checkout
        в той же транзакции, что и создание заявки.
        """
        return OrderStatusLog.objects.create(
            order=self,
            from_status="",
            to_status=self.status,
            changed_by=by,
            comment=comment,
        )

    # ---- статусы ----------------------------------------------------------
    def transition_to(
        self,
        status: str,
        by=None,
        comment: str = "",
    ) -> "Order":
        """
        Переводит заявку в новый статус и пишет запись в историю.

        * проверяет переход по таблице ``TRANSITIONS``;
        * блокирует строку заявки на время перехода (``select_for_update``),
          чтобы два менеджера не сделали взаимоисключающие переходы;
        * для статуса «Счёт выставлен» требует действующий счёт: статус не
          должен опережать документ.

        Бросает ``InvalidTransition``, ничего не записывая.
        """
        if status not in OrderStatus.values:
            raise ValueError(f"Неизвестный статус заявки: {status!r}")

        with transaction.atomic():
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if status == locked.status:
                raise InvalidTransition(locked.status, status)
            if not can_transition(locked.status, status):
                raise InvalidTransition(locked.status, status)
            if status == OrderStatus.INVOICED and not locked.invoices.filter(
                is_current=True
            ).exists():
                raise InvalidTransition(locked.status, status)

            from_status = locked.status
            locked.status = status
            locked.save(update_fields=["status", "updated_at"])
            OrderStatusLog.objects.create(
                order=locked,
                from_status=from_status,
                to_status=status,
                changed_by=by,
                comment=comment,
            )

        self.status = status
        self.updated_at = locked.updated_at
        return self


class OrderItem(models.Model):
    """Позиция заявки — снимок товара на момент оформления."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Заявка",
    )
    product = models.ForeignKey(
        "shop.Product",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_items",
        verbose_name="Товар",
        help_text="Может стать пустым, если товар удалят; данные позиции сохраняются.",
    )
    name = models.CharField("Название", max_length=255)
    sku = models.CharField("Артикул", max_length=64)
    price = models.DecimalField(
        "Цена",
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    qty = models.PositiveIntegerField(
        "Количество",
        validators=[MinValueValidator(1)],
    )

    class Meta:
        verbose_name = "Позиция заявки"
        verbose_name_plural = "Позиции заявки"
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(qty__gte=1),
                name="order_item_qty_positive",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.sku} × {self.qty}"

    @property
    def line_total(self) -> Decimal:
        return (self.price * self.qty).quantize(MONEY_PLACES)


class OrderStatusLog(models.Model):
    """История переходов: кто, когда и почему сменил статус."""

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="status_log",
        verbose_name="Заявка",
    )
    from_status = models.CharField(
        "Из статуса",
        max_length=16,
        choices=OrderStatus.choices,
        blank=True,
        help_text="Пусто — заявка только что создана.",
    )
    to_status = models.CharField(
        "В статус",
        max_length=16,
        choices=OrderStatus.choices,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="order_status_changes",
        verbose_name="Изменил",
    )
    at = models.DateTimeField("Когда", auto_now_add=True, db_index=True)
    comment = models.TextField("Комментарий", blank=True)

    class Meta:
        verbose_name = "История статуса"
        verbose_name_plural = "История статусов"
        ordering = ["-at", "-pk"]

    def __str__(self) -> str:
        if not self.from_status:
            return f"{self.order_id}: создана → {self.to_status}"
        return f"{self.order_id}: {self.from_status} → {self.to_status}"


class InvoiceQuerySet(models.QuerySet):
    def current(self):
        return self.filter(is_current=True)


class Invoice(models.Model):
    """
    Счёт на оплату. Номер выдаётся только при одобрении заявки менеджером.

    Все версии одного счёта делят номер, различаются ``version``. Действующая
    версия ровно одна на заявку (частичный уникальный индекс).
    """

    order = models.ForeignKey(
        Order,
        on_delete=models.PROTECT,
        related_name="invoices",
        verbose_name="Заявка",
    )
    number = models.CharField(
        "Номер счёта",
        max_length=32,
        db_index=True,
        editable=False,
        help_text="Из последовательности PostgreSQL; присваивается при одобрении.",
    )
    version = models.PositiveIntegerField("Версия", default=1)
    issued_at = models.DateTimeField("Выставлен", default=timezone.now)
    pdf = models.FileField(
        "PDF",
        upload_to=invoice_pdf_path,
        blank=True,
        help_text="Заполняется фоновой задачей после одобрения заявки.",
    )
    sent_at = models.DateTimeField("Отправлен клиенту", null=True, blank=True)
    is_current = models.BooleanField("Действующая версия", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    objects = InvoiceQuerySet.as_manager()

    class Meta:
        verbose_name = "Счёт"
        verbose_name_plural = "Счета"
        ordering = ["-issued_at", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "version"],
                name="uniq_invoice_order_version",
            ),
            models.UniqueConstraint(
                fields=["order"],
                condition=Q(is_current=True),
                name="uniq_current_invoice_per_order",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.number} (v{self.version})"

    @property
    def is_sent(self) -> bool:
        return self.sent_at is not None

    @classmethod
    def issue_for(cls, order: Order) -> "Invoice":
        """
        Создаёт новую версию счёта для заявки.

        * первая версия получает номер из последовательности;
        * повторная — тот же номер и ``version + 1``;
        * прошлая действующая версия становится историей;
        * строка заявки блокируется, чтобы параллельные одобрения не создали
          две «действующие» версии.

        Метод не меняет статус заявки: это делает вызывающий код
        (``order.transition_to(OrderStatus.INVOICED)``).
        """
        with transaction.atomic():
            locked_order = Order.objects.select_for_update().get(pk=order.pk)
            previous = (
                cls.objects.select_for_update()
                .filter(order=locked_order)
                .order_by("-version")
                .first()
            )
            if previous is None:
                number = next_invoice_number()
                version = 1
            else:
                number = previous.number
                version = previous.version + 1

            cls.objects.filter(order=locked_order, is_current=True).update(
                is_current=False
            )
            return cls.objects.create(
                order=locked_order,
                number=number,
                version=version,
                is_current=True,
            )
