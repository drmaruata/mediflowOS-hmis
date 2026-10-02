from django.urls import path, re_path
from rest_framework.routers import DefaultRouter

from . import views
from .auth_views import (
    BreakGlassView,
    MeView,
    TOTPEnrolViewSet,
    TenantTokenObtainPairView,
)

app_name = "identity"

router = DefaultRouter()
router.register(r"tenants", views.TenantViewSet, basename="tenant")
router.register(r"facilities", views.FacilityViewSet, basename="facility")
router.register(r"departments", views.DepartmentViewSet, basename="department")
router.register(r"wards", views.WardViewSet, basename="ward")
router.register(r"beds", views.BedViewSet, basename="bed")
router.register(r"service-units", views.ServiceUnitViewSet, basename="serviceunit")
router.register(r"staff-positions", views.StaffPositionViewSet, basename="staffposition")

# django-otp persistent ids look like "otp_totp.totpdevice/3" - they contain a
# slash as well as a dot. DRF's router builds every detail route from a single
# shared pattern, "[^/.]+", so a router-generated route 404s for every device.
# The pattern is not configurable per registration, so these routes are declared
# explicitly rather than patching the router's internals.
#
# The id pattern is ".+" rather than "[^/]+" precisely because the id itself
# contains a slash; the trailing anchor keeps it from swallowing the action
# segment.
#
# Consequence: mfa-devices is absent from the DefaultRouter's api-root listing.
_mfa_list = TOTPEnrolViewSet.as_view({"get": "list", "post": "create"})
_mfa_confirm = TOTPEnrolViewSet.as_view({"post": "confirm"})
_mfa_destroy = TOTPEnrolViewSet.as_view({"delete": "destroy"})

urlpatterns = [
    path("auth/token/", TenantTokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("auth/break-glass/", BreakGlassView.as_view(), name="break-glass"),
    path("mfa-devices/", _mfa_list, name="mfadevice-list"),
    re_path(r"^mfa-devices/(?P<persistent_id>.+)/confirm/$", _mfa_confirm,
            name="mfadevice-confirm"),
    re_path(r"^mfa-devices/(?P<persistent_id>.+)/$", _mfa_destroy,
            name="mfadevice-detail"),
    # Declared before the router so "auth" cannot be captured as a router
    # prefix for a resource named "auth".
    *router.urls,
]
