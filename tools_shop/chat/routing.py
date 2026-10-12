from typing import Any

from django.urls import path

from .consumers import ChatConsumer, OperatorInboxConsumer

websocket_urlpatterns: list[Any] = [
    path("ws/chat/", ChatConsumer.as_asgi()),
    path("ws/chat/operator/", OperatorInboxConsumer.as_asgi()),
    path("ws/chat/operator/<uuid:pk>/", ChatConsumer.as_asgi()),
]
