"""ABDM outbound ABHA adapter, counter-channel resilience and department QR codes
(REG-009, REG-013, ABD-013).

REG-009 (create/verify an ABHA at the counter) is shipped as an outbound
``ABDMClient`` plus a strict 503 when the sandbox is not configured: the ABDM
sandbox create/verify spec (endpoint paths, payloads, OTP flow) is unresolved,
so the ``ABDMClient`` paths below are patterned on the community-mirrored
sandbox v1 enrollment spec and must be re-verified when the official spec is
confirmed (see the REG-009 entry in ``docs/traceability.md`` Known gaps).
No endpoint may fake a 200 for a request the adapter never completed.

ABD-013 (the counter channel stays fully usable if the ABDM gateway is
unavailable) is pinned here too: registration never touches the outbound
client, and the actions that do touch it answer a structured 502 rather than
a fabricated success.

REG-013 (department-specific QR codes) pins the ``encode_data`` contract
``HIP[-counter][-department_id]`` and the audited regenerate action.

INT-002 (older and newer ABDM API versions served through one adapter) is
pinned here too: ``ABDMClient.for_adapter`` binds a client to an
``IntegrationAdapter`` row's version, and the profile-share callback answers in
the version the gateway declared. The builders themselves are pure, so their
contract is pinned without a network in ``tests/unit/test_abdm_payload_versions.py``;
this file pins the binding and the wire. **v3's shape is provisional** — the
official sandbox spec is unresolved (REG-009) — so these cases pin *our*
documented contract, not the real ABDM API.
"""
import json
import re
import uuid

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APIClient

# Signing a callback and the callback's own payload helpers live in
# ``test_abdm_callback`` — the file that pins the endpoint's behaviour — and
# ``tests/integration/conftest.py`` says so explicitly. Copying the HMAC rule
# here would let these cases sign by a different rule than the one the endpoint
# verifies, which is the mistake ``test_abdm_sandbox.py`` documents. Importing
# works because pytest puts this directory on ``sys.path``.
from test_abdm_callback import _demographic_profile, _payload, _post, _tenant_with_opd

from apps.abdm_gateway.client import (
    ABDMAdapterInactiveError,
    ABDMClient,
    ABDMRequestError,
    ABDMSandboxUnconfiguredError,
    ABDMUnsupportedVersionError,
    build_callback_ack,
    require_sandbox_base_url,
    resolve_sandbox_base_url,
)
from apps.abdm_gateway.models import ABHACallbackLog, ConsentEvent
from apps.audit.models import AuditEvent
from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.integration.models import IntegrationAdapter
from apps.opd.models import Token
from apps.patient_registry.models import IntakePoint, Patient, QRCode

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

#: The sandbox root the client builds its URLs on. Hostname carries "sbx" and
#: is https, so it satisfies the settings gate's sandbox-only predicate.
SANDBOX_BASE = "https://healthidsbx.abdm.gov.in/api/v1"

#: The ABDM API versions this deployment serves through the adapter (INT-002).
#: An older and a newer one, per SRS INT-002.
ABDM_API_VERSIONS = ("v2", "v3")

#: The key a profile-share callback declares its API version with. Deliberately
#: inside the signed body rather than a header: only the body is covered by the
#: ABDM-005 HMAC, so a version in a header could be added or stripped in transit
#: and would change the shape of the acknowledgement with nothing to detect it.
API_VERSION_KEY = "apiVersion"

#: The acknowledgement the callback returned **before** INT-002, captured from
#: the implementation as it stood with the per-scan values replaced by sentinels
#: (a token, a patient id, a grant time and a facility id differ on every run).
#: ``v2`` must reproduce these bytes: an existing gateway on the unversioned
#: contract cannot be broken by adding version support.
PRE_CHANGE_OK_ACK = {
    "status": "ok",
    "token": "<token>",
    "request_id": "req-1",
    "patient_id": "<patient>",
    "consent_event": {
        "timestamp": "<grant-time>",
        "source_app": "ABDM",
        "purpose": "registration",
        "facility_id": "<facility>",
    },
}

#: The pre-change replay acknowledgement. Its shape is not the serializer's: a
#: literal body with a ``detail`` and no consent event, so it is pinned
#: separately rather than assumed to follow the ok branch.
PRE_CHANGE_DUPLICATE_ACK = {
    "status": "duplicate",
    "detail": "This request was already processed",
    "request_id": "req-1",
    "token": "<token>",
    "patient_id": "<patient>",
}

#: How the pre-change acknowledgement rendered the consent grant time
#: (``2026-10-16T02:31:57.292506-05:00`` in the capture). Microseconds and a
#: numeric offset, not a ``Z``: a v2 ack that changed this would be a change to
#: bytes every existing gateway parses.
ACK_TIMESTAMP_FORMAT = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}[+-]\d{2}:\d{2}"


def _with_sentinels(body, request_id="req-1"):
    """Replace a body's per-scan values with the capture's sentinels."""
    return {
        "status": body["status"],
        "token": "<token>",
        "request_id": body.get("request_id", request_id),
        "patient_id": "<patient>",
        "consent_event": {
            "timestamp": "<grant-time>",
            "source_app": body["consent_event"]["source_app"],
            "purpose": body["consent_event"]["purpose"],
            "facility_id": "<facility>",
        },
    }


def _abdm_adapter(
    tenant, *, api_version=None, active=True, base_url=SANDBOX_BASE, config=None
):
    """An ``IntegrationAdapter(name="abdm")`` row, with ``api_version`` optional.

    Omitting ``api_version`` is deliberate: adapter rows created before INT-002
    and by existing callers must keep working through the field default, so the
    cases that care about the default omit it rather than restating ``"v2"``.
    """
    kwargs = {
        "tenant_id": tenant.id,
        "name": "abdm",
        "adapter_type": "rest",
        "config": {"base_url": base_url} if config is None else config,
        "active": active,
    }
    if api_version is not None:
        kwargs["api_version"] = api_version
    return IntegrationAdapter.objects.create(**kwargs)


def _exploding_transport():
    """A transport that fails the test if any HTTP is attempted."""

    def handler(request):
        raise AssertionError(f"unexpected HTTP to {request.url}")

    return httpx.MockTransport(handler)


def _make_context(name="ABHA Hospital"):
    tenant = Tenant.objects.create(
        name=name, slug=f"abha-{uuid.uuid4().hex[:8]}"
    )
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus",
        abdm_hip_id=f"HIP-ABHA-{uuid.uuid4().hex[:6].upper()}",
    )
    department = Department.objects.create(
        tenant=tenant, facility=facility, name="Medicine",
        effective_from="2026-01-01", opd_enabled=True,
    )
    return tenant, facility, department


