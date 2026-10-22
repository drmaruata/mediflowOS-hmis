"""QR code lifecycle: revocation, the regenerate guard, tenant scoping.

``QRCode.revoked_at`` and ``QRCode.active`` have existed since the model was
created, but only the regenerate half of ABD-002 had an endpoint (Task 14,
pinned in ``test_abha_services.py``). This file pins the revoke half and the
two properties that make revoking safe to expose:

* a revoked code cannot be regenerated — a rebuild would mint a fresh
  ``encode_data`` for a poster that was printed *because* the old one was
  withdrawn, so the answer is 409, never a silent success;
* every write is tenant-scoped, because ``encode_data`` carries the
  facility's ABDM HIP identifier and a QR of another hospital must not be
  readable, revocable or regenerable from this one.

Every write goes through the real authenticated API and every assertion
re-reads the database: a 201 whose ``active`` flag stayed true is exactly the
partial write that looks green in a response body and is broken in the table.
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
from apps.patient_registry.models import QRCode

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

QR_LIST_URL = "/api/v1/qr-codes/"

#: ``TenantScopedQuerysetMixin._write_audit_log`` names the row by the model's
#: ``db_table``, the same convention ``ConfigRevision.entity`` uses.
QR_DB_TABLE = "registry.qr_code"


def _make_context(name="QR Hospital"):
    """One tenant + facility + OPD-enabled department, as in the other suites."""
    tenant = Tenant.objects.create(
        name=name, slug=f"qr-{uuid.uuid4().hex[:8]}"
    )
    facility = Facility.objects.create(
        tenant=tenant, name="Main Campus",
        abdm_hip_id=f"HIP-QR-{uuid.uuid4().hex[:6].upper()}",
    )
    department = Department.objects.create(
        tenant=tenant, facility=facility, name="Medicine",
        effective_from="2026-01-01", opd_enabled=True,
    )
    return tenant, facility, department


def _make_client(tenant, username="reception"):
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


def _make_qr(tenant, facility, department=None, active=True):
    return QRCode.objects.create(
        tenant_id=tenant.id,
        facility=facility,
        department=department,
        encode_data=facility.abdm_hip_id,
        active=active,
    )


class TestRevoke:
    """POST /qr-codes/{id}/revoke/ ends the code's life (ABD-002)."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()
        self.client, self.user = _make_client(self.tenant)
        self.qr = _make_qr(self.tenant, self.facility, self.department)

    def _revoke(self, qr=None):
        return self.client.post(f"{QR_LIST_URL}{qr.id if qr else self.qr.id}/revoke/")

    def test_revoke_stamps_revoked_at_and_deactivates(self):
        response = self._revoke()

        assert response.status_code == 201, response.content
        self.qr.refresh_from_db()
        assert self.qr.revoked_at is not None
        assert self.qr.active is False
        assert response.json()["revoked_at"] is not None
        assert response.json()["active"] is False

    def test_revoke_writes_one_audit_row_naming_the_row(self):
        """AUD-001: the withdrawal is traceable to the account that made it.

        The row is the one ``TenantScopedQuerysetMixin._write_audit_log``
        writes, so it carries the mixin's conventions: the model's
        ``db_table`` as the entity type, the requester's user id, and no
        machine-provenance marker — which is what tells it apart from the
        ``source="qr.regenerate"`` row the regenerate action writes.
        """
        self._revoke()

        events = AuditEvent.objects.filter(
            tenant_id=self.tenant.id, entity_id=str(self.qr.id)
        )
        assert events.count() == 1
        event = events.get()
        assert event.action == "update"
        assert event.entity_type == QR_DB_TABLE
        # auth.User keeps an integer pk while audit.user_id is a UUIDField,
        # so the int pk is stored coerced — same convention as
        # test_authentication.py::_uuid_pk.
        assert event.user_id == uuid.UUID(int=self.user.pk)
        assert event.source is None

    def test_double_revoke_is_idempotent_and_writes_no_second_audit(self):
        """A repeated revoke is the same end state, so it must be a no-op.

        The endpoint is a POST a client (or a retrying network stack) may
        send twice; a second ``revoked_at`` stamp or audit row would make the
        trail claim two withdrawals of one code.
        """
        assert self._revoke().status_code == 201

        second = self._revoke()

        assert second.status_code == 200, second.content
        assert AuditEvent.objects.filter(
            tenant_id=self.tenant.id, entity_id=str(self.qr.id)
        ).count() == 1
        self.qr.refresh_from_db()
        assert self.qr.active is False
        assert self.qr.revoked_at is not None

    def test_revoke_requires_authentication(self):
        anonymous = APIClient()
        response = anonymous.post(f"{QR_LIST_URL}{self.qr.id}/revoke/")

        assert response.status_code in (401, 403)
        self.qr.refresh_from_db()
        assert self.qr.revoked_at is None
        assert self.qr.active is True

    def test_revoked_at_is_server_owned_and_cannot_be_forged(self):
        """A client-supplied ``revoked_at`` must never reach the column.

        ``read_only_fields`` is what makes this true: a forged timestamp would
        let anyone date a withdrawal into the past (or the future) and would
        make the audit trail's ``occurred_at`` disagree with the state it
        describes.
        """
        response = self.client.patch(
            f"{QR_LIST_URL}{self.qr.id}/",
            {"revoked_at": "2020-01-01T00:00:00Z"},
            format="json",
        )

        assert response.status_code == 200, response.content
        self.qr.refresh_from_db()
        assert self.qr.revoked_at is None
        assert self.qr.active is True


