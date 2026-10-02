"""Realtime URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "realtime"

router = DefaultRouter()
router.register(r"realtime-status", views.RealtimeStatusViewSet, basename="realtimestatus")

urlpatterns = [
    *router.urls,
]
