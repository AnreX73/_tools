from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Conversation, Message


class MessageInline(admin.TabularInline):
    model = Message
    fields = ("is_staff", "text", "created_at")
    readonly_fields = fields
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "created_at", "updated_at", "open_chat")
    readonly_fields = ("id", "created_at", "updated_at", "open_chat")
    inlines = (MessageInline,)

    @admin.display(description="Ответить")
    def open_chat(self, obj):
        return format_html('<a href="{}">Открыть чат</a>', reverse("chat:conversation", args=[obj.pk]))

    def has_add_permission(self, request):
        return False
