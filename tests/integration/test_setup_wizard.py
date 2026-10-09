"""Resumable setup wizard state (SET-001, SET-008, SET-009).

``GET /api/v1/setup/`` returns the whole wizard as an ordered list of
declared steps with a ``complete`` flag on each (a step with no stored row is
still present, flagged incomplete — SET-008); ``PUT /api/v1/setup/{step_key}/``
upserts the step's saved state so a resumed session continues where it left
off (SET-001); and continuing edits after setup belong to the same state
surface (SET-009). The tests pin the contract the brief calls out: a PUT
completes exactly its own step, a second PUT updates the same row instead of
duplicating it, an unknown step key 404s, tenant B never sees tenant A's
progress, anonymous callers are refused, and every write lands an audit event
(SET-012) through the tenant mixin's hook.

They exist because a wizard that cannot resume is the classic silent failure:
the state table is all the evidence the UI has of where a hospital stopped,
and a wizard that forgets a completed step — or shows another hospital's
steps — corrupts the onboarding a tenant administrator cannot undo.
"""
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.identity_tenancy.models import (
    BaselineInput,
    ReferenceData,
    SETUP_STEPS,
    SetupProgress,
)

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("a1111111-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("b2222222-0000-4000-8000-000000000002")

TEST_PASSWORD = "pw-for-tests-only"

SETUP_MANAGE = "identity.setup.manage"
REFERENCE_WRITE = "identity.reference_data.write"
BASELINE_WRITE = "identity.baseline_input.write"


def _login(username, password=TEST_PASSWORD):
    """Issue a real access token through the API.

    Issued through ``/auth/token/`` rather than built by hand so the claims
    under test come from the same serializer production uses — the same
    pattern as ``test_tenant_onboarding`` and ``test_rbac_enforcement``.
    """
    response = APIClient().post(
        "/api/v1/auth/token/",
        {"username": username, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


def _make_client(tenant_id, username, slug, permissions):
    """An authenticated client whose token carries ``permissions``.

    The returned token is asserted to actually carry every seated claim: a
    200 from a token that never held the code would prove nothing about which
    gate fired (same claim-assertion discipline as the RBAC suites).
    """
    from apps.identity_tenancy.models import Role, Tenant, UserMembership

    Tenant.objects.create(id=tenant_id, name=slug, slug=slug)
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
def client():
    """A tenant administrator of tenant A with the setup claim."""
    return _make_client(TENANT_A, "setup-admin-a", "tenant-a", [SETUP_MANAGE])


@pytest.fixture
def other_client():
    """A tenant administrator of tenant B with the same claim."""
    return _make_client(TENANT_B, "setup-admin-b", "tenant-b", [SETUP_MANAGE])


@pytest.fixture
def reference_client():
    """A tenant administrator of tenant A with the indicator claims.

    Reference data and baseline inputs are the last two wizard steps
    (SET-006, SET-007), so the one fixture holds both write claims the new
    endpoints gate on.
    """
    return _make_client(
        TENANT_A, "indicator-admin-a", "tenant-a", [REFERENCE_WRITE, BASELINE_WRITE]
    )


@pytest.fixture
def reference_other_client():
    """A tenant administrator of tenant B with the same indicator claims.

    A write claim is required to reach the tenant-scoped object lookup; a
    claim-less B caller would 403 at the permission gate before scoping ever
    ran, which tests the gate, not the isolation. This fixture seats the
    claims so an assertion like "B's DELETE of A's row 404s" exercises the
    scoping itself.
    """
    return _make_client(
        TENANT_B, "indicator-admin-b", "tenant-b", [REFERENCE_WRITE, BASELINE_WRITE]
    )


class TestSetupWizardState:
    """The SET-001/SET-008 surface: ordered steps, complete flags, upserts."""

    def test_put_completes_one_step_and_get_flags_rest_incomplete(self, client):
        """PUT must complete exactly its step; GET shows all steps, in order.

        The list is orchestrated from the declared step list — a step with no
        row still appears, flagged pending/incomplete — because that is what
        makes the wizard resumable (SET-008): the response is the full wizard,
        not a raw dump of whatever rows happen to exist.
        """
        step_key = SETUP_STEPS[1]

        put = client.put(
            f"/api/v1/setup/{step_key}/",
            {"status": "complete", "payload": {"name": "Seed Hospital"}},
            format="json",
        )

        assert put.status_code == 200, put.content
        put_body = put.json()
        assert put_body["step_key"] == step_key
        assert put_body["status"] == "complete"
        assert put_body["complete"] is True

        body = client.get("/api/v1/setup/").json()
        assert [item["step_key"] for item in body] == list(SETUP_STEPS)
        by_key = {item["step_key"]: item for item in body}
        assert by_key[step_key]["complete"] is True
        for key in SETUP_STEPS[2:]:
            assert by_key[key]["complete"] is False
            assert by_key[key]["status"] == "pending"

    def test_re_put_updates_the_same_row(self, client):
        """A second PUT on a step must update, never mint a duplicate row.

        ``(tenant_id, step_key)`` is unique, and resumed sessions PUT the same
        step repeatedly; a duplicate row would make the wizard's state
        ambiguous. Asserted from the database, not the response, so a response
        that merely *looked* updated cannot pass.
        """
        step_key = SETUP_STEPS[3]

        first = client.put(
            f"/api/v1/setup/{step_key}/",
            {"status": "in_progress", "payload": {"draft": 1}},
            format="json",
        )
        assert first.status_code == 200, first.content

        second = client.put(
            f"/api/v1/setup/{step_key}/",
            {"status": "complete", "payload": {"final": 2}},
            format="json",
        )
        assert second.status_code == 200, second.content

        rows = SetupProgress.objects.filter(tenant_id=TENANT_A, step_key=step_key)
        assert rows.count() == 1
        row = rows.get()
        assert row.status == "complete"
        assert row.payload == {"final": 2}

    def test_unknown_step_key_returns_404(self, client):
        """A step outside the declared wizard must 404, not create a row.

        The declared list is the whole interface; a typo'd step that minted a
        stray row would never be rendered by the orchestration, silently
        divorcing storage from the wizard.
        """
        response = client.put(
            "/api/v1/setup/not_a_step/", {"status": "complete"}, format="json"
        )

        assert response.status_code == 404, response.content
        assert SetupProgress.objects.count() == 0

    def test_incomplete_query_returns_only_incomplete_steps(self, client):
        """``?incomplete=true`` narrows the list to what remains (SET-008).

        A resumed wizard needs exactly the still-required steps; the default
        list keeps the whole ordered wizard. Only the literal ``true`` opts in
        so a stray parameter cannot silently truncate the UI.
        """
        step_key = SETUP_STEPS[0]
        put = client.put(
            f"/api/v1/setup/{step_key}/",
            {"status": "complete", "payload": {"name": "A"}},
            format="json",
        )
        assert put.status_code == 200, put.content

        body = client.get("/api/v1/setup/", {"incomplete": "true"}).json()
        keys = [item["step_key"] for item in body]
        assert step_key not in keys
        assert keys == list(SETUP_STEPS[1:])
        assert all(not item["complete"] for item in body)

        full = client.get("/api/v1/setup/").json()
        assert len(full) == len(SETUP_STEPS)

    def test_status_is_restricted_to_the_three_enum_values(self, client):
        """A status outside pending/in_progress/complete must 400.

        The wizard stepper keys its rendering off exactly three states; a
        fourth value would render as an unknown step and could not be saved
        anywhere.
        """
        response = client.put(
            f"/api/v1/setup/{SETUP_STEPS[0]}/",
            {"status": "not-a-status", "payload": {}},
            format="json",
        )

        assert response.status_code == 400, response.content
        assert SetupProgress.objects.count() == 0


class TestSetupWizardTenantIsolation:
    """Wizard state is tenant state, like every other tenant-owned row."""

    def test_tenant_b_sees_none_of_tenant_a_progress(self, client, other_client):
        """Another hospital's step state must be invisible (SET-001).

        The mixin scopes the queryset to the request tenant; the same table is
        covered at the database layer by ``test_rls_isolation`` once the
        migration's policy is applied.
        """
        put = client.put(
            f"/api/v1/setup/{SETUP_STEPS[0]}/",
            {"status": "complete", "payload": {"name": "Tenant A"}},
            format="json",
        )
        assert put.status_code == 200, put.content

        body = other_client.get("/api/v1/setup/").json()
        by_key = {item["step_key"]: item for item in body}
        assert by_key[SETUP_STEPS[0]]["status"] == "pending"
        assert by_key[SETUP_STEPS[0]]["complete"] is False
        assert by_key[SETUP_STEPS[0]]["payload"] is None
        assert SetupProgress.objects.filter(tenant_id=TENANT_B).count() == 0

    def test_unauthenticated_requests_are_refused(self):
        """Anonymous callers must 401 on both reads and writes.

        Deny by default: the wizard exposes hospital configuration, so an
        anonymous surface — read or write — would leak setup state and let
        strangers mutate it.
        """
        anon = APIClient()

        assert anon.get("/api/v1/setup/").status_code == 401
        assert (
            anon.put(
                f"/api/v1/setup/{SETUP_STEPS[0]}/",
                {"status": "complete"},
                format="json",
            ).status_code
            == 401
        )

    def test_write_requires_the_setup_manage_claim(self):
        """PUT without ``identity.setup.manage`` 403s naming the code.

        Reads stay authorised by authentication plus tenant scoping, matching
        every other tenant-owned resource (TEN-002); writes are gated on the
        claim, and the 403 must name the missing code so the refusal is
        distinguishable from the MFA gate's.
        """
        from apps.identity_tenancy.models import Role, Tenant, UserMembership

        Tenant.objects.create(id=TENANT_A, name="tenant-a", slug="tenant-a")
        user = get_user_model().objects.create_user(
            username="setup-reader", password=TEST_PASSWORD
        )
        role = Role.objects.create(
            tenant_id=TENANT_A, name="role-readonly", permissions=["identity.users.manage"]
        )
        UserMembership.objects.create(
            user=user, tenant_id=TENANT_A, role=role, active=True
        )
        access = _login(user.username)
        assert "identity.setup.manage" not in AccessToken(access).payload["permissions"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        assert client.get("/api/v1/setup/").status_code == 200
        response = client.put(
            f"/api/v1/setup/{SETUP_STEPS[0]}/",
            {"status": "complete"},
            format="json",
        )
        assert response.status_code == 403, response.content
        assert SETUP_MANAGE in response.json()["detail"]
        assert SetupProgress.objects.count() == 0


class TestSetupWizardAudit:
    """Every setup write is audited (SET-012)."""

    def test_put_writes_an_audit_event_per_change(self, client):
        """A PUT must land an AUD-001 event, one per write, never silent.

        The wizard is configuration; SET-012 audits all configuration changes,
        and a resumed session that overwrote a completed step without a trace
        would be un-reviewable. The entity type is the table name, matching
        the mixin's convention for every other audited resource.
        """
        from apps.audit.models import AuditEvent

        def audit_count():
            return AuditEvent.objects.filter(
                tenant_id=TENANT_A, entity_type="identity.setup_progress"
            ).count()

        step_key = SETUP_STEPS[5]
        created = client.put(
            f"/api/v1/setup/{step_key}/",
            {"status": "in_progress", "payload": {"started": True}},
            format="json",
        )
        assert created.status_code == 200, created.content
        assert audit_count() == 1

        updated = client.put(
            f"/api/v1/setup/{step_key}/",
            {"status": "complete", "payload": {"done": True}},
            format="json",
        )
        assert updated.status_code == 200, updated.content
        assert audit_count() == 2

        row = SetupProgress.objects.get(tenant_id=TENANT_A, step_key=step_key)
        # ``get`` instead of ``order_by(...).last()``: two audit inserts can
        # share a timestamp, and the workflow the test pins is the action, not
        # a microsecond race.
        event = AuditEvent.objects.get(
            tenant_id=TENANT_A,
            entity_type="identity.setup_progress",
            action="update",
        )
        assert event.entity_id == str(row.pk)


#: The reference-data kinds the API accepts (SET-006). The choices live on the
#: model; the duplicates here are what the tests send, so a kind that strays
#: from the brief's list fails loudly in two places instead of one.
CATCHMENT = "catchment_population"
COMMODITY = "essential_commodity"


class TestReferenceDataApi:
    """Indicator-denominator reference data (SET-006)."""

    def test_catchment_population_saved_and_returned_for_the_wizard(self, reference_client):
        """A catchment population row must round-trip: 201 with the stored
        shape, then a kind-filtered GET returns it.

        This is the reference-data step of the wizard (SET-006): the stored
        row is what the indicator engine later divides by. Asserting the
        create response AND the list response pins both halves of the
        contract — a row that only appeared in one would not serve the
        wizard.
        """
        create = reference_client.post(
            "/api/v1/reference-data/",
            {"kind": CATCHMENT, "key": "deoni", "value": {"population": 125000}},
            format="json",
        )
        assert create.status_code == 201, create.content
        body = create.json()
        assert body["kind"] == CATCHMENT
        assert body["key"] == "deoni"
        assert body["value"] == {"population": 125000}
        assert body["active"] is True
        assert body["tenant_id"] == str(TENANT_A)

        listing = reference_client.get(
            "/api/v1/reference-data/", {"kind": CATCHMENT}
        ).json()["results"]
        assert [item["key"] for item in listing] == ["deoni"]

    def test_kind_filter_limits_the_list(self, reference_client):
        """``?kind=`` must narrow the list to that kind alone (SET-006).

        The wizard writes one kind at a time; an unfiltered list mixing kinds
        would make the response ambiguous about which denominator it carries.
        """
        for kind, key in (
            ("ambulance", "state-ambulance"),
            (COMMODITY, "oxygen"),
            (CATCHMENT, "deoni"),
        ):
            post = reference_client.post(
                "/api/v1/reference-data/",
                {"kind": kind, "key": key, "value": {"count": 1}},
                format="json",
            )
            assert post.status_code == 201, post.content

        listing = reference_client.get(
            "/api/v1/reference-data/", {"kind": "ambulance"}
        ).json()["results"]
        assert [item["key"] for item in listing] == ["state-ambulance"]

    def test_duplicate_kind_key_returns_409(self, reference_client):
        """A second POST of the same ``(kind, key)`` in this tenant is 409.

        ``(tenant_id, kind, key)`` is unique; a duplicate is a state conflict
        the caller must reconcile, not a malformed payload (400) and not a
        crash (500). One row must remain in the database.
        """
        payload = {"kind": CATCHMENT, "key": "deoni", "value": {"population": 1}}

        first = reference_client.post("/api/v1/reference-data/", payload, format="json")
        assert first.status_code == 201, first.content

        second = reference_client.post("/api/v1/reference-data/", payload, format="json")
        assert second.status_code == 409, second.content
        assert (
            ReferenceData.objects.filter(tenant_id=TENANT_A, kind=CATCHMENT, key="deoni").count()
            == 1
        )

    def test_deactivate_keeps_row_and_excludes_from_default_list(self, reference_client):
        """DELETE deactivates, never hard-deletes (SET-011).

        The row must survive with ``active`` false — audit history and locked
        indicator periods keep pointing at it — while the default (and
        kind-filtered) list excludes it. Read back from the database, not the
        response, so a response that merely looked deleted cannot pass.
        """
        create = reference_client.post(
            "/api/v1/reference-data/",
            {"kind": "ambulance", "key": "district", "value": {"count": 3}},
            format="json",
        )
        assert create.status_code == 201, create.content
        row_id = create.json()["id"]

        delete = reference_client.delete(f"/api/v1/reference-data/{row_id}/")
        assert delete.status_code == 204, delete.content

        row = ReferenceData.objects.get(pk=row_id)
        assert str(row.tenant_id) == str(TENANT_A)
        assert row.active is False

        assert [item["key"] for item in reference_client.get("/api/v1/reference-data/").json()["results"]] == []
        assert (
            reference_client.get("/api/v1/reference-data/", {"kind": "ambulance"}).json()["results"]
            == []
        )

    def test_invalid_kind_is_rejected(self, reference_client):
        """A kind outside the three declared values must 400, not store.

        The indicator engine keys its denominator lookups off exactly the
        declared kinds; a fourth value would be stored yet unreachable.
        """
        response = reference_client.post(
            "/api/v1/reference-data/",
            {"kind": "not-a-kind", "key": "x", "value": {"count": 1}},
            format="json",
        )
        assert response.status_code == 400, response.content
        assert ReferenceData.objects.count() == 0

    def test_write_requires_the_reference_data_write_claim(self):
        """POST without ``identity.reference_data.write`` 403s naming the code.

        Reads stay authorised by authentication plus tenant scoping (TEN-002);
        writes are gated on the claim, and the 403 must name the missing code
        so the refusal is distinguishable from the MFA gate's.
        """
        from apps.identity_tenancy.models import Role, Tenant, UserMembership

        Tenant.objects.create(id=TENANT_A, name="tenant-a", slug="tenant-a")
        user = get_user_model().objects.create_user(
            username="reference-reader", password=TEST_PASSWORD
        )
        role = Role.objects.create(
            tenant_id=TENANT_A,
            name="role-readonly",
            permissions=["identity.users.manage"],
        )
        UserMembership.objects.create(
            user=user, tenant_id=TENANT_A, role=role, active=True
        )
        access = _login(user.username)
        assert REFERENCE_WRITE not in AccessToken(access).payload["permissions"]
        reader = APIClient()
        reader.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        assert reader.get("/api/v1/reference-data/").status_code == 200
        response = reader.post(
            "/api/v1/reference-data/",
            {"kind": CATCHMENT, "key": "deoni", "value": {"population": 1}},
            format="json",
        )
        assert response.status_code == 403, response.content
        assert REFERENCE_WRITE in response.json()["detail"]
        assert ReferenceData.objects.count() == 0


class TestBaselineInputApi:
    """Baseline/manual indicator inputs collected by the wizard (SET-007)."""

    def test_baseline_input_saved_and_returned(self, reference_client):
        """A baseline input must round-trip: 201 with the stored shape, then a
        GET returns it.

        SET-007's wizard step files the value with the indicator's source code
        and the period it locks; the default ``source`` is ``manual`` because
        the wizard collects by hand and ``imported`` is the bulk-import path.
        """
        create = reference_client.post(
            "/api/v1/baseline-inputs/",
            {"indicator_source_code": "HMI-10", "period": "2026-10", "value": 85.5},
            format="json",
        )
        assert create.status_code == 201, create.content
        body = create.json()
        assert body["indicator_source_code"] == "HMI-10"
        assert body["period"] == "2026-10"
        assert body["value"] == 85.5
        assert body["source"] == "manual"
        assert body["tenant_id"] == str(TENANT_A)

        listing = reference_client.get("/api/v1/baseline-inputs/").json()["results"]
        assert [item["indicator_source_code"] for item in listing] == ["HMI-10"]

    def test_negative_value_is_rejected(self, reference_client):
        """A negative baseline value must 400 and store nothing.

        A negative count or rate is meaningless for every indicator the
        baseline step collects, so it is refused at the serializer (AGENTS §4
        puts business rules there), before any row is written.
        """
        response = reference_client.post(
            "/api/v1/baseline-inputs/",
            {"indicator_source_code": "HMI-10", "period": "2026-10", "value": -1},
            format="json",
        )
        assert response.status_code == 400, response.content
        assert BaselineInput.objects.count() == 0

    def test_invalid_source_is_rejected(self, reference_client):
        """A source outside ``manual``/``imported`` must 400.

        The two sources are the only provenance a baseline value can have;
        anything else would be stored yet explainable by nothing.
        """
        response = reference_client.post(
            "/api/v1/baseline-inputs/",
            {
                "indicator_source_code": "HMI-10",
                "period": "2026-10",
                "value": 3,
                "source": "exported",
            },
            format="json",
        )
        assert response.status_code == 400, response.content
        assert BaselineInput.objects.count() == 0

    def test_write_requires_the_baseline_input_write_claim(self):
        """POST without ``identity.baseline_input.write`` 403s naming the code."""
        from apps.identity_tenancy.models import Role, Tenant, UserMembership

        Tenant.objects.create(id=TENANT_A, name="tenant-a", slug="tenant-a")
        user = get_user_model().objects.create_user(
            username="baseline-reader", password=TEST_PASSWORD
        )
        role = Role.objects.create(
            tenant_id=TENANT_A,
            name="role-readonly",
            permissions=["identity.users.manage"],
        )
        UserMembership.objects.create(
            user=user, tenant_id=TENANT_A, role=role, active=True
        )
        access = _login(user.username)
        assert BASELINE_WRITE not in AccessToken(access).payload["permissions"]
        reader = APIClient()
        reader.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        assert reader.get("/api/v1/baseline-inputs/").status_code == 200
        response = reader.post(
            "/api/v1/baseline-inputs/",
            {"indicator_source_code": "HMI-10", "period": "2026-10", "value": 1},
            format="json",
        )
        assert response.status_code == 403, response.content
        assert BASELINE_WRITE in response.json()["detail"]
        assert BaselineInput.objects.count() == 0


class TestReferenceBaselineTenantIsolation:
    """Reference data and baseline inputs are tenant state, like every row."""

    def test_tenant_b_sees_none_of_tenant_a_reference_data(
        self, reference_client, reference_other_client
    ):
        """Another hospital's reference data must be invisible and untouchable.

        The mixin scopes the queryset to the request tenant, so B's list is
        empty and B's DELETE of A's row resolves nothing — 404, not 403, so
        the existence of A's row is not disclosed. The database layer is
        covered independently by ``test_rls_isolation`` once the migration's
        policy is applied.
        """
        create = reference_client.post(
            "/api/v1/reference-data/",
            {"kind": CATCHMENT, "key": "deoni", "value": {"population": 125000}},
            format="json",
        )
        assert create.status_code == 201, create.content
        row_id = create.json()["id"]

        assert reference_other_client.get("/api/v1/reference-data/").json()["results"] == []
        assert ReferenceData.objects.filter(tenant_id=TENANT_B).count() == 0
        assert (
            reference_other_client.delete(f"/api/v1/reference-data/{row_id}/").status_code
            == 404
        )
        assert ReferenceData.objects.get(pk=row_id).active is True

    def test_tenant_b_sees_none_of_tenant_a_baseline_inputs(
        self, reference_client, other_client
    ):
        """Another hospital's baseline values must be invisible (SET-007)."""
        create = reference_client.post(
            "/api/v1/baseline-inputs/",
            {"indicator_source_code": "HMI-10", "period": "2026-10", "value": 85.5},
            format="json",
        )
        assert create.status_code == 201, create.content

        assert other_client.get("/api/v1/baseline-inputs/").json()["results"] == []
        assert BaselineInput.objects.filter(tenant_id=TENANT_B).count() == 0

    def test_same_kind_key_in_another_tenant_is_not_a_conflict(
        self, reference_client, reference_other_client
    ):
        """Uniqueness is per tenant, so B may reuse A's ``(kind, key)``.

        The unique constraint leads with ``tenant_id``; a global duplicate
        check would let one hospital's row block another's configuration.
        """
        payload = {"kind": CATCHMENT, "key": "deoni", "value": {"population": 1}}
        first = reference_client.post("/api/v1/reference-data/", payload, format="json")
        assert first.status_code == 201, first.content

        second = reference_other_client.post(
            "/api/v1/reference-data/", payload, format="json"
        )
        assert second.status_code == 201, second.content
        assert ReferenceData.objects.filter(tenant_id=TENANT_A).count() == 1
        assert ReferenceData.objects.filter(tenant_id=TENANT_B).count() == 1

    def test_anonymous_requests_are_refused_on_both(self):
        """Anonymous callers must 401 on reads and writes of both resources.

        Deny by default: indicator denominators and baseline values are
        hospital configuration, so an anonymous surface would leak them and
        let strangers mutate them.
        """
        anon = APIClient()
        for url in ("/api/v1/reference-data/", "/api/v1/baseline-inputs/"):
            assert anon.get(url).status_code == 401
            assert anon.post(url, {}, format="json").status_code == 401


class TestReferenceBaselineAudit:
    """Every reference-data and baseline-input write is audited (SET-012)."""

    def test_writes_land_audit_events(self, reference_client):
        """Creates and the deactivate must each land an AUD-001 event.

        SET-012 audits all configuration changes; the indicator denominators
        and baseline values are exactly the kind of configuration a locked
        reporting period later needs to be able to justify. The entity type
        is the table name, matching the mixin's convention.
        """
        from apps.audit.models import AuditEvent

        def events(entity_type):
            return AuditEvent.objects.filter(
                tenant_id=TENANT_A, entity_type=entity_type
            ).count()

        created = reference_client.post(
            "/api/v1/reference-data/",
            {"kind": CATCHMENT, "key": "deoni", "value": {"population": 125000}},
            format="json",
        )
        assert created.status_code == 201, created.content
        assert events("identity.reference_data") == 1

        baseline = reference_client.post(
            "/api/v1/baseline-inputs/",
            {"indicator_source_code": "HMI-10", "period": "2026-10", "value": 85.5},
            format="json",
        )
        assert baseline.status_code == 201, baseline.content
        assert events("identity.baseline_input") == 1

        delete = reference_client.delete(
            f"/api/v1/reference-data/{created.json()['id']}/"
        )
        assert delete.status_code == 204, delete.content
        assert events("identity.reference_data") == 2
        event = AuditEvent.objects.get(
            tenant_id=TENANT_A,
            entity_type="identity.reference_data",
            action="delete",
        )
        assert event.entity_id == created.json()["id"]