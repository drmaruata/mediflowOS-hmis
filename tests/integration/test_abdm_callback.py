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

ABD-005 is enforced with a real HMAC: every successful call posts a signature
computed over the exact bytes the client sends (``_signed_request`` serializes
the payload once and signs those bytes), and the view re-computes the digest
over the raw body it receives. Tests that must change the bytes after signing
post the mutated body with the original signature — the view computes over
what it receives, so the digest no longer matches.
"""
import hashlib
import hmac
import json

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.abdm_gateway.models import ABHACallbackLog
from apps.identity_tenancy.models import Department, Facility, Tenant
from apps.opd.models import Token
from apps.patient_registry.models import Patient

CALLBACK_URL = "/api/v1/abdm-callbacks/"


def _signed_request(payload, secret=None):
    """Serialize once and sign the exact bytes the client will post.

    The view re-computes the HMAC over the raw request body, so the digest has
    to cover the same bytes that go on the wire: serializing twice could reorder
    keys and break the signature even for a legitimate call. Returns the body
    bytes and the ``HTTP_X_ABDM_SIGNATURE`` header dict.
    """
    secret = settings.ABDM_CLIENT_SECRET if secret is None else secret
    body_bytes = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
    return body_bytes, {"HTTP_X_ABDM_SIGNATURE": signature}


def _post(client, payload, count=1, **kwargs):
    """Post ``payload`` signed, returning the last response.

    ``count`` repeats the same signed request (a replay) and returns the final
    response — replaying must send identical bytes, which requires one signed
    body reused verbatim.
    """
    body, headers = _signed_request(payload, **kwargs)
    response = None
    for _ in range(count):
        response = client.post(
            CALLBACK_URL, body, content_type="application/json", **headers
        )
    return response


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
    response = APIClient().post(CALLBACK_URL, _payload(), format="json")

    assert response.status_code == 401
    assert response.json()["status"] == "rejected"


@pytest.mark.integration
@pytest.mark.django_db
def test_unauthenticated_call_writes_nothing():
    """A refused call must not leave rows behind."""
    _tenant_with_opd()
    APIClient().post(CALLBACK_URL, _payload(), format="json")

    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_legacy_presence_only_headers_are_rejected():
    """The pre-ABD-005 presence fallbacks no longer authenticate (ABD-005).

    The previous implementation accepted any non-empty X-Authorization header
    or Bearer token. A header without a valid HMAC must now be refused, or an
    attacker with either legacy header shape could write into a tenant.
    """
    _tenant_with_opd()
    body, _ = _signed_request(_payload())
    response = APIClient().post(
        CALLBACK_URL,
        body,
        content_type="application/json",
        HTTP_X_AUTHORIZATION="gateway-shared-secret",
    )

    assert response.status_code == 401
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_abdm_callback_processes_an_authenticated_call():
    """A valid HMAC-signed, well-formed call issues a token and logs it."""
    tenant, _, department = _tenant_with_opd()
    response = _post(APIClient(), _payload())

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
    response = _post(APIClient(), _payload())

    patient = Patient.objects.get(id=response.json()["patient_id"])
    assert patient.verification_status == "pending"
    assert patient.abha_number == "123456789012"
    assert patient.consent_flags["abdm_scan_and_share"] is True


@pytest.mark.integration
@pytest.mark.django_db
def test_tampered_body_with_original_signature_is_rejected():
    """Mutating the body after signing must fail the HMAC (ABD-005).

    The view computes the digest over what it receives, so a body whose bytes
    differ from the ones that were signed can never match — even though the
    signature header is identical to a legitimate call's.
    """
    _tenant_with_opd()
    body, headers = _signed_request(_payload())
    tampered = body[:-1] + (b"x" if body[-1:] != b"x" else b"y")

    response = APIClient().post(
        CALLBACK_URL, tampered, content_type="application/json", **headers
    )

    assert response.status_code == 401
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
@override_settings(ABDM_CLIENT_SECRET="")
def test_unset_secret_fails_closed_outside_debug():
    """An unset shared secret must reject under non-DEBUG settings (ABD-005).

    The sandbox has no shared secret yet, so the fail-open path is DEBUG-only.
    If this returns 200 the endpoint would accept unsigned calls under
    production settings whenever the variable is missing.
    """
    _tenant_with_opd()
    body, _ = _signed_request(_payload())

    response = APIClient().post(
        CALLBACK_URL, body, content_type="application/json", **{"HTTP_X_ABDM_SIGNATURE": "deadbeef"}
    )

    assert response.status_code == 401
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_callback_is_idempotent_on_request_id():
    """A replayed request ID returns the first result, no second writes (ABD-006).

    Review Focus #3: the replay must return the *original* acknowledgement and
    must not create a second patient, token, or log row.
    """
    _tenant_with_opd()
    client = APIClient()

    first = _post(client, _payload())
    second = _post(client, _payload(), count=2)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    assert second.json()["token"] == first.json()["token"]
    assert second.json()["request_id"] == first.json()["request_id"]
    assert second.json()["patient_id"] == first.json()["patient_id"]
    assert Token.objects.count() == 1
    assert ABHACallbackLog.objects.count() == 1
    assert Patient.objects.count() == 1


@pytest.mark.integration
@pytest.mark.django_db
def test_stale_timestamp_is_rejected():
    """Timestamps outside the skew window are refused (ABD-007)."""
    _tenant_with_opd()
    response = _post(APIClient(), _payload(timestamp="2020-01-01T00:00:00Z"))

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_payload_requires_request_id():
    """A missing requestId is a 400 ack, not a fabricated id (ABD-006, ABD-007).

    The old fallback invented ``secrets.token_uuid4().hex`` when requestId was
    absent, which defeated idempotency: the same scan replayed would be treated
    as fresh. A callback without a gateway request id is malformed, period.
    """
    _tenant_with_opd()
    response = _post(APIClient(), _payload(requestId=None))

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert "requestId" in response.json()["detail"]
    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_payload_requires_timestamp():
    """A missing timestamp is a 400 ack, never a 500 (ABD-007)."""
    _tenant_with_opd()
    response = _post(APIClient(), _payload(timestamp=None))

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert "timestamp" in response.json()["detail"]
    assert ABHACallbackLog.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_payload_requires_profile():
    """A missing profile is a 400 ack, never a write with a bogus profile (ABD-007).

    The old ``profile or payload`` fallback treated the whole callback as the
    profile, which would register a patient whose demographics came from
    transport fields. A profile-share callback without a profile is malformed.
    """
    _tenant_with_opd()
    response = _post(APIClient(), _payload(profile=None))

    assert response.status_code == 400
    assert response.json()["status"] == "rejected"
    assert "profile" in response.json()["detail"]
    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_unknown_hip_id_is_rejected():
    """A HIP ID belonging to no facility cannot resolve a tenant (ABD-004).

    A callback from an unknown HIP names a resource this installation does not
    own, so it is answered 404 (resource-not-found semantics) and writes
    nothing. Previously 400; the brief's ABD-004 pin makes the status explicit.
    """
    _tenant_with_opd()
    response = _post(APIClient(), _payload(facilityId="hip-not-registered"))

    assert response.status_code == 404
    assert response.json()["status"] == "rejected"
    assert response.json()["detail"] == "Unknown facility HIP ID"
    assert ABHACallbackLog.objects.count() == 0
    assert Token.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
@pytest.mark.django_db
def test_scan_cannot_write_into_another_tenants_department():
    """A department UUID from another tenant refuses the call with 404 (ABD-013).

    The gateway is not trusted to name our departments. A supplied department id
    that is a valid UUID must resolve inside the scanned tenant; when it does
    not, the call is refused before any row is written — no patient, no token,
    no log. The old behaviour silently rerouted the scan to the first
    OPD-enabled department (a plausible misroute for a mis-issued QR code); the
    brief's ABD-013 pin makes a foreign department a hard refusal instead.
    """
    _tenant_with_opd(slug="hospital-a", hip_id="hip-a")
    _, _, department_b = _tenant_with_opd(slug="hospital-b", hip_id="hip-b")

    response = _post(
        APIClient(), _payload(facilityId="hip-a", departmentId=str(department_b.id))
    )

    assert response.status_code == 404
    assert response.json()["status"] == "rejected"
    assert Token.objects.count() == 0
    assert ABHACallbackLog.objects.count() == 0
    assert Patient.objects.count() == 0


@pytest.mark.integration
def test_health_probe_route_name_is_stable():
    """Guard against a router rename silently breaking monitoring."""
    assert reverse("common:health") == "/api/v1/health/"
