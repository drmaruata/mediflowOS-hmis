"""Integration URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "integration"

router = DefaultRouter()
router.register(r"adapters", views.IntegrationAdapterViewSet, basename="adapter")
router.register(r"webhooks", views.WebhookEndpointViewSet, basename="webhook")

urlpatterns = [*router.urls]
