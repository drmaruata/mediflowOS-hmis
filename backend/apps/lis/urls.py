"""LIS URLs."""
from rest_framework.routers import DefaultRouter

from . import views

app_name = "lis"

router = DefaultRouter()
router.register(r"orders", views.LabOrderViewSet, basename="laborder")
router.register(r"results", views.LabResultViewSet, basename="labresult")

urlpatterns = [
    *router.urls,
]
