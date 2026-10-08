"""Tests that the API surface denies by default.

Step 1 of the hardening pass changed the DRF defaults from DRF's implicit
``AllowAny`` to an explicit ``IsAuthenticated``. These tests exist so that a
future edit to ``REST_FRAMEWORK`` which silently reopens the data plane fails
here rather than in production.
"""
import pytest
from rest_framework.test import APIClient

# Endpoints that carry tenant-owned data. None of these may be reachable
# without authentication.
PROTECTED_ENDPOINTS = [
    "/api/v1/tenants/",
    "/api/v1/tenants/onboard/",
    "/api/v1/facilities/",
    "/api/v1/departments/",
    "/api/v1/wards/",
    "/api/v1/beds/",
    "/api/v1/service-units/",
    "/api/v1/staff-positions/",
    "/api/v1/patients/",
    "/api/v1/patients/search/",
    "/api/v1/intake-points/",
    "/api/v1/qr-codes/",
    "/api/v1/users/",
]


@pytest.mark.integration
@pytest.mark.parametrize("endpoint", PROTECTED_ENDPOINTS)
def test_tenant_endpoints_reject_anonymous_reads(endpoint):
    """An unauthenticated GET must not reach any tenant-owned resource."""
    response = APIClient().get(endpoint)

    assert response.status_code in (401, 403), (
        f"{endpoint} returned {response.status_code} to an anonymous request; "
        "the data plane must deny by default"
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "method",
    ["post", "put", "patch", "delete"],
)
def test_tenant_endpoints_reject_anonymous_writes(method):
    """Anonymous callers must not be able to create, alter or delete rows."""
    response = getattr(APIClient(), method)("/api/v1/tenants/", {}, format="json")

    assert response.status_code in (401, 403), (
        f"anonymous {method.upper()} returned {response.status_code}; "
        "writes must require authentication"
    )


@pytest.mark.integration
def test_onboard_endpoint_is_not_publicly_writable():
    """TEN-010 reserves tenant onboarding for the platform administrator.

    ``TenantViewSet.onboard`` is a plain model viewset action, so it inherits
    the project-wide permission class. It must not be anonymously reachable.
    """
    response = APIClient().post(
        "/api/v1/tenants/onboard/",
        {"name": "Injected Hospital", "slug": "injected"},
        format="json",
    )

    assert response.status_code in (401, 403)


@pytest.mark.integration
def test_health_probe_remains_public():
    """The liveness probe is the one intentionally anonymous endpoint."""
    response = APIClient().get("/api/v1/health/")

    assert response.status_code == 200


@pytest.mark.integration
def test_invalid_token_does_not_bypass_permissions():
    """A malformed bearer token must fail closed, not fall through to AllowAny."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")

    response = client.get("/api/v1/tenants/")

    assert response.status_code in (401, 403)