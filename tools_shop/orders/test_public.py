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

from companies.models import LegalEntity, SellerProfile
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
        cls.seller = SellerProfile.objects.create(
            short_name="ООО «Публичный продавец»",
            full_name="Общество с ограниченной ответственностью «Публичный продавец»",
            inn="7707083893",
            kpp="773601001",
            legal_address="г. Москва, ул. Продавца, д. 1",
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
        self.assertContains(response, "Продавец")
        self.assertContains(response, "ООО «Публичный продавец»")
        self.assertContains(response, "ИНН 7707083893")

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

    def test_invoice_seller_snapshot_is_used_on_page(self):
        order = self.make_order()
        Invoice.issue_for(order)

        SellerProfile.objects.create(
            short_name="ООО «Новый продавец»",
            full_name="Общество с ограниченной ответственностью «Новый продавец»",
            inn="7707083893",
            kpp="773601001",
            legal_address="г. Москва, ул. Новая, д. 2",
        )

        response = self.client.get(reverse("orders:detail", args=[order.uuid]))
        self.assertEqual(
            response.context["order_seller"]["short_name"],
            "ООО «Публичный продавец»",
        )
        self.assertContains(response, "ООО «Публичный продавец»")
