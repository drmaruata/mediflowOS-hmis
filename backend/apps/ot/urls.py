"""OT URLs."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "ot"

router = DefaultRouter()
router.register(r"schedules", views.OperationScheduleViewSet, basename="schedule")
router.register(r"records", views.SurgeryRecordViewSet, basename="surgeryrecord")

urlpatterns = [
    path("conflicts/", views.OperationScheduleViewSet.as_view({"get": "conflicts"}), name="schedule-conflicts"),
    *router.urls,
]
