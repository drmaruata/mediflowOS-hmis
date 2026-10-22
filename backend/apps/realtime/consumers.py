"""Django Channels consumers - notifications and live vitals ONLY (INT-012)."""
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.platform.models import Notification

logger = logging.getLogger(__name__)


def _mark_delivered(tenant_id, notification_id):
    """Flag a notification as delivered, scoped to the tenant that got it.

    The filter names the tenant *and* the primary key, so a consumer can only
    ever mark a row belonging to the tenant its token claimed - a cross-tenant id
    in the payload matches nothing. ``update()`` rather than a read-then-save,
    because a row deleted between the push and this write is a no-op here instead
    of a DoesNotExist raised inside the consumer's event loop.
    """
    return Notification.objects.filter(
        tenant_id=tenant_id, id=notification_id
    ).update(delivered=True)


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Delivers in-app notifications to one tenant's sockets (PLT-001, INT-012)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: Tenant the handshake was issued for. Only the middleware sets it, from
        #: the token's signed claim; never from the user record.
        self.tenant_id = None
        #: Group this connection joined. Initialised here so that a
        #: ``connect()`` that closes early still leaves ``disconnect()`` with
        #: something to discard: touching an unset attribute in teardown turns a
        #: refused handshake into an exception in the consumer's event loop.
        self.group = None

    async def connect(self):
        self.tenant_id = self.scope.get("tenant_id")
        if not self.tenant_id:
            # Defence in depth. token_auth_middleware refuses such a handshake
            # before this code runs; closing here keeps a consumer mounted
            # without it (as the tests do) fail closed rather than joining a
            # group named "tenant_None".
            await self.close()
            return
        self.group = f"tenant_{self.tenant_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.group is None:
            return
        await self.channel_layer.group_discard(self.group, self.channel_name)

    async def send_notification(self, event):
        """Send one notification, then record that this socket received it."""
        payload = event["payload"]
        await self.send_json(payload)
        notification_id = payload.get("id") if isinstance(payload, dict) else None
        if not notification_id:
            # A frame with no row to point at cannot be flagged. The frame has
            # already gone out, so this is a log line, not a failure.
            logger.debug("notification frame carried no row id; delivery not flagged")
            return
        await database_sync_to_async(_mark_delivered)(self.tenant_id, notification_id)


class VitalsConsumer(AsyncJsonWebsocketConsumer):
    """Streams live vitals to one tenant's dashboards (INT-012)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant_id = None
        self.group = None

    async def connect(self):
        self.tenant_id = self.scope.get("tenant_id")
        if not self.tenant_id:
            await self.close()
            return
        self.group = f"vitals_{self.tenant_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if self.group is None:
            return
        await self.channel_layer.group_discard(self.group, self.channel_name)

    async def send_vitals(self, event):
        await self.send_json(event["payload"])
