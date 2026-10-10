"""Audit drill-down filtering and patient read logging (AUD-001, AUD-003).

Two halves of AUD-001/AUD-003 are pinned here.

The **drill-down** half guards the audit log's read contract: ``GET
/api/v1/audit-log/`` must honour ``?entity_type=`` (one resource kind) and,
paired with it, ``?entity_id=`` (one row). The filter was once built inside a
``list()`` override that delegated to ``super().list()``, which re-fetches
``self.get_queryset()`` and discards the local queryset — so the filter
silently never applied. That defect is only *invisible* when a single audit
row exists (unfiltered and filtered both return one), which is why every
drill-down case below seeds several rows.

The **read-logging** half closes AUD-001's read side: a patient detail GET and
each row a counter ``search`` returns must land an ``AuditEvent(action="read")``
naming the row by table + pk and the requester, with no PHI in the row.

Everything is scoped through the JWT's tenant, so a second tenant's rows are
proved invisible, and the endpoint itself stays read-only and deny-by-default.
"""
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.patient_registry.models import Patient

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

AUDIT_LOG_URL = "/api/v1/audit-log/"
PATIENTS_URL = "/api/v1/patients/"

#: ``TenantScopedQuerysetMixin._write_audit_log`` and ``audit_read`` name the
#: row by its model's ``db_table``; patients live in ``registry.patient``.
PATIENT_DB_TABLE = "registry.patient"


def _make_context(name="Audit Hospital"):
    """One tenant + facility + OPD-enabled department, as in the other suites."""
    tenant = Tenant.objects.create(
        name=name, slug=f"audit-{uuid.uuid4().hex[:8]}"
    )
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus",
        abdm_hip_id=f"HIP-AUD-{uuid.uuid4().hex[:6].upper()}",
    )
    department = Department.objects.create(
        tenant=tenant, facility=facility, name="Medicine",
        effective_from="2026-01-01", opd_enabled=True,
    )
    return tenant, facility, department


