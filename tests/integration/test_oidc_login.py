"""The OIDC ID-token exchange (INT-009).

The exchange's root of trust is the IdP's signature, so every test here runs
against real signature verification: a local RSA key stands in for the IdP's
signing key and its JWKS is served from a stubbed fetcher, which pins the
endpoint's behaviour with no network and no IdP. The stub replaces
``apps.identity_tenancy.oidc.fetch_jwks`` — the one seam the module exposes for
exactly this purpose — so the key selection, signature, issuer, audience and
expiry checks all run for real on every request below.

What each refusal family pins:

* **501 before any work** — an unconfigured deployment answers 501 with a
  structured body before the request body is parsed, so no garbage token can
  make it do cryptographic work or touch a row.
* **401** — anything about the token itself: foreign signature, wrong
  audience, expired, or carrying no ``exp`` at all (a token with no expiry
  would otherwise verify forever).
* **403 with one stable message** — a *verified* identity that may not log in
  to the bound tenant. Every condition below reads identically to the caller,
  so the endpoint cannot be used to enumerate accounts or probe which tenants
  exist.
* **The decode pin** — the returned access token carries the bound tenant in
  its signed claims, exactly as the password flow's does, because the same
  serializer issued it.
"""
import base64
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.identity_tenancy.oidc import NO_ACCOUNT_MESSAGE, NO_TENANT_MESSAGE

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

EXCHANGE_URL = "/api/v1/auth/oidc/"
ISSUER = "https://idp.example.test"
AUDIENCE = "mediflow-hmis"
JWKS_URI = "https://idp.example.test/.well-known/jwks.json"
KID = "integration-test-key"

# Fixed ids, not random ones: `active_membership` orders by role-tenant id, so
# a deterministic "the account's active membership sits on the other tenant"
# (TENANT_OTHER sorts above TENANT_BOUND descending) needs comparable values.
TENANT_BOUND = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000a1")
TENANT_OTHER = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000b2")


def _b64url_uint(value):
    """A JWK ``n``/``e`` integer as the base64url string a JWKS carries."""
    length = (value.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(value.to_bytes(length, "big")).decode().rstrip("=")


@pytest.fixture(scope="module")
def signing_key():
    """The IdP's signing key, generated in-process so the suite needs no IdP."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def foreign_key():
    """A key the JWKS never publishes: a token it signs must fail verification."""
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def jwks(signing_key):
    """The IdP's published key set, served from the stub fetcher."""
    numbers = signing_key.public_key().public_numbers()
    return {"keys": [{
        "kty": "RSA", "alg": "RS256", "use": "sig", "kid": KID,
        "n": _b64url_uint(numbers.n), "e": _b64url_uint(numbers.e),
    }]}


@pytest.fixture
def configured(settings, monkeypatch, jwks):
    """The deployment's OIDC settings, with the JWKS served from the stub."""
    from apps.identity_tenancy import oidc

    settings.OIDC_ISSUER = ISSUER
    settings.OIDC_AUDIENCE = AUDIENCE
    settings.OIDC_JWKS_URI = JWKS_URI
    settings.OIDC_JIT_PROVISION = False
    monkeypatch.setattr(oidc, "fetch_jwks", lambda uri: jwks)
    return settings


@pytest.fixture
def tenant():
    """The tenant the ID token's slug claim names."""
    from apps.identity_tenancy.models import Tenant

    return Tenant.objects.get_or_create(
        id=TENANT_BOUND, defaults={"name": "Hospital SSO", "slug": "hospital-sso"}
    )[0]


@pytest.fixture
def other_tenant():
    from apps.identity_tenancy.models import Tenant

    return Tenant.objects.get_or_create(
        id=TENANT_OTHER, defaults={"name": "Hospital B", "slug": "hospital-b"}
    )[0]


@pytest.fixture
def clerk(tenant):
    """A staff account with one active membership on the bound tenant."""
    from apps.identity_tenancy.models import Role, UserMembership

    user = get_user_model().objects.create_user(
        username="idp-sub-1", password="pw-for-tests-only", email="clerk@hospital.test"
    )
    role = Role.objects.create(
        tenant=tenant, name="reception", permissions=["patient_registry.view_patient"]
    )
    UserMembership.objects.create(user=user, tenant=tenant, role=role, active=True)
    return user


def _id_token(key, claims=None):
    """A signed ID token; ``claims`` merge over the valid defaults (None drops one)."""
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "idp-sub-1",
        "email": "clerk@hospital.test",
        "iat": now,
        "exp": now + 300,
        "tenant": "hospital-sso",
    }
    for claim, value in (claims or {}).items():
        if value is None:
            payload.pop(claim, None)
        else:
            payload[claim] = value
    return jwt.encode(payload, key, algorithm="RS256", headers={"kid": KID})


def _post(id_token):
    return APIClient().post(EXCHANGE_URL, {"id_token": id_token}, format="json")


class TestUnconfiguredDeployment:
    def test_answers_501_with_a_structured_body(self):
        response = _post("header.payload.signature")

        assert response.status_code == 501
        body = response.json()
        assert body["status"] == "not_configured"
        assert "OIDC_ISSUER" in body["detail"]

    def test_the_501_precedes_any_work(self):
        """No parse, no crypto, no rows: a body with no id_token at all is
        answered by the configuration check, not by validation."""
        response = APIClient().post(EXCHANGE_URL, {}, format="json")

        assert response.status_code == 501


