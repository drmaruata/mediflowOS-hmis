"""Effective-dated configuration, deactivation and audit proof (SET-002..005, SET-010, SET-011, SET-012).

Every update to a department, ward, bed, service unit or staff position first
archives the row's *pre-update* state into ``ConfigRevision`` (SET-010) — the
snapshot is the old configuration, opened ``effective_from = today`` and closed
again (``effective_to = yesterday``) by the following update, so a locked
indicator period keeps the settings that were in force when it was filed. Config
rows are never hard-deleted: DELETE is blocked (405) and deactivation is a
PATCH of ``active`` that keeps the row (SET-011), and every config create and
update lands an ``AuditEvent`` (SET-012) through the tenant mixin's write
hooks. ``GET /api/v1/config-revisions/?entity=&entity_id=`` exposes the
tenant-scoped history, newest first.

The tests pin the contract the brief calls out: the revision captures the
pre-update row (asserted from the database, not the response), the history
endpoint shows both the closed and the open revision, DELETE answers 405 while
a deactivated row survives with ``active`` false, beds expose the additive
``active`` field, each SET-002..005 create and update increments the audit row
count, and tenant B can neither see nor touch tenant A's revisions.
"""
from datetime import date, timedelta
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.identity_tenancy.models import (
    Bed,
    ConfigRevision,
    Department,
    StaffPosition,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("a1111111-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("b2222222-0000-4000-8000-000000000002")

TEST_PASSWORD = "pw-for-tests-only"

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def _login(username, password=TEST_PASSWORD):
    """Issue a real access token through the API.

    Issued through ``/auth/token/`` rather than built by hand so the claims
    under test come from the same serializer production uses — the same
    pattern as ``test_setup_wizard`` and ``test_rbac_enforcement``.
    """
    response = APIClient().post(
        "/api/v1/auth/token/",
        {"username": username, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


def _make_client(tenant_id, username, slug, permissions):
    """An authenticated client of one tenant.

    Config endpoints gate writes on authentication plus tenant scoping (TEN-002)
    rather than a permission claim, so the permission list is not asserted
    here; the shape mirrors ``test_setup_wizard``'s helper for consistency.
    """
    from apps.identity_tenancy.models import Role, Tenant, UserMembership

    # ``get_or_create``: a facility fixture may already have minted the tenant
    # (the slug is globally unique, so a second create would clash).
    Tenant.objects.get_or_create(id=tenant_id, defaults={"name": slug, "slug": slug})
    user = get_user_model().objects.create_user(
        username=username, password=TEST_PASSWORD
    )
    role = Role.objects.create(
        tenant_id=tenant_id, name=f"role-{slug}", permissions=list(permissions)
    )
    UserMembership.objects.create(
        user=user, tenant_id=tenant_id, role=role, active=True
    )

    access = _login(username)
    seated = AccessToken(access).payload["permissions"]
    for code in permissions:
        assert code in seated, f"token for {username} lacks the {code} claim"
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


@pytest.fixture
def facility():
    """A facility for tenant A, so department and service-unit writes resolve."""
    from apps.identity_tenancy.models import Facility, Tenant

    Tenant.objects.create(id=TENANT_A, name="tenant-a", slug="tenant-a")
    return Facility.objects.create(
        tenant_id=TENANT_A, name="Main Campus", level="District Hospital"
    )


@pytest.fixture
def config_client(facility):
    """An authenticated tenant-A user."""
    return _make_client(TENANT_A, "config-admin-a", "tenant-a", [])


@pytest.fixture
def other_client():
    """An authenticated tenant-B user with the same (claim-less) write surface."""
    return _make_client(TENANT_B, "config-admin-b", "tenant-b", [])


def _create_department(client, facility, name="OPD"):
    response = client.post(
        "/api/v1/departments/",
        {
            "facility": str(facility.id),
            "name": name,
            "effective_from": TODAY.isoformat(),
        },
        format="json",
    )
    assert response.status_code == 201, response.content
    return response.json()


class TestEffectiveDatedRevisions:
    """SET-010: updates archive the pre-update row; history exposes both."""

    def test_update_records_revision_of_old_state_and_no_revision_on_create(
        self, config_client, facility
    ):
        """Create writes nothing; the first update snapshots the pre-update row.

        A revision is a record of the *old* configuration at the moment it was
        replaced (SET-010). Creating a department must therefore leave no
        revision behind, and the first rename must archive the created state —
        asserted from the database with the snapshot's name, so a response
        that merely looks right cannot pass.
        """
        department = _create_department(config_client, facility, name="OPD")
        department_id = department["id"]

        assert ConfigRevision.objects.filter(
            tenant_id=TENANT_A, entity="identity.department", entity_id=department_id
        ).count() == 0

        rename = config_client.patch(
            f"/api/v1/departments/{department_id}/",
            {"name": "OPD Acute"},
            format="json",
        )
        assert rename.status_code == 200, rename.content

        revisions = ConfigRevision.objects.filter(
            tenant_id=TENANT_A, entity="identity.department", entity_id=department_id
        )
        assert revisions.count() == 1
        revision = revisions.get()
        assert revision.snapshot["name"] == "OPD"
        assert revision.effective_from == TODAY
        assert revision.effective_to is None
        assert revision.created_by is not None

    def test_second_update_closes_prior_and_history_shows_both(
        self, config_client, facility
    ):
        """The next update closes the open revision and both stay visible.

        Closing uses ``effective_to = yesterday`` while the new snapshot opens
        ``effective_from = today`` — the closed record is what a locked
        indicator period re-reads (SET-010). The history endpoint must expose
        both revisions of this department, current (open) one first, and
        nothing of any other row.
        """
        department = _create_department(config_client, facility, name="OPD")
        department_id = department["id"]

        first = config_client.patch(
            f"/api/v1/departments/{department_id}/",
            {"name": "OPD Acute"},
            format="json",
        )
        assert first.status_code == 200, first.content
        second = config_client.patch(
            f"/api/v1/departments/{department_id}/",
            {"name": "OPD Chronic"},
            format="json",
        )
        assert second.status_code == 200, second.content

        revisions = {
            row.snapshot["name"]: row
            for row in ConfigRevision.objects.filter(
                tenant_id=TENANT_A, entity="identity.department", entity_id=department_id
            )
        }
        assert set(revisions) == {"OPD", "OPD Acute"}
        # The first snapshot was replaced by the second update, so it is
        # closed; the second snapshot is still current. Discriminate by
        # ``effective_to`` rather than row order: both snapshots share
        # ``effective_from`` (the two updates happened the same day), so any
        # ``order_by(... id)`` fallback would be random UUID order.
        assert revisions["OPD"].effective_to == YESTERDAY
        assert revisions["OPD Acute"].effective_to is None

        body = config_client.get(
            "/api/v1/config-revisions/",
            {"entity": "identity.department", "entity_id": department_id},
        )
        assert body.status_code == 200, body.content
        results = body.json()["results"]
        assert len(results) == 2
        assert [row["snapshot"]["name"] for row in results] == ["OPD Acute", "OPD"]
        # The current settings always lead the history list.
        assert results[0]["effective_to"] is None
        assert results[0]["effective_from"] == TODAY.isoformat()
        assert results[1]["effective_to"] == YESTERDAY.isoformat()
        assert all(row["entity"] == "identity.department" for row in results)
        assert all(row["tenant_id"] == str(TENANT_A) for row in results)

    def test_entity_id_filter_narrows_to_one_row(self, config_client, facility):
        """Two departments must not share a revision history.

        ``entity_id`` is the discriminator inside ``entity``; a history query
        for one department must never return another's revisions.
        """
        first = _create_department(config_client, facility, name="OPD")
        second = _create_department(config_client, facility, name="IPD")
        for department_id, name in ((first["id"], "OPD-1"), (second["id"], "IPD-1")):
            patch = config_client.patch(
                f"/api/v1/departments/{department_id}/", {"name": name}, format="json"
            )
            assert patch.status_code == 200, patch.content

        body = config_client.get(
            "/api/v1/config-revisions/",
            {"entity": "identity.department", "entity_id": first["id"]},
        )
        results = body.json()["results"]
        assert len(results) == 1
        assert results[0]["snapshot"]["name"] == "OPD"


class TestConfigDeactivation:
    """SET-011: DELETE is blocked; deactivation keeps the row."""

    def test_delete_returns_405_on_config_rows(self, config_client, facility):
        """A hard DELETE of a config row must be refused, not performed.

        Config rows are referenced by audit history and locked indicator
        periods, so removing them would orphan both. The refusal is 405 — the
        verb is not part of the config interface — and the database row must
        be untouched afterwards.
        """
        department = _create_department(config_client, facility)

        response = config_client.delete(f"/api/v1/departments/{department['id']}/")

        assert response.status_code == 405, response.content
        assert Department.objects.filter(pk=department["id"]).exists()

    def test_patch_active_false_deactivates_keeping_row(self, config_client, facility):
        """Deactivation is ``PATCH {active: false}``; the row survives.

        Read back from the database, not the response, so a response that
        merely looked deactivated cannot pass (same discipline as the
        reference-data deactivate test). SET-011 forbids deletion; the flip is
        what removes the row from day-to-day use while keeping it resolvable.
        """
        department = _create_department(config_client, facility)
        department_id = department["id"]

        patch = config_client.patch(
            f"/api/v1/departments/{department_id}/",
            {"active": False},
            format="json",
        )
        assert patch.status_code == 200, patch.content
        assert patch.json()["active"] is False

        row = Department.objects.get(pk=department_id)
        assert row.active is False
        assert Department.objects.filter(pk=department_id).count() == 1

    def test_bed_exposes_active_on_create_and_patch(self, config_client, facility):
        """Beds carry the additive ``active`` flag (SET-011).

        The migration adds ``Bed.active`` default ``True``; the serializer
        must expose it on create and honour a deactivating PATCH so a ward's
        bed can be switched off without losing its history.
        """
        department = _create_department(config_client, facility)
        ward = config_client.post(
            "/api/v1/wards/",
            {
                "department": department["id"],
                "name": "Ward A",
                "type_tag": "Medical",
            },
            format="json",
        )
        assert ward.status_code == 201, ward.content
        ward_id = ward.json()["id"]

        created = config_client.post(
            "/api/v1/beds/",
            {"ward": ward_id, "bed_number": "A1"},
            format="json",
        )
        assert created.status_code == 201, created.content
        bed_id = created.json()["id"]
        assert created.json()["active"] is True

        patch = config_client.patch(
            f"/api/v1/beds/{bed_id}/",
            {"active": False},
            format="json",
        )
        assert patch.status_code == 200, patch.content

        row = Bed.objects.get(pk=bed_id)
        assert row.active is False
        assert Bed.objects.filter(pk=bed_id).count() == 1


class TestConfigAudit:
    """SET-012: every config create and update lands an AuditEvent."""

    def test_set_002_to_005_operations_write_audit_events(
        self, config_client, facility
    ):
        """Each SET-002..005 create and update must increment the row count.

        The audit write already lives in ``TenantScopedQuerysetMixin``'s
        ``perform_*`` hooks; these assertions make the guarantee part of the
        config contract rather than an accident of the base class — a future
        viewset that bypasses the mixin would fail here. Entity type is the
        table name, matching the mixin's convention.
        """
        from apps.audit.models import AuditEvent

        def events(entity_type):
            return AuditEvent.objects.filter(
                tenant_id=TENANT_A, entity_type=entity_type
            ).count()

        department = _create_department(config_client, facility)  # SET-002
        assert events("identity.department") == 1

        patch = config_client.patch(
            f"/api/v1/departments/{department['id']}/",
            {"name": "OPD Acute"},
            format="json",
        )
        assert patch.status_code == 200, patch.content
        assert events("identity.department") == 2
        assert AuditEvent.objects.get(
            tenant_id=TENANT_A,
            entity_type="identity.department",
            action="update",
        ).entity_id == department["id"]

        ward = config_client.post(
            "/api/v1/wards/",
            {
                "department": department["id"],
                "name": "Ward A",
                "type_tag": "Medical",
            },
            format="json",
        )
        assert ward.status_code == 201, ward.content  # SET-003 (ward)
        assert events("identity.ward") == 1

        bed = config_client.post(
            "/api/v1/beds/",
            {"ward": ward.json()["id"], "bed_number": "A1"},
            format="json",
        )
        assert bed.status_code == 201, bed.content  # SET-003 (bed)
        assert events("identity.bed") == 1

        su = config_client.post(
            "/api/v1/service-units/",
            {
                "facility": str(facility.id),
                "name": "OT-1",
                "type_tag": "OT",
            },
            format="json",
        )
        assert su.status_code == 201, su.content  # SET-004
        assert events("identity.service_unit") == 1

        sp = config_client.post(
            "/api/v1/staff-positions/",
            {
                "department": department["id"],
                "designation": "Medical Officer",
                "specialty": "General Medicine",
                "sanctioned": 3,
                "in_position": 2,
            },
            format="json",
        )
        assert sp.status_code == 201, sp.content  # SET-005
        assert events("identity.staff_position") == 1
        assert StaffPosition.objects.filter(tenant_id=TENANT_A).count() == 1


class TestConfigRevisionTenantIsolation:
    """Revision history is tenant state, like every other tenant-owned row."""

    def test_tenant_b_sees_and_touches_none_of_tenant_a_revisions(
        self, config_client, other_client, facility
    ):
        """Another hospital's revision history must be invisible and untouchable.

        The mixin scopes the read to the request tenant, so B's history is
        empty and B's PATCH of A's department resolves nothing — 404, not 403,
        so the existence of A's row is not disclosed. The database layer is
        covered independently by ``test_rls_isolation`` once the migration's
        policy is applied.
        """
        department = _create_department(config_client, facility, name="OPD")
        patch = config_client.patch(
            f"/api/v1/departments/{department['id']}/",
            {"name": "OPD Acute"},
            format="json",
        )
        assert patch.status_code == 200, patch.content
        assert ConfigRevision.objects.filter(tenant_id=TENANT_A).count() == 1

        history = other_client.get("/api/v1/config-revisions/")
        assert history.status_code == 200, history.content
        assert history.json()["results"] == []
        assert ConfigRevision.objects.filter(tenant_id=TENANT_B).count() == 0

        foreign_patch = other_client.patch(
            f"/api/v1/departments/{department['id']}/",
            {"name": "Hijacked"},
            format="json",
        )
        assert foreign_patch.status_code == 404, foreign_patch.content
        assert ConfigRevision.objects.filter(tenant_id=TENANT_A).count() == 1

    def test_unauthenticated_requests_are_refused(self):
        """Anonymous callers must 401 on the revision history and the config rows.

        Deny by default: configuration and its history are hospital data, so an
        anonymous surface would leak both.
        """
        anon = APIClient()
        assert anon.get("/api/v1/config-revisions/").status_code == 401
        assert anon.get("/api/v1/departments/").status_code == 401