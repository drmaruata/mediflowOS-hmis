"""IPD URLs."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "ipd"

router = DefaultRouter()
router.register(r"admissions", views.AdmissionViewSet, basename="admission")
router.register(r"bed-status", views.BedStatusViewSet, basename="bedstatus")
router.register(r"census", views.CensusSnapshotViewSet, basename="censussnapshot")

urlpatterns = [
    path("discharge/", views.AdmissionViewSet.as_view({"post": "discharge"}), name="admission-discharge"),
    path("active/", views.AdmissionViewSet.as_view({"get": "active"}), name="admission-active"),
    path("board/", views.BedStatusViewSet.as_view({"get": "board"}), name="bedstatus-board"),
    *router.urls,
]
