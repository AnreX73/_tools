"""
companies/test_dadata.py

Тесты клиента DaData и маппинга ответа. Сеть не используется: HTTP-вызовы
подменяются через ``unittest.mock``.
"""
from __future__ import annotations

from unittest import mock

import requests
from django.test import TestCase, override_settings

from .dadata import (
    DadataClient,
    DadataNotConfigured,
    DadataNotFound,
    DadataUnavailable,
    map_party,
)
from .models import LegalEntity


def party_payload(**data_overrides):
    """Ответ findById/party с одной организацией."""
    data = {
        "inn": "7707083893",
        "kpp": "773601001",
        "ogrn": "1027700132195",
        "type": "LEGAL",
        "name": {
            "short_with_opf": 'ПАО "СБЕРБАНК"',
            "full_with_opf": 'Публичное акционерное общество "СБЕРБАНК"',
        },
        "opf": {"short": "ПАО"},
        "address": {
            "value": "г Москва, ул Вавилова, д 19",
            "unrestricted_value": "119312, г Москва, ул Вавилова, д 19",
            "data": {"qc": 0},
        },
        "state": {"status": "ACTIVE"},
        "branch_type": "MAIN",
    }
    data.update(data_overrides)
    return {"suggestions": [{"value": "ПАО СБЕРБАНК", "data": data}]}


class PartyMappingTests(TestCase):
    def test_maps_legal_entity(self):
        party = map_party(party_payload()["suggestions"][0], "7707083893")

        self.assertEqual(party.short_name, 'ПАО "СБЕРБАНК"')
        self.assertEqual(
            party.full_name, 'Публичное акционерное общество "СБЕРБАНК"'
        )
        self.assertEqual(party.legal_form, LegalEntity.LegalForm.PAO)
        self.assertEqual(party.inn, "7707083893")
        self.assertEqual(party.kpp, "773601001")
        self.assertEqual(party.ogrn, "1027700132195")
        self.assertIn("Вавилова", party.legal_address)
        self.assertEqual(party.status, "ACTIVE")
        self.assertEqual(party.warnings, ())

    def test_maps_individual_entrepreneur(self):
        payload = party_payload(
            inn="500100732259",
            kpp="",
            ogrn="304500116000157",
            type="INDIVIDUAL",
            name={
                "short_with_opf": "ИП Иванов Иван Иванович",
                "full_with_opf": "Индивидуальный предприниматель Иванов Иван Иванович",
            },
            opf={"short": "ИП"},
        )
        party = map_party(payload["suggestions"][0], "500100732259")

        self.assertEqual(party.legal_form, LegalEntity.LegalForm.IP)
        self.assertEqual(party.kpp, "")
        self.assertEqual(party.ogrn, "304500116000157")

    def test_maps_other_legal_forms(self):
        cases = {
            "ООО": LegalEntity.LegalForm.OOO,
            "АО": LegalEntity.LegalForm.AO,
            "ЗАО": LegalEntity.LegalForm.AO,
            "ПАО": LegalEntity.LegalForm.PAO,
            "ФГУП": LegalEntity.LegalForm.OTHER,
        }
        for opf_short, expected in cases.items():
            with self.subTest(opf=opf_short):
                payload = party_payload(opf={"short": opf_short})
                party = map_party(payload["suggestions"][0], "7707083893")
                self.assertEqual(party.legal_form, expected)

    def test_warns_about_bad_status_and_invalid_data(self):
        payload = party_payload(
            state={"status": "LIQUIDATED"},
            invalid=True,
            address={
                "unrestricted_value": "адрес",
                "data": {"qc": 1},
            },
        )
        party = map_party(payload["suggestions"][0], "7707083893")

        self.assertTrue(party.is_invalid)
        self.assertIn("ликвидирована", " ".join(party.warnings))
        self.assertIn("недостоверных", " ".join(party.warnings))
        self.assertIn("ручной проверки", " ".join(party.warnings))

    def test_missing_data_raises_not_found(self):
        with self.assertRaises(DadataNotFound):
            map_party({"value": "без data", "data": {}})

    def test_to_form_initial_has_no_contacts_or_bank_fields(self):
        party = map_party(party_payload()["suggestions"][0], "7707083893")
        initial = party.to_form_initial()

        self.assertEqual(
            set(initial),
            {
                "short_name",
                "full_name",
                "legal_form",
                "inn",
                "kpp",
                "ogrn",
                "legal_address",
            },
        )