def _make_client(tenant, username="auditor"):
    """JWT-authenticated client whose token carries the tenant's claims."""
    user = get_user_model().objects.create_user(
        username=username, password="testpass123"
    )
    role = Role.objects.create(tenant=tenant, name=f"role-{username}", permissions=[])
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    refresh = TenantAwareTokenSerializer.get_token(user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {str(refresh.access_token)}")
    return client, user


class TestAuditDrillDown:
    """`GET /audit-log/` narrows by entity_type, and entity_id with it (AUD-003)."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client, self.user = _make_client(self.tenant)
        # Three events across two resources: one patient event, and two events
        # on a single QR code. Seeding more than one row is what makes the
        # discarded-filter defect visible — a single row would pass either way.
        AuditEvent.objects.create(
            tenant_id=self.tenant.id, action="create",
            entity_type=PATIENT_DB_TABLE, entity_id="P1",
        )
        AuditEvent.objects.create(
            tenant_id=self.tenant.id, action="update",
            entity_type="registry.qr_code", entity_id="Q1",
        )
        AuditEvent.objects.create(
            tenant_id=self.tenant.id, action="update",
            entity_type="registry.qr_code", entity_id="Q1",
        )

    def _results(self, response):
        return response.json()["results"]

    def test_drill_down_to_one_resource_returns_only_that_resource(self):
        """The type + id pair selects exactly the one resource's rows.

        RED against the discarded-filter bug: the URL is filtered in a local
        variable and thrown away, so ``super().list`` returns all three rows.
        """
        response = self.client.get(
            AUDIT_LOG_URL, {"entity_type": PATIENT_DB_TABLE, "entity_id": "P1"}
        )

        assert response.status_code == 200, response.content
        results = self._results(response)
        assert len(results) == 1
        assert results[0]["entity_id"] == "P1"
        assert results[0]["entity_type"] == PATIENT_DB_TABLE

    def test_entity_type_alone_narrows_to_that_kind(self):
        """A type with no id returns every row of that kind (two QR rows)."""
        response = self.client.get(AUDIT_LOG_URL, {"entity_type": "registry.qr_code"})

        assert response.status_code == 200, response.content
        results = self._results(response)
        assert len(results) == 2
        assert {row["entity_type"] for row in results} == {"registry.qr_code"}

    def test_no_params_returns_all_tenant_rows(self):
        response = self.client.get(AUDIT_LOG_URL)

        assert response.status_code == 200, response.content
        assert len(self._results(response)) == 3

    def test_entity_id_alone_does_not_narrow(self):
        """``entity_id`` is only meaningful paired with ``entity_type``.

        Alone it is ignored, matching the old resource-type/resource-id
        pairing; a lone id must not silently filter every kind down to one.
        """
        response = self.client.get(AUDIT_LOG_URL, {"entity_id": "Q1"})

        assert response.status_code == 200, response.content
        assert len(self._results(response)) == 3


class TestAuditLogTenantIsolation:
    """Another tenant's audit rows are invisible to this tenant (AUD-003)."""

    def test_unfiltered_list_excludes_foreign_tenant_rows(self):
        tenant_a, _, _ = _make_context("Hospital A")
        tenant_b, _, _ = _make_context("Hospital B")
        client_a, _ = _make_client(tenant_a)
        AuditEvent.objects.create(
            tenant_id=tenant_a.id, action="create",
            entity_type=PATIENT_DB_TABLE, entity_id="P1",
        )
        # Same resource shape as the local row, but a different tenant.
        foreign = AuditEvent.objects.create(
            tenant_id=tenant_b.id, action="create",
            entity_type=PATIENT_DB_TABLE, entity_id="P1",
        )

        response = client_a.get(AUDIT_LOG_URL)

        assert response.status_code == 200, response.content
        assert str(foreign.id) not in {row["id"] for row in response.json()["results"]}
        assert len(response.json()["results"]) == 1

    def test_filtered_drill_down_excludes_foreign_tenant_rows(self):
        """A drill-down on the foreign row's exact resource returns nothing."""
        tenant_a, _, _ = _make_context("Hospital A")
        tenant_b, _, _ = _make_context("Hospital B")
        client_a, _ = _make_client(tenant_a)
        AuditEvent.objects.create(
            tenant_id=tenant_b.id, action="create",
            entity_type=PATIENT_DB_TABLE, entity_id="P1",
        )

        response = client_a.get(
            AUDIT_LOG_URL, {"entity_type": PATIENT_DB_TABLE, "entity_id": "P1"}
        )

        assert response.status_code == 200, response.content
        assert response.json()["results"] == []


class TestPatientReadLogging:
    """A patient read is audited (AUD-001, read half)."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client, self.user = _make_client(self.tenant)

    def test_retrieve_writes_one_read_event(self):
        patient = Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UHID-READ-1",
            demographics={"name": "Reader", "gender": "F", "yearOfBirth": 1980},
        )

        response = self.client.get(f"{PATIENTS_URL}{patient.id}/")

        assert response.status_code == 200, response.content
        reads = AuditEvent.objects.filter(
            action="read", entity_type=PATIENT_DB_TABLE, entity_id=str(patient.id)
        )
        assert reads.count() == 1
        event = reads.get()
        assert event.tenant_id == self.tenant.id
        # auth.User keeps an integer pk while audit.user_id is a UUIDField, so
        # the stored value is the coerced uuid (same convention as
        # test_authentication.py::BreakGlassTest._uuid_pk).
        assert event.user_id == uuid.UUID(int=self.user.pk)
        assert event.source_ip == "127.0.0.1"

    def test_search_writes_one_read_per_returned_patient(self):
        """Each row a counter search returns is a read that must be recorded.

        The page bounds the write volume: search slices to its page, so one
        logged read per returned patient scales with the page, not the table.
        """
        patients = [
            Patient.objects.create(
                tenant_id=self.tenant.id, uhid=f"UHID-SEARCH-{index}",
                demographics={"name": "Searchable", "gender": "M", "yearOfBirth": 1990},
            )
            for index in range(3)
        ]

        response = self.client.get(f"{PATIENTS_URL}search/", {"name": "Searchable"})

        assert response.status_code == 200, response.content
        assert len(response.json()) == 3
        reads = AuditEvent.objects.filter(action="read", entity_type=PATIENT_DB_TABLE)
        assert reads.count() == 3
        assert {event.entity_id for event in reads} == {str(p.id) for p in patients}

    def test_read_event_carries_no_phi(self):
        """The read row is identifiers only — no name, ABHA or demographics.

        AUD-001 read coverage must never become a PHI sink: ``audit_read``
        writes the table and pk and nothing else, so the only free-text the row
        could carry (``reason``/``source``) stays empty. This pins that
        minimisation against a future change that starts logging more.
        """
        patient = Patient.objects.create(
            tenant_id=self.tenant.id, uhid="UHID-PHI-1", abha_number="123456789012",
            demographics={"name": "Private Person", "gender": "F", "yearOfBirth": 1975},
            contact={"mobile": "9876543210"},
        )

        response = self.client.get(f"{PATIENTS_URL}{patient.id}/")

        assert response.status_code == 200, response.content
        event = AuditEvent.objects.get(action="read", entity_id=str(patient.id))
        assert event.entity_type == PATIENT_DB_TABLE
        assert event.entity_id == str(patient.id)
        assert event.reason is None
        assert event.source is None


class TestAuditEndpointSecurity:
    """The audit endpoint stays read-only and deny-by-default (AUD-003)."""

    def test_unauthenticated_read_is_rejected(self):
        response = APIClient().get(AUDIT_LOG_URL)

        assert response.status_code == 401

    def test_authenticated_write_is_method_not_allowed(self):
        tenant, _, _ = _make_context()
        client, _ = _make_client(tenant, username="writer-auditor")

        response = client.post(AUDIT_LOG_URL, {"action": "read"}, format="json")

        assert response.status_code == 405
