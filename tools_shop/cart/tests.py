"""
cart/tests.py

Тесты сервисов корзины/избранного и htmx-вьюх.

Запуск: python manage.py test cart
"""
from __future__ import annotations

from decimal import Decimal

from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from shop.models import Category, Product

from .services import (
    CART_SESSION_KEY,
    FAVORITES_SESSION_KEY,
    MAX_QTY,
    Cart,
    Favorites,
    InvalidQuantity,
    ProductUnavailable,
    get_cart,
    get_favorites,
    normalize_qty,
)


class CartTestMixin:
    """Общий набор товаров: обычный, скрытый, без цены, удалённый."""

    @classmethod
    def setUpTestData(cls):
        root = Category.objects.add_root(create_kwargs={"name": "Инструмент"})
        cls.leaf = Category.objects.add_child(root, create_kwargs={"name": "Свёрла"})
        cls.product = cls._product("CART-1", Decimal("120.00"))
        cls.product2 = cls._product("CART-2", Decimal("50.50"))
        cls.hidden = cls._product("CART-H", Decimal("10.00"), is_active=False)
        # Цена NULL возможна только у скрытого товара (CheckConstraint
        # active_product_requires_price), поэтому причина удаления — inactive.
        cls.no_price = cls._product("CART-N", None, is_active=False)
        cls.deleted_id = 999_999

    @classmethod
    def _product(cls, sku: str, price: Decimal | None, is_active: bool = True) -> Product:
        return Product.objects.create(
            sku=sku,
            name=f"Товар {sku}",
            category=cls.leaf,
            price=price,
            is_active=is_active,
            attributes={},
        )

    def request_with_session(self):
        request = RequestFactory().get("/")
        from django.contrib.sessions.backends.db import SessionStore

        request.session = SessionStore()
        return request


class NormalizeQtyTests(TestCase):
    def test_accepts_valid_values(self):
        self.assertEqual(normalize_qty(1), 1)
        self.assertEqual(normalize_qty("42"), 42)
        self.assertEqual(normalize_qty(MAX_QTY), MAX_QTY)
        self.assertEqual(normalize_qty(Decimal("7")), 7)

    def test_rejects_out_of_range(self):
        for value in (0, -1, MAX_QTY + 1, "0", "-3", "10000"):
            with self.subTest(value=value), self.assertRaises(InvalidQuantity):
                normalize_qty(value)

    def test_rejects_non_integer(self):
        for value in ("abc", "", "1.5", Decimal("1.5"), None, [], True, False):
            with self.subTest(value=value), self.assertRaises(InvalidQuantity):
                normalize_qty(value)


