"""ASGI entrypoint.

Django Channels is intentionally narrow (architecture doc §13): the WebSocket
routing covers only the two approved consumers — notification delivery and live
vitals dashboards. All other operational screens use REST polling.
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.base")
django_asgi = get_asgi_application()

# Import after Django setup to avoid AppRegistryNotReady.
from apps.realtime.middleware import token_auth_middleware  # noqa: E402
from apps.realtime.routing import websocket_urlpatterns  # noqa: E402

# AuthMiddlewareStack is deliberately gone: it authenticates the handshake against
# the Django session, and a session carries no tenant claim, so both consumers -
# which exist to deliver one tenant's data - had nothing to scope to and every
# connection closed during the handshake. The JWT middleware reads the access token
# from the query string and scopes from its signed claim (PLT-001, INT-012); see
# apps/realtime/middleware.py. daphne remains the ASGI server (AGENTS.md §3).
application = ProtocolTypeRouter({
    "http": django_asgi,
    "websocket": token_auth_middleware(URLRouter(websocket_urlpatterns)),
})
