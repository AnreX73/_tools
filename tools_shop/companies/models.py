"""
companies/models.py

Модель юридического лица для B2B проекта.
"""
from __future__ import annotations

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class LegalEntity(models.Model):
    """
    Юридическое лицо (организация-клиент).
    Одно юридическое лицо может иметь несколько контактных лиц (users).
    """
    class LegalForm(models.TextChoices):
        OOO = "ooo", "ООО"  # type: ignore[assignment]
        AO = "ao", "АО"  # type: ignore[assignment]
        PAO = "pao", "ПАО"  # type: ignore[assignment]
        IP = "ip", "ИП"  # type: ignore[assignment]
        OTHER = "other", "Другое"  # type: ignore[assignment]

    # ---- основные реквизиты ----
    full_name = models.CharField(
        "Полное наименование",
        max_length=512,
        help_text='Например: ООО "Производственная компания ИНСТРУМЕНТ"'
    )
    short_name = models.CharField(
        "Краткое наименование",
        max_length=255,
        help_text='Например: ООО "ПК ИНСТРУМЕНТ"'
    )
    legal_form = models.CharField(
        "Организационно-правовая форма",
        max_length=16,
        choices=LegalForm.choices,
        default=LegalForm.OOO
    )

    # ---- ИНН, КПП, ОГРН ----
    inn_validator = RegexValidator(
        r"^\d{10}(\d{2})?$",
        "ИНН должен содержать 10 цифр (юрлицо) или 12 цифр (ИП)"
    )
    inn = models.CharField(
        "ИНН",
        max_length=12,
        unique=True,
        validators=[inn_validator],
        help_text="10 или 12 цифр"
    )
    kpp = models.CharField(
        "КПП",
        max_length=9,
        blank=True,
        validators=[RegexValidator(r"^\d{9}$", "КПП должен содержать 9 цифр")],
        help_text="9 цифр (для юрлиц)"
    )
    ogrn = models.CharField(
        "ОГРН/ОГРНИП",
        max_length=15,
        blank=True,
        validators=[RegexValidator(r"^\d{13}(\d{2})?$", "ОГРН — 13 или 15 цифр")],
        help_text="13 цифр (ОГРН) или 15 цифр (ОГРНИП)"
    )

    # ---- юридический адрес ----
    legal_address = models.TextField(
        "Юридический адрес",
        help_text="Адрес регистрации из ЕГРЮЛ/ЕГРИП"
    )
    
    # ---- фактический адрес ----
    actual_address = models.TextField(
        "Фактический адрес",
        blank=True,
        help_text="Адрес для доставки (если отличается от юридического)"
    )

    # ---- банковские реквизиты ----
    bank_name = models.CharField("Наименование банка", max_length=255, blank=True)
    bik = models.CharField(
        "БИК",
        max_length=9,
        blank=True,
        validators=[RegexValidator(r"^\d{9}$", "БИК должен содержать 9 цифр")]
    )
    correspondent_account = models.CharField(
        "Корр. счет",
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^\d{20}$", "Корр. счет — 20 цифр")]
    )
    checking_account = models.CharField(
        "Расчетный счет",
        max_length=20,
        blank=True,
        validators=[RegexValidator(r"^\d{20}$", "Расчетный счет — 20 цифр")]
    )

    # ---- контакты ----
    phone = models.CharField("Телефон", max_length=30, blank=True)
    email = models.EmailField("Email", blank=True)
    website = models.URLField("Веб-сайт", blank=True)

    # ---- руководитель ----
    director_name = models.CharField(
        "ФИО руководителя",
        max_length=255,
        blank=True,
        help_text="Генеральный директор / ИП"
    )
    director_position = models.CharField(
        "Должность руководителя",
        max_length=128,
        blank=True,
        default="Генеральный директор"
    )

    # ---- связь с пользователями ----
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="CompanyUser",
        related_name="companies",
        verbose_name="Пользователи"
    )

    # ---- статус и даты ----
    is_active = models.BooleanField("Активна", default=True)  # type: ignore[assignment]
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)  # type: ignore[assignment]
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)  # type: ignore[assignment]

    # ---- дополнительно ----
    notes = models.TextField("Примечания", blank=True)

    class Meta:
        verbose_name = "Юридическое лицо"
        verbose_name_plural = "Юридические лица"
        ordering = ["short_name"]
        indexes = [
            models.Index(fields=["is_active", "created_at"], name="company_active_created_idx"),
        ]

    def __str__(self) -> str:
        return str(self.short_name)

    def get_delivery_address(self) -> str:
        """Возвращает адрес доставки (фактический или юридический)."""
        return str(self.actual_address or self.legal_address)


class CompanyUser(models.Model):
    """
    Связь пользователя с компанией.
    Один пользователь может представлять несколько компаний,
    одна компания может иметь несколько контактных лиц.
    """
    class Role(models.TextChoices):
        ADMIN = "admin", "Администратор"  # type: ignore[assignment]
        BUYER = "buyer", "Закупщик"  # type: ignore[assignment]
        ACCOUNTANT = "accountant", "Бухгалтер"  # type: ignore[assignment]
        VIEWER = "viewer", "Наблюдатель"  # type: ignore[assignment]

    company = models.ForeignKey(
        LegalEntity,
        on_delete=models.CASCADE,
        related_name="company_users",
        verbose_name="Компания"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="company_memberships",
        verbose_name="Пользователь"
    )
    role = models.CharField(
        "Роль",
        max_length=16,
        choices=Role.choices,
        default=Role.BUYER
    )
    is_primary = models.BooleanField(
        "Основной контакт",
        default=False,  # type: ignore[assignment]
        help_text="Основное контактное лицо компании"
    )
    position = models.CharField("Должность", max_length=128, blank=True)
    
    added_at = models.DateTimeField("Дата добавления", auto_now_add=True)  # type: ignore[assignment]

    class Meta:
        verbose_name = "Пользователь компании"
        verbose_name_plural = "Пользователи компаний"
        constraints = [
            models.UniqueConstraint(fields=["company", "user"], name="uniq_user_per_company"),
            models.UniqueConstraint(
                fields=["company"],
                condition=Q(is_primary=True),
                name="uniq_primary_contact_per_company",
            ),
        ]
        ordering = ["-is_primary", "user__last_name"]

    def __str__(self) -> str:
        user = self.user  # type: ignore[misc]
        company = self.company  # type: ignore[misc]
        return f"{user.get_full_name() or user.username} ({company.short_name})"  # type: ignore[attr-defined]
