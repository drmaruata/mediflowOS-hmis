"""Duplicate warning, intake channel, and hardened patient validation (REG-002, REG-003, REG-005, REG-006, REG-007).

The registration counter is the single place a wrong patient can enter the
system, so this suite pins the three controls that stop it: a pre-save
duplicate warning (REG-003) that never crosses a tenant boundary, field-level
validation on the demographics/contact/consent payloads (REG-007), and the
recorded intake channel (REG-005). It also pins the search additions REG-002
asks for (exact year of birth and an approximate age window) without regressing
the UHID/ABHA lookup the counter already relies on.

Every write is driven through the real token-authenticated API and every
assertion re-reads the database, because a serializer that silently drops a
field still answers 201 and looks green.
"""
import re
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.patient_registry.models import Patient

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

UHID_RE = re.compile(r"UHID-\d{6}-\d{6}")


def _make_context(name="Registry Hospital"):
    """One tenant + facility + OPD-enabled department, as in the other suites."""
    tenant = Tenant.objects.create(
        name=name, slug=f"registry-{uuid.uuid4().hex[:8]}"
    )
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus",
        abdm_hip_id=f"HIP-REG-{uuid.uuid4().hex[:6].upper()}",
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


def _payload(**overrides):
    payload = {
        "demographics": {"name": "New Patient", "yearOfBirth": 1991, "gender": "F"},
    }
    payload.update(overrides)
    return payload


