"""URLs for identity and tenancy (v1)."""
from django.urls import path, re_path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView

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
router.register(r"roles", views.RoleViewSet, basename="role")
router.register(r"memberships", views.UserMembershipViewSet, basename="membership")
router.register(r"users", views.UserViewSet, basename="user")
router.register(r"break-glass", views.BreakGlassViewSet, basename="break-glass")
router.register(r"setup", views.SetupProgressViewSet, basename="setup")
router.register(r"reference-data", views.ReferenceDataViewSet, basename="referencedata")
router.register(r"baseline-inputs", views.BaselineInputViewSet, basename="baselineinput")
router.register(r"config-revisions", views.ConfigRevisionViewSet, basename="configrevision")

_mfa_list = TOTPEnrolViewSet.as_view({"get": "list", "post": "create"})
_mfa_confirm = TOTPEnrolViewSet.as_view({"post": "confirm"})
_mfa_destroy = TOTPEnrolViewSet.as_view({"delete": "destroy"})

urlpatterns = [
    path("auth/token/", TenantTokenObtainPairView.as_view(), name="token-obtain"),
    # Refresh and blacklist authorise themselves with the refresh token in the
    # request body, not a bearer header, so SimpleJWT's views ship empty
    # authentication_classes/permission_classes (no AllowAny is added here).
    # The claims on that refresh token — tenant scope included — survive
    # rotation, which is what makes refresh safe to use (TEN-006).
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path(
        "auth/token/blacklist/",
        TokenBlacklistView.as_view(),
        name="token-blacklist",
    ),
    path("auth/me/", MeView.as_view(), name="me"),
    path("auth/break-glass/", BreakGlassView.as_view(), name="break-glass"),
    path("mfa-devices/", _mfa_list, name="mfadevice-list"),
    re_path(r"^mfa-devices/(?P<persistent_id>.+)/confirm/$", _mfa_confirm, name="mfadevice-confirm"),
    re_path(r"^mfa-devices/(?P<persistent_id>.+)/$", _mfa_destroy, name="mfadevice-detail"),
    *router.urls,
]
