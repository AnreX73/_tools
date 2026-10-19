"""Конфигурация приложения cart."""
from django.apps import AppConfig


class CartConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # type: ignore[assignment]
    name = "cart"
    verbose_name = "Корзина и избранное"

    def ready(self) -> None:
        # Подключает обработчик user_logged_in (точка расширения для слияния
        # гостевой корзины с корзиной пользователя).
        from . import signals  # noqa: F401
