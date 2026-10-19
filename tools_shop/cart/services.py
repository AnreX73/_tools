"""
cart/services.py

Корзина и избранное для анонимного покупателя.

В сессии хранится МИНИМУМ:
  * корзина   — {"<product_id>": qty};
  * избранное — ["<product_id>", ...].

Ни названий, ни цен, ни артикулов в сессии нет: при каждом показе товары
подтягиваются из БД одним запросом (``in_bulk``), а недоступные позиции
(удалённые, скрытые, с ценой «по запросу») отфильтровываются и вычищаются
из сессии, чтобы уведомление не повторялось бесконечно.

Сервисы принимают ``request``, а не ``request.session``: так позже можно
переключить хранение на БД, не меняя вызовы во вьюхах.
"""
from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.http import HttpRequest

from shop.models import Product

CART_SESSION_KEY = "cart"
FAVORITES_SESSION_KEY = "favorites"

MIN_QTY = 1
MAX_QTY = 9999

# Причины, по которым позиция пропала из корзины.
REASON_DELETED = "deleted"
REASON_INACTIVE = "inactive"
REASON_NO_PRICE = "no_price"

REASON_MESSAGES = {
    REASON_DELETED: "Товар больше не продаётся и удалён из корзины",
    REASON_INACTIVE: "Товар снят с продажи и удалён из корзины",
    REASON_NO_PRICE: "У товара изменилась цена, оформить его нельзя",
}


class CartError(Exception):
    """Базовая ошибка сервисов корзины."""


class InvalidQuantity(CartError):
    """Количество не является целым числом в диапазоне 1..9999."""

    def __init__(self, value: object) -> None:
        self.value = value
        super().__init__(
            f"Количество должно быть целым числом от {MIN_QTY} до {MAX_QTY}."
        )


class ProductUnavailable(CartError):
    """Товар нельзя положить в корзину."""

    def __init__(self, product: Product | None, reason: str) -> None:
        self.product = product
        self.reason = reason
        super().__init__(REASON_MESSAGES.get(reason, "Товар недоступен"))


@dataclass(frozen=True, slots=True)
class CartLine:
    """Позиция корзины, собранная из сессии и актуальных данных товара."""

    product: Product
    qty: int

    @property
    def price(self) -> Decimal:
        return self.product.price  # type: ignore[return-value]

    @property
    def line_total(self) -> Decimal:
        return (self.price or Decimal("0")) * self.qty


@dataclass(frozen=True, slots=True)
class RemovedLine:
    """Позиция, которую пришлось убрать: товар исчез или стал недоступен."""

    product_id: int
    qty: int
    reason: str
    name: str = ""

    @property
    def message(self) -> str:
        base = REASON_MESSAGES.get(self.reason, "Товар недоступен")
        if self.name:
            return f"«{self.name}»: {base[0].lower()}{base[1:]}"
        return base


def normalize_qty(value: object) -> int:
    """
    Приводит количество к int и проверяет диапазон.

    Принимает int, строку из формы и Decimal без дробной части.
    bool отвергается, хотя в Python bool — подкласс int.
    """
    if isinstance(value, bool):
        raise InvalidQuantity(value)
    if isinstance(value, int):
        qty = value
    elif isinstance(value, str):
        text = value.strip()
        if not text or not text.lstrip("+-").isdigit():
            raise InvalidQuantity(value)
        qty = int(text)
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise InvalidQuantity(value)
        qty = int(value)
    else:
        raise InvalidQuantity(value)
    if not MIN_QTY <= qty <= MAX_QTY:
        raise InvalidQuantity(value)
    return qty


def _product_is_orderable(product: Product) -> str | None:
    """None — можно заказывать, иначе причина отказа."""
    if not product.is_active:
        return REASON_INACTIVE
    if product.price is None:
        return REASON_NO_PRICE
    return None


class _SessionCollection:
    """Общая логика сессионных коллекций: ключ, загрузка/запись, кэш."""

    session_key = ""

    def __init__(self, request: HttpRequest) -> None:
        self.request = request
        self.session = request.session
        self._invalidate()

    # ---- кэш в пределах запроса -------------------------------------------
    def _invalidate(self) -> None:
        self._raw_cache: dict[int, int] | None = None

    def _mark_dirty(self) -> None:
        self._invalidate()
        self.session.modified = True

    # ---- чтение с кэшем ---------------------------------------------------
    def _data(self) -> dict[int, int]:
        """Разобранное содержимое сессии; парсится один раз за запрос."""
        if self._raw_cache is None:
            self._raw_cache = self._read()
        return self._raw_cache

    # ---- абстрактные операции --------------------------------------------
    def _read(self) -> dict[int, int]:
        raise NotImplementedError

    def _write(self, data: dict[int, int]) -> None:
        raise NotImplementedError


