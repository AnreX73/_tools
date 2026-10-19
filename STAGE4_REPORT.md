# Этап 4 — полные файлы

Каждый файл приведён целиком, с полным путём от корня репозитория `_tools`.

## `tools_shop\checkout\__init__.py`

``python

````

## `tools_shop\checkout\apps.py`

``python
"""Конфигурация приложения checkout."""
from django.apps import AppConfig


class CheckoutConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # type: ignore[assignment]
    name = "checkout"
    verbose_name = "Оформление заказов"
````

## `tools_shop\checkout\forms.py`

``python
"""
checkout/forms.py

Форма реквизитов для оформления заявки.

Это обычная ``forms.Form``, а не ``ModelForm`` на ``LegalEntity``:
* проверка уникальности ИНН/КПП не должна срабатывать до создания заявки;
* форма не должна раскрывать, что организация уже есть в базе;
* существующая организация не перезаписывается (см. ``checkout/services.py``).

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
````

## `tools_shop\checkout\draft.py`

``python
"""
checkout/draft.py

Черновик формы и ключ идемпотентности в сессии.

Зачем черновик: если форма не прошла проверку, покупатель не должен заново
вводить реквизиты. В сессии хранятся только строки формы; пароли, файлы и
служебные поля туда не попадают. Черновик живёт ограниченное время, чтобы
персональные данные не лежали в сессии бессрочно.

Ключ идемпотентности создаётся при показе формы, передаётся в скрытом поле и
хранится в сессии. ``place_order`` по этому ключу понимает, что форма уже
отправлена, и не создаёт вторую заявку.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid4

from django.http import HttpRequest
from django.utils import timezone

from .forms import CheckoutForm

DRAFT_SESSION_KEY = "checkout_draft"
IDEMPOTENCY_SESSION_KEY = "checkout_idempotency_key"
DRAFT_TTL = timedelta(days=7)

#: Поля, которые нельзя хранить в черновике.
DRAFT_EXCLUDED = frozenset(
    {"csrfmiddlewaretoken", "honeypot", "idempotency_key", "consent"}
)
#: В сессию попадают только поля формы, а не произвольные ключи из POST.
DRAFT_FIELDS = frozenset(CheckoutForm.base_fields) - DRAFT_EXCLUDED


def _clean_data(data) -> dict[str, str]:
    """Оставляет только строковые значения полей формы."""
    result: dict[str, str] = {}
    for key, value in data.items():
        if key in DRAFT_EXCLUDED or key not in DRAFT_FIELDS:
            continue
        # QueryDict может отдать список; в форме нет множественного выбора,
        # поэтому берём последнее значение.
        if isinstance(value, (list, tuple)):
            value = value[-1] if value else ""
        result[str(key)] = "" if value is None else str(value)
    return result


def load_draft(request: HttpRequest) -> dict[str, str]:
    """Возвращает сохранённый черновик, если он не устарел."""
    payload = request.session.get(DRAFT_SESSION_KEY)
    if not isinstance(payload, dict):
        return {}
    saved_at = payload.get("saved_at")
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(saved_at, str):
        request.session.pop(DRAFT_SESSION_KEY, None)
        return {}
    try:
        saved = datetime.fromisoformat(saved_at)
    except ValueError:
        request.session.pop(DRAFT_SESSION_KEY, None)
        return {}
    if saved.tzinfo is None:
        saved = timezone.make_aware(saved, timezone.get_current_timezone())
    if timezone.now() - saved > DRAFT_TTL:
        request.session.pop(DRAFT_SESSION_KEY, None)
        return {}
    return {str(key): str(value) for key, value in data.items()}


def save_draft(request: HttpRequest, data) -> None:
    """Сохраняет введённые значения, чтобы не потерять их при ошибке."""
    request.session[DRAFT_SESSION_KEY] = {
        "data": _clean_data(data),
        "saved_at": timezone.now().isoformat(),
    }


def clear_draft(request: HttpRequest) -> None:
    request.session.pop(DRAFT_SESSION_KEY, None)


def ensure_idempotency_key(request: HttpRequest) -> str:
    """Возвращает ключ текущей попытки оформления, создавая его при показе формы."""
    key = request.session.get(IDEMPOTENCY_SESSION_KEY)
    if isinstance(key, str) and key:
        try:
            UUID(key)
        except ValueError:
            key = ""
    if not key:
        key = str(uuid4())
        request.session[IDEMPOTENCY_SESSION_KEY] = key
    return key


def clear_checkout_state(request: HttpRequest) -> None:
    """Убирает черновик и ключ после успешной заявки."""
    request.session.pop(DRAFT_SESSION_KEY, None)
    request.session.pop(IDEMPOTENCY_SESSION_KEY, None)
````

## `tools_shop\checkout\ratelimit.py`

``python
"""
checkout/ratelimit.py

Ограничение частоты POST-запросов на оформление заявки.

Счётчик живёт в Redis (``CACHES["default"]`` в настройках), поэтому ограничение
общее для всех процессов. Ключ — IP клиента; за прокси берём ``REMOTE_ADDR``,
а не подделываемый клиентом ``X-Forwarded-For`` (при необходимости доверенный
прокси настраивается отдельно).
"""
from __future__ import annotations

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

DEFAULT_LIMIT = 5
DEFAULT_WINDOW = 60 * 60  # час


