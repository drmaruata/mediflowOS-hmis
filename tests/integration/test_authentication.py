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
            "permissions": [
                "patient_registry.view_patient",
                "quality_os.view_capa",
                # TEN-007: the revoke endpoint is admin-only, and this role is
                # the tenant administrator whose membership the revoke tests use.
                "identity.break_glass.revoke",
            ],
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


def _totp_code(device):
    """The device's current valid code, the way an authenticator app computes it.

    django-otp's own TOTP helper rather than a hand-rolled one — the technique
    ``test_confirm_with_a_real_token_marks_the_device_usable`` established.
    """
    from django_otp.oath import TOTP

    return TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift).token()


def _confirmed_device(user):
    """A confirmed TOTP device for ``user``, plus a code that verifies right now."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    device = TOTPDevice.objects.create(user=user, name="Authenticator", confirmed=True)
    return device, _totp_code(device)


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

    def test_me_reports_the_mfa_gate_state_from_the_token_claim(self, users):
        """/auth/me/ must publish both MFA fields (UI-001).

        The SPA routes on this response before it renders the shell, so the
        unverified half must be visible, not just the role's requirement: a
        missing ``mfa_verified`` would force the client to guess from
        ``requires_mfa`` alone and every privileged user would be either
        stuck on or waved past the challenge.
        """
        from apps.identity_tenancy.tokens import TenantAwareTokenSerializer

        unverified = _authed("admin-a").get("/api/v1/auth/me/").json()
        assert unverified["requires_mfa"] is True
        assert unverified["mfa_verified"] is False

        # The verified half mirrors the token POST /auth/mfa/verify/ mints, the
        # same way TestMfaEnforcement mints it.
        refresh = TenantAwareTokenSerializer.get_token(users["admin"])
        refresh["mfa_verified"] = True
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        verified = client.get("/api/v1/auth/me/").json()
        assert verified["mfa_verified"] is True


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

    def test_confirm_completes_the_session(self, users):
        """Confirm mints the verified pair in the same request (TEN-006).

        One TOTP presentation proves both possession of the device and the
        second factor, so the session completes here instead of the client
        re-presenting the same code to verify — the library's timestep replay
        protection (``verify_token`` demands a step above ``last_t``) would
        refuse that second presentation.
        """
        from django_otp.plugins.otp_totp.models import TOTPDevice

        client = _authed("admin-a")
        device = client.post(
            "/api/v1/mfa-devices/", {"name": "Authenticator"}, format="json"
        ).json()
        totp_device = TOTPDevice.objects.get(
            name="Authenticator", user__username="admin-a"
        )

        response = client.post(
            f"/api/v1/mfa-devices/{device['persistent_id']}/confirm/",
            {"token": _totp_code(totp_device)},
            format="json",
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["status"] == "confirmed"
        claims = AccessToken(body["access"]).payload
        assert claims["mfa_verified"] is True
        assert claims["tenant_id"] == str(TENANT_A)
        assert claims["role"] == "tenant-admin"

    def test_confirm_refuses_a_deactivated_membership(self, users):
        """Confirm mints a pair now, so it must refuse an offboarded membership
        like every other issuance path (TEN-008) — and must not half-confirm
        the device on the way out.
        """
        from django_otp.plugins.otp_totp.models import TOTPDevice

        from apps.identity_tenancy.models import UserMembership

        client = _authed("admin-a")
        device = client.post(
            "/api/v1/mfa-devices/", {"name": "Authenticator"}, format="json"
        ).json()
        totp_device = TOTPDevice.objects.get(
            name="Authenticator", user__username="admin-a"
        )
        UserMembership.objects.filter(user=users["admin"]).update(active=False)

        response = client.post(
            f"/api/v1/mfa-devices/{device['persistent_id']}/confirm/",
            {"token": _totp_code(totp_device)},
            format="json",
        )

        assert response.status_code == 401, response.content
        assert "deactivated" in response.json()["detail"]
        totp_device.refresh_from_db()
        assert totp_device.confirmed is False


class TestMfaVerify:
    """POST /auth/mfa/verify/ — the missing half of TEN-006.

    Enrolment's confirm flips a device usable but authenticates nothing, so a
    privileged caller could never obtain a token the MFA gate accepts. Verify
    checks a code against a confirmed device and mints a fresh pair in the
    same request, the claim riding the refresh token so later rotations keep
    it — the reversion trap a verify that minted only an access token would
    fall into, since rotation copies claims from the login-time refresh token.
    """

    def test_verify_mints_a_pair_carrying_the_verified_claim(self, users):
        """A valid code returns a pair whose access carries the claim.

        The caller's login token is asserted first: requires_mfa true and
        mfa_verified false is exactly the caller MFARequiredIfConfigured
        denies, so the 200 below is also the permission opt-out pin — the
        endpoint must stay reachable by the unverified privileged user who
        needs it, the deliberate default replacement TOTPEnrolViewSet makes.
        """
        client = APIClient()
        access = _token(client, "admin-a")
        payload = AccessToken(access).payload
        assert payload["requires_mfa"] is True
        assert payload["mfa_verified"] is False
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        device, code = _confirmed_device(users["admin"])
        response = client.post(
            "/api/v1/auth/mfa/verify/", {"token": code}, format="json"
        )

        assert response.status_code == 200, response.content
        body = response.json()
        assert set(body) == {"access", "refresh"}
        claims = AccessToken(body["access"]).payload
        assert claims["mfa_verified"] is True
        assert claims["tenant_id"] == str(TENANT_A)
        assert claims["role"] == "tenant-admin"

    def test_the_verified_claim_survives_refresh_rotation(self, users):
        """The returned REFRESH mints verified access tokens after rotation.

        This is the design's whole point: rotation copies claims from the
        refresh token presented to it, and the login-time refresh token never
        saw the second factor. A pair whose refresh half carries the claim is
        the only shape that does not revert to unverified on the next refresh.
        """
        client = _authed("admin-a")
        device, code = _confirmed_device(users["admin"])
        pair = client.post(
            "/api/v1/auth/mfa/verify/", {"token": code}, format="json"
        ).json()

        refreshed = APIClient().post(
            "/api/v1/auth/token/refresh/", {"refresh": pair["refresh"]}, format="json"
        )

        assert refreshed.status_code == 200, refreshed.content
        rotated = AccessToken(refreshed.json()["access"]).payload
        assert rotated["mfa_verified"] is True
        assert rotated["tenant_id"] == str(TENANT_A)

    def test_wrong_code_is_rejected(self, users):
        client = _authed("admin-a")
        _confirmed_device(users["admin"])

        response = client.post(
            "/api/v1/auth/mfa/verify/", {"token": "000000"}, format="json"
        )

        assert response.status_code == 400
        assert response.json()["token"] == "Invalid token."

    def test_repeated_failures_are_throttled(self, users):
        """The device model's own throttling answers 429 — fail closed, so
        even a valid code is refused inside the backoff window."""
        client = _authed("admin-a")
        device, code = _confirmed_device(users["admin"])

        first = client.post(
            "/api/v1/auth/mfa/verify/", {"token": "000000"}, format="json"
        )
        assert first.status_code == 400

        second = client.post(
            "/api/v1/auth/mfa/verify/", {"token": code}, format="json"
        )
        assert second.status_code == 429
        assert second.json()["detail"] == "Too many attempts. Try again later."

    def test_without_a_confirmed_device_verify_refuses(self, users):
        """403 with a stable message, and not the mfa_required code — the
        caller is told to enrol, not to keep guessing."""
        from django_otp.plugins.otp_totp.models import TOTPDevice

        client = _authed("admin-a")
        TOTPDevice.objects.create(
            user=users["admin"], name="Authenticator", confirmed=False
        )

        response = client.post(
            "/api/v1/auth/mfa/verify/", {"token": "123456"}, format="json"
        )

        assert response.status_code == 403, response.content
        assert response.json()["detail"] == (
            "No confirmed authenticator is registered for your account. "
            "Enrol one at /api/v1/mfa-devices/ and confirm it."
        )

    def test_verify_requires_authentication(self, users):
        assert (
            APIClient()
            .post("/api/v1/auth/mfa/verify/", {"token": "123456"}, format="json")
            .status_code
            == 401
        )

    def test_verify_reopens_the_privileged_endpoints(self, users):
        """The end-to-end enforcement pin: the login-time token is still
        denied by MFARequiredIfConfigured while the pair verify mints is not."""
        client = APIClient()
        access = _token(client, "admin-a")
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        denied = client.get("/api/v1/patients/")
        assert denied.status_code == 403
        assert denied.json()["code"] == "mfa_required"

        device, code = _confirmed_device(users["admin"])
        pair = client.post(
            "/api/v1/auth/mfa/verify/", {"token": code}, format="json"
        ).json()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {pair['access']}")

        allowed = client.get("/api/v1/patients/")
        assert allowed.status_code == 200, allowed.content

    def test_deactivated_membership_cannot_verify(self, users):
        """An offboarded caller must not re-mint through verify (TEN-008)."""
        from apps.identity_tenancy.models import UserMembership

        client = _authed("admin-a")
        device, code = _confirmed_device(users["admin"])
        UserMembership.objects.filter(user=users["admin"]).update(active=False)

        response = client.post(
            "/api/v1/auth/mfa/verify/", {"token": code}, format="json"
        )

        assert response.status_code == 401, response.content
        assert "deactivated" in response.json()["detail"]


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


class TestBreakGlassAuditAndRevocation:
    """TEN-007: a grant is logged and raises the critical alert; a revoke ends it.

    The grant path in :class:`TestBreakGlass` already pinned reason, claim and
    resource-target checks. These tests pin the two things TEN-007 adds on
    top: the audit record (AUD-001) and the alert — ``BreakGlassView.post``
    must write an ``AuditEvent(action="break-glass")`` carrying the reason and
    a ``Notification(type="critical", title="Break-glass access granted")``
    for *every active* membership whose role demands MFA — and the revocation
    half of the interface: ``GET /break-glass/{id}/revoke/``, admin-only, sets
    ``revoked_at`` so the id no longer satisfies the grant check any
    downstream ``BREAK_GLASS_CLAIM`` verification would consult.
    """

    def _grant(self):
        """One successful break-glass grant as admin-a, returning the access id."""
        response = _authed("admin-a").post(
            "/api/v1/auth/break-glass/",
            {"resource_type": "patient", "resource_id": "UH-A-0001"},
            format="json",
            HTTP_X_BREAK_GLASS_REASON="Emergency admission, awaiting bed",
        )
        assert response.status_code == 201, response.content
        return uuid.UUID(response.json()["access_id"])

    def _admin_access(self, users):
        """An admin-a access token that satisfies the break-glass gates.

        The tenant-admin role demands MFA, so the ``mfa_verified`` claim is
        flagged on the issued token exactly the way
        ``test_mfa_verified_claim_unblocks_access`` does — the same claim
        ``POST /auth/mfa/verify/`` mints. Setting it directly keeps this pin
        independent of the verify endpoint. The permission claim comes from
        the role row, unchanged.
        """
        from apps.identity_tenancy.tokens import TenantAwareTokenSerializer

        refresh = TenantAwareTokenSerializer.get_token(users["admin"])
        refresh["mfa_verified"] = True
        return str(refresh.access_token)

    def _admin_client(self, users):
        """An admin-a client carrying :meth:`_admin_access`'s token."""
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self._admin_access(users)}")
        return client

    @staticmethod
    def _uuid_pk(pk):
        """The UUID spell of an auth.User integer pk as the UUID columns store it.

        ``auth.User`` keeps Django's integer primary key, while the audit and
        notification ``user_id`` columns are UUIDFields, so the int pk is
        coerced (``uuid.UUID(int=pk)``) when the row is written. Comparing
        against that spell — not the raw int — is what pins "the row records
        the requester".
        """
        return uuid.UUID(int=pk)

    def test_break_grant_writes_audit_and_alert(self, users):
        """A grant must land an AUD-001 row and a critical notification (TEN-007).

        The audit record is what keeps the emergency read reviewable; the
        alert is what makes it visible to the privileged peers who can stop
        it. TEN-007 says the alert reaches every active membership whose role
        demands MFA, so an active peer must receive one, while an inactive
        peer of the same role and a non-privileged clerk must not — the
        recipient count is what pins that rule.
        """
        from apps.audit.models import AuditEvent
        from apps.identity_tenancy.models import Role, Tenant, UserMembership
        from apps.platform.models import Notification

        mfa_peer = get_user_model().objects.create_user(
            username="mfa-peer", password="pw-for-tests-only"
        )
        inactive_peer = get_user_model().objects.create_user(
            username="inactive-peer", password="pw-for-tests-only"
        )
        admin_role = Role.objects.get(tenant_id=TENANT_A, name="tenant-admin")
        for member, active in ((mfa_peer, True), (inactive_peer, False)):
            UserMembership.objects.create(
                user=member,
                tenant=Tenant.objects.get(id=TENANT_A),
                role=admin_role,
                active=active,
            )

        response = _authed("admin-a").post(
            "/api/v1/auth/break-glass/",
            {"resource_type": "patient", "resource_id": "UH-A-0001"},
            format="json",
            HTTP_X_BREAK_GLASS_REASON="Emergency admission, awaiting bed",
        )

        assert response.status_code == 201, response.content
        event = AuditEvent.objects.get(action="break-glass")
        assert event.tenant_id == TENANT_A
        assert event.user_id == self._uuid_pk(users["admin"].id)
        # The audit row names the record that was opened, reason and all.
        assert event.entity_type == "patient"
        assert event.entity_id == "UH-A-0001"
        assert event.reason == "Emergency admission, awaiting bed"

        # Recipients: the requester herself plus the active peer — exactly the
        # two active require_mfa memberships. The inactive peer and the clerk
        # (role.require_mfa=False) get nothing.
        alerts = Notification.objects.filter(tenant_id=TENANT_A)
        assert alerts.count() == 2
        assert set(alerts.values_list("user_id", flat=True)) == {
            self._uuid_pk(users["admin"].id),
            self._uuid_pk(mfa_peer.id),
        }
        for alert in alerts:
            assert alert.type == "critical"
            assert alert.title == "Break-glass access granted"
            # Persisted before delivery: Task 22's consumer flips `delivered`.
            assert alert.persisted is True
            assert alert.delivered is False
            assert "Emergency admission, awaiting bed" in alert.body

    def test_break_grant_audit_row_joins_the_hash_chain(self, users):
        """The AUD-001 break-glass row must chain, or its UPDATE is invisible.

        A row written straight with ``AuditEvent.objects.create`` keeps the
        column's empty default, and ``verify_chain`` reads an empty hash as a
        pre-chain row it skips — so the grant would answer ``valid: true``
        while a hand-edited ``reason`` sat in the trail. AUD-002 chains every
        writer, break-glass included. This pins the grant's row as a chain
        member: it carries a digest, the verify pass covers it, and touching
        ``reason`` afterwards fails verification naming that row. The row is
        deliberately written behind an earlier event, because the oldest
        surviving chained row is the walk's re-anchor and its own digest is
        accepted by design (AUD-004's concession) — a first-ever grant is the
        one row whose in-place edit the chain cannot see, exactly as the
        purge's re-anchor pins describe.
        """
        from apps.audit.models import AuditEvent
        from apps.audit.services import append_event, verify_chain

        # An earlier event, so the grant is not the anchor row.
        append_event(
            tenant_id=TENANT_A,
            action="read",
            entity_type="registry.patient",
            entity_id="P-earlier",
        )
        self._grant()

        event = AuditEvent.objects.get(action="break-glass")
        assert event.hash_chain, (
            "the break-glass audit row must carry a chain digest (AUD-002)"
        )
        assert verify_chain(tenant_id=TENANT_A) == {
            "valid": True,
            "checked": 2,
            "first_bad": None,
        }

        event.reason = "a justification rewritten after the fact"
        event.save(update_fields=["reason"])
        tampered = verify_chain(tenant_id=TENANT_A)
        assert tampered["valid"] is False
        assert tampered["first_bad"] == str(event.id)

    def test_break_grant_without_reason_still_400(self, users):
        """No reason header, no grant — and no audit or alert row either.

        The audit and notification writes sit on the success path only. A
        reasonless request must not half-write a trail for an access that
        never started: the reason is the whole point of TEN-007's record.
        """
        from apps.audit.models import AuditEvent
        from apps.platform.models import Notification

        response = _authed("admin-a").post(
            "/api/v1/auth/break-glass/",
            {"resource_type": "patient", "resource_id": "UH-A-0001"},
            format="json",
        )

        assert response.status_code == 400
        assert "reason" in response.json()["detail"].lower()
        assert not AuditEvent.objects.filter(action="break-glass").exists()
        assert not Notification.objects.filter(type="critical").exists()

    def test_break_revoke_sets_revoked_at(self, users):
        """Revoking a grant stamps revoked_at; the id then fails the grant check.

        The endpoint is GET and admin-only (``identity.break_glass.revoke``):
        the claim is asserted on the token before the call, so a 200 cannot
        come from some other gate. The revoked_at stamp is read back from the
        database — the "still granted" predicate any BREAK_GLASS_CLAIM
        verification would consult flips from True to False.
        """
        from apps.identity_tenancy.models import BreakGlassAccess

        grant_id = self._grant()
        record = BreakGlassAccess.objects.get(pk=grant_id)
        assert record.revoked_at is None  # the grant-check predicate passes

        access = self._admin_access(users)
        assert "identity.break_glass.revoke" in AccessToken(access).payload["permissions"]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = client.get(f"/api/v1/break-glass/{grant_id}/revoke/")

        assert response.status_code == 200, response.content
        record.refresh_from_db()
        assert record.revoked_at is not None
        # A revoked id no longer satisfies the grant-check predicate.
        assert BreakGlassAccess.objects.get(pk=grant_id).revoked_at is not None

    def test_break_revoke_requires_revoke_permission(self, users):
        """A member without the claim must be refused revoke with a named 403.

        Clerk-a's role carries neither ``identity.break_glass.revoke`` nor
        ``require_mfa``, so the default gates cannot fire and the denial has
        to come from ``RequirePermission`` — whose detail names the missing
        code, distinguishing this 403 from the MFA gate's. The record is
        re-read afterwards: a refusal that still revoked would be no refusal.
        """
        from apps.identity_tenancy.models import BreakGlassAccess

        grant_id = self._grant()
        access = _token(APIClient(), "clerk-a")
        assert "identity.break_glass.revoke" not in AccessToken(access).payload[
            "permissions"
        ]
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = client.get(f"/api/v1/break-glass/{grant_id}/revoke/")

        assert response.status_code == 403, response.content
        assert "identity.break_glass.revoke" in response.json()["detail"]
        assert BreakGlassAccess.objects.get(pk=grant_id).revoked_at is None

    def test_break_revoke_without_mfa_verification_is_denied(self, users):
        """A password-only privileged token must not revoke a grant (TEN-006).

        ``BreakGlassViewSet`` must inherit the project default gates instead of
        replacing them wholesale the way a view that declares its own
        ``permission_classes`` does. Admin-a's role demands MFA *and* carries
        ``identity.break_glass.revoke``, so with only IsAuthenticated and the
        appended claim check a stolen password would reach the write: the
        ``MFARequiredIfConfigured`` default must deny first, with the
        ``mfa_required`` code the frontend routes on, and the grant must stay
        open. The negative path deliberately mints the token the way
        ``test_mfa_claim_blocks_unverified_session`` does — no
        ``mfa_verified`` claim — unlike :meth:`_admin_access`.
        """
        from apps.identity_tenancy.models import BreakGlassAccess

        grant_id = self._grant()
        client = APIClient()
        access = _token(client, "admin-a")
        payload = AccessToken(access).payload
        assert payload["requires_mfa"] is True
        assert payload["mfa_verified"] is False
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        response = client.get(f"/api/v1/break-glass/{grant_id}/revoke/")

        assert response.status_code == 403, response.content
        assert response.json()["code"] == "mfa_required"
        assert BreakGlassAccess.objects.get(pk=grant_id).revoked_at is None

    def test_break_revoke_of_foreign_tenant_grant_404s(self, users):
        """Another hospital's grant id must not resolve to a revocable row.

        The detail lookup is tenant-scoped like every other tenant-owned
        queryset: a foreign id answers 404, never 403 and never a mutation —
        the existence of another tenant's grant is not disclosed, and the
        request cannot touch the foreign row (TEN-002).
        """
        from apps.identity_tenancy.models import BreakGlassAccess

        foreign = BreakGlassAccess.objects.create(
            tenant_id=TENANT_B,
            user_id=users["b"].id,
            resource_type="patient",
            resource_id="UH-B-0001",
            reason="Foreign emergency",
        )

        response = self._admin_client(users).get(
            f"/api/v1/break-glass/{foreign.id}/revoke/"
        )

        assert response.status_code == 404, response.content
        foreign.refresh_from_db()
        assert foreign.revoked_at is None


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
        # MFA claims are in this tuple deliberately: rotation dropping
        # requires_mfa would fail open (the gate stops denying), and dropping
        # mfa_verified would fail closed for privileged roles — either way the
        # contract in common/mfa.py's docstring ("survive refresh") would be
        # silently broken.
        for claim in (
            "tenant_id",
            "facility_id",
            "role",
            "permissions",
            "requires_mfa",
            "mfa_verified",
        ):
            assert new_access.payload[claim] == original.payload[claim], (
                f"refresh dropped the {claim} claim; the rotated token no longer "
                "carries what was issued — tenant scope or MFA state is lost"
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

        The claim is set by hand rather than obtained from
        ``POST /auth/mfa/verify/`` so this pin exercises the permission alone,
        in isolation from the endpoint's availability — it pins that the
        permission denies only when ``mfa_verified`` is absent, not for every
        ``requires_mfa`` role. ``TestMfaVerify`` pins the endpoint's own
        minting.
        """
        from apps.identity_tenancy.tokens import TenantAwareTokenSerializer

        refresh = TenantAwareTokenSerializer.get_token(users["admin"])
        refresh["mfa_verified"] = True
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

        response = client.get("/api/v1/patients/")

        assert response.status_code == 200, response.content
