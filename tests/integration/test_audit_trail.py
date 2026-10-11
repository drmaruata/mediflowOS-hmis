"""Audit drill-down filtering, read logging and the hash chain (AUD-001 to AUD-004).

Three halves are pinned here.

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

The **hash-chain** half pins AUD-002 and AUD-004: every writer routes through
``append_event`` so no row is left unchained, ``GET /audit-log/verify/``
recomputes the chain, an in-place mutation is reported naming the row,
interleaved writes across two tenants never cross-link, and the retention
purge trims a chain rather than breaking it.

Everything is scoped through the JWT's tenant, so a second tenant's rows are
proved invisible, and the endpoint itself stays read-only and deny-by-default.
"""
import uuid
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.audit.models import AuditEvent
from apps.audit.services import append_event, purge_expired
from apps.identity_tenancy.models import (
    Department, Facility, Role, Tenant, UserMembership,
)
from apps.identity_tenancy.tokens import TenantAwareTokenSerializer
from apps.patient_registry.models import Patient, QRCode

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

AUDIT_LOG_URL = "/api/v1/audit-log/"
VERIFY_URL = "/api/v1/audit-log/verify/"
PATIENTS_URL = "/api/v1/patients/"
QR_LIST_URL = "/api/v1/qr-codes/"

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


def _make_qr(tenant, facility):
    """One facility QR code, the shape the regenerate action acts on."""
    return QRCode.objects.create(
        tenant_id=tenant.id,
        facility=facility,
        encode_data=facility.abdm_hip_id,
    )


def _append_chained(tenant_id, entity_id="P-1", action="read", **extra):
    """One chained audit row through the real writer, as the endpoints do."""
    return append_event(
        tenant_id=tenant_id,
        action=action,
        entity_type=PATIENT_DB_TABLE,
        entity_id=entity_id,
        **extra,
    )


def _backdate(event, days):
    """Move an already-written row ``days`` into the past.

    ``occurred_at`` is ``auto_now_add`` so a row cannot be created in the
    past, and the retention tests need one on either side of a cutoff without
    sleeping. The chain is unaffected: the digest commits to the field set,
    not to the timestamp, so the row keeps verifying after the move.
    """
    AuditEvent.objects.filter(pk=event.pk).update(
        occurred_at=timezone.now() - timedelta(days=days)
    )
    event.refresh_from_db()
    return event


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


class TestAuditChainWiring:
    """Every writer routes through append_event (AUD-002).

    Before this, the mixin's write path, ``audit_read`` and the QR regenerate
    path each called ``AuditEvent.objects.create`` directly and left
    ``hash_chain`` at its empty default. A single unchained writer is a
    permanent hole in the chain that no verify pass can close, because a row
    with nothing to recompute is indistinguishable from an unmodified one.
    These three pins hold the delegation at each writer.
    """

    def setup_method(self):
        self.tenant, self.facility, self.department = _make_context()
        self.client, self.user = _make_client(self.tenant)

    def test_patient_create_update_and_read_events_all_carry_a_hash(self):
        """The delegate pin for the mixin write path and audit_read.

        Both writers pass ``user_id`` as ``auth.User``'s *integer* pk while
        the row stores a UUID; the hashed value has to be the stored value or
        no authenticated write would ever verify.
        """
        created = self.client.post(
            PATIENTS_URL,
            {
                "demographics": {
                    "name": "Chained Person",
                    "gender": "F",
                    "yearOfBirth": 1990,
                }
            },
            format="json",
        )
        assert created.status_code == 201, created.content
        patient_id = created.json()["id"]

        detail = self.client.get(f"{PATIENTS_URL}{patient_id}/")
        assert detail.status_code == 200, detail.content

        create_event = AuditEvent.objects.get(
            action="create", entity_type=PATIENT_DB_TABLE
        )
        read_event = AuditEvent.objects.get(action="read")

        assert create_event.hash_chain
        assert read_event.hash_chain
        assert read_event.user_id == uuid.UUID(int=self.user.pk)

    def test_qr_regenerate_stays_chained_and_keeps_its_source_marker(self):
        """The T14 direct write converted to append_event.

        ``regenerate`` bypasses the mixin deliberately — a re-derive is
        machine-initiated, so the write path cannot express it — but leaving
        it on ``AuditEvent.objects.create`` would leave the hole above. The
        conversion must not cost the ``source`` marker that makes such an
        event findable, nor the ``update`` action it records.
        """
        qr = _make_qr(self.tenant, self.facility)
        qr.department = self.department
        qr.save(update_fields=["department"])

        response = self.client.post(f"{QR_LIST_URL}{qr.id}/regenerate/")

        assert response.status_code == 200, response.content
        event = AuditEvent.objects.get(
            tenant_id=self.tenant.id,
            entity_type="qr_code",
            entity_id=str(qr.id),
            source="qr.regenerate",
        )
        assert event.action == "update"
        assert event.hash_chain

    def test_verify_pass_after_endpoint_writes(self):
        """A chain built only through the endpoints must verify end to end."""
        created = self.client.post(
            PATIENTS_URL,
            {
                "demographics": {
                    "name": "Verified Person",
                    "gender": "M",
                    "yearOfBirth": 1975,
                }
            },
            format="json",
        )
        assert created.status_code == 201, created.content
        patient_id = created.json()["id"]
        assert self.client.get(f"{PATIENTS_URL}{patient_id}/").status_code == 200

        response = self.client.get(VERIFY_URL)

        assert response.status_code == 200, response.content
        assert response.json() == {"valid": True, "checked": 2, "first_bad": None}


