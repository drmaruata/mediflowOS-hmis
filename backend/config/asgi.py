"""ASGI entrypoint.

Django Channels is intentionally narrow (architecture doc §13): the WebSocket
routing covers only the two approved consumers — notification delivery and live
vitals dashboards. All other operational screens use REST polling.
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django_asgi = get_asgi_application()

# Import after Django setup to avoid AppRegistryNotReady.
from apps.realtime.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi,
    "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
})