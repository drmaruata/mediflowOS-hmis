"""Top-level URL routing."""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/health/", include("apps.common.urls", namespace="common")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/v1/", include("apps.identity_tenancy.urls", namespace="identity")),
    path("api/v1/", include("apps.patient_registry.urls", namespace="patient")),
]