class TestDuplicateCheck:
    """POST /patients/duplicate-check/ warns before a likely duplicate is saved."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client = _make_client(self.tenant, self.facility)

    def test_exact_abha_match_is_the_first_candidate(self):
        """The strongest identifier ranks ahead of a name+year match (REG-003).

        The name match is created first so a naive "first row wins" ordering
        would put it at index 0; the ABHA match must still lead.
        """
        Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UHID-NAME-MATCH",
            demographics={"name": "Alpha Beta", "gender": "M", "yearOfBirth": 1980},
        )
        Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UHID-ABHA-MATCH", abha_number="123456789012",
            demographics={"name": "Someone Else", "gender": "F", "yearOfBirth": 1990},
        )

        response = self.client.post(
            "/api/v1/patients/duplicate-check/",
            {"name": "Alpha Beta", "dob": "1980-05-01", "abha_number": "123456789012"},
            format="json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["warn"] is True
        assert body["candidates"][0]["uhid"] == "UHID-ABHA-MATCH"
        assert {row["uhid"] for row in body["candidates"]} == {
            "UHID-ABHA-MATCH", "UHID-NAME-MATCH",
        }

    def test_matches_on_normalised_name_and_year_of_birth(self):
        """Case and whitespace differences must not hide a duplicate (REG-003)."""
        Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UHID-NORMALISED",
            demographics={"name": "John  Doe", "gender": "M", "yearOfBirth": 1980},
        )

        response = self.client.post(
            "/api/v1/patients/duplicate-check/",
            {"name": "  john   doe ", "dob": "1980-01-15"},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert [row["uhid"] for row in response.json()["candidates"]] == [
            "UHID-NORMALISED"
        ]

    def test_matches_on_normalised_mobile(self):
        """``+91``/spacing must not let the same mobile slip through twice."""
        Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UHID-MOBILE",
            demographics={"name": "Mobile Patient", "gender": "M", "yearOfBirth": 1975},
            contact={"mobile": "9876543210"},
        )

        response = self.client.post(
            "/api/v1/patients/duplicate-check/",
            {"mobile": "+91 98765 43210"},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert [row["uhid"] for row in response.json()["candidates"]] == [
            "UHID-MOBILE"
        ]

    def test_warns_false_when_nothing_matches(self):
        response = self.client.post(
            "/api/v1/patients/duplicate-check/",
            {"name": "Nobody Here", "dob": "2001-01-01"},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json() == {"candidates": [], "warn": False}

    def test_candidate_payload_masks_contact_identifiers(self):
        """The warning carries enough to recognise a match, not full PHI.

        A UHID, name, birth year and a masked mobile is enough for the clerk to
        say "that is the patient"; the full ABHA and mobile must not be echoed
        back on every probe (data minimisation, Architecture section 4).
        """
        Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UHID-MASKED", abha_number="123456789012",
            demographics={"name": "Masked Patient", "gender": "F", "yearOfBirth": 1960},
            contact={"mobile": "9876501234"},
        )

        response = self.client.post(
            "/api/v1/patients/duplicate-check/",
            {"name": "Masked Patient", "dob": "1960-03-03"},
            format="json",
        )

        candidate = response.json()["candidates"][0]
        assert candidate["uhid"] == "UHID-MASKED"
        assert candidate["mobile_masked"] == "******1234"
        assert "9876501234" not in str(response.json())
        assert "123456789012" not in str(response.json())

    def test_duplicate_check_never_sees_another_tenant(self):
        """Tenant B's probe must not surface tenant A's patient (REG-003)."""
        other_tenant, other_facility, _ = _make_context("Other Hospital")
        Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UHID-TENANT-A", abha_number="987654321098",
            demographics={"name": "Cross Tenant", "gender": "M", "yearOfBirth": 1985},
        )
        intruder = _make_client(other_tenant, other_facility, username="other-reception")

        response = intruder.post(
            "/api/v1/patients/duplicate-check/",
            {"name": "Cross Tenant", "dob": "1985-01-01", "abha_number": "987654321098"},
            format="json",
        )

        assert response.status_code == 200, response.content
        assert response.json() == {"candidates": [], "warn": False}

    def test_duplicate_check_requires_authentication(self):
        """A tenant-owned probe is deny-by-default; no token means no data."""
        response = APIClient().post(
            "/api/v1/patients/duplicate-check/",
            {"name": "Anyone"},
            format="json",
        )
        assert response.status_code in (401, 403)


class TestFindDuplicatesService:
    """The service the endpoint wraps, pinned directly for precedence/tenant scope."""

    def test_isolated_by_tenant(self):
        from apps.patient_registry.services import find_duplicates

        tenant, _, _ = _make_context()
        other_tenant, _, _ = _make_context("Service Other")
        Patient.objects.create(
            tenant_id=other_tenant.id, uhid="UHID-OTHER",
            demographics={"name": "Same Name", "gender": "M", "yearOfBirth": 1980},
        )

        assert find_duplicates(
            tenant_id=tenant.id, candidate={"name": "Same Name", "dob": "1980-01-01"}
        ) == []

    def test_respects_limit(self):
        from apps.patient_registry.services import find_duplicates

        tenant, _, _ = _make_context()
        for index in range(3):
            Patient.objects.create(
                tenant_id=tenant.id, uhid=f"UHID-LIMIT-{index}",
                demographics={"name": "Repeated", "gender": "F", "yearOfBirth": 1990},
            )

        found = find_duplicates(
            tenant_id=tenant.id,
            candidate={"name": "Repeated", "dob": "1990-06-06"},
            limit=2,
        )
        assert len(found) == 2

    def test_empty_tenant_returns_nothing(self):
        from apps.patient_registry.services import find_duplicates

        assert find_duplicates(tenant_id=None, candidate={"name": "x"}) == []


class TestPatientSerializerValidation:
    """Field-level validation on the registration payload (REG-007)."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client = _make_client(self.tenant, self.facility)

    def test_missing_gender_is_rejected_with_a_field_error(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(demographics={"name": "No Gender", "yearOfBirth": 1990}),
            format="json",
        )
        assert response.status_code == 400, response.content
        assert "demographics" in response.json()
        assert Patient.objects.count() == 0

    def test_missing_name_is_rejected(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(demographics={"gender": "M", "yearOfBirth": 1990}),
            format="json",
        )
        assert response.status_code == 400, response.content
        assert "demographics" in response.json()

    def test_missing_birth_data_is_rejected(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(demographics={"name": "No Birth", "gender": "M"}),
            format="json",
        )
        assert response.status_code == 400, response.content
        assert "demographics" in response.json()

    def test_dob_is_an_accepted_birth_key(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(demographics={"name": "Has Dob", "gender": "F", "dob": "1995-04-01"}),
            format="json",
        )
        assert response.status_code == 201, response.content

    def test_age_years_is_an_accepted_birth_key(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(demographics={"name": "Has Age", "gender": "M", "age_years": 30}),
            format="json",
        )
        assert response.status_code == 201, response.content

    def test_invalid_mobile_is_rejected_with_a_contact_field_error(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(contact={"mobile": "12345"}),
            format="json",
        )
        assert response.status_code == 400, response.content
        assert "contact" in response.json()
        assert Patient.objects.count() == 0

    def test_mobile_with_country_prefix_is_accepted(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(contact={"mobile": "+91 98765 43210"}),
            format="json",
        )
        assert response.status_code == 201, response.content

    def test_unknown_consent_flag_key_is_rejected(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(consent_flags={"definitely_not_documented": True}),
            format="json",
        )
        assert response.status_code == 400, response.content
        assert "consent_flags" in response.json()

    def test_non_boolean_consent_flag_is_rejected(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(consent_flags={"abdm_scan_and_share": "yes"}),
            format="json",
        )
        assert response.status_code == 400, response.content
        assert "consent_flags" in response.json()

    def test_documented_consent_flag_is_accepted(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(consent_flags={"abdm_scan_and_share": True}),
            format="json",
        )
        assert response.status_code == 201, response.content
        patient = Patient.objects.get(id=response.json()["id"])
        assert patient.consent_flags == {"abdm_scan_and_share": True}

    def test_client_supplied_uhid_and_verification_status_are_ignored(self):
        """Server-owned values stay server-owned (REG-001, REG-006)."""
        response = self.client.post(
            "/api/v1/patients/",
            _payload(uhid="HACKED-000001", verification_status="verified"),
            format="json",
        )
        assert response.status_code == 201, response.content
        patient = Patient.objects.get(id=response.json()["id"])
        assert UHID_RE.fullmatch(patient.uhid), patient.uhid
        assert patient.uhid != "HACKED-000001"
        assert patient.verification_status == "pending"


