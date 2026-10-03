"""Quality OS URLs."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

app_name = "quality"

router = DefaultRouter()
router.register(r"frameworks", views.FrameworkViewSet, basename="framework")
router.register(r"editions", views.FrameworkEditionViewSet, basename="frameworkedition")
router.register(r"source-documents", views.IndicatorSourceDocumentViewSet, basename="sourcedocument")
router.register(r"indicators", views.IndicatorDefViewSet, basename="indicatordef")
router.register(r"indicator-values", views.IndicatorValueViewSet, basename="indicatorvalue")
router.register(r"capas", views.CAPAViewSet, basename="capa")
router.register(r"facts", views.QualityFactViewSet, basename="qualityfact")

urlpatterns = [
    path("indicator-values/dashboard/", views.IndicatorValueViewSet.as_view({"get": "dashboard"}), name="indicator-value-dashboard"),
    *router.urls,
]