class Cart(_SessionCollection):
    """Корзина: {product_id: qty} в сессии."""

    session_key = CART_SESSION_KEY

    def __init__(self, request: HttpRequest) -> None:
        super().__init__(request)
        self._lines: list[CartLine] | None = None
        self._removed: list[RemovedLine] = []

    # ---- чтение/запись сессии --------------------------------------------
    def _read(self) -> dict[int, int]:
        raw = self.session.get(self.session_key) or {}
        if not isinstance(raw, dict):
            return {}
        result: dict[int, int] = {}
        for key, value in raw.items():
            try:
                product_id = int(key)
                qty = int(value)
            except (TypeError, ValueError):
                continue
            if MIN_QTY <= qty <= MAX_QTY:
                result[product_id] = qty
        return result

    def _write(self, data: dict[int, int]) -> None:
        self.session[self.session_key] = {str(pid): qty for pid, qty in data.items()}
        self._lines = None
        self._removed = []
        self._mark_dirty()

    # ---- доступные позиции -----------------------------------------------
    def items(self) -> list[CartLine]:
        """
        Позиции корзины с актуальными ценами и названиями.

        Недоступные товары не попадают в результат и удаляются из сессии;
        список причин доступен в ``removed``.
        """
        if self._lines is not None:
            return self._lines

        raw = self._data()
        products = Product.objects.in_bulk(list(raw))
        lines: list[CartLine] = []
        removed: list[RemovedLine] = []
        changed = False

        for product_id, qty in raw.items():
            product = products.get(product_id)
            if product is None:
                removed.append(RemovedLine(product_id, qty, REASON_DELETED))
                changed = True
                continue
            reason = _product_is_orderable(product)
            if reason is not None:
                removed.append(RemovedLine(product_id, qty, reason, product.name))
                changed = True
                continue
            lines.append(CartLine(product, qty))

        if changed:
            self._write({line.product.pk: line.qty for line in lines})
        self._lines = lines
        self._removed = removed
        return lines

    @property
    def removed(self) -> list[RemovedLine]:
        """Позиции, вычищенные при последнем вызове items()."""
        self.items()
        return self._removed

    def as_dict(self) -> dict[int, int]:
        """Сырое содержимое корзины (без обращения к БД)."""
        return dict(self._data())

    def has(self, product_id: int) -> bool:
        return int(product_id) in self._data()

    def qty_of(self, product_id: int) -> int:
        return self._data().get(int(product_id), 0)

    # ---- изменение --------------------------------------------------------
    def set(self, product_id: int, qty: object) -> int:
        """Устанавливает точное количество. Бросает InvalidQuantity/ProductUnavailable."""
        quantity = normalize_qty(qty)
        product = Product.objects.filter(pk=product_id).first()
        reason = REASON_DELETED if product is None else _product_is_orderable(product)
        if reason is not None:
            raise ProductUnavailable(product, reason)
        raw = dict(self._data())
        raw[int(product_id)] = quantity
        self._write(raw)
        return quantity

    def add(self, product_id: int, qty: object = 1) -> int:
        """
        Добавляет количество к уже лежащему в корзине.

        Итог ограничивается MAX_QTY, чтобы «+» у предела не ронял запрос.
        """
        quantity = normalize_qty(qty)
        product = Product.objects.filter(pk=product_id).first()
        reason = REASON_DELETED if product is None else _product_is_orderable(product)
        if reason is not None:
            raise ProductUnavailable(product, reason)
        raw = dict(self._data())
        total = min(raw.get(int(product_id), 0) + quantity, MAX_QTY)
        raw[int(product_id)] = total
        self._write(raw)
        return total

    def remove(self, product_id: int) -> None:
        raw = dict(self._data())
        if raw.pop(int(product_id), None) is not None:
            self._write(raw)

    def clear(self) -> None:
        if self.session.get(self.session_key):
            self._write({})

    # ---- агрегаты ---------------------------------------------------------
    def count(self) -> int:
        """Суммарное количество единиц (для бейджа)."""
        return sum(line.qty for line in self.items())

    def total(self) -> Decimal:
        """Сумма по корзине в рублях с точностью до копейки."""
        amount = sum((line.line_total for line in self.items()), Decimal("0"))
        return amount.quantize(Decimal("0.01"))

    def is_empty(self) -> bool:
        return not self.items()

    # ---- отпечаток цен для checkout --------------------------------------
    def fingerprint(self) -> str:
        """
        HMAC-отпечаток состава корзины и цен.

        Нужен, чтобы на /checkout/ понять, что цена изменилась с момента,
        когда покупатель видел корзину. Сам отпечаток цен не раскрывает:
        в нём только необратимый хеш, и в сессии он не хранится.
        """
        parts = [
            f"{line.product.pk}:{line.qty}:{line.price}"
            for line in sorted(self.items(), key=lambda line: line.product.pk)
        ]
        message = "|".join(parts).encode("utf-8")
        return hmac.new(
            settings.SECRET_KEY.encode("utf-8"), message, hashlib.sha256
        ).hexdigest()


