"""
orders/test_pdf.py

Проверка HTML-шаблона счёта: экранирование пользовательских данных и
фактическая генерация PDF через WeasyPrint (если системные библиотеки есть).
"""
from __future__ import annotations

from decimal import Decimal
from unittest import mock, skipUnless
from uuid import uuid4

from django.test import TestCase, override_settings

from companies.models import LegalEntity, SellerProfile
from shop.models import Category, Product

from .models import Invoice, Order, OrderItem
from .pdf import InvoicePDFError, render_invoice_pdf
from .statuses import OrderStatus


def _weasyprint_available() -> bool:
    try:
        from weasyprint import HTML  # noqa: F401

        return True
    except Exception:  # noqa: BLE001 - на Windows без GTK это OSError
        return False


@override_settings(
    SELLER_REQUISITES={
        "name": "ООО «Тестовый продавец»",
        "full_name": "Общество с ограниченной ответственностью «Тестовый продавец»",
        "inn": "7700000000",
        "kpp": "770001001",
        "ogrn": "1027700132195",
        "address": "г. Москва, ул. Тестовая, д. 1",
        "phone": "+7 (495) 111-22-33",
        "email": "seller@example.ru",
        "bank_name": "ПАО «Тест-Банк»",
        "bik": "044525225",
        "correspondent_account": "30101810400000000225",
        "checking_account": "40702810400000000001",
        "director": "Иванов И. И.",
    }
)
class InvoicePDFTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        root = Category.objects.add_root(create_kwargs={"name": "Инструмент"})
        leaf = Category.objects.add_child(root, create_kwargs={"name": "Свёрла"})
        cls.product = Product.objects.create(
            sku="PDF-1",
            name="Сверло 12 мм",
            category=leaf,
            price=Decimal("300.00"),
            is_active=True,
            attributes={},
        )

    def make_invoice(self) -> Invoice:
        company = LegalEntity.objects.create(
            full_name='ООО "Покупатель"',
            short_name='ООО "Покупатель"',
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
            requisites_snapshot={
                "short_name": '<script>alert("x")</script>',
                "full_name": 'ООО "Покупатель"',
                "inn": "7707083893",
                "kpp": "773601001",
                "legal_form": LegalEntity.LegalForm.OOO,
                "legal_address": "г. Москва",
            },
            status=OrderStatus.REVIEW,
            idempotency_key=uuid4(),
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            name='<b>Сверло</b> "12"',
            sku=self.product.sku,
            price=self.product.price,
            qty=2,
        )
        return Invoice.issue_for(order)

    def test_template_escapes_user_data_and_contains_requisites(self):
        invoice = self.make_invoice()
        html_class = mock.Mock()
        html_class.return_value.write_pdf.return_value = b"%PDF-1.4 test"

        with mock.patch("orders.pdf._html_class", return_value=html_class):
            result = render_invoice_pdf(invoice)

        self.assertEqual(result, b"%PDF-1.4 test")
        html = html_class.call_args.kwargs["string"]
        self.assertIn("&lt;script&gt;alert", html)
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIn("&lt;b&gt;Сверло&lt;/b&gt;", html)
        self.assertIn("ООО «Тестовый продавец»", html)
        self.assertIn("ОГРН 1027700132195", html)
        self.assertIn(invoice.number, html)
        self.assertIn(invoice.order.number, html)
        self.assertIn("600,00", html)

    def test_invoice_snapshots_seller_at_issue(self):
        invoice = self.make_invoice()

        self.assertEqual(
            invoice.seller_snapshot["short_name"], "ООО «Тестовый продавец»"
        )
        self.assertEqual(invoice.seller_snapshot["ogrn"], "1027700132195")

    def test_old_invoice_keeps_seller_snapshot(self):
        invoice = self.make_invoice()

        SellerProfile.objects.create(
            short_name="ООО «Новый продавец»",
            full_name="Общество с ограниченной ответственностью «Новый продавец»",
            inn="7707083893",
            kpp="773601001",
            legal_address="г. Москва, ул. Новая, д. 2",
        )

        html_class = mock.Mock()
        html_class.return_value.write_pdf.return_value = b"%PDF-1.4 old"
        with mock.patch("orders.pdf._html_class", return_value=html_class):
            render_invoice_pdf(invoice)

        html = html_class.call_args.kwargs["string"]
        self.assertIn("ООО «Тестовый продавец»", html)
        self.assertNotIn("ООО «Новый продавец»", html)

    @override_settings(SELLER_REQUISITES={})
    def test_missing_seller_raises_before_pdf(self):
        invoice = self.make_invoice()

        with self.assertRaises(InvoicePDFError) as ctx:
            render_invoice_pdf(invoice)
        self.assertIn("Реквизиты продавца", str(ctx.exception))

    def test_weasyprint_failure_is_wrapped(self):
        invoice = self.make_invoice()
        with mock.patch("orders.pdf._html_class", side_effect=OSError("no pango")):
            with self.assertRaises(InvoicePDFError) as ctx:
                render_invoice_pdf(invoice)
        self.assertIn("WeasyPrint", str(ctx.exception))

    @skipUnless(
        _weasyprint_available(),
        "WeasyPrint/GTK/Pango недоступны в этом окружении",
    )
    def test_real_weasyprint_pdf(self):
        invoice = self.make_invoice()
        pdf = render_invoice_pdf(invoice)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertGreater(len(pdf), 1000)