@override_settings(
    DADATA_API_KEY="test-key",
    DADATA_SECRET_KEY="",
    DADATA_TIMEOUT=3,
    DADATA_SUGGEST_URL="https://example.test/find",
)
class DadataClientTests(TestCase):
    def _response(self, payload, status_code: int = 200):
        response = mock.Mock(status_code=status_code)
        response.json.return_value = payload
        return response

    def test_request_without_kpp_asks_for_main_branch(self):
        response = self._response(party_payload())
        with mock.patch(
            "companies.dadata.requests.post", return_value=response
        ) as post:
            party = DadataClient().find_party("7707083893")

        kwargs = post.call_args.kwargs
        self.assertEqual(
            kwargs["json"], {"query": "7707083893", "branch_type": "MAIN"}
        )
        self.assertEqual(
            kwargs["headers"]["Authorization"], "Token test-key"
        )
        self.assertNotIn("X-Secret", kwargs["headers"])
        self.assertEqual(kwargs["timeout"], 3.0)
        self.assertEqual(party.kpp, "773601001")

    def test_request_with_kpp_searches_branch(self):
        kpp = "773601001"
        response = self._response(party_payload())
        with mock.patch(
            "companies.dadata.requests.post", return_value=response
        ) as post:
            DadataClient().find_party("7707083893", kpp)

        self.assertEqual(
            post.call_args.kwargs["json"],
            {"query": "7707083893", "kpp": kpp},
        )

    @override_settings(DADATA_SECRET_KEY="secret-key")
    def test_secret_key_is_sent_only_when_configured(self):
        response = self._response(party_payload())
        with mock.patch(
            "companies.dadata.requests.post", return_value=response
        ) as post:
            DadataClient().find_party("7707083893")

        self.assertEqual(
            post.call_args.kwargs["headers"]["X-Secret"], "secret-key"
        )

    def test_chooses_matching_kpp(self):
        payload = party_payload()
        branch = party_payload(
            kpp="540602001",
            branch_type="BRANCH",
            name={
                "short_with_opf": "Филиал",
                "full_with_opf": "Филиал организации",
            },
        )
        payload["suggestions"].append(branch["suggestions"][0])
        response = self._response(payload)

        with mock.patch(
            "companies.dadata.requests.post", return_value=response
        ):
            party = DadataClient().find_party("7707083893", "540602001")

        self.assertEqual(party.kpp, "540602001")
        self.assertEqual(party.short_name, "Филиал")

    def test_empty_suggestions_raise_not_found(self):
        response = self._response({"suggestions": []})
        with mock.patch(
            "companies.dadata.requests.post", return_value=response
        ):
            with self.assertRaises(DadataNotFound):
                DadataClient().find_party("7707083893")

    def test_http_error_raises_unavailable(self):
        response = self._response({}, status_code=500)
        with mock.patch(
            "companies.dadata.requests.post", return_value=response
        ):
            with self.assertRaises(DadataUnavailable):
                DadataClient().find_party("7707083893")

    def test_malformed_json_raises_unavailable(self):
        response = mock.Mock(status_code=200)
        response.json.side_effect = ValueError("bad json")
        with mock.patch(
            "companies.dadata.requests.post", return_value=response
        ):
            with self.assertRaises(DadataUnavailable):
                DadataClient().find_party("7707083893")

    def test_network_error_raises_unavailable(self):
        with mock.patch(
            "companies.dadata.requests.post",
            side_effect=requests.Timeout("timeout"),
        ):
            with self.assertRaises(DadataUnavailable):
                DadataClient().find_party("7707083893")

    @override_settings(DADATA_API_KEY="")
    def test_missing_key_raises_not_configured(self):
        with mock.patch("companies.dadata.requests.post") as post:
            with self.assertRaises(DadataNotConfigured):
                DadataClient().find_party("7707083893")

        post.assert_not_called()