class Favorites(_SessionCollection):
    """Избранное: упорядоченный список product_id в сессии."""

    session_key = FAVORITES_SESSION_KEY

    def __init__(self, request: HttpRequest) -> None:
        super().__init__(request)
        self._products: list[Product] | None = None
        self._removed: list[RemovedLine] = []

    def _read(self) -> dict[int, int]:
        raw = self.session.get(self.session_key) or []
        if not isinstance(raw, list):
            return {}
        result: dict[int, int] = {}
        for value in raw:
            try:
                product_id = int(value)
            except (TypeError, ValueError):
                continue
            result.setdefault(product_id, 1)  # порядок добавления сохраняем
        return result

    def _write(self, data: dict[int, int]) -> None:
        self.session[self.session_key] = [str(pid) for pid in data]
        self._products = None
        self._removed = []
        self._mark_dirty()

    def products(self) -> list[Product]:
        """
        Товары из избранного в порядке добавления.

        Скрытые и удалённые товары вычищаются; причины — в ``removed``.
        Товары с ценой «по запросу» остаются в избранном: их можно держать
        «на заметку», но в корзину они не добавляются.
        """
        if self._products is not None:
            return self._products

        raw = self._data()
        found = Product.objects.in_bulk(list(raw))
        products: list[Product] = []
        removed: list[RemovedLine] = []
        changed = False

        for product_id in raw:
            product = found.get(product_id)
            if product is None:
                removed.append(RemovedLine(product_id, 1, REASON_DELETED))
                changed = True
                continue
            if not product.is_active:
                removed.append(RemovedLine(product_id, 1, REASON_INACTIVE, product.name))
                changed = True
                continue
            products.append(product)

        if changed:
            self._write({product.pk: 1 for product in products})
        self._products = products
        self._removed = removed
        return products

    @property
    def removed(self) -> list[RemovedLine]:
        self.products()
        return self._removed

    def ids(self) -> list[int]:
        return [product.pk for product in self.products()]

    def count(self) -> int:
        return len(self.products())

    def contains(self, product_id: int) -> bool:
        return int(product_id) in self._data()

    def add(self, product_id: int) -> bool:
        """True — добавлен, False — уже был."""
        product = Product.objects.filter(pk=product_id).first()
        reason = REASON_DELETED if product is None else (
            None if product.is_active else REASON_INACTIVE
        )
        if reason is not None:
            raise ProductUnavailable(product, reason)
        raw = dict(self._data())
        if int(product_id) in raw:
            return False
        raw[int(product_id)] = 1
        self._write(raw)
        return True

    def remove(self, product_id: int) -> None:
        raw = dict(self._data())
        if raw.pop(int(product_id), None) is not None:
            self._write(raw)

    def toggle(self, product_id: int) -> bool:
        """True — теперь в избранном, False — убрали."""
        if self.contains(product_id):
            self.remove(product_id)
            return False
        self.add(product_id)
        return True

    def clear(self) -> None:
        if self.session.get(self.session_key):
            self._write({})


# ---------------------------------------------------------------------------
# Кэш сервисов в пределах запроса
# ---------------------------------------------------------------------------
def get_cart(request: HttpRequest) -> Cart:
    """Один экземпляр Cart на запрос (контекст-процессор + вьюха)."""
    cart = getattr(request, "_cart_service", None)
    if cart is None:
        cart = Cart(request)
        request._cart_service = cart  # type: ignore[attr-defined]
    return cart


def get_favorites(request: HttpRequest) -> Favorites:
    favorites = getattr(request, "_favorites_service", None)
    if favorites is None:
        favorites = Favorites(request)
        request._favorites_service = favorites  # type: ignore[attr-defined]
    return favorites
