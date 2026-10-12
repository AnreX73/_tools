import uuid
from typing import Any, cast

from django.conf import settings
from django.db import models


class Conversation(models.Model):
    objects = models.Manager()
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "Диалог"
        verbose_name_plural = "Диалоги"
        permissions = [("reply_conversation", "Может отвечать посетителям в чате")]

    def __str__(self):
        return f"Диалог {str(self.pk)[:8]}"


class Message(models.Model):
    objects = models.Manager()
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    client_id = models.UUIDField(default=uuid.uuid4)
    is_staff = models.BooleanField(default=cast(Any, False))
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    text = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Сообщение"
        verbose_name_plural = "Сообщения"
        constraints = [models.UniqueConstraint(fields=["conversation", "is_staff", "client_id"], name="chat_message_dedup")]

    def payload(self):
        return {
            "id": self.pk,
            "client_id": str(self.client_id),
            "is_staff": self.is_staff,
            "text": self.text,
            "created_at": cast(Any, self.created_at).isoformat(),
        }
