"""RIS URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "ris"

router = DefaultRouter()
router.register(r"imaging-orders", views.ImagingOrderViewSet, basename="imagingorder")

urlpatterns = [*router.urls]
