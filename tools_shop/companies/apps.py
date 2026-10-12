"""
Конфигурация приложения companies.
"""
from django.apps import AppConfig


class CompaniesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # type: ignore[assignment]
    name = "companies"
    verbose_name = "Юридические лица"
