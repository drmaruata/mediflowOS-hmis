"""OP slip payload and OPD department picker (REG-011, REG-012).

``GET /api/v1/visits/{visit_id}/op-slip/`` renders the JSON print contract a
paper OPD slip shows — the patient's UHID and name, the issued token's
series/number, the department and facility display names, plus the issue and
visit dates. The route is keyed by the OPD encounter id (the "visit") and
every lookup is scoped to the caller's tenant: an unknown or foreign visit
must answer 404 without disclosing the existence of another hospital's
encounter (isolation is the highest-severity rule in this repo).

``GET /api/v1/departments/?opd_enabled=true`` narrows the department list to
OPD-selectable rows for the picker the slip is printed from.

The token row is created directly (the documented caller pattern — the token
issuance service returns the series/number and the caller inserts the row), so
this suite pins the slip's read path, not the token-writer.
"""
import time
import uuid
from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.opd.models import OPDEncounter, Token
from apps.patient_registry.models import Patient

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _make_context(name="Slip Hospital"):
    """One tenant + facility + an OPD-enabled department, as in the other suites."""
    tenant = Tenant.objects.create(
        name=name, slug=f"slip-{uuid.uuid4().hex[:8]}"
    )
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus",
        abdm_hip_id=f"HIP-SLIP-{uuid.uuid4().hex[:6].upper()}",
    )
    department = Department.objects.create(
        tenant=tenant, facility=facility, name="Medicine",
        effective_from="2026-01-01", opd_enabled=True,
    )
    return tenant, facility, department


