"""
orders/tests.py

Тесты моделей заказов и счетов: нумерация, снимок позиций, таблица
переходов статусов, история и версии счетов.

Запуск: python manage.py test orders
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from companies.models import LegalEntity
from shop.models import Category, Product

from .models import Invoice, InvoiceNotAllowed, InvalidTransition, Order, OrderItem, OrderStatusLog
from .services import approve_order
from .statuses import (
    EDITABLE_STATUSES,
    TERMINAL_STATUSES,
    OrderStatus,
    allowed_transitions,
    can_transition,
)


class OrderTestMixin:
    @classmethod
    def setUpTestData(cls):
        root = Category.objects.add_root(create_kwargs={"name": "Инструмент"})
        cls.leaf = Category.objects.add_child(root, create_kwargs={"name": "Свёрла"})
        cls.product = Product.objects.create(
            sku="ORD-1",
            name="Сверло 6 мм",
            category=cls.leaf,
            price=Decimal("120.50"),
            attributes={},
        )
        cls.company = LegalEntity.objects.create(
            full_name='ООО "Ромашка"',
            short_name="Ромашка",
            inn="7707083893",
            kpp="773601001",
            legal_address="Москва, ул. Тестовая, 1",
            email="Buyer@Example.RU",
        )

    def make_order(self, **kwargs) -> Order:
        data = {
            "company": self.company,
            "contact_name": "Иван Петров",
            "contact_email": "Ivan@Example.RU",
            "contact_phone": "+7 999 000-00-00",
            "delivery_address": "Москва, ул. Тестовая, 1",
        }
        data.update(kwargs)
        return Order.objects.create(**data)

    def add_item(self, order: Order, *, price: str = "120.50", qty: int = 2) -> OrderItem:
        return OrderItem.objects.create(
            order=order,
            product=self.product,
            name=self.product.name,
            sku=self.product.sku,
            price=Decimal(price),
            qty=qty,
        )


class OrderModelTests(OrderTestMixin, TestCase):
    def test_number_is_generated_and_unique(self):
        first = self.make_order()
        second = self.make_order()
        self.assertRegex(first.number, r"^З-\d{6}$")
        self.assertNotEqual(first.number, second.number)

    def test_uuid_is_public_identifier(self):
        order = self.make_order()
        self.assertIsNotNone(order.uuid)
        self.assertEqual(Order.objects.get(uuid=order.uuid), order)

    def test_email_is_normalized_to_lowercase(self):
        order = self.make_order(contact_email="  Manager@Example.RU ")
        order.refresh_from_db()
        self.assertEqual(order.contact_email, "manager@example.ru")

    def test_default_status_is_new(self):
        self.assertEqual(self.make_order().status, OrderStatus.NEW)

    def test_items_total_uses_snapshot_prices(self):
        order = self.make_order()
        self.add_item(order, price="120.50", qty=2)
        self.add_item(order, price="10.25", qty=4)
        self.assertEqual(order.items_total, Decimal("282.00"))

    def test_item_line_total(self):
        item = self.add_item(self.make_order(), price="99.99", qty=3)
        self.assertEqual(item.line_total, Decimal("299.97"))

    def test_price_snapshot_survives_product_change(self):
        order = self.make_order()
        item = self.add_item(order, price="120.50", qty=2)
        Product.objects.filter(pk=self.product.pk).update(price=Decimal("999.00"))
        item.refresh_from_db()
        self.assertEqual(item.price, Decimal("120.50"))
        self.assertEqual(order.items_total, Decimal("241.00"))

    def test_product_can_be_deleted_and_item_survives(self):
        order = self.make_order()
        item = self.add_item(order)
        Product.objects.filter(pk=self.product.pk).delete()
        item.refresh_from_db()
        self.assertIsNone(item.product)
        self.assertEqual(item.sku, "ORD-1")

    def test_editable_only_before_invoice(self):
        order = self.make_order()
        self.assertTrue(order.is_editable)
        order.status = OrderStatus.INVOICED
        self.assertFalse(order.is_editable)

    def test_company_orders_related_name(self):
        order = self.make_order()
        self.assertEqual(list(self.company.orders.all()), [order])

    def test_email_lookup_ignores_case(self):
        self.make_order(contact_email="Ivan@Example.RU")
        self.assertEqual(Order.objects.for_email("IVAN@example.ru").count(), 1)


class StatusTransitionTests(OrderTestMixin, TestCase):
    def test_transition_table_is_explicit(self):
        self.assertEqual(
            allowed_transitions(OrderStatus.NEW),
            frozenset({OrderStatus.REVIEW, OrderStatus.CANCELLED, OrderStatus.REJECTED}),
        )
        self.assertEqual(allowed_transitions(OrderStatus.DONE), frozenset())
        self.assertFalse(can_transition(OrderStatus.NEW, OrderStatus.PAID))

    def test_terminal_statuses_have_no_exits(self):
        for status in TERMINAL_STATUSES:
            with self.subTest(status=status):
                self.assertEqual(allowed_transitions(status), frozenset())

    def test_editable_statuses(self):
        self.assertEqual(
            EDITABLE_STATUSES, frozenset({OrderStatus.NEW, OrderStatus.REVIEW})
        )

    def test_happy_path_writes_history(self):
        order = self.make_order()
        Invoice.issue_for(order)
        path = [
            OrderStatus.REVIEW,
            OrderStatus.INVOICED,
            OrderStatus.PAID,
            OrderStatus.SHIPPED,
            OrderStatus.DONE,
        ]
        for status in path:
            order.transition_to(status, comment=f"→ {status}")

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.DONE)
        logs = list(OrderStatusLog.objects.filter(order=order).order_by("at", "pk"))
        self.assertEqual(len(logs), len(path))
        self.assertEqual(logs[0].from_status, OrderStatus.NEW)
        self.assertEqual(logs[-1].to_status, OrderStatus.DONE)
        self.assertEqual(logs[-1].comment, "→ done")

    def test_invoiced_requires_current_invoice(self):
        order = self.make_order()
        order.transition_to(OrderStatus.REVIEW)
        with self.assertRaises(InvalidTransition):
            order.transition_to(OrderStatus.INVOICED)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.REVIEW)

    def test_invoiced_allowed_after_invoice_issued(self):
        order = self.make_order()
        order.transition_to(OrderStatus.REVIEW)
        Invoice.issue_for(order)
        order.transition_to(OrderStatus.INVOICED)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.INVOICED)

    def test_forbidden_transition_does_not_write_log(self):
        order = self.make_order()
        with self.assertRaises(InvalidTransition):
            order.transition_to(OrderStatus.PAID)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertFalse(OrderStatusLog.objects.filter(order=order).exists())

    def test_same_status_is_forbidden(self):
        order = self.make_order()
        with self.assertRaises(InvalidTransition):
            order.transition_to(OrderStatus.NEW)

    def test_unknown_status_is_rejected(self):
        with self.assertRaises(ValueError):
            self.make_order().transition_to("archived")

    def test_terminal_order_cannot_be_changed(self):
        order = self.make_order()
        order.transition_to(OrderStatus.CANCELLED)
        with self.assertRaises(InvalidTransition):
            order.transition_to(OrderStatus.REVIEW)

    def test_log_created_writes_initial_entry(self):
        order = self.make_order()
        log = order.log_created(comment="Заявка оформлена на сайте")
        self.assertEqual(log.from_status, "")
        self.assertEqual(log.to_status, OrderStatus.NEW)
        self.assertEqual(log.comment, "Заявка оформлена на сайте")

    def test_changed_by_is_saved(self):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.create_user(
            username="manager", password="secret123"
        )
        order = self.make_order()
        order.transition_to(OrderStatus.REVIEW, by=user, comment="Беру в работу")
        log = OrderStatusLog.objects.get(order=order)
        self.assertEqual(log.changed_by, user)
        self.assertEqual(log.comment, "Беру в работу")

    def test_error_message_is_human_readable(self):
        order = self.make_order()
        with self.assertRaises(InvalidTransition) as ctx:
            order.transition_to(OrderStatus.SHIPPED)
        self.assertIn("Новая заявка", str(ctx.exception))
        self.assertIn("Отгружен", str(ctx.exception))


class InvoiceModelTests(OrderTestMixin, TestCase):
    def test_number_is_not_assigned_before_issue(self):
        order = self.make_order()
        self.assertFalse(Invoice.objects.filter(order=order).exists())

    def test_first_version_gets_number(self):
        invoice = Invoice.issue_for(self.make_order())
        self.assertRegex(invoice.number, r"^С-\d{6}$")
        self.assertEqual(invoice.version, 1)
        self.assertTrue(invoice.is_current)
        self.assertIsNone(invoice.sent_at)
        self.assertFalse(invoice.is_sent)

    def test_reissue_keeps_number_and_increments_version(self):
        order = self.make_order()
        first = Invoice.issue_for(order)
        second = Invoice.issue_for(order)

        self.assertEqual(second.number, first.number)
        self.assertEqual(second.version, 2)
        first.refresh_from_db()
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        self.assertEqual(Invoice.objects.filter(order=order).count(), 2)

    def test_only_one_current_invoice_per_order(self):
        order = self.make_order()
        Invoice.issue_for(order)
        Invoice.issue_for(order)
        self.assertEqual(order.invoices.current().count(), 1)

    def test_different_orders_get_different_numbers(self):
        first = Invoice.issue_for(self.make_order())
        second = Invoice.issue_for(self.make_order())
        self.assertNotEqual(first.number, second.number)

    def test_sent_invoice_is_not_sent_twice(self):
        from django.utils import timezone

        invoice = Invoice.issue_for(self.make_order())
        self.assertFalse(invoice.is_sent)
        Invoice.objects.filter(pk=invoice.pk).update(sent_at=timezone.now())
        invoice.refresh_from_db()
        self.assertTrue(invoice.is_sent)

    def test_pdf_path_uses_order_uuid(self):
        from .models import invoice_pdf_path

        invoice = Invoice.issue_for(self.make_order())
        path = invoice_pdf_path(invoice, "invoice.pdf")
        self.assertIn(str(invoice.order.uuid), path)
        self.assertTrue(path.endswith(".pdf"))


class ApproveOrderTests(OrderTestMixin, TestCase):
    def test_approve_issues_invoice_and_changes_status(self):
        order = self.make_order()
        order.transition_to(OrderStatus.REVIEW)

        invoice = approve_order(order, comment="Проверено, наличие есть")

        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.INVOICED)
        self.assertEqual(order.invoices.current().get(), invoice)
        log = OrderStatusLog.objects.filter(order=order).order_by("-pk").first()
        self.assertEqual(log.to_status, OrderStatus.INVOICED)
        self.assertEqual(log.comment, "Проверено, наличие есть")

    def test_approve_writes_invoice_number_to_history_by_default(self):
        order = self.make_order()
        order.transition_to(OrderStatus.REVIEW)

        invoice = approve_order(order)

        log = OrderStatusLog.objects.filter(order=order).order_by("-pk").first()
        self.assertIn(invoice.number, log.comment)
        self.assertIn(f"v{invoice.version}", log.comment)

    def test_approve_is_forbidden_before_review(self):
        order = self.make_order()
        with self.assertRaises(InvoiceNotAllowed):
            approve_order(order)
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.NEW)
        self.assertFalse(Invoice.objects.filter(order=order).exists())

    def test_reapprove_creates_new_version_with_same_number(self):
        order = self.make_order()
        order.transition_to(OrderStatus.REVIEW)
        first = approve_order(order)

        # Менеджер поправил состав и выставляет счёт заново: номер тот же,
        # версия выше, старая версия остаётся в истории.
        second = Invoice.issue_for(order)

        self.assertEqual(second.number, first.number)
        self.assertEqual(second.version, 2)
        first.refresh_from_db()
        self.assertFalse(first.is_current)

    def test_approve_twice_on_same_order_is_rejected(self):
        order = self.make_order()
        order.transition_to(OrderStatus.REVIEW)
        approve_order(order)
        with self.assertRaises(InvoiceNotAllowed):
            approve_order(order)
        self.assertEqual(Invoice.objects.filter(order=order).count(), 1)

    def test_approve_rolls_back_invoice_when_status_change_fails(self):
        """Счёт и статус меняются вместе: сбой перехода откатывает и счёт."""
        from unittest import mock

        order = self.make_order()
        order.transition_to(OrderStatus.REVIEW)

        with mock.patch.object(
            Order,
            "transition_to",
            side_effect=InvalidTransition(OrderStatus.REVIEW, OrderStatus.INVOICED),
        ):
            with self.assertRaises(InvalidTransition):
                approve_order(order)

        self.assertFalse(Invoice.objects.filter(order=order).exists())
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.REVIEW)
