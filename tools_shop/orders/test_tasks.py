"""
orders/test_tasks.py

Проверка писем этапа 4: уведомление менеджеров и подтверждение покупателю.
"""
from __future__ import annotations

import shutil
import tempfile
from decimal import Decimal
from unittest import mock
from uuid import uuid4

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from companies.models import LegalEntity
from shop.models import Category, Product

from .models import Invoice, Order, OrderItem
from .pdf import InvoicePDFError
from .statuses import OrderStatus
from .tasks import (
    generate_and_send_invoice,
    notify_managers,
    send_order_accepted_email,
)


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

    def setUp(self):
        self.media_dir = tempfile.mkdtemp(prefix="orders-media-")
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)

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

    def test_notify_managers_sends_email_with_admin_link(self):
        order = self.make_order()
        sent = notify_managers(order.pk)
        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["manager@example.ru", "sales@example.ru"])
        self.assertIn(order.number, message.subject)
        self.assertIn(reverse("orders:detail", args=[order.uuid]), message.body)
        self.assertIn(
            reverse("admin:orders_order_change", args=[order.pk]),
            message.body,
        )

    def test_notify_managers_accepts_order_object(self):
        order = self.make_order()
        self.assertEqual(notify_managers(order), 1)
        self.assertEqual(len(mail.outbox), 1)

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

    def make_invoice(self) -> Invoice:
        order = self.make_order()
        return Invoice.issue_for(order)

    def test_generate_and_send_invoice_attaches_pdf_and_marks_sent(self):
        invoice = self.make_invoice()
        with mock.patch(
            "orders.tasks.render_invoice_pdf",
            return_value=b"%PDF-1.4 invoice",
        ):
            sent = generate_and_send_invoice(invoice.pk)

        self.assertEqual(sent, 1)
        invoice.refresh_from_db()
        self.assertIsNotNone(invoice.sent_at)
        self.assertTrue(invoice.pdf.name.endswith(".pdf"))
        self.assertEqual(invoice.pdf.read(), b"%PDF-1.4 invoice")

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["buyer@example.ru"])
        self.assertIn(invoice.number, message.subject)
        self.assertEqual(len(message.attachments), 1)
        filename, content, mimetype = message.attachments[0]
        self.assertTrue(filename.endswith(".pdf"))
        self.assertEqual(content, b"%PDF-1.4 invoice")
        self.assertEqual(mimetype, "application/pdf")

    def test_generate_and_send_invoice_is_idempotent(self):
        invoice = self.make_invoice()
        invoice.sent_at = timezone.now()
        invoice.save(update_fields=["sent_at"])

        with mock.patch("orders.tasks.render_invoice_pdf") as render:
            sent = generate_and_send_invoice(invoice.pk)

        self.assertEqual(sent, 0)
        render.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    def test_old_invoice_version_is_not_sent(self):
        first = self.make_invoice()
        Invoice.issue_for(first.order)
        first.refresh_from_db()
        self.assertFalse(first.is_current)

        with mock.patch("orders.tasks.render_invoice_pdf") as render:
            sent = generate_and_send_invoice(first.pk)

        self.assertEqual(sent, 0)
        render.assert_not_called()
        self.assertEqual(len(mail.outbox), 0)

    def test_pdf_failure_propagates_for_retry_and_keeps_unsent(self):
        invoice = self.make_invoice()
        with mock.patch(
            "orders.tasks.render_invoice_pdf",
            side_effect=InvoicePDFError("PDF broken"),
        ):
            with self.assertRaises(InvoicePDFError):
                generate_and_send_invoice(invoice.pk)

        invoice.refresh_from_db()
        self.assertIsNone(invoice.sent_at)
        self.assertFalse(invoice.pdf)
        self.assertEqual(len(mail.outbox), 0)

    def test_missing_invoice_is_ignored(self):
        with mock.patch("orders.tasks.logger.warning") as warning:
            self.assertEqual(generate_and_send_invoice(999_999), 0)
            warning.assert_called_once()
