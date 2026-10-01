

# from django import forms
# from django.conf import settings
# from django.contrib.auth import get_user_model
# from django.contrib.auth.forms import (
#     UserCreationForm,
# )
# from django.core.exceptions import ValidationError
# import re





# User = get_user_model()


# def validate_russian_email(value):
#     if not value or "@" not in value:
#         raise ValidationError("Некорректный адрес электронной почты.")

#     # 1. Проверяем по регулярному выражению (зону .ru)
#     pattern = getattr(
#         settings, "RU_EMAIL_PATTERN", r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.ru$"
#     )
#     if re.match(pattern, value):
#         return True  # Email подходит, завершаем проверку успешным исходом

#     # 2. Если не .ru, проверяем по списку исключений (by, kz и т.д.)
#     domain = value.split("@")[-1].lower()
#     extra_domains = getattr(settings, "EXTRA_ALLOWED_DOMAINS", [])

#     if domain not in extra_domains:
#         raise ValidationError(
#             "Регистрация доступна только через российские почтовые сервисы."
#         )

    
# class RegisterUserForm(UserCreationForm):
#     def __init__(self, *args, **kwargs):
#         super().__init__(*args, **kwargs)
#         # Делаем все поля кроме email и паролей необязательными
#         optional_fields = [
#             "first_name",
#             "last_name",
#             "phone_number",
#         ]
#         for field in optional_fields:
#             if field in self.fields:
#                 self.fields[field].required = False

#     email = forms.EmailField(
#         validators=[validate_russian_email],
#         required=True,
#         label="Email",
#         widget=forms.TextInput(
#             attrs={
#                 "autocomplete": "off",
#                 "placeholder": "example@mail.com",
#             }
#         ),
#     )

#     password1 = forms.CharField(
#         required=True, label="Пароль", widget=forms.PasswordInput
#     )

#     password2 = forms.CharField(
#         required=True, label="Повторите пароль", widget=forms.PasswordInput
#     )

#     class Meta:
#         model = User
#         fields = (
#             "email",
#             "password1",
#             "password2",
#         )

#     def clean_email(self):
#         email = self.cleaned_data.get("email")
#         if User.objects.filter(email=email).exists():
#             raise forms.ValidationError("Пользователь с таким email уже существует.")
#         return email

#     def save(self, commit=True):
#         user = super().save(commit=False)
#         email = self.cleaned_data["email"]
#         # username = email, гарантируем уникальность через срез если нужно
#         user.username = email[:150]
#         user.email = email
#         if commit:
#             user.save()
#         return user