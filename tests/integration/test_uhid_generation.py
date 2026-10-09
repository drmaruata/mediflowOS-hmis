"""Server-generated UHID and OPD token series (REG-001, REG-010, ABD-010).

UHIDs and token numbers are server-owned identifiers: the client must not be
able to choose them, two simultaneous registrations must not mint the same
number, and every tenant's counter starts at one. These tests pin the service
layer that guarantees that, plus the venues that consume it (patient
registration and the ABDM callback).

The two-thread proof (``test_uhid_unique_under_concurrent_creation``) runs only
against PostgreSQL, where ``select_for_update()`` actually blocks the loser and
the first-create race is resolved by the bounded IntegrityError retry. On
SQLite the same scenario is not expressible: the in-memory shared-cache
database reports ``database is locked`` *immediately* when ``BEGIN IMMEDIATE``
contends (the busy timeout is never invoked there, verified empirically), so
the loser can exhaust its retries before the winner's transaction commits. The
retry branch that makes the PostgreSQL race safe is therefore also pinned
deterministically in ``test_generate_uhid_retries_raced_sequence_row``, which
runs on every backend.
"""
import os
import re
import threading
import uuid
from datetime import datetime, timezone

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.utils import timezone as dj_timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.opd.models import Token, TokenSeries
from apps.patient_registry.models import Patient, PatientSequence

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

UHID_RE = re.compile(r"UHID-\d{6}-\d{6}")

requires_postgres = pytest.mark.skipif(
    not os.getenv("MEDIFLOW_TEST_PGHOST"),
    reason=(
        "set MEDIFLOW_TEST_PGHOST (and companion MEDIFLOW_TEST_PG* variables) "
        "to run tests that assert real PostgreSQL locking behaviour"
    ),
)


