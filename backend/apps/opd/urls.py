"""OPD URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "opd"

router = DefaultRouter()
router.register(r"tokens", views.TokenViewSet, basename="token")
router.register(r"encounters", views.OPDEncounterViewSet, basename="opdencounter")

urlpatterns = router.urls
