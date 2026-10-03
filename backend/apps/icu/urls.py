"""ICU URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "icu"

router = DefaultRouter()
router.register(r"vitals", views.VitalsFlowsheetViewSet, basename="vitals")
router.register(r"devices", views.DeviceViewSet, basename="device")

urlpatterns = [*router.urls]