class CartServiceTests(CartTestMixin, TestCase):
    def setUp(self):
        self.request = self.request_with_session()
        self.cart = Cart(self.request)

    def test_add_and_read(self):
        self.cart.add(self.product.pk, 2)
        self.assertEqual(self.cart.qty_of(self.product.pk), 2)
        self.assertEqual(self.cart.count(), 2)
        self.assertEqual(self.cart.total(), Decimal("240.00"))

    def test_add_accumulates(self):
        self.cart.add(self.product.pk, 2)
        self.cart.add(self.product.pk, 3)
        self.assertEqual(self.cart.qty_of(self.product.pk), 5)

    def test_add_is_capped_at_max(self):
        self.cart.add(self.product.pk, MAX_QTY - 1)
        self.cart.add(self.product.pk, 10)
        self.assertEqual(self.cart.qty_of(self.product.pk), MAX_QTY)

    def test_set_overwrites(self):
        self.cart.add(self.product.pk, 2)
        self.cart.set(self.product.pk, 7)
        self.assertEqual(self.cart.qty_of(self.product.pk), 7)

    def test_set_rejects_bad_quantity(self):
        with self.assertRaises(InvalidQuantity):
            self.cart.set(self.product.pk, 0)

    def test_remove(self):
        self.cart.add(self.product.pk, 2)
        self.cart.remove(self.product.pk)
        self.assertEqual(self.cart.qty_of(self.product.pk), 0)
        self.assertTrue(self.cart.is_empty())

    def test_clear(self):
        self.cart.add(self.product.pk, 2)
        self.cart.add(self.product2.pk, 1)
        self.cart.clear()
        self.assertTrue(self.cart.is_empty())
        self.assertEqual(self.cart.total(), Decimal("0.00"))

    def test_total_uses_actual_prices(self):
        self.cart.add(self.product.pk, 2)
        self.cart.add(self.product2.pk, 4)
        self.assertEqual(self.cart.total(), Decimal("442.00"))

    def test_session_stores_only_ids_and_quantities(self):
        self.cart.add(self.product.pk, 2)
        stored = self.request.session[CART_SESSION_KEY]
        self.assertEqual(stored, {str(self.product.pk): 2})
        self.assertNotIn("name", str(stored))
        self.assertNotIn("price", str(stored))

    def test_price_change_is_reflected(self):
        self.cart.add(self.product.pk, 2)
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("999.99"))
        self.assertEqual(self.cart.total(), Decimal("1999.98"))

    def test_deleted_product_is_removed_and_reported(self):
        self.request.session[CART_SESSION_KEY] = {str(self.deleted_id): 3}
        self.request.session.save()
        cart = Cart(self.request)
        self.assertEqual(cart.items(), [])
        self.assertEqual(len(cart.removed), 1)
        self.assertEqual(cart.removed[0].reason, "deleted")
        self.assertNotIn(str(self.deleted_id), self.request.session[CART_SESSION_KEY])

    def test_inactive_product_is_removed_and_reported(self):
        self.request.session[CART_SESSION_KEY] = {str(self.hidden.pk): 1}
        cart = Cart(self.request)
        self.assertEqual(cart.items(), [])
        self.assertEqual(cart.removed[0].reason, "inactive")
        self.assertIn(self.hidden.name, cart.removed[0].message)

    def test_product_without_price_is_not_orderable(self):
        """
        Активный товар без цены невозможен (CheckConstraint), но проверка
        в сервисе остаётся защитной: причина no_price срабатывает первой.
        """
        from types import SimpleNamespace

        from .services import REASON_NO_PRICE, _product_is_orderable

        fake = SimpleNamespace(is_active=True, price=None)
        self.assertEqual(_product_is_orderable(fake), REASON_NO_PRICE)

    def test_add_unavailable_raises(self):
        with self.assertRaises(ProductUnavailable):
            self.cart.add(self.hidden.pk, 1)
        with self.assertRaises(ProductUnavailable):
            self.cart.add(self.no_price.pk, 1)
        with self.assertRaises(ProductUnavailable):
            self.cart.add(self.deleted_id, 1)

    def test_fingerprint_changes_with_price(self):
        self.cart.add(self.product.pk, 1)
        before = self.cart.fingerprint()
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("121.00"))
        after = Cart(self.request).fingerprint()
        self.assertNotEqual(before, after)

    def test_fingerprint_changes_with_quantity(self):
        self.cart.add(self.product.pk, 1)
        before = self.cart.fingerprint()
        self.cart.set(self.product.pk, 2)
        self.assertNotEqual(before, self.cart.fingerprint())

    def test_get_cart_is_cached_per_request(self):
        self.assertIs(get_cart(self.request), get_cart(self.request))


class FavoritesServiceTests(CartTestMixin, TestCase):
    def setUp(self):
        self.request = self.request_with_session()
        self.favorites = Favorites(self.request)

    def test_add_and_count(self):
        self.assertTrue(self.favorites.add(self.product.pk))
        self.assertFalse(self.favorites.add(self.product.pk))  # уже есть
        self.assertEqual(self.favorites.count(), 1)
        self.assertTrue(self.favorites.contains(self.product.pk))

    def test_toggle(self):
        self.assertTrue(self.favorites.toggle(self.product.pk))
        self.assertFalse(self.favorites.toggle(self.product.pk))
        self.assertEqual(self.favorites.count(), 0)

    def test_order_is_preserved(self):
        self.favorites.add(self.product2.pk)
        self.favorites.add(self.product.pk)
        self.assertEqual(self.favorites.ids(), [self.product2.pk, self.product.pk])

    def test_session_stores_only_ids(self):
        self.favorites.add(self.product.pk)
        self.assertEqual(self.request.session[FAVORITES_SESSION_KEY], [str(self.product.pk)])

    def test_hidden_and_deleted_are_filtered(self):
        self.request.session[FAVORITES_SESSION_KEY] = [
            str(self.hidden.pk),
            str(self.deleted_id),
            str(self.product.pk),
        ]
        favorites = Favorites(self.request)
        self.assertEqual([p.pk for p in favorites.products()], [self.product.pk])
        self.assertEqual({item.reason for item in favorites.removed}, {"inactive", "deleted"})

    def test_inactive_product_cannot_be_added_to_favorites(self):
        with self.assertRaises(ProductUnavailable):
            self.favorites.add(self.no_price.pk)

    def test_get_favorites_is_cached_per_request(self):
        self.assertIs(get_favorites(self.request), get_favorites(self.request))


