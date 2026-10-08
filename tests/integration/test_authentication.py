"""Authentication, tenant binding, MFA and break-glass.

The central test here is :class:`TestTenantComesFromTheToken`. Before step 7 the
tenant was read from the ``X-Tenant-Id`` header for every request, including
authenticated ones, so any logged-in user could read another hospital's data by
changing a header - and because the same header fed the row level security
policy, the database filtered for the caller's chosen tenant. The tenant now
lives in the signed token and overrides the header.
"""
import uuid

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000a1")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000b2")


@pytest.fixture
def tenants():
    from apps.identity_tenancy.models import Tenant

    for tenant_id, name, slug in (
        (TENANT_A, "Hospital A", "hospital-a"),
        (TENANT_B, "Hospital B", "hospital-b"),
    ):
        Tenant.objects.get_or_create(
            id=tenant_id, defaults={"name": name, "slug": slug}
        )


@pytest.fixture
def roles(tenants):
    from apps.identity_tenancy.models import Role, Tenant

    clerk, _ = Role.objects.get_or_create(
        tenant=Tenant.objects.get(id=TENANT_A),
        name="clerk",
        defaults={"permissions": ["patient_registry.view_patient"]},
    )
    admin_a, _ = Role.objects.get_or_create(
        tenant=Tenant.objects.get(id=TENANT_A),
        name="tenant-admin",
        defaults={
            "permissions": ["patient_registry.view_patient", "quality_os.view_capa"],
            "require_mfa": True,
            "allows_break_glass": True,
        },
    )
    Role.objects.get_or_create(
        tenant=Tenant.objects.get(id=TENANT_B),
        name="clerk",
        defaults={"permissions": ["patient_registry.view_patient"]},
    )
    return {"clerk": clerk, "admin": admin_a}


@pytest.fixture
def users(roles):
    """One user per tenant, each holding a single membership."""
    from apps.identity_tenancy.models import Tenant, UserMembership

    User = get_user_model()
    created = {}
    for label, username, tenant_id, role_key in (
        ("a", "clerk-a", TENANT_A, "clerk"),
        ("b", "clerk-b", TENANT_B, "clerk"),
        ("admin", "admin-a", TENANT_A, "admin"),
    ):
        user = User.objects.create_user(
            username=username, password="pw-for-tests-only"
        )
        UserMembership.objects.create(
            user=user,
            tenant=Tenant.objects.get(id=tenant_id),
            role=roles[role_key],
        )
        created[label] = user
    return created