def _make_client(tenant, username="reception"):
    user = get_user_model().objects.create_user(
        username=username, password="testpass123"
    )
    role = Role.objects.create(tenant=tenant, name=f"role-{username}", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    refresh = TenantAwareTokenSerializer.get_token(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client, user


def _make_patient(tenant, facility, uhid="UHID-ABHA-1"):
    return Patient.objects.create(
        tenant_id=tenant.id,
        uhid=uhid,
        demographics={"name": "ABHA Patient", "gender": "F", "yearOfBirth": 1985},
        abha_number="123456789012",
    )


class TestABDMClient:
    """ABDMClient builds the documented sandbox URLs and fails loudly (REG-009)."""

    def test_create_abha_posts_enrollment_create_url(self):
        captured = {}

        def handler(request):
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["content_type"] = request.headers.get("content-type")
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"healthId": "new-pat@abdm"})

        client = ABDMClient(SANDBOX_BASE, transport=httpx.MockTransport(handler))
        payload = {"aadhaar": "XXXXXXXXXXXX", "mobile": "9876543210", "otp": "123456"}

        result = client.create_abha(payload)

        assert captured["method"] == "POST"
        assert captured["url"] == f"{SANDBOX_BASE}/enrollment/createHealthIdWithPreVerified/"
        assert captured["content_type"] == "application/json"
        assert captured["payload"] == payload
        assert result == {"healthId": "new-pat@abdm"}

    def test_verify_abha_posts_mobile_otp_url_with_abha_and_otp(self):
        captured = {}

        def handler(request):
            captured["method"] = request.method
            captured["url"] = str(request.url)
            captured["payload"] = json.loads(request.content)
            return httpx.Response(200, json={"status": "SUCCESS"})

        client = ABDMClient(SANDBOX_BASE, transport=httpx.MockTransport(handler))

        result = client.verify_abha("existing@abdm", "654321")

        assert captured["method"] == "POST"
        assert captured["url"] == f"{SANDBOX_BASE}/enrollment/mobile/verifyOtp/"
        assert captured["payload"] == {"healthId": "existing@abdm", "otp": "654321"}
        assert result == {"status": "SUCCESS"}

    def test_non_2xx_response_raises_loudly(self):
        def handler(request):
            return httpx.Response(400, json={"details": [{"code": "OTP_INVALID"}]})

        client = ABDMClient(SANDBOX_BASE, transport=httpx.MockTransport(handler))

        with pytest.raises(ABDMRequestError) as excinfo:
            client.verify_abha("existing@abdm", "000000")

        assert excinfo.value.status_code == 400
        assert excinfo.value.body == {"details": [{"code": "OTP_INVALID"}]}
        assert "400" in str(excinfo.value)

    def test_2xx_non_json_body_raises_loudly(self):
        """A 2xx with a non-JSON body raises as loudly as the error path.

        A 200 that is an HTML page (WAF login, proxy error) is not a usable
        sandbox response; raising ``ABDMRequestError`` here is what stops a
        ``json.JSONDecodeError`` from escaping as an unstructured Django 500
        with no `ABDM_REQUEST_FAILED` body (REG-009).
        """
        def handler(request):
            return httpx.Response(
                200,
                text="<html><body>ABDM sandbox login</body></html>",
                headers={"content-type": "text/html"},
            )

        client = ABDMClient(SANDBOX_BASE, transport=httpx.MockTransport(handler))

        with pytest.raises(ABDMRequestError) as excinfo:
            client.create_abha({"aadhaar": "XXXXXXXXXXXX", "otp": "123456"})

        assert excinfo.value.status_code == 200
        assert excinfo.value.body == "<html><body>ABDM sandbox login</body></html>"
        assert "200" in str(excinfo.value)


class TestSandboxUrlGate:
    """The sandbox predicate refuses every URL that is not an https *sbx* host."""

    def test_accepts_sandbox_https_url(self):
        assert require_sandbox_base_url(SANDBOX_BASE) == SANDBOX_BASE

    def test_rejects_insecure_url(self):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured):
            require_sandbox_base_url(SANDBOX_BASE.replace("https://", "http://"))

    def test_rejects_non_sbx_host(self):
        from django.core.exceptions import ImproperlyConfigured

        with pytest.raises(ImproperlyConfigured):
            require_sandbox_base_url("https://healthid.abdm.gov.in/api/v1")


class TestSandboxBaseUrlResolution:
    """Env wins; the tenant's ABDM IntegrationAdapter is the fallback (REG-009)."""

    def test_env_wins_over_adapter(self, monkeypatch):
        tenant, _, _ = _make_context()
        from apps.integration.models import IntegrationAdapter

        IntegrationAdapter.objects.create(
            tenant_id=tenant.id, name="abdm", adapter_type="rest",
            config={"base_url": "https://healthidsbx.adapter.example/api/v1"},
        )
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL",
            SANDBOX_BASE,
        )
        assert resolve_sandbox_base_url(tenant.id) == SANDBOX_BASE

    def test_falls_back_to_tenant_adapter(self, monkeypatch):
        tenant, _, _ = _make_context()
        from apps.integration.models import IntegrationAdapter

        IntegrationAdapter.objects.create(
            tenant_id=tenant.id, name="abdm", adapter_type="rest",
            config={"base_url": SANDBOX_BASE},
        )
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", ""
        )
        assert resolve_sandbox_base_url(tenant.id) == SANDBOX_BASE

    def test_returns_empty_when_nothing_is_configured(self, monkeypatch):
        tenant, _, _ = _make_context()
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", ""
        )
        assert resolve_sandbox_base_url(tenant.id) == ""


class TestAbhaActionsWhenUnconfigured:
    """With no sandbox URL, the ABHA actions fail closed (REG-009).

    The 503 body is a structured error pinned on the single stable code
    ``ABDM_SANDBOX_UNCONFIGURED``; there is deliberately no success shape for
    a request whose outbound call could not exist.
    """

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client, self.user = _make_client(self.tenant)
        self.patient = _make_patient(self.tenant, self.facility)

    def _post(self, action, data=None):
        return self.client.post(
            f"/api/v1/patients/{self.patient.id}/{action}/",
            data or {},
            format="json",
        )

    def _assert_unconfigured(self, response):
        assert response.status_code == 503, response.content
        body = response.json()
        assert body["status"] == "unavailable"
        assert body["code"] == "ABDM_SANDBOX_UNCONFIGURED"
        assert body["detail"]

    def test_create_returns_503_structured_when_unconfigured(self):
        self._assert_unconfigured(self._post("abha/create"))

    def test_verify_returns_503_structured_when_unconfigured(self):
        self._assert_unconfigured(self._post("abha/verify", {"otp": "123456"}))

    def test_abha_actions_require_authentication(self):
        anonymous = APIClient()
        response = anonymous.post(
            f"/api/v1/patients/{self.patient.id}/abha/create/", {}, format="json"
        )
        assert response.status_code in (401, 403)

    def test_foreign_patient_answers_404_not_503(self):
        """Scoping wins over configurability: an unknown id must never leak."""
        other_tenant, _, _ = _make_context("Other Hospital")
        foreign_patient = _make_patient(
            other_tenant, Facility.objects.get(tenant=other_tenant), uhid="UHID-ABHA-F"
        )
        response = self.client.post(
            f"/api/v1/patients/{foreign_patient.id}/abha/create/", {}, format="json"
        )
        assert response.status_code == 404