def client_ip(request: HttpRequest) -> str:
    """
    IP клиента для ключа счётчика.

    Если сайт стоит за доверенным прокси и ``USE_X_FORWARDED_FOR`` включён,
    берём первый адрес из ``X-Forwarded-For``. По умолчанию доверяем только
    ``REMOTE_ADDR``: заголовок легко подделать на клиенте.
    """
    if getattr(settings, "USE_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
    return (request.META.get("REMOTE_ADDR") or "unknown").strip() or "unknown"


def _key(ip: str) -> str:
    return f"checkout:rate:{ip}"


def hit(request: HttpRequest) -> int:
    """
    Учитывает попытку отправки и возвращает число попыток за окно.

    ``cache.add`` атомарно создаёт счётчик; ``cache.incr`` атомарно увеличивает
    его в Redis. Если ключ успел истечь между операциями — начинаем заново.
    """
    window = int(getattr(settings, "CHECKOUT_RATE_WINDOW", DEFAULT_WINDOW))
    key = _key(client_ip(request))

    if cache.add(key, 1, window):
        return 1
    try:
        return int(cache.incr(key))
    except ValueError:
        # Ключ исчез между add и incr (истёк/сброшен) — начинаем окно заново.
        cache.set(key, 1, window)
        return 1


def is_rate_limited(request: HttpRequest) -> bool:
    """True, если лимит попыток уже исчерпан."""
    limit = int(getattr(settings, "CHECKOUT_RATE_LIMIT", DEFAULT_LIMIT))
    return hit(request) > limit


def retry_after() -> int:
    """Сколько секунд ждать до следующей попытки (для заголовка Retry-After)."""
    return int(getattr(settings, "CHECKOUT_RATE_WINDOW", DEFAULT_WINDOW))
````

## `tools_shop\checkout\services.py`

``python
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
````

## `tools_shop\checkout\views.py`

``python
"""
checkout/views.py

Страница оформления заявки и htmx-заглушка автозаполнения по ИНН.

Порядок проверок на POST:
1. повторная отправка уже созданной заявки (по ключу из сессии) — редирект;
2. пустая корзина — редирект в каталог;
3. изменения состава/цен — показать их до формы;
4. лимит попыток с IP;
5. валидация формы и создание заявки.

Корзина всегда перепроверяется на сервере: цены и доступность товаров в
сессии не хранятся, поэтому доверять данным из браузера нельзя.
"""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from cart.fingerprint import COOKIE_NAME, fingerprint_changed, remember_fingerprint
from cart.services import get_cart

from .draft import (
    IDEMPOTENCY_SESSION_KEY,
    clear_checkout_state,
    ensure_idempotency_key,
    load_draft,
    save_draft,
)
from .forms import CheckoutForm
from .ratelimit import is_rate_limited, retry_after
from .services import EmptyCart, find_order_by_key, place_order


def _cart_context(request: HttpRequest) -> dict:
    cart = get_cart(request)
    return {
        "cart": cart,
        "lines": cart.items(),
        "removed": list(cart.removed),
        "cart_total": cart.total(),
        "cart_count": cart.count(),
    }


def _render_with_fingerprint(
    request: HttpRequest,
    template: str,
    context: dict,
    *,
    status: int = 200,
) -> HttpResponse:
    """
    Рендер checkout-страницы + отпечаток текущей корзины.

    После ответа браузер запомнит, что покупатель видел именно это состояние:
    следующее изменение цены или состава снова покажем до формы.
    """
    response = render(request, template, context, status=status)
    return remember_fingerprint(response, get_cart(request))


@require_http_methods(["GET", "POST"])
def index(request: HttpRequest) -> HttpResponse:
    """Оформление заявки: показ формы и создание заказа."""
    cart = get_cart(request)

    # Повторная отправка (двойной клик, обновление POST-страницы) не должна
    # создавать новую заявку. Ключ берём только из сессии: чужой ключ из
    # скрытого поля не даёт доступа к чужой заявке.
    if request.method == "POST":
        existing = find_order_by_key(request.session.get(IDEMPOTENCY_SESSION_KEY))
        if existing is not None:
            cart.clear()
            clear_checkout_state(request)
            response = redirect("orders:detail", uuid=existing.uuid)
            response.delete_cookie(COOKIE_NAME)
            return response

    context = _cart_context(request)
    if not context["lines"]:
        return redirect("shop:catalog")

    price_changed = fingerprint_changed(request, cart)
    if context["removed"] or price_changed:
        # Данные, которые покупатель уже ввёл, не теряем: покажем форму после
        # подтверждения изменений.
        if request.method == "POST":
            save_draft(request, request.POST)
        context.update(
            {
                "title": "Корзина изменилась",
                "price_changed": price_changed,
                "draft_saved": request.method == "POST",
            }
        )
        return _render_with_fingerprint(
            request, "checkout/cart_changed.html", context
        )

    if request.method == "POST":
        if is_rate_limited(request):
            response = render(
                request,
                "checkout/rate_limited.html",
                {"title": "Слишком много попыток"},
                status=429,
            )
            response["Retry-After"] = str(retry_after())
            return response

        form = CheckoutForm(request.POST)
        if form.is_valid():
            session_key = request.session.get(IDEMPOTENCY_SESSION_KEY)
            posted_key = str(form.cleaned_data["idempotency_key"])
            if session_key and posted_key != str(session_key):
                # Форма из другой вкладки/сессии: не подставляем чужой ключ.
                form.add_error(
                    None,
                    "Форма устарела. Обновите страницу и отправьте заявку снова.",
                )
            else:
                key = str(session_key or posted_key)
                try:
                    order = place_order(
                        cart,
                        form.cleaned_data,
                        key,
                        user=request.user,
                    )
                except EmptyCart:
                    return redirect("shop:catalog")

                cart.clear()
                clear_checkout_state(request)
                response = redirect("orders:detail", uuid=order.uuid)
                response.delete_cookie(COOKIE_NAME)
                return response

        # Ошибки формы: сохраняем введённое, чтобы не заполнять заново.
        save_draft(request, request.POST)
    else:
        initial = load_draft(request)
        initial["idempotency_key"] = ensure_idempotency_key(request)
        form = CheckoutForm(initial=initial)

    context.update({"title": "Оформление заказа", "form": form})
    return _render_with_fingerprint(request, "checkout/form.html", context)


@require_GET
def suggest_by_inn(request: HttpRequest) -> HttpResponse:
    """
    Заглушка автозаполнения реквизитов по ИНН.

    Интерфейс: GET с параметром ``inn``; ответ — HTML-фрагмент для блока
    ``#inn-suggest``. Сейчас всегда пустой: подключение DaData появится
    позже, контракт вьюхи при этом менять не придётся.
    """
    return HttpResponse("", content_type="text/html; charset=utf-8")
````

## `tools_shop\checkout\urls.py`

``python
"""URL-маршруты приложения checkout."""
from django.urls import path

from . import views

app_name = "checkout"

urlpatterns = [
    path("", views.index, name="index"),
    path("suggest-by-inn/", views.suggest_by_inn, name="suggest_by_inn"),
]
````

## `tools_shop\checkout\templates\checkout\form.html`

``html
{% extends "shop/base.html" %}
{% load static %}
{% block title %}Оформление заказа{% endblock %}
{% block head %}
    <link rel="stylesheet" href="{% static 'css/checkout.css' %}">
{% endblock %}
{% block content %}
    <nav class="breadcrumbs">
        <a href="{% url 'shop:index' %}">Главная</a>
        <span class="sep">/</span> <a href="{% url 'cart:detail' %}">Корзина</a>
        <span class="sep">/</span> <span>Оформление</span>
    </nav>

    <h1 class="page-title">Оформление заказа</h1>
    <p class="lead">
        Заполните реквизиты организации. Менеджер проверит наличие товара
        и пришлёт счёт на указанный email.
    </p>

    <form method="post" action="{% url 'checkout:index' %}?confirmed=1"
          class="checkout-form" id="checkout-form" autocomplete="on">
        {% csrf_token %}
        {{ form.idempotency_key }}

        {% if form.non_field_errors %}
            <div class="notice notice-error" role="alert">
                {{ form.non_field_errors }}
            </div>
        {% endif %}

        <div class="checkout-layout">
            <div class="checkout-main">
                <fieldset class="form-section">
                    <legend>Организация</legend>
                    <div class="form-grid">
                        <div class="form-row">
                            {{ form.legal_form.label_tag }}
                            {{ form.legal_form }}
                            {{ form.legal_form.errors }}
                        </div>
                        <div class="form-row">
                            {{ form.short_name.label_tag }}
                            {{ form.short_name }}
                            {{ form.short_name.errors }}
                        </div>
                        <div class="form-row form-row-full">
                            {{ form.full_name.label_tag }}
                            {{ form.full_name }}
                            {{ form.full_name.errors }}
                        </div>
                        <div class="form-row">
                            {{ form.inn.label_tag }}
                            <div class="field-with-action">
                                {{ form.inn }}
                                <button type="button" class="btn btn-ghost btn-sm"
                                        hx-get="{% url 'checkout:suggest_by_inn' %}"
                                        hx-include="#id_inn"
                                        hx-target="#inn-suggest"
                                        hx-swap="innerHTML"
                                        hx-disabled-elt="this">Заполнить по ИНН</button>
                            </div>
                            <div id="inn-suggest" class="inn-suggest" aria-live="polite"></div>
                            {% if form.inn.help_text %}<p class="help">{{ form.inn.help_text }}</p>{% endif %}
                            {{ form.inn.errors }}
                        </div>
                        <div class="form-row">
                            {{ form.kpp.label_tag }}
                            {{ form.kpp }}
                            {% if form.kpp.help_text %}<p class="help">{{ form.kpp.help_text }}</p>{% endif %}
                            {{ form.kpp.errors }}
                        </div>
                    </div>
                </fieldset>

                <fieldset class="form-section">
                    <legend>Адреса</legend>
                    <div class="form-grid">
                        <div class="form-row form-row-full">
                            {{ form.legal_address.label_tag }}
                            {{ form.legal_address }}
                            {{ form.legal_address.errors }}
                        </div>
                        <div class="form-row form-row-full">
                            {{ form.delivery_address.label_tag }}
                            {% if form.delivery_address.help_text %}<p class="help">{{ form.delivery_address.help_text }}</p>{% endif %}
                            {{ form.delivery_address }}
                            {{ form.delivery_address.errors }}
                        </div>
                    </div>
                </fieldset>

                <fieldset class="form-section">
                    <legend>Банковские реквизиты <span class="optional">необязательно</span></legend>
                    <p class="help">Нужны, если счёт должен быть выставлен с банковскими реквизитами.</p>
                    <div class="form-grid">
                        <div class="form-row form-row-full">
                            {{ form.bank_name.label_tag }}
                            {{ form.bank_name }}
                            {{ form.bank_name.errors }}
                        </div>
                        <div class="form-row">
                            {{ form.bik.label_tag }}
                            {{ form.bik }}
                            {{ form.bik.errors }}
                        </div>
                        <div class="form-row">
                            {{ form.correspondent_account.label_tag }}
                            {{ form.correspondent_account }}
                            {{ form.correspondent_account.errors }}
                        </div>
                        <div class="form-row form-row-full">
                            {{ form.checking_account.label_tag }}
                            {{ form.checking_account }}
                            {{ form.checking_account.errors }}
                        </div>
                    </div>
                </fieldset>

                <fieldset class="form-section">
                    <legend>Контакты</legend>
                    <div class="form-grid">
                        <div class="form-row">
                            {{ form.contact_name.label_tag }}
                            {{ form.contact_name }}
                            {{ form.contact_name.errors }}
                        </div>
                        <div class="form-row">
                            {{ form.email.label_tag }}
                            {{ form.email }}
                            {% if form.email.help_text %}<p class="help">{{ form.email.help_text }}</p>{% endif %}
                            {{ form.email.errors }}
                        </div>
                        <div class="form-row">
                            {{ form.phone.label_tag }}
                            {{ form.phone }}
                            {{ form.phone.errors }}
                        </div>
                    </div>
                </fieldset>

                <fieldset class="form-section">
                    <legend>Комментарий</legend>
                    <div class="form-row">
                        {{ form.comment.label_tag }}
                        {{ form.comment }}
                        {{ form.comment.errors }}
                    </div>
                </fieldset>

                <div class="checkout-consent">
                    <label class="checkbox-row" for="{{ form.consent.id_for_label }}">
                        {{ form.consent }}
                        <span>{{ form.consent.label }}</span>
                    </label>
                    {{ form.consent.errors }}
                    <p class="help">
                        Данные используются для обработки заявки и выставления счёта.
                    </p>
                </div>

                <div class="hp-field" aria-hidden="true">
                    <label for="{{ form.honeypot.id_for_label }}">Не заполняйте это поле</label>
                    {{ form.honeypot }}
                </div>

                <div class="checkout-submit">
                    <button type="submit" class="btn btn-primary">Отправить заявку</button>
                    <span class="help">Поля, отмеченные звёздочкой, обязательны.</span>
                </div>
            </div>

            <aside class="checkout-aside">
                <div class="checkout-summary-card">
                    <div class="checkout-summary-head">
                        <h2>Ваш заказ</h2>
                        <a href="{% url 'cart:detail' %}" class="checkout-edit">Изменить</a>
                    </div>
                    {% include "checkout/partials/summary.html" %}
                    <p class="help checkout-note">
                        Цены и наличие проверяются на сервере при отправке заявки.
                        Менеджер подтвердит состав перед выставлением счёта.
                    </p>
                </div>

                <div class="checkout-contacts">
                    <h2>Нужна помощь?</h2>
                    <p class="help">
                        Напишите нам в чат на сайте или свяжитесь с менеджером —
                        поможем подобрать аналог и уточнить сроки поставки.
                    </p>
                </div>
            </aside>
        </div>
    </form>
{% endblock %}
````

## `tools_shop\checkout\templates\checkout\cart_changed.html`

``html
{% extends "shop/base.html" %}
{% load static %}
{% block title %}Корзина изменилась{% endblock %}
{% block head %}
    <link rel="stylesheet" href="{% static 'css/checkout.css' %}">
{% endblock %}
{% block content %}
    <nav class="breadcrumbs">
        <a href="{% url 'shop:index' %}">Главная</a>
        <span class="sep">/</span> <a href="{% url 'cart:detail' %}">Корзина</a>
        <span class="sep">/</span> <span>Оформление</span>
    </nav>

    <h1 class="page-title">Корзина изменилась</h1>
    <p class="lead">
        Пока вы оформляли заказ, состав или цены в корзине обновились.
        Проверьте заказ перед отправкой заявки.
    </p>

    {% if removed %}
        <div class="notice notice-warning" role="alert">
            <strong>Недоступные позиции удалены из корзины:</strong>
            <ul>
                {% for item in removed %}<li>{{ item.message }}</li>{% endfor %}
            </ul>
        </div>
    {% endif %}

    {% if price_changed %}
        <div class="notice notice-warning" role="status">
            Цены в корзине изменились с момента её просмотра.
            Ниже указаны актуальные цены — проверьте итоговую сумму.
        </div>
    {% endif %}

    {% if draft_saved %}
        <div class="notice" role="status">
            Введённые реквизиты сохранены. После проверки заказа вы вернётесь
            к заполненной форме.
        </div>
    {% endif %}

    <div class="checkout-changed-layout">
        <div class="checkout-summary-card">
            <div class="checkout-summary-head">
                <h2>Актуальный состав заказа</h2>
                <a href="{% url 'cart:detail' %}" class="checkout-edit">В корзину</a>
            </div>
            {% include "checkout/partials/summary.html" %}
        </div>

        <div class="checkout-changed-actions">
            <a class="btn btn-primary" href="{% url 'checkout:index' %}?confirmed=1">
                Продолжить оформление
            </a>
            <a class="btn btn-ghost" href="{% url 'cart:detail' %}">Вернуться в корзину</a>
        </div>
    </div>
{% endblock %}
````

## `tools_shop\checkout\templates\checkout\rate_limited.html`

``html
{% extends "shop/base.html" %}
{% load static %}
{% block title %}Слишком много попыток{% endblock %}
{% block head %}
    <link rel="stylesheet" href="{% static 'css/checkout.css' %}">
{% endblock %}
{% block content %}
    <div class="checkout-rate-limited">
        <h1 class="page-title">Слишком много попыток</h1>
        <p class="lead">
            Заявку нельзя отправить так часто. Подождите немного и попробуйте
            снова — или свяжитесь с менеджером.
        </p>
        <div class="checkout-changed-actions">
            <a class="btn btn-primary" href="{% url 'cart:detail' %}">Вернуться в корзину</a>
            <a class="btn btn-ghost" href="{% url 'shop:catalog' %}">В каталог</a>
        </div>
    </div>
{% endblock %}
````

## `tools_shop\checkout\templates\checkout\partials\summary.html`

``html
{% load shop_money %}
{# Краткий состав заявки для колонки оформления. #}
<div class="checkout-lines">
    {% for line in lines %}
        <div class="checkout-line">
            <div class="checkout-line-name">
                <a href="{{ line.product.get_absolute_url }}">{{ line.product.name }}</a>
                <span class="sku">Артикул: {{ line.product.sku }}</span>
            </div>
            <div class="checkout-line-qty">{{ line.qty }} × {{ line.price|money_rub }}</div>
            <div class="checkout-line-sum">{{ line.line_total|money_rub }}</div>
        </div>
    {% endfor %}
</div>
<div class="checkout-total">
    <span>Итого</span>
    <strong>{{ cart_total|money_rub }}</strong>
</div>
````

## `tools_shop\orders\views.py`

``python
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
````

## `tools_shop\orders\urls.py`

``python
"""URL-маршруты приложения orders."""
from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("order/<uuid:uuid>/", views.detail, name="detail"),
]
````

## `tools_shop\orders\tasks.py`

``python
"""
orders/tasks.py

Фоновые задачи по заявке.

Этап 4 ставит их из ``checkout.services.place_order`` через
``transaction.on_commit``. Этап 5 добавит PDF счёта, расширенные шаблоны
письем и настройки повторов; здесь — работающая отправка уведомлений, чтобы
заявка не оставалась без ответа.
"""
from __future__ import annotations

import logging
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

from .models import Order

logger = logging.getLogger(__name__)


def _site_url() -> str:
    return str(getattr(settings, "SITE_URL", "http://localhost:8002")).rstrip("/") + "/"


def _public_order_url(order: Order) -> str:
    path = reverse("orders:detail", args=[order.uuid])
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


def notify_managers(order_id: int) -> int:
    """Письмо менеджерам о новой заявке. Возвращает число писем."""
    order = _load_order(order_id)
    if order is None:
        logger.warning("notify_managers: заявка %s не найдена", order_id)
        return 0

    recipients = _recipients()
    if not recipients:
        logger.info("notify_managers: MANAGER_NOTIFY_EMAILS не задан, письмо пропущено")
        return 0

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
        f"Публичная страница заявки: {_public_order_url(order)}\n"
    )
    if order.comment:
        body += f"\nКомментарий покупателя:\n{order.comment}\n"

    send_mail(
        f"Новая заявка {order.number}",
        body,
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
````

## `tools_shop\orders\templates\orders\order_detail.html`

``html
{% extends "shop/base.html" %}
{% load static shop_money %}
{% block title %}Заявка № {{ order.number }}{% endblock %}
{% block head %}
    <link rel="stylesheet" href="{% static 'css/checkout.css' %}">
    <meta name="robots" content="noindex, nofollow">
{% endblock %}
{% block content %}
    <article class="order-page">
        <header class="order-head">
            <nav class="breadcrumbs">
                <a href="{% url 'shop:index' %}">Главная</a>
                <span class="sep">/</span> <a href="{% url 'shop:catalog' %}">Каталог</a>
                <span class="sep">/</span> <span>Заявка № {{ order.number }}</span>
            </nav>
            <div class="order-head-row">
                <div>
                    <p class="order-kicker">Заявка № {{ order.number }}</p>
                    <h1 class="page-title">{{ heading }}</h1>
                </div>
                <span class="status-badge status-{{ order.status }}">
                    {{ order.get_status_display }}
                </span>
            </div>
            <p class="lead">{{ status_hint }}</p>
            <p class="help">
                Оформлена {{ order.created_at|date:"d.m.Y H:i" }}.
                Сохраните ссылку на эту страницу — по ней можно проверить статус.
            </p>
        </header>

        <div class="order-layout">
            <div class="order-main">
                <section class="order-card">
                    <h2>Состав заявки</h2>
                    <div class="order-items">
                        {% for item in order.items.all %}
                            <div class="order-item">
                                <div class="order-item-name">
                                    <strong>{{ item.name }}</strong>
                                    <span class="sku">Артикул: {{ item.sku }}</span>
                                </div>
                                <div class="order-item-qty">{{ item.qty }} × {{ item.price|money_rub }}</div>
                                <div class="order-item-sum">{{ item.line_total|money_rub }}</div>
                            </div>
                        {% endfor %}
                    </div>
                    <div class="order-total">
                        <span>Итого</span>
                        <strong>{{ order.items_total|money_rub }}</strong>
                    </div>
                </section>

                <section class="order-card">
                    <h2>Реквизиты</h2>
                    <dl class="order-details">
                        <div>
                            <dt>Организация</dt>
                            <dd>{{ snapshot.short_name|default:"—" }}</dd>
                        </div>
                        {% if snapshot.full_name %}
                            <div>
                                <dt>Полное наименование</dt>
                                <dd>{{ snapshot.full_name }}</dd>
                            </div>
                        {% endif %}
                        {% if legal_form_label %}
                            <div>
                                <dt>ОПФ</dt>
                                <dd>{{ legal_form_label }}</dd>
                            </div>
                        {% endif %}
                        <div>
                            <dt>ИНН / КПП</dt>
                            <dd>{{ snapshot.inn|default:"—" }}{% if snapshot.kpp %} / {{ snapshot.kpp }}{% endif %}</dd>
                        </div>
                        {% if snapshot.legal_address %}
                            <div>
                                <dt>Юридический адрес</dt>
                                <dd>{{ snapshot.legal_address }}</dd>
                            </div>
                        {% endif %}
                        <div>
                            <dt>Адрес доставки</dt>
                            <dd>{{ order.delivery_address|default:"—" }}</dd>
                        </div>
                        {% if snapshot.bank_name or snapshot.checking_account %}
                            <div>
                                <dt>Банк</dt>
                                <dd>{{ snapshot.bank_name|default:"—" }}</dd>
                            </div>
                            <div>
                                <dt>БИК</dt>
                                <dd>{{ snapshot.bik|default:"—" }}</dd>
                            </div>
                            {% if snapshot.correspondent_account %}
                                <div>
                                    <dt>Корр. счёт</dt>
                                    <dd>{{ snapshot.correspondent_account }}</dd>
                                </div>
                            {% endif %}
                            <div>
                                <dt>Расчётный счёт</dt>
                                <dd>{{ snapshot.checking_account|default:"—" }}</dd>
                            </div>
                        {% endif %}
                    </dl>
                </section>

                <section class="order-card">
                    <h2>Контакты</h2>
                    <dl class="order-details">
                        <div>
                            <dt>Контактное лицо</dt>
                            <dd>{{ order.contact_name }}</dd>
                        </div>
                        <div>
                            <dt>Email</dt>
                            <dd>{{ order.contact_email }}</dd>
                        </div>
                        {% if order.contact_phone %}
                            <div>
                                <dt>Телефон</dt>
                                <dd>{{ order.contact_phone }}</dd>
                            </div>
                        {% endif %}
                        {% if order.comment %}
                            <div>
                                <dt>Комментарий</dt>
                                <dd>{{ order.comment|linebreaksbr }}</dd>
                            </div>
                        {% endif %}
                    </dl>
                </section>

                {% if current_invoice %}
                    <section class="order-card">
                        <h2>Счёт</h2>
                        <p>
                            Счёт № {{ current_invoice.number }}
                            от {{ current_invoice.issued_at|date:"d.m.Y" }}
                            {% if current_invoice.version > 1 %}(версия {{ current_invoice.version }}){% endif %}.
                        </p>
                        {% if current_invoice.pdf %}
                            <a class="btn btn-ghost" href="{{ current_invoice.pdf.url }}"
                               target="_blank" rel="noopener">Скачать PDF</a>
                        {% else %}
                            <p class="help">PDF счёта готовится. Мы отправим его на ваш email.</p>
                        {% endif %}
                        {% if current_invoice.sent_at %}
                            <p class="help">
                                Отправлен на email {{ current_invoice.sent_at|date:"d.m.Y H:i" }}.
                            </p>
                        {% endif %}
                    </section>
                {% endif %}
            </div>

            <aside class="order-aside">
                <section class="order-card">
                    <h2>История статусов</h2>
                    <ol class="order-timeline">
                        {% for log in order.status_log.all %}
                            <li>
                                <time datetime="{{ log.at|date:'c' }}">{{ log.at|date:"d.m.Y H:i" }}</time>
                                <span>
                                    {% if log.from_status %}
                                        {{ log.get_from_status_display }} → {{ log.get_to_status_display }}
                                    {% else %}
                                        Заявка создана — {{ log.get_to_status_display }}
                                    {% endif %}
                                </span>
                            </li>
                        {% endfor %}
                    </ol>
                </section>
                <a class="btn btn-ghost btn-block" href="{% url 'shop:catalog' %}">Вернуться в каталог</a>
            </aside>
        </div>
    </article>
{% endblock %}
````

## `tools_shop\static\css\checkout.css`

``css
/* --- checkout.css: оформление заявки и публичная страница заявки --- */

.checkout-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 360px;
    gap: 24px;
    align-items: start;
}
.checkout-main { min-width: 0; }
.checkout-aside {
    position: sticky;
    top: 18px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}