def _make_client(tenant, facility, username="reception"):
    """JWT-authenticated client whose token carries the tenant claims."""
    user = get_user_model().objects.create_user(
        username=username, password="testpass123"
    )
    role = Role.objects.create(tenant=tenant, name=f"role-{username}", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    refresh = TenantAwareTokenSerializer.get_token(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


def _make_patient(tenant, uhid, name="Slip Patient"):
    return Patient.objects.create(
        tenant_id=tenant.id, uhid=uhid,
        demographics={"name": name, "gender": "F", "yearOfBirth": 1985},
    )


def _make_visit(tenant, department, patient):
    return OPDEncounter.objects.create(
        tenant_id=tenant.id,
        patient_id=patient.id,
        department_id=department.id,
        visit_type="new",
        registration_time=timezone.now(),
    )


class TestOpSlipPayload:
    """GET /api/v1/visits/{id}/op-slip/ renders the print contract (REG-011)."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()
        self.client = _make_client(self.tenant, self.facility)
        self.patient = _make_patient(self.tenant, "UHID-SLIP-1")
        self.encounter = _make_visit(self.tenant, self.department, self.patient)
        self.token = Token.objects.create(
            tenant_id=self.tenant.id,
            patient_id=self.patient.id,
            department_id=self.department.id,
            series="MED",
            number=1,
        )

    def test_op_slip_renders_the_exact_print_contract(self):
        """The payload is exactly the seven contract fields, values denormalised.

        A paper slip shows these strings verbatim, so the assertion pins every
        field — including that ``token`` nests ``series``/``number`` and no
        extra PHI leaks into the representation. ``issued_at`` is compared as
        an instant rather than a literal string because DRF renders aware
        datetimes in the project timezone (America/Chicago default), so the
        wire value can carry a ``-05:00`` offset while the model stores UTC.
        """
        response = self.client.get(
            f"/api/v1/visits/{self.encounter.id}/op-slip/"
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert set(body) == {
            "uhid",
            "patient_name",
            "token",
            "department",
            "facility",
            "issued_at",
            "visit_date",
        }
        assert body["uhid"] == "UHID-SLIP-1"
        assert body["patient_name"] == "Slip Patient"
        assert body["token"] == {"series": "MED", "number": 1}
        assert body["department"] == "Medicine"
        assert body["facility"] == "Main Campus"
        assert datetime.fromisoformat(body["issued_at"]).astimezone(
            dt_timezone.utc
        ) == self.token.issued_at
        assert (
            body["visit_date"]
            == self.encounter.registration_time.date().isoformat()
        )

    def test_unknown_visit_answers_404(self):
        response = self.client.get(f"/api/v1/visits/{uuid.uuid4()}/op-slip/")

        assert response.status_code == 404, response.content

    def test_another_tenants_visit_answers_404_without_leaking_existence(self):
        """A foreign visit must not resolve, and the 404 must not name it.

        The body carrying the patient's UHID or name would be an existence
        leak across the tenancy boundary even with a 404 status.
        """
        other_tenant, other_facility, _ = _make_context("Other Slip Hospital")
        intruder = _make_client(other_tenant, other_facility, username="other")

        response = intruder.get(
            f"/api/v1/visits/{self.encounter.id}/op-slip/"
        )

        assert response.status_code == 404, response.content
        assert "UHID-SLIP-1" not in response.content.decode()

    def test_encounter_without_token_renders_core_with_null_token(self):
        """A missing token must not 404 the whole slip (REG-011).

        The patient + visit core is still valid for printing; only the token
        block and the issue time (which the token is the source of) go null.
        """
        patient = _make_patient(self.tenant, "UHID-SLIP-NOTOKEN", name="No Token")
        encounter = _make_visit(self.tenant, self.department, patient)

        response = self.client.get(f"/api/v1/visits/{encounter.id}/op-slip/")

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["token"] is None
        assert body["issued_at"] is None
        assert body["uhid"] == "UHID-SLIP-NOTOKEN"
        assert body["patient_name"] == "No Token"
        assert body["visit_date"] == encounter.registration_time.date().isoformat()

    def test_latest_token_for_the_patient_department_is_selected(self):
        """Re-issue picks the newest token, not an arbitrary or the first row.

        The design decision keys the slip's token by (tenant, patient,
        department) with the latest ``issued_at`` because there is no foreign
        key joining Token to the encounter. The sleep keeps the two
        ``auto_now_add`` timestamps distinct on coarse-resolution clocks.
        """
        older = Token.objects.create(
            tenant_id=self.tenant.id,
            patient_id=self.patient.id,
            department_id=self.department.id,
            series="MED",
            number=2,
        )
        time.sleep(0.005)
        newer = Token.objects.create(
            tenant_id=self.tenant.id,
            patient_id=self.patient.id,
            department_id=self.department.id,
            series="MED",
            number=3,
        )

        response = self.client.get(
            f"/api/v1/visits/{self.encounter.id}/op-slip/"
        )

        assert response.status_code == 200, response.content
        assert response.json()["token"] == {"series": "MED", "number": 3}
        assert older.issued_at < newer.issued_at

    def test_op_slip_requires_authentication(self):
        response = APIClient().get(f"/api/v1/visits/{self.encounter.id}/op-slip/")

        assert response.status_code in (401, 403)


class TestOpdDepartmentFilter:
    """?opd_enabled=true narrows /departments/ to OPD-selectable rows (REG-012)."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()
        self.non_opd = Department.objects.create(
            tenant=self.tenant, facility=self.facility, name="Radiology",
            effective_from="2026-01-01", opd_enabled=False,
        )
        self.client = _make_client(self.tenant, self.facility)
        self.path = "/api/v1/departments/"

    def test_opd_enabled_true_filters_to_opd_departments_only(self):
        response = self.client.get(self.path, {"opd_enabled": "true"})

        assert response.status_code == 200, response.content
        # The list response is paginated (PAGE_SIZE=50), so rows live in
        # ``results`` like every other collection endpoint here.
        names = [row["name"] for row in response.json()["results"]]
        assert "Medicine" in names
        assert "Radiology" not in names

    def test_absent_false_or_garbage_value_leaves_the_list_unfiltered(self):
        """Only the ``true`` token opts the filter in (mirrors SET-008's parse).

        A typo such as ``opd_enabled=1`` must not silently truncate the picker
        to zero rows, which would look like a working filter.
        """
        for value in (None, "false", "1"):
            query = {} if value is None else {"opd_enabled": value}
            response = self.client.get(self.path, query)

            assert response.status_code == 200, response.content
            names = {row["name"] for row in response.json()["results"]}
            assert {"Medicine", "Radiology"} <= names, value