class TestAbhaRequestBodyValidation:
    """Non-object request bodies answer the precise 400, before any dispatch.

    A JSON array (or any non-object) body must not be silently coerced to
    ``{}`` and forwarded to the sandbox: that would both send a create the
    client never wrote and mislabel the failure as the sandbox's. The 400
    carries the stable ``ABDM_REQUEST_INVALID`` code and is answered before
    any adapter dispatch, configured or not (REG-009).
    """

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client, self.user = _make_client(self.tenant)
        self.patient = _make_patient(self.tenant, self.facility)

    def test_create_rejects_non_object_body_with_stable_400(self):
        response = self.client.post(
            f"/api/v1/patients/{self.patient.id}/abha/create/",
            data=[{"aadhaar": "XXXXXXXXXXXX"}],
            format="json",
        )
        assert response.status_code == 400, response.content
        body = response.json()
        assert body["status"] == "error"
        assert body["code"] == "ABDM_REQUEST_INVALID"
        assert body["detail"]

    def test_verify_rejects_non_object_body_with_stable_400(self):
        response = self.client.post(
            f"/api/v1/patients/{self.patient.id}/abha/verify/",
            data=["not-an-object"],
            format="json",
        )
        assert response.status_code == 400, response.content
        body = response.json()
        assert body["status"] == "error"
        assert body["code"] == "ABDM_REQUEST_INVALID"
        assert body["detail"]


class TestAbhaActionsWhenConfigured:
    """A configured sandbox means the action delegates to the ABDM client."""

    def test_create_delegates_to_the_client(self, monkeypatch):
        tenant, facility, _ = _make_context()
        client, _ = _make_client(tenant)
        patient = _make_patient(tenant, facility)

        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        from apps.patient_registry import views

        created = {}

        class StubClient:
            def __init__(self, base_url, **kwargs):
                created["base_url"] = base_url

            def create_abha(self, payload):
                created["payload"] = payload
                return {"healthId": "new@abdm", "status": "SUCCESS"}

        monkeypatch.setattr(views, "ABDMClient", StubClient)

        payload = {"aadhaar": "XXXXXXXXXXXX", "mobile": "9876543210", "otp": "111111"}
        response = client.post(
            f"/api/v1/patients/{patient.id}/abha/create/", payload, format="json"
        )

        assert response.status_code == 200, response.content
        assert created["base_url"] == SANDBOX_BASE
        assert created["payload"] == payload
        assert response.json() == {"healthId": "new@abdm", "status": "SUCCESS"}

    def test_transport_failure_answers_502_sandbox_unreachable(self, monkeypatch):
        """A failure before any response must surface, never a fake OK (REG-009)."""
        tenant, facility, _ = _make_context()
        client, _ = _make_client(tenant)
        patient = _make_patient(tenant, facility)
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        from apps.patient_registry import views

        class RaisingClient:
            def __init__(self, base_url, **kwargs):
                pass

            def create_abha(self, payload):
                raise httpx.ConnectError("sandbox down")

        monkeypatch.setattr(views, "ABDMClient", RaisingClient)

        response = client.post(
            f"/api/v1/patients/{patient.id}/abha/create/",
            {"aadhaar": "XXXXXXXXXXXX", "mobile": "9876543210", "otp": "111111"},
            format="json",
        )

        assert response.status_code == 502, response.content
        body = response.json()
        assert body["code"] == "ABDM_SANDBOX_UNREACHABLE"
        assert body["status"] == "error"

    def test_non_2xx_sandbox_response_is_mirrored(self, monkeypatch):
        """A 400 from the sandbox is mirrored, keeping its code surface (REG-009)."""
        tenant, facility, _ = _make_context()
        client, _ = _make_client(tenant)
        patient = _make_patient(tenant, facility)
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        from apps.patient_registry import views

        class RejectingClient:
            def __init__(self, base_url, **kwargs):
                pass

            def verify_abha(self, abha, otp):
                raise ABDMRequestError(400, {"details": [{"code": "OTP_INVALID"}]})

        monkeypatch.setattr(views, "ABDMClient", RejectingClient)

        response = client.post(
            f"/api/v1/patients/{patient.id}/abha/verify/",
            {"otp": "000000"},
            format="json",
        )

        assert response.status_code == 400, response.content
        body = response.json()
        assert body["code"] == "ABDM_REQUEST_FAILED"
        assert "OTP_INVALID" in body["detail"]

    def test_non_json_success_body_answers_502_structured(self, monkeypatch):
        """A 2xx non-JSON sandbox body maps to a structured 502, never a 500.

        The client raises ``ABDMRequestError(200, text)`` for an HTML login
        page on a 2xx; here the view maps that 2xx status to 502 so the
        client always sees the stable `ABDM_REQUEST_FAILED` body instead of an
        unstructured ``json.JSONDecodeError``->Django 500 (REG-009).
        """
        tenant, facility, _ = _make_context()
        client, _ = _make_client(tenant)
        patient = _make_patient(tenant, facility)
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        from apps.patient_registry import views

        class HtmlClient:
            def __init__(self, base_url, **kwargs):
                pass

            def create_abha(self, payload):
                raise ABDMRequestError(200, "<html><body>sandbox login</body></html>")

        monkeypatch.setattr(views, "ABDMClient", HtmlClient)

        response = client.post(
            f"/api/v1/patients/{patient.id}/abha/create/",
            {"aadhaar": "XXXXXXXXXXXX"},
            format="json",
        )

        assert response.status_code == 502, response.content
        body = response.json()
        assert body["status"] == "error"
        assert body["code"] == "ABDM_REQUEST_FAILED"
        assert "sandbox login" in body["detail"]


