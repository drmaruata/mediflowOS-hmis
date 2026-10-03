"""Emergency URLs."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "emergency"

router = DefaultRouter()
router.register(r"triages", views.TriageViewSet, basename="triage")

urlpatterns = [
    path("tracking-board/", views.TriageViewSet.as_view({"get": "tracking_board"}), name="tracking-board"),
    *router.urls,
]
