"""Phase 1 integration tests — identity, patient registry, ABDM, OPD, IPD."""
import uuid
import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from apps.identity_tenancy.models import (
    Tenant, Facility, Department, Ward, Bed, Role, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.patient_registry.models import Patient
from apps.opd.models import Token
from apps.ipd.models import Admission, BedStatus
from apps.emergency.models import Triage
from apps.quality_os.models import (
    Framework, FrameworkEdition, IndicatorDef, IndicatorSourceDocument,
    IndicatorValue, CAPA,
)
from apps.billing_insurance.models import Invoice
from apps.audit.models import AuditEvent


pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _make_client(username, tenant, facility, role_name, permissions):
    """Helper: create user, membership, and return APIClient with token."""
    user = get_user_model().objects.create_user(username=username, password="testpass123")
    role = Role.objects.create(tenant=tenant, name=role_name, permissions=permissions)
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    refresh = TenantAwareTokenSerializer.get_token(user)
    access_token = str(refresh.access_token)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
    return client, user, role


@pytest.mark.django_db(transaction=True)
class TestIdentityTenancyAPI:
    """Tenant and facility CRUD endpoints (TEN-001 to TEN-010)."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-TEST-001",
        )
        self.client, self.user, self.role = _make_client(
            # platform.tenants.manage: tenant list/onboard are gated on it
            # since TEN-004; "all" is a marker no permission class reads.
            "admin", self.tenant, self.facility, "admin", ["all", "platform.tenants.manage"],
        )
        self.department = Department.objects.create(
            tenant=self.tenant, facility=self.facility, name="Medicine", effective_from="2026-01-01",
        )
        self.ward = Ward.objects.create(
            tenant_id=self.tenant.id, department=self.department, name="Ward A", type_tag="Medical",
        )
        self.bed = Bed.objects.create(
            tenant_id=self.tenant.id, ward=self.ward, bed_number="A1",
        )

    def test_tenant_list(self):
        response = self.client.get("/api/v1/tenants/")
        assert response.status_code == status.HTTP_200_OK

    def test_tenant_onboard(self):
        response = self.client.post("/api/v1/tenants/onboard/", {"name": "New Hospital", "slug": "new-hospital"})
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["slug"] == "new-hospital"

    def test_facility_list_scoped(self):
        response = self.client.get("/api/v1/facilities/")
        assert response.status_code == status.HTTP_200_OK

    def test_department_list_scoped(self):
        response = self.client.get("/api/v1/departments/")
        assert response.status_code == status.HTTP_200_OK

    def test_ward_list_scoped(self):
        response = self.client.get("/api/v1/wards/")
        assert response.status_code == status.HTTP_200_OK

    def test_bed_list_scoped(self):
        response = self.client.get("/api/v1/beds/")
        assert response.status_code == status.HTTP_200_OK

    def test_me_endpoint(self):
        response = self.client.get("/api/v1/auth/me/")
        assert response.status_code == status.HTTP_200_OK

    def test_break_glass_recorded(self):
        # Role has allows_break_glass=False, so request should be forbidden
        response = self.client.post("/api/v1/auth/break-glass/", {"reason": "emergency access"})
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db(transaction=True)
class TestPatientRegistryAPI:
    """Patient registry, UHID, duplicate detection, verification queue (REG-001 to REG-013)."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-TEST-002",
        )
        self.client, self.user, self.role = _make_client(
            "doc", self.tenant, self.facility, "doctor", ["view_patient"],
        )
        self.patient = Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UH001", abha_number="123456789012",
            verification_status="pending",
            demographics={"name": "Test Patient", "yearOfBirth": 1980, "gender": "M"},
        )

    def test_patient_list_scoped_to_tenant(self):
        response = self.client.get("/api/v1/patients/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1

    def test_patient_search_by_uhid(self):
        response = self.client.get("/api/v1/patients/search/?q=UH001")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_patient_search_by_abha(self):
        response = self.client.get("/api/v1/patients/search/?q=123456789012")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_verification_queue(self):
        response = self.client.get("/api/v1/patients/?verification_status=pending")
        assert response.status_code == status.HTTP_200_OK

    def test_verify_patient(self):
        response = self.client.post(f"/api/v1/patients/{self.patient.id}/verify/")
        assert response.status_code == status.HTTP_200_OK
        self.patient.refresh_from_db()
        assert self.patient.verification_status == "verified"

    def test_intake_point_list_scoped(self):
        response = self.client.get("/api/v1/intake-points/")
        assert response.status_code == status.HTTP_200_OK

    def test_qr_code_list_scoped(self):
        response = self.client.get("/api/v1/qr-codes/")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db(transaction=True)
class TestOPDTokenAPI:
    """OPD token queue and call workflow."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-OPD-001",
        )
        self.client, self.user, self.role = _make_client(
            "receptionist", self.tenant, self.facility, "receptionist", ["view_token"],
        )
        self.department = Department.objects.create(
            tenant=self.tenant, facility=self.facility, name="Medicine", effective_from="2026-01-01",
        )

    def test_token_creation_scoped(self):
        response = self.client.post("/api/v1/tokens/", {
            "patient_id": str(uuid.uuid4()),
            "department_id": str(self.department.id),
            "series": "MED-001",
            "number": 1,
            "status": "waiting",
        })
        assert response.status_code == status.HTTP_201_CREATED
        assert Token.objects.count() == 1

    def test_token_list_scoped(self):
        Token.objects.create(tenant_id=self.tenant.id, patient_id=self.tenant.id,
                             department_id=self.department.id, series="MED-001", number=1)
        response = self.client.get("/api/v1/tokens/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1

    def test_queue_endpoint(self):
        Token.objects.create(tenant_id=self.tenant.id, patient_id=self.tenant.id,
                             department_id=self.department.id, series="MED-001", number=1, status="waiting")
        response = self.client.get(f"/api/v1/tokens/queue/?department_id={self.department.id}")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_call_token(self):
        token_obj = Token.objects.create(tenant_id=self.tenant.id, patient_id=self.tenant.id,
                                         department_id=self.department.id, series="MED-001", number=1)
        response = self.client.post(f"/api/v1/tokens/{token_obj.id}/call/")
        assert response.status_code == status.HTTP_200_OK
        token_obj.refresh_from_db()
        assert token_obj.status == "called"

    def test_done_token(self):
        token_obj = Token.objects.create(tenant_id=self.tenant.id, patient_id=self.tenant.id,
                                         department_id=self.department.id, series="MED-001", number=1)
        response = self.client.post(f"/api/v1/tokens/{token_obj.id}/done/")
        assert response.status_code == status.HTTP_200_OK
        token_obj.refresh_from_db()
        assert token_obj.status == "done"


@pytest.mark.django_db(transaction=True)
class TestIPDAdmissionAPI:
    """IPD admission, bed board, discharge with disposition."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-IPD-001",
        )
        self.client, self.user, self.role = _make_client(
            "doctor", self.tenant, self.facility, "doctor", ["view_admission"],
        )
        self.department = Department.objects.create(
            tenant=self.tenant, facility=self.facility, name="Medicine", effective_from="2026-01-01",
        )
        self.ward = Ward.objects.create(
            tenant_id=self.tenant.id, department=self.department, name="Ward A", type_tag="Medical",
        )
        self.bed = Bed.objects.create(tenant_id=self.tenant.id, ward=self.ward, bed_number="A1")

    def _admission_payload(self, **overrides):
        payload = {
            "patient_id": str(uuid.uuid4()),
            "department_id": str(self.department.id),
            "ward_id": str(self.ward.id),
            "bed_id": str(self.bed.id),
            "source": "OPD",
        }
        payload.update(overrides)
        return payload

    def _make_admission(self, **overrides):
        return Admission.objects.create(
            tenant_id=self.tenant.id,
            **{**self._admission_payload(), **overrides},
        )

    def test_admission_creation_scoped(self):
        response = self.client.post("/api/v1/admissions/", self._admission_payload())
        assert response.status_code == status.HTTP_201_CREATED
        assert Admission.objects.count() == 1

    def test_tenant_id_is_server_owned(self):
        """A client-supplied tenant_id must not decide which tenant the row lands in.

        tenant_id is read-only on the serializer, so a value sent in the body is
        ignored rather than rejected. Without that, a caller could write into
        another hospital's data.
        """
        other_tenant = Tenant.objects.create(name="Other Hospital", slug="other-hospital")
        response = self.client.post(
            "/api/v1/admissions/",
            self._admission_payload(tenant_id=str(other_tenant.id)),
        )
        assert response.status_code == status.HTTP_201_CREATED
        admission = Admission.objects.get(id=response.data["id"])
        assert str(admission.tenant_id) == str(self.tenant.id)

    def test_active_admissions(self):
        self._make_admission()
        response = self.client.get("/api/v1/admissions/active/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_discharged_admission_leaves_active_list(self):
        admission = self._make_admission()
        self.client.post(
            f"/api/v1/admissions/{admission.id}/discharge/", {"disposition": "routine"}
        )
        response = self.client.get("/api/v1/admissions/active/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0

    def test_discharge_requires_disposition(self):
        admission = self._make_admission()
        response = self.client.post(f"/api/v1/admissions/{admission.id}/discharge/", {})
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_bed_board(self):
        BedStatus.objects.create(
            tenant_id=self.tenant.id, bed_id=self.bed.id, ward_id=self.ward.id, occupied=True,
        )
        response = self.client.get("/api/v1/bed-status/board/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]["occupied"] is True


@pytest.mark.django_db(transaction=True)
class TestEmergencyAPI:
    """Emergency triage and tracking board."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-ER-001",
        )
        self.client, self.user, self.role = _make_client(
            "er_doc", self.tenant, self.facility, "doctor", ["view_triage"],
        )
        self.triage = Triage.objects.create(tenant_id=self.tenant.id, patient_id=self.tenant.id,
                                             category="II", arrival_time="2026-10-02T10:00:00Z")

    def test_triage_list_scoped(self):
        response = self.client.get("/api/v1/triages/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1

    def test_tracking_board(self):
        response = self.client.get("/api/v1/triages/tracking_board/")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db(transaction=True)
class TestQualityOSAPI:
    """Quality OS indicators, CAPA, facts (QOS-001 to QOS-074)."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-QOS-001",
        )
        self.client, self.user, self.role = _make_client(
            "quality", self.tenant, self.facility, "quality", ["view_indicator"],
        )
        self.framework = Framework.objects.create(code="NQAS", name="NQAS 2025")
        self.edition = FrameworkEdition.objects.create(
            framework=self.framework, edition="2025", effective_from="2025-01-01",
        )
        self.source_doc = IndicatorSourceDocument.objects.create(
            framework=self.framework, document_name="NQAS 2025", document_version="1.0",
            content_hash="abc123",
        )
        self.indicator = IndicatorDef.objects.create(
            edition=self.edition, source_document=self.source_doc,
            name="LAMA Rate", unit="rate", periodicity="Monthly",
            calculation_mode="auto", direction="lower-is-better",
        )

    def test_indicator_value_list_scoped(self):
        IndicatorValue.objects.create(tenant_id=self.tenant.id, facility_id=self.tenant.id,
                                       indicator=self.indicator, definition_version=1,
                                       period_start="2026-09-01", period_end="2026-09-30",
                                       value=5.2)
        response = self.client.get("/api/v1/indicator-values/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1

    def test_indicator_dashboard(self):
        IndicatorValue.objects.create(tenant_id=self.tenant.id, facility_id=self.tenant.id,
                                       indicator=self.indicator, definition_version=1,
                                       period_start="2026-09-01", period_end="2026-09-30",
                                       value=5.2)
        response = self.client.get("/api/v1/indicator-values/dashboard/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_capa_close(self):
        capa = CAPA.objects.create(tenant_id=self.tenant.id, source_type="alert",
                                    source_ref="QOS-001", title="Test CAPA",
                                    severity="major", owner=self.user.id, due_date="2026-12-01")
        response = self.client.post(f"/api/v1/capas/{capa.id}/close/")
        assert response.status_code == status.HTTP_200_OK
        capa.refresh_from_db()
        assert capa.status == "closed"

    def test_framework_list_global(self):
        response = self.client.get("/api/v1/frameworks/")
        assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db(transaction=True)
class TestABDMCallbackAPI:
    """ABDM Scan and Share callback with authentication, idempotency, tenant resolution."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-ABDM-001",
        )
        self.client, self.user, self.role = _make_client(
            "abdm_user", self.tenant, self.facility, "admin", ["all"],
        )
        self.department = Department.objects.create(
            tenant=self.tenant, facility=self.facility, name="Medicine",
            effective_from="2026-01-01", opd_enabled=True,
        )

    def test_callback_without_auth_rejected(self):
        """Unauthenticated gateway call is rejected (ABD-005).

        The endpoint is ``AllowAny`` because the gateway carries no user JWT, so
        DRF will not 401 it. Authentication is enforced inside the view instead;
        this pins that the view actually refuses rather than falling through to
        the patient-match path.
        """
        anonymous = APIClient()
        response = anonymous.post("/api/v1/abdm-callbacks/", {}, format="json")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.data["status"] == "rejected"

    def test_health_endpoint(self):
        response = self.client.get("/api/v1/abdm-callbacks/health/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ok"

    def test_stale_timestamp_rejected(self):
        """A timestamp outside the 5-minute window is refused (ABD-007)."""
        response = self.client.post(
            "/api/v1/abdm-callbacks/",
            {
                "requestId": "req-stale-1",
                "facilityId": "HIP-ABDM-001",
                "timestamp": "2020-01-01T00:00:00Z",
            },
            format="json",
            HTTP_X_AUTHORIZATION="gateway-shared-secret",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "timestamp" in response.data["detail"].lower()

    def test_unknown_hip_rejected(self):
        """A HIP ID that maps to no facility is refused (ABD-004)."""
        response = self.client.post(
            "/api/v1/abdm-callbacks/",
            {
                "requestId": "req-unknown-hip",
                "facilityId": "HIP-DOES-NOT-EXIST",
                "timestamp": timezone.now().isoformat(),
            },
            format="json",
            HTTP_X_AUTHORIZATION="gateway-shared-secret",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "hip" in response.data["detail"].lower()

    def test_callback_is_idempotent(self):
        """Replaying a request ID returns the first result, not a new token (ABD-006)."""
        payload = {
            "requestId": "req-idem-1",
            "facilityId": "HIP-ABDM-001",
            "timestamp": timezone.now().isoformat(),
            "profile": {"abhaNumber": "999999999999"},
        }
        first = self.client.post(
            "/api/v1/abdm-callbacks/",
            payload,
            format="json",
            HTTP_X_AUTHORIZATION="gateway-shared-secret",
        )
        assert first.status_code == status.HTTP_200_OK

        second = self.client.post(
            "/api/v1/abdm-callbacks/",
            payload,
            format="json",
            HTTP_X_AUTHORIZATION="gateway-shared-secret",
        )
        assert second.status_code == status.HTTP_200_OK
        assert second.data["status"] == "duplicate"
        # Exactly one token must exist - the replay must not issue a second one.
        assert Token.objects.count() == 1
        assert second.data["token"] == first.data["token"]


@pytest.mark.django_db(transaction=True)
class TestAuditLogAPI:
    """Audit log read-only, tenant-scoped (AUD-003)."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-AUD-001",
        )
        self.client, self.user, self.role = _make_client(
            "auditor", self.tenant, self.facility, "auditor", ["view_audit"],
        )
        AuditEvent.objects.create(tenant_id=self.tenant.id, user_id=self.user.id,
                                   action="create", entity_type="Patient", entity_id="123")

    def test_audit_log_list_scoped(self):
        response = self.client.get("/api/v1/audit-log/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1

    def test_audit_log_drill_down(self):
        response = self.client.get("/api/v1/audit-log/?resource_type=Patient&resource_id=123")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1


@pytest.mark.django_db(transaction=True)
class TestBillingAPI:
    """Billing and insurance endpoints."""

    def setup_method(self):
        self.tenant = Tenant.objects.create(name="Test Hospital", slug="test-hospital")
        self.facility = Facility.objects.create(
            tenant=self.tenant, name="Main Campus",
            abdm_hip_id="HIP-BILL-001",
        )
        self.client, self.user, self.role = _make_client(
            "billing", self.tenant, self.facility, "billing", ["view_invoice"],
        )

    def test_tariff_list_scoped(self):
        response = self.client.get("/api/v1/tariffs/")
        assert response.status_code == status.HTTP_200_OK

    def test_invoice_pay_creates_payment_and_closes_invoice(self):
        invoice = Invoice.objects.create(
            tenant_id=self.tenant.id, patient_id=str(uuid.uuid4()),
            type="opd", total=1000.00, status="draft",
        )
        response = self.client.post(
            f"/api/v1/invoices/{invoice.id}/pay/", {"amount": 1000.00, "method": "cash"}
        )
        assert response.status_code == status.HTTP_201_CREATED
        invoice.refresh_from_db()
        assert invoice.status == "paid"
        assert response.data["payment"]["amount"] == "1000.00"

    def test_cannot_pay_another_tenants_invoice(self):
        """The pay action resolves through the tenant-scoped queryset."""
        other_tenant = Tenant.objects.create(name="Other Hospital", slug="other-hospital")
        foreign = Invoice.objects.create(
            tenant_id=other_tenant.id, patient_id=str(uuid.uuid4()),
            type="opd", total=500.00, status="draft",
        )
        response = self.client.post(f"/api/v1/invoices/{foreign.id}/pay/", {"amount": 500.00})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        foreign.refresh_from_db()
        assert foreign.status == "draft"


@pytest.mark.django_db(transaction=True)
class TestCrossTenantIsolation:
    """Ensure tenant-scoped endpoints never leak data across tenants."""

    def setup_method(self):
        self.tenant_t1 = Tenant.objects.create(name="Hospital T1", slug="t1")
        self.tenant_t2 = Tenant.objects.create(name="Hospital T2", slug="t2")
        self.facility_t1 = Facility.objects.create(
            tenant=self.tenant_t1, name="T1 Campus",
            abdm_hip_id="HIP-T1-001",
        )
        self.facility_t2 = Facility.objects.create(
            tenant=self.tenant_t2, name="T2 Campus",
            abdm_hip_id="HIP-T2-001",
        )
        self.role_t1 = Role.objects.create(tenant=self.tenant_t1, name="doctor", permissions=["view_patient"])
        self.role_t2 = Role.objects.create(tenant=self.tenant_t2, name="doctor", permissions=["view_patient"])
        user_t1 = get_user_model().objects.create_user(username="t1_user", password="testpass123")
        user_t2 = get_user_model().objects.create_user(username="t2_user", password="testpass123")
        UserMembership.objects.create(user=user_t1, tenant=self.tenant_t1, role=self.role_t1, active=True)
        UserMembership.objects.create(user=user_t2, tenant=self.tenant_t2, role=self.role_t2, active=True)
        refresh_t1 = TenantAwareTokenSerializer.get_token(user_t1)
        access_token_t1 = str(refresh_t1.access_token)
        refresh_t2 = TenantAwareTokenSerializer.get_token(user_t2)
        access_token_t2 = str(refresh_t2.access_token)
        self.token_t1 = access_token_t1
        self.token_t2 = access_token_t2
        # Patient in T1
        self.patient_t1 = Patient.objects.create(
            tenant_id=self.tenant_t1.id, uhid="T1-UH001", abha_number="T1-ABHA",
            verification_status="verified",
            demographics={"name": "T1 Patient", "yearOfBirth": 1990, "gender": "F"},
        )
        # Patient in T2
        self.patient_t2 = Patient.objects.create(
            tenant_id=self.tenant_t2.id, uhid="T2-UH001", abha_number="T2-ABHA",
            verification_status="verified",
            demographics={"name": "T2 Patient", "yearOfBirth": 1985, "gender": "M"},
        )

    def test_t1_only_sees_t1_patients(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_t1}")
        response = client.get("/api/v1/patients/")
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["uhid"] == "T1-UH001"

    def test_t2_only_sees_t2_patients(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token_t2}")
        response = client.get("/api/v1/patients/")
        assert response.status_code == status.HTTP_200_OK
        results = response.data["results"]
        assert len(results) == 1
        assert results[0]["uhid"] == "T2-UH001"