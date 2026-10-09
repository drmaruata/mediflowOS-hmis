"""ABDM outbound ABHA adapter and department QR codes (REG-009, REG-013).

REG-009 (create/verify an ABHA at the counter) is shipped as an outbound
``ABDMClient`` plus a strict 503 when the sandbox is not configured: the ABDM
sandbox create/verify spec (endpoint paths, payloads, OTP flow) is unresolved,
so the ``ABDMClient`` paths below are patterned on the community-mirrored
sandbox v1 enrollment spec and must be re-verified when the official spec is
confirmed (see the REG-009 entry in ``docs/traceability.md`` Known gaps).
No endpoint may fake a 200 for a request the adapter never completed.

REG-013 (department-specific QR codes) pins the ``encode_data`` contract
``HIP[-counter][-department_id]`` and the audited regenerate action.
"""
import json
import uuid

import httpx
import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.abdm_gateway.client import (
    ABDMClient,
    ABDMRequestError,
    require_sandbox_base_url,
    resolve_sandbox_base_url,
)
from apps.audit.models import AuditEvent
from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.patient_registry.models import IntakePoint, Patient, QRCode

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

#: The sandbox root the client builds its URLs on. Hostname carries "sbx" and
#: is https, so it satisfies the settings gate's sandbox-only predicate.
SANDBOX_BASE = "https://healthidsbx.abdm.gov.in/api/v1"


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