class TestIntakeChannel:
    """The registration records how the patient arrived (REG-005)."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client = _make_client(self.tenant, self.facility)

    def test_intake_channel_counter_persists(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(intake_channel="counter"),
            format="json",
        )
        assert response.status_code == 201, response.content
        assert response.json()["intake_channel"] == "counter"
        patient = Patient.objects.get(id=response.json()["id"])
        assert patient.intake_channel == "counter"

    def test_every_documented_channel_is_accepted(self):
        for channel in ("counter", "abha_qr", "appointment"):
            response = self.client.post(
                "/api/v1/patients/",
                _payload(intake_channel=channel),
                format="json",
            )
            assert response.status_code == 201, (channel, response.content)
            assert Patient.objects.get(id=response.json()["id"]).intake_channel == channel

    def test_unknown_channel_is_rejected(self):
        response = self.client.post(
            "/api/v1/patients/",
            _payload(intake_channel="walkin"),
            format="json",
        )
        assert response.status_code == 400, response.content
        assert "intake_channel" in response.json()


class TestSearchByBirthDate:
    """REG-002 search additions alongside the existing UHID/ABHA lookup."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client = _make_client(self.tenant, self.facility)
        self.current_year = timezone.now().year

    def _patient(self, uhid, year_of_birth):
        return Patient.objects.create(
            tenant_id=self.tenant.id, uhid=uhid,
            demographics={"name": uhid, "gender": "M", "yearOfBirth": year_of_birth},
        )

    def test_age_window_includes_44_to_46(self):
        """``?age=45`` finds patients aged 44-46 (a +/-1 year DOB window)."""
        self._patient("UHID-AGE-44", self.current_year - 44)
        self._patient("UHID-AGE-45", self.current_year - 45)
        self._patient("UHID-AGE-46", self.current_year - 46)
        self._patient("UHID-AGE-47", self.current_year - 47)

        response = self.client.get("/api/v1/patients/search/?age=45")

        assert response.status_code == 200, response.content
        found = {row["uhid"] for row in response.json()}
        assert found == {"UHID-AGE-44", "UHID-AGE-45", "UHID-AGE-46"}

    def test_exact_year_of_birth_filter(self):
        self._patient("UHID-YOB-1980", 1980)
        self._patient("UHID-YOB-1981", 1981)

        response = self.client.get("/api/v1/patients/search/?year_of_birth=1980")

        assert response.status_code == 200, response.content
        assert {row["uhid"] for row in response.json()} == {"UHID-YOB-1980"}

    def test_existing_uhid_lookup_still_works(self):
        """The regression guard for the counter's original lookup (REG-002)."""
        self._patient("UHID-KEEP", 1990)

        response = self.client.get("/api/v1/patients/search/?q=UHID-KEEP")

        assert response.status_code == 200, response.content
        assert {row["uhid"] for row in response.json()} == {"UHID-KEEP"}