class TestTheExchange:
    def test_a_valid_token_returns_the_pair_and_binds_the_named_tenant(
        self, configured, signing_key, tenant, clerk
    ):
        response = _post(_id_token(signing_key))

        assert response.status_code == 200, response.content
        body = response.json()
        assert body["refresh"]
        assert body["access"]
        assert body["tenant_id"] == str(tenant.id)
        assert body["role"] == "reception"
        # The decode pin: the issued access token carries the bound tenant in
        # its signed claims, exactly as the password flow's does.
        claims = AccessToken(body["access"]).payload
        assert claims["tenant_id"] == str(tenant.id)
        assert "patient_registry.view_patient" in claims["permissions"]

    def test_wrong_audience_is_refused(self, configured, signing_key, tenant, clerk):
        response = _post(_id_token(signing_key, {"aud": "some-other-client"}))

        assert response.status_code == 401

    def test_expired_token_is_refused(self, configured, signing_key, tenant, clerk):
        response = _post(_id_token(signing_key, {"exp": int(time.time()) - 3600}))

        assert response.status_code == 401

    def test_a_token_without_expiry_is_refused(self, configured, signing_key, tenant, clerk):
        """Expiry is verified before any local effect: a token carrying no
        ``exp`` would otherwise verify forever."""
        response = _post(_id_token(signing_key, {"exp": None}))

        assert response.status_code == 401

    def test_a_signature_from_an_unpublished_key_is_refused(
        self, configured, foreign_key, tenant, clerk
    ):
        response = _post(_id_token(foreign_key))

        assert response.status_code == 401

    def test_a_token_without_a_tenant_claim_is_refused(
        self, configured, signing_key, tenant, clerk
    ):
        response = _post(_id_token(signing_key, {"tenant": None}))

        assert response.status_code == 403
        assert response.json()["detail"] == NO_TENANT_MESSAGE

    def test_an_unresolvable_tenant_claim_is_refused(
        self, configured, signing_key, tenant, clerk
    ):
        response = _post(_id_token(signing_key, {"tenant": "no-such-hospital"}))

        assert response.status_code == 403
        assert response.json()["detail"] == NO_TENANT_MESSAGE

    def test_an_unknown_identity_is_refused_while_jit_is_off(
        self, configured, signing_key, tenant, clerk
    ):
        claims = {"sub": "idp-sub-2", "email": "stranger@hospital.test"}
        response = _post(_id_token(signing_key, claims))

        assert response.status_code == 403
        assert response.json()["detail"] == NO_ACCOUNT_MESSAGE
        assert not get_user_model().objects.filter(email="stranger@hospital.test").exists()

    def test_a_member_of_another_tenant_is_refused(
        self, configured, signing_key, tenant, other_tenant, clerk
    ):
        """A login is not a role-granting event: an account holding no
        membership on the bound tenant gets nothing, and no row is created."""
        from apps.identity_tenancy.models import Role, UserMembership

        outsider = get_user_model().objects.create_user(
            username="idp-sub-outsider", password="pw-for-tests-only",
            email="elsewhere@hospital.test",
        )
        UserMembership.objects.create(
            user=outsider, tenant=other_tenant,
            role=Role.objects.create(tenant=other_tenant, name="clerk-b"),
            active=True,
        )

        response = _post(_id_token(signing_key, {
            "sub": "idp-sub-outsider", "email": "elsewhere@hospital.test",
        }))

        assert response.status_code == 403
        assert response.json()["detail"] == NO_ACCOUNT_MESSAGE
        assert not UserMembership.objects.filter(user=outsider, tenant=tenant).exists()

    def test_an_account_whose_active_membership_is_elsewhere_is_refused(
        self, configured, signing_key, tenant, other_tenant, clerk
    ):
        """The pair binds exactly the tenant the sign-on named: this account
        holds active memberships on the bound tenant and on another, and its
        password-flow token would bind the other — so the exchange refuses
        rather than issue a token for a tenant the token did not name."""
        from apps.identity_tenancy.models import Role, UserMembership

        UserMembership.objects.create(
            user=clerk, tenant=other_tenant,
            role=Role.objects.create(tenant=other_tenant, name="clerk-b"),
            active=True,
        )

        response = _post(_id_token(signing_key))

        assert response.status_code == 403
        assert response.json()["detail"] == NO_ACCOUNT_MESSAGE


class TestJustInTimeProvisioning:
    def test_first_sign_on_provisions_a_least_privilege_account(
        self, configured, signing_key, tenant
    ):
        configured.OIDC_JIT_PROVISION = True
        claims = {"sub": "idp-newcomer", "email": "newcomer@hospital.test"}

        first = _post(_id_token(signing_key, claims))

        assert first.status_code == 200, first.content
        user = get_user_model().objects.get(email="newcomer@hospital.test")
        # An OIDC identity must never be replayable as a password login.
        assert user.has_usable_password() is False
        membership = user.memberships.get(tenant=tenant)
        assert membership.active is True
        assert membership.role.name == "SSO User"
        assert membership.role.permissions == []
        # The provisioned account's pair binds the named tenant too.
        assert AccessToken(first.json()["access"]).payload["tenant_id"] == str(tenant.id)

        second = _post(_id_token(signing_key, claims))
        assert second.status_code == 200, second.content
        assert get_user_model().objects.filter(email="newcomer@hospital.test").count() == 1

    def test_a_privileged_role_named_for_sso_is_not_adopted(
        self, configured, signing_key, tenant
    ):
        """A tenant-authored "SSO User" role holding permissions would make
        every login a role grant; the exchange refuses instead, and the
        rollback leaves no half-provisioned account behind."""
        from apps.identity_tenancy.models import Role

        configured.OIDC_JIT_PROVISION = True
        Role.objects.create(
            tenant=tenant, name="SSO User", permissions=["identity.view_user"]
        )

        response = _post(_id_token(signing_key, {
            "sub": "idp-newcomer", "email": "newcomer@hospital.test",
        }))

        assert response.status_code == 403
        assert not get_user_model().objects.filter(email="newcomer@hospital.test").exists()