/* --- форма --- */
.form-section {
    margin: 0 0 18px;
    padding: 18px 20px 20px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
    box-shadow: var(--shadow-xs);
}
.form-section legend {
    padding: 0 8px;
    margin-left: -8px;
    font-size: 17px;
    font-weight: 700;
}
.form-section .optional {
    color: var(--muted);
    font-size: 13px;
    font-weight: 400;
}
.form-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}
.form-row { min-width: 0; }
.form-row-full { grid-column: 1 / -1; }
.form-row > label {
    display: block;
    margin-bottom: 6px;
    font-weight: 600;
    font-size: 14px;
}

.checkout-form :where(input[type="text"], input[type="email"], input[type="tel"],
    input[type="number"], input[type="url"], select, textarea) {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--panel);
    color: var(--text);
    font: inherit;
    line-height: 1.35;
    transition: border-color .15s var(--ease), box-shadow .15s var(--ease);
}
.checkout-form :where(input, select, textarea):hover { border-color: var(--border-strong); }
.checkout-form :where(input, select, textarea):focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 4px var(--accent-ring);
}
.checkout-form textarea { resize: vertical; min-height: 64px; }
.checkout-form select { cursor: pointer; }
.checkout-form .help { margin: 5px 0 0; font-size: 13px; }

