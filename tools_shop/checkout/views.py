"""
checkout/views.py

Страница оформления заявки и htmx-автозаполнение реквизитов по ИНН.

Порядок проверок на POST:
1. повторная отправка уже созданной заявки (по ключу из сессии) — редирект;
2. пустая корзина — редирект в каталог;
3. изменения состава/цен — показать их до формы;
4. лимит попыток с IP;
5. валидация формы и создание заявки.

Автозаполнение по ИНН сначала ищет организацию в базе (повторный клиент),
и только потом обращается к DaData. Сервис подсказок не должен ломать
оформление: при любой его ошибке форма остаётся доступной для ручного ввода.

Корзина всегда перепроверяется на сервере: цены и доступность товаров в
сессии не хранятся, поэтому доверять данным из браузера нельзя.
"""
from __future__ import annotations

import logging
import re

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from cart.fingerprint import COOKIE_NAME, fingerprint_changed, remember_fingerprint
from cart.services import get_cart
from companies.dadata import (
    DadataError,
    DadataNotConfigured,
    DadataNotFound,
    DadataUnavailable,
)
from companies.validators import is_valid_inn

from .draft import (
    IDEMPOTENCY_SESSION_KEY,
    clear_checkout_state,
    ensure_idempotency_key,
    load_draft,
    save_draft,
)
from .forms import CheckoutForm
from .lookup import lookup_requisites
from .ratelimit import is_rate_limited, retry_after
from .services import EmptyCart, find_order_by_key, place_order

logger = logging.getLogger(__name__)


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


def _lookup_notice(
    request: HttpRequest,
    message: str,
    *,
    level: str = "warning",
    retry_after_seconds: int | None = None,
) -> HttpResponse:
    """
    Небольшой ответ для ``#inn-suggest``.

    htmx-заголовки перенаправляют ответ с общего блока организации на блок
    сообщения: при ошибке уже введённые поля не перерисовываются.
    """
    response = render(
        request,
        "checkout/partials/inn_suggest.html",
        {"message": message, "level": level},
    )
    response["HX-Retarget"] = "#inn-suggest"
    response["HX-Reswap"] = "innerHTML"
    response["Cache-Control"] = "no-store"
    if retry_after_seconds is not None:
        response["Retry-After"] = str(int(retry_after_seconds))
    return response


@never_cache
@require_POST
def suggest_by_inn(request: HttpRequest) -> HttpResponse:
    """
    htmx-подсказка реквизитов по ИНН.

    Сначала ищем повторного клиента в базе. Если карточки нет — запрашиваем
    DaData. Успешный ответ заменяет блок ``#organization-fields`` целиком,
    ошибка показывается рядом с полем ИНН.
    """
    inn = re.sub(r"\s+", "", request.POST.get("inn", "") or "")
    kpp = re.sub(r"\s+", "", request.POST.get("kpp", "") or "")

    if not is_valid_inn(inn):
        return _lookup_notice(
            request,
            "Проверьте ИНН: нужно 10 цифр для юрлица или 12 для ИП, "
            "контрольная сумма должна совпадать.",
            level="error",
        )
    if kpp and not re.fullmatch(r"\d{9}", kpp):
        return _lookup_notice(
            request,
            "Проверьте КПП: он должен содержать 9 цифр.",
            level="error",
        )
    if len(inn) == 12 and kpp:
        return _lookup_notice(
            request,
            "Для ИНН из 12 цифр (ИП) КПП не заполняется.",
            level="error",
        )

    limit = int(getattr(settings, "DADATA_RATE_LIMIT", 10))
    window = int(getattr(settings, "DADATA_RATE_WINDOW", 60))
    try:
        limited = is_rate_limited(
            request,
            scope="dadata",
            limit=limit,
            window=window,
        )
    except Exception:
        # Кэш/Redis недоступен: лучше показать подсказку, чем уронить форму.
        logger.warning("Не удалось проверить лимит подсказок DaData", exc_info=True)
        limited = False

    if limited:
        return _lookup_notice(
            request,
            "Слишком много запросов на проверку ИНН. Попробуйте немного позже.",
            level="warning",
            retry_after_seconds=retry_after(window=window),
        )

    try:
        result = lookup_requisites(inn, kpp)
    except DadataNotFound:
        return _lookup_notice(
            request,
            "Организация по указанному ИНН/КПП не найдена. "
            "Проверьте номер и заполните реквизиты вручную.",
        )
    except DadataNotConfigured:
        return _lookup_notice(
            request,
            "Автозаполнение по ИНН пока не настроено. "
            "Заполните реквизиты вручную или обратитесь к менеджеру.",
        )
    except DadataUnavailable as exc:
        logger.warning("DaData временно недоступен: %s", exc)
        return _lookup_notice(
            request,
            "Сервис проверки временно недоступен. "
            "Заполните реквизиты вручную и отправьте заявку.",
        )
    except DadataError as exc:
        logger.warning("Ошибка интеграции с DaData: %s", exc)
        return _lookup_notice(
            request,
            "Не удалось получить реквизиты. Заполните их вручную.",
        )

    if result.multiple_kpp:
        return _lookup_notice(
            request,
            result.notice,
            level=result.notice_level,
        )

    form = CheckoutForm(initial=result.initial)
    response = render(
        request,
        "checkout/partials/organization_fields.html",
        {
            "form": form,
            "lookup_notice": result.notice,
            "lookup_level": result.notice_level,
        },
    )
    response["Cache-Control"] = "no-store"
    return response
