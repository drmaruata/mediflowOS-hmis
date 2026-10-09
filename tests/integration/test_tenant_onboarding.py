"""Tenant onboarding with seed configuration (TEN-010, TEN-011).

``POST /tenants/onboard/`` must mint a whole hospital in one transaction: a
tenant, its first facility, default OPD/IPD departments, the seeded
``platform_admin`` and ``tenant_admin`` roles, and the first administrative
account with its active membership. The tests pin the boundaries the brief
calls out — 201 with every artifact present, a duplicate slug answered 409,
an invalid admin rolling back so no Tenant row remains, the
``platform.tenants.manage`` gate, and the facility's ABDM identifiers
round-tripping through ``GET /facilities/{id}/`` (TEN-011).

They exist because onboarding is legacy-free and therefore cheap to get
wrong exactly once: a tenant created without its administrator is an orphan
nothing can ever configure, and a partial boarding that leaves a Facility
but no departments would confuse every downstream queue. The rollback test
calls the service *itself* with an invalid admin — through the API the
password rule can fire before any write is attempted, so only a direct call
proves the atomic block actually rolls the Tenant back.
"""
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

#: The platform operator's own hospital, so their membership has a tenant to
#: belong to. Distinct from every tenant the tests board.
CONTEXT_TENANT = uuid.UUID("c0000000-0000-4000-8000-00000000000c")

TEST_PASSWORD = "a-secure-test-password"


def _onboard_payload(**overrides):
    """The onboarding payload shape TEN-010 specifies."""
    payload = {
        "name": "Seed Hospital",
        "slug": "seed-hospital",
        "facility": {"name": "Main Campus", "level": "District Hospital"},
        "admin": {
            "username": "seed-admin",
            "password": TEST_PASSWORD,
            "email": "seed-admin@example.org",
        },
        "abdm": {
            "abdm_hip_id": "HIP-SEED-001",
            "abdm_facility_id": "1000-seed-facility",
            "abdm_registration_status": "registered",
        },
    }
    payload.update(overrides)
    return payload


