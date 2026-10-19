"""
cart/views.py

htmx-эндпоинты корзины и избранного. Все изменения — только POST + CSRF.
Ответ — HTML-фрагмент, обновляющий конкретный блок страницы; счётчики в
шапке обновляются по событию ``cart-updated`` (см. base.html).
"""
from __future__ import annotations

from functools import wraps
from typing import Any, Callable

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from shop.models import Product

from .fingerprint import remember_fingerprint
from .services import (
    MAX_QTY,
    MIN_QTY,
    InvalidQuantity,
    ProductUnavailable,
    get_cart,
    get_favorites,
)

CART_UPDATED = "cart-updated"


def htmx_required(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """
    Мутирующие эндпоинты доступны только htmx-запросам.

    Без ``HX-Request`` отвечаем 400: у операций нет no-JS fallback, а
    случайный переход по URL не должен менять корзину.
    """

    @wraps(view)
    def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if not request.headers.get("HX-Request"):
            return HttpResponseBadRequest("Эндпоинт доступен только через htmx.")
        return view(request, *args, **kwargs)

    return wrapper


def _fragment(
    request: HttpRequest,
    template: str,
    context: dict,
    *,
    trigger: str = CART_UPDATED,
) -> HttpResponse:
    response = render(request, template, context)
    response["HX-Trigger"] = trigger
    return response


def _cart_fragment(request: HttpRequest, error: str = "") -> HttpResponse:
    """Фрагмент корзины + отпечаток «что покупатель видит сейчас»."""
    response = _fragment(
        request,
        "cart/partials/cart_lines.html",
        _cart_context(request, error=error),
    )
    return remember_fingerprint(response, get_cart(request))


def _cart_context(request: HttpRequest, error: str = "") -> dict:
    cart = get_cart(request)
    return {
        "cart": cart,
        "lines": cart.items(),
        "removed": cart.removed,
        "cart_total": cart.total(),
        "cart_count": cart.count(),
        "cart_error": error,
    }


# ---------------------------------------------------------------------------
# Корзина
# ---------------------------------------------------------------------------
@require_POST
@htmx_required
def add(request: HttpRequest, product_id: int) -> HttpResponse:
    """Добавить товар в корзину (кнопка «В корзину» / степпер)."""
    product = get_object_or_404(Product, pk=product_id)
    cart = get_cart(request)
    qty = request.POST.get("qty", 1)
    try:
        total_qty = cart.add(product.pk, qty)
    except InvalidQuantity:
        # 200, а не 400: htmx по умолчанию не подменяет блок на ошибочный
        # ответ, и покупатель не увидел бы причину отказа.
        return render(
            request,
            "cart/partials/cart_button.html",
            {
                "product": product,
                "in_cart_qty": cart.qty_of(product.pk),
                "error": f"Количество должно быть целым числом от {MIN_QTY} до {MAX_QTY}.",
            },
        )
    except ProductUnavailable as exc:
        # 200 + фрагмент-уведомление: htmx по умолчанию не подменяет блок
        # на ответ с ошибочным статусом, и покупатель не увидел бы причину.
        return render(
            request,
            "cart/partials/product_unavailable.html",
            {"product": product, "message": str(exc)},
        )

    return _fragment(
        request,
        "cart/partials/cart_button.html",
        {"product": product, "in_cart_qty": total_qty},
    )


@require_POST
@htmx_required
def update(request: HttpRequest, product_id: int) -> HttpResponse:
    """Изменить количество. qty=0 удаляет позицию."""
    product = get_object_or_404(Product, pk=product_id)
    cart = get_cart(request)
    raw_qty = request.POST.get("qty", "")
    if str(raw_qty).strip() in {"0", "0.0"}:
        cart.remove(product.pk)
        return _cart_fragment(request)
    try:
        cart.set(product.pk, raw_qty)
    except InvalidQuantity:
        return _cart_fragment(
            request,
            error=f"Количество должно быть целым числом от {MIN_QTY} до {MAX_QTY}.",
        )
    except ProductUnavailable as exc:
        # Товар успел стать недоступным: чистим корзину и показываем причину.
        return _cart_fragment(request, error=str(exc))
    return _cart_fragment(request)


@require_POST
@htmx_required
def remove(request: HttpRequest, product_id: int) -> HttpResponse:
    product = get_object_or_404(Product, pk=product_id)
    get_cart(request).remove(product.pk)
    return _cart_fragment(request)


@require_POST
@htmx_required
def clear(request: HttpRequest) -> HttpResponse:
    get_cart(request).clear()
    return _cart_fragment(request)


def detail(request: HttpRequest) -> HttpResponse:
    """Страница корзины."""
    context = _cart_context(request)
    context["title"] = "Корзина"
    response = render(request, "cart/detail.html", context)
    # Запоминаем состояние, которое покупатель сейчас видит: checkout
    # сравнит его с актуальным и покажет изменения цен/состава.
    return remember_fingerprint(response, get_cart(request))


# ---------------------------------------------------------------------------
# Избранное
# ---------------------------------------------------------------------------
def _favorites_context(request: HttpRequest) -> dict:
    favorites = get_favorites(request)
    return {
        "favorites": favorites,
        "products": favorites.products(),
        "removed": favorites.removed,
        "favorites_count": favorites.count(),
    }


@require_POST
@htmx_required
def favorite_toggle(request: HttpRequest, product_id: int) -> HttpResponse:
    """Переключить избранное. Возвращает кнопку в новом состоянии."""
    product = get_object_or_404(Product, pk=product_id)
    favorites = get_favorites(request)
    try:
        is_favorite = favorites.toggle(product.pk)
    except ProductUnavailable as exc:
        return render(
            request,
            "cart/partials/product_unavailable.html",
            {"product": product, "message": str(exc)},
        )
    return _fragment(
        request,
        "cart/partials/favorite_button.html",
        {"product": product, "is_favorite": is_favorite},
        trigger="favorites-updated, cart-updated",
    )


@require_POST
@htmx_required
def favorite_add(request: HttpRequest, product_id: int) -> HttpResponse:
    """Добавить в избранное (из списка избранного не используется)."""
    product = get_object_or_404(Product, pk=product_id)
    favorites = get_favorites(request)
    try:
        favorites.add(product.pk)
    except ProductUnavailable as exc:
        return render(
            request,
            "cart/partials/product_unavailable.html",
            {"product": product, "message": str(exc)},
        )
    return _fragment(
        request,
        "cart/partials/favorite_button.html",
        {"product": product, "is_favorite": True},
        trigger="favorites-updated, cart-updated",
    )


@require_POST
@htmx_required
def favorite_remove(request: HttpRequest, product_id: int) -> HttpResponse:
    """Убрать из избранного; на странице избранного — перерисовать список."""
    product = get_object_or_404(Product, pk=product_id)
    get_favorites(request).remove(product.pk)
    return _fragment(
        request,
        "cart/partials/favorites_list.html",
        _favorites_context(request),
        trigger="favorites-updated, cart-updated",
    )


def favorites_detail(request: HttpRequest) -> HttpResponse:
    context = _favorites_context(request)
    context["title"] = "Избранное"
    return render(request, "cart/favorites.html", context)


# ---------------------------------------------------------------------------
# Бейдж и мини-счётчики
# ---------------------------------------------------------------------------
def badge(request: HttpRequest) -> HttpResponse:
    """Бейдж корзины в шапке; обновляется по ``cart-updated from:body``."""
    return render(
        request,
        "cart/partials/cart_badge.html",
        {"cart_count": get_cart(request).count()},
    )


def favorites_badge(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "cart/partials/favorites_badge.html",
        {"favorites_count": get_favorites(request).count()},
    )


def state(request: HttpRequest) -> JsonResponse:
    """
    Машиночитаемое состояние корзины для мелких сценариев на JS.

    Не используется htmx-разметкой; оставлен для интеграций и отладки.
    """
    cart = get_cart(request)
    favorites = get_favorites(request)
    return JsonResponse(
        {
            "count": cart.count(),
            "total": str(cart.total()),
            "items": [
                {"product_id": line.product.pk, "qty": line.qty}
                for line in cart.items()
            ],
            "favorites": favorites.ids(),
        }
    )