class TestCounterChannelSurvivesGatewayOutage:
    """ABD-013: a dead ABDM gateway must not take the counter down with it.

    The counter's job is registering patients and issuing tokens, neither of
    which depends on the ABDM gateway. Pinning that with a *configured* base
    URL that cannot be reached is the point: an unconfigured sandbox is a
    trivially offline gateway, whereas a configured-but-unreachable one is the
    state a hospital is actually in when the network or the gateway is down,
    and it is where a shared client could hold a request hostage.

    The base URL is sandbox-shaped so it passes ``require_sandbox_base_url``
    (the gate that keeps this client away from production ABDM), and the
    transport is the real ``ABDMClient`` failing to connect — the same
    ``httpx.TransportError`` a real outage raises, not a stub of it.
    """

    UNREACHABLE_BASE = "https://sbx-unreachable.example.invalid/api/v1"

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client, _ = _make_client(self.tenant)

    def _unreachable_client(self, monkeypatch):
        """Point the views' client at a transport that cannot connect."""

        def _unreachable(request):
            raise httpx.ConnectError(
                "connection refused", request=request
            )

        from apps.patient_registry import views

        class UnreachableClient(ABDMClient):
            def __init__(self, base_url, **kwargs):
                super().__init__(
                    base_url, transport=httpx.MockTransport(_unreachable), **kwargs
                )

        monkeypatch.setattr(views, "ABDMClient", UnreachableClient)

    @override_settings(ABDM_SANDBX_BASE_URL=UNREACHABLE_BASE)
    def test_registration_succeeds_with_the_gateway_unreachable(self, monkeypatch):
        """POST /patients/ never touches the outbound client (ABD-013).

        Registration is a local write: UHID, demographics, the server-issued
        token. If a future change makes it depend on the gateway, this fails
        — and that failure is the requirement being broken, not the test.
        """
        self._unreachable_client(monkeypatch)

        payload = {
            "demographics": {
                "name": "Counter Patient",
                "yearOfBirth": 1990,
                "gender": "F",
            }
        }
        response = self.client.post("/api/v1/patients/", payload, format="json")

        assert response.status_code == 201, response.content
        body = response.json()
        assert body["uhid"].startswith("UHID-")
        assert Patient.objects.filter(uhid=body["uhid"]).count() == 1

    @override_settings(ABDM_SANDBX_BASE_URL=UNREACHABLE_BASE)
    def test_abha_create_answers_structured_502_not_a_fake_success(self, monkeypatch):
        """The gateway path fails loudly while the counter path does not.

        Same request, same unreachable gateway, opposite outcomes: the ABHA
        action answers 502 with the stable ``ABDM_SANDBOX_UNREACHABLE`` code
        (a request the adapter could not complete must never look like a
        created ABHA), and the client can see the difference.
        """
        self._unreachable_client(monkeypatch)
        patient = _make_patient(self.tenant, self.facility)

        response = self.client.post(
            f"/api/v1/patients/{patient.id}/abha/create/",
            {"aadhaar": "XXXXXXXXXXXX", "mobile": "9876543210", "otp": "111111"},
            format="json",
        )

        assert response.status_code == 502, response.content
        body = response.json()
        assert body["status"] == "error"
        assert body["code"] == "ABDM_SANDBOX_UNREACHABLE"
        assert body["detail"]
        patient.refresh_from_db()
        # The failed gateway call wrote nothing onto the patient either: an
        # outbound create that could not happen must not clear or mint an ABHA.
        assert patient.abha_number == "123456789012"


