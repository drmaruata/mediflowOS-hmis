"""Tests for the ABDM profile-share callback endpoint.

History: this file originally asserted the endpoint answered 501 and wrote
nothing, which was the honest state while the seven architecture doc section 8.4
requirements were outstanding. The callback is now implemented, so these tests
pin the behaviour that replaced it.

The route stays ``AllowAny`` because the gateway carries no user JWT.
Authentication therefore happens *inside* the view, not by DRF, and that is the
single most important thing to keep pinned here: an anonymous route that reaches
a database write without authenticating first would let anyone register
patients into a real hospital.
"""
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.abdm_gateway.models import ABHACallbackLog
from apps.identity_tenancy.models import Department, Facility, Tenant
from apps.opd.models import Token
from apps.patient_registry.models import Patient

GATEWAY_AUTH = {"HTTP_X_AUTHORIZATION": "gateway-shared-secret"}


def _tenant_with_opd(slug="abdm-hospital", hip_id="hip-123"):
    tenant = Tenant.objects.create(name="ABDM Hospital", slug=slug)
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus", abdm_hip_id=hip_id,
    )
    department = Department.objects.create(
        tenant=tenant, facility=facility, name="Medicine",
        effective_from="2026-01-01", opd_enabled=True,
    )
    return tenant, facility, department


def _payload(**overrides):
    body = {
        "requestId": "req-1",
        "facilityId": "hip-123",
        "timestamp": timezone.now().isoformat(),
        "profile": {"abhaNumber": "123456789012"},
    }
    body.update(overrides)
    return body


@pytest.mark.integration
@pytest.mark.django_db
def test_abdm_callback_rejects_unauthenticated_call():
    """An anonymous write attempt must be refused before any work happens.

    DRF does not do this: the route is AllowAny. If this ever returns 200, the
    gateway is unauthenticated and anyone can write into a tenant. The tenant is
    set up so the call would otherwise succeed — the rejection has to come from
    authentication, not from the payload failing later.
    """
    _tenant_with_opd()
    response = APIClient().post("/api/v1/abdm-callbacks/", _payload(), format="json")

    assert response.status_code == 401
    assert response.json()["status"] == "rejected"


@pytest.mark.integration
@pytest.mark.django_db
def test_unauthenticated_call_writes_nothing():
    """A refused call must not leave rows behind."""
    _tenant_with_opd()
    APIClient().post("/api/v1/abdm-callbacks/", _payload(), format="json")

    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_abdm_callback_processes_an_authenticated_call():
    """An authenticated, well-formed call issues a token and logs the callback."""
    tenant, _, department = _tenant_with_opd()
    response = APIClient().post(
        "/api/v1/abdm-callbacks/", _payload(), format="json", **GATEWAY_AUTH
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["request_id"] == "req-1"

    log = ABHACallbackLog.objects.get(request_id="req-1")
    assert str(log.tenant_id) == str(tenant.id)
    assert log.token_issued == body["token"]
    assert Token.objects.get(id=body["token"]).department_id == department.id


@pytest.mark.integration
@pytest.mark.django_db
def test_unmatched_profile_is_registered_pending_verification():
    """A scan for an unknown patient creates a record, not a verified identity.

    Nobody has checked the demographics against an ID document, so the patient
    must land in the verification queue (REG-004).
    """
    _tenant_with_opd()
    response = APIClient().post(
        "/api/v1/abdm-callbacks/", _payload(), format="json", **GATEWAY_AUTH
    )

    patient = Patient.objects.get(id=response.json()["patient_id"])
    assert patient.verification_status == "pending"
    assert patient.abha_number == "123456789012"
    assert patient.consent_flags["abdm_scan_and_share"] is True


@pytest.mark.integration
@pytest.mark.django_db
def test_callback_is_idempotent_on_request_id():
    """A replayed request ID returns the first result and issues no second token."""
    _tenant_with_opd()
    client = APIClient()

    first = client.post("/api/v1/abdm-callbacks/", _payload(), format="json", **GATEWAY_AUTH)
    second = client.post("/api/v1/abdm-callbacks/", _payload(), format="json", **GATEWAY_AUTH)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["token"] == first.json()["token"]
    assert Token.objects.count() == 1
    assert ABHACallbackLog.objects.count() == 1


@pytest.mark.integration
@pytest.mark.django_db
def test_stale_timestamp_is_rejected():
    """Timestamps outside the 5-minute window are refused (ABD-007)."""
    _tenant_with_opd()
    response = APIClient().post(
        "/api/v1/abdm-callbacks/",
        _payload(timestamp="2020-01-01T00:00:00Z"),
        format="json",
        **GATEWAY_AUTH,
    )

    assert response.status_code == 400
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_unknown_hip_id_is_rejected():
    """A HIP ID belonging to no facility cannot resolve a tenant (ABD-004)."""
    _tenant_with_opd()
    response = APIClient().post(
        "/api/v1/abdm-callbacks/",
        _payload(facilityId="hip-not-registered"),
        format="json",
        **GATEWAY_AUTH,
    )

    assert response.status_code == 400
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_scan_cannot_write_into_another_tenants_department():
    """A department UUID from another tenant must not be adopted.

    The gateway is not trusted to name our departments. If the department lookup
    were not tenant-scoped, one hospital could push tokens into another's queue.
    """
    tenant_a, _, _ = _tenant_with_opd(slug="hospital-a", hip_id="hip-a")
    _, _, department_b = _tenant_with_opd(slug="hospital-b", hip_id="hip-b")

    response = APIClient().post(
        "/api/v1/abdm-callbacks/",
        _payload(facilityId="hip-a", departmentId=str(department_b.id)),
        format="json",
        **GATEWAY_AUTH,
    )

    assert response.status_code == 200
    token = Token.objects.get(id=response.json()["token"])
    assert str(token.tenant_id) == str(tenant_a.id)
    assert token.department_id != department_b.id


@pytest.mark.integration
def test_health_probe_route_name_is_stable():
    """Guard against a router rename silently breaking monitoring."""
    assert reverse("common:health") == "/api/v1/health/"
