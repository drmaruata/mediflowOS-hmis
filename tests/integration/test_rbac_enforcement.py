"""RBAC enforcement through the token's permission claim (TEN-004).

``TenantAwareTokenSerializer`` copies ``Role.permissions`` into the access
token's ``permissions`` claim, and ``RequirePermission`` is the class that
reads it back. These tests pin the denial half of that contract: an
authenticated caller whose claim lacks the code is refused with 403.

They exist because the pre-TEN-004 code performed no claim check anywhere —
any authenticated user could write memberships and read or mint tenancy
roots. The claim assertions in each test matter: the permission reads claims,
so a 403 from a token that never carried them would prove nothing about
which check fired.

``TestPlatformScopeConstraint`` covers the other half of the constraint: not
only *which* code a token carries, but *which role scope* may carry
platform-scope codes at all (platform scope = ``Role.tenant is None``).
"""
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT = uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture
def tenant():
    """The tenant the administrator belongs to."""
    from apps.identity_tenancy.models import Tenant

    return Tenant.objects.create(id=TENANT, name="Hospital C", slug="hospital-c")


@pytest.fixture
def tenant_admin(tenant):
    """A tenant-administrator whose role lacks the codes under test.

    ``require_mfa`` stays at its False default deliberately: if the role
    demanded MFA, the MFA gate would deny before the permission claim is ever
    evaluated, and the 403 below would prove nothing about RBAC.
    """
    from apps.identity_tenancy.models import Role, UserMembership

    user = get_user_model().objects.create_user(
        username="tenant-admin", password="pw-for-tests-only"
    )
    role = Role.objects.create(
        tenant=tenant,
        name="tenant-admin",
        # Has role-write but not membership-write nor platform tenant manage —
        # each test asserts which code is missing from its own token.
        permissions=["identity.roles.write"],
    )
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    return user


@pytest.fixture
def admin_access(tenant_admin):
    """A real access token for the tenant admin, issued through the API.

    Issued through ``/auth/token/`` rather than built by hand so the claims
    under test come from the same serializer production uses.
    """
    response = APIClient().post(
        "/api/v1/auth/token/",
        {"username": "tenant-admin", "password": "pw-for-tests-only"},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


@pytest.fixture
def admin_client(admin_access):
    """The tenant admin's authenticated client (bearer token, not a session)."""
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_access}")
    return client


class TestWriteClaimEnforcement:
    def test_membership_write_denied_without_permission(
        self, tenant, admin_access, admin_client
    ):
        """POST /memberships/ must 403 when the claim lacks membership-write.

        Pins TEN-004 against the old behaviour, where the viewset ran no
        claim check and the create succeeded for any authenticated user.
        """
        from apps.identity_tenancy.models import Role

        assert "identity.memberships.write" not in AccessToken(admin_access).payload[
            "permissions"
        ]

        assignee = get_user_model().objects.create_user(
            username="assignee", password="pw-for-tests-only"
        )
        role = Role.objects.get(tenant=tenant, name="tenant-admin")

        response = admin_client.post(
            "/api/v1/memberships/",
            {"user": str(assignee.id), "tenant": str(TENANT), "role": str(role.id)},
            format="json",
        )

        assert response.status_code == 403, response.content
        # The detail must name the missing code, or a 403 from some other gate
        # (MFA, tenant resolution) would look identical to a claim denial.
        # Message format: RequirePermission.message in permissions.py.
        assert "identity.memberships.write" in response.json()["detail"]

    def test_tenant_crud_denied_for_tenant_admin(self, admin_access, admin_client):
        """GET and POST /tenants/ must 403 without platform.tenants.manage.

        The tenancy root is platform-owned (TEN-010): a tenant administrator
        must be able to neither enumerate other hospitals' tenants nor mint
        new ones. Both verbs are asserted because the gate has to cover every
        method, not only writes — the list endpoint leaks the tenancy tree
        just as surely as create grows it.
        """
        assert (
            "platform.tenants.manage"
            not in AccessToken(admin_access).payload["permissions"]
        )

        list_response = admin_client.get("/api/v1/tenants/")
        assert list_response.status_code == 403, list_response.content

        create_response = admin_client.post(
            "/api/v1/tenants/",
            {"name": "Injected Hospital", "slug": "injected"},
            format="json",
        )
        assert create_response.status_code == 403, create_response.content


class TestPlatformScopeConstraint:
    """Platform scope is ``Role.tenant is None`` — enforced on every role write.

    The constraint was binding in the brief but had no code behind it: a
    tenant admin holding ``identity.roles.write`` could PATCH
    ``platform.tenants.manage`` onto their own role, re-login, and pass the
    ``TenantViewSet`` gate that enumerates and mints hospitals.
    ``RoleSerializer.validate_permissions`` is what now refuses that write.
    """

    def test_platform_claim_rejected_on_tenant_role_write(
        self, tenant, admin_access, admin_client
    ):
        """Role writes carrying ``platform.*`` codes must 4xx and change nothing.

        Both write paths are asserted: PATCH (the privilege-escalation path
        from the review) and POST, which creates a tenant-owned role because
        ``RoleViewSet`` is tenant-scoped. In both cases the stored role is
        checked afterwards — a rejection that still persisted the code, or
        created the role, would be no protection at all.
        """
        from apps.identity_tenancy.models import Role

        assert "identity.roles.write" in AccessToken(admin_access).payload["permissions"]
        role = Role.objects.get(tenant=tenant, name="tenant-admin")

        patch_response = admin_client.patch(
            f"/api/v1/roles/{role.id}/",
            {"permissions": ["identity.roles.write", "platform.tenants.manage"]},
            format="json",
        )
        assert patch_response.status_code == 400, patch_response.content
        role.refresh_from_db()
        assert role.permissions == ["identity.roles.write"]

        post_response = admin_client.post(
            "/api/v1/roles/",
            {"name": "escalated", "permissions": ["platform.tenants.manage"]},
            format="json",
        )
        assert post_response.status_code == 400, post_response.content
        assert not Role.objects.filter(tenant=tenant, name="escalated").exists()

    def test_platform_roles_excluded_from_tenant_list(self, admin_client):
        """A tenant's ``GET /roles/`` must never contain a platform-scoped role.

        Platform roles (``tenant is None``) belong to no tenant, so the
        tenant-scoped queryset must filter them out — otherwise a tenant admin
        could read the platform's role names and permission bundles. The
        admin's own tenant role must still be listed, so an empty list cannot
        pass for isolation.
        """
        from apps.identity_tenancy.models import Role

        platform_role = Role.objects.create(
            tenant=None,
            name="platform-superadmin",
            permissions=["platform.tenants.manage"],
        )

        response = admin_client.get("/api/v1/roles/")

        assert response.status_code == 200
        rows = response.json()["results"]
        assert str(platform_role.id) not in [row["id"] for row in rows]
        assert "platform-superadmin" not in [row["name"] for row in rows]
        assert "tenant-admin" in [row["name"] for row in rows]
