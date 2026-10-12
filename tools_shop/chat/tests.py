import uuid
from typing import Any, cast

from asgiref.sync import async_to_sync
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import Client, TransactionTestCase
from django.urls import reverse

from .models import Conversation, Message
from .routing import websocket_urlpatterns


class ChatTests(TransactionTestCase):
    client: Any
    def setUp(self):
        cache.clear()
        self.conversation = Conversation.objects.create()

    def communicator(self, conversation=None, operator=None):
        if operator:
            assert conversation is not None
        path = f"/ws/chat/operator/{conversation.pk}/" if operator and conversation else "/ws/chat/"
        socket = WebsocketCommunicator(URLRouter(websocket_urlpatterns), path)
        scope = cast(dict[str, Any], socket.scope)
        scope["user"] = operator or AnonymousUser()
        scope["session"] = {"chat_conversation": str(conversation.pk)} if conversation else {}
        return socket

    def test_start_is_post_only_and_reuses_guest_session(self):
        self.assertEqual(self.client.get(reverse("chat:start")).status_code, 405)
        self.assertEqual(self.client.post(reverse("chat:start")).status_code, 200)
        key = self.client.session["chat_conversation"]
        self.client.post(reverse("chat:start"))
        self.assertEqual(self.client.session["chat_conversation"], key)
        self.assertTrue(Conversation.objects.filter(pk=key).exists())

    def test_start_requires_csrf(self):
        self.assertEqual(cast(Any, Client(enforce_csrf_checks=True).post(reverse("chat:start"))).status_code, 403)

    def test_operator_http_is_protected(self):
        self.assertEqual(self.client.get(reverse("chat:inbox")).status_code, 302)
        user = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("chat:inbox")).status_code, 403)

    def test_websocket_requires_session(self):
        async def run():
            socket = self.communicator()
            connected, code = await socket.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4403)
            await socket.disconnect()
        async_to_sync(run)()

    def test_guest_messages_are_persisted_and_deduplicated(self):
        async def run():
            socket = self.communicator(self.conversation)
            self.assertTrue((await socket.connect())[0])
            self.assertEqual((await socket.receive_json_from())["type"], "history")
            payload = {"text": "Нужен подшипник", "client_id": str(uuid.uuid4()), "is_staff": True}
            await socket.send_json_to(payload)
            first = await socket.receive_json_from()
            self.assertFalse(first["message"]["is_staff"])
            await socket.send_json_to(payload)
            self.assertEqual((await socket.receive_json_from())["message"]["id"], first["message"]["id"])
            await socket.disconnect()
        async_to_sync(run)()
        self.assertEqual(Message.objects.count(), 1)
        self.assertEqual(Message.objects.get().text, "Нужен подшипник")

    def test_operator_and_guest_exchange_messages(self):
        operator = get_user_model().objects.create_superuser(username="operator", password="test")
        async def run():
            guest = self.communicator(self.conversation)
            staff = self.communicator(self.conversation, operator)
            for socket in (guest, staff):
                self.assertTrue((await socket.connect())[0])
                await socket.receive_json_from()
            await staff.send_json_to({"text": "Уточните модель станка", "client_id": str(uuid.uuid4())})
            self.assertTrue((await guest.receive_json_from())["message"]["is_staff"])
            self.assertTrue((await staff.receive_json_from())["message"]["is_staff"])
            await guest.disconnect()
            await staff.disconnect()
        async_to_sync(run)()

    def test_other_sessions_cannot_read_messages(self):
        other = Conversation.objects.create()
        Message.objects.create(conversation=self.conversation, text="Приватное сообщение")
        async def run():
            socket = self.communicator(other)
            self.assertTrue((await socket.connect())[0])
            self.assertEqual((await socket.receive_json_from())["messages"], [])
            await socket.disconnect()
        async_to_sync(run)()

    def test_invalid_messages_and_rate_limit(self):
        async def run():
            socket = self.communicator(self.conversation)
            await socket.connect()
            await socket.receive_json_from()
            for payload in ([], {"text": "x", "client_id": "bad"}, {"text": "x" * 2001, "client_id": str(uuid.uuid4())}):
                await socket.send_json_to(payload)
                self.assertEqual((await socket.receive_json_from())["type"], "error")
            await socket.send_to(text_data="not-json")
            self.assertEqual((await socket.receive_json_from())["type"], "error")
            for _ in range(20):
                await socket.send_json_to({"text": "Вопрос", "client_id": str(uuid.uuid4())})
                self.assertEqual((await socket.receive_json_from())["type"], "message")
            await socket.send_json_to({"text": "Вопрос", "client_id": str(uuid.uuid4())})
            self.assertEqual((await socket.receive_json_from())["type"], "error")
            await socket.disconnect()
        async_to_sync(run)()
        self.assertEqual(Message.objects.count(), 20)

    def test_staff_without_permission_is_denied(self):
        user = get_user_model().objects.create_user(username="no-permission", is_staff=True)
        async def run():
            socket = self.communicator(self.conversation, user)
            connected, code = await socket.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4403)
            await socket.disconnect()
        async_to_sync(run)()
