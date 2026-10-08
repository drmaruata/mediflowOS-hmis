"""User management endpoints (TEN-008).

``POST /users/`` must create an ``auth.User`` and an active
``UserMembership`` in one transaction: the membership row — not the user row —
is what every access token's tenant claims are derived from, so a user created
without one could never be scoped to a hospital. The tests pin the boundaries
the brief calls out — 201 + membership, no password in any response body,
cross-tenant detail reads 404, deactivation rejects the next login, and create
is gated on ``identity.users.manage`` — plus the interface guarantees stated
alongside them (PATCH works, DELETE is never offered, the minimal password
policy, and cross-tenant role/facility references are refused).

They exist because ``auth.User`` has no tenant column: scoping runs through
the membership join, and without it ``GET /users/{id}/`` would resolve any
hospital's account by primary key. The own-tenant 200 is therefore asserted
before the cross-tenant 404 — an endpoint that merely 404s everything would
otherwise pass an isolation test without being a working endpoint.
"""
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("a1000000-0000-4000-8000-00000000000a")
TENANT_B = uuid.UUID("b2000000-0000-4000-8000-00000000000b")

TEST_PASSWORD = "a-secure-test-password"


@pytest.fixture
def tenants():
    """Two hospitals, so isolation has something to separate."""
    from apps.identity_tenancy.models import Tenant

    Tenant.objects.create(id=TENANT_A, name="Hospital A", slug="user-mgmt-a")
    Tenant.objects.create(id=TENANT_B, name="Hospital B", slug="user-mgmt-b")


@pytest.fixture
def roles(tenants):
    """Roles and a facility the create payload references.

    The manager role holds ``identity.users.manage`` and, deliberately, not
    ``require_mfa``: a role demanding MFA would trip the MFA gate before the
    permission claim is evaluated, and these tests are about RBAC and
    scoping, not the second factor.
    """
    from apps.identity_tenancy.models import Facility, Role

    return {
        "manager": Role.objects.create(
            tenant_id=TENANT_A,
            name="user-manager",
            permissions=["identity.users.manage"],
        ),
        "clinician": Role.objects.create(
            tenant_id=TENANT_A, name="clinician", permissions=[]
        ),
        "foreign": Role.objects.create(
            tenant_id=TENANT_B,
            name="foreign-admin",
            permissions=["identity.users.manage"],
        ),
        "facility": Facility.objects.create(
            tenant_id=TENANT_A, name="Main Block", level="District Hospital"
        ),
    }


@pytest.fixture
def manager(roles):
    """A tenant administrator allowed to manage users of TENANT_A only."""
    from apps.identity_tenancy.models import UserMembership

    user = get_user_model().objects.create_user(
        username="tenant-user-admin", password="pw-for-tests-only"
    )
    UserMembership.objects.create(
        user=user, tenant_id=TENANT_A, role=roles["manager"], active=True
    )
    return user


@pytest.fixture
def clerk(roles):
    """An authenticated tenant user whose role lacks identity.users.manage."""
    from apps.identity_tenancy.models import UserMembership

    user = get_user_model().objects.create_user(
        username="plain-clerk", password="pw-for-tests-only"
    )
    UserMembership.objects.create(
        user=user, tenant_id=TENANT_A, role=roles["clinician"], active=True
    )
    return user


