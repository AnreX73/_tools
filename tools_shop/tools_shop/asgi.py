import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tools_shop.settings")

from django.core.asgi import get_asgi_application

django_asgi_application = get_asgi_application()

# Routing imports models, so Django must be initialized above first.
from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from chat.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_application,
    "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(websocket_urlpatterns))),
})