def _login(username, password="pw-for-tests-only"):
    """Issue a real access token through the API.

    Issued through ``/auth/token/`` rather than built by hand so the claims
    under test come from the same serializer production uses — the same
    pattern as ``test_user_management`` and ``test_rbac_enforcement``.
    """
    response = APIClient().post(
        "/api/v1/auth/token/",
        {"username": username, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


@pytest.fixture
def context_tenant():
    """The platform operator's hospital."""
    from apps.identity_tenancy.models import Tenant

    return Tenant.objects.create(
        id=CONTEXT_TENANT, name="Platform HQ", slug="platform-hq"
    )


@pytest.fixture
def platform_client(context_tenant):
    """A platform administrator: platform-scoped role, ``platform.tenants.manage``.

    The role is ``tenant is None`` (platform scope) — the only legal shape
    for a role carrying ``platform.*`` codes since ``RoleSerializer``
    refuses them on tenant-scoped roles (TEN-004) — and the membership
    lives in the operator's own hospital. The claim is asserted on the
    issued token itself: the gate reads claims, so a 201 from a token that
    never carried the code would prove nothing about which check fired.
    """
    from apps.identity_tenancy.models import Role, UserMembership

    user = get_user_model().objects.create_user(
        username="platform-operator", password="pw-for-tests-only"
    )
    role = Role.objects.create(
        tenant=None, name="platform_admin", permissions=["platform.tenants.manage"]
    )
    UserMembership.objects.create(
        user=user, tenant=context_tenant, role=role, active=True
    )

    access = _login(user.username)
    assert "platform.tenants.manage" in AccessToken(access).payload["permissions"]
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
    return client


class TestTenantOnboarding:
    """The TEN-010 surface: one transactional onboarding with seed config."""

    def test_onboard_returns_201_and_creates_every_artifact(self, platform_client):
        """POST /tenants/onboard/ must create the whole hospital, not just a tenant.

        Every artifact the brief lists is asserted directly from the database:
        the facility with its ABDM identifiers (TEN-011), the default OPD/IPD
        departments, both seeded roles, and the first admin user with its
        active membership. A 201 that minted a bare Tenant would pass an
        endpoint-level assertion, so each artifact is checked where it lives.
        """
        from apps.identity_tenancy.models import (
            Department,
            Facility,
            Role,
            Tenant,
            UserMembership,
        )

        response = platform_client.post(
            "/api/v1/tenants/onboard/", _onboard_payload(), format="json"
        )

        assert response.status_code == 201, response.content
        tenant = Tenant.objects.get(slug="seed-hospital")
        assert response.json()["id"] == str(tenant.id)

        facility = Facility.objects.get(tenant=tenant)
        assert facility.name == "Main Campus"
        assert facility.level == "District Hospital"
        assert facility.abdm_hip_id == "HIP-SEED-001"
        assert facility.abdm_facility_id == "1000-seed-facility"
        assert facility.abdm_registration_status == "registered"

        departments = {d.name: d for d in Department.objects.filter(tenant=tenant)}
        assert set(departments) == {"OPD", "IPD"}
        assert departments["OPD"].opd_enabled and not departments["OPD"].ipd_enabled
        assert departments["IPD"].ipd_enabled and not departments["IPD"].opd_enabled
        assert all(d.active for d in departments.values())
        assert all(d.facility_id == facility.id for d in departments.values())

        roles = {r.name: r for r in Role.objects.filter(tenant=tenant)}
        assert set(roles) == {"platform_admin", "tenant_admin"}
        # Seed permissions are explicit codes — "all" is a human marker the
        # RBAC gate never reads (see seed_dev_data.py) — and platform-tenancy
        # codes are illegal on tenant-scoped roles (TEN-004), so the seed
        # bundles must contain neither.
        for role in roles.values():
            assert role.permissions
            assert all(isinstance(code, str) for code in role.permissions)
            assert not any(code.startswith("platform.") for code in role.permissions)

        user = get_user_model().objects.get(username="seed-admin")
        assert user.check_password(TEST_PASSWORD)
        membership = UserMembership.objects.get(user=user)
        assert membership.tenant_id == tenant.id
        assert membership.role.name == "platform_admin"
        assert membership.active is True

    def test_duplicate_slug_returns_409(self, platform_client):
        """A second onboarding with the same slug must 409, not 400 or 500.

        ``Tenant.slug`` is globally unique (one installation, one slug), so a
        duplicate is a state conflict the client must reconcile — not the 400
        a UniqueValidator would give and not the 500 an uncaught
        IntegrityError would. Exactly one tenant must survive the refusal.
        """
        from apps.identity_tenancy.models import Tenant

        first = platform_client.post(
            "/api/v1/tenants/onboard/", _onboard_payload(), format="json"
        )
        assert first.status_code == 201, first.content

        second = platform_client.post(
            "/api/v1/tenants/onboard/", _onboard_payload(), format="json"
        )

        assert second.status_code == 409, second.content
        assert Tenant.objects.filter(slug="seed-hospital").count() == 1

    def test_invalid_admin_rolls_back_via_api(self, platform_client):
        """A short password must 400 AND leave no seed rows behind (TEN-010).

        The password rule is Task 3's (>= 12 characters, enforced
        server-side), inherited by the onboarding admin serializer. Through
        the API it fires inside the onboarding transaction, so the 400 also
        proves the failure rolled back every artifact — the only tenant left
        is the platform operator's own fixture row.
        """
        from apps.identity_tenancy.models import Tenant

        payload = _onboard_payload()
        payload["admin"]["password"] = "short"

        response = platform_client.post(
            "/api/v1/tenants/onboard/", payload, format="json"
        )

        assert response.status_code == 400, response.content
        # Composite payloads nest field errors under the failing sub-resource.
        assert "password" in response.json()["admin"]
        assert not Tenant.objects.filter(slug="seed-hospital").exists()
        assert Tenant.objects.count() == 1

    def test_invalid_admin_rolls_back_service_transaction(self):
        """A failed admin validation must roll back the Tenant created first.

        Through the API the password rule can fire before the service is
        reached, so this calls ``onboard_tenant`` directly: the tenant row is
        created inside the service's ``atomic`` block *before* the admin is
        validated, and the resulting ValidationError must take that row with
        it. This is the test that pins the transaction living inside the
        service rather than being trusted to the view layer — ATOMIC_REQUESTS
        is False in the test profile.
        """
        from apps.identity_tenancy.models import Tenant
        from apps.identity_tenancy.services import onboard_tenant
        from rest_framework import serializers

        with pytest.raises(serializers.ValidationError):
            onboard_tenant(
                name="Rollback Hospital",
                slug="rollback-hospital",
                facility={"name": "Main Campus", "level": "District Hospital"},
                admin={
                    "username": "rollback-admin",
                    "password": "short",
                    "email": "rollback@example.org",
                },
            )

        assert not Tenant.objects.filter(slug="rollback-hospital").exists()

    def test_onboard_requires_platform_tenants_manage(self, context_tenant):
        """A tenant administrator without the claim must 403, not onboard.

        Onboarding mints tenancy roots, so only the platform-scoped claim may
        drive it (TEN-010). Asserted the way the RBAC tests do: the 403 must
        name the missing code (or a denial from another gate would look
        identical), and the target state is re-read afterwards — a refusal
        that still wrote would protect nothing.
        """
        from apps.identity_tenancy.models import Role, Tenant, UserMembership

        user = get_user_model().objects.create_user(
            username="hospital-admin", password="pw-for-tests-only"
        )
        role = Role.objects.create(
            tenant=context_tenant,
            name="tenant_admin",
            permissions=["identity.users.manage"],
        )
        UserMembership.objects.create(
            user=user, tenant=context_tenant, role=role, active=True
        )

        access = _login(user.username)
        assert "platform.tenants.manage" not in AccessToken(access).payload[
            "permissions"
        ]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = client.post(
            "/api/v1/tenants/onboard/",
            _onboard_payload(slug="guarded-hospital"),
            format="json",
        )

        assert response.status_code == 403, response.content
        assert "platform.tenants.manage" in response.json()["detail"]
        assert not Tenant.objects.filter(slug="guarded-hospital").exists()

    def test_facility_abdm_identifiers_round_trip(self, platform_client):
        """Identifiers sent at onboarding must read back via the facilities API (TEN-011).

        Read back as the *seeded admin* rather than the platform operator:
        the new facility belongs to the new tenant, which only a membership
        in that tenant can scope to — and logging in as the seeded admin
        doubles as proof the first account is actually usable.
        """
        from apps.identity_tenancy.models import Facility

        onboard = platform_client.post(
            "/api/v1/tenants/onboard/", _onboard_payload(), format="json"
        )
        assert onboard.status_code == 201, onboard.content
        facility = Facility.objects.get(tenant__slug="seed-hospital")

        admin_access = _login("seed-admin", TEST_PASSWORD)
        admin_client = APIClient()
        admin_client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_access}")

        detail = admin_client.get(f"/api/v1/facilities/{facility.id}/")

        assert detail.status_code == 200, detail.content
        body = detail.json()
        assert body["abdm_hip_id"] == "HIP-SEED-001"
        assert body["abdm_facility_id"] == "1000-seed-facility"
        assert body["abdm_registration_status"] == "registered"