class TestRegenerate:
    """The regenerate guard, plus the happy path it must not regress (REG-013)."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()
        self.client, self.user = _make_client(self.tenant)

    def test_regenerate_rebuilds_encode_data_and_audits(self):
        """Regression pin for the Task 14 behaviour the guard sits in front of."""
        qr = _make_qr(self.tenant, self.facility)
        qr.department = self.department
        qr.save(update_fields=["department"])

        response = self.client.post(f"{QR_LIST_URL}{qr.id}/regenerate/")

        assert response.status_code == 200, response.content
        qr.refresh_from_db()
        assert qr.encode_data == f"{self.facility.abdm_hip_id}-{self.department.id}"
        assert qr.regenerated_at is not None
        assert AuditEvent.objects.filter(
            tenant_id=self.tenant.id, entity_id=str(qr.id), source="qr.regenerate"
        ).count() == 1

    def test_regenerate_on_a_revoked_code_answers_409(self):
        """Revocation is final for the encoded string (ABD-002).

        Rebuilding ``encode_data`` after a withdrawal would mint a working
        routing string out of a code that was pulled — the poster is printed,
        the department may have been reassigned, and the audit trail would say
        the code was revoked while the queue keeps accepting its scans. The
        refusal names "revoked" so the caller knows which state it hit, and it
        happens before any write: the row and its audit trail are untouched.
        """
        qr = _make_qr(self.tenant, self.facility, self.department)
        assert self.client.post(f"{QR_LIST_URL}{qr.id}/revoke/").status_code == 201
        encode_before = qr.encode_data

        response = self.client.post(f"{QR_LIST_URL}{qr.id}/regenerate/")

        assert response.status_code == 409, response.content
        assert "revoked" in response.json()["detail"].lower()
        qr.refresh_from_db()
        assert qr.encode_data == encode_before
        assert qr.regenerated_at is None
        # Only the revoke's audit row exists; the refused write left nothing.
        assert AuditEvent.objects.filter(
            tenant_id=self.tenant.id, entity_id=str(qr.id)
        ).count() == 1


class TestTenantScoping:
    """A QR of another hospital must be unreachable, not merely hidden."""

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()
        self.other_tenant, self.other_facility, _ = _make_context("Other Hospital")
        self.client, self.user = _make_client(self.tenant)
        self.qr = _make_qr(self.tenant, self.facility, self.department)
        self.foreign_qr = _make_qr(self.other_tenant, self.other_facility)

    def test_list_returns_only_the_owning_tenants_codes(self):
        response = self.client.get(QR_LIST_URL)

        assert response.status_code == 200, response.content
        ids = [row["id"] for row in response.json()["results"]]
        assert ids == [str(self.qr.id)]

    def test_foreign_detail_answers_404(self):
        response = self.client.get(f"{QR_LIST_URL}{self.foreign_qr.id}/")

        assert response.status_code == 404
        assert response.json()["detail"]

    def test_foreign_revoke_is_refused(self):
        """A cross-tenant revoke must 404 rather than write into another tenant.

        ``get_object()`` reads the tenant-scoped queryset, so the foreign id
        resolves to nothing and no audit row, warning or state change is
        produced for a hospital the requester does not belong to.
        """
        response = self.client.post(f"{QR_LIST_URL}{self.foreign_qr.id}/revoke/")

        assert response.status_code == 404
        self.foreign_qr.refresh_from_db()
        assert self.foreign_qr.revoked_at is None
        assert self.foreign_qr.active is True
        assert AuditEvent.objects.filter(
            entity_id=str(self.foreign_qr.id)
        ).count() == 0
