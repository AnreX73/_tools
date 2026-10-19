"""
companies/tests.py

Тесты валидатора ИНН, нормализации и ограничений LegalEntity.

Запуск: python manage.py test companies
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from .models import CompanyUser, LegalEntity
from .validators import is_valid_inn, validate_inn

# Реальные ИНН с корректной контрольной суммой (используются только в тестах).
VALID_INN_10 = [
    "7707083893",  # ПАО Сбербанк
    "7736050003",  # ПАО Газпром
    "7736207543",
    "5001007329",
    "5024002119",
]
VALID_INN_12 = [
    "500100732259",  # ИП
    "772816897110",
    "770708389324",
    "773605000380",
]
INVALID_INN_10 = [
    "7707083894",  # последняя цифра неверна
    "7736050004",
    "1234567890",  # контрольная сумма не сходится
]
INVALID_INN_12 = [
    "500100732258",  # 12-я цифра неверна
    "500100732159",  # 11-я цифра неверна
    "772816897111",
    "772816897114",
    "770708389300",
]


class ValidateInnTests(TestCase):
    """Проверка контрольной суммы ИНН (10 и 12 цифр)."""

    def test_valid_inn_10(self):
        for inn in VALID_INN_10:
            with self.subTest(inn=inn):
                self.assertTrue(is_valid_inn(inn))
                validate_inn(inn)  # не бросает

    def test_valid_inn_12(self):
        for inn in VALID_INN_12:
            with self.subTest(inn=inn):
                self.assertTrue(is_valid_inn(inn))
                validate_inn(inn)

    def test_invalid_checksum_10(self):
        for inn in INVALID_INN_10:
            with self.subTest(inn=inn):
                self.assertFalse(is_valid_inn(inn))
                with self.assertRaises(ValidationError) as ctx:
                    validate_inn(inn)
                self.assertEqual(ctx.exception.code, "invalid_inn")

    def test_invalid_checksum_12(self):
        for inn in INVALID_INN_12:
            with self.subTest(inn=inn):
                self.assertFalse(is_valid_inn(inn))
                with self.assertRaises(ValidationError):
                    validate_inn(inn)

    def test_wrong_length(self):
        for inn in ("", "1", "123456789", "12345678901", "1234567890123"):
            with self.subTest(inn=inn):
                self.assertFalse(is_valid_inn(inn))

    def test_non_digits(self):
        for inn in ("77070838 3", "770708389a", "７７０７０８３８９３"):
            with self.subTest(inn=inn):
                self.assertFalse(is_valid_inn(inn))

    def test_all_zero_inn_is_invalid(self):
        self.assertFalse(is_valid_inn("0000000000"))
        self.assertFalse(is_valid_inn("000000000000"))

    def test_validate_inn_allows_empty(self):
        """Пустое значение пропускается: обязательность задаёт поле формы."""
        validate_inn("")

    def test_whitespace_is_stripped(self):
        self.assertTrue(is_valid_inn("  7707083893  "))


class LegalEntityCleanTests(TestCase):
    """clean(): обязательность КПП для 10-значного ИНН и нормализация."""

    def _entity(self, **kwargs) -> LegalEntity:
        data = {
            "full_name": 'ООО "Тестовая компания"',
            "short_name": 'ООО "Тест"',
            "legal_form": LegalEntity.LegalForm.OOO,
            "inn": "7707083893",
            "kpp": "770701001",
            "legal_address": "г. Москва, ул. Тестовая, д. 1",
        }
        data.update(kwargs)
        return LegalEntity(**data)

    def test_legal_entity_inn_requires_kpp(self):
        entity = self._entity(kpp="")
        with self.assertRaises(ValidationError) as ctx:
            entity.full_clean()
        self.assertIn("kpp", ctx.exception.message_dict)

    def test_legal_entity_inn_with_kpp_is_valid(self):
        entity = self._entity()
        entity.full_clean()  # не бросает
        self.assertEqual(entity.inn, "7707083893")
        self.assertEqual(entity.kpp, "770701001")

    def test_entrepreneur_inn_without_kpp_is_valid(self):
        entity = self._entity(
            inn="500100732259",
            kpp="",
            legal_form=LegalEntity.LegalForm.IP,
        )
        entity.full_clean()
        self.assertEqual(entity.kpp, "")

    def test_entrepreneur_inn_with_kpp_is_valid(self):
        """КПП у ИП не обязателен, но если указан — не мешает."""
        entity = self._entity(inn="500100732259", kpp="770701001")
        entity.full_clean()

    def test_clean_normalizes_whitespace(self):
        entity = self._entity(inn="  7707083893 ", kpp=" 770701001 ")
        entity.full_clean()
        self.assertEqual(entity.inn, "7707083893")
        self.assertEqual(entity.kpp, "770701001")

    def test_clean_normalizes_none_kpp_to_empty_string(self):
        entity = self._entity(inn="500100732259", kpp=None)
        entity.full_clean()
        self.assertEqual(entity.kpp, "")

    def test_invalid_inn_fails_full_clean(self):
        entity = self._entity(inn="7707083894")
        with self.assertRaises(ValidationError) as ctx:
            entity.full_clean()
        self.assertIn("inn", ctx.exception.message_dict)

    def test_defaults(self):
        entity = self._entity(inn="500100732259", kpp="")
        self.assertFalse(entity.is_verified)
        self.assertTrue(entity.is_active)


class LegalEntityConstraintTests(TestCase):
    """UniqueConstraint(inn, kpp): ИНН может повторяться при разных КПП."""

    def _create(self, inn: str, kpp: str, name: str = 'ООО "Тест"') -> LegalEntity:
        return LegalEntity.objects.create(
            full_name=f'ООО "{name}"',
            short_name=name,
            legal_form=LegalEntity.LegalForm.OOO,
            inn=inn,
            kpp=kpp,
            legal_address="г. Москва",
        )

    def test_same_inn_with_different_kpp_is_allowed(self):
        self._create("7707083893", "770701001", "Филиал 1")
        self._create("7707083893", "770701002", "Филиал 2")
        self.assertEqual(LegalEntity.objects.filter(inn="7707083893").count(), 2)

    def test_same_inn_and_kpp_is_rejected(self):
        self._create("7707083893", "770701001", "Первая")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create("7707083893", "770701001", "Вторая")

    def test_two_entrepreneurs_with_same_inn_and_empty_kpp_rejected(self):
        self._create("500100732259", "", "ИП Первый")
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._create("500100732259", "", "ИП Второй")


class CompanyUserConfirmedAtTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = LegalEntity.objects.create(
            full_name='ООО "Тест"',
            short_name="Тест",
            inn="500100732259",
            kpp="",
            legal_address="г. Москва",
        )
        cls.user = get_user_model().objects.create_user(
            username="buyer", password="test-pass-123"
        )

    def test_confirmed_at_is_null_by_default(self):
        membership = CompanyUser.objects.create(company=self.company, user=self.user)
        self.assertIsNone(membership.confirmed_at)

    def test_confirmed_at_can_be_set(self):
        now = timezone.now()
        membership = CompanyUser.objects.create(
            company=self.company, user=self.user, confirmed_at=now
        )
        membership.refresh_from_db()
        self.assertEqual(membership.confirmed_at, now)

    def test_field_is_nullable(self):
        field = CompanyUser._meta.get_field("confirmed_at")
        self.assertTrue(field.null)
        self.assertTrue(field.blank)
