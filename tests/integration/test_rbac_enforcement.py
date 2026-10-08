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
