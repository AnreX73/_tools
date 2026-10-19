"""
orders/test_admin.py

Тесты админки этапа 5: действия менеджера, read-only позиции, отклонение
с комментарием, предпросмотр PDF и проверка юрлиц.
"""
from __future__ import annotations

from decimal import Decimal
from unittest import mock
from uuid import uuid4

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.urls import reverse

from companies.admin import LegalEntityAdmin
from companies.models import LegalEntity
from shop.models import Category, Product
from users.models import User

from .admin import OrderItemInline
from .models import Invoice, Order, OrderItem
from .services import approve_order
from .statuses import OrderStatus


class AdminTestMixin:
    @classmethod
    def setUpTestData(cls):
        root = Category.objects.add_root(create_kwargs={"name": "Инструмент"})
        leaf = Category.objects.add_child(root, create_kwargs={"name": "Свёрла"})
        cls.product = Product.objects.create(
            sku="ADM-1",
            name="Сверло 10 мм",
            category=leaf,
            price=Decimal("300.00"),
            is_active=True,
            attributes={},
        )
        cls.user = User.objects.create_superuser(
            username="admin",
            email="admin@example.ru",
            password="secret",
        )

    def make_order(self, status=OrderStatus.NEW):
        company, _ = LegalEntity.objects.get_or_create(
            inn="7707083893",
            kpp="773601001",
            defaults={
                "full_name": 'ООО "Админский клиент"',
                "short_name": 'ООО "Админский клиент"',
                "legal_form": LegalEntity.LegalForm.OOO,
                "legal_address": "г. Москва",
            },
        )
        order = Order.objects.create(
            company=company,
            contact_name="Иван Петров",
            contact_email="buyer@example.ru",
            delivery_address="г. Москва",
            requisites_snapshot={
                "short_name": 'ООО "Админский клиент"',
                "inn": "7707083893",
                "kpp": "773601001",
                "legal_form": LegalEntity.LegalForm.OOO,
            },
            status=status,
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


class OrderAdminActionsTests(AdminTestMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)
        self.changelist = reverse("admin:orders_order_changelist")

    def post_action(self, action, order):
        return self.client.post(
            self.changelist,
            {
                "action": action,
                "_selected_action": [order.pk],
            },
            follow=True,
        )

    def test_take_to_work_changes_status(self):
        order = self.make_order()
        response = self.post_action("take_to_work", order)
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.REVIEW)
        self.assertTrue(order.status_log.filter(to_status=OrderStatus.REVIEW).exists())

    def test_approve_creates_invoice_and_enqueues_task(self):
        order = self.make_order(status=OrderStatus.REVIEW)
        with mock.patch("orders.services.async_task") as async_task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post_action("approve_and_send", order)

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.INVOICED)
        invoice = Invoice.objects.get(order=order, is_current=True)
        self.assertEqual(invoice.version, 1)
        async_task.assert_called_once_with(
            "orders.tasks.generate_and_send_invoice", invoice.pk
        )

    def test_reject_requires_comment(self):
        order = self.make_order(status=OrderStatus.REVIEW)
        response = self.client.post(
            self.changelist,
            {
                "action": "reject_orders",
                "_selected_action": [order.pk],
            },
        )
        self.assertEqual(response.status_code, 302)
        reject_url = response["Location"]

        get_response = self.client.get(reject_url)
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Причина отклонения")

        bad = self.client.post(
            reject_url,
            {"order_ids": str(order.pk), "comment": ""},
        )
        self.assertEqual(bad.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.REVIEW)

        good = self.client.post(
            reject_url,
            {"order_ids": str(order.pk), "comment": "Нет в наличии"},
        )
        self.assertEqual(good.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.REJECTED)
        self.assertTrue(
            order.status_log.filter(
                to_status=OrderStatus.REJECTED,
                comment="Нет в наличии",
            ).exists()
        )

    def test_reissue_invoice_creates_new_version(self):
        order = self.make_order(status=OrderStatus.REVIEW)
        first = approve_order(order, enqueue=False)
        self.assertEqual(first.version, 1)

        with mock.patch("orders.services.async_task") as async_task:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post_action("reissue_invoice", order)

        self.assertEqual(response.status_code, 200)
        current = Invoice.objects.get(order=order, is_current=True)
        self.assertEqual(current.number, first.number)
        self.assertEqual(current.version, 2)
        first.refresh_from_db()
        self.assertFalse(first.is_current)
        async_task.assert_called_once_with(
            "orders.tasks.generate_and_send_invoice", current.pk
        )

    def test_search_by_inn_and_email(self):
        order = self.make_order()
        for query in (order.company.inn, order.contact_email):
            response = self.client.get(self.changelist, {"q": query})
            self.assertContains(response, order.number)

    def test_change_page_renders_editable_and_read_only_inlines(self):
        editable = self.make_order(status=OrderStatus.REVIEW)
        response = self.client.get(
            reverse("admin:orders_order_change", args=[editable.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Позиции заявки")
        self.assertContains(response, "История статусов")

        invoiced = self.make_order(status=OrderStatus.REVIEW)
        invoice = approve_order(invoiced, enqueue=False)
        invoiced.refresh_from_db()
        response = self.client.get(
            reverse("admin:orders_order_change", args=[invoiced.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Счета")
        self.assertContains(response, "Позиции заявки")
        self.assertContains(
            response,
            reverse("admin:orders_invoice_preview", args=[invoice.pk]),
        )


class OrderInlineTests(AdminTestMixin, TestCase):
    def setUp(self):
        self.request = RequestFactory().get("/")
        self.request.user = self.user

    def test_items_editable_before_invoice(self):
        order = self.make_order(status=OrderStatus.REVIEW)
        inline = OrderItemInline(Order, admin.site)
        self.assertTrue(inline.has_add_permission(self.request, order))
        self.assertTrue(inline.has_delete_permission(self.request, order))
        self.assertNotIn("price", inline.get_readonly_fields(self.request, order))

    def test_items_read_only_after_invoice(self):
        order = self.make_order(status=OrderStatus.REVIEW)
        approve_order(order, enqueue=False)
        order.refresh_from_db()
        inline = OrderItemInline(Order, admin.site)
        self.assertFalse(inline.has_add_permission(self.request, order))
        self.assertFalse(inline.has_delete_permission(self.request, order))
        self.assertIn("price", inline.get_readonly_fields(self.request, order))


class InvoicePreviewTests(AdminTestMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_preview_returns_pdf_without_saving_it(self):
        order = self.make_order(status=OrderStatus.REVIEW)
        invoice = approve_order(order, enqueue=False)
        url = reverse("admin:orders_invoice_preview", args=[invoice.pk])

        with mock.patch(
            "orders.admin.render_invoice_pdf", return_value=b"%PDF-1.4 preview"
        ):
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response.content, b"%PDF-1.4 preview")
        invoice.refresh_from_db()
        self.assertFalse(invoice.pdf)


class LegalEntityAdminTests(AdminTestMixin, TestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def test_mark_verified_action(self):
        company = LegalEntity.objects.create(
            full_name='ООО "Проверка"',
            short_name="Проверка",
            legal_form=LegalEntity.LegalForm.OOO,
            inn="7707083893",
            kpp="773601001",
        )
        self.assertFalse(company.is_verified)

        response = self.client.post(
            reverse("admin:companies_legalentity_changelist"),
            {
                "action": "mark_verified",
                "_selected_action": [company.pk],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        company.refresh_from_db()
        self.assertTrue(company.is_verified)

        admin_instance = LegalEntityAdmin(LegalEntity, admin.site)
        self.assertIn("is_verified", admin_instance.list_filter)