class TestAuditChainVerification:
    """GET /audit-log/verify/ recomputes the tenant's chain (AUD-002)."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client, self.user = _make_client(self.tenant)

    def test_chained_writes_verify(self):
        """The contract: a chain nobody touched recomputes all the way through.

        This pins both halves at once — that ``append_event`` hashed the
        fields the row actually stores, and that the verifier rebuilds the
        same digest from those stored columns. A disagreement about the
        canonical field set would surface here as a false tampering report,
        not as a clean pass.
        """
        for index in range(4):
            _append_chained(self.tenant.id, entity_id=f"P-{index}")

        response = self.client.get(VERIFY_URL)

        assert response.status_code == 200, response.content
        assert response.json() == {"valid": True, "checked": 4, "first_bad": None}

    def test_hash_chain_verifies_after_interleaved_writes(self):
        """Review Focus #4: interleaved writes across tenants never cross-link.

        Writing tenant A's row, then tenant B's, then A's again is the shape a
        shared chain cursor would corrupt: A's second event would take B's
        hash as its ``prev_hash``, and both chains would then report
        tampering on rows nothing touched. ``checked`` carries the isolation
        pin — each pass covers only its own tenant's rows, not both.
        """
        tenant_b, _, _ = _make_context("Chain Hospital B")
        client_b, _ = _make_client(tenant_b, username="auditor-b")

        for index in range(3):
            _append_chained(self.tenant.id, entity_id=f"A-{index}")
            _append_chained(tenant_b.id, entity_id=f"B-{index}")

        assert self.client.get(VERIFY_URL).json() == {
            "valid": True,
            "checked": 3,
            "first_bad": None,
        }
        assert client_b.get(VERIFY_URL).json() == {
            "valid": True,
            "checked": 3,
            "first_bad": None,
        }

    def test_in_place_mutation_is_detected_and_reported(self):
        """Review Focus #4's detection half: the edited row is named.

        ``save()`` on a loaded instance is the realistic tamper — an UPDATE
        issued by a session with write access to the table. The digest is
        over the stored columns, so the edit is caught at that row; the row
        after it would fail too, since it commits to this row's hash.
        ``checked`` counts the failing row as examined, which is how the
        response is documented.
        """
        rows = [
            _append_chained(self.tenant.id, entity_id=f"P-{index}")
            for index in range(3)
        ]
        rows[1].source = "qr.regenerate"
        rows[1].save(update_fields=["source"])

        response = self.client.get(VERIFY_URL)

        assert response.json()["valid"] is False
        assert response.json()["first_bad"] == str(rows[1].id)
        assert response.json()["checked"] == 2

    def test_mutation_of_a_chained_field_of_the_original_field_value(self):
        """Editing ``entity_id`` is caught the same way as editing ``source``.

        Pinned separately because ``entity_id`` is one of the three fields no
        writer ever omits: a defect that hashed only the optional fields
        would pass the ``source`` case and fail this one.
        """
        _append_chained(self.tenant.id, entity_id="P-keep")
        second = _append_chained(self.tenant.id, entity_id="P-mutate")

        AuditEvent.objects.filter(pk=second.pk).update(entity_id="P-edited")

        response = self.client.get(VERIFY_URL)

        assert response.json()["valid"] is False
        assert response.json()["first_bad"] == str(second.id)

    def test_legacy_rows_are_tolerated_not_reported_as_tampering(self):
        """Rows written before the chain existed hash nothing, and that is not
        evidence of tampering.

        They carry the column's empty default, so there is nothing to
        recompute for them. The verifier skips them without counting them and
        anchors the chain at the oldest row that does carry a digest.
        Reporting them would cry wolf on every database that predates the
        chain, and the alarm would be indistinguishable from a real one.
        """
        AuditEvent.objects.create(
            tenant_id=self.tenant.id,
            action="create",
            entity_type=PATIENT_DB_TABLE,
            entity_id="LEGACY-1",
        )
        AuditEvent.objects.create(
            tenant_id=self.tenant.id,
            action="update",
            entity_type=PATIENT_DB_TABLE,
            entity_id="LEGACY-2",
        )
        _append_chained(self.tenant.id, entity_id="NEW-1")

        response = self.client.get(VERIFY_URL)

        assert response.json() == {"valid": True, "checked": 1, "first_bad": None}

    def test_an_empty_trail_verifies(self):
        """An empty chain is valid, not a failure: nothing has been tampered."""
        response = self.client.get(VERIFY_URL)

        assert response.json() == {"valid": True, "checked": 0, "first_bad": None}

    def test_verify_reports_nothing_for_a_chain_of_only_legacy_rows(self):
        """All pre-chain rows: nothing is checked, and nothing is reported."""
        for index in range(2):
            AuditEvent.objects.create(
                tenant_id=self.tenant.id,
                action="read",
                entity_type=PATIENT_DB_TABLE,
                entity_id=f"OLD-{index}",
            )

        response = self.client.get(VERIFY_URL)

        assert response.json() == {"valid": True, "checked": 0, "first_bad": None}


class TestVerifyEndpointContract:
    """The verify endpoint's response shape and deny-by-default (AUD-003)."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client, self.user = _make_client(self.tenant)

    def test_unauthenticated_verify_is_rejected(self):
        """Deny-by-default: verifying is an authenticated read, like ``list``.

        No ``AllowAny`` — an anonymous pass over a tenant's trail would be an
        unauthenticated probe of that tenant's activity.
        """
        assert APIClient().get(VERIFY_URL).status_code == 401

    def test_response_is_exactly_the_three_documented_keys(self):
        """The contract is fixed at three keys, spelled in the plan.

        A consumer reading ``valid`` should not have to negotiate extra keys,
        and an undocumented key cannot be relied on by one client and ignored
        by another.
        """
        response = self.client.get(VERIFY_URL)

        assert response.status_code == 200, response.content
        assert set(response.json()) == {"valid", "checked", "first_bad"}
        assert isinstance(response.json()["valid"], bool)
        assert isinstance(response.json()["checked"], int)
        assert response.json()["first_bad"] is None

    def test_verify_is_not_a_write(self):
        """The action is read-only: it must not mint an audit row of its own.

        A verify pass that wrote would grow the chain it is meant to be
        observing, and a tamperer could bury an edit under passes.
        """
        self.client.get(VERIFY_URL)

        assert AuditEvent.objects.filter(action="read").count() == 0
        self.client.get(VERIFY_URL)

        assert AuditEvent.objects.count() == 0

    def test_verify_uses_the_collection_not_a_detail_route(self):
        """``detail=False``: the tenant's chain as a whole, not one row's.

        A chain is only meaningful across the tenant's rows, so the action
        hangs off the collection.
        """
        assert self.client.get(VERIFY_URL).status_code == 200
        assert self.client.get(f"{AUDIT_LOG_URL}{uuid.uuid4()}/verify/").status_code == 404


