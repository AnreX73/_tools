"""
companies/test_seller.py

Реквизиты продавца: singleton-профиль, fallback на настройки и попадание
данных в публичные страницы.
"""
from __future__ import annotations

from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from .context_processors import seller as seller_context
from .models import SellerProfile
from .seller import get_seller, is_seller_configured


def make_seller(**overrides) -> SellerProfile:
    data = {
        "legal_form": "ooo",
        "short_name": "ООО «Тестовый продавец»",
        "full_name": "Общество с ограниченной ответственностью «Тестовый продавец»",
        "inn": "7707083893",
        "kpp": "773601001",
        "ogrn": "1027700132195",
        "legal_address": "г. Москва, ул. Тестовая, д. 1",
        "phone": "+7 (495) 111-22-33",
        "email": "seller@example.ru",
        "website": "https://seller.example.ru",
        "bank_name": "ПАО «Тест-Банк»",
        "bik": "044525225",
        "correspondent_account": "30101810400000000225",
        "checking_account": "40702810400000000001",
        "director_name": "Иванов И. И.",
    }
    data.update(overrides)
    return SellerProfile.objects.create(**data)


class SellerProfileModelTests(TestCase):
    def test_only_one_active_profile(self):
        first = make_seller()
        second = make_seller(short_name="ООО «Новый продавец»")

        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(SellerProfile.get_active(), second)

    def test_snapshot_contains_all_fields(self):
        seller = make_seller()
        snapshot = seller.as_snapshot()

        self.assertEqual(snapshot["short_name"], "ООО «Тестовый продавец»")
        self.assertEqual(snapshot["inn"], "7707083893")
        self.assertEqual(snapshot["ogrn"], "1027700132195")
        self.assertEqual(snapshot["director_name"], "Иванов И. И.")

    def test_ten_digit_inn_requires_kpp(self):
        seller = make_seller()
        seller.kpp = ""
        with self.assertRaises(ValidationError) as ctx:
            seller.full_clean()
        self.assertIn("kpp", ctx.exception.message_dict)

    def test_twelve_digit_inn_forbids_kpp(self):
        seller = SellerProfile(
            short_name="ИП Тестов",
            full_name="Индивидуальный предприниматель Тестов",
            inn="500100732259",
            kpp="773601001",
            legal_address="г. Москва",
        )
        with self.assertRaises(ValidationError) as ctx:
            seller.full_clean()
        self.assertIn("kpp", ctx.exception.message_dict)

    def test_partial_bank_details_are_rejected(self):
        seller = make_seller(checking_account="")
        with self.assertRaises(ValidationError) as ctx:
            seller.full_clean()
        self.assertIn("__all__", ctx.exception.message_dict)


class SellerResolutionTests(TestCase):
    def test_database_profile_wins_over_settings(self):
        make_seller()
        with override_settings(
            SELLER_REQUISITES={"name": "Из настроек", "inn": "7707083893"}
        ):
            self.assertEqual(get_seller()["short_name"], "ООО «Тестовый продавец»")

    @override_settings(
        SELLER_REQUISITES={
            "name": "ООО «Из настроек»",
            "inn": "7707083893",
            "address": "г. Москва",
        }
    )
    def test_settings_are_fallback(self):
        seller = get_seller()
        self.assertEqual(seller["short_name"], "ООО «Из настроек»")
        self.assertEqual(seller["legal_address"], "г. Москва")
        self.assertTrue(is_seller_configured(seller))

    @override_settings(SELLER_REQUISITES={})
    def test_empty_settings_are_not_configured(self):
        self.assertFalse(is_seller_configured(get_seller()))


class SellerContextTests(TestCase):
    def test_site_page_gets_seller_context(self):
        make_seller()
        response = self.client.get(reverse("shop:index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["seller"]["short_name"], "ООО «Тестовый продавец»"
        )
        self.assertContains(response, "ООО «Тестовый продавец»")
        # Реквизиты больше не дублируются в подвале — они внутри юр. документов.
        self.assertNotContains(response, "ИНН 7707083893")

    def test_admin_and_htmx_do_not_query_seller(self):
        factory = RequestFactory()
        self.assertEqual(seller_context(factory.get("/admin/")), {})

        request = factory.get("/", HTTP_HX_REQUEST="true")
        self.assertEqual(seller_context(request), {})

    def test_footer_has_legal_link_without_requisites(self):
        make_seller()
        response = self.client.get(reverse("shop:index"))

        self.assertContains(response, reverse("shop:legal"))
        self.assertContains(response, "Правовая информация")
        self.assertNotContains(response, "7707083893")
        self.assertNotContains(response, "г. Москва, ул. Тестовая, д. 1")


class LegalPageTests(TestCase):
    def test_offer_and_privacy_show_seller(self):
        make_seller()

        for tab in ("offer", "privacy"):
            with self.subTest(tab=tab):
                response = self.client.get(reverse("shop:legal"), {"tab": tab})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "ООО «Тестовый продавец»")
                self.assertContains(response, "7707083893")
