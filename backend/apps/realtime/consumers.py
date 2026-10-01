"""Django Channels consumers - notifications and live vitals ONLY (INT-012)."""
from channels.generic.websocket import AsyncJsonWebsocketConsumer


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.tenant_id = self.scope["user"].tenant_id if hasattr(self.scope["user"], "tenant_id") else None
        if not self.tenant_id:
            await self.close()
            return
        self.group = f"tenant_{self.tenant_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group, self.channel_name)

    async def send_notification(self, event):
        await self.send_json(event["payload"])


class VitalsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.tenant_id = self.scope["user"].tenant_id if hasattr(self.scope["user"], "tenant_id") else None
        if not self.tenant_id:
            await self.close()
            return
        self.group = f"vitals_{self.tenant_id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group, self.channel_name)

    async def send_vitals(self, event):
        await self.send_json(event["payload"])
