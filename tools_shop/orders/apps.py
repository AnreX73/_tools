"""Конфигурация приложения orders."""
from django.apps import AppConfig


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # type: ignore[assignment]
    name = "orders"
    verbose_name = "Заказы и счета"