class TestAuditRetentionPurge:
    """AUD-004: retention deletes old rows of one tenant and nothing else."""

    def setup_method(self):
        self.tenant, self.facility, _ = _make_context()
        self.client, self.user = _make_client(self.tenant)

    def test_purge_deletes_only_rows_older_than_the_threshold(self):
        """The cutoff is strict, so a row inside the window survives.

        400 and 200 days are far either side of a 365-day threshold, so the
        boundary cannot bite on ordering.
        """
        stale = _backdate(_append_chained(self.tenant.id, entity_id="P-stale"), 400)
        fresh = _append_chained(self.tenant.id, entity_id="P-fresh")

        deleted = purge_expired(tenant_id=self.tenant.id, retention_days=365)

        assert deleted == 1
        assert not AuditEvent.objects.filter(pk=stale.pk).exists()
        assert AuditEvent.objects.filter(pk=fresh.pk).exists()

    def test_purge_never_touches_another_tenant(self):
        """Retention is per tenant: one hospital's policy is not another's.

        A cross-tenant delete would destroy another tenant's audit evidence
        from a job that was only asked to trim this one's — the worst possible
        outcome for a multi-tenant clinical store.
        """
        _backdate(_append_chained(self.tenant.id, entity_id="P-mine"), 400)
        foreign_tenant, _, _ = _make_context("Purge Hospital B")
        foreign = _backdate(
            _append_chained(foreign_tenant.id, entity_id="P-foreign"), 900
        )

        deleted = purge_expired(tenant_id=self.tenant.id, retention_days=365)

        assert deleted == 1
        assert AuditEvent.objects.filter(pk=foreign.pk).exists()

    def test_purge_returns_the_deleted_count(self):
        """The return value is what a scheduled task logs (Task 23)."""
        for index in range(3):
            _backdate(_append_chained(self.tenant.id, entity_id=f"P-{index}"), 400)
        _append_chained(self.tenant.id, entity_id="P-fresh")

        assert purge_expired(tenant_id=self.tenant.id, retention_days=365) == 3

    def test_purge_without_retention_days_uses_the_setting(self, settings):
        """The caller may omit the window; the setting supplies it (AUD-004).

        Task 23 schedules ``purge_expired``; requiring every caller to remember
        the retention value is how a job silently ends up purging nothing (or
        everything). ``None`` must resolve to ``settings.AUDIT_RETENTION_DAYS``
        — the same env-overridable, default-365 value the settings suite pins.
        """
        settings.AUDIT_RETENTION_DAYS = 30
        stale = _backdate(_append_chained(self.tenant.id, entity_id="P-stale"), 40)
        fresh = _append_chained(self.tenant.id, entity_id="P-fresh")

        deleted = purge_expired(tenant_id=self.tenant.id)

        assert deleted == 1
        assert not AuditEvent.objects.filter(pk=stale.pk).exists()
        assert AuditEvent.objects.filter(pk=fresh.pk).exists()

    def test_purge_of_everything_leaves_an_empty_valid_chain(self):
        """A full purge is the honest end state of the window, not a failure."""
        _backdate(_append_chained(self.tenant.id, entity_id="P-stale"), 400)

        deleted = purge_expired(tenant_id=self.tenant.id, retention_days=0)

        assert deleted == 1
        assert AuditEvent.objects.count() == 0
        assert self.client.get(VERIFY_URL).json() == {
            "valid": True,
            "checked": 0,
            "first_bad": None,
        }

    def test_verify_reanchors_on_the_oldest_surviving_row_after_a_purge(self):
        """The AUD-002/AUD-004 meeting point: a purge trims, it does not break.

        A surviving row's hash was computed against its predecessor's hash, so
        once the predecessor is purged that digest can no longer be rebuilt.
        Verification re-anchors on the oldest surviving chained row instead,
        which means the purge has to stay purely a delete: it never rewrites
        the surviving row's ``hash_chain``, because an audit store that edits
        its own rows is not append-only and the chain would be attesting to
        hashes the purge itself wrote after the fact.
        """
        old = _backdate(_append_chained(self.tenant.id, entity_id="P-old"), 400)
        middle = _append_chained(self.tenant.id, entity_id="P-middle")
        newest = _append_chained(self.tenant.id, entity_id="P-newest")
        surviving_hash = newest.hash_chain

        deleted = purge_expired(tenant_id=self.tenant.id, retention_days=365)

        assert deleted == 1
        assert not AuditEvent.objects.filter(pk=old.pk).exists()
        # The purge deleted a row; it did not touch the survivor's hash.
        newest.refresh_from_db()
        assert newest.hash_chain == surviving_hash
        assert middle.hash_chain
        assert self.client.get(VERIFY_URL).json() == {
            "valid": True,
            "checked": 2,
            "first_bad": None,
        }

    def test_a_hole_punched_in_the_middle_is_still_detected(self):
        """The re-anchor is a one-time concession, so it cannot hide an edit.

        Deleting a row by hand is not what the retention job does, so it is
        not covered by the anchor: the row after the gap commits to a hash
        that is no longer there and fails, which is what stops a purge
        becoming a way to remove one event among the rest.
        """
        rows = [
            _backdate(_append_chained(self.tenant.id, entity_id=f"P-{index}"), 200 - index)
            for index in range(3)
        ]
        removed = rows[1]
        AuditEvent.objects.filter(pk=removed.pk).delete()

        response = self.client.get(VERIFY_URL)

        assert response.json()["valid"] is False
        assert response.json()["first_bad"] == str(rows[2].id)

