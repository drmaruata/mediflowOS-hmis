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

from apps.identity_tenancy.models import SETUP_STEPS, SetupProgress

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("a1111111-0000-4000-8000-000000000001")
TENANT_B = uuid.UUID("b2222222-0000-4000-8000-000000000002")

TEST_PASSWORD = "pw-for-tests-only"

SETUP_MANAGE = "identity.setup.manage"


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

    The returned token is asserted to actually carry the setup claim when it
    is seated: a 200 from a token that never held the code would prove nothing
    about which gate fired (same claim-assertion discipline as the RBAC
    suites).
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
    if "identity.setup.manage" in permissions:
        assert "identity.setup.manage" in AccessToken(access).payload["permissions"]
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