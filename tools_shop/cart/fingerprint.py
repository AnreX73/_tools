"""
cart/fingerprint.py

Отпечаток «что покупатель видел в корзине» для проверки изменений на checkout.

В сессии по требованию лежат только ``{product_id: qty}`` и список id
избранного — цен там нет. Чтобы на /checkout/ понять, что цена или состав
изменились с момента просмотра корзины, отпечаток хранится в отдельной
подписанной cookie:

* cookie содержит только HMAC-хеш (см. ``Cart.fingerprint``), не цены;
* подпись не даёт подменить хеш на клиенте;
* cookie HttpOnly и SameSite=Lax, живёт неделю.

Checkout сравнивает ``read_fingerprint(request)`` с актуальным
``Cart.fingerprint()`` и показывает изменения, если они разошлись.
"""
from __future__ import annotations

from django.core import signing
from django.http import HttpRequest, HttpResponse

from .services import Cart

COOKIE_NAME = "cart_fp"
SALT = "cart.fingerprint"
MAX_AGE = 60 * 60 * 24 * 7  # неделя


def remember_fingerprint(response: HttpResponse, cart: Cart) -> HttpResponse:
    """Записывает подписанный отпечаток текущей корзины в ответ."""
    value = signing.dumps(cart.fingerprint(), salt=SALT, compress=True)
    response.set_cookie(
        COOKIE_NAME,
        value,
        max_age=MAX_AGE,
        httponly=True,
        samesite="Lax",
    )
    return response


def read_fingerprint(request: HttpRequest) -> str | None:
    """Возвращает отпечаток из cookie или None, если cookie нет/испорчена."""
    raw = request.COOKIES.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        value = signing.loads(raw, salt=SALT, max_age=MAX_AGE)
    except signing.BadSignature:
        return None
    return value if isinstance(value, str) else None


def fingerprint_changed(request: HttpRequest, cart: Cart) -> bool:
    """
    True, если состав/цены корзины изменились с момента прошлого просмотра.

    Отсутствие cookie не считается изменением: покупатель мог прийти на
    checkout по прямой ссылке, показывать ему «изменения» не за что.
    """
    remembered = read_fingerprint(request)
    if remembered is None:
        return False
    return remembered != cart.fingerprint()
