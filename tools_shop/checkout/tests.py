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
from companies.models import LegalEntity, SellerProfile
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

    def test_ogrn_is_optional_and_validated(self):
        form = CheckoutForm(
            data=self.payload(idempotency_key=str(uuid4()))
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["ogrn"], "")

        form = CheckoutForm(
            data=self.payload(
                ogrn="1027700132195", idempotency_key=str(uuid4())
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["ogrn"], "1027700132195")

        form = CheckoutForm(
            data=self.payload(ogrn="123", idempotency_key=str(uuid4()))
        )
        self.assertFalse(form.is_valid())
        self.assertIn("ogrn", form.errors)

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

    def test_ogrn_is_saved_to_company_and_snapshot(self):
        cart = self.make_cart()
        with mock.patch("checkout.services.async_task"), \
                self.captureOnCommitCallbacks(execute=True):
            order = place_order(
                cart,
                self.cleaned(ogrn="1027700132195"),
                uuid4(),
            )

        self.assertEqual(order.company.ogrn, "1027700132195")
        self.assertEqual(
            order.requisites_snapshot["ogrn"], "1027700132195"
        )

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
        self.assertContains(
            response,
            f'hx-post="{reverse("checkout:suggest_by_inn")}"',
        )
        self.assertContains(response, 'hx-include="#id_inn, #id_kpp"')
        self.assertContains(
            response,
            'hx-trigger="input[event.target.value.length === 10'
            ' || event.target.value.length === 12]'
            ' changed delay:800ms"',
        )
        self.assertContains(response, 'name="ogrn"')
        key = str(response.context["form"]["idempotency_key"].value())
        self.assertEqual(key, self.client.session["checkout_idempotency_key"])

    def test_get_shows_seller_and_legal_links(self):
        SellerProfile.objects.create(
            short_name="ООО «Продавец оформления»",
            full_name="Общество с ограниченной ответственностью «Продавец оформления»",
            inn="7707083893",
            kpp="773601001",
            legal_address="г. Москва, ул. Продавца, д. 1",
        )
        self.set_cart()
        response = self.client.get(FORM_URL)

        self.assertContains(response, "ООО «Продавец оформления»")
        self.assertContains(response, "ИНН / КПП")
        self.assertContains(response, f"{reverse('shop:legal')}?tab=offer")
        self.assertContains(response, f"{reverse('shop:legal')}?tab=privacy")
        self.assertContains(response, "Оператор обработки персональных данных")

    def test_get_with_htmx_header_renders_page(self):
        # htmx-запросы идут без seller в контексте (процессор их пропускает),
        # но страница всё равно должна рендериться: раньше подвал падал
        # с VariableDoesNotExist из-за цепочки default: в base.html.
        self.set_cart()
        response = self.client.get(FORM_URL, HTTP_HX_REQUEST="true")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="organization-fields"')
        self.assertContains(response, "ТУЛЗ СЕРВИС")

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

    def test_suggest_by_inn_rejects_get(self):
        response = self.client.get(reverse("checkout:suggest_by_inn"))
        self.assertEqual(response.status_code, 405)