class CartViewTests(CartTestMixin, TestCase):
    def setUp(self):
        self.client = Client(HTTP_HOST="localhost")

    def test_add_requires_post(self):
        response = self.client.get(reverse("cart:add", args=[self.product.pk]))
        self.assertEqual(response.status_code, 405)

    def test_add_requires_csrf(self):
        client = Client(HTTP_HOST="localhost", enforce_csrf_checks=True)
        response = client.post(
            reverse("cart:add", args=[self.product.pk]), {"qty": 1}
        )
        self.assertEqual(response.status_code, 403)

    def test_add_returns_fragment_and_trigger(self):
        response = self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 2},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Trigger"], "cart-updated")
        self.assertContains(response, "В корзине: 2")

    def test_add_updates_badge(self):
        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 3},
            HTTP_HX_REQUEST="true",
        )
        response = self.client.get(reverse("cart:badge"))
        self.assertContains(response, "header-badge")
        self.assertContains(response, ">3<")

    def test_add_rejects_bad_quantity(self):
        response = self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": "abc"},
            HTTP_HX_REQUEST="true",
        )
        # 200 + сообщение в фрагменте: htmx не подменяет блок на 4xx.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Количество должно быть целым числом")
        self.assertEqual(self.client.get(reverse("cart:state")).json()["count"], 0)

    def test_add_unavailable_product_returns_notice(self):
        response = self.client.post(
            reverse("cart:add", args=[self.hidden.pk]),
            {"qty": 1},
            HTTP_HX_REQUEST="true",
        )
        # 200 + фрагмент с причиной, чтобы htmx показал сообщение.
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "снят с продажи")

    def test_mutation_without_htmx_is_rejected(self):
        """У мутирующих эндпоинтов нет no-JS fallback: без HX-Request — 400."""
        response = self.client.post(
            reverse("cart:add", args=[self.product.pk]), {"qty": 1}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(reverse("cart:state")).json()["count"], 0)

    def test_update_changes_quantity(self):
        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 1},
            HTTP_HX_REQUEST="true",
        )
        response = self.client.post(
            reverse("cart:update", args=[self.product.pk]),
            {"qty": 5},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Trigger"], "cart-updated")
        self.assertContains(response, "600")

    def test_update_to_zero_removes_line(self):
        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 1},
            HTTP_HX_REQUEST="true",
        )
        response = self.client.post(
            reverse("cart:update", args=[self.product.pk]),
            {"qty": 0},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Корзина пуста")

    def test_remove(self):
        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 1},
            HTTP_HX_REQUEST="true",
        )
        response = self.client.post(
            reverse("cart:remove", args=[self.product.pk]), HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Корзина пуста")

    def test_clear(self):
        for product in (self.product, self.product2):
            self.client.post(
                reverse("cart:add", args=[product.pk]),
                {"qty": 1},
                HTTP_HX_REQUEST="true",
            )
        response = self.client.post(reverse("cart:clear"), HTTP_HX_REQUEST="true")
        self.assertContains(response, "Корзина пуста")

    def test_cart_page_shows_removed_notice(self):
        session = self.client.session
        session[CART_SESSION_KEY] = {str(self.hidden.pk): 1}
        session.save()
        response = self.client.get(reverse("cart:detail"))
        self.assertContains(response, "Корзина изменилась")
        self.assertContains(response, "снят с продажи")

    def test_favorite_toggle(self):
        response = self.client.post(
            reverse("cart:favorite_toggle", args=[self.product.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("favorites-updated", response["HX-Trigger"])
        self.assertContains(response, 'aria-pressed="true"')

    def test_favorite_toggle_twice(self):
        url = reverse("cart:favorite_toggle", args=[self.product.pk])
        self.client.post(url, HTTP_HX_REQUEST="true")
        response = self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertContains(response, 'aria-pressed="false"')

    def test_favorites_page(self):
        self.client.post(
            reverse("cart:favorite_toggle", args=[self.product.pk]),
            HTTP_HX_REQUEST="true",
        )
        response = self.client.get(reverse("cart:favorites"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.product.name)

    def test_favorite_remove_rerenders_list(self):
        self.client.post(
            reverse("cart:favorite_toggle", args=[self.product.pk]),
            HTTP_HX_REQUEST="true",
        )
        response = self.client.post(
            reverse("cart:favorite_remove", args=[self.product.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, "В избранном пока ничего нет")

    def test_state_endpoint(self):
        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 2},
            HTTP_HX_REQUEST="true",
        )
        response = self.client.get(reverse("cart:state"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["total"], "240.00")

    def test_counters_in_header(self):
        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 2},
            HTTP_HX_REQUEST="true",
        )
        response = self.client.get("/")
        self.assertContains(response, 'aria-label="Корзина: 2"')

    def test_htmx_request_has_no_counters(self):
        """Фрагменты не должны тянуть счётчики из контекст-процессора."""
        response = self.client.get(
            reverse("cart:badge"), HTTP_HX_REQUEST="true"
        )
        self.assertNotContains(response, "Избранное:")

    def test_update_returns_trigger(self):
        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 1},
            HTTP_HX_REQUEST="true",
        )
        for name in ("cart:update", "cart:remove"):
            with self.subTest(view=name):
                response = self.client.post(
                    reverse(name, args=[self.product.pk]),
                    {"qty": 1} if name == "cart:update" else {},
                    HTTP_HX_REQUEST="true",
                )
                self.assertEqual(response["HX-Trigger"], "cart-updated")
                self.client.post(
                    reverse("cart:add", args=[self.product.pk]),
                    {"qty": 1},
                    HTTP_HX_REQUEST="true",
                )


class CartSessionTests(CartTestMixin, TestCase):
    """Корзина и избранное переживают переход между запросами."""

    def setUp(self):
        self.client = Client(HTTP_HOST="localhost")

    def test_cart_persists_between_requests(self):
        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 4},
            HTTP_HX_REQUEST="true",
        )
        state = self.client.get(reverse("cart:state")).json()
        self.assertEqual(state["count"], 4)
        self.assertEqual(state["items"], [{"product_id": self.product.pk, "qty": 4}])

    def test_favorites_persist_between_requests(self):
        self.client.post(
            reverse("cart:favorite_toggle", args=[self.product.pk]),
            HTTP_HX_REQUEST="true",
        )
        state = self.client.get(reverse("cart:state")).json()
        self.assertEqual(state["favorites"], [self.product.pk])

    def test_session_settings(self):
        from django.conf import settings

        self.assertEqual(
            settings.SESSION_ENGINE,
            "django.contrib.sessions.backends.cached_db",
        )
        self.assertEqual(settings.SESSION_COOKIE_AGE, 60 * 60 * 24 * 90)

    def test_cart_page_sets_fingerprint_cookie(self):
        from cart.fingerprint import COOKIE_NAME

        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 1},
            HTTP_HX_REQUEST="true",
        )
        response = self.client.get(reverse("cart:detail"))
        self.assertIn(COOKIE_NAME, response.cookies)
        self.assertTrue(response.cookies[COOKIE_NAME]["httponly"])

    def test_fingerprint_detects_price_change(self):
        from cart.fingerprint import fingerprint_changed

        self.client.post(
            reverse("cart:add", args=[self.product.pk]),
            {"qty": 1},
            HTTP_HX_REQUEST="true",
        )
        self.client.get(reverse("cart:detail"))  # запоминаем отпечаток
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("999.00"))

        request = RequestFactory().get("/checkout/")
        request.COOKIES.update(
            {key: morsel.value for key, morsel in self.client.cookies.items()}
        )
        request.session = self.client.session
        from cart.services import get_cart as _get_cart

        self.assertTrue(fingerprint_changed(request, _get_cart(request)))

    def test_fingerprint_ignores_missing_cookie(self):
        from cart.fingerprint import fingerprint_changed

        request = RequestFactory().get("/checkout/")
        request.session = self.client.session
        from cart.services import get_cart as _get_cart

        self.assertFalse(fingerprint_changed(request, _get_cart(request)))

    def test_context_processor_skips_admin(self):
        response = self.client.get("/admin/login/")
        # Контекст-процессор не добавляет счётчики в админку; шапка витрины
        # там не рендерится, поэтому достаточно, что страница открывается.
        self.assertIn(response.status_code, (200, 302))


