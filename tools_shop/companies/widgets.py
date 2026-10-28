"""
companies/widgets.py

Виджет поля ИНН для админки: input + кнопка «Заполнить по ИНН».

Разметка и скрипт подключаются через ``Media`` виджета, поэтому JS и CSS
грузятся только на страницах моделей, где поле действительно есть.
"""
from __future__ import annotations

from django import forms
from django.urls import reverse


class InnLookupWidget(forms.TextInput):
    """Текстовое поле ИНН с кнопкой подсказки реквизитов."""

    template_name = "companies/widgets/inn_lookup.html"

    class Media:
        css = {"all": ("companies/admin/inn_lookup.css",)}
        js = ("companies/admin/inn_lookup.js",)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["inn_lookup_url"] = reverse("admin_inn_lookup")
        return context
