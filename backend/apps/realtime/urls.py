"""Realtime URLs - WebSocket endpoints only."""
from django.urls import path
from . import consumers

urlpatterns = [
    path("ws/notifications/", consumers.NotificationConsumer.as_asgi()),
    path("ws/vitals/", consumers.VitalsConsumer.as_asgi()),
]