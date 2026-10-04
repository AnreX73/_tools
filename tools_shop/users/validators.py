"""Русифицированные версии стандартных валидаторов паролей Django.

Логика проверки полностью наследуется от django.contrib.auth.password_validation,
переопределяются только тексты сообщений (на русском языке).
"""

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.utils.translation import ngettext_lazy


class RuMinimumLengthValidator(password_validation.MinimumLengthValidator):
    """Проверяет, что пароль не короче минимальной длины."""

    def get_error_message(self):
        return (
            ngettext_lazy(
                "Пароль слишком короткий. Он должен содержать не менее %d символа.",
                "Пароль слишком короткий. Он должен содержать не менее %d символов.",
                self.min_length,
            )
            % self.min_length
        )

    def get_help_text(self):
        return ngettext_lazy(
            "Пароль должен содержать не менее %(min_length)d символа.",
            "Пароль должен содержать не менее %(min_length)d символов.",
            self.min_length,
        ) % {"min_length": self.min_length}


class RuCommonPasswordValidator(password_validation.CommonPasswordValidator):
    """Проверяет, что пароль не входит в список часто используемых."""

    def get_error_message(self):
        return "Этот пароль слишком распространён."

    def get_help_text(self):
        return "Пароль не должен быть слишком простым и часто используемым."


class RuNumericPasswordValidator(password_validation.NumericPasswordValidator):
    """Проверяет, что пароль не состоит только из цифр."""

    def get_error_message(self):
        return "Пароль не может состоять только из цифр."

    def get_help_text(self):
        return "Пароль не может состоять только из цифр."


class RuUserAttributeSimilarityValidator(
    password_validation.UserAttributeSimilarityValidator
):
    """Проверяет, что пароль не слишком похож на данные пользователя."""

    def get_error_message(self):
        return "Пароль слишком похож на %(verbose_name)s."

    def get_help_text(self):
        return "Пароль не должен быть слишком похож на другие ваши личные данные."

    def validate(self, password, user=None):
        try:
            super().validate(password, user)
        except ValidationError as error:
            # Переводим сообщение, подставляя verbose_name атрибута.
            params = error.params or {}
            raise ValidationError(
                self.get_error_message(),
                code="password_too_similar",
                params=params,
            ) from error
