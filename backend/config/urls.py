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
    path("api/v1/", include("apps.abdm_gateway.urls", namespace="abdm")),
    path("api/v1/", include("apps.opd.urls", namespace="opd")),
    path("api/v1/", include("apps.ipd.urls", namespace="ipd")),
    path("api/v1/", include("apps.emergency.urls", namespace="emergency")),
    path("api/v1/", include("apps.icu.urls", namespace="icu")),
    path("api/v1/", include("apps.ot.urls", namespace="ot")),
    path("api/v1/", include("apps.lis.urls", namespace="lis")),
    path("api/v1/", include("apps.ris.urls", namespace="ris")),
    path("api/v1/", include("apps.pharmacy.urls", namespace="pharmacy")),
    path("api/v1/", include("apps.blood_bank.urls", namespace="blood_bank")),
    path("api/v1/", include("apps.billing_insurance.urls", namespace="billing")),
    path("api/v1/", include("apps.emr.urls", namespace="emr")),
    path("api/v1/", include("apps.quality_os.urls", namespace="quality")),
    path("api/v1/", include("apps.audit.urls", namespace="audit")),
    path("api/v1/", include("apps.integration.urls", namespace="integration")),
    path("api/v1/", include("apps.platform.urls", namespace="platform")),
    path("api/v1/", include("apps.realtime.urls", namespace="realtime")),
]
