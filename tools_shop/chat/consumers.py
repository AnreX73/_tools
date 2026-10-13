import time
import uuid
from typing import Any, cast

from asgiref.sync import async_to_sync
from channels.generic.websocket import JsonWebsocketConsumer
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import Conversation, Message
from .push import enqueue_message_push

OPERATORS_GROUP = "chat.operators"


def can_reply(user):
    return bool(user and user.is_authenticated and user.is_staff and user.has_perm("chat.reply_conversation"))


def summary(conversation_pk, message):
    """Краткая сводка диалога для списка в виджете оператора."""
    return {
        "id": str(conversation_pk),
        "updated_at": message.created_at.isoformat(),
        "last_text": message.text[:80],
        "last_is_staff": message.is_staff,
    }


class ChatConsumer(JsonWebsocketConsumer):
    def connect(self):
        self.group_name = None
        route = self.scope.get("url_route", {}).get("kwargs", {})
        self.operator = "pk" in route
        user = self.scope.get("user")
        if self.operator:
            if not can_reply(user):
                self.close(code=4403)
                return
            conversation_id = route["pk"]
        else:
            session = self.scope.get("session")
            conversation_id = session.get("chat_conversation") if session else None
        self.conversation = Conversation.objects.filter(pk=conversation_id).first()
        if self.conversation is None:
            self.close(code=4403)
            return
        self.group_name = f"chat.{self.conversation.pk.hex}"
        # Subscribe first: concurrent messages are deduplicated by ID in the browser.
        async_to_sync(self.channel_layer.group_add)(self.group_name, self.channel_name)
        self.accept()
        messages = list(self.conversation.messages.order_by("-id")[:100])
        self.send_json({"type": "history", "messages": [m.payload() for m in reversed(messages)]})

    def disconnect(self, code):
        if self.group_name:
            async_to_sync(self.channel_layer.group_discard)(self.group_name, self.channel_name)

    def receive(self, text_data=None, bytes_data=None, **kwargs):
        if bytes_data is not None or text_data is None or len(text_data.encode("utf-8")) > 16384:
            self.close(code=1009)
            return
        try:
            content = self.decode_json(text_data)
        except (ValueError, TypeError):
            self.send_json({"type": "error", "message": "Некорректный формат сообщения."})
            return
        self.receive_json(content)

    def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            self.send_json({"type": "error", "message": "Некорректный формат сообщения."})
            return
        text = content.get("text")
        try:
            client_id = uuid.UUID(str(content.get("client_id")))
        except ValueError:
            self.send_json({"type": "error", "message": "Некорректный идентификатор сообщения."})
            return
        if not isinstance(text, str) or not text.strip() or len(text) > 2000:
            self.send_json({"type": "error", "message": "Введите сообщение от 1 до 2000 символов."})
            return
        user = self.scope.get("user")
        if self.operator and not can_reply(user):
            self.close(code=4403)
            return
        existing = Message.objects.filter(conversation=self.conversation, is_staff=self.operator, client_id=client_id).first()
        if existing:
            self.send_json({"type": "message", "message": existing.payload()})
            return
        # Shared Redis counter limits all tabs for this conversation to 20 messages/minute.
        key = f"chat-rate:{self.conversation.pk}:{int(self.operator)}:{int(time.time()) // 60}"
        cache.add(key, 0, timeout=120)
        if cache.incr(key) > 20:
            self.send_json({"type": "error", "message": "Слишком много сообщений. Подождите минуту."})
            return
        with cast(Any, transaction.atomic()):
            message, created = Message.objects.get_or_create(
                conversation=self.conversation, is_staff=self.operator, client_id=client_id,
                defaults={"text": text.strip(), "author": user if self.operator else None},
            )
            if created:
                Conversation.objects.filter(pk=self.conversation.pk).update(updated_at=timezone.now())
                transaction.on_commit(lambda: enqueue_message_push(message.pk))
        assert self.group_name is not None
        async_to_sync(self.channel_layer.group_send)(self.group_name, {"type": "chat.message", "message": message.payload()})
        if created:
            # Живое обновление списка диалогов у всех сотрудников, у кого открыт сайт.
            async_to_sync(self.channel_layer.group_send)(
                OPERATORS_GROUP,
                {"type": "inbox.update", "conversation": summary(self.conversation.pk, message)},
            )

    def chat_message(self, event):
        self.send_json({"type": "message", "message": event["message"]})


class OperatorInboxConsumer(JsonWebsocketConsumer):
    """Список диалогов для виджета оператора: снимок при подключении и живые обновления."""

    def connect(self):
        self.joined = False
        if not can_reply(self.scope.get("user")):
            self.close(code=4403)
            return
        async_to_sync(self.channel_layer.group_add)(OPERATORS_GROUP, self.channel_name)
        self.joined = True
        self.accept()
        self.send_json({"type": "inbox", "conversations": self.snapshot()})

    def disconnect(self, code):
        if self.joined:
            async_to_sync(self.channel_layer.group_discard)(OPERATORS_GROUP, self.channel_name)

    def receive(self, text_data=None, bytes_data=None, **kwargs):
        pass  # Клиент ничего не присылает, только слушает.

    def snapshot(self):
        result = []
        conversations = Conversation.objects.filter(messages__isnull=False).distinct()[:50]
        for conversation in conversations:
            last = conversation.messages.order_by("-id").first()
            if last:
                result.append(summary(conversation.pk, last))
        return result

    def inbox_update(self, event):
        self.send_json({"type": "update", "conversation": event["conversation"]})