def _token(client, username, password="pw-for-tests-only"):
    response = client.post(
        "/api/v1/auth/token/",
        {"username": username, "password": password},
        format="json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


def _authed(username, tenants_header=None):
    client = APIClient()
    # credentials() replaces the credential set rather than merging, so both
    # headers have to be supplied in one call.
    extra = {"HTTP_X_TENANT_ID": str(tenants_header)} if tenants_header else {}
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {_token(client, username)}", **extra)
    return client


class TestTokenIssuance:
    def test_token_carries_tenant_role_and_permissions(self, users):
        client = APIClient()
        response = client.post(
            "/api/v1/auth/token/",
            {"username": "clerk-a", "password": "pw-for-tests-only"},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert body["tenant_id"] == str(TENANT_A)
        assert body["role"] == "clerk"
        assert "patient_registry.view_patient" in body["permissions"]

    def test_wrong_password_is_rejected_without_leaking_why(self, users):
        response = APIClient().post(
            "/api/v1/auth/token/",
            {"username": "clerk-a", "password": "wrong"},
            format="json",
        )

        assert response.status_code == 401
        assert "password" not in response.json().get("detail", "").lower() or (
            "incorrect" in response.json().get("detail", "").lower()
        )

    def test_privileged_role_is_flagged_for_mfa(self, users):
        response = APIClient().post(
            "/api/v1/auth/token/",
            {"username": "admin-a", "password": "pw-for-tests-only"},
            format="json",
        )

        assert response.json()["requires_mfa"] is True

    def test_me_endpoint_reports_resolved_tenant(self, users):
        response = _authed("clerk-a").get("/api/v1/auth/me/")

        assert response.status_code == 200
        assert response.json()["tenant_id"] == str(TENANT_A)


class TestTenantComesFromTheToken:
    """The regression this step exists to close."""

    def test_header_cannot_override_the_token_tenant(self, users):
        """An authenticated clerk cannot borrow another tenant by header."""
        response = _authed("clerk-a", tenants_header=TENANT_B).get(
            "/api/v1/auth/me/"
        )

        assert response.status_code == 200
        assert response.json()["tenant_id"] == str(TENANT_A), (
            "the X-Tenant-Id header overrode the signed token"
        )

    def test_header_override_cannot_read_another_tenants_data(self, users):
        """The override must not leak rows, not merely report the right tenant."""
        from apps.patient_registry.models import Patient

        Patient.objects.create(
            id=uuid.uuid4(),
            tenant_id=TENANT_B,
            uhid="UH-B-0001",
            demographics={"name": "Patient B"},
        )

        response = _authed("clerk-a", tenants_header=TENANT_B).get("/api/v1/patients/")

        assert response.status_code == 200
        assert response.json()["results"] == []

    def test_a_user_of_tenant_b_sees_only_its_own_rows(self, users):
        from apps.patient_registry.models import Patient

        Patient.objects.create(
            id=uuid.uuid4(), tenant_id=TENANT_A, uhid="UH-A-0001", demographics={}
        )
        Patient.objects.create(
            id=uuid.uuid4(), tenant_id=TENANT_B, uhid="UH-B-0001", demographics={}
        )

        rows = _authed("clerk-b").get("/api/v1/patients/").json()["results"]

        assert [row["uhid"] for row in rows] == ["UH-B-0001"]

    def test_user_without_membership_resolves_no_tenant(self, users):
        """A tenant-less token must fail closed, not fall back to the header."""
        get_user_model().objects.create_user(username="orphan", password="pw-x")
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {_token(client, 'orphan', 'pw-x')}",
            HTTP_X_TENANT_ID=str(TENANT_A),
        )

        me = client.get("/api/v1/auth/me/")
        assert me.json()["tenant_id"] is None

        listing = client.get("/api/v1/patients/")
        assert listing.json()["results"] == []


class TestSecondFactor:
    def test_totp_device_starts_unconfirmed(self, users):
        response = _authed("admin-a").post(
            "/api/v1/mfa-devices/", {"name": "Authenticator"}, format="json"
        )

        assert response.status_code == 201
        assert response.json()["confirmed"] is False
        assert response.json()["config_url"].startswith("otpauth://totp/")

    def test_confirm_requires_a_valid_token(self, users):
        client = _authed("admin-a")
        device = client.post(
            "/api/v1/mfa-devices/", {"name": "Authenticator"}, format="json"
        ).json()

        bad = client.post(
            f"/api/v1/mfa-devices/{device['persistent_id']}/confirm/",
            {"token": "000000"},
            format="json",
        )
        assert bad.status_code == 400

    def test_confirm_with_a_real_token_marks_the_device_usable(self, users):
        from django_otp.oath import TOTP
        from django_otp.plugins.otp_totp.models import TOTPDevice

        client = _authed("admin-a")
        device = client.post(
            "/api/v1/mfa-devices/", {"name": "Authenticator"}, format="json"
        ).json()

        totp_device = TOTPDevice.objects.get(
            name="Authenticator", user__username="admin-a"
        )
        # Generate the current code the same way an authenticator app does,
        # using django-otp's own TOTP helper rather than a hand-rolled one.
        totp = TOTP(
            totp_device.bin_key,
            totp_device.step,
            totp_device.t0,
            totp_device.digits,
            totp_device.drift,
        )

        response = client.post(
            f"/api/v1/mfa-devices/{device['persistent_id']}/confirm/",
            {"token": totp.token()},
            format="json",
        )

        assert response.status_code == 200
        totp_device.refresh_from_db()
        assert totp_device.confirmed is True


class TestBreakGlass:
    def test_requires_break_glass_permission(self, users):
        response = _authed("clerk-a").post(
            "/api/v1/auth/break-glass/",
            {"resource_type": "patient", "resource_id": "UH-A-0001"},
            format="json",
            HTTP_X_BREAK_GLASS_REASON="Emergency admission",
        )

        assert response.status_code == 403

    def test_refuses_without_a_reason(self, users):
        response = _authed("admin-a").post(
            "/api/v1/auth/break-glass/",
            {"resource_type": "patient", "resource_id": "UH-A-0001"},
            format="json",
        )

        assert response.status_code == 400
        assert "reason" in response.json()["detail"].lower()

    def test_blank_reason_is_refused(self, users):
        """Whitespace is not a reason."""
        response = _authed("admin-a").post(
            "/api/v1/auth/break-glass/",
            {"resource_type": "patient", "resource_id": "UH-A-0001"},
            format="json",
            HTTP_X_BREAK_GLASS_REASON="   ",
        )

        assert response.status_code == 400

    def test_grants_and_records_the_access(self, users):
        from apps.identity_tenancy.models import BreakGlassAccess

        response = _authed("admin-a").post(
            "/api/v1/auth/break-glass/",
            {"resource_type": "patient", "resource_id": "UH-A-0001"},
            format="json",
            HTTP_X_BREAK_GLASS_REASON="Emergency admission, awaiting bed",
        )

        assert response.status_code == 201
        record = BreakGlassAccess.objects.get()
        assert record.tenant_id == TENANT_A
        assert record.reason == "Emergency admission, awaiting bed"
        assert record.resource_id == "UH-A-0001"

    def test_requires_resource_target(self, users):
        response = _authed("admin-a").post(
            "/api/v1/auth/break-glass/",
            {},
            format="json",
            HTTP_X_BREAK_GLASS_REASON="Emergency",
        )

        assert response.status_code == 400


class TestMfaDeviceManagement:
    def test_requires_authentication(self, users):
        assert APIClient().get("/api/v1/mfa-devices/").status_code in (401, 403)

    def test_lists_only_the_callers_devices(self, users):
        _authed("admin-a").post("/api/v1/mfa-devices/", {"name": "Mine"}, format="json")

        listed = _authed("admin-a").get("/api/v1/mfa-devices/").json()
        names = [device["name"] for device in listed]

        assert names == ["Mine"]

    def test_device_can_be_removed(self, users):
        client = _authed("admin-a")
        device = client.post(
            "/api/v1/mfa-devices/", {"name": "Spare"}, format="json"
        ).json()

        assert client.delete(
            f"/api/v1/mfa-devices/{device['persistent_id']}/"
        ).status_code == 204
        assert client.get("/api/v1/mfa-devices/").json() == []


class TestTokenRefresh:
    """Refresh must carry the tenant context forward, then burn the old token."""

    def test_refresh_preserves_tenant_claims(self, users):
        """Refresh must re-bind tenant/facility/role claims — a bare refresh that
        drops them would silently un-scope every follow-up request (TEN-006)."""
        client = APIClient()
        issued = client.post(
            "/api/v1/auth/token/",
            {"username": "clerk-a", "password": "pw-for-tests-only"},
            format="json",
        ).json()
        original = AccessToken(issued["access"])

        refreshed = client.post(
            "/api/v1/auth/token/refresh/",
            {"refresh": issued["refresh"]},
            format="json",
        )

        assert refreshed.status_code == 200, refreshed.content
        new_access = AccessToken(refreshed.json()["access"])
        for claim in ("tenant_id", "facility_id", "role", "permissions"):
            assert new_access.payload[claim] == original.payload[claim], (
                f"refresh dropped the {claim} claim; every request made with the "
                "new access token would lose its tenant scope"
            )

    def test_old_refresh_token_rejected_after_rotation(self, users):
        """A consumed refresh token must be dead, not merely expired.

        ``BLACKLIST_AFTER_ROTATION`` silently no-ops while the blacklist app is
        absent from ``INSTALLED_APPS`` (SimpleJWT catches the missing method),
        so replaying the pre-refresh token returning 401 is what proves the app
        is actually installed and migrated (TEN-006).
        """
        client = APIClient()
        issued = client.post(
            "/api/v1/auth/token/",
            {"username": "clerk-a", "password": "pw-for-tests-only"},
            format="json",
        ).json()
        refresh = issued["refresh"]

        rotated = client.post(
            "/api/v1/auth/token/refresh/", {"refresh": refresh}, format="json"
        )
        assert rotated.status_code == 200, rotated.content
        assert rotated.json()["refresh"] != refresh

        replay = client.post(
            "/api/v1/auth/token/refresh/", {"refresh": refresh}, format="json"
        )
        assert replay.status_code == 401, (
            "the blacklisted refresh token was accepted again — the token_blacklist "
            "app is not doing its job"
        )


class TestMfaEnforcement:
    """TEN-006: the second factor is enforced through the signed token claims."""

    @pytest.mark.parametrize("endpoint", ["/api/v1/patients/", "/api/v1/roles/"])
    def test_mfa_claim_blocks_unverified_session(self, users, endpoint):
        """requires_mfa without mfa_verified must deny an authenticated endpoint.

        The token's claims are asserted first: the permission reads claims, so
        a token that never carried them would make the 403 below prove nothing
        about which check fired.
        """
        client = APIClient()
        access = _token(client, "admin-a")
        payload = AccessToken(access).payload
        assert payload["requires_mfa"] is True
        assert payload["mfa_verified"] is False

        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        response = client.get(endpoint)

        assert response.status_code == 403, response.content
        assert response.json()["code"] == "mfa_required"

    def test_mfa_verified_claim_unblocks_access(self, users):
        """The other half of the gate: a token that proves the factor passes.

        The claim is set by hand because the backend has no MFA-verify
        endpoint yet (``POST /auth/mfa/verify`` in the UI spec) — this is
        exactly the token that endpoint will mint, and it pins that the
        permission denies only when ``mfa_verified`` is absent, not for every
        ``requires_mfa`` role.
        """
        from apps.identity_tenancy.tokens import TenantAwareTokenSerializer

        refresh = TenantAwareTokenSerializer.get_token(users["admin"])
        refresh["mfa_verified"] = True
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = client.get("/api/v1/patients/")

        assert response.status_code == 200, response.content
