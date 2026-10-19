"""
companies/admin.py

Админ-интерфейс для управления юридическими лицами и пользователями компаний.
"""
from django.contrib import admin
from .models import LegalEntity, CompanyUser


class CompanyUserInline(admin.TabularInline):
    """Inline для добавления/редактирования пользователей компании."""
    model = CompanyUser
    extra = 1
    fields = ("user", "role", "position", "is_primary")
    autocomplete_fields = ("user",)


@admin.register(LegalEntity)
class LegalEntityAdmin(admin.ModelAdmin):
    list_display = (
        "short_name",
        "legal_form",
        "inn",
        "is_active",
        "is_verified",
        "created_at",
        "get_primary_contact"
    )
    list_filter = ("legal_form", "is_active", "is_verified", "created_at")
    search_fields = ("short_name", "full_name", "inn", "email")
    actions = ("mark_verified",)
    
    fieldsets = (
        ("Основные реквизиты", {
            "fields": ("full_name", "short_name", "legal_form")
        }),
        ("Регистрационные данные", {
            "fields": ("inn", "kpp", "ogrn")
        }),
        ("Адреса", {
            "fields": ("legal_address", "actual_address")
        }),
        ("Банковские реквизиты", {
            "fields": (
                "bank_name", "bik", "correspondent_account", "checking_account"
            ),
            "classes": ("collapse",)
        }),
        ("Контакты", {
            "fields": ("phone", "email", "website")
        }),
        ("Руководство", {
            "fields": ("director_name", "director_position")
        }),
        ("Статус и дополнительно", {
            "fields": ("is_active", "is_verified", "notes")
        }),
    )
    
    inlines = [CompanyUserInline]
    readonly_fields = ("created_at", "updated_at")

    @admin.action(description="Отметить проверенной")
    def mark_verified(self, request, queryset):
        """Массово подтверждает реквизиты после проверки менеджером."""
        updated = queryset.update(is_verified=True)
        self.message_user(
            request,
            f"Отмечено проверенными: {updated}.",
        )

    @admin.display(description="Основной контакт")
    def get_primary_contact(self, obj):
        """Показывает основного контакта компании."""
        primary = obj.company_users.filter(is_primary=True).first()
        if primary:
            return f"{primary.user.get_full_name() or primary.user.username}"
        return "—"
    
    def get_queryset(self, request):
        """Оптимизация запросов."""
        qs = super().get_queryset(request)
        return qs.prefetch_related("company_users__user")


@admin.register(CompanyUser)
class CompanyUserAdmin(admin.ModelAdmin):
    list_display = ("user", "company", "role", "position", "is_primary", "added_at")
    list_filter = ("role", "is_primary", "added_at", "company")
    search_fields = ("user__username", "user__email", "company__short_name", "position")
    
    fieldsets = (
        (None, {
            "fields": ("company", "user")
        }),
        ("Информация", {
            "fields": ("role", "position", "is_primary")
        }),
    )
    
    readonly_fields = ("added_at",)
    autocomplete_fields = ("company", "user")
    
    def get_queryset(self, request):
        """Оптимизация запросов."""
        qs = super().get_queryset(request)
        return qs.select_related("company", "user")
