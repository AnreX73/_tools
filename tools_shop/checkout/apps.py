"""Конфигурация приложения checkout."""
from django.apps import AppConfig


class CheckoutConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # type: ignore[assignment]
    name = "checkout"
    verbose_name = "Оформление заказов"