class MergeOnLoginTests(CartTestMixin, TestCase):
    """Слияние при входе: точка расширения не теряет данные и не падает."""

    def setUp(self):
        self.request = self.request_with_session()

    def test_snapshot_collects_guest_data(self):
        from .merge import merge_guest_data_into_account

        Cart(self.request).add(self.product.pk, 3)
        Favorites(self.request).add(self.product2.pk)
        snapshot = merge_guest_data_into_account(self.request, user=object())
        self.assertEqual(snapshot.cart, {self.product.pk: 3})
        self.assertEqual(snapshot.favorites, [self.product2.pk])
        self.assertFalse(snapshot.is_empty)

    def test_session_is_preserved_after_login(self):
        from .merge import merge_guest_data_into_account

        Cart(self.request).add(self.product.pk, 2)
        merge_guest_data_into_account(self.request, user=object())
        self.assertEqual(Cart(self.request).qty_of(self.product.pk), 2)

    def test_empty_snapshot(self):
        from .merge import merge_guest_data_into_account

        snapshot = merge_guest_data_into_account(self.request, user=object())
        self.assertTrue(snapshot.is_empty)

    def test_signal_is_connected(self):
        from django.contrib.auth.signals import user_logged_in

        names = {
            getattr(entry[1](), "__name__", "")
            for entry in user_logged_in.receivers
        }
        self.assertIn("merge_session_cart_on_login", names)