.field-with-action { display: flex; align-items: stretch; gap: 8px; }
.field-with-action input { flex: 1 1 auto; min-width: 0; }
.field-with-action .btn { flex: none; white-space: nowrap; }
.inn-suggest:empty { display: none; }

.errorlist {
    margin: 6px 0 0;
    padding: 0;
    list-style: none;
    color: #b91c1c;
    font-size: 13px;
}
.errorlist li + li { margin-top: 4px; }
:root[data-theme="dark"] .errorlist { color: #fca5a5; }

.notice-error {
    border-color: #fecaca;
    background: #fef2f2;
    color: #991b1b;
    margin-bottom: 16px;
}
:root[data-theme="dark"] .notice-error {
    border-color: rgba(254, 202, 202, .35);
    background: rgba(153, 27, 27, .18);
    color: #fecaca;
}
.notice .errorlist { color: inherit; }

/* honeypot: невидим человеку, но доступен ботам */
.hp-field {
    position: absolute;
    left: -10000px;
    top: auto;
    width: 1px;
    height: 1px;
    overflow: hidden;
}

.checkout-consent { margin: 4px 0 18px; }
.checkbox-row {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    cursor: pointer;
    font-size: 14px;
}
.checkbox-row input[type="checkbox"] {
    width: 18px;
    height: 18px;
    margin: 1px 0 0;
    flex: none;
    accent-color: var(--accent);
    cursor: pointer;
}
.checkout-consent .help { margin: 6px 0 0 28px; font-size: 13px; }

.checkout-submit {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
    padding: 2px 0 24px;
}
.checkout-submit .help { font-size: 13px; }

/* --- сводка заказа --- */
.checkout-summary-card,
.checkout-contacts,
.order-card {
    padding: 18px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--panel);
    box-shadow: var(--shadow-xs);
}
.checkout-summary-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
}
.checkout-summary-head h2,
.checkout-contacts h2 {
    margin: 0;
    font-size: 18px;
}
.checkout-edit {
    color: var(--accent);
    font-size: 13px;
    white-space: nowrap;
}

