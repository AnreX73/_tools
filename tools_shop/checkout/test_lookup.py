"""
checkout/test_lookup.py

Тесты подстановки реквизитов: база -> DaData и htmx-вьюха.
"""
from __future__ import annotations

from unittest import mock

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from companies.dadata import (
    DadataNotFound,
    DadataUnavailable,
    PartyRequisites,
)
from companies.models import LegalEntity

from .lookup import lookup_requisites

LOOKUP_URL = reverse("checkout:suggest_by_inn")


def make_company(
    *,
    inn: str = "7707083893",
    kpp: str = "773601001",
    short_name: str = 'ООО "Ромашка"',
    verified: bool = True,
    **overrides,
) -> LegalEntity:
    data = {
        "full_name": 'Общество с ограниченной ответственностью "Ромашка"',
        "short_name": short_name,
        "legal_form": LegalEntity.LegalForm.OOO,
        "inn": inn,
        "kpp": kpp,
        "ogrn": "1027700132195",
        "legal_address": "г. Москва, ул. Тверская, д. 1",
        "email": "secret@example.ru",
        "phone": "+7 999 111-22-33",
        "bank_name": "ПАО Секретный банк",
        "bik": "044525225",
        "correspondent_account": "30101810400000000225",
        "checking_account": "40702810400000000001",
        "is_verified": verified,
    }
    data.update(overrides)
    return LegalEntity.objects.create(**data)


def party(
    *,
    inn: str = "7736050003",
    kpp: str = "773601001",
    short_name: str = 'ПАО "Газпром"',
    legal_form: str = LegalEntity.LegalForm.PAO,
    warnings: tuple[str, ...] = (),
) -> PartyRequisites:
    return PartyRequisites(
        short_name=short_name,
        full_name='Публичное акционерное общество "Газпром"',
        legal_form=legal_form,
        inn=inn,
        kpp=kpp,
        ogrn="1027700070518",
        legal_address="г. Москва, ул. Наметкина, д. 16",
        warnings=warnings,
    )


class LookupServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_existing_company_is_loaded_from_database(self):
        company = make_company()

        with mock.patch("checkout.lookup.DadataClient.find_party") as find:
            result = lookup_requisites("7707083893", "773601001")

        find.assert_not_called()
        self.assertEqual(result.source, "db")
        self.assertTrue(result.is_verified)
        self.assertEqual(result.initial["short_name"], company.short_name)
        self.assertEqual(result.initial["ogrn"], "1027700132195")
        self.assertNotIn("email", result.initial)
        self.assertNotIn("phone", result.initial)
        self.assertNotIn("checking_account", result.initial)

    def test_company_without_kpp_is_found_when_one(self):
        company = make_company(kpp="773601001")

        result = lookup_requisites("7707083893")

        self.assertEqual(result.source, "db")
        self.assertEqual(result.initial["kpp"], company.kpp)

    def test_multiple_kpp_requires_user_choice(self):
        make_company(kpp="773601001", short_name="Головная")
        make_company(kpp="773601002", short_name="Филиал")

        with mock.patch("checkout.lookup.DadataClient.find_party") as find:
            result = lookup_requisites("7707083893")

        find.assert_not_called()
        self.assertTrue(result.multiple_kpp)
        self.assertEqual(result.initial, {})
        self.assertIn("КПП", result.notice)

    def test_exact_kpp_selects_branch(self):
        make_company(kpp="773601001", short_name="Головная")
        make_company(kpp="773601002", short_name="Филиал")

        result = lookup_requisites("7707083893", "773601002")

        self.assertEqual(result.source, "db")
        self.assertEqual(result.initial["short_name"], "Филиал")
        self.assertEqual(result.initial["kpp"], "773601002")

    def test_new_company_uses_dadata(self):
        with mock.patch(
            "checkout.lookup.DadataClient.find_party",
            return_value=party(warnings=("Статус в ЕГРЮЛ: ликвидируется.",)),
        ) as find:
            result = lookup_requisites("7736050003", "773601001")

        find.assert_called_once_with("7736050003", "773601001")
        self.assertEqual(result.source, "dadata")
        self.assertEqual(result.initial["short_name"], 'ПАО "Газпром"')
        self.assertEqual(result.initial["legal_form"], LegalEntity.LegalForm.PAO)
        self.assertEqual(result.notice_level, "warning")
        self.assertIn("ЕГРЮЛ", result.notice)

    def test_successful_dadata_response_is_cached(self):
        with mock.patch(
            "checkout.lookup.DadataClient.find_party",
            return_value=party(),
        ) as find:
            first = lookup_requisites("7736050003", "773601001")
            second = lookup_requisites("7736050003", "773601001")

        find.assert_called_once()
        self.assertEqual(first.initial, second.initial)


class SuggestByInnViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_existing_company_is_rendered_without_contacts(self):
        company = make_company()

        with mock.patch("checkout.lookup.DadataClient.find_party") as find:
            response = self.client.post(
                LOOKUP_URL,
                {"inn": "7707083893", "kpp": "773601001"},
            )

        find.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="organization-fields"')
        self.assertContains(response, "проверенной карточки")
        self.assertEqual(
            response.context["form"]["short_name"].value(), company.short_name
        )
        self.assertNotContains(response, company.email)
        self.assertNotContains(response, company.phone)
        self.assertNotContains(response, company.bank_name)

    def test_dadata_result_fills_form(self):
        with mock.patch(
            "checkout.lookup.DadataClient.find_party",
            return_value=party(),
        ):
            response = self.client.post(
                LOOKUP_URL,
                {"inn": "7736050003", "kpp": "773601001"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ЕГРЮЛ")
        self.assertEqual(
            response.context["form"]["short_name"].value(), 'ПАО "Газпром"'
        )
        self.assertEqual(
            response.context["form"]["ogrn"].value(), "1027700070518"
        )

    @override_settings(DADATA_RATE_LIMIT=10, DADATA_RATE_WINDOW=60)
    def test_invalid_inn_does_not_call_dadata(self):
        with mock.patch("checkout.lookup.DadataClient.find_party") as find:
            response = self.client.post(LOOKUP_URL, {"inn": "7707083894"})

        find.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Retarget"], "#inn-suggest")
        self.assertContains(response, "Проверьте ИНН")

    def test_invalid_kpp_is_reported(self):
        response = self.client.post(
            LOOKUP_URL,
            {"inn": "7707083893", "kpp": "123"},
        )

        self.assertEqual(response["HX-Retarget"], "#inn-suggest")
        self.assertContains(response, "КПП")

    def test_ip_with_kpp_is_rejected(self):
        response = self.client.post(
            LOOKUP_URL,
            {"inn": "500100732259", "kpp": "773601001"},
        )

        self.assertEqual(response["HX-Retarget"], "#inn-suggest")
        self.assertContains(response, "КПП не заполняется")

    def test_unavailable_dadata_keeps_form_manual(self):
        with mock.patch(
            "checkout.lookup.DadataClient.find_party",
            side_effect=DadataUnavailable("down"),
        ):
            response = self.client.post(
                LOOKUP_URL,
                {"inn": "7736050003", "kpp": "773601001"},
            )

        self.assertEqual(response["HX-Retarget"], "#inn-suggest")
        self.assertContains(response, "временно недоступен")

    def test_not_found_is_reported(self):
        with mock.patch(
            "checkout.lookup.DadataClient.find_party",
            side_effect=DadataNotFound("not found"),
        ):
            response = self.client.post(
                LOOKUP_URL,
                {"inn": "7736050003", "kpp": "773601001"},
            )

        self.assertEqual(response["HX-Retarget"], "#inn-suggest")
        self.assertContains(response, "не найдена")

    def test_multiple_kpp_asks_for_kpp(self):
        make_company(kpp="773601001", short_name="Головная")
        make_company(kpp="773601002", short_name="Филиал")

        response = self.client.post(LOOKUP_URL, {"inn": "7707083893"})

        self.assertEqual(response["HX-Retarget"], "#inn-suggest")
        self.assertContains(response, "несколько организаций")
        self.assertContains(response, "Укажите КПП")

    @override_settings(DADATA_RATE_LIMIT=1, DADATA_RATE_WINDOW=60)
    def test_rate_limit_is_applied(self):
        make_company()

        first = self.client.post(
            LOOKUP_URL, {"inn": "7707083893", "kpp": "773601001"}
        )
        second = self.client.post(
            LOOKUP_URL, {"inn": "7707083893", "kpp": "773601001"}
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "Слишком много запросов")
        self.assertEqual(second["Retry-After"], "60")

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(LOOKUP_URL, {"inn": "7707083893"})

        self.assertEqual(response.status_code, 403)
