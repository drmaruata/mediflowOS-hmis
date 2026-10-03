"""ABDM gateway URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "abdm"

router = DefaultRouter()
router.register(r"abdm-callbacks", views.ABHACallbackViewSet, basename="abdmcallback")

urlpatterns = [
    *router.urls,
]