.checkout-lines { display: flex; flex-direction: column; }
.checkout-line {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 4px 12px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
}
.checkout-line:last-child { border-bottom: 0; }
.checkout-line-name {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
    grid-column: 1;
}
.checkout-line-name a { color: var(--text); font-weight: 600; }
.checkout-line-name a:hover { color: var(--accent); }
.checkout-line-qty {
    grid-column: 1;
    color: var(--muted);
    font-size: 13px;
    font-variant-numeric: tabular-nums;
}
.checkout-line-sum {
    grid-column: 2;
    grid-row: 1 / span 2;
    align-self: center;
    font-weight: 700;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.checkout-total {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    padding-top: 14px;
    font-size: 16px;
}
.checkout-total strong { font-size: 22px; font-variant-numeric: tabular-nums; }
.checkout-note { margin: 12px 0 0; font-size: 13px; }
.checkout-contacts h2 { margin-bottom: 8px; }
.checkout-contacts .help { margin: 0; font-size: 13px; }

/* --- изменения корзины и лимит --- */
.checkout-changed-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 20px;
    align-items: start;
    max-width: 860px;
    margin-top: 18px;
}
.checkout-changed-actions {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-width: 220px;
}
.checkout-changed-layout .notice,
.checkout-rate-limited .notice { margin-top: 16px; }
.checkout-rate-limited { max-width: 640px; }

/* --- публичная страница заявки --- */
.order-head { margin-bottom: 22px; }
.order-head-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
}
.order-kicker {
    margin: 0 0 4px;
    color: var(--muted);
    font-size: 13px;
    letter-spacing: .03em;
    text-transform: uppercase;
}
.order-head .page-title { margin-bottom: 8px; }
.order-head .lead { margin-bottom: 6px; }

