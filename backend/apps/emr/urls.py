"""EMR URLs."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "emr"

router = DefaultRouter()
router.register(r"documents", views.ClinicalDocumentViewSet, basename="document")
router.register(r"problems", views.ProblemListViewSet, basename="problem")
router.register(r"safety-events", views.SafetyEventViewSet, basename="safetyevent")

urlpatterns = [
    path("documents/<uuid:pk>/amend/", views.ClinicalDocumentViewSet.as_view({"post": "amend"}), name="document-amend"),
    *router.urls,
]