def _login(username, password="pw-for-tests-only"):
    """Issue a real access token through the API.

    Issued through ``/auth/token/`` rather than built by hand so the claims
    under test come from the same serializer production uses — the same
    pattern as ``test_rbac_enforcement``.
    """
    response = APIClient().post(
        "/api/v1/auth/token/",
        {"username": username, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


@pytest.fixture
def manager_access(manager):
    return _login(manager.username)


@pytest.fixture
def manager_client(manager_access):
    """The administrator's bearer-authenticated client (not a session)."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {manager_access}")
    return client


def _payload(roles, username="nurse-1", password=TEST_PASSWORD):
    """The create payload shape the brief specifies (TEN-008)."""
    return {
        "username": username,
        "password": password,
        "email": f"{username}@example.org",
        "role_id": str(roles["clinician"].id),
        "facility_id": str(roles["facility"].id),
    }


class TestUserManagement:
    """The TEN-008 surface: create, read, deactivate — and their boundaries."""

    def test_create_user_with_role_returns_201_and_membership_exists(
        self, roles, manager_access, manager_client
    ):
        """POST /users/ must create the user AND its active membership (TEN-008).

        A 201 that left the membership missing would produce an account no
        token can ever scope, so the row itself — tenant, role, facility,
        active — is asserted rather than inferred from the response. The
        audit assertion pins the other half of Step 3: ``perform_create``
        writes the AUD-001 event through the mixin.
        """
        from apps.audit.models import AuditEvent
        from apps.identity_tenancy.models import UserMembership

        # The claim is what the permission gate reads, so a 201 from a token
        # that never carried it would prove nothing about which check fired.
        assert "identity.users.manage" in AccessToken(manager_access).payload[
            "permissions"
        ]

        response = manager_client.post("/api/v1/users/", _payload(roles), format="json")

        assert response.status_code == 201, response.content
        user = get_user_model().objects.get(username="nurse-1")
        membership = UserMembership.objects.get(user=user)
        assert membership.tenant_id == TENANT_A
        assert membership.role_id == roles["clinician"].id
        assert membership.facility_id == roles["facility"].id
        assert membership.active is True
        # auth.User keeps Django's integer pk (the tenant-owned UUID rule
        # does not reach the built-in model), so the id serialises as a
        # number, not a UUID string.
        assert response.json()["id"] == user.id
        assert AuditEvent.objects.filter(
            tenant_id=TENANT_A,
            action="create",
            entity_type="auth_user",
            entity_id=str(user.id),
        ).exists()

    def test_password_never_in_response_body(self, roles, manager_client):
        """Neither the submitted password nor the stored hash may leave the API.

        Asserted on both the create response and a subsequent detail read:
        a serializer that exposed the field once would expose it on every
        read, handing every listed user's credential to any caller who can
        list users.
        """
        response = manager_client.post(
            "/api/v1/users/", _payload(roles, username="nurse-2"), format="json"
        )
        assert response.status_code == 201, response.content

        created = get_user_model().objects.get(username="nurse-2")
        assert "password" not in response.json()

        detail = manager_client.get(f"/api/v1/users/{response.json()['id']}/")
        assert detail.status_code == 200, detail.content
        assert "password" not in detail.json()
        # The hash itself, not just the key name — an accidental
        # ``password`` field serialisation would print it here.
        assert created.password not in detail.content.decode()

    def test_cross_tenant_user_detail_returns_404(self, roles, manager_client):
        """Another hospital's user id must not resolve (TEN-008).

        ``auth.User`` is tenant-reachable only through ``UserMembership``, so
        the detail queryset must join on it. The own-tenant 200 runs first:
        without it, a missing route or broken endpoint would satisfy the 404
        assertion and pass for isolation.
        """
        from apps.identity_tenancy.models import UserMembership

        local = get_user_model().objects.create_user(
            username="local-user", password="pw-for-tests-only"
        )
        UserMembership.objects.create(
            user=local, tenant_id=TENANT_A, role=roles["clinician"], active=True
        )
        foreign = get_user_model().objects.create_user(
            username="foreign-user", password="pw-for-tests-only"
        )
        UserMembership.objects.create(
            user=foreign, tenant_id=TENANT_B, role=roles["foreign"], active=True
        )

        own = manager_client.get(f"/api/v1/users/{local.id}/")
        assert own.status_code == 200, own.content

        cross = manager_client.get(f"/api/v1/users/{foreign.id}/")
        assert cross.status_code == 404, cross.content

    def test_deactivate_rejects_subsequent_login(self, roles, manager_client):
        """Deactivation must cut the account off at its next login (TEN-008).

        ``UserMembership.active=False`` is only a flag unless the token
        serializer refuses it, so the assertion is the login itself: the
        pre-deactivation 200 is the control proving the credentials worked
        and only the flag flipped the outcome. The account row surviving is
        asserted too — deactivation, never deletion, so audit history stays
        resolvable.
        """
        from apps.audit.models import AuditEvent
        from apps.identity_tenancy.models import UserMembership

        created = manager_client.post(
            "/api/v1/users/", _payload(roles, username="leaver"), format="json"
        )
        assert created.status_code == 201, created.content
        user_id = created.json()["id"]
        credentials = {"username": "leaver", "password": TEST_PASSWORD}

        before = APIClient().post("/api/v1/auth/token/", credentials, format="json")
        assert before.status_code == 200, before.content

        deactivated = manager_client.post(f"/api/v1/users/{user_id}/deactivate/")
        assert deactivated.status_code == 200, deactivated.content
        # The response reflects the new state, not a cached pre-flip read.
        assert deactivated.json()["active"] is False
        membership = UserMembership.objects.get(
            user__username="leaver", tenant_id=TENANT_A
        )
        assert membership.active is False
        assert get_user_model().objects.filter(username="leaver").exists()
        # The offboarding is an auditable event (AUD-001), not a silent flip.
        assert AuditEvent.objects.filter(
            tenant_id=TENANT_A,
            action="deactivate",
            entity_type="auth_user",
            entity_id=str(user_id),
        ).exists()

        after = APIClient().post("/api/v1/auth/token/", credentials, format="json")
        assert after.status_code == 401, after.content

    def test_create_without_users_manage_permission_returns_403(
        self, roles, clerk
    ):
        """POST /users/ must 403 when the claim lacks identity.users.manage (TEN-008).

        Asserted against a token whose payload is checked first, and against
        the database afterwards: a 403 that still created the user, or one
        from some other gate, would look identical to a claim denial.
        """
        access = _login(clerk.username)
        assert "identity.users.manage" not in AccessToken(access).payload[
            "permissions"
        ]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = client.post(
            "/api/v1/users/", _payload(roles, username="intruder"), format="json"
        )

        assert response.status_code == 403, response.content
        # RequirePermission names the missing code in its detail — message
        # format lives in identity_tenancy/permissions.py.
        assert "identity.users.manage" in response.json()["detail"]
        assert not get_user_model().objects.filter(username="intruder").exists()

    def test_short_password_is_rejected(self, roles, manager_client):
        """The minimal password policy (>= 12 chars) must refuse before any write.

        Pinning the policy from Step 3 of the brief: without it, the create
        endpoint would accept a four-character password for a clinical
        account.
        """
        response = manager_client.post(
            "/api/v1/users/",
            _payload(roles, username="short-pw", password="short"),
            format="json",
        )

        assert response.status_code == 400, response.content
        assert "password" in response.json()
        assert not get_user_model().objects.filter(username="short-pw").exists()

    def test_create_with_another_tenants_role_is_rejected(self, roles, manager_client):
        """role_id must belong to the caller's tenant, not merely exist (TEN-008).

        Existence-only validation would let an administrator for TENANT_A
        mint a membership carrying TENANT_B's permission bundle, because the
        token copies permissions off the role row regardless of which tenant
        owns it. The role is scoped-validated rather than trusted after a
        plain primary-key fetch.
        """
        payload = _payload(roles, username="foreign-role-user")
        payload["role_id"] = str(roles["foreign"].id)

        response = manager_client.post("/api/v1/users/", payload, format="json")

        assert response.status_code == 400, response.content
        assert not get_user_model().objects.filter(username="foreign-role-user").exists()

    def test_create_with_unknown_facility_is_rejected(self, roles, manager_client):
        """facility_id must resolve inside the tenant (TEN-008).

        ``UserMembership.facility_id`` is a bare UUID with no FK constraint,
        so validation is the only place a cross-tenant or invented facility
        pointer can be refused.
        """
        payload = _payload(roles, username="lost-facility-user")
        payload["facility_id"] = str(uuid.uuid4())

        response = manager_client.post("/api/v1/users/", payload, format="json")

        assert response.status_code == 400, response.content
        assert not get_user_model().objects.filter(
            username="lost-facility-user"
        ).exists()

    def test_delete_is_refused_so_users_are_never_removed(self, roles, manager_client):
        """DELETE /users/{id}/ must 405 — audit history must survive (TEN-008).

        ``ModelViewSet`` generates destroy by default, so without an explicit
        refusal the router would silently offer a delete that erases the
        account every audit row points at. Deactivation is the only
        offboarding path.
        """
        created = manager_client.post(
            "/api/v1/users/", _payload(roles, username="keep-forever"), format="json"
        )
        assert created.status_code == 201, created.content

        response = manager_client.delete(
            f"/api/v1/users/{created.json()['id']}/"
        )

        assert response.status_code == 405, response.content
        assert get_user_model().objects.filter(username="keep-forever").exists()

    def test_patch_updates_the_email(self, roles, manager_client):
        """PATCH /users/{id}/ must persist an editable field (TEN-008).

        The brief lists PATCH in the interface; this pins that it is wired
        and that the update reaches the database rather than only the
        response body.
        """
        created = manager_client.post(
            "/api/v1/users/", _payload(roles, username="contact-change"), format="json"
        )
        assert created.status_code == 201, created.content

        response = manager_client.patch(
            f"/api/v1/users/{created.json()['id']}/",
            {"email": "new-address@example.org"},
            format="json",
        )

        assert response.status_code == 200, response.content
        refreshed = get_user_model().objects.get(username="contact-change")
        assert refreshed.email == "new-address@example.org"