.status-badge {
    display: inline-flex;
    align-items: center;
    padding: 6px 12px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--panel-2);
    font-size: 13px;
    font-weight: 600;
    white-space: nowrap;
}
.status-new { border-color: #bfdbfe; background: #eff6ff; color: #1d4ed8; }
.status-review { border-color: #fde68a; background: #fffbeb; color: #92400e; }
.status-invoiced { border-color: #ddd6fe; background: #f5f3ff; color: #5b21b6; }
.status-paid { border-color: #bbf7d0; background: #f0fdf4; color: #15803d; }
.status-shipped { border-color: #99f6e4; background: #f0fdfa; color: #0f766e; }
.status-done { border-color: #bbf7d0; background: #f0fdf4; color: #166534; }
.status-cancelled,
.status-rejected { border-color: #fecaca; background: #fef2f2; color: #991b1b; }
:root[data-theme="dark"] .status-new,
:root[data-theme="dark"] .status-review,
:root[data-theme="dark"] .status-invoiced,
:root[data-theme="dark"] .status-paid,
:root[data-theme="dark"] .status-shipped,
:root[data-theme="dark"] .status-done,
:root[data-theme="dark"] .status-cancelled,
:root[data-theme="dark"] .status-rejected {
    background: var(--panel-2);
    color: var(--text);
    border-color: var(--border-strong);
}

.order-layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 340px;
    gap: 20px;
    align-items: start;
}
.order-main,
.order-aside { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
.order-aside { position: sticky; top: 18px; }
.order-card h2 { margin: 0 0 14px; font-size: 19px; }
.order-items { display: flex; flex-direction: column; }
.order-item {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto auto;
    gap: 12px;
    align-items: center;
    padding: 11px 0;
    border-bottom: 1px solid var(--border);
}
.order-item:last-child { border-bottom: 0; }
.order-item-name { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.order-item-qty {
    color: var(--muted);
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}
.order-item-sum { font-weight: 700; font-variant-numeric: tabular-nums; white-space: nowrap; }
.order-total {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    padding-top: 14px;
    font-size: 16px;
}
.order-total strong { font-size: 22px; font-variant-numeric: tabular-nums; }

.order-details {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px 20px;
    margin: 0;
}
.order-details > div { min-width: 0; }
.order-details dt { color: var(--muted); font-size: 12px; }
.order-details dd { margin: 3px 0 0; overflow-wrap: anywhere; }

.order-timeline {
    display: flex;
    flex-direction: column;
    gap: 12px;
    margin: 0;
    padding-left: 18px;
    font-size: 14px;
}
.order-timeline time {
    display: block;
    color: var(--muted);
    font-size: 12px;
    font-variant-numeric: tabular-nums;
}

@media (max-width: 980px) {
    .checkout-layout,
    .order-layout { grid-template-columns: minmax(0, 1fr); }
    .checkout-aside,
    .order-aside { position: static; }
    .checkout-changed-layout { grid-template-columns: minmax(0, 1fr); }
    .checkout-changed-actions { flex-direction: row; flex-wrap: wrap; }
}

@media (max-width: 640px) {
    .form-grid { grid-template-columns: minmax(0, 1fr); }
    .form-row-full { grid-column: auto; }
    .field-with-action { flex-direction: column; }
    .field-with-action .btn { width: 100%; }
    .order-details { grid-template-columns: minmax(0, 1fr); }
    .order-item { grid-template-columns: minmax(0, 1fr) auto; }
    .order-item-qty { grid-column: 1; }
    .order-item-sum { grid-column: 2; grid-row: 1 / span 2; }
}
````

## `tools_shop\checkout\tests.py`

``python
"""
checkout/tests.py

Тесты формы, сервиса создания заявки, ограничения частоты и вьюх оформления.

Запуск: python manage.py test checkout
"""
from __future__ import annotations

from decimal import Decimal
from unittest import mock
from uuid import uuid4

from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from cart.services import Cart
from companies.models import LegalEntity
from orders.models import Order, OrderItem
from orders.statuses import OrderStatus
from shop.models import Category, Product

from .forms import CheckoutForm
from .services import EmptyCart, place_order

FORM_URL = reverse("checkout:index")
POST_URL = f"{FORM_URL}?confirmed=1"


class CheckoutTestMixin:
    """Общие данные: категория, товар и валидные реквизиты."""

    @classmethod
    def setUpTestData(cls):
        root = Category.objects.add_root(create_kwargs={"name": "Инструмент"})
        cls.leaf = Category.objects.add_child(root, create_kwargs={"name": "Свёрла"})
        cls.product = cls._product("CHK-1", Decimal("100.00"))
        cls.product2 = cls._product("CHK-2", Decimal("250.50"))

    @classmethod
    def _product(cls, sku: str, price: Decimal | None) -> Product:
        return Product.objects.create(
            sku=sku,
            name=f"Товар {sku}",
            category=cls.leaf,
            price=price,
            is_active=True,
            attributes={},
        )

    def setUp(self):
        # Лимит оформления и сессии могут кэшироваться в Redis — чистим,
        # чтобы тесты не влияли друг на друга.
        cache.clear()

    def set_cart(self, mapping: dict | None = None, client=None) -> None:
        client = client or self.client
        session = client.session
        session["cart"] = {
            str(pk): qty
            for pk, qty in (
                mapping if mapping is not None else {self.product.pk: 2}
            ).items()
        }
        session.save()

    def payload(self, **overrides) -> dict:
        data = {
            "legal_form": LegalEntity.LegalForm.OOO,
            "short_name": 'ООО "Ромашка"',
            "full_name": 'Общество с ограниченной ответственностью "Ромашка"',
            "inn": "7707083893",
            "kpp": "773601001",
            "legal_address": "г. Москва, ул. Тверская, д. 1",
            "delivery_address": "г. Москва, ул. Тверская, д. 1, склад",
            "bank_name": "ПАО Сбербанк",
            "bik": "044525225",
            "correspondent_account": "30101810400000000225",
            "checking_account": "40702810400000000001",
            "contact_name": "Иван Петров",
            "email": "Buyer@Example.RU",
            "phone": "+7 900 000-00-00",
            "comment": "Доставка после 10:00",
            "consent": "on",
            "honeypot": "",
        }
        data.update(overrides)
        return data

    def form_with_key(self) -> dict:
        """Открывает форму и возвращает данные с актуальным ключом."""
        response = self.client.get(FORM_URL)
        self.assertEqual(response.status_code, 200)
        key = str(response.context["form"]["idempotency_key"].value())
        return self.payload(idempotency_key=key)


class CheckoutFormTests(CheckoutTestMixin, TestCase):
    def test_valid_form(self):
        form = CheckoutForm(data=self.payload(idempotency_key=str(uuid4())))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["email"], "buyer@example.ru")
        self.assertEqual(form.cleaned_data["inn"], "7707083893")

    def test_digits_field_strips_spaces(self):
        form = CheckoutForm(
            data=self.payload(inn="7707 083 893", idempotency_key=str(uuid4()))
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["inn"], "7707083893")

    def test_bad_inn_is_rejected(self):
        form = CheckoutForm(
            data=self.payload(inn="7707083894", idempotency_key=str(uuid4()))
        )
        self.assertFalse(form.is_valid())
        self.assertIn("inn", form.errors)

    def test_kpp_required_for_10_digit_inn(self):
        form = CheckoutForm(
            data=self.payload(kpp="", idempotency_key=str(uuid4()))
        )
        self.assertFalse(form.is_valid())
        self.assertIn("kpp", form.errors)

    def test_ip_without_kpp_is_valid(self):
        form = CheckoutForm(
            data=self.payload(
                legal_form=LegalEntity.LegalForm.IP,
                inn="500100732259",
                kpp="",
                idempotency_key=str(uuid4()),
            )
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_ip_with_kpp_is_rejected(self):
        form = CheckoutForm(
            data=self.payload(
                legal_form=LegalEntity.LegalForm.IP,
                inn="500100732259",
                kpp="773601001",
                idempotency_key=str(uuid4()),
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn("kpp", form.errors)

    def test_invalid_bank_details_are_rejected(self):
        form = CheckoutForm(
            data=self.payload(
                bik="123",
                checking_account="123",
                idempotency_key=str(uuid4()),
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn("bik", form.errors)
        self.assertIn("checking_account", form.errors)

    def test_bank_details_are_optional(self):
        form = CheckoutForm(
            data=self.payload(
                bank_name="",
                bik="",
                correspondent_account="",
                checking_account="",
                idempotency_key=str(uuid4()),
            )
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_honeypot_blocks_submission(self):
        form = CheckoutForm(
            data=self.payload(
                honeypot="https://spam.example", idempotency_key=str(uuid4())
            )
        )
        self.assertFalse(form.is_valid())
        self.assertTrue(form.non_field_errors())

    def test_consent_is_required(self):
        data = self.payload(idempotency_key=str(uuid4()))
        data.pop("consent")
        form = CheckoutForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("consent", form.errors)


class PlaceOrderTests(CheckoutTestMixin, TestCase):
    def make_cart(self, mapping: dict | None = None) -> Cart:
        request = RequestFactory().get("/")
        request.session = SessionStore()
        cart = Cart(request)
        for pk, qty in (
            mapping if mapping is not None else {self.product.pk: 2}
        ).items():
            cart.add(pk, qty)
        return cart

    def cleaned(self, **overrides) -> dict:
        form = CheckoutForm(
            data=self.payload(
                idempotency_key=str(uuid4()),
                **overrides,
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        return form.cleaned_data

    def test_creates_order_items_and_log(self):
        cart = self.make_cart({self.product.pk: 3})
        key = uuid4()
        with mock.patch("checkout.services.async_task") as async_task, \
                self.captureOnCommitCallbacks(execute=True):
            order = place_order(cart, self.cleaned(), key)

        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertEqual(order.contact_email, "buyer@example.ru")
        self.assertIsNotNone(order.consent_at)
        self.assertEqual(order.items.count(), 1)
        item = order.items.get()
        self.assertEqual(item.price, Decimal("100.00"))
        self.assertEqual(item.qty, 3)
        self.assertEqual(order.status_log.count(), 1)
        self.assertEqual(order.requisites_snapshot["short_name"], 'ООО "Ромашка"')
        self.assertEqual(
            [call.args[0] for call in async_task.call_args_list],
            [
                "orders.tasks.notify_managers",
                "orders.tasks.send_order_accepted_email",
            ],
        )

    def test_idempotent_repeat_returns_same_order(self):
        cart = self.make_cart()
        key = uuid4()
        data = self.cleaned()
        with mock.patch("checkout.services.async_task"), \
                self.captureOnCommitCallbacks(execute=True):
            first = place_order(cart, data, key)
            second = place_order(cart, data, key)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_existing_company_is_not_overwritten(self):
        company = LegalEntity.objects.create(
            full_name='ООО "Старое имя"',
            short_name='ООО "Старое имя"',
            legal_form=LegalEntity.LegalForm.OOO,
            inn="7707083893",
            kpp="773601001",
            legal_address="Старый адрес",
        )
        cart = self.make_cart()
        order = place_order(cart, self.cleaned(short_name='ООО "Новое имя"'), uuid4())

        company.refresh_from_db()
        self.assertEqual(company.pk, order.company_id)
        self.assertEqual(company.short_name, 'ООО "Старое имя"')
        self.assertEqual(order.requisites_snapshot["short_name"], 'ООО "Новое имя"')

    def test_price_snapshot_does_not_change_after_product_update(self):
        cart = self.make_cart()
        order = place_order(cart, self.cleaned(), uuid4())
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("999.00"))

        item = order.items.get()
        self.assertEqual(item.price, Decimal("100.00"))
        self.assertEqual(order.items_total, Decimal("200.00"))

    def test_empty_cart_raises(self):
        cart = self.make_cart({})
        with self.assertRaises(EmptyCart):
            place_order(cart, self.cleaned(), uuid4())

    def test_order_number_and_public_uuid_are_set(self):
        cart = self.make_cart()
        order = place_order(cart, self.cleaned(), uuid4())
        self.assertTrue(order.number.startswith("З-"))
        self.assertIsNotNone(order.uuid)


class CheckoutViewTests(CheckoutTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        # Вьюха ставит задачи django-q2; в тестах не трогаем очередь.
        patcher = mock.patch("checkout.services.async_task")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_empty_cart_redirects_to_catalog(self):
        response = self.client.get(FORM_URL)
        self.assertRedirects(response, reverse("shop:catalog"))

    def test_get_shows_form_and_idempotency_key(self):
        self.set_cart()
        response = self.client.get(FORM_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Оформление заказа")
        key = str(response.context["form"]["idempotency_key"].value())
        self.assertEqual(key, self.client.session["checkout_idempotency_key"])

    def test_post_creates_order_clears_cart_and_redirects(self):
        self.set_cart({self.product.pk: 2})
        data = self.form_with_key()
        response = self.client.post(POST_URL, data)

        order = Order.objects.get()
        self.assertRedirects(response, reverse("orders:detail", args=[order.uuid]))
        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertFalse(self.client.session.get("cart"))
        self.assertNotIn("checkout_idempotency_key", self.client.session)

        page = self.client.get(response.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, order.number)
        self.assertContains(page, "Заявка принята")

    def test_repeat_post_does_not_create_duplicate(self):
        self.set_cart({self.product.pk: 2})
        data = self.form_with_key()
        self.client.post(POST_URL, data)
        self.client.post(POST_URL, data)
        self.assertEqual(Order.objects.count(), 1)

    def test_invalid_post_saves_draft(self):
        self.set_cart()
        data = self.form_with_key()
        data["contact_name"] = ""
        response = self.client.post(POST_URL, data)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Обязательное поле")
        draft = self.client.session["checkout_draft"]["data"]
        self.assertEqual(draft["contact_name"], "")
        self.assertEqual(draft["email"], "Buyer@Example.RU")
        self.assertNotIn("honeypot", draft)
        self.assertNotIn("consent", draft)

        page = self.client.get(FORM_URL)
        self.assertEqual(page.context["form"]["contact_name"].value(), "")

    def test_price_change_is_shown_before_form(self):
        self.set_cart()
        self.client.get(reverse("cart:detail"))  # запоминаем отпечаток
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("120.00"))

        response = self.client.get(FORM_URL)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Цены в корзине изменились")
        self.assertContains(response, "Продолжить оформление")
        self.assertNotContains(response, 'id="checkout-form"')

        form_page = self.client.get(f"{FORM_URL}?confirmed=1")
        self.assertContains(form_page, 'id="checkout-form"')
        self.assertContains(form_page, "120")

    def test_removed_product_is_reported_and_pruned(self):
        self.set_cart({self.product.pk: 1, self.product2.pk: 1})
        self.client.get(reverse("cart:detail"))
        Product.objects.filter(pk=self.product2.pk).update(is_active=False)

        response = self.client.get(FORM_URL)
        self.assertContains(response, "снят с продажи")
        self.assertEqual(self.client.session["cart"], {str(self.product.pk): 1})

    def test_rate_limit_blocks_sixth_post(self):
        self.set_cart()
        statuses = [self.client.post(POST_URL, {}).status_code for _ in range(6)]
        self.assertEqual(statuses[:5], [200] * 5)
        self.assertEqual(statuses[5], 429)

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        self.set_cart(client=client)
        response = client.post(POST_URL, self.payload(idempotency_key=str(uuid4())))
        self.assertEqual(response.status_code, 403)

    def test_suggest_by_inn_stub_returns_empty_fragment(self):
        response = self.client.get(reverse("checkout:suggest_by_inn"), {"inn": "7707083893"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"")
````

## `tools_shop\orders\test_public.py`

``python
"""
orders/test_public.py

Публичная страница заявки: доступ по UUID, без авторизации, без внутренних
комментариев и служебных данных.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from django.test import TestCase
from django.urls import reverse

from companies.models import LegalEntity
from shop.models import Category, Product

from .models import Invoice, Order, OrderItem
from .statuses import OrderStatus


class PublicOrderPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Category.objects.add_root(create_kwargs={"name": "Инструмент"})
        cls.leaf = Category.objects.add_child(root, create_kwargs={"name": "Свёрла"})
        cls.product = Product.objects.create(
            sku="PUB-1",
            name="Сверло 6 мм",
            category=cls.leaf,
            price=Decimal("150.00"),
            is_active=True,
            attributes={},
        )

    def make_order(self, *, comment: str = "") -> Order:
        company, _ = LegalEntity.objects.get_or_create(
            inn="7707083893",
            kpp="773601001",
            defaults={
                "full_name": 'ООО "Публичный клиент"',
                "short_name": 'ООО "Публичный клиент"',
                "legal_form": LegalEntity.LegalForm.OOO,
                "legal_address": "г. Москва, ул. Тверская, д. 1",
            },
        )
        order = Order.objects.create(
            company=company,
            contact_name="Иван Петров",
            contact_email="buyer@example.ru",
            contact_phone="+7 900 000-00-00",
            delivery_address="г. Москва, ул. Тверская, д. 1",
            comment="Комментарий покупателя",
            requisites_snapshot={
                "legal_form": "ooo",
                "short_name": 'ООО "Публичный клиент"',
                "full_name": 'ООО "Публичный клиент"',
                "inn": "7707083893",
                "kpp": "773601001",
                "legal_address": "г. Москва, ул. Тверская, д. 1",
                "delivery_address": "г. Москва, ул. Тверская, д. 1",
                "bank_name": "",
                "bik": "",
                "correspondent_account": "",
                "checking_account": "",
                "contact_name": "Иван Петров",
                "email": "buyer@example.ru",
                "phone": "+7 900 000-00-00",
                "comment": "Комментарий покупателя",
            },
            status=OrderStatus.NEW,
            idempotency_key=uuid4(),
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            name=self.product.name,
            sku=self.product.sku,
            price=self.product.price,
            qty=2,
        )
        order.log_created(comment=comment or "Внутренний комментарий менеджера")
        return order

    def test_page_is_available_by_uuid_without_login(self):
        order = self.make_order()
        response = self.client.get(reverse("orders:detail", args=[order.uuid]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.number)
        self.assertContains(response, "Заявка принята")
        self.assertContains(response, "Публичный клиент")
        self.assertContains(response, "Сверло 6 мм")
        self.assertContains(response, "300")

    def test_internal_comment_is_not_exposed(self):
        order = self.make_order(comment="Секретный комментарий менеджера")
        response = self.client.get(reverse("orders:detail", args=[order.uuid]))
        self.assertNotContains(response, "Секретный комментарий менеджера")

    def test_page_is_not_cacheable_and_not_indexed(self):
        order = self.make_order()
        response = self.client.get(reverse("orders:detail", args=[order.uuid]))
        self.assertIn("no-cache", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_unknown_uuid_returns_404(self):
        response = self.client.get(reverse("orders:detail", args=[uuid4()]))
        self.assertEqual(response.status_code, 404)

    def test_one_order_is_not_visible_through_another_uuid(self):
        first = self.make_order()
        second = self.make_order()
        response = self.client.get(reverse("orders:detail", args=[first.uuid]))
        self.assertNotContains(response, second.number)

    def test_invoice_without_pdf_shows_preparing_message(self):
        order = self.make_order()
        Invoice.objects.create(
            order=order,
            number="С-000001",
            version=1,
            is_current=True,
        )
        response = self.client.get(reverse("orders:detail", args=[order.uuid]))
        self.assertContains(response, "С-000001")
        self.assertContains(response, "PDF счёта готовится")
````

## `tools_shop\orders\test_tasks.py`

``python
"""
orders/test_tasks.py

Проверка писем этапа 4: уведомление менеджеров и подтверждение покупателю.
"""
from __future__ import annotations

from decimal import Decimal
from unittest import mock
from uuid import uuid4

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from companies.models import LegalEntity
from shop.models import Category, Product

from .models import Order, OrderItem
from .statuses import OrderStatus
from .tasks import notify_managers, send_order_accepted_email


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEFAULT_FROM_EMAIL="shop@example.ru",
    MANAGER_NOTIFY_EMAILS=["manager@example.ru", "sales@example.ru"],
    SITE_URL="https://shop.example.ru",
)
class OrderTaskTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Category.objects.add_root(create_kwargs={"name": "Инструмент"})
        leaf = Category.objects.add_child(root, create_kwargs={"name": "Свёрла"})
        cls.product = Product.objects.create(
            sku="TASK-1",
            name="Сверло 8 мм",
            category=leaf,
            price=Decimal("200.00"),
            is_active=True,
            attributes={},
        )

    def make_order(self) -> Order:
        company = LegalEntity.objects.create(
            full_name='ООО "Почтовый клиент"',
            short_name='ООО "Почтовый клиент"',
            legal_form=LegalEntity.LegalForm.OOO,
            inn="7707083893",
            kpp="773601001",
            legal_address="г. Москва",
        )
        order = Order.objects.create(
            company=company,
            contact_name="Иван Петров",
            contact_email="buyer@example.ru",
            delivery_address="г. Москва",
            requisites_snapshot={"short_name": 'ООО "Почтовый клиент"', "inn": "7707083893"},
            status=OrderStatus.NEW,
            idempotency_key=uuid4(),
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            name=self.product.name,
            sku=self.product.sku,
            price=self.product.price,
            qty=2,
        )
        order.log_created()
        return order

    def test_notify_managers_sends_email(self):
        order = self.make_order()
        sent = notify_managers(order.pk)
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["manager@example.ru", "sales@example.ru"])
        self.assertIn(order.number, message.subject)
        self.assertIn(reverse("orders:detail", args=[order.uuid]), message.body)

    def test_accepted_email_goes_to_customer(self):
        order = self.make_order()
        sent = send_order_accepted_email(order.pk)
        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[0].to, ["buyer@example.ru"])
        self.assertIn("принята", mail.outbox[0].subject.lower())

    @override_settings(MANAGER_NOTIFY_EMAILS=[])
    def test_notify_managers_without_recipients_is_noop(self):
        order = self.make_order()
        self.assertEqual(notify_managers(order.pk), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_order_is_ignored(self):
        with mock.patch("orders.tasks.logger.warning") as warning:
            self.assertEqual(notify_managers(999_999), 0)
            warning.assert_called_once()
````

## `tools_shop\tools_shop\settings.py`

``python


import os
from pathlib import Path

from decouple import Csv, config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!

SECRET_KEY = config("SECRET_KEY")
# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=False, cast=bool)


ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# за nginx: доверяем его заголовкам о схеме/хосте
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = True

INTERNAL_IPS = [
    # ...
    "127.0.0.1",
    # ...
]

# Application definition

INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    "django_q",
    "chat.apps.ChatConfig",
    "users.apps.UsersConfig",
    "shop.apps.ShopConfig",
    "companies.apps.CompaniesConfig",
    "cart.apps.CartConfig",
    "orders.apps.OrdersConfig",
    "checkout.apps.CheckoutConfig",
    "adminsortable2",
    "django_browser_reload",    
    "django.contrib.postgres",
    "treebeard",
    "django_extensions",
    "debug_toolbar",
    "django_cleanup.apps.CleanupConfig",
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    "django_browser_reload.middleware.BrowserReloadMiddleware",
    "debug_toolbar.middleware.DebugToolbarMiddleware",
]

ROOT_URLCONF = 'tools_shop.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, "templates")],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'shop.context_processors.popup_notice',
                'cart.context_processors.cart_counters',
            ],
        },
    },
]

WSGI_APPLICATION = 'tools_shop.wsgi.application'
ASGI_APPLICATION = 'tools_shop.asgi.application'


# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases

# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST"),
        "PORT": config("DB_PORT"),
    }
}

# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "users.validators.RuMinimumLengthValidator", "OPTIONS": {"min_length": 6}},
    {
        "NAME": "users.validators.RuCommonPasswordValidator",
    },
    {
        "NAME": "users.validators.RuNumericPasswordValidator",
    },
    {
        "NAME": "users.validators.RuUserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("username", "email"), "max_similarity": 0.6},
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = "ru"

TIME_ZONE = "Asia/Novosibirsk"

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = "/static/"
# Папка, где лежат ваши исходные файлы (JS, CSS, картинки)
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, "static"),
]


# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")


MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"


AUTH_USER_MODEL = "users.User"

LOGOUT_REDIRECT_URL = "shop:index"





# Читаем строку и сразу бьем её по запятым
CSRF_TRUSTED_ORIGINS = config(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:8002,http://127.0.0.1:8002",
    cast=Csv(),
)


REDIS_HOST = config("REDIS_HOST", default="127.0.0.1")
REDIS_PORT = config("REDIS_PORT", default=6379, cast=int)

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [(REDIS_HOST, REDIS_PORT)]},
    }
}


CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
    }
}


Q_CLUSTER = {
    "name": "myshop",
    "workers": 2,
    "recycle": 500,
    "timeout": 60,
    "retry": 120,
    "queue_limit": 50,
    "bulk": 10,
    "redis": {
        "host": REDIS_HOST,
        "port": REDIS_PORT,
        "db": 0,
    },
    "save_limit": 10000,
}


RU_EMAIL_PATTERN = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.ru$"

# ---- почта и заявки -------------------------------------------------------
DEFAULT_FROM_EMAIL = config(
    "DEFAULT_FROM_EMAIL", default="noreply@tools-service.ru"
)
# Адреса менеджеров, которым уходят уведомления о новых заявках.
MANAGER_NOTIFY_EMAILS = config("MANAGER_NOTIFY_EMAILS", default="", cast=Csv())

# Базовый адрес сайта для ссылок в письмах (без завершающего слэша).
SITE_URL = config("SITE_URL", default="http://localhost:8002").rstrip("/")

# Ограничение POST на оформление заявки: 5 попыток в час с одного IP.
CHECKOUT_RATE_LIMIT = config("CHECKOUT_RATE_LIMIT", default=5, cast=int)
CHECKOUT_RATE_WINDOW = config("CHECKOUT_RATE_WINDOW", default=3600, cast=int)
# Включать только если перед Django стоит доверенный прокси, который
# перезаписывает X-Forwarded-For. Иначе клиент подделает IP и обойдёт лимит.
USE_X_FORWARDED_FOR = config("USE_X_FORWARDED_FOR", default=False, cast=bool)

# Дополнительные разрешенные домены, которые не заканчиваются на .ru
EXTRA_ALLOWED_DOMAINS = ["yandex.by", "yandex.kz", "yandex.com"]

SESSION_COOKIE_NAME = "sessionid_hairshop"

# Корзина и избранное живут в сессии. cached_db: чтение из Redis, запись
# и в кэш, и в БД — сессии не теряются при перезапуске Redis.
SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90  # 90 дней

# CSRF_COOKIE_NAME = "csrftoken_hairshop"

# SESSION_COOKIE_SECURE = True  # Включить на деплое, чтобы куки передавались только по HTTPS
# CSRF_COOKIE_SECURE = True  # Включить на деплое, чтобы куки передавались только по HTTPS
# Web Push: use one persistent VAPID key pair for all deployments.
VAPID_PUBLIC_KEY = config("VAPID_PUBLIC_KEY", default="")
VAPID_PRIVATE_KEY = config("VAPID_PRIVATE_KEY", default="")
VAPID_SUBJECT = config("VAPID_SUBJECT", default="")

SESSION_COOKIE_HTTPONLY = True  # Куки сессии недоступны через JavaScript

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
````

## `tools_shop\tools_shop\urls.py`

``python

from debug_toolbar.toolbar import debug_toolbar_urls
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from chat.push_views import service_worker




urlpatterns = [
    path('sw.js', service_worker, name='service-worker'),
    path('chat/', include('chat.urls')),
    path('admin/', admin.site.urls),
    path("cart/", include("cart.urls")),
    path("checkout/", include("checkout.urls")),
    path("", include("orders.urls")),
    path("", include("shop.urls")),
    # path("users/", include("users.urls")),
    path("__reload__/", include("django_browser_reload.urls"))
] + debug_toolbar_urls()

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
````

## `tools_shop\cart\templates\cart\partials\cart_lines.html`

``html
{% load shop_money %}
{# Содержимое корзины: таблица позиций, итог, кнопки. Перерисовывается целиком. #}
<div id="cart-lines" class="cart-lines">
    {% if cart_error %}
        <div class="notice notice-warning" role="alert">{{ cart_error }}</div>
    {% endif %}
    {% if removed %}
        <div class="notice notice-warning" role="status">
            <strong>Корзина изменилась:</strong>
            <ul>
                {% for item in removed %}<li>{{ item.message }}</li>{% endfor %}
            </ul>
        </div>
    {% endif %}

    {% if lines %}
        <div class="cart-table" role="table" aria-label="Товары в корзине">
            {% for line in lines %}
                <div class="cart-row" role="row" id="cart-row-{{ line.product.pk }}">
                    <div class="cart-cell cart-name" role="cell">
                        <a href="{{ line.product.get_absolute_url }}">{{ line.product.name }}</a>
                        <span class="sku">Артикул: {{ line.product.sku }}</span>
                    </div>
                    <div class="cart-cell cart-price" role="cell">
                        {{ line.price|money_rub }}
                    </div>
                    <div class="cart-cell" role="cell">
                        <div class="qty-stepper" x-data="{ qty: {{ line.qty }} }">
                            <button type="button" aria-label="Уменьшить количество"
                                    @click="qty = Math.max(1, qty - 1); $refs.input.dispatchEvent(new Event('change'))">−</button>
                            <input x-ref="input" type="number" inputmode="numeric" name="qty"
                                   min="1" max="9999" step="1" x-model.number="qty"
                                   aria-label="Количество"
                                   hx-post="{% url 'cart:update' line.product.pk %}"
                                   hx-trigger="change delay:400ms"
                                   hx-target="#cart-lines"
                                   hx-swap="outerHTML"
                                   hx-disabled-elt="this">
                            <button type="button" aria-label="Увеличить количество"
                                    @click="qty = Math.min(9999, qty + 1); $refs.input.dispatchEvent(new Event('change'))">+</button>
                        </div>
                    </div>
                    <div class="cart-cell cart-sum" role="cell">
                        {{ line.line_total|money_rub }}
                    </div>
                    <div class="cart-cell cart-actions" role="cell">
                        <button type="button" class="link-danger"
                                hx-post="{% url 'cart:remove' line.product.pk %}"
                                hx-target="#cart-lines"
                                hx-swap="outerHTML"
                                hx-confirm="Удалить товар из корзины?"
                                aria-label="Удалить «{{ line.product.name }}» из корзины">Удалить</button>
                    </div>
                </div>
            {% endfor %}
        </div>

        <div class="cart-summary">
            <div class="cart-total">
                <span>Итого</span>
                <strong>{{ cart_total|money_rub }}</strong>
            </div>
            <div class="cart-actions-row">
                <button type="button" class="btn btn-ghost"
                        hx-post="{% url 'cart:clear' %}"
                        hx-target="#cart-lines"
                        hx-swap="outerHTML"
                        hx-confirm="Очистить корзину полностью?">Очистить корзину</button>
                <a class="btn btn-primary" href="{% url 'checkout:index' %}">Оформить заказ</a>
            </div>
        </div>
    {% else %}
        <div class="empty-state">
            <p>Корзина пуста.</p>
            <a class="btn btn-primary" href="{% url 'shop:catalog' %}">Перейти в каталог</a>
        </div>
    {% endif %}
</div>
````

