import base64
import json
from typing import Any, cast
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from pywebpush import WebPushException
from requests import Response

from .models import Conversation, Message, PushSubscription
from .push import send_message_push


@override_settings(VAPID_PUBLIC_KEY="public", VAPID_PRIVATE_KEY="private", VAPID_SUBJECT="mailto:admin@example.com")
class PushTests(TestCase):
    client: Any
    def setUp(self):
        self.client.post('/chat/start/')
        self.conversation = Conversation.objects.get(pk=self.client.session['chat_conversation'])
        self.payload = {"subscription": {
            "endpoint": "https://fcm.googleapis.com/fcm/send/test",
            "keys": {"auth": base64.urlsafe_b64encode(b'a' * 16).decode().rstrip('='),
                     "p256dh": base64.urlsafe_b64encode(b'\x04' + b'b' * 64).decode().rstrip('=')},
        }}

    def subscribe(self, client=None, payload=None) -> Any:
        return cast(Any, client or self.client).post('/chat/push/subscribe/',
                                          data=json.dumps(payload or self.payload), content_type='application/json')

    def test_subscription_is_bound_to_guest_and_requires_csrf(self):
        self.assertEqual(self.subscribe().status_code, 200)
        self.assertEqual(self.subscribe().status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 1)
        subscription = PushSubscription.objects.get()
        self.assertEqual(subscription.conversation_id, self.conversation.pk)
        self.assertEqual(subscription.session_key, self.client.session.session_key)
        self.assertIsNone(subscription.user_id)
        self.assertEqual(self.subscribe(Client(enforce_csrf_checks=True)).status_code, 403)

    def test_other_session_cannot_claim_endpoint(self):
        self.subscribe()
        other = Client()
        other.post('/chat/start/')
        self.assertEqual(self.subscribe(other).status_code, 409)
        self.assertEqual(PushSubscription.objects.get().conversation_id, self.conversation.pk)

    def test_invalid_endpoint_and_keys_rejected(self):
        for endpoint in ('http://fcm.googleapis.com/test', 'https://127.0.0.1/test',
                         'https://fcm.googleapis.com.evil.example/test'):
            self.payload['subscription']['endpoint'] = endpoint
            self.assertEqual(self.subscribe().status_code, 400)
        self.payload['subscription']['endpoint'] = 'https://fcm.googleapis.com/fcm/send/test'
        self.payload['subscription']['keys']['auth'] = 'bad'
        self.assertEqual(self.subscribe().status_code, 400)

    def test_operator_subscription_and_delivery_routing(self):
        self.subscribe()
        operator = get_user_model().objects.create_superuser(username='push-operator', password='test')
        staff_client: Any = Client()
        staff_client.force_login(operator)
        payload = json.loads(json.dumps(self.payload))
        payload['subscription']['endpoint'] += '-operator'
        self.assertEqual(self.subscribe(staff_client, payload).status_code, 200)
        staff_subscription = PushSubscription.objects.get(user=operator)
        self.assertIsNone(staff_subscription.conversation_id)
        with patch('chat.push.webpush') as send:
            guest_message = Message.objects.create(conversation=self.conversation, text='Вопрос')
            send_message_push(guest_message.pk)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.kwargs['subscription_info']['endpoint'], payload['subscription']['endpoint'])
            self.assertIn(str(self.conversation.pk), json.loads(send.call_args.kwargs['data'])['data']['url'])
            send.reset_mock()
            reply = Message.objects.create(conversation=self.conversation, text='Ответ', is_staff=True)
            send_message_push(reply.pk)
            self.assertEqual(send.call_count, 1)
            self.assertEqual(send.call_args.kwargs['subscription_info']['endpoint'], self.payload['subscription']['endpoint'])
            staff_client.logout()
            send.reset_mock()
            send_message_push(guest_message.pk)
            send.assert_not_called()
            self.assertFalse(PushSubscription.objects.filter(user=operator).exists())

    def test_expired_endpoint_removed_and_unsubscribe(self):
        self.subscribe()
        reply = Message.objects.create(conversation=self.conversation, text='Ответ', is_staff=True)
        response = Response()
        response.status_code = 410
        with patch('chat.push.webpush', side_effect=WebPushException('gone', response=response)):
            send_message_push(reply.pk)
        self.assertEqual(PushSubscription.objects.count(), 0)
        self.subscribe()
        self.assertEqual(self.client.post('/chat/push/unsubscribe/').status_code, 200)
        self.assertEqual(PushSubscription.objects.count(), 0)

    def test_worker_available_at_root_and_not_cached(self):
        response = self.client.get('/sw.js')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Service-Worker-Allowed'], '/')
        self.assertEqual(response['Cache-Control'], 'no-cache')
        self.assertIn(b"addEventListener('push'", response.content)
