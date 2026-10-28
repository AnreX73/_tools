"""
companies/test_admin_lookup.py

Тесты JSON-подсказки реквизитов для админки и виджета ИНН.

Запуск: python manage.py test companies
"""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .dadata import DadataNotConfigured, DadataNotFound
from .lookup import LookupResult

LOOKUP_URL = reverse("admin_inn_lookup")

SBER_FIELDS = {
    "short_name": "ПАО СБЕРБАНК",
    "full_name": 'ПУБЛИЧНОЕ АКЦИОНЕРНОЕ ОБЩЕСТВО "СБЕРБАНК РОССИИ"',
    "legal_form": "pao",
    "inn": "7707083893",
    "kpp": "773601001",
    "ogrn": "1027700132195",
    "legal_address": "117312, г Москва, Академический р-н, ул Вавилова, д 19",
}


def make_result(**overrides) -> LookupResult:
    data = {
        "source": "dadata",
        "initial": dict(SBER_FIELDS),
        "notice": "Организация найдена в ЕГРЮЛ/ЕГРИП.",
    }
    data.update(overrides)
    return LookupResult(**data)


class InnLookupViewTests(TestCase):
    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.staff = user_model.objects.create_user(
            "manager", password="secret", is_staff=True
        )
        self.regular = user_model.objects.create_user("client", password="secret")
        self.client = Client()

    def test_anonymous_is_redirected_to_admin_login(self):
        response = self.client.post(LOOKUP_URL, {"inn": "7707083893"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_non_staff_is_redirected(self):
        self.client.force_login(self.regular)

        response = self.client.post(LOOKUP_URL, {"inn": "7707083893"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])

    def test_get_is_not_allowed(self):
        self.client.force_login(self.staff)

        self.assertEqual(self.client.get(LOOKUP_URL).status_code, 405)

    @mock.patch("companies.admin_views.lookup_requisites")
    def test_returns_fields(self, lookup):
        lookup.return_value = make_result()
        self.client.force_login(self.staff)

        response = self.client.post(
            LOOKUP_URL, {"inn": "7707083893", "kpp": "773601001"}
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["fields"], SBER_FIELDS)
        self.assertEqual(payload["source"], "dadata")
        self.assertEqual(payload["level"], "info")
        lookup.assert_called_once_with("7707083893", "773601001")

    @mock.patch("companies.admin_views.lookup_requisites")
    def test_spaces_in_inn_are_stripped(self, lookup):
        lookup.return_value = make_result()
        self.client.force_login(self.staff)

        self.client.post(LOOKUP_URL, {"inn": "7707 083 893"})

        lookup.assert_called_once_with("7707083893", "")

    @mock.patch("companies.admin_views.lookup_requisites")
    def test_invalid_inn_is_rejected(self, lookup):
        self.client.force_login(self.staff)

        response = self.client.post(LOOKUP_URL, {"inn": "7707083894"})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        lookup.assert_not_called()

    @mock.patch("companies.admin_views.lookup_requisites")
    def test_ip_with_kpp_is_rejected(self, lookup):
        self.client.force_login(self.staff)

        response = self.client.post(
            LOOKUP_URL, {"inn": "500100732259", "kpp": "773601001"}
        )

        self.assertEqual(response.status_code, 400)
        lookup.assert_not_called()

    @mock.patch("companies.admin_views.lookup_requisites")
    def test_not_found_returns_404(self, lookup):
        lookup.side_effect = DadataNotFound("нет организации")
        self.client.force_login(self.staff)

        response = self.client.post(LOOKUP_URL, {"inn": "7707083893"})

        self.assertEqual(response.status_code, 404)
        self.assertIn("не найдена", response.json()["error"])

    @mock.patch("companies.admin_views.lookup_requisites")
    def test_not_configured_returns_503(self, lookup):
        lookup.side_effect = DadataNotConfigured("нет ключа")
        self.client.force_login(self.staff)

        response = self.client.post(LOOKUP_URL, {"inn": "7707083893"})

        self.assertEqual(response.status_code, 503)
        self.assertIn("DADATA_API_KEY", response.json()["error"])

    @mock.patch("companies.admin_views.lookup_requisites")
    def test_multiple_kpp_returns_409(self, lookup):
        lookup.return_value = make_result(
            initial={},
            notice="Укажите КПП.",
            notice_level="warning",
            multiple_kpp=True,
        )
        self.client.force_login(self.staff)

        response = self.client.post(LOOKUP_URL, {"inn": "7707083893"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["level"], "warning")

    @override_settings(DADATA_ADMIN_RATE_LIMIT=1)
    @mock.patch("companies.admin_views.lookup_requisites")
    def test_rate_limit_returns_429(self, lookup):
        lookup.return_value = make_result()
        self.client.force_login(self.staff)

        first = self.client.post(LOOKUP_URL, {"inn": "7707083893"})
        second = self.client.post(LOOKUP_URL, {"inn": "7707083893"})

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second)
        self.assertEqual(lookup.call_count, 1)


class InnLookupWidgetTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_superuser(
            "root", "root@example.com", "secret"
        )
        self.client.force_login(self.admin)

    def assert_lookup_widget(self, url):
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Заполнить по ИНН")
        self.assertContains(response, 'data-inn-lookup')
        self.assertContains(response, f'data-url="{LOOKUP_URL}"')
        self.assertContains(response, "companies/admin/inn_lookup.js")
        self.assertContains(response, "companies/admin/inn_lookup.css")

    def test_legal_entity_form_has_lookup_widget(self):
        self.assert_lookup_widget(reverse("admin:companies_legalentity_add"))

    def test_seller_profile_form_has_lookup_widget(self):
        self.assert_lookup_widget(reverse("admin:companies_sellerprofile_add"))