def _make_context():
    """One tenant + facility + OPD-enabled department, as in the other suites."""
    tenant = Tenant.objects.create(
        name="UHID Hospital", slug=f"uhid-{uuid.uuid4().hex[:8]}"
    )
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus",
        abdm_hip_id=f"HIP-UHID-{uuid.uuid4().hex[:6].upper()}",
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
    role = Role.objects.create(tenant=tenant, name="receptionist", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    refresh = TenantAwareTokenSerializer.get_token(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client


class TestServerGeneratedUHID:
    """POST /patients/ mints the UHID; a client-supplied one is ignored (REG-001)."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()
        self.client = _make_client(self.tenant, self.facility)

    def _payload(self, **overrides):
        payload = {
            "demographics": {"name": "New Patient", "yearOfBirth": 1991, "gender": "F"},
        }
        payload.update(overrides)
        return payload

    def test_uhid_generated_server_side(self):
        """POST without uhid returns a UHID-<YYYYMM>-<NNNNNN> identifier."""
        response = self.client.post(
            "/api/v1/patients/", self._payload(), format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        uhid = response.data["uhid"]
        assert UHID_RE.fullmatch(uhid), uhid
        assert response.data["verification_status"] == "pending"
        assert Patient.objects.get(id=response.data["id"]).uhid == uhid

    def test_client_supplied_uhid_is_ignored(self):
        """A caller cannot squat on a chosen UHID; the server value wins."""
        response = self.client.post(
            "/api/v1/patients/", self._payload(uhid="UH999999-999999"), format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert UHID_RE.fullmatch(response.data["uhid"])
        assert response.data["uhid"] != "UH999999-999999"

    def test_uhid_sequence_is_per_tenant(self):
        """Two tenants each start their own UHID series at one (REG-001)."""
        from apps.patient_registry.services import generate_uhid

        other_tenant, _, _ = _make_context()
        first = generate_uhid(tenant_id=self.tenant.id)
        second = generate_uhid(tenant_id=other_tenant.id)
        # Tenant B's first UHID is 000001 even though tenant A already used its
        # counter — a shared row would hand tenant B a number starting at 2.
        assert first.endswith("-000001")
        assert second.endswith("-000001")
        assert PatientSequence.objects.filter(
            tenant_id=self.tenant.id, kind="uhid"
        ).count() == 1
        assert PatientSequence.objects.filter(
            tenant_id=other_tenant.id, kind="uhid"
        ).count() == 1

    def test_registration_with_intake_department_returns_token_series(self):
        """Registering into a department mints an OPD token (REG-010).

        The intake department is a write-only input: it must not reappear in
        the response, only the issued token's series and number.
        """
        response = self.client.post(
            "/api/v1/patients/",
            self._payload(intake_department_id=str(self.department.id)),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "intake_department_id" not in response.data
        token = Token.objects.get(patient_id=response.data["id"])
        assert token.department_id == self.department.id
        assert token.number == 1
        assert response.data["token"] == {"series": token.series, "number": 1}

    def test_unknown_intake_department_is_rejected(self):
        """An intake department from outside the tenant is refused before save.

        The patient must not be written at all when the department cannot be
        resolved, or a bad intake would silently register a patient with no
        queue anywhere.
        """
        response = self.client.post(
            "/api/v1/patients/",
            self._payload(intake_department_id=str(uuid.uuid4())),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Patient.objects.count() == 0
        assert Token.objects.count() == 0

    def test_foreign_tenants_department_is_rejected(self):
        """Another hospital's department UUID must not mint a token here."""
        _, _, other_department = _make_context()
        response = self.client.post(
            "/api/v1/patients/",
            self._payload(intake_department_id=str(other_department.id)),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert Patient.objects.count() == 0
        assert Token.objects.count() == 0


class TestConcurrentUHIDCreation:
    """Two simultaneous first registrations must mint distinct UHIDs (REG-001)."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()

    @requires_postgres
    @pytest.mark.django_db(transaction=True)
    def test_uhid_unique_under_concurrent_creation(self):
        """The row-creation race is won by one thread and retried by the other.

        PostgreSQL-only in this suite: the loser blocks on
        ``select_for_update`` and the first-create INSERT race is resolved by
        the bounded IntegrityError retry, which re-reads the winner's committed
        row and mints the *next* number. Exactly one thread wins; the other
        still returns a distinct, valid UHID and the tenant-month sequence row
        ends up advanced past both.

        On SQLite the same scenario is a test-infrastructure artifact rather
        than an exercise of the locking: the in-memory shared-cache database
        answers a contended ``BEGIN IMMEDIATE`` with ``database is locked``
        immediately (busy handler never invoked), so the loser can exhaust its
        three retries before the winner commits. ``select_for_update`` is also
        a documented no-op there. The retry branch is pinned on every backend
        by ``test_generate_uhid_retries_raced_sequence_row``.
        """
        from apps.patient_registry.services import generate_uhid

        barrier = threading.Barrier(2)
        results = {}
        errors = []

        def _generate():
            try:
                barrier.wait()
                results[threading.get_ident()] = generate_uhid(
                    tenant_id=self.tenant.id
                )
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=_generate) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, errors
        uhids = list(results.values())
        assert len(set(uhids)) == 2, uhids
        for uhid in uhids:
            assert UHID_RE.fullmatch(uhid), uhid
        # One row per tenant-month, advanced past both issued numbers.
        assert PatientSequence.objects.filter(tenant_id=self.tenant.id).count() == 1
        sequence = PatientSequence.objects.get(
            tenant_id=self.tenant.id, kind="uhid"
        )
        assert sequence.next_value == 3


class TestUHIDService:
    """The sequence service itself: retry on race, monthly rollover."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()

    def test_generate_uhid_retries_raced_sequence_row(self, monkeypatch):
        """A lost creation race is retried, not surfaced to the caller.

        The threaded proof of the race lives in
        ``test_uhid_unique_under_concurrent_creation`` (PostgreSQL-only, where
        ``select_for_update`` actually locks). This test pins the same retry
        branch deterministically on every backend: the first create attempt
        raises IntegrityError, exactly as the loser's INSERT does when the
        winner's row for ``(tenant_id, kind, period)`` commits first, and the
        retry must recover with a valid UHID instead of failing the
        registration. ``calls["n"] == 2`` proves the retry really ran.
        """
        from apps.patient_registry.services import generate_uhid

        real_create = PatientSequence.objects.create
        calls = {"n": 0}

        def _flaky_create(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise IntegrityError("unique constraint")
            return real_create(**kwargs)

        monkeypatch.setattr(PatientSequence.objects, "create", _flaky_create)

        uhid = generate_uhid(tenant_id=self.tenant.id)
        assert UHID_RE.fullmatch(uhid), uhid
        assert calls["n"] == 2
        sequence = PatientSequence.objects.get(
            tenant_id=self.tenant.id, kind="uhid"
        )
        assert sequence.next_value == 2

    def test_uhid_period_rolls_over_monthly(self, monkeypatch):
        """The UHID carries its issue month; a new month restarts at 000001."""
        from apps.patient_registry.services import generate_uhid
        import apps.patient_registry.services as services

        oct_end = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
        nov_start = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
        moments = iter([oct_end, nov_start])
        monkeypatch.setattr(services.timezone, "now", lambda: next(moments))

        first = generate_uhid(tenant_id=self.tenant.id)
        second = generate_uhid(tenant_id=self.tenant.id)

        assert first == "UHID-202610-000001"
        assert second == "UHID-202611-000001"
        periods = sorted(
            PatientSequence.objects.filter(tenant_id=self.tenant.id)
            .values_list("period", flat=True)
        )
        assert periods == ["2026-10", "2026-11"]


class TestTokenSeriesService:
    """OPD token numbers increment per series and stay tenant-scoped (REG-010)."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()

    def _issue(self, department_id):
        from apps.opd.services import next_token_number

        return next_token_number(
            tenant_id=self.tenant.id,
            facility_id=self.facility.id,
            department_id=department_id,
        )

    def test_token_number_increments_per_series(self):
        assert self._issue(self.department.id) == ("GEN", 1)
        assert self._issue(self.department.id) == ("GEN", 2)
        series = TokenSeries.objects.get(
            tenant_id=self.tenant.id,
            facility_id=self.facility.id,
            department_id=self.department.id,
        )
        assert series.prefix == "GEN"
        assert series.next_number == 3

    def test_each_department_starts_its_own_series(self):
        surgery = Department.objects.create(
            tenant=self.tenant, facility=self.facility, name="Surgery",
            effective_from="2026-01-01",
        )
        assert self._issue(self.department.id) == ("GEN", 1)
        assert self._issue(surgery.id) == ("GEN", 1)
        assert TokenSeries.objects.filter(tenant_id=self.tenant.id).count() == 2

    def test_null_department_uses_gen_series(self):
        """A registration with no intake department falls back to the GEN series."""
        assert self._issue(None) == ("GEN", 1)
        assert self._issue(None) == ("GEN", 2)
        assert TokenSeries.objects.filter(
            tenant_id=self.tenant.id, department_id__isnull=True
        ).count() == 1

    def test_token_series_are_per_tenant(self):
        from apps.opd.services import next_token_number

        other_tenant, other_facility, other_department = _make_context()
        self._issue(self.department.id)
        first_other = next_token_number(
            tenant_id=other_tenant.id,
            facility_id=other_facility.id,
            department_id=other_department.id,
        )
        # Tenant B starts at 1 even though tenant A has already issued one.
        assert first_other == ("GEN", 1)
        assert TokenSeries.objects.count() == 2


class TestABDMTokenUsesSharedSeries:
    """The callback issues series/numbers from TokenSeries, not inline logic (ABD-010)."""

    def _scan(self, facility, request_id, abha="555555555555"):
        client = APIClient()
        return client.post(
            "/api/v1/abdm-callbacks/",
            {
                "requestId": request_id,
                "facilityId": facility.abdm_hip_id,
                "timestamp": dj_timezone.now().isoformat(),
                "profile": {"abhaNumber": abha},
            },
            format="json",
            HTTP_X_AUTHORIZATION="gateway-shared-secret",
        )

    def test_abdm_token_uses_shared_series_service(self):
        """A pre-configured series wins over the old QR-<uuid> scheme."""
        tenant, facility, department = _make_context()
        TokenSeries.objects.create(
            tenant_id=tenant.id,
            facility_id=facility.id,
            department_id=department.id,
            prefix="MED",
            next_number=7,
        )

        response = self._scan(facility, "req-series-1")
        assert response.status_code == status.HTTP_200_OK

        token = Token.objects.get(id=response.json()["token"])
        assert token.series == "MED"
        assert token.number == 7
        assert token.department_id == department.id
        series = TokenSeries.objects.get(
            tenant_id=tenant.id, facility_id=facility.id, department_id=department.id
        )
        assert series.next_number == 8

    def test_abdm_series_increments_across_calls(self):
        """Two scans for one department take consecutive numbers."""
        tenant, facility, department = _make_context()
        first = self._scan(facility, "req-incr-1", abha="666666666666")
        second = self._scan(facility, "req-incr-2", abha="777777777777")

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        token_1 = Token.objects.get(id=first.json()["token"])
        token_2 = Token.objects.get(id=second.json()["token"])
        assert (token_1.series, token_1.number) == ("GEN", 1)
        assert (token_2.series, token_2.number) == ("GEN", 2)