from django.urls import re_path
from .consumers import NotificationConsumer, VitalsConsumer

websocket_urlpatterns = [
    re_path(r"ws/notifications/$", NotificationConsumer.as_asgi()),
    re_path(r"ws/vitals/$", VitalsConsumer.as_asgi()),
]