class TestDepartmentQRCodes:
    """department-scoped encode_data and the audited regenerate (REG-013)."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()
        self.client, self.user = _make_client(self.tenant)

    def _create_qr(self, **overrides):
        payload = {"facility": str(self.facility.id), "department": str(self.department.id), **overrides}
        response = self.client.post("/api/v1/qr-codes/", payload, format="json")
        return response

    def test_create_with_department_appends_department_segment(self):
        response = self._create_qr()
        assert response.status_code == 201, response.content

        qr = QRCode.objects.get(pk=response.json()["id"])
        assert qr.encode_data == f"{self.facility.abdm_hip_id}-{self.department.id}"
        assert qr.department_id == self.department.id

    def test_create_with_counter_and_department_keeps_both_segments(self):
        intake_point = IntakePoint.objects.create(
            tenant_id=self.tenant.id, facility=self.facility,
            type="opd", counter_id="CTR-01",
        )
        response = self._create_qr(
            intake_point=str(intake_point.id), department=str(self.department.id)
        )
        assert response.status_code == 201, response.content

        qr = QRCode.objects.get(pk=response.json()["id"])
        assert qr.encode_data == (
            f"{self.facility.abdm_hip_id}-CTR-01-{self.department.id}"
        )

    def test_facility_only_qr_keeps_hip_prefix(self):
        response = self._create_qr(department="")
        assert response.status_code == 201, response.content
        qr = QRCode.objects.get(pk=response.json()["id"])
        assert qr.encode_data == self.facility.abdm_hip_id
        assert qr.department_id is None

    def test_cross_tenant_department_is_rejected(self):
        other_tenant, _, _ = _make_context("Other Hospital")
        foreign_department = Department.objects.get(tenant=other_tenant)

        response = self._create_qr(department=str(foreign_department.id))
        assert response.status_code == 400, response.content
        assert QRCode.objects.count() == 0

    def test_cross_tenant_intake_point_is_rejected(self):
        """A foreign intake point is refused with zero rows written (REG-013).

        The intake_point FK drives which ABDM counter queue the encoded scan
        string routes callbacks into, so accepting another hospital's row
        would seed callbacks into a foreign queue — the same tenant-horizon
        defect as a foreign department. ``validate_intake_point`` pins it
        inside the requesting tenant, so the 400 lands before any row exists.
        """
        other_tenant, other_facility, _ = _make_context("Other Hospital")
        foreign_intake = IntakePoint.objects.create(
            tenant_id=other_tenant.id,
            facility=other_facility,
            type="opd",
            counter_id="CTR-FOREIGN",
        )

        response = self._create_qr(intake_point=str(foreign_intake.id))
        assert response.status_code == 400, response.content
        assert QRCode.objects.count() == 0

    def test_regenerate_rebuilds_encode_data_and_audits(self):
        qr = QRCode.objects.create(
            tenant_id=self.tenant.id,
            facility=self.facility,
            encode_data=self.facility.abdm_hip_id,
        )
        qr.department = self.department
        qr.save(update_fields=["department"])

        response = self.client.post(f"/api/v1/qr-codes/{qr.id}/regenerate/")
        assert response.status_code == 200, response.content

        qr.refresh_from_db()
        assert qr.encode_data == f"{self.facility.abdm_hip_id}-{self.department.id}"
        assert qr.regenerated_at is not None

        event = AuditEvent.objects.get(
            tenant_id=self.tenant.id,
            action="update",
            entity_type="qr_code",
            entity_id=str(qr.id),
            source="qr.regenerate",
        )
        # auth.User keeps an integer pk while audit.user_id is a UUIDField, so
        # the int pk is stored coerced (uuid.UUID(int=pk)) — same convention as
        # test_authentication.py::_uuid_pk.
        assert event.user_id == uuid.UUID(int=self.user.pk)


# --- INT-002: one adapter, older and newer API versions ------------------------
#
# Two dispatch points, pinned from opposite ends: ``ABDMClient.for_adapter``
# binds an outbound client to an adapter row's version (below), and the
# profile-share callback answers in the version the gateway declared (further
# below). The payload builders both dispatch to are pure and pinned in
# ``tests/unit/test_abdm_payload_versions.py``.


class TestVersionedAdapterBinding:
    """``for_adapter`` binds a version and a sandbox URL, or refuses (INT-002)."""

    @pytest.mark.parametrize("api_version", ABDM_API_VERSIONS, ids=ABDM_API_VERSIONS)
    def test_for_adapter_binds_the_adapters_version(self, api_version, monkeypatch):
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant, api_version=api_version)
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        client = ABDMClient.for_adapter(adapter)

        assert client.api_version == api_version

    def test_for_adapter_defaults_to_v2_when_the_row_does_not_declare(self, monkeypatch):
        """A row written before INT-002 has no version and must still work.

        The field default is ``"v2"`` precisely so this case is the common one:
        every adapter row that exists today is a ``v2`` row.
        """
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant)
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        assert adapter.api_version == "v2"
        assert ABDMClient.for_adapter(adapter).api_version == "v2"

    @pytest.mark.parametrize("api_version", ABDM_API_VERSIONS, ids=ABDM_API_VERSIONS)
    def test_for_adapter_builds_the_version_shaped_profile_share_body(
        self, api_version, monkeypatch
    ):
        """The binding is not a label: the body the client would post differs."""
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant, api_version=api_version)
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )
        payload = {"requestId": "req-1", "profile": {"abhaNumber": "123456789012"}}

        body = ABDMClient.for_adapter(adapter).profile_share_body(payload)

        assert body["requestId"] == "req-1"
        # v2 is the pre-versioning body exactly — it must gain no version stamp,
        # which is the whole reason the pre-change bytes are unchanged. v3
        # declares the contract it is speaking.
        assert body.get("apiVersion") == ("v3" if api_version == "v3" else None)
        assert payload == {"requestId": "req-1", "profile": {"abhaNumber": "123456789012"}}

    def test_a_v2_client_puts_the_pre_change_bytes_on_the_wire(self, monkeypatch):
        """The outbound half of the byte-for-byte claim, at the transport itself.

        ``create_abha`` is ABHA *enrollment* (REG-009), not profile share, so it
        is deliberately not routed through the version builder — its payload is
        the sandbox spec's and is passed through verbatim. This pins the
        consequence: binding a v2 adapter changes nothing an existing counter
        deployment puts on the wire, because the v2 client still posts exactly
        the bytes the pre-INT-002 client posted. Asserted on the request
        ``httpx`` actually built, not on a dict.
        """
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant, api_version="v2")
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )
        captured = {}

        def handler(request):
            captured["body"] = request.content
            return httpx.Response(200, json={"status": "SUCCESS"})

        payload = {"aadhaar": "XXXXXXXXXXXX", "mobile": "9876543210", "otp": "123456"}
        ABDMClient.for_adapter(adapter, transport=httpx.MockTransport(handler)).create_abha(
            payload
        )

        assert captured["body"] == (
            b'{"aadhaar":"XXXXXXXXXXXX","mobile":"9876543210","otp":"123456"}'
        )

    def test_for_adapter_calls_the_adapters_own_sandbox_url(self, monkeypatch):
        """The base URL still comes from the single existing resolver.

        Environment first, then this adapter's row — one precedence, the one
        ``resolve_sandbox_base_url`` already owns. What is pinned here is that
        the adapter's own URL is honoured when the environment is silent.
        """
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant)
        monkeypatch.setattr("apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", "")
        captured = {}

        def handler(request):
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"status": "SUCCESS"})

        client = ABDMClient.for_adapter(
            adapter, transport=httpx.MockTransport(handler)
        )
        client.verify_abha("existing@abdm", "654321")

        assert captured["url"] == f"{SANDBOX_BASE}/enrollment/mobile/verifyOtp/"

    def test_for_adapter_reads_the_row_it_was_handed(self, monkeypatch):
        """Not a re-query: the binding is the row in hand, whoever else exists.

        ``for_adapter`` used to call ``resolve_sandbox_base_url(tenant_id)``,
        which queried for the newest active ``abdm`` row and returned *that* row's
        URL. It agreed with the adapter in hand only by accident of
        ``unique_together(tenant_id, name)``. Here the row in hand is unsaved and
        carries a different URL from the one stored for the tenant, so a re-query
        is observably wrong rather than merely redundant.
        """
        tenant, _, _ = _make_context()
        _abdm_adapter(tenant, base_url="https://abha-sbx.abdm.gov.in/api/v1")
        monkeypatch.setattr("apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", "")
        captured = {}

        def handler(request):
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"status": "SUCCESS"})

        handed = IntegrationAdapter(
            tenant_id=tenant.id, name="abdm", adapter_type="rest", active=True,
            config={"base_url": "https://profile-sbx.abdm.gov.in/api/v1"},
        )
        ABDMClient.for_adapter(handed, transport=httpx.MockTransport(handler)).verify_abha(
            "existing@abdm", "654321"
        )

        assert captured["url"].startswith("https://profile-sbx.abdm.gov.in/api/v1")

    def test_for_adapter_binds_the_default_for_an_unrecognised_row_version(self, caplog, monkeypatch):
        """A config typo must not take the tenant's channel down (INT-002).

        ``api_version="v9"`` on one adapter row used to make **every** scan-and-
        share callback for that tenant answer 422 — no patient, no token, no
        consent row — because the row is read before any write. It now binds the
        default shape with a warning, so the channel keeps working and the
        operator is told which label to fix.
        """
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant, api_version="v9")
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        with caplog.at_level("WARNING", logger="apps.abdm_gateway.client"):
            client = ABDMClient.for_adapter(adapter, transport=_exploding_transport())

        assert client.api_version == "v2"
        assert str(tenant.id) in caplog.text
        assert "'v9'" in caplog.text

    def test_for_adapter_resolves_an_aliased_row_version_to_its_target(self, monkeypatch):
        """The legacy label on a row is served as the alias it names, not refused."""
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant, api_version="v1.0")
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        client = ABDMClient.for_adapter(adapter, transport=_exploding_transport())

        assert adapter.api_version == "v1.0"
        assert client.api_version == "v2"

    def test_for_adapter_refuses_a_non_string_row_version(self, monkeypatch):
        """A row whose ``api_version`` is not a label is a broken row, not a dialect.

        Pinned against a **hand-built** instance on purpose: ``api_version`` is a
        ``CharField``, so anything saved through the ORM is stored as its string
        repr and comes back a string (asserted below) — the case that reaches
        this guard is an in-memory adapter handed straight to the factory, which
        is exactly what a future non-text column or a caller constructing a row
        would look like. Refusing it is the same call the builders make, so there
        is one rule rather than two.
        """
        tenant, _, _ = _make_context()
        saved = _abdm_adapter(tenant)
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )
        # The premise, pinned: a value written through the ORM comes back a string.
        IntegrationAdapter.objects.filter(pk=saved.pk).update(
            api_version={"major": 3}
        )
        assert isinstance(
            IntegrationAdapter.objects.get(pk=saved.pk).api_version, str
        )
        hand_built = IntegrationAdapter(
            tenant_id=tenant.id, name="abdm", adapter_type="rest",
            active=True, config={"base_url": SANDBOX_BASE}, api_version={"major": 3},
        )

        with pytest.raises(ABDMUnsupportedVersionError):
            ABDMClient.for_adapter(hand_built, transport=_exploding_transport())

    def test_for_adapter_refuses_an_inactive_adapter(self, monkeypatch):
        """``active=False`` is the operator's off-switch, so it is honoured here.

        The base-URL resolver already filters on ``active=True``; binding a
        client straight from a row would otherwise be a way around that filter.
        """
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant, active=False)
        monkeypatch.setattr(
            "apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", SANDBOX_BASE
        )

        with pytest.raises(ABDMAdapterInactiveError):
            ABDMClient.for_adapter(adapter, transport=_exploding_transport())

    def test_for_adapter_refuses_a_non_sandbox_base_url(self, monkeypatch):
        """An adapter row must not be able to point the client at production ABDM."""
        from django.core.exceptions import ImproperlyConfigured

        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant, base_url="https://healthid.abdm.gov.in/api/v1")
        monkeypatch.setattr("apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", "")

        with pytest.raises(ImproperlyConfigured):
            ABDMClient.for_adapter(adapter, transport=_exploding_transport())

    def test_for_adapter_refuses_when_no_sandbox_base_url_is_configured(self, monkeypatch):
        """Unconfigured is refused, not answered with a request to a relative URL."""
        tenant, _, _ = _make_context()
        adapter = _abdm_adapter(tenant, config={})
        monkeypatch.setattr("apps.abdm_gateway.client.settings.ABDM_SANDBX_BASE_URL", "")

        with pytest.raises(ABDMSandboxUnconfiguredError):
            ABDMClient.for_adapter(adapter, transport=_exploding_transport())

    def test_the_constructor_binds_the_default_for_an_unrecognised_version(self, caplog):
        """The same rule as the row: a string label is served, never refused.

        Without this the guard would live in one factory method, and a caller
        constructing a client directly could get a different contract.
        """
        with caplog.at_level("WARNING", logger="apps.abdm_gateway.client"):
            client = ABDMClient(SANDBOX_BASE, api_version="v9")

        assert client.api_version == "v2"
        assert "'v9'" in caplog.text

    def test_the_constructor_refuses_a_non_string_version_too(self):
        """A list, an object or a number is malformed, and malformed is refused."""
        with pytest.raises(ABDMUnsupportedVersionError):
            ABDMClient(SANDBOX_BASE, api_version=["v3"])


class TestCallbackApiVersionDispatch:
    """The callback answers in the version the gateway speaks (INT-002).

    Version resolution precedence, and the order it runs in, is the contract
    here: the version the **request declares**, else the tenant's **active
    ``abdm`` adapter's** version, else ``"v2"``. It is validated after
    authentication, the mandatory-key check and the timestamp check, and before
    any write, so an unauthenticated caller cannot enumerate supported versions
    and a refused call leaves no row behind.

    **A label is never refused; only a malformed declaration is.** An exact label
    is served in its own shape, a documented alias in the shape it names, and an
    unrecognised label in the default shape with a warning. Only a **malformed**
    declaration — a list, an object or a number — is answered ``422``. The
    rationale is recorded once, on ``client.resolve_api_version``.
    """

    def test_a_v2_ack_is_the_pre_change_acknowledgement_byte_for_byte(self):
        """INT-002 must not move the bytes an existing gateway already parses."""
        _tenant_with_opd()

        response = _post(APIClient(), _payload(apiVersion="v2"))
        body = response.json()

        assert response.status_code == 200, response.content
        assert _with_sentinels(body) == PRE_CHANGE_OK_ACK
        # Key order is part of the captured bytes, and so is the rendering of
        # the consent grant time (microseconds and a numeric offset, not "Z").
        assert list(body) == list(PRE_CHANGE_OK_ACK)
        assert re.fullmatch(ACK_TIMESTAMP_FORMAT, body["consent_event"]["timestamp"])

    def test_a_v3_ack_answers_in_the_newer_vocabulary(self):
        _tenant_with_opd()

        response = _post(APIClient(), _payload(apiVersion="v3"))
        body = response.json()

        assert response.status_code == 200, response.content
        assert list(body) == [
            "apiVersion", "status", "token", "requestId", "patientId", "consentEvent",
        ]
        assert body["apiVersion"] == "v3"
        assert body["status"] == "ok"
        assert body["requestId"] == "req-1"
        assert list(body["consentEvent"]) == [
            "timestamp", "sourceApp", "purpose", "facilityId",
        ]
        assert body["consentEvent"]["sourceApp"] == "ABDM"
        assert body["consentEvent"]["purpose"] == "registration"
        assert re.fullmatch(ACK_TIMESTAMP_FORMAT, body["consentEvent"]["timestamp"])

    def test_an_undeclared_callback_falls_back_to_the_pre_change_shape(self):
        """No declaration, no adapter row: the unversioned contract, unchanged."""
        _tenant_with_opd()

        body = _post(APIClient(), _payload()).json()

        assert _with_sentinels(body) == PRE_CHANGE_OK_ACK

    def test_the_endpoint_ack_is_exactly_what_the_registry_builder_produces(self):
        """Ties the wire to the pure builders so the two cannot drift apart.

        The endpoint could hand-build a body that *looks* versioned; this is what
        proves it is the registry's builder's output, for the same values.
        """
        _tenant_with_opd()

        body = _post(APIClient(), _payload(apiVersion="v3")).json()
        canonical = {
            "status": body["status"],
            "token": body["token"],
            "request_id": body["requestId"],
            "patient_id": body["patientId"],
            "consent_event": {
                "timestamp": body["consentEvent"]["timestamp"],
                "source_app": body["consentEvent"]["sourceApp"],
                "purpose": body["consentEvent"]["purpose"],
                "facility_id": body["consentEvent"]["facilityId"],
            },
        }

        assert body == build_callback_ack("v3", canonical)

    def test_a_malformed_version_cannot_ride_a_replay(self):
        """Pins *where* the version check sits, not just that it exists.

        The declared-declaration check runs before the idempotency
        early-return, and the replay branch depends on it. Moving it down into
        the transaction — the natural-looking place for it, next to the rest of
        the resolution — makes this case answer **500**, not 200: the replay
        branch never reaches a check inside the atomic block, so it hands the
        list straight to the ack builder and the resolver raises with no handler.
        Reproduced by the Task 28 re-review (F8); the early check is therefore
        load-bearing twice over, which is the kind of coupling a test exists to
        make visible.
        """
        _tenant_with_opd()
        client = APIClient()
        _post(client, _payload(apiVersion="v2"))

        replay = _post(client, _payload(apiVersion=["v2"]))

        assert replay.status_code == 422, replay.content
        assert replay.json()["status"] == "rejected"
        # The stored outcome is untouched: the refusal re-ran nothing.
        assert ABHACallbackLog.objects.count() == 1
        assert Token.objects.count() == 1
        assert Patient.objects.count() == 1

    @pytest.mark.parametrize("declared", ["v1.0", "v9", "V3"])
    def test_a_declared_version_label_is_never_refused(self, declared):
        """The Critical: a label that worked before INT-002 must still work.

        Every one of these returned a complete 200 flow (row written, consent
        recorded, token issued) at ``f1c0556`` and returned a permanent 422 with
        nothing written afterwards. ``v1.0`` is the label this repository's own
        architecture doc and sandbox replay use, so refusing it took down the
        flow the project documents.
        """
        _tenant_with_opd()

        response = _post(APIClient(), _payload(apiVersion=declared))

        assert response.status_code == 200, response.content
        assert response.json()["status"] == "ok"
        assert ABHACallbackLog.objects.count() == 1
        assert Token.objects.count() == 1
        assert Patient.objects.count() == 1
        assert ConsentEvent.objects.count() == 1

    @pytest.mark.parametrize("declared", ["v1.0", "1.0"])
    def test_an_alias_declared_version_is_served_in_the_aliased_shape(self, declared, caplog):
        """Not merely "200": the body is the aliased (v2) shape, byte for byte.

        Asserted against the pre-change capture, key order included, so a label
        that resolves to ``v2`` cannot be answered in some other shape and still
        pass. **No fallback warning** is asserted too: an alias and an
        unrecognised label produce the same body, so the absence of the warning
        is the only thing that proves the alias table did the work rather than
        the default doing it.
        """
        _tenant_with_opd()

        with caplog.at_level("WARNING", logger="apps.abdm_gateway.client"):
            body = _post(APIClient(), _payload(apiVersion=declared)).json()

        assert _with_sentinels(body) == PRE_CHANGE_OK_ACK
        assert list(body) == list(PRE_CHANGE_OK_ACK)
        assert declared not in body
        assert [
            record for record in caplog.records if record.name == "apps.abdm_gateway.client"
        ] == [], caplog.text

    def test_an_unrecognised_label_is_served_in_the_default_shape_with_a_warning(
        self, caplog
    ):
        """Served, in the pre-versioning shape, and the operator is told."""
        tenant, _, _ = _tenant_with_opd()

        with caplog.at_level("WARNING", logger="apps.abdm_gateway.client"):
            response = _post(APIClient(), _payload(apiVersion="V3"))
        body = response.json()

        assert response.status_code == 200, response.content
        assert _with_sentinels(body) == PRE_CHANGE_OK_ACK
        assert list(body) == list(PRE_CHANGE_OK_ACK)
        # Case is not folded, so this is a fallback and not a v3 acknowledgement.
        assert "apiVersion" not in body
        assert str(tenant.id) in caplog.text
        assert "'V3'" in caplog.text

    def test_a_replay_declaring_an_alias_is_answered_in_the_aliased_shape(self):
        """The replay branch resolves the declaration too, not just the first pass.

        The early return hands a version to ``build_callback_ack``; if it used
        the raw declaration, an alias or an unknown label would either raise
        (a 500 on an honest gateway retry) or build a shape nobody asked for.
        """
        _tenant_with_opd()
        client = APIClient()
        _post(client, _payload())

        replay = _post(client, _payload(apiVersion="v1.0"))

        assert replay.status_code == 200, replay.content
        body = replay.json()
        assert body["status"] == "duplicate"
        assert body["request_id"] == "req-1"
        assert "patient_id" in body and "requestId" not in body

    @pytest.mark.parametrize("declared", [["v9"], {"version": "v3"}, 3])
    def test_a_malformed_declared_version_is_422_naming_the_supported_set(self, declared):
        """The one refusal: a payload that cannot be read as a version at all."""
        _tenant_with_opd()

        response = _post(APIClient(), _payload(apiVersion=declared))

        assert response.status_code == 422, response.content
        assert response.json()["status"] == "rejected"
        detail = response.json()["detail"]
        for supported in ABDM_API_VERSIONS:
            assert supported in detail

    def test_a_malformed_declared_version_writes_nothing(self):
        """Refused before any write: no patient, no token, no ledger row."""
        _tenant_with_opd()

        _post(APIClient(), _payload(apiVersion=["v9"]))

        assert ABHACallbackLog.objects.count() == 0
        assert Token.objects.count() == 0
        assert Patient.objects.count() == 0
        assert ConsentEvent.objects.count() == 0

    @pytest.mark.parametrize("declared", ["v9", ["v9"], {"version": "v3"}])
    def test_an_unauthenticated_caller_cannot_probe_supported_versions(self, declared):
        """The version check runs *after* authentication (ABD-005).

        Answering 422 to an unsigned call would turn the supported set into an
        unauthenticated oracle, and the 422 body names the set explicitly. The
        string case is pinned alongside the malformed one because both must be
        authenticated before anything is said about the vocabulary.
        """
        _tenant_with_opd()

        response = APIClient().post(
            "/api/v1/abdm-callbacks/", _payload(apiVersion=declared), format="json"
        )

        assert response.status_code == 401
        assert ABHACallbackLog.objects.count() == 0

    def test_a_missing_mandatory_key_is_still_400_even_with_a_malformed_version(self):
        """Pins the order: the mandatory-key check runs before the version check.

        If the version check came first, a malformed callback would be told its
        API version is unprocessable — a different diagnosis for the same broken
        payload, and one that leaks the supported set to a merely-malformed call.
        """
        _tenant_with_opd()

        response = _post(APIClient(), _payload(apiVersion=["v9"], requestId=None))

        assert response.status_code == 400, response.content
        assert "requestId" in response.json()["detail"]

    def test_a_stale_timestamp_is_still_400_even_with_a_malformed_version(self):
        """Same ordering pin for the timestamp check (ABD-007)."""
        _tenant_with_opd()

        response = _post(
            APIClient(), _payload(apiVersion=["v9"], timestamp="2020-01-01T00:00:00Z")
        )

        assert response.status_code == 400, response.content
        assert response.json()["detail"] == "Invalid or stale timestamp"

    def test_the_tenants_adapter_version_shapes_an_undeclared_ack(self):
        """No declaration: the tenant's active adapter decides."""
        tenant, _, _ = _tenant_with_opd()
        _abdm_adapter(tenant, api_version="v3")

        response = _post(APIClient(), _payload())
        body = response.json()

        assert body["apiVersion"] == "v3"
        assert "requestId" in body

    def test_the_declared_version_wins_over_the_adapter(self):
        """Precedence, first rung: what the gateway says it is speaking."""
        tenant, _, _ = _tenant_with_opd()
        _abdm_adapter(tenant, api_version="v3")

        body = _post(APIClient(), _payload(apiVersion="v2")).json()

        assert list(body) == list(PRE_CHANGE_OK_ACK)

    def test_an_inactive_adapter_does_not_shape_the_ack(self):
        """The lookup filters on ``active=True``, like the base-URL resolver."""
        tenant, _, _ = _tenant_with_opd()
        _abdm_adapter(tenant, api_version="v3", active=False)

        body = _post(APIClient(), _payload()).json()

        assert list(body) == list(PRE_CHANGE_OK_ACK)

    def test_an_unrecognised_adapter_version_serves_the_default_shape(self, caplog):
        """One mis-typed row must not 422 every scan-and-share callback (INT-002).

        The adapter row is read before any write, so refusing an unrecognised
        label on it does not fail one scan: it fails the tenant's whole intake
        channel, permanently, until somebody fixes a JSON column nobody is
        watching. The scan is therefore served in the default shape with a
        warning naming the row's label.
        """
        tenant, _, _ = _tenant_with_opd()
        _abdm_adapter(tenant, api_version="v3.1")

        with caplog.at_level("WARNING", logger="apps.abdm_gateway.client"):
            response = _post(APIClient(), _payload())
        body = response.json()

        assert response.status_code == 200, response.content
        assert _with_sentinels(body) == PRE_CHANGE_OK_ACK
        assert str(tenant.id) in caplog.text
        assert "'v3.1'" in caplog.text
        # The scan completed: the channel is alive, which is the whole point.
        assert ABHACallbackLog.objects.count() == 1
        assert Token.objects.count() == 1
        assert Patient.objects.count() == 1

    def test_an_aliased_adapter_version_shapes_the_ack_as_its_target(self, caplog):
        """A row naming the legacy label is served as the alias it names."""
        tenant, _, _ = _tenant_with_opd()
        _abdm_adapter(tenant, api_version="v1.0")

        with caplog.at_level("WARNING", logger="apps.abdm_gateway.client"):
            body = _post(APIClient(), _payload()).json()

        assert list(body) == list(PRE_CHANGE_OK_ACK)
        assert [
            record for record in caplog.records if record.name == "apps.abdm_gateway.client"
        ] == [], caplog.text

    def test_a_row_value_that_is_not_a_label_is_served_as_an_unrecognised_label(self, caplog):
        """The row cannot deliver a non-string, so the callback path cannot 422 on it.

        ``api_version`` is a ``CharField``: a dict written to the row comes back
        as its string repr, which is an unrecognised *label* like any other, so
        the scan is served in the default shape with a warning. The 422 is
        reserved for the signed callback body, where JSON really can carry a list
        or an object. Pinned because the asymmetry is otherwise invisible — the
        column quietly makes the malformed case unreachable from this direction.
        """
        tenant, _, _ = _tenant_with_opd()
        _abdm_adapter(tenant, api_version={"major": 3})

        with caplog.at_level("WARNING", logger="apps.abdm_gateway.client"):
            response = _post(APIClient(), _payload())

        assert response.status_code == 200, response.content
        assert _with_sentinels(response.json()) == PRE_CHANGE_OK_ACK
        assert str(tenant.id) in caplog.text
        assert "major" in caplog.text

    def test_another_tenants_adapter_cannot_shape_the_ack(self):
        """Tenant isolation on the adapter lookup (never RLS alone).

        Tenant A configured for v3 must not decide the shape of tenant B's
        acknowledgement: the lookup is explicitly filtered by ``tenant_id``.
        """
        tenant_a, _, _ = _tenant_with_opd(slug="abdm-a", hip_id="hip-a")
        tenant_b, _, _ = _tenant_with_opd(slug="abdm-b", hip_id="hip-b")
        _abdm_adapter(tenant_a, api_version="v3")

        body = _post(APIClient(), _payload(facilityId="hip-b")).json()

        assert tenant_b.id != tenant_a.id
        assert list(body) == list(PRE_CHANGE_OK_ACK)

    @pytest.mark.parametrize("api_version", ABDM_API_VERSIONS, ids=ABDM_API_VERSIONS)
    def test_the_ambiguous_ack_is_version_shaped(self, api_version):
        """The ABD-009 branch keeps its null token through the rename."""
        tenant, _, _ = _tenant_with_opd()
        for suffix in ("1", "2"):
            Patient.objects.create(
                tenant_id=tenant.id, uhid=f"UHID-AMB-VER-{suffix}",
                demographics={"name": "Shared Name", "gender": "M", "year_of_birth": 1980},
            )

        body = _post(
            APIClient(),
            _payload(
                apiVersion=api_version,
                profile=_demographic_profile(name="Shared Name", year=1980, gender="M"),
            ),
        ).json()

        assert body["status"] == "ambiguous"
        if api_version == "v3":
            assert body["token"] is None
            assert body["apiVersion"] == "v3"
            assert "patientId" in body
        else:
            assert body["token"] is None
            assert "patient_id" in body

    @pytest.mark.parametrize("api_version", ABDM_API_VERSIONS, ids=ABDM_API_VERSIONS)
    def test_a_replay_is_idempotent_in_every_version(self, api_version):
        """Both versions replay idempotently, and write nothing the second time."""
        _tenant_with_opd()
        client = APIClient()
        payload = _payload(apiVersion=api_version)

        first = _post(client, payload)
        replay = _post(client, payload)

        assert first.status_code == 200
        assert replay.status_code == 200, replay.content
        assert replay.json()["status"] == "duplicate"
        assert Token.objects.count() == 1
        assert Patient.objects.count() == 1
        assert ConsentEvent.objects.count() == 1
        assert ABHACallbackLog.objects.count() == 1

    @pytest.mark.parametrize("api_version", ABDM_API_VERSIONS, ids=ABDM_API_VERSIONS)
    def test_repeated_replays_return_identical_bytes(self, api_version):
        """Within a version the replayed acknowledgement is byte-identical.

        A gateway that retries must get the same body every time, in the version
        it is speaking, so the comparison is on the raw response bytes.
        """
        _tenant_with_opd()
        client = APIClient()
        payload = _payload(apiVersion=api_version)

        _post(client, payload)
        second = _post(client, payload)
        third = _post(client, payload)

        assert second.content == third.content

    def test_a_replay_declaring_another_version_returns_the_stored_outcome(self):
        """A cross-version replay is answered, never re-run.

        The decision, and why: the stored outcome (request id, token, patient id,
        status) is version-independent — only its vocabulary is not — so the
        replay is answered in the version *it* declared, which is also the only
        option available without recording the version on the ledger row (this
        task's migration is the adapter field, and nothing else). Refusing with a
        conflict would mean refusing a replay we cannot prove is a conflict.
        Either way the flow is not re-executed and nothing is written.
        """
        _tenant_with_opd()
        client = APIClient()

        first = _post(client, _payload()).json()
        replay = _post(client, _payload(apiVersion="v3")).json()

        assert replay["status"] == "duplicate"
        assert replay["apiVersion"] == "v3"
        assert replay["requestId"] == first["request_id"]
        assert replay["patientId"] == first["patient_id"]
        assert replay["token"] == first["token"]
        assert Token.objects.count() == 1
        assert Patient.objects.count() == 1
        assert ConsentEvent.objects.count() == 1
        assert ABHACallbackLog.objects.count() == 1

    @pytest.mark.parametrize("api_version", ABDM_API_VERSIONS, ids=ABDM_API_VERSIONS)
    def test_no_version_acknowledges_the_link_token(self, api_version):
        """ABD-012, pinned per version: the credential is sealed, never echoed.

        A new builder is the most likely place for this invariant to break, so
        the assertion is made per version and against the sealed column too.
        """
        _tenant_with_opd()

        response = _post(APIClient(), _payload(apiVersion=api_version))
        body = response.json()

        assert "link_token" not in body
        assert "linkToken" not in body
        assert "link_token" not in json.dumps(body)
        sealed = ABHACallbackLog.objects.get(request_id="req-1").link_token_enc
        assert sealed is not None and sealed.startswith("v1